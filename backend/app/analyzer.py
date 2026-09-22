"""Фоновый AI-анализ разговоров (v2).

Раз в ANALYZE_INTERVAL секунд берёт самую старую «пачку» новых реплик устройства
(до MAX_BLOCK_LINES, обрезанную по первой большой паузе), и если она завершена
(тишина ≥ CONV_SETTLE_MINUTES) — отдаёт Mistral, который САМ делит её на эпизоды
(консультация / отвлечение / внутреннее / прочее), классифицирует, оценивает и
чистит транскрипт. Каждый эпизод сохраняется строкой в conversations.

Обрабатываем строго по времени; на ошибке анализа не двигаем границу (повтор в
следующий проход). Граница = max(Conversation.end_ts) на устройство.
"""
import os
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import func
from fastapi.concurrency import run_in_threadpool

from . import config, mistral, vision, realtime, prompts
from .db import SessionLocal
from .models import Transcript, Conversation

logger = logging.getLogger("monitoring.analyzer")

_MIN_CHARS = 40
# Ниже этого объёма речи в окне эпизода оценку не ставим — см. _store.
MIN_EPISODE_CHARS = int(os.environ.get("MIN_EPISODE_CHARS", 120))


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _to_ms(dt: datetime) -> int:
    return int(_as_utc(dt).timestamp() * 1000)


def _from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _first_gap_cut(lines: list, gap: timedelta) -> list:
    """Обрезаем пачку до первого разрыва больше gap — чтобы не смешивать далёкие эпизоды."""
    out = [lines[0]]
    for prev, nxt in zip(lines, lines[1:]):
        if _as_utc(nxt.start_ts) - _as_utc(prev.end_ts) > gap:
            break
        out.append(nxt)
    return out


def _embed_text(ep: dict) -> str:
    """Текст эпизода для семантического поиска: заголовок + сводка + моменты + реплики."""
    parts = [ep.get("title", ""), ep.get("summary", "")]
    parts += [h.get("text", "") for h in ep.get("highlights", [])]
    parts += [c.get("text", "") for c in ep.get("clean", [])]
    return " ".join(p for p in parts if p)[:6000]


def _raw_chars(lines: list[dict], start_ms: int, end_ms: int) -> int:
    """Сколько РЕАЛЬНОЙ распознанной речи попало в окно эпизода."""
    return sum(len(l["text"]) for l in lines if start_ms <= l["ms"] <= end_ms)


def _store(db, device_id: str, episodes: list[dict], chunk_start: datetime, chunk_end: datetime,
           screens: list[dict] | None = None, vecs: list | None = None,
           lines: list[dict] | None = None) -> int:
    """Сохраняем эпизоды пачки; гарантируем, что граница дойдёт до конца пачки.

    Только запись — эмбеддинги считаются заранее (vecs), чтобы не держать соединение
    с БД во время сетевого вызова."""
    screens = screens or []
    lines = lines or []
    convs: list[Conversation] = []
    for i, ep in enumerate(episodes):
        # Кадры экрана, попавшие во временной промежуток эпизода → метка «что открыто».
        ep_screens = [s for s in screens if ep["start_ms"] <= s["t"] <= ep["end_ms"]]

        # Защита от оценок по выдуманному тексту: если речи в окне эпизода почти не
        # было, модель склонна дописать «правдоподобный» диалог. Такие эпизоды
        # сохраняем, но БЕЗ оценок — иначе сотрудника накажут за разговор, которого
        # не было. Порог мягкий: короткая, но настоящая реплика оценку не теряет.
        raw = _raw_chars(lines, ep["start_ms"], ep["end_ms"])
        thin = raw < MIN_EPISODE_CHARS
        if thin and (ep["score"] is not None or ep["criteria"]):
            logger.info("Эпизод %s %s..%s: речи всего %d симв. — снимаю оценку",
                        device_id, ep["start_ms"], ep["end_ms"], raw)
            ep["score"] = None
            ep["seller_score"] = None
            ep["criteria"] = {}

        data = {
            "title": ep["title"], "participants": ep["participants"], "criteria": ep["criteria"],
            "seller_score": ep["seller_score"], "sentiment": ep.get("sentiment"),
            "flags": ep["flags"], "clean": ep["clean"],
            "screen": vision.dominant_label(ep_screens), "screens": ep_screens,
            "raw_chars": raw, "thin": thin,
        }
        vec = vecs[i] if (vecs and i < len(vecs)) else None
        c = Conversation(
            device_id=device_id, start_ts=_from_ms(ep["start_ms"]), end_ts=_from_ms(ep["end_ms"]),
            kind=ep["type"], score=ep["score"], summary=ep["summary"],
            highlights=json.dumps(ep["highlights"], ensure_ascii=False),
            data=json.dumps(data, ensure_ascii=False),
            embedding=json.dumps(vec) if vec else "",
        )
        db.add(c)
        convs.append(c)

    if not convs:  # LLM ничего не выделил — кладём пустой 'other' на всю пачку
        c = Conversation(device_id=device_id, start_ts=chunk_start, end_ts=chunk_end,
                         kind="other", score=None, summary="", highlights="[]", data="{}")
        db.add(c)
        convs.append(c)

    if _as_utc(convs[-1].end_ts) < _as_utc(chunk_end):
        convs[-1].end_ts = chunk_end   # двигаем границу до конца пачки (без «дыр»)
    db.commit()
    return len(convs)


def _prepare(device_id: str, now: datetime, gap: timedelta, settle: timedelta):
    """Фаза ЧТЕНИЯ (короткая сессия): берём следующую пачку и планируем кадры.

    → dict с данными для анализа | "empty" (мелочь уже сохранена) | None (нечего/ждём).
    """
    db = SessionLocal()
    try:
        last_end = (
            db.query(func.max(Conversation.end_ts))
            .filter(Conversation.device_id == device_id).scalar()
        )
        q = db.query(Transcript).filter(Transcript.device_id == device_id)
        if last_end is not None:
            q = q.filter(Transcript.start_ts > last_end)
        lines = q.order_by(Transcript.start_ts.asc()).limit(config.MAX_BLOCK_LINES + 1).all()
        if not lines:
            return None

        full = len(lines) > config.MAX_BLOCK_LINES
        chunk = _first_gap_cut(lines[:config.MAX_BLOCK_LINES], gap)
        # Не заполнено и ещё «свежее» — возможно, разговор идёт: ждём тишины.
        if not full and (now - _as_utc(chunk[-1].end_ts)) < settle:
            return None

        chunk_start, chunk_end = chunk[0].start_ts, chunk[-1].end_ts
        total_text = " ".join(t.text for t in chunk).strip()
        if len(total_text) < _MIN_CHARS:
            _store(db, device_id, [], chunk_start, chunk_end)  # мелочь — без LLM
            return "empty"

        lo_ms, hi_ms = _to_ms(chunk_start), _to_ms(chunk_end)
        return {
            "payload": [{"ms": _to_ms(t.start_ts), "text": t.text} for t in chunk],
            "lo": lo_ms, "hi": hi_ms,
            "chunk_start": chunk_start, "chunk_end": chunk_end,
            # План кадров считаем ЗДЕСЬ (нужна БД), а извлекаем/классифицируем уже без неё.
            "frame_plan": vision.plan_frames(db, device_id, lo_ms, hi_ms, config.VISION_SAMPLES),
            # Промпты разрешаем ЗДЕСЬ (нужна БД): у каждой сети/студии свои.
            "prompts": prompts.resolve(db, device_id),
        }
    finally:
        db.close()


def _store_conv(device_id, episodes, chunk_start, chunk_end, screens, vecs, lines) -> int:
    """Фаза ЗАПИСИ (короткая сессия)."""
    db = SessionLocal()
    try:
        return _store(db, device_id, episodes, chunk_start, chunk_end, screens, vecs, lines)
    finally:
        db.close()


def run_once() -> int:
    if not (config.ANALYZE and config.MISTRAL_API_KEY):
        return 0
    gap = timedelta(minutes=config.COARSE_GAP_MINUTES)
    settle = timedelta(minutes=config.CONV_SETTLE_MINUTES)
    now = datetime.now(timezone.utc)
    made = 0

    db = SessionLocal()
    try:
        device_ids = [r[0] for r in db.query(Transcript.device_id).distinct().all()]
    finally:
        db.close()

    for device_id in device_ids:
        if made >= config.ANALYZE_BATCH:
            break
        prep = _prepare(device_id, now, gap, settle)
        if prep is None:
            continue
        if prep == "empty":
            made += 1
            continue

        # --- Сетевые вызовы (зрение + LLM + эмбеддинги) БЕЗ удержания соединения с БД ---
        pr = prep["prompts"]
        screens = vision.classify_planned(prep["frame_plan"], pr["vision_task"],
                                          pr["vision_format"])
        hint = vision.build_hint(screens, pr["screen_hint_header"])
        episodes = mistral.analyze_block(prep["payload"], prep["lo"], prep["hi"],
                                         screen_hint=hint, pr=pr)
        if episodes is None:
            continue  # ошибка — повторим в следующий проход (граница не двинулась)
        vecs = mistral.embed([_embed_text(ep) for ep in episodes]) if (config.EMBED and episodes) else None

        # --- Запись под короткой сессией ---
        n = _store_conv(device_id, episodes, prep["chunk_start"], prep["chunk_end"],
                        screens, vecs, prep["payload"])
        made += 1
        realtime.broadcast_soon({"type": "conversation", "device_id": device_id})
        logger.info("Разбор %s: пачка %s..%s → эпизодов %d",
                    device_id, prep["chunk_start"], prep["chunk_end"], n)

    return made


async def loop(interval: int | None = None) -> None:
    interval = interval or config.ANALYZE_INTERVAL
    while True:
        try:
            n = await run_in_threadpool(run_once)
            if n:
                logger.info("Анализатор: обработано пачек %d", n)
        except Exception:  # noqa: BLE001 — фон не должен ронять процесс
            logger.exception("Анализатор: сбой прохода")
        await asyncio.sleep(interval)

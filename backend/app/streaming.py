"""Отдача live-видео в формате HLS.

Плейлист собирается динамически из индекса сегментов: берём N самых свежих
сегментов устройства, у которых уже готов .ts, и формируем скользящее окно.
Сами .ts-сегменты и превью отдаёт статика (/hls) — в деве FastAPI, в проде Nginx.
"""
import os
import re
import json
import math
import tempfile
import subprocess
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from . import config
from .db import get_db, SessionLocal
from .models import Segment, User, Transcript, Conversation, ScreenEvent
from .security import get_current_user, get_current_username
from .access import require_device, can_access

router = APIRouter(prefix="/devices", tags=["streaming"])

DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# Сегменты, отстоящие не более чем на столько секунд, считаем непрерывной записью.
RANGE_GAP_TOLERANCE = 8.0


def _check_device_id(device_id: str) -> None:
    if not DEVICE_ID_RE.match(device_id):
        raise HTTPException(status_code=400, detail="Invalid device_id")


def _parse_iso(value: str) -> datetime:
    """ISO-время (в т.ч. с 'Z') → aware datetime в UTC."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _to_ms(dt: datetime) -> int:
    return int(_as_utc(dt).timestamp() * 1000)


def _seg_end(s) -> datetime:
    """Момент конца сегмента (начало + длительность)."""
    return _as_utc(s.start_ts) + timedelta(seconds=float(s.duration or 0))


def _segments_overlapping(db, device_id: str, dt_from: datetime, dt_to: datetime, limit: int = 5000):
    """Сегменты, ПЕРЕСЕКАЮЩИЕ [from, to): начинающиеся внутри + один предыдущий,
    если он заходит в диапазон (иначе перемотка в середину длинного сегмента → пустой ответ)."""
    main = (
        db.query(Segment)
        .filter(Segment.device_id == device_id,
                Segment.start_ts >= dt_from, Segment.start_ts < dt_to)
        .order_by(Segment.start_ts.asc())
        .limit(limit)
        .all()
    )
    prev = (
        db.query(Segment)
        .filter(Segment.device_id == device_id, Segment.start_ts < dt_from)
        .order_by(Segment.start_ts.desc())
        .first()
    )
    segs = []
    if prev is not None and _seg_end(prev) > dt_from:
        segs.append(prev)
    segs.extend(main)
    return segs


def _view_file(device_id: str, seg, view: int) -> str | None:
    """Имя .ts нужного ракурса. Если запрошенного вида нет — ракурс 0;
    для старых (муксовых) сегментов — общий seg_<id>.ts. None, если файла нет вовсе."""
    hls_dir = os.path.join(config.HLS_DIR, device_id)
    for name in (f"seg_{seg.id}_v{view}.ts", f"seg_{seg.id}_v0.ts", f"seg_{seg.id}.ts"):
        if os.path.exists(os.path.join(hls_dir, name)):
            return name
    return None


def _merge(segs, with_kind: bool = False) -> list[dict]:
    """Сливает соседние сегменты в непрерывные отрезки (при with_kind — с учётом типа)."""
    out: list[dict] = []
    for s in segs:
        start_ms = _to_ms(s.start_ts)
        end_ms = start_ms + int((s.duration or 0) * 1000)
        joinable = (
            out
            and start_ms - out[-1]["end"] <= RANGE_GAP_TOLERANCE * 1000
            and (not with_kind or out[-1]["kind"] == s.event)
        )
        if joinable:
            out[-1]["end"] = max(out[-1]["end"], end_ms)
        else:
            item = {"start": start_ms, "end": end_ms}
            if with_kind:
                item["kind"] = s.event
            out.append(item)
    return out


@router.get("/{device_id}/live.m3u8")
def live_playlist(
    device_id: str,
    view: int = Query(0),
    db: Session = Depends(get_db),
    _: str = Depends(require_device),   # проверка прав на эту камеру
):
    _check_device_id(device_id)
    view = max(0, view)

    # Берём с запасом свежие сегменты, оставляем только те, у кого готов .ts.
    recent = (
        db.query(Segment)
        .filter(Segment.device_id == device_id)
        .order_by(Segment.start_ts.desc())
        .limit(config.LIVE_WINDOW * 3)
        .all()
    )
    recent.reverse()  # по возрастанию времени

    window = [
        (s, f) for (s, f) in ((s, _view_file(device_id, s, view)) for s in recent) if f
    ][-config.LIVE_WINDOW:]

    if not window:
        raise HTTPException(status_code=404, detail="No live segments yet")

    first = window[0][0]
    # Монотонная (в рамках устройства) медиа-последовательность.
    media_seq = (
        db.query(Segment)
        .filter(Segment.device_id == device_id, Segment.id < first.id)
        .count()
    )
    target = max(1, math.ceil(max(s.duration for s, _ in window) or 1))

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{target}",
        f"#EXT-X-MEDIA-SEQUENCE:{media_seq}",
        f"#EXT-X-DISCONTINUITY-SEQUENCE:{media_seq}",
    ]
    for s, fname in window:
        # Каждый сегмент — независимо закодированный файл (таймлайн с нуля),
        # поэтому перед ним ставим разрыв: плеер корректно сшивает поток.
        lines.append("#EXT-X-DISCONTINUITY")
        lines.append(f"#EXTINF:{s.duration:.3f},")
        lines.append(f"/hls/{device_id}/{fname}")

    body = "\n".join(lines) + "\n"
    return Response(
        content=body,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/{device_id}/timeline")
def timeline(
    device_id: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    db: Session = Depends(get_db),
    _: str = Depends(require_device),   # проверка прав на эту камеру
):
    """Записанные интервалы устройства за диапазон — для полосы таймлайна.

    Смежные сегменты объединяются в непрерывные отрезки, чтобы отдать компактно.
    """
    _check_device_id(device_id)
    dt_from = _parse_iso(from_)
    dt_to = _parse_iso(to)

    # Только нужные колонки (не полные ORM-объекты): при непрерывной записи за сутки
    # это тысячи строк, а тянем их каждые 15 с — лёгкие кортежи заметно дешевле.
    segs = (
        db.query(Segment.start_ts, Segment.duration, Segment.event, Segment.idle)
        .filter(Segment.device_id == device_id,
                Segment.start_ts >= dt_from, Segment.start_ts < dt_to)
        .order_by(Segment.start_ts.asc())
        .all()
    )

    active = [s for s in segs if not s.idle]
    normal = [s for s in active if (s.event or "normal") == "normal"]
    special = [s for s in active if (s.event or "normal") != "normal"]
    idle = [s for s in segs if s.idle]

    # Тихое отвлечение (зрение по кадрам, screen_events): промежутки без речи, где на
    # экране развлечение. Берём пересекающиеся с диапазоном.
    distractions = (
        db.query(ScreenEvent)
        .filter(ScreenEvent.device_id == device_id, ScreenEvent.distraction.is_(True),
                ScreenEvent.start_ts < dt_to, ScreenEvent.end_ts > dt_from)
        .order_by(ScreenEvent.start_ts.asc())
        .all()
    )

    # ranges — активная запись (синяя полоса); events — спец-записи (маркеры по типу);
    # idle — простой; distractions — молчаливое отвлечение по кадрам.
    return {
        "ranges": _merge(normal),
        "events": _merge(special, with_kind=True),
        "idle": _merge(idle),
        "distractions": [
            {"start": _to_ms(d.start_ts), "end": _to_ms(d.end_ts), "label": d.label or ""}
            for d in distractions
        ],
        "segments": len(segs),
    }


_PHRASE_GAP = 1.2      # пауза, по которой рвём на фразы, секунды
_PHRASE_MAX_WORDS = 22  # и принудительно, чтобы не получались простыни


def _phrases(words_json: str, fallback: str) -> list[dict]:
    """Пословные тайминги → фразы [{s, e, text}] (секунды от начала сегмента).

    Рвём по паузе между словами и по длине. Если таймингов нет (старые записи
    или сбой) — отдаём весь текст одной фразой с нулевым смещением, как было.
    """
    try:
        words = json.loads(words_json) if words_json else []
    except (ValueError, TypeError):
        words = []
    if not words:
        return [{"s": 0.0, "e": 0.0, "text": fallback}] if fallback else []

    out: list[dict] = []
    cur: list[dict] = []
    for w in words:
        if not isinstance(w, dict) or not w.get("w"):
            continue
        if cur and (float(w.get("s", 0)) - float(cur[-1].get("e", 0)) > _PHRASE_GAP
                    or len(cur) >= _PHRASE_MAX_WORDS):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)

    return [
        {"s": float(g[0].get("s", 0)), "e": float(g[-1].get("e", 0)),
         "text": " ".join(str(x["w"]) for x in g)}
        for g in out if g
    ]


@router.get("/{device_id}/transcript")
def transcript(
    device_id: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
    _: str = Depends(require_device),   # проверка прав на эту камеру
):
    """Расшифровки речи устройства за диапазон [from, to] (для панели транскрипта).

    Хранятся отдельно и не удаляются ретеншеном → доступны даже после удаления видео.
    q — необязательный поиск по тексту.
    """
    _check_device_id(device_id)
    dt_from = _parse_iso(from_)
    dt_to = _parse_iso(to)

    query = db.query(Transcript).filter(
        Transcript.device_id == device_id,
        Transcript.start_ts >= dt_from,
        Transcript.start_ts < dt_to,
    )
    if q and q.strip():
        query = query.filter(Transcript.text.ilike(f"%{q.strip()}%"))
    rows = query.order_by(Transcript.start_ts.asc()).limit(5000).all()

    # Раньше отдавали по одной записи на 60-секундный сегмент с одним таймкодом:
    # клик по реплике уводил на НАЧАЛО сегмента, и фразу приходилось ждать до
    # минуты. Deepgram отдаёт пословные тайминги, они лежат в words — режем по
    # ним на фразы, и каждая получает свой точный момент.
    out: list[dict] = []
    for r in rows:
        base = _to_ms(r.start_ts)
        for ph in _phrases(r.words, r.text):
            out.append({
                "id": r.id,
                "start": base + int(ph["s"] * 1000),
                "end": base + int(ph["e"] * 1000),
                "text": ph["text"],
            })
    # Соседние сегменты изредка перекрываются на стыке (джиттер загрузки), поэтому
    # порядок по сегментам не гарантирует порядок по времени — сортируем явно.
    out.sort(key=lambda x: x["start"])
    return out


@router.get("/{device_id}/conversations")
def conversations(
    device_id: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    db: Session = Depends(get_db),
    _: str = Depends(require_device),   # проверка прав на эту камеру
):
    """AI-разборы разговоров за диапазон: сводка + ключевые моменты с таймкодами."""
    _check_device_id(device_id)
    dt_from = _parse_iso(from_)
    dt_to = _parse_iso(to)

    rows = (
        db.query(Conversation)
        .filter(Conversation.device_id == device_id,
                Conversation.start_ts >= dt_from, Conversation.start_ts < dt_to)
        .order_by(Conversation.start_ts.asc())
        .limit(2000)
        .all()
    )

    def _json(raw: str, default):
        try:
            return json.loads(raw) if raw else default
        except (ValueError, TypeError):
            return default

    out = []
    for r in rows:
        data = _json(r.data, {})
        out.append({
            "id": r.id,
            "start": _to_ms(r.start_ts),
            "end": _to_ms(r.end_ts),
            "type": r.kind or "other",
            "title": (data.get("title") or "") if isinstance(data, dict) else "",
            "score": r.score,
            "summary": r.summary,
            "participants": data.get("participants", []) if isinstance(data, dict) else [],
            "criteria": data.get("criteria", {}) if isinstance(data, dict) else {},
            "seller_score": data.get("seller_score") if isinstance(data, dict) else None,
            "sentiment": data.get("sentiment") if isinstance(data, dict) else None,
            "screen": (data.get("screen") or "") if isinstance(data, dict) else "",
            "screens": data.get("screens", []) if isinstance(data, dict) else [],
            "flags": data.get("flags", []) if isinstance(data, dict) else [],
            "highlights": _json(r.highlights, []),
            "clean": data.get("clean", []) if isinstance(data, dict) else [],
        })
    return out


@router.get("/{device_id}/frame")
def frame(
    device_id: str,
    ts: int = Query(...),  # момент времени, epoch ms
    db: Session = Depends(get_db),
    _: str = Depends(require_device),   # проверка прав на эту камеру
):
    """Превью-кадр ближайшего к моменту `ts` сегмента (для наведения на таймлайн)."""
    _check_device_id(device_id)
    dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)

    seg = (
        db.query(Segment)
        .filter(Segment.device_id == device_id, Segment.start_ts <= dt)
        .order_by(Segment.start_ts.desc())
        .first()
    )
    if seg is None:
        seg = (
            db.query(Segment)
            .filter(Segment.device_id == device_id, Segment.start_ts >= dt)
            .order_by(Segment.start_ts.asc())
            .first()
        )
    if seg is None or not os.path.exists(os.path.join(config.HLS_DIR, device_id, f"seg_{seg.id}.jpg")):
        raise HTTPException(status_code=404, detail="No frame")

    return RedirectResponse(url=f"/hls/{device_id}/seg_{seg.id}.jpg", status_code=307)


@router.get("/{device_id}/export")
def export(
    device_id: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    view: int = Query(0),
    # Лёгкая проверка сессии (без БД): иначе соединение через get_current_user
    # держалось бы весь стрим выгрузки. Список файлов берём короткой сессией ниже.
    _: str = Depends(get_current_username),
):
    """Скачивание всего диапазона [from, to] одним MP4.

    Сегменты (в т.ч. разрозненные фрагменты) склеиваются ffmpeg'ом без
    перекодирования и отдаются потоком (фрагментированный MP4) — размер любой.
    """
    _check_device_id(device_id)
    dt_from = _parse_iso(from_)
    dt_to = _parse_iso(to)
    view = max(0, view)

    device_hls_dir = os.path.join(config.HLS_DIR, device_id)
    # Короткая сессия ТОЛЬКО под проверку прав и список файлов — не держим
    # соединение весь стрим (выгрузка суток идёт минутами).
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == _).first()
        if user is None or not can_access(db, user, device_id):
            raise HTTPException(status_code=404, detail="Device not found")
        names = [
            f for f in (_view_file(device_id, s, view)
                        for s in _segments_overlapping(db, device_id, dt_from, dt_to))
            if f
        ]
    finally:
        db.close()
    if not names:
        raise HTTPException(status_code=404, detail="Нет записей в выбранном диапазоне")

    # Список кладём в саму папку сегментов и используем относительные ASCII-имена
    # + cwd — так ffmpeg не спотыкается о не-ASCII символы в пути к проекту.
    fd, list_path = tempfile.mkstemp(suffix=".txt", prefix="_export_", dir=device_hls_dir)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        for n in names:
            f.write(f"file '{n}'\n")

    cmd = [
        config.FFMPEG_BIN, "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", os.path.basename(list_path),
        # Один ракурс = одна видео+аудио дорожка (файлы уже разложены по видам).
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c", "copy", "-bsf:a", "aac_adtstoasc",  # AAC из TS (ADTS) → MP4 (ASC)
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4", "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=device_hls_dir)

    def stream():
        try:
            while True:
                chunk = proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                proc.stdout.close()
            except OSError:
                pass
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            try:
                os.remove(list_path)
            except OSError:
                pass

    view_sfx = f"_r{view + 1}" if view else ""
    fname = f"{device_id}{view_sfx}_{dt_from.strftime('%Y%m%d_%H%M')}-{dt_to.strftime('%Y%m%d_%H%M')}.mp4"
    return StreamingResponse(
        stream(),
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/{device_id}/archive.m3u8")
def archive_playlist(
    device_id: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    view: int = Query(0),
    db: Session = Depends(get_db),
    _: str = Depends(require_device),   # проверка прав на эту камеру
):
    """VOD-плейлист сегментов в диапазоне [from, to] для перемотки по архиву."""
    _check_device_id(device_id)
    dt_from = _parse_iso(from_)
    dt_to = _parse_iso(to)
    view = max(0, view)

    window = [
        (s, f)
        for (s, f) in ((s, _view_file(device_id, s, view))
                       for s in _segments_overlapping(db, device_id, dt_from, dt_to))
        if f
    ]
    if not window:
        raise HTTPException(status_code=404, detail="No archive in range")

    target = max(1, math.ceil(max(s.duration for s, _ in window) or 1))
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        f"#EXT-X-TARGETDURATION:{target}",
        "#EXT-X-MEDIA-SEQUENCE:0",
    ]

    # Сегменты кладём целиком, поэтому первый начинается РАНЬШЕ запрошенного
    # момента — без подсказки плеер играл бы его с начала, то есть до минуты
    # чужого звука перед нужной фразой. Считаем смещение внутри плейлиста
    # (сумма длительностей до нужного сегмента + позиция внутри него) и отдаём
    # его в EXT-X-START — hls.js стартует ровно оттуда.
    offset = 0.0
    acc = 0.0
    for s, _f in window:
        dur = float(s.duration or 0)
        seg_start = s.start_ts if s.start_ts.tzinfo else s.start_ts.replace(tzinfo=timezone.utc)
        inside = (dt_from - seg_start).total_seconds()
        if 0 <= inside < max(dur, 0.001):
            offset = acc + inside
            break
        acc += dur
    if offset > 0:
        lines.append(f"#EXT-X-START:TIME-OFFSET={offset:.3f},PRECISE=YES")

    for s, fname in window:
        lines.append("#EXT-X-DISCONTINUITY")
        # Настоящее время сегмента: по нему панель понимает, какой момент играет.
        # Без этого позицию приходилось считать арифметикой от начала плейлиста,
        # а он начинается с головы сегмента и рвётся на дырах в архиве.
        seg_start = s.start_ts if s.start_ts.tzinfo else s.start_ts.replace(tzinfo=timezone.utc)
        lines.append("#EXT-X-PROGRAM-DATE-TIME:"
                     + seg_start.isoformat(timespec="milliseconds").replace("+00:00", "Z"))
        lines.append(f"#EXTINF:{s.duration:.3f},")
        lines.append(f"/hls/{device_id}/{fname}")
    lines.append("#EXT-X-ENDLIST")

    return Response(
        content="\n".join(lines) + "\n",
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-cache"},
    )

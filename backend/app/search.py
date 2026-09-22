"""Кэш эмбеддингов для семантического поиска.

Раньше каждый запрос грузил ВСЕ разговоры из БД и парсил их JSON-эмбеддинги
заново (O(N) + json.loads на каждый). Разговоры не удаляются, а embedding
пишется один раз при создании → кэш append-only: догружаем только новые строки
(id больше водяного знака), держим распарсенные векторы + нормы + лёгкие метаданные
в памяти. Косинус считаем по кэшу.
"""
import json
import math
import threading

from .models import Conversation

_lock = threading.Lock()
_vecs: dict[int, list[float]] = {}
_norms: dict[int, float] = {}
_meta: dict[int, dict] = {}
_max_id = 0


def _title_of(data_str: str) -> str:
    try:
        d = json.loads(data_str) if data_str else {}
        return d.get("title", "") if isinstance(d, dict) else ""
    except (ValueError, TypeError):
        return ""


def refresh(db) -> None:
    """Догружаем в кэш разговоры с id больше водяного знака (только с эмбеддингом)."""
    global _max_id
    rows = (
        db.query(
            Conversation.id, Conversation.device_id, Conversation.start_ts,
            Conversation.end_ts, Conversation.kind, Conversation.score,
            Conversation.summary, Conversation.data, Conversation.embedding,
        )
        .filter(Conversation.id > _max_id)
        .order_by(Conversation.id.asc())
        .all()
    )
    if not rows:
        return
    with _lock:
        for r in rows:
            if r.id > _max_id:
                _max_id = r.id  # двигаем знак и по строкам без эмбеддинга — не рескан
            if not r.embedding:
                continue
            try:
                v = json.loads(r.embedding)
            except (ValueError, TypeError):
                continue
            if not v:
                continue
            _vecs[r.id] = v
            _norms[r.id] = math.sqrt(sum(x * x for x in v)) or 1.0
            _meta[r.id] = {
                "id": r.id, "device_id": r.device_id,
                "start_ts": r.start_ts, "end_ts": r.end_ts,
                "kind": r.kind, "score": r.score, "summary": r.summary,
                "title": _title_of(r.data),
            }


def search(db, qvec: list[float], limit: int) -> list[tuple[float, dict]]:
    """→ [(similarity, meta)] топ-limit по косинусной близости к qvec."""
    refresh(db)
    qn = math.sqrt(sum(x * x for x in qvec)) or 1.0
    with _lock:
        items = list(_vecs.items())  # снимок пар (id, вектор)
        norms = _norms
        metas = _meta

    scored: list[tuple[float, int]] = []
    for cid, v in items:
        dot = 0.0
        for a, b in zip(qvec, v):
            dot += a * b
        scored.append((dot / (qn * norms[cid]), cid))
    scored.sort(key=lambda t: t[0], reverse=True)

    out: list[tuple[float, dict]] = []
    for sim, cid in scored[: max(1, limit)]:
        m = metas.get(cid)
        if m:
            out.append((sim, m))
    return out

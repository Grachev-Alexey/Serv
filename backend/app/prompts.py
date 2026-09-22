"""Промпты ИИ: встроенные дефолты + переопределения из панели.

Редактируется ВСЁ, что уходит в модель, включая формат ответа. Разрешение от
частного к общему: студия → сеть → глобально → дефолт.

Плейсхолдеры, которые подставляет код:
  {transcript} — распознанная речь (таймкод, TAB, текст)
  {screens}    — данные с экрана, если зрение что-то нашло
  {criteria}   — критерии из ключа criteria
"""
import time
import logging

from sqlalchemy.orm import Session

from .models import Device, PromptOverride, Studio

logger = logging.getLogger("monitoring.prompts")

CACHE_TTL = 60.0

DEFAULTS: dict[str, str] = {
    # ── Разбор разговоров ──────────────────────────────────────────────
    "analyzer_system": (
        "Ты — аналитик записей рабочего дня в салоне лазерной эпиляции. "
        "Работаешь строго по расшифровке речи: не додумываешь события, не "
        "добавляешь реплик, которых нет в тексте. Отвечаешь только валидным JSON."
    ),
    "analyzer_intro": (
        "Фрагмент записи рабочего дня сотрудника салона лазерной эпиляции (экран + микрофон). "
        "Ниже распознанная речь; каждая строка: таймкод в миллисекундах, TAB, текст "
        "(распознавание сырое, бывают ошибки)."
    ),
    "analyzer_task": (
        "РАЗДЕЛИ фрагмент на ЭПИЗОДЫ по смыслу и участникам (не по времени). Эпизод — "
        "цельный кусок: консультация/продажа с клиентом; либо отвлечение (мастер смотрит "
        "видео/подкаст, листает телефон, личный разговор); либо болтовня сотрудников; либо "
        "прочее. Разбери КАЖДЫЙ эпизод.\n"
        "Если приведены данные с экрана — учитывай их: развлечение на экране (видео/соцсети/"
        "игры) без консультации с клиентом = distraction, даже если речи мало; рабочая CRM/"
        "звонок с клиентом подтверждают консультацию/продажу.\n\n"
        "Роли: master (мастер на месте), seller (дистанционный продавец/спец по видеосвязи), "
        "client (клиент), other. Типы: consultation, sale, distraction, internal, other.\n"
        "Консультации/продажи оцени по критериям (0-10 каждый) и общим score (0-100). Для "
        "distraction/internal/other: score=null, criteria={}. Если есть дистанционный "
        "продавец — оцени и его: seller_score (0-100), иначе null.\n"
        "Если речи в эпизоде почти нет — не восстанавливай разговор по догадке. "
        "Ставь score=null и коротко пиши в summary, что речи недостаточно."
    ),
    "analyzer_format": (
        "Ответь СТРОГО валидным JSON на русском:\n"
        '{"episodes":[{"start_ms":<из строк>,"end_ms":<из строк>,'
        '"type":"consultation|sale|distraction|internal|other","title":"<кратко>",'
        '"participants":[{"role":"master|seller|client|other","note":"<кто/имя>"}],'
        '"summary":"<2-4 предложения: суть и итог>","score":<0-100|null>,'
        '"criteria":{"<ключ>":<0-10>},"seller_score":<0-100|null>,'
        '"sentiment":"<настроение клиента к концу: happy|neutral|hesitant|unhappy; для не-консультаций null>",'
        '"flags":["<красные флаги: не спросил противопоказания, грубость, обещал скидку>"],'
        '"highlights":[{"t":<мс>,"text":"<что произошло>","kind":"objection|upsell|contra|promise|complaint|redflag|other"}]}]}\n'
        "highlights — 2-8 важных моментов только для содержательных эпизодов; "
        "цитируй ТОЛЬКО то, что реально есть в расшифровке выше. "
        "Расшифровку не переписывай — она уже хранится отдельно."
    ),
    "criteria": (
        "greeting: приветствие и знакомство\n"
        "needs: выявление потребностей и зоны\n"
        "contraindications: сбор противопоказаний и анамнеза\n"
        "presentation: презентация процедуры и аппарата\n"
        "objections: работа с возражениями\n"
        "upsell: попытка продажи курса/абонемента\n"
        "next_step: договорённость о следующем шаге (запись)\n"
        "politeness: вежливость и тон"
    ),
    # ── Зрение по кадрам экрана ────────────────────────────────────────
    "vision_task": (
        "На кадре — экран рабочего компьютера сотрудника салона лазерной эпиляции. Может "
        "быть открыт видеозвонок с клиентом, CRM/расписание/рабочие программы — либо "
        "отвлечение: видео/ютуб, соцсети, мессенджер, игры, личный телефон. Определи, что "
        "на экране и чем занят сотрудник."
    ),
    "vision_format": (
        "Ответь СТРОГО валидным JSON на русском, без пояснений:\n"
        '{"activity":"work|communication|entertainment|idle|unknown",'
        '"label":"<коротко что на экране: напр. CRM/расписание, YouTube, Telegram, рабочий стол>",'
        '"distraction":<true|false — true, если это развлечение/личное, не относящееся к работе>,'
        '"note":"<кратко, что видно>"}\n'
        "activity: work — рабочие программы/CRM/консультация; communication — мессенджер/"
        "почта/звонок (бывает и рабочим); entertainment — видео/соцсети/игры; idle — "
        "заставка/пустой рабочий стол/экран блокировки."
    ),
    "screen_hint_header": "Данные с экрана (кадры, что было открыто в эти моменты):",
}

KEYS = tuple(DEFAULTS)

TITLES = {
    "analyzer_system":    "Разбор — системный промпт",
    "analyzer_intro":     "Разбор — вступление перед расшифровкой",
    "analyzer_task":      "Разбор — правила деления на эпизоды",
    "analyzer_format":    "Разбор — формат ответа (JSON)",
    "criteria":           "Критерии оценки консультации",
    "vision_task":        "Зрение — что определять на экране",
    "vision_format":      "Зрение — формат ответа (JSON)",
    "screen_hint_header": "Заголовок блока данных с экрана",
}

_cache: dict[tuple[str, str], tuple[float, dict[str, str]]] = {}


def _lookup(db: Session, scope: str, scope_key: str) -> dict[str, str]:
    rows = (
        db.query(PromptOverride)
        .filter(PromptOverride.scope == scope, PromptOverride.scope_key == scope_key)
        .all()
    )
    return {r.key: r.text for r in rows if (r.text or "").strip()}


def resolve(db: Session, device_id: str | None = None) -> dict[str, str]:
    """Итоговый набор промптов для камеры (или глобальный, если device_id=None)."""
    studio_key, network_key = "", ""
    if device_id:
        dev = db.get(Device, device_id)
        if dev is not None and dev.studio_id:
            studio_key = str(dev.studio_id)
            st = db.get(Studio, dev.studio_id)
            network_key = (st.network or "") if st else ""

    ck = (studio_key, network_key)
    now = time.monotonic()
    hit = _cache.get(ck)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]

    out = dict(DEFAULTS)
    out.update(_lookup(db, "global", ""))
    if network_key:
        out.update(_lookup(db, "network", network_key))
    if studio_key:
        out.update(_lookup(db, "studio", studio_key))
    _cache[ck] = (now, out)
    return out


def invalidate() -> None:
    _cache.clear()


def criteria_list(text: str) -> list[tuple[str, str]]:
    """«ключ: описание» построчно → [(ключ, описание)]."""
    out: list[tuple[str, str]] = []
    for line in (text or "").splitlines():
        line = line.strip().lstrip("-").strip()
        if not line or ":" not in line:
            continue
        k, _, label = line.partition(":")
        k, label = k.strip(), label.strip()
        if k and label and k.replace("_", "").isalnum():
            out.append((k[:32], label[:120]))
    return out

"""Разовая переразметка УЖЕ записанных сегментов по активности.

Помечает idle те сегменты, где нет реального движения (детектор на OpenCV,
устойчив к шуму/таймстампу, ловит движение и в углу-камере) И звук тихий.
Анализирует сохранённый .ts ракурса 0 — сырой mp4 к этому моменту уже удалён.
Логика идентична «живому» детекту в ingest.

Запуск ВНУТРИ контейнера бэкенда:
    docker compose exec -T backend python -m app.backfill_idle
Опции:
    --device <id>   только одно устройство
    --days N        только сегменты за последние N дней (по умолчанию — все)
    --dry-run       ничего не писать в БД, только показать, сколько бы пометилось
    --verbose       печатать по каждому сегменту долю движения и пик аудио
                    (удобно, чтобы подобрать пороги MOTION_MIN_AREA_FRAC / *_DB)

ВНИМАНИЕ: после пометки retention удалит старый простой в течение
IDLE_RETENTION_HOURS часов — это и есть цель (освободить диск/БД). Гоняет
детектор по каждому .ts, так что на большом архиве займёт время и подъест CPU —
лучше в период низкой активности. Сначала прогони с --dry-run (и/или --verbose).
"""
import os
import argparse
from datetime import datetime, timezone, timedelta

from . import config, hls, motion
from .db import SessionLocal
from .models import Segment


def _view0_path(device_id: str, seg_id: int) -> str | None:
    """Путь к .ts ракурса 0 (или к старому муксовому). None, если файла уже нет."""
    hls_dir = os.path.join(config.HLS_DIR, device_id)
    for name in (f"seg_{seg_id}_v0.ts", f"seg_{seg_id}.ts"):
        p = os.path.join(hls_dir, name)
        if os.path.exists(p):
            return p
    return None


def _analyze(path: str) -> tuple[bool, float | None, float | None]:
    """(is_idle, motion_fraction, audio_peak_db). Та же логика, что в ingest."""
    frac = motion.max_motion_fraction(path)
    no_motion = frac is not None and frac < config.MOTION_MIN_AREA_FRAC
    peak = None
    audio_quiet = True
    if no_motion and config.IDLE_AUDIO_CHECK:
        peak = hls.audio_max_db(path)
        audio_quiet = peak is None or peak < config.IDLE_AUDIO_SILENCE_DB
    return (no_motion and audio_quiet), frac, peak


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device")
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0, help="взять только N самых свежих (дёшево для проверки)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    q = db.query(Segment)
    if args.device:
        q = q.filter(Segment.device_id == args.device)
    if args.days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
        q = q.filter(Segment.start_ts >= cutoff)
    # С --limit берём N САМЫХ СВЕЖИХ (desc); иначе весь диапазон по порядку.
    if args.limit > 0:
        segs = q.order_by(Segment.start_ts.desc()).limit(args.limit).all()
    else:
        segs = q.order_by(Segment.start_ts.asc()).all()

    total = len(segs)
    marked = active = skipped = 0
    tag = " (dry-run, без записи)" if args.dry_run else ""
    print(f"Сегментов к анализу: {total}{tag}", flush=True)

    for i, s in enumerate(segs, 1):
        path = _view0_path(s.device_id, s.id)
        if not path:
            skipped += 1                      # .ts уже удалён retention'ом — пропускаем
            continue
        is_idle, frac, peak = _analyze(path)
        if args.verbose:
            print(f"  seg {s.id} {s.start_ts:%Y-%m-%d %H:%M:%S} "
                  f"движение={0 if frac is None else frac * 100:.2f}% "
                  f"аудио={'n/a' if peak is None else f'{peak:.1f}dB'} "
                  f"→ {'IDLE' if is_idle else 'active'}", flush=True)
        if is_idle:
            marked += 1
            if not args.dry_run and not s.idle:
                s.idle = True
        else:
            active += 1
        if i % 200 == 0:
            if not args.dry_run:
                db.commit()
            print(f"  {i}/{total}… idle={marked} active={active} skip={skipped}", flush=True)

    if not args.dry_run:
        db.commit()
    db.close()
    print(f"Готово: idle={marked}, активных={active}, "
          f"пропущено (нет .ts)={skipped}, всего={total}", flush=True)


if __name__ == "__main__":
    main()

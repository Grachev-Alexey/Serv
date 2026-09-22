"""Детекция реального движения в сегменте (OpenCV).

Отличает НАСТОЯЩЕЕ движение (человек, открытие окна, движение на камере
наблюдения в углу экрана) от сенсорного шума и бегущего таймстампа:
кадры уменьшаются и сглаживаются (режем шум), берётся разница соседних кадров,
мелкие/точечные изменения отсекаются по площади — остаётся только связная
«клякса» движения. Если её площадь ≥ порога (доля кадра) — считаем, что движение
было. Так человек даже в маленьком углу пройдёт порог, а тикающий таймстамп — нет.

OpenCV импортируется лениво: если его вдруг нет/сломан — функции вернут None,
и вызывающий код трактует это как «не смогли определить → НЕ простой» (безопасно,
ничего лишнего не удалим).
"""
import logging

from . import config

logger = logging.getLogger("monitoring.motion")


def max_motion_fraction(path: str) -> float | None:
    """Максимальная доля кадра (0..1), занятая связным движением, по всем парам
    соседних (сэмплированных) кадров. None — если не удалось открыть/прочитать видео
    или недоступен OpenCV."""
    try:
        import cv2
    except Exception:  # noqa: BLE001 — нет OpenCV → детект отключаем безопасно
        logger.warning("OpenCV недоступен — детект движения выключен", exc_info=True)
        return None

    cap = cv2.VideoCapture(path, cv2.CAP_FFMPEG)
    # У VideoCapture по умолчанию НЕТ тайм-аутов — битый/подвисший .ts мог бы
    # заморозить анализ. Ставим тайм-ауты на открытие и чтение (мс).
    for _prop in ("CAP_PROP_OPEN_TIMEOUT_MSEC", "CAP_PROP_READ_TIMEOUT_MSEC"):
        _p = getattr(cv2, _prop, None)
        if _p is not None:
            try:
                cap.set(_p, 5000)
            except Exception:  # noqa: BLE001
                pass
    if not cap.isOpened():
        return None
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        step = 1
        if fps and config.MOTION_SAMPLE_FPS > 0:
            step = max(1, int(round(fps / config.MOTION_SAMPLE_FPS)))

        prev = None
        max_frac = 0.0
        n = 0
        read_any = False
        # Потолок прочитанных кадров — страховка от бесконечного/огромного файла.
        while n < config.MOTION_MAX_FRAMES:
            ok, frame = cap.read()
            if not ok:
                break
            read_any = True
            take = (n % step == 0)
            n += 1
            if not take:
                continue

            h, w = frame.shape[:2]
            tw = config.MOTION_WIDTH
            if tw and w > tw:
                frame = cv2.resize(frame, (tw, max(1, int(h * tw / w))))
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)

            if prev is not None:
                diff = cv2.absdiff(prev, gray)
                _, th = cv2.threshold(diff, config.MOTION_DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)
                th = cv2.dilate(th, None, iterations=2)   # склеиваем разрозненные точки
                contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                area = float(th.shape[0] * th.shape[1]) or 1.0
                for c in contours:
                    frac = cv2.contourArea(c) / area
                    if frac > max_frac:
                        max_frac = frac
            prev = gray

        return max_frac if read_any else None
    except Exception:  # noqa: BLE001 — любая ошибка анализа → «не определили»
        logger.exception("Ошибка детекта движения для %s", path)
        return None
    finally:
        cap.release()


def has_motion(path: str) -> bool | None:
    """True — есть реальное движение; False — движения нет; None — определить не удалось."""
    frac = max_motion_fraction(path)
    if frac is None:
        return None
    return frac >= config.MOTION_MIN_AREA_FRAC

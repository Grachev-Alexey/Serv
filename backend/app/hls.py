"""Обработка видео через ffmpeg: переупаковка в HLS-сегменты (TS) и превью.

Камеры шлют H.264/AAC в MP4 → в MPEG-TS переупаковываем копированием потоков
(`-c copy`, без перекодирования). Если копирование не удалось (например, иной
кодек) — откатываемся к транскоду в H.264/AAC.
"""
import os
import re
import glob
import logging
import subprocess

from . import config

logger = logging.getLogger("monitoring.hls")


def audio_max_db(path: str) -> float | None:
    """Пиковая громкость аудио (dBFS) через volumedetect.

    None — если дорожки нет / ошибка (трактуем как тишину). Тихий фон/шум обычно
    ниже ~-50 dB; речь даёт пики заметно выше (-10..-35), поэтому по пику надёжно
    отличаем «кто-то говорит» от «просто шумит микрофон».
    """
    try:
        r = subprocess.run(
            [config.FFMPEG_BIN, "-hide_banner", "-i", path,
             "-map", "0:a:0", "-vn", "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=60,
        )
        m = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", r.stderr)
        return float(m.group(1)) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def probe_duration(path: str) -> float:
    """Длительность файла в секундах (0.0 при ошибке)."""
    try:
        r = subprocess.run(
            [config.FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return float(r.stdout.strip())
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0.0


def probe_video_count(path: str) -> int:
    """Сколько видеодорожек (ракурсов) в файле. Минимум 1."""
    try:
        r = subprocess.run(
            [config.FFPROBE_BIN, "-v", "error", "-select_streams", "v",
             "-show_entries", "stream=index", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        )
        n = len([ln for ln in r.stdout.splitlines() if ln.strip()])
        return max(1, n)
    except (OSError, subprocess.SubprocessError):
        return 1


def _remux(src_mp4: str, dst_ts: str, maps: list[str]) -> bool:
    """MP4 → MPEG-TS с заданными -map. Сначала copy (дёшево), при неудаче — транскод."""
    os.makedirs(os.path.dirname(dst_ts), exist_ok=True)
    tmp = dst_ts + ".part"
    base = [config.FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-i", src_mp4]
    copy_cmd = base + maps + ["-c", "copy", "-f", "mpegts", tmp]
    transcode_cmd = base + maps + [
        "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-f", "mpegts", tmp,
    ]
    for cmd, label in ((copy_cmd, "copy"), (transcode_cmd, "transcode")):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                os.replace(tmp, dst_ts)  # атомарно — плеер не увидит недописанный .ts
                if label == "transcode":
                    logger.info("Сегмент транскодирован (copy не подошёл): %s", dst_ts)
                return True
            logger.warning("ffmpeg %s не удался для %s: %s", label, dst_ts, r.stderr.strip()[:300])
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("ffmpeg %s ошибка для %s: %s", label, dst_ts, e)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    return False


def remux_to_ts(src_mp4: str, dst_ts: str) -> bool:
    """Переупаковать весь файл (все дорожки) в один .ts."""
    return _remux(src_mp4, dst_ts, [])


def remux_views(src_mp4: str, device_hls_dir: str, seg_id: int, n_views: int) -> int:
    """Разложить каждый ракурс в отдельный seg_<id>_v<i>.ts (видео i + аудио i).

    Суммарный объём тот же, что у исходника — просто разделяем потоки (copy).
    Возвращает число успешно созданных видов.
    """
    made = 0
    for i in range(max(1, n_views)):
        dst = os.path.join(device_hls_dir, f"seg_{seg_id}_v{i}.ts")
        maps = ["-map", f"0:v:{i}", "-map", f"0:a:{i}?"]
        if _remux(src_mp4, dst, maps):
            made += 1
    return made


def make_thumbnail(src: str, dst_jpg: str, width: int | None = None) -> bool:
    """Один кадр (превью) из сегмента. width — уменьшить до N px по ширине."""
    os.makedirs(os.path.dirname(dst_jpg), exist_ok=True)
    tmp = dst_jpg + ".part"
    vf = ["-vf", f"scale={width}:-2"] if width else []
    try:
        r = subprocess.run(
            # -f image2: временный файл с расширением .part, формат задаём явно.
            [config.FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y",
             "-i", src, *vf, "-frames:v", "1", "-q:v", "4", "-f", "image2", tmp],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            os.replace(tmp, dst_jpg)
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    if os.path.exists(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass
    return False


def prune_ts(device_hls_dir: str, keep: int) -> None:
    """Оставляет только `keep` самых свежих .ts (по номеру сегмента в имени)."""
    files = glob.glob(os.path.join(device_hls_dir, "seg_*.ts"))

    def _seg_num(p: str) -> int:
        try:
            return int(os.path.basename(p)[len("seg_"):-len(".ts")])
        except ValueError:
            return 0

    for old in sorted(files, key=_seg_num, reverse=True)[keep:]:
        try:
            os.remove(old)
        except OSError:
            pass

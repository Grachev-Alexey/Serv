# Клиент камеры — как слать видео на Виви

Камера (или скрипт рядом с ней) отправляет короткие MP4-сегменты на сервер по HTTP.

## Эндпоинт
```
POST https://vivi-control.tw1.ru/api/upload
Content-Type: multipart/form-data
Authorization: Bearer t1n8bzy0uL_WpRcxZWOhxP9yVKM3bsvd1eYH6fr46sY
```
Токен — из `.env` сервера (`UPLOAD_TOKEN`). Если сменишь его на сервере — смени и здесь.

## Поля формы
| поле          | обяз.  | что это |
|---------------|--------|---------|
| `file`        | да     | сам .mp4-сегмент |
| `device_id`   | да     | ID камеры: `A-Z a-z 0-9 _ -`, до 128 симв. (напр. `cam-entrance`) |
| `start_ts`    | желат. | время начала сегмента — **epoch в миллисекундах** |
| `duration`    | желат. | длительность сегмента в секундах (напр. `4`) |
| `device_host` | нет    | инфо: адрес/имя источника |
| `device_user` | нет    | инфо: пользователь/владелец |
| `event`       | нет    | тип записи (см. ниже) |

Имя файла: только `A-Z a-z 0-9 . _ -` (без пробелов и кириллицы), до 255 символов.
`duration` слать **обязательно** — по ней строится таймлайн.

> **Имя файла важнее `start_ts`.** Сервер сам берёт время съёмки из имени
> (`rec_[тип_]ГГГГММДД_ЧЧММСС…`) и переводит его в UTC по часовому поясу студии,
> заданному в панели. Так догрузка накопленного попадает в архив на своё место,
> даже если клиент прислал в `start_ts` момент отправки.
> `start_ts` используется только когда времени в имени нет, оно не разбирается,
> часы камеры убежали больше чем на 10 минут вперёд или у камеры не задана студия.
> Расхождение `start_ts` с именем файла больше 90 секунд пишется в лог сервера —
> это признак либо неверного `start_ts`, либо неправильного пояса у студии.
>
> Отсюда два требования: **имя файла обязано содержать время начала записи**
> (`ffmpeg -strftime 1 "rec_%Y%m%d_%H%M%S.mp4"`), а **часы и часовой пояс на
> камере должны быть верными**.

> ⚠️ `start_ts` — это время **НАЧАЛА записи сегмента**, а не момент отправки.
> Не `date +%s%3N` и не `time.time()` в момент заливки! Если связь пропала и
> очередь накопилась, все файлы приедут с временем догрузки и архив съедет.
> На камере «Садовая» так уехало на **23 дня**: 758 файлов от 15 августа легли
> в архив как «сегодня 05:42». Берите время из имени файла (`-strftime`).

Если `start_ts` не прислать — сервер проставит текущее время (то есть заведомо
неверное для любой очереди), а длительность вычислит через ffprobe.

## Обычная запись vs «зум-запись»
Тип задаётся любым из двух способов:
- поле `event=zoom`, ИЛИ
- имя файла `rec_<тип>_<дата>…`:
  - `rec_20260721_130501_ab12.mp4` → обычная (жёлтого нет)
  - `rec_zoom_20260721_130501_ab12.mp4` → тип `zoom` (жёлтые блоки на таймлайне)

## Формат видео (чтобы сервер НЕ перекодировал)
Как сейчас: **H.264 + AAC, 1280×720, ~10 fps, yuv420p, mp4**. Сервер переупаковывает
`-c copy` без транскодинга — быстро и дёшево. H.265 тоже примут, но тогда сервер
перекодирует (нагрузка выше). Длина сегмента **2–6 сек** — меньше задержка live,
точнее таймлайн.

## Пример: bash + ffmpeg + curl (режем RTSP-поток и заливаем)
```bash
TOKEN=t1n8bzy0uL_WpRcxZWOhxP9yVKM3bsvd1eYH6fr46sY
SRV=https://vivi-control.tw1.ru/api/upload
DEV=cam-entrance
OUT=/tmp/vivi
mkdir -p "$OUT"

# 1) режем поток камеры на сегменты по 4 сек (без перекодирования)
ffmpeg -rtsp_transport tcp -i "rtsp://ЛОГИН:ПАРОЛЬ@КАМЕРА:554/stream1" \
  -c copy -f segment -segment_time 4 -reset_timestamps 1 \
  -strftime 1 "$OUT/rec_%Y%m%d_%H%M%S.mp4" &

# 2) как только сегмент дописан — заливаем и удаляем
inotifywait -m -e close_write --format '%f' "$OUT" | while read f; do
  # ВАЖНО: start_ts — время НАЧАЛА съёмки, а НЕ момент отправки. ffmpeg -strftime
  # уже записал его в имя файла (локальное время камеры) — берём оттуда.
  # Иначе при накопившейся очереди весь архив съедет на время догрузки.
  ts=$(printf '%s' "$f" | grep -oE '[0-9]{8}_[0-9]{6}' | head -1)
  d=${ts:0:8}; t=${ts:9:6}
  ms=$(( $(date -d "${d:0:4}-${d:4:2}-${d:6:2} ${t:0:2}:${t:2:2}:${t:4:2}" +%s) * 1000 ))
  curl -s -H "Authorization: Bearer $TOKEN" \
       -F "file=@$OUT/$f" \
       -F "device_id=$DEV" \
       -F "start_ts=$ms" \
       -F "duration=4" \
       "$SRV" >/dev/null
  rm -f "$OUT/$f"
done
```

## Пример: Python
```python
import re, time, datetime, requests


def start_ms_from_name(name: str) -> int:
    """Время НАЧАЛА съёмки из имени rec_[тип_]YYYYMMDD_HHMMSS… (локальное время камеры).

    Слать момент отправки (time.time()) НЕЛЬЗЯ: если очередь накопилась, весь архив
    съедет на время догрузки — у нас так уехало на 23 дня.
    """
    m = re.search(r"(\d{8})_(\d{6})", name)
    if not m:
        return int(time.time() * 1000)
    dt = datetime.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    return int(dt.timestamp() * 1000)

SRV   = "https://vivi-control.tw1.ru/api/upload"
TOKEN = "t1n8bzy0uL_WpRcxZWOhxP9yVKM3bsvd1eYH6fr46sY"

def send(path, device_id, start_ms, duration_s, event=""):
    with open(path, "rb") as f:
        r = requests.post(
            SRV,
            headers={"Authorization": f"Bearer {TOKEN}"},
            files={"file": (path.split("/")[-1], f, "video/mp4")},
            data={
                "device_id": device_id,
                "start_ts": str(start_ms),
                "duration": str(duration_s),
                "event": event,          # "" или "zoom"
            },
            timeout=60,
        )
    r.raise_for_status()
    return r.json()

NAME = "rec_20260721_130501.mp4"
print(send(NAME, "cam-entrance", start_ms_from_name(NAME), 4.0))
```

## Ответ сервера
Успех: `200 {"status":"success","message":"File ... uploaded successfully","size":<байт>}`
Ошибки: `401` — неверный токен · `400` — плохой device_id/имя файла · `413` — файл больше лимита.

После первой удачной загрузки камера сама появится в панели (по `device_id`),
там ей можно задать понятное имя.

# Виви — бэкенд (FastAPI + ffmpeg)
FROM python:3.12-slim

# ffmpeg/ffprobe — переупаковка в HLS и экспорт; libglib2.0-0 — нужен OpenCV (детект движения).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Один процесс (БЕЗ --workers): нужен для WebSocket (сокеты общие в одном процессе).
# Без обёртки-супервизора приложение = PID 1 → сигналы (kill -USR1 1 для дампа стека)
# и диагностика идут прямо в него, а не в мастер-процесс. Async + threadpool для
# ffmpeg с запасом тянут ~6–10 камер; экспорт стримится в threadpool, не блокируя.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

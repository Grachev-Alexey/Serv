import os
import secrets
import logging

from dotenv import load_dotenv

logger = logging.getLogger("monitoring")

APP_DIR = os.path.dirname(os.path.abspath(__file__))          # backend/app
BACKEND_DIR = os.path.dirname(APP_DIR)                         # backend
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)                    # server/

load_dotenv(os.path.join(BACKEND_DIR, ".env"))

STORAGE_DIR = os.environ.get("STORAGE_DIR", os.path.join(PROJECT_ROOT, "storage"))
UPLOAD_DIR = os.path.join(STORAGE_DIR, "uploads")
HLS_DIR = os.path.join(STORAGE_DIR, "hls")

for _d in (STORAGE_DIR, UPLOAD_DIR, HLS_DIR):
    os.makedirs(_d, exist_ok=True)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(STORAGE_DIR, 'monitoring.db')}",
)


DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", 20))
DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", 30))
DB_POOL_TIMEOUT = int(os.environ.get("DB_POOL_TIMEOUT", 10))
DB_POOL_RECYCLE = int(os.environ.get("DB_POOL_RECYCLE", 1800))
DB_CONNECT_TIMEOUT = int(os.environ.get("DB_CONNECT_TIMEOUT", 5))

THREADPOOL_TOKENS = int(os.environ.get("THREADPOOL_TOKENS", 80))


DIAG_INTERVAL = int(os.environ.get("DIAG_INTERVAL", 30))

UPLOAD_TOKEN = os.environ.get("UPLOAD_TOKEN")
if not UPLOAD_TOKEN:
    UPLOAD_TOKEN = secrets.token_urlsafe(32)
    logger.warning("UPLOAD_TOKEN не задан. Сгенерирован временный токен: %s", UPLOAD_TOKEN)

JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET:
    JWT_SECRET = secrets.token_urlsafe(48)
    logger.warning("JWT_SECRET не задан. Сгенерирован временный (сессии сбросятся при рестарте).")
JWT_ALGORITHM = "HS256"
JWT_TTL_SECONDS = int(os.environ.get("JWT_TTL_SECONDS", 7 * 24 * 3600))

COOKIE_NAME = os.environ.get("COOKIE_NAME", "session")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = os.environ.get("COOKIE_SAMESITE", "lax")


ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

MAX_FILE_SIZE = int(os.environ.get("MAX_FILE_SIZE", 512 * 1024 * 1024))
CHUNK_SIZE = 1024 * 1024


DEVICE_ONLINE_SECONDS = int(os.environ.get("DEVICE_ONLINE_SECONDS", 30 * 60))

RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", 2))


IDLE_DETECTION = os.environ.get("IDLE_DETECTION", "true").lower() == "true"
IDLE_RETENTION_HOURS = float(os.environ.get("IDLE_RETENTION_HOURS", 6))


MOTION_MIN_AREA_FRAC = float(os.environ.get("MOTION_MIN_AREA_FRAC", 0.004))
MOTION_DIFF_THRESHOLD = int(os.environ.get("MOTION_DIFF_THRESHOLD", 25))
MOTION_SAMPLE_FPS = float(os.environ.get("MOTION_SAMPLE_FPS", 4))
MOTION_WIDTH = int(os.environ.get("MOTION_WIDTH", 480))
MOTION_MAX_FRAMES = int(os.environ.get("MOTION_MAX_FRAMES", 600))

IDLE_AUDIO_CHECK = os.environ.get("IDLE_AUDIO_CHECK", "true").lower() == "true"
IDLE_AUDIO_SILENCE_DB = float(os.environ.get("IDLE_AUDIO_SILENCE_DB", -45.0))

INGEST_CONCURRENCY = int(os.environ.get("INGEST_CONCURRENCY", 3))


DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")
TRANSCRIBE = os.environ.get("TRANSCRIBE", "true").lower() == "true"
DEEPGRAM_MODEL = os.environ.get("DEEPGRAM_MODEL", "nova-3")
DEEPGRAM_LANGUAGE = os.environ.get("DEEPGRAM_LANGUAGE", "ru")
DEEPGRAM_TIMEOUT = float(os.environ.get("DEEPGRAM_TIMEOUT", 30))
DEEPGRAM_RETRIES = int(os.environ.get("DEEPGRAM_RETRIES", 3))
DEEPGRAM_RETRY_BACKOFF = float(os.environ.get("DEEPGRAM_RETRY_BACKOFF", 1.5))
TRANSCRIBE_MIN_DB = float(os.environ.get("TRANSCRIBE_MIN_DB", -55.0))
TRANSCRIBE_AUDIO_FILTER = os.environ.get("TRANSCRIBE_AUDIO_FILTER", "loudnorm=I=-16:TP=-1.5:LRA=11")
TRANSCRIBE_CONCURRENCY = int(os.environ.get("TRANSCRIBE_CONCURRENCY", 2))

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
ANALYZE = os.environ.get("ANALYZE", "true").lower() == "true"
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "mistral-large-latest")
MISTRAL_TIMEOUT = float(os.environ.get("MISTRAL_TIMEOUT", 60))
MISTRAL_RETRIES = int(os.environ.get("MISTRAL_RETRIES", 3))
MISTRAL_RETRY_BACKOFF = float(os.environ.get("MISTRAL_RETRY_BACKOFF", 2.0))
EMBED = os.environ.get("EMBED", "true").lower() == "true"
MISTRAL_EMBED_MODEL = os.environ.get("MISTRAL_EMBED_MODEL", "mistral-embed")
SEARCH_LIMIT = int(os.environ.get("SEARCH_LIMIT", 20))
COARSE_GAP_MINUTES = float(os.environ.get("COARSE_GAP_MINUTES", 12))
CONV_SETTLE_MINUTES = float(os.environ.get("CONV_SETTLE_MINUTES", 5))
ANALYZE_INTERVAL = int(os.environ.get("ANALYZE_INTERVAL", 120))
ANALYZE_BATCH = int(os.environ.get("ANALYZE_BATCH", 3))
MAX_BLOCK_LINES = int(os.environ.get("MAX_BLOCK_LINES", 350))

VISION = os.environ.get("VISION", "true").lower() == "true"
VISION_MODEL = os.environ.get("VISION_MODEL", "pixtral-large-latest")
VISION_SAMPLES = int(os.environ.get("VISION_SAMPLES", 6))
VISION_CONCURRENCY = int(os.environ.get("VISION_CONCURRENCY", 2))
VISION_MAX_WIDTH = int(os.environ.get("VISION_MAX_WIDTH", 768))
VISION_TIMEOUT = float(os.environ.get("VISION_TIMEOUT", 40))
VISION_RETRIES = int(os.environ.get("VISION_RETRIES", 2))
VISION_RETRY_BACKOFF = float(os.environ.get("VISION_RETRY_BACKOFF", 2.0))

VISION_SCAN = os.environ.get("VISION_SCAN", "true").lower() == "true"
VISION_SCAN_INTERVAL = int(os.environ.get("VISION_SCAN_INTERVAL", 300)) 
VISION_SCAN_HOURS = float(os.environ.get("VISION_SCAN_HOURS", 12))
VISION_SCAN_SETTLE_MINUTES = float(os.environ.get("VISION_SCAN_SETTLE_MINUTES", 5))
VISION_SCAN_GAP_MINUTES = float(os.environ.get("VISION_SCAN_GAP_MINUTES", 3))
VISION_SCAN_MIN_MINUTES = float(os.environ.get("VISION_SCAN_MIN_MINUTES", 2))
VISION_SCAN_SAMPLES = int(os.environ.get("VISION_SCAN_SAMPLES", 3))
VISION_SCAN_BATCH = int(os.environ.get("VISION_SCAN_BATCH", 4))


CONSULT_CRITERIA = [
    ("greeting", "приветствие и знакомство"),
    ("needs", "выявление потребностей и зоны"),
    ("contraindications", "сбор противопоказаний и анамнеза"),
    ("presentation", "презентация процедуры и аппарата"),
    ("objections", "работа с возражениями"),
    ("upsell", "попытка продажи курса/абонемента"),
    ("next_step", "договорённость о следующем шаге (запись)"),
    ("politeness", "вежливость и тон"),
]

FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.environ.get("FFPROBE_BIN", "ffprobe")
LIVE_WINDOW = int(os.environ.get("LIVE_WINDOW", 6))
HLS_KEEP = int(os.environ.get("HLS_KEEP", 12))


_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").strip()
ALLOWED_ORIGINS = [o.strip() for o in _origins.split(",") if o.strip()]

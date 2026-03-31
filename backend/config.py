from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Database
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "image_pro.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

# Thumbnails
THUMBNAIL_DIR = DATA_DIR / "thumbnails"
THUMBNAIL_SIZE = (300, 300)
THUMBNAIL_QUALITY = 85

# AI Models
MODEL_DIR = DATA_DIR / "models"
MODEL_CURRENT_DIR = MODEL_DIR / "current"
MODEL_HISTORY_DIR = MODEL_DIR / "history"
MAX_MODEL_VERSIONS = 15

# CLIP
CLIP_MODEL_NAME = "ViT-L-14"
CLIP_PRETRAINED = "laion2b_s32b_b82k"
CLIP_FEATURE_DIM = 768
CLIP_BATCH_SIZE = 32

# AI Training
AI_MIN_SAMPLES = 200
AI_HIDDEN_DIM = 256
AI_DROPOUT = 0.3
AI_LEARNING_RATE = 1e-3
AI_BATCH_SIZE = 64
AI_MAX_EPOCHS = 50
AI_EARLY_STOP_PATIENCE = 5
AI_FOCAL_GAMMA = 2.0

# Hashing
QUICK_HASH_CHUNK_SIZE = 8 * 1024  # 8KB
HASH_THREAD_WORKERS = 16
DHASH_PROCESS_WORKERS = 8

# Similarity thresholds (hamming distance)
SIMILARITY_THRESHOLDS = {
    "loose": 4,
    "standard": 8,
    "strict": 12,
}

# GPX
GPX_GOOD_THRESHOLD_SEC = 300  # 5 minutes

# Timezone
DEFAULT_TIMEZONE_OFFSET = 8  # UTC+8

# Server
HOST = "0.0.0.0"
PORT = 8000

# Supported file extensions
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".avif",
    ".bmp", ".tiff", ".tif", ".gif",
}
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm",
    ".m4v", ".3gp", ".mts", ".m2ts",
}
RAW_EXTENSIONS = {
    ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".dng", ".raf",
}

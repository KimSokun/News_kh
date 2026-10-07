import os
from pathlib import Path
from dotenv import load_dotenv

# Base & Data Directories
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Load .env file
load_dotenv(BASE_DIR / ".env")


def get_env_str(key: str, default: str = "") -> str:
    val = os.getenv(key)
    return val.strip() if val is not None else default


def get_env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return int(val.strip())
    except (ValueError, TypeError):
        return default


def get_env_bool(key: str, default: bool = True) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# Telegram Configuration (Channel & Public Bot Mode)
TELEGRAM_BOT_TOKEN = get_env_str("TELEGRAM_BOT_TOKEN")
TELEGRAM_PARSE_MODE = get_env_str("TELEGRAM_PARSE_MODE", "HTML").upper()

# Telegram Channel Settings
# Can be single or comma-separated list: "@mychannel", "-1001234567890"
raw_channels = get_env_str("TELEGRAM_CHANNEL_IDS", get_env_str("TELEGRAM_CHANNEL_ID", ""))
TELEGRAM_CHANNEL_IDS = [
    ch.strip()
    for ch in raw_channels.split(",")
    if ch.strip()
]
BROADCAST_TO_CHANNEL = get_env_bool("BROADCAST_TO_CHANNEL", bool(TELEGRAM_CHANNEL_IDS))
BROADCAST_TO_SUBSCRIBERS = get_env_bool("BROADCAST_TO_SUBSCRIBERS", True)
CHANNEL_ENABLE_BUTTONS = get_env_bool("CHANNEL_ENABLE_BUTTONS", True)

# Auto-Moderation Settings (Channel Discussion & Group Anti-Spam)
ENABLE_MODERATION = get_env_bool("ENABLE_MODERATION", True)
AUTO_DELETE_LINKS = get_env_bool("AUTO_DELETE_LINKS", True)
AUTO_DELETE_FILES = get_env_bool("AUTO_DELETE_FILES", True)
AUTO_BAN_SPAMMERS = get_env_bool("AUTO_BAN_SPAMMERS", False)

# API Keys
NEWS_API_KEY = get_env_str("NEWS_API_KEY")
GEMINI_API_KEY = get_env_str("GEMINI_API_KEY")
GEMINI_MODEL = get_env_str("GEMINI_MODEL", "gemini-3.6-flash")
OPENAI_API_KEY = get_env_str("OPENAI_API_KEY")

# Polling & Alert Settings
POLL_INTERVAL_SECONDS = get_env_int("POLL_INTERVAL_SECONDS", 300)  # Default: 5 minutes
ALERT_CATEGORIES = [
    cat.strip().lower()
    for cat in get_env_str("ALERT_CATEGORIES", "tech").split(",")
    if cat.strip()
]
TRANSLATE_TO_KHMER = get_env_bool("TRANSLATE_TO_KHMER", True)
SEND_PHOTO = get_env_bool("SEND_PHOTO", True)

# Filtering Rules
REQUIRE_PHOTO_CARD = get_env_bool("REQUIRE_PHOTO_CARD", True)
ONLY_BIG_NEWS = get_env_bool("ONLY_BIG_NEWS", False)

# Rate & Volume Limits
MAX_ALERTS_PER_CYCLE = get_env_int("MAX_ALERTS_PER_CYCLE", 2)
MAX_ITEMS_PER_CHECK = get_env_int("MAX_ITEMS_PER_CHECK", 50)
SEED_ON_FIRST_RUN = get_env_bool("SEED_ON_FIRST_RUN", True)

# Network & Logging
HTTP_TIMEOUT = get_env_int("HTTP_TIMEOUT", 15)
LOG_LEVEL = get_env_str("LOG_LEVEL", "INFO").upper()

# Storage Paths
NEWS_SEEN_FILE = str(DATA_DIR / "news_seen.json")
SUBSCRIBERS_FILE = str(DATA_DIR / "subscribers.json")
MAX_SEEN_HISTORY = get_env_int("MAX_SEEN_HISTORY", 3000)


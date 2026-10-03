import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set in .env")

ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# Data directory — can be overridden by DATA_DIR env var (e.g. /var/lib/survey-bot)
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).parent))
DATA_DIR.mkdir(parents=True, exist_ok=True)

MODEL_PATH = DATA_DIR / "models" / "ggml-small.bin"
DB_PATH = DATA_DIR / "survey.db"
AUDIO_DIR = DATA_DIR / "audio"

# whisper-cli binary location (installed via brew)
WHISPER_BIN = "whisper-cli"

# Language: auto-detect (our staff speaks multiple languages)
WHISPER_LANG = "auto"

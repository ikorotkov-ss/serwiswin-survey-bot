import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set in .env")

ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

BASE_DIR = Path(__file__).parent
MODEL_PATH = BASE_DIR / "models" / "ggml-small.bin"
DB_PATH = BASE_DIR / "survey.db"
AUDIO_DIR = BASE_DIR / "audio"

# whisper-cli binary location (installed via brew)
WHISPER_BIN = "whisper-cli"

# Language: auto-detect (our staff speaks multiple languages)
WHISPER_LANG = "auto"

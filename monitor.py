"""
Monitoring module for SerwisWin Survey Bot.

Provides:
- send_alert() — sends emergency messages to all admins via bot
- log_error() — structured error logging with context
- startup_alert() — sends a startup notification
- health_check() — returns dict of system health metrics
"""

import os
import sys
import logging
import traceback
from datetime import datetime
from pathlib import Path

from config import ADMIN_IDS, BOT_TOKEN

# ─── Structured logging ────────────────────────────────────────────────

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("survey-bot")

# File handler (writes to DATA_DIR / logs /)
DATA_DIR = Path(__file__).parent
DATA_DIR = Path(os.getenv("DATA_DIR", DATA_DIR))
log_dir = DATA_DIR / "logs"
log_dir.mkdir(parents=True, exist_ok=True)

fh = logging.FileHandler(log_dir / "survey-bot.log", encoding="utf-8")
fh.setLevel(logging.DEBUG)
fh.setFormatter(logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
))
logger.addHandler(fh)

# ─── Alert queue ───────────────────────────────────────────────────────

_alert_queue = []


def log_error(context: str, exc: Exception | None = None, extra: dict | None = None):
    """Log an error with structured context and queue an alert."""
    msg = f"[{context}]"
    if exc:
        msg += f" {exc.__class__.__name__}: {exc}"
    if extra:
        msg += f" | extra={extra}"

    logger.error(msg)

    if exc:
        logger.debug("Traceback:\n%s", "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))

    _alert_queue.append({
        "message": msg,
        "timestamp": datetime.now().isoformat(),
        "context": context,
    })


def log_info(msg: str):
    logger.info(msg)


# ─── Alert sender (called from bot.py main loop) ───────────────────────

async def send_pending_alerts(application) -> int:
    """Send queued alerts to all admins. Returns number sent."""
    global _alert_queue
    if not _alert_queue or not ADMIN_IDS:
        return 0

    sent = 0
    while _alert_queue:
        alert = _alert_queue.pop(0)
        for admin_id in ADMIN_IDS:
            try:
                await application.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"⚠️ **Alert: {alert['context']}**\n\n"
                        f"{alert['message']}\n\n"
                        f"🕐 {alert['timestamp']}"
                    ),
                    parse_mode="Markdown",
                )
                sent += 1
            except Exception:
                pass
    return sent


async def send_immediate_alert(application, context: str, message: str):
    """Send an alert immediately (not queued)."""
    if not ADMIN_IDS:
        return
    for admin_id in ADMIN_IDS:
        try:
            await application.bot.send_message(
                chat_id=admin_id,
                text=f"🚨 **{context}**\n\n{message}",
                parse_mode="Markdown",
            )
        except Exception:
            pass


async def startup_alert(application):
    """Send a startup notification to all admins."""
    await send_immediate_alert(
        application,
        "Bot Started",
        f"🤖 Бот запущен\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"📦 DATA_DIR: {DATA_DIR}",
    )


# ─── Health check ──────────────────────────────────────────────────────

def health_check() -> dict:
    """Return system health metrics as a dict."""
    import shutil

    data_dir = Path(os.getenv("DATA_DIR", Path(__file__).parent))
    db_path = data_dir / "survey.db"

    # Disk
    disk_usage = shutil.disk_usage(str(data_dir))

    # DB size
    db_size = db_path.stat().st_size if db_path.exists() else 0

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "disk": {
            "total_gb": round(disk_usage.total / (1024**3), 1),
            "used_gb": round(disk_usage.used / (1024**3), 1),
            "free_gb": round(disk_usage.free / (1024**3), 1),
            "percent_used": round(disk_usage.used / disk_usage.total * 100, 1),
        },
        "database": {
            "exists": db_path.exists(),
            "size_mb": round(db_size / (1024**2), 2),
        },
        "data_dir": str(data_dir),
    }

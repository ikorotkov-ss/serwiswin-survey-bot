"""Reminder script for inactive survey participants.

Sends reminders to users who started but haven't finished the survey:
- 1 hour after last activity → gentle reminder
- 3 hours after last activity → stronger reminder (skips if already reminded)

Run by systemd timer every 15 minutes.
Quiet hours: 23:00-07:00 Europe/Warsaw (no reminders sent).
"""

import os
import sys
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from config import BOT_TOKEN
from database import get_connection, db_migrate
from telegram import Bot
from telegram.error import TelegramError


# ─── Config ──────────────────────────────────────────────────────────

QUIET_HOURS_START = 23  # 11 PM Warsaw
QUIET_HOURS_END = 7     # 7 AM Warsaw
REMINDER_1H = timedelta(hours=1)
REMINDER_3H = timedelta(hours=3)
TZ = ZoneInfo("Europe/Warsaw")

REMINDER_TEXTS = {
    1: (
        "👋 Привет! Ты начал опрос, но не закончил.\n\n"
        "Твои ответы помогут нам сделать рекламу и контент лучше. "
        "Всего 20-30 минут — расскажи реальные случаи из работы.\n\n"
        "Продолжить: /start"
    ),
    3: (
        "⏰ Напоминаю про опрос!\n\n"
        "Мы собрали уже много крутых инсайтов от коллег, "
        "и твой опыт тоже важен. Клиенты каждый день говорят "
        "интересные вещи — поделись ими.\n\n"
        "Это займёт всего 20-30 минут. Начни с /start",
    ),
}


def is_quiet_hours() -> bool:
    """Check if current local time (Warsaw) is in quiet hours."""
    now = datetime.now(TZ)
    hour = now.hour
    if QUIET_HOURS_START <= hour or hour < QUIET_HOURS_END:
        return True
    return False


def get_users_for_reminder() -> list[dict]:
    """Get users who need a reminder: started, not finished, past threshold."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, username, role, last_activity, last_reminder, finished "
        "FROM users WHERE finished = 0 AND role IS NOT NULL"
    )
    rows = cur.fetchall()
    conn.close()

    now = datetime.now(timezone.utc)
    users = []

    for row in rows:
        user = dict(row)
        last_activity = user.get("last_activity")
        if not last_activity:
            continue

        # Parse last_activity (stored as datetime('now') = UTC)
        try:
            last_active = datetime.fromisoformat(last_activity)
        except (ValueError, TypeError):
            continue

        # Ensure timezone-aware
        if last_active.tzinfo is None:
            last_active = last_active.replace(tzinfo=timezone.utc)

        elapsed = now - last_active

        # Determine which reminder level applies
        level = None
        if elapsed >= REMINDER_3H:
            level = 3
        elif elapsed >= REMINDER_1H:
            level = 1
        else:
            continue

        # Check last_reminder to avoid spamming
        last_rem = user.get("last_reminder")
        if last_rem:
            try:
                last_rem_dt = datetime.fromisoformat(last_rem)
                if last_rem_dt.tzinfo is None:
                    last_rem_dt = last_rem_dt.replace(tzinfo=timezone.utc)
                if now - last_rem_dt < timedelta(hours=level):
                    continue  # Already reminded at this level
            except (ValueError, TypeError):
                pass

        user["reminder_level"] = level
        users.append(user)

    return users


def update_last_reminder(user_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET last_reminder = datetime('now') WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()


def main():
    # Run migrations in case they haven't been applied yet
    db_migrate()

    if is_quiet_hours():
        print(f"[{datetime.now(TZ).isoformat()}] Quiet hours — skipping")
        return

    bot = Bot(token=BOT_TOKEN)
    users = get_users_for_reminder()

    print(f"[{datetime.now(TZ).isoformat()}] Found {len(users)} users to remind")

    for user in users:
        text = REMINDER_TEXTS.get(user["reminder_level"], REMINDER_TEXTS[1])
        try:
            bot.send_message(chat_id=user["user_id"], text=text)
            update_last_reminder(user["user_id"])
            print(f"  ✓ Sent reminder level {user['reminder_level']} to user {user['user_id']}")
        except TelegramError as e:
            print(f"  ✗ Failed to send to user {user['user_id']}: {e}")


if __name__ == "__main__":
    main()

"""Integration tests for reminder logic — imports real get_users_for_reminder().

Strategy: patching config.DB_PATH before the first import of database is tricky
because config.py reads from .env at import time. Instead we patch
database.get_connection to return a fresh SQLite in-memory connection.
"""
import pytest
import sqlite3
from datetime import datetime, timezone, timedelta
import sys, os

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PROJECT_DIR)


def _hours_ago(h):
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


@pytest.fixture
def db_path(tmp_path):
    """Create an isolated file-based DB with the real schema."""
    path = tmp_path / "test_reminder.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            role TEXT,
            current_block INTEGER DEFAULT 0,
            last_activity TEXT,
            last_reminder TEXT,
            finished INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            question_number INTEGER,
            raw_text TEXT,
            audio_path TEXT,
            status TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number INTEGER NOT NULL UNIQUE,
            block TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'all',
            text TEXT NOT NULL,
            optional INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()
    return path


def _create_user(db_path, user_id, username, role="sales",
                  last_activity=None, last_reminder=None, finished=0):
    conn = sqlite3.connect(str(db_path))
    if last_activity is None:
        last_activity = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO users (user_id, username, role, current_block, last_activity, last_reminder, finished)"
        "VALUES (?, ?, ?, 0, ?, ?, ?)",
        (user_id, username, role, last_activity, last_reminder, finished),
    )
    conn.commit()
    conn.close()


class TestGetUsersForReminder:
    """Test real get_users_for_reminder() from reminder.py.

    We monkey-patch config.DB_PATH for each test to point to an isolated
    temp file DB. This avoids cross-test contamination and lets the real
    reminder code open/close connections as it normally does.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, db_path, monkeypatch):
        """Per-test: point config.DB_PATH to the temp DB."""
        import config as cfg
        monkeypatch.setattr(cfg, "DB_PATH", db_path)
        import database as db_mod
        # Re-init: apply migrations on the temp DB
        db_mod.init_db()
        db_mod.db_migrate()

    def test_no_users_returns_empty(self):
        from reminder import get_users_for_reminder
        assert get_users_for_reminder() == []

    def test_finished_user_excluded(self, db_path):
        _create_user(db_path, 1, "done_user", finished=1, last_activity=_hours_ago(5))
        from reminder import get_users_for_reminder
        assert get_users_for_reminder() == []

    def test_no_role_user_excluded(self, db_path):
        _create_user(db_path, 1, "norole_user", role=None, last_activity=_hours_ago(5))
        from reminder import get_users_for_reminder
        assert get_users_for_reminder() == []

    def test_finished_and_no_role_excluded(self, db_path):
        _create_user(db_path, 1, "nobody", role=None, finished=1, last_activity=_hours_ago(5))
        from reminder import get_users_for_reminder
        assert get_users_for_reminder() == []

    def test_active_within_1h_excluded(self, db_path):
        _create_user(db_path, 1, "recent", role="sales", last_activity=_hours_ago(0.5))
        from reminder import get_users_for_reminder
        assert get_users_for_reminder() == []

    def test_inactive_1h_gets_level_1(self, db_path):
        _create_user(db_path, 1, "forgotten", role="sales", last_activity=_hours_ago(1.1))
        from reminder import get_users_for_reminder
        users = get_users_for_reminder()
        assert len(users) == 1
        assert users[0]["reminder_level"] == 1
        assert users[0]["user_id"] == 1

    def test_inactive_3h_gets_level_3(self, db_path):
        _create_user(db_path, 1, "very_forgotten", role="sales", last_activity=_hours_ago(3.5))
        from reminder import get_users_for_reminder
        users = get_users_for_reminder()
        assert len(users) == 1
        assert users[0]["reminder_level"] == 3
        assert users[0]["user_id"] == 1

    def test_reminded_recently_skips_level_1(self, db_path):
        _create_user(db_path, 1, "already_reminded", role="sales",
                      last_activity=_hours_ago(2), last_reminder=_hours_ago(0.5))
        from reminder import get_users_for_reminder
        assert get_users_for_reminder() == []

    def test_reminded_1h_ago_still_skips_level_3(self, db_path):
        """last_reminder was 1.5h ago, < 3h → level 3 suppressed."""
        _create_user(db_path, 1, "old_reminder", role="sales",
                      last_activity=_hours_ago(5), last_reminder=_hours_ago(1.5))
        from reminder import get_users_for_reminder
        assert get_users_for_reminder() == []

    def test_reminded_3h_ago_allows_level_3(self, db_path):
        """last_reminder was 3.5h ago, >= 3h → level 3 fires."""
        _create_user(db_path, 1, "old_reminder_3h", role="sales",
                      last_activity=_hours_ago(6), last_reminder=_hours_ago(3.5))
        from reminder import get_users_for_reminder
        users = get_users_for_reminder()
        assert len(users) == 1
        assert users[0]["reminder_level"] == 3

    def test_no_last_activity_skipped(self, db_path):
        _create_user(db_path, 1, "no_activity", role="sales", last_activity=None)
        from reminder import get_users_for_reminder
        assert get_users_for_reminder() == []

    def test_multiple_users_at_different_levels(self, db_path):
        _create_user(db_path, 1, "fresh", role="sales", last_activity=_hours_ago(0.5))
        _create_user(db_path, 2, "level1", role="sales", last_activity=_hours_ago(1.5))
        _create_user(db_path, 3, "level3", role="masters", last_activity=_hours_ago(5))
        _create_user(db_path, 4, "finished", role="sales", finished=1, last_activity=_hours_ago(5))

        from reminder import get_users_for_reminder
        users = get_users_for_reminder()
        assert len(users) == 2
        user_ids = {u["user_id"] for u in users}
        assert 2 in user_ids
        assert 3 in user_ids
        assert 1 not in user_ids
        assert 4 not in user_ids

    def test_edge_exactly_1h(self, db_path):
        activity = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        _create_user(db_path, 1, "edge_1h", role="sales", last_activity=activity)
        from reminder import get_users_for_reminder
        assert len(get_users_for_reminder()) == 1

    def test_edge_exactly_3h(self, db_path):
        activity = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        _create_user(db_path, 1, "edge_3h", role="sales", last_activity=activity)
        from reminder import get_users_for_reminder
        users = get_users_for_reminder()
        assert len(users) == 1
        assert users[0]["reminder_level"] == 3

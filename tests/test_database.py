"""Tests for database operations."""
import sqlite3


class TestDatabaseSchema:
    """Verify the database schema and basic operations."""

    def test_create_tables(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.executescript("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number INTEGER NOT NULL UNIQUE,
                block TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'all',
                text TEXT NOT NULL,
                optional INTEGER DEFAULT 0
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

            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                role TEXT,
                last_activity TEXT
            );
        """)

        # Verify tables exist
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r["name"] for r in cur.fetchall()]
        assert "questions" in tables
        assert "responses" in tables

        conn.close()

    def test_insert_and_read_question(self, test_db):
        cur = test_db.cursor()
        cur.execute(
            "INSERT INTO questions (number, block, role, text) VALUES (?, ?, ?, ?)",
            (1, "Универсальный", "all", "Test question?"),
        )
        test_db.commit()

        cur.execute("SELECT * FROM questions WHERE number = 1")
        row = dict(cur.fetchone())
        assert row["number"] == 1
        assert row["block"] == "Универсальный"
        assert row["role"] == "all"

    def test_insert_response_with_status(self, test_db):
        cur = test_db.cursor()
        cur.execute(
            "INSERT INTO responses (user_id, username, question_number, raw_text, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (12345, "testuser", 5, "some answer", "answered"),
        )
        test_db.commit()

        cur.execute("SELECT * FROM responses")
        row = dict(cur.fetchone())
        assert row["status"] == "answered"
        assert row["user_id"] == 12345

    def test_skipped_status(self, test_db):
        cur = test_db.cursor()
        cur.execute(
            "INSERT INTO responses (user_id, question_number, status) VALUES (?, ?, ?)",
            (12345, 7, "skipped"),
        )
        test_db.commit()

        cur.execute("SELECT * FROM responses WHERE status = 'skipped'")
        rows = cur.fetchall()
        assert len(rows) == 1

    def test_user_role_storage(self, test_db):
        cur = test_db.cursor()
        # Create users table inline for test
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                role TEXT,
                last_activity TEXT
            )
        """)
        cur.execute(
            "INSERT OR REPLACE INTO users (user_id, username, role, last_activity) "
            "VALUES (?, ?, ?, datetime('now'))",
            (12345, "testuser", "sales"),
        )
        test_db.commit()

        cur.execute("SELECT * FROM users WHERE user_id = 12345")
        row = dict(cur.fetchone())
        assert row["role"] == "sales"
        assert row["last_activity"] is not None

    def test_multiple_responses_same_user(self, test_db):
        cur = test_db.cursor()
        for qnum in [1, 2, 3, 5, 8]:
            cur.execute(
                "INSERT INTO responses (user_id, username, question_number, raw_text, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (999, "active_user", qnum, f"answer {qnum}", "answered"),
            )
        test_db.commit()

        cur.execute("SELECT COUNT(*) as cnt FROM responses WHERE user_id = 999 AND status = 'answered'")
        assert cur.fetchone()["cnt"] == 5

        # Skipped questions
        cur.execute("INSERT INTO responses (user_id, question_number, status) VALUES (?, ?, ?)",
                     (999, 4, "skipped"))
        cur.execute("INSERT INTO responses (user_id, question_number, status) VALUES (?, ?, ?)",
                     (999, 6, "skipped"))
        test_db.commit()

        cur.execute("SELECT COUNT(*) as cnt FROM responses WHERE user_id = 999 AND status = 'skipped'")
        assert cur.fetchone()["cnt"] == 2

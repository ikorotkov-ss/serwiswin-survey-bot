"""Tests for database operations."""
import sqlite3
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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


class TestUserFunctions:
    """Test get_or_create_user and related user functions."""

    def _setup_db(self, db_path, questions_list):
        from database import init_db, db_migrate, load_questions, get_connection
        import config
        config.DB_PATH = db_path
        init_db()
        db_migrate()
        load_questions(questions_list)

    def test_create_new_user(self, tmp_path):
        from database import get_or_create_user
        from survey_data import questions as qs

        db_path = tmp_path / "test_new_user.db"
        self._setup_db(db_path, qs)

        user = get_or_create_user(11111, "newuser")
        assert user["user_id"] == 11111
        assert user["username"] == "newuser"
        assert user.get("finished", 0) == 0

    def test_get_existing_user(self, tmp_path):
        from database import get_or_create_user
        from survey_data import questions as qs

        db_path = tmp_path / "test_existing_user.db"
        self._setup_db(db_path, qs)

        get_or_create_user(22222, "existing")
        user2 = get_or_create_user(22222, "existing")
        assert user2["user_id"] == 22222

    def test_update_user_role(self, tmp_path):
        from database import get_or_create_user, update_user_role
        from survey_data import questions as qs

        db_path = tmp_path / "test_update_role.db"
        self._setup_db(db_path, qs)

        get_or_create_user(33333, "role_user")
        update_user_role(33333, "masters")

        from database import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT role FROM users WHERE user_id = 33333")
        assert cur.fetchone()["role"] == "masters"
        conn.close()


class TestUserProgressIntegration:
    """Integration tests for get_user_progress with real data."""

    def test_sales_progress_initial(self, tmp_path):
        from database import get_or_create_user, get_user_progress, load_questions
        from survey_data import questions as qs

        import config
        config.DB_PATH = tmp_path / "test_progress_init.db"

        from database import init_db, db_migrate
        init_db()
        db_migrate()
        load_questions(qs)

        get_or_create_user(77777, "progress_user")

        progress = get_user_progress(77777, "sales")
        assert progress["total_questions"] == 29
        assert progress["total_mandatory"] == 27
        assert progress["total_optional"] == 2
        assert progress["answered_count"] == 0
        assert progress["skipped_count"] == 0

    def test_sales_progress_with_answers(self, tmp_path):
        from database import (
            get_or_create_user, get_user_progress, load_questions,
            save_response, mark_skipped,
        )
        from survey_data import questions as qs

        import config
        config.DB_PATH = tmp_path / "test_progress_answers.db"

        from database import init_db, db_migrate
        init_db()
        db_migrate()
        load_questions(qs)

        get_or_create_user(88888, "ans_user")

        # Answer 5 mandatory questions
        for qnum in range(1, 6):
            save_response(88888, "ans_user", qnum, f"answer {qnum}")

        # Skip 1
        mark_skipped(88888, 12)

        # Answer 1 optional
        save_response(88888, "ans_user", 42, "optional answer")

        progress = get_user_progress(88888, "sales")
        assert progress["answered_count"] == 6  # 5 mandatory + 1 optional
        assert progress["skipped_count"] == 1
        assert progress["optional_answered"] == 1
        assert progress["mandatory_answered"] == 5
        assert progress["total_mandatory"] == 27
        assert progress["total_optional"] == 2

    def test_skipped_questions_func(self, tmp_path):
        # Isolated test with unique user ID
        from database import (
            get_or_create_user, load_questions, mark_skipped, get_skipped_questions,
        )
        from survey_data import questions as qs

        import config
        config.DB_PATH = tmp_path / "test_skipped_func.db"

        from database import init_db, db_migrate
        init_db()
        db_migrate()
        load_questions(qs)

        user_id = 555501  # unique ID to avoid cross-test contamination
        get_or_create_user(user_id, "skip_user")
        mark_skipped(user_id, 3)
        mark_skipped(user_id, 7)
        mark_skipped(user_id, 15)

        skipped = get_skipped_questions(user_id)
        assert skipped == [3, 7, 15]

    def test_skipped_empty(self, tmp_path):
        from database import get_or_create_user, get_skipped_questions, load_questions
        from survey_data import questions as qs

        import config
        config.DB_PATH = tmp_path / "test_skipped_empty.db"

        from database import init_db, db_migrate
        init_db()
        db_migrate()
        load_questions(qs)

        get_or_create_user(10001, "no_skip_user")

        assert get_skipped_questions(10001) == []

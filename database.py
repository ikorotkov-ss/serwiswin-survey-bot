import sqlite3
from pathlib import Path
from config import DB_PATH


def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def db_migrate():
    """Apply schema migrations for new features. Idempotent."""
    conn = get_connection()
    cur = conn.cursor()

    migrations = [
        "ALTER TABLE questions ADD COLUMN optional INTEGER DEFAULT 0",
        "ALTER TABLE responses ADD COLUMN status TEXT DEFAULT ''",
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            role TEXT,
            current_block INTEGER DEFAULT 0,
            last_activity TEXT,
            finished INTEGER DEFAULT 0
        )
        """,
    ]

    for migration in migrations:
        try:
            cur.execute(migration)
        except sqlite3.OperationalError:
            pass  # Column already exists

    conn.commit()
    conn.close()


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number INTEGER NOT NULL UNIQUE,
            block TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'all',
            text TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            question_number INTEGER,
            raw_text TEXT,
            audio_path TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    conn.commit()
    conn.close()


def load_questions(questions_list):
    """Import questions from a list of dicts: {number, block, role, text, optional}"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM questions")
    # Ensure all items have the optional key
    prepared = []
    for q in questions_list:
        item = dict(q)
        item.setdefault("optional", 0)
        prepared.append(item)
    cur.executemany(
        "INSERT OR REPLACE INTO questions (number, block, role, text, optional) "
        "VALUES (:number, :block, :role, :text, :optional)",
        prepared,
    )
    conn.commit()
    conn.close()


def get_all_questions():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM questions ORDER BY number")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_question(number):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM questions WHERE number = ?", (number,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def save_response(user_id, username, question_number, raw_text, audio_path=None, status="answered"):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO responses (user_id, username, question_number, raw_text, audio_path, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, username, question_number, raw_text, audio_path, status),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def mark_skipped(user_id, question_number):
    """Insert a response row with status='skipped' and no answer text."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO responses (user_id, question_number, status) VALUES (?, ?, 'skipped')",
        (user_id, question_number),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


# ─── Users table ──────────────────────────────────────────────────────


def get_or_create_user(user_id, username):
    """Get user data from users table; create row if not exists."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row:
        conn.close()
        return dict(row)

    cur.execute(
        "INSERT INTO users (user_id, username) VALUES (?, ?)",
        (user_id, username),
    )
    conn.commit()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row)


def update_user_role(user_id, role):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET role = ? WHERE user_id = ?",
        (role, user_id),
    )
    conn.commit()
    conn.close()


def update_user_block(user_id, block_index):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET current_block = ? WHERE user_id = ?",
        (block_index, user_id),
    )
    conn.commit()
    conn.close()


def update_user_activity(user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET last_activity = datetime('now') WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()


def mark_user_finished(user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET finished = 1 WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()


# ─── Responses queries ────────────────────────────────────────────────


def get_user_responses(user_id):
    """Return all responses for user (including skipped)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM responses WHERE user_id = ? ORDER BY question_number",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_skipped_questions(user_id):
    """Return list of question numbers with status='skipped' for user."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT question_number FROM responses WHERE user_id = ? AND status = 'skipped'",
        (user_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return [r["question_number"] for r in rows]


def get_user_progress(user_id, role):
    """Return dict with full progress stats for a user."""
    from survey_data import is_optional

    conn = get_connection()
    cur = conn.cursor()

    # Questions for this role
    from survey_data import get_questions_for_role
    role_qs = get_questions_for_role(role)
    total_questions = len(role_qs)

    # Count optional questions
    total_optional = sum(1 for q in role_qs if is_optional(q["number"]))
    total_mandatory = total_questions - total_optional

    # User answers
    cur.execute(
        "SELECT question_number, status FROM responses WHERE user_id = ?",
        (user_id,),
    )
    resp_rows = cur.fetchall()
    conn.close()

    answered_by_qnum = {}
    for r in resp_rows:
        # If multiple responses per question, last answered status wins
        qnum = r["question_number"]
        status = r["status"]
        answered_by_qnum[qnum] = status

    answered_count = sum(1 for q in role_qs if answered_by_qnum.get(q["number"]) == "answered")
    skipped_count = sum(1 for q in role_qs if answered_by_qnum.get(q["number"]) == "skipped")

    optional_answered = sum(
        1 for q in role_qs
        if is_optional(q["number"]) and answered_by_qnum.get(q["number"]) == "answered"
    )
    mandatory_answered = answered_count - optional_answered

    return {
        "total_questions": total_questions,
        "answered_count": answered_count,
        "skipped_count": skipped_count,
        "optional_answered": optional_answered,
        "total_optional": total_optional,
        "mandatory_answered": mandatory_answered,
        "total_mandatory": total_mandatory,
    }


def get_stats():
    conn = get_connection()
    cur = conn.cursor()

    # Total participants
    cur.execute("SELECT COUNT(DISTINCT user_id) FROM responses")
    total_users = cur.fetchone()[0]

    # Total responses
    cur.execute("SELECT COUNT(*) FROM responses")
    total_responses = cur.fetchone()[0]

    # Responses per question
    cur.execute("""
        SELECT q.number, q.text, COUNT(r.id) as count
        FROM questions q
        LEFT JOIN responses r ON q.number = r.question_number
        GROUP BY q.number
        ORDER BY q.number
    """)
    per_question = [dict(r) for r in cur.fetchall()]

    conn.close()
    return {"total_users": total_users, "total_responses": total_responses, "per_question": per_question}


def get_all_responses():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT r.id, r.user_id, r.username, r.question_number, q.text as question_text,
               r.raw_text, r.audio_path, r.created_at
        FROM responses r
        LEFT JOIN questions q ON r.question_number = q.number
        ORDER BY r.created_at
    """)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

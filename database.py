import sqlite3
from pathlib import Path
from config import DB_PATH


def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


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
    """Import questions from a list of dicts: {number, block, role, text}"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM questions")
    cur.executemany(
        "INSERT OR REPLACE INTO questions (number, block, role, text) VALUES (:number, :block, :role, :text)",
        questions_list,
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


def save_response(user_id, username, question_number, raw_text, audio_path=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO responses (user_id, username, question_number, raw_text, audio_path) VALUES (?, ?, ?, ?, ?)",
        (user_id, username, question_number, raw_text, audio_path),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


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

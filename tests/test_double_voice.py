"""Test: two voice messages in a row — second must not orphan the first."""

import sqlite3
import pytest

# Setup: fake an in-memory DB that matches the real schema
@pytest.fixture
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            question_number INTEGER,
            raw_text TEXT,
            audio_path TEXT,
            status TEXT DEFAULT '',
            transcript TEXT DEFAULT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    return conn


def _mark_voice_pending(conn, user_id, username, audio_path):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO responses (user_id, username, audio_path, status) VALUES (?, ?, ?, 'voice_saved')",
        (user_id, username, audio_path),
    )
    conn.commit()
    return cur.lastrowid


def _get_pending_voices(conn, user_id):
    cur = conn.cursor()
    cur.execute(
        "SELECT id, audio_path, created_at FROM responses WHERE user_id = ? AND status = 'voice_saved' AND question_number IS NULL ORDER BY created_at",
        (user_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def _bind_voice(conn, response_id, question_number):
    cur = conn.cursor()
    cur.execute(
        "UPDATE responses SET question_number = ?, status = 'answered' WHERE id = ?",
        (question_number, response_id),
    )
    conn.commit()


def test_two_voices_same_user_both_pending(conn):
    """Two voice messages in a row from same user — both orphaned until bound."""
    id1 = _mark_voice_pending(conn, user_id=42, username="alice", audio_path="/tmp/a1.ogg")
    id2 = _mark_voice_pending(conn, user_id=42, username="alice", audio_path="/tmp/a2.ogg")

    pending = _get_pending_voices(conn, 42)
    assert len(pending) == 2
    # First in = first out
    assert pending[0]["id"] == id1
    assert pending[1]["id"] == id2


def test_bind_second_voice_first_still_pending(conn):
    """Binding the second voice leaves the first orphaned."""
    id1 = _mark_voice_pending(conn, user_id=7, username="bob", audio_path="/tmp/b1.ogg")
    id2 = _mark_voice_pending(conn, user_id=7, username="bob", audio_path="/tmp/b2.ogg")

    # Bind only the second one
    _bind_voice(conn, id2, 5)

    pending = _get_pending_voices(conn, 7)
    assert len(pending) == 1
    assert pending[0]["id"] == id1


def test_bind_all_voices_empty(conn):
    """After binding all voices, pending list is empty."""
    id1 = _mark_voice_pending(conn, user_id=99, username="carol", audio_path="/tmp/c1.ogg")
    id2 = _mark_voice_pending(conn, user_id=99, username="carol", audio_path="/tmp/c2.ogg")

    _bind_voice(conn, id1, 3)
    _bind_voice(conn, id2, 5)

    assert _get_pending_voices(conn, 99) == []


def test_pending_not_affected_by_other_users(conn):
    """Pending queries are user-scoped."""
    id1 = _mark_voice_pending(conn, user_id=1, username="a", audio_path="/tmp/a.ogg")
    id2 = _mark_voice_pending(conn, user_id=2, username="b", audio_path="/tmp/b.ogg")

    assert len(_get_pending_voices(conn, 1)) == 1
    assert len(_get_pending_voices(conn, 2)) == 1


def test_answered_voice_ignored_by_pending(conn):
    """A voice that was already answered should not appear in pending."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO responses (user_id, username, question_number, audio_path, status) VALUES (?, ?, ?, ?, ?)",
        (10, "eve", 3, "/tmp/e1.ogg", "answered"),
    )
    conn.commit()

    id2 = _mark_voice_pending(conn, user_id=10, username="eve", audio_path="/tmp/e2.ogg")

    pending = _get_pending_voices(conn, 10)
    assert len(pending) == 1
    assert pending[0]["id"] == id2

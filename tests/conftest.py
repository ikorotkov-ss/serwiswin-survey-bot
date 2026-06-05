"""Shared fixtures for survey bot tests."""
import pytest
import sqlite3
import os
import sys

# Add parent dir to path so we can import project modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def test_db(tmp_path):
    """Create a clean in-memory SQLite database for each test."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.executescript("""
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
            status TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            role TEXT,
            current_block INTEGER DEFAULT 0,
            last_activity TEXT,
            last_reminder TEXT,
            finished INTEGER DEFAULT 0
        );
    """)

    conn.commit()
    yield conn
    conn.close()

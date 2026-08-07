from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def sample_channel_db(tmp_path: Path) -> Path:
    path = tmp_path / "sample_channel.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE content_language (
            id TEXT PRIMARY KEY,
            lang_code TEXT,
            lang_subcode TEXT,
            lang_name TEXT
        );

        CREATE TABLE content_contentnode (
            id TEXT PRIMARY KEY,
            content_id TEXT,
            channel_id TEXT,
            parent_id TEXT,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            author TEXT,
            sort_order REAL,
            duration INTEGER,
            lang_id TEXT,
            available INTEGER,
            license_name TEXT,
            license_owner TEXT,
            options TEXT,
            grade_levels TEXT,
            resource_types TEXT,
            learning_activities TEXT,
            categories TEXT,
            learner_needs TEXT,
            tree_id INTEGER,
            lft INTEGER,
            rght INTEGER
        );

        CREATE TABLE content_channelmetadata (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            tagline TEXT,
            author TEXT,
            version INTEGER,
            last_updated TEXT,
            root_id TEXT
        );
        """
    )
    connection.execute(
        "INSERT INTO content_language VALUES (?, ?, ?, ?)",
        ("en", "en", "", "English"),
    )
    connection.execute(
        "INSERT INTO content_channelmetadata VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "channel-1",
            "Khan Academy Test",
            "Synthetic channel",
            "For tests",
            "Test Author",
            7,
            "2026-08-01T00:00:00Z",
            "root",
        ),
    )
    rows = [
        ("root", "c-root", "channel-1", None, "topic", "Khan Academy", "", "", 1, None, "en", 1, None, None, "{}", None, None, None, None, None, 1, 1, 12),
        ("math", "c-math", "channel-1", "root", "topic", "Math", "", "", 1, None, "en", 1, None, None, "{}", None, None, None, None, None, 1, 2, 11),
        ("algebra", "c-algebra", "channel-1", "math", "topic", "Algebra 1", "", "", 1, None, "en", 1, None, None, "{}", None, None, None, None, None, 1, 3, 10),
        ("unit6", "c-unit6", "channel-1", "algebra", "topic", "Unit 6", "Systems of equations", "", 1, None, "en", 1, None, None, "{}", None, None, None, None, None, 1, 4, 9),
        ("lesson1", "c-lesson1", "channel-1", "unit6", "topic", "Lesson 1", "Graphing systems", "", 1, None, "en", 1, None, None, "{}", None, None, None, None, None, 1, 5, 8),
        ("video1", "c-video1", "channel-1", "lesson1", "video", "Graphing systems of equations", "Sal graphs the following system of equations and solves it by looking for the intersection point: y=7/5x-5 and y=3/5x-1.", "Sal Khan", 1, 420, "en", 0, "CC BY-NC-SA", "Khan Academy", "{\"youtube_id\": \"abc\"}", "9,10", "video", "watch", "algebra", None, 1, 6, 7)
    ]
    connection.executemany(
        """
        INSERT INTO content_contentnode VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        rows,
    )
    connection.commit()
    connection.close()
    return path

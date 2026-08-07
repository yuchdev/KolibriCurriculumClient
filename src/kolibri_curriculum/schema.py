from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceSchema:
    node_table: str
    channel_table: str | None
    language_table: str | None
    node_columns: frozenset[str]
    channel_columns: frozenset[str]
    language_columns: frozenset[str]


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def table_names(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows if not str(row[0]).startswith("sqlite_")]


def table_columns(connection: sqlite3.Connection, table: str) -> frozenset[str]:
    rows = connection.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()
    return frozenset(str(row[1]) for row in rows)


def _best_table(
    connection: sqlite3.Connection,
    required: set[str],
    preferred_names: tuple[str, ...],
    optional_score: set[str],
) -> tuple[str | None, frozenset[str]]:
    best_name: str | None = None
    best_columns: frozenset[str] = frozenset()
    best_score = -1

    for table in table_names(connection):
        columns = table_columns(connection, table)
        if not required.issubset(columns):
            continue
        score = len(optional_score.intersection(columns))
        lower = table.lower()
        for index, preferred in enumerate(preferred_names):
            if lower == preferred:
                score += 100 - index
            elif preferred in lower:
                score += 25 - index
        if score > best_score:
            best_name, best_columns, best_score = table, columns, score

    return best_name, best_columns


def detect_schema(connection: sqlite3.Connection) -> SourceSchema:
    node_table, node_columns = _best_table(
        connection,
        required={"id", "title", "kind"},
        preferred_names=("content_contentnode", "contentnode"),
        optional_score={
            "parent_id",
            "content_id",
            "channel_id",
            "description",
            "author",
            "sort_order",
            "tree_id",
            "lft",
            "rght",
        },
    )
    if node_table is None or not ({"parent_id", "parent"} & set(node_columns)):
        raise ValueError("Could not identify a Kolibri ContentNode table")

    channel_table, channel_columns = _best_table(
        connection,
        required={"id", "name"},
        preferred_names=("content_channelmetadata", "channelmetadata"),
        optional_score={"description", "tagline", "author", "version", "root_id"},
    )
    language_table, language_columns = _best_table(
        connection,
        required={"id"},
        preferred_names=("content_language", "language"),
        optional_score={"lang_code", "lang_subcode", "lang_name"},
    )
    if language_table and not ({"lang_code", "lang_name"} & set(language_columns)):
        language_table, language_columns = None, frozenset()

    return SourceSchema(
        node_table=node_table,
        channel_table=channel_table,
        language_table=language_table,
        node_columns=node_columns,
        channel_columns=channel_columns,
        language_columns=language_columns,
    )

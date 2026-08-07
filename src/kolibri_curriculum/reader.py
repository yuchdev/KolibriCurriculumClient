from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .models import Catalog, ChannelMetadata, CurriculumNode
from .schema import SourceSchema, detect_schema, quote_identifier
from .tree import enrich_tree


def _normalize(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    return value


def _text(value: Any) -> str:
    value = _normalize(value)
    return "" if value is None else str(value)


def _optional_text(value: Any) -> str | None:
    value = _normalize(value)
    return None if value is None else str(value)


def _json_value(value: Any) -> Any:
    value = _normalize(value)
    if not isinstance(value, str):
        return value
    value = value.strip()
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def open_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _select_columns(available: Iterable[str], wanted: Iterable[str]) -> list[str]:
    columns = set(available)
    return [column for column in wanted if column in columns]


def _language_map(connection: sqlite3.Connection, schema: SourceSchema) -> dict[str, str]:
    if not schema.language_table:
        return {}
    wanted = _select_columns(
        schema.language_columns,
        ("id", "lang_code", "lang_subcode", "lang_name"),
    )
    if "id" not in wanted:
        return {}
    query = (
        f"SELECT {', '.join(quote_identifier(c) for c in wanted)} "
        f"FROM {quote_identifier(schema.language_table)}"
    )
    result: dict[str, str] = {}
    for row in connection.execute(query):
        values = dict(row)
        identifier = _text(values.get("id"))
        code = _text(values.get("lang_code"))
        subcode = _text(values.get("lang_subcode"))
        name = _text(values.get("lang_name"))
        display = "-".join(part for part in (code, subcode) if part) or name or identifier
        result[identifier] = display
    return result


def _channel_metadata(
    connection: sqlite3.Connection,
    schema: SourceSchema,
    database_path: Path,
) -> ChannelMetadata:
    if schema.channel_table:
        wanted = _select_columns(
            schema.channel_columns,
            (
                "id",
                "name",
                "description",
                "tagline",
                "author",
                "version",
                "last_updated",
                "root_id",
            ),
        )
        query = (
            f"SELECT {', '.join(quote_identifier(c) for c in wanted)} "
            f"FROM {quote_identifier(schema.channel_table)} LIMIT 1"
        )
        row = connection.execute(query).fetchone()
        if row:
            values = dict(row)
            return ChannelMetadata(
                channel_id=_text(values.get("id")),
                name=_text(values.get("name")),
                description=_text(values.get("description")),
                tagline=_text(values.get("tagline")),
                author=_text(values.get("author")),
                version=int(values["version"]) if values.get("version") is not None else None,
                last_updated=_optional_text(values.get("last_updated")),
                root_id=_optional_text(values.get("root_id")),
            )

    channel_column = "channel_id" if "channel_id" in schema.node_columns else None
    if channel_column:
        row = connection.execute(
            f"SELECT {quote_identifier(channel_column)} FROM "
            f"{quote_identifier(schema.node_table)} "
            f"WHERE {quote_identifier(channel_column)} IS NOT NULL LIMIT 1"
        ).fetchone()
        if row:
            return ChannelMetadata(channel_id=_text(row[0]), name=database_path.stem)
    return ChannelMetadata(channel_id=database_path.stem, name=database_path.stem)


def inspect_channel_ids(database_path: Path) -> set[str]:
    try:
        with open_readonly(database_path) as connection:
            schema = detect_schema(connection)
            channel = _channel_metadata(connection, schema, database_path)
            ids = {channel.channel_id} if channel.channel_id else set()
            if "channel_id" in schema.node_columns:
                query = (
                    f"SELECT DISTINCT channel_id FROM {quote_identifier(schema.node_table)} "
                    "WHERE channel_id IS NOT NULL LIMIT 20"
                )
                ids.update(_text(row[0]) for row in connection.execute(query))
            return {value for value in ids if value}
    except (sqlite3.Error, ValueError, OSError):
        return set()


def read_catalog(
    database_path: Path,
    *,
    include_kinds: set[str] | None = None,
) -> Catalog:
    database_path = Path(database_path)
    if not database_path.exists():
        raise FileNotFoundError(database_path)

    with open_readonly(database_path) as connection:
        schema = detect_schema(connection)
        channel = _channel_metadata(connection, schema, database_path)
        languages = _language_map(connection, schema)

        wanted = _select_columns(
            schema.node_columns,
            (
                "id",
                "content_id",
                "channel_id",
                "parent_id",
                "parent",
                "kind",
                "title",
                "description",
                "author",
                "sort_order",
                "duration",
                "lang_id",
                "available",
                "license_name",
                "license_owner",
                "options",
                "grade_levels",
                "resource_types",
                "learning_activities",
                "categories",
                "learner_needs",
                "tree_id",
                "lft",
                "rght",
            ),
        )
        order_by = [
            column
            for column in ("tree_id", "lft", "sort_order", "title")
            if column in schema.node_columns
        ]
        query = (
            f"SELECT {', '.join(quote_identifier(c) for c in wanted)} "
            f"FROM {quote_identifier(schema.node_table)}"
        )
        if order_by:
            query += " ORDER BY " + ", ".join(quote_identifier(c) for c in order_by)

        nodes: list[CurriculumNode] = []
        for row in connection.execute(query):
            values = dict(row)
            kind = _text(values.get("kind"))
            if include_kinds is not None and kind not in include_kinds:
                continue
            node_channel_id = _text(values.get("channel_id")) or channel.channel_id
            parent_id = values.get("parent_id", values.get("parent"))
            lang_id = _optional_text(values.get("lang_id"))
            nodes.append(
                CurriculumNode(
                    node_id=_text(values.get("id")),
                    content_id=_optional_text(values.get("content_id")),
                    channel_id=node_channel_id,
                    parent_id=_optional_text(parent_id),
                    kind=kind,
                    title=_text(values.get("title")),
                    description=_text(values.get("description")),
                    author=_text(values.get("author")),
                    sort_order=(
                        float(values["sort_order"])
                        if values.get("sort_order") is not None
                        else None
                    ),
                    duration_seconds=(
                        int(values["duration"])
                        if values.get("duration") is not None
                        else None
                    ),
                    language=languages.get(lang_id, lang_id) if lang_id else None,
                    available=(
                        bool(values["available"])
                        if values.get("available") is not None
                        else None
                    ),
                    license_name=_optional_text(values.get("license_name")),
                    license_owner=_optional_text(values.get("license_owner")),
                    options=_json_value(values.get("options")),
                    grade_levels=_optional_text(values.get("grade_levels")),
                    resource_types=_optional_text(values.get("resource_types")),
                    learning_activities=_optional_text(values.get("learning_activities")),
                    categories=_optional_text(values.get("categories")),
                    learner_needs=_optional_text(values.get("learner_needs")),
                    tree_id=int(values["tree_id"]) if values.get("tree_id") is not None else None,
                    left=int(values["lft"]) if values.get("lft") is not None else None,
                    right=int(values["rght"]) if values.get("rght") is not None else None,
                )
            )

    return Catalog(
        channel=channel,
        nodes=enrich_tree(nodes),
        source_database=database_path.resolve(),
    )

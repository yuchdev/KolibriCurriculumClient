from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import Catalog, CurriculumNode, SyncSummary, utc_now_iso

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tagline TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    version INTEGER,
    last_updated TEXT,
    root_id TEXT,
    source_database TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodes (
    channel_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    content_id TEXT,
    parent_id TEXT,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    sort_order REAL,
    duration_seconds INTEGER,
    language TEXT,
    available INTEGER,
    license_name TEXT,
    license_owner TEXT,
    options_json TEXT,
    grade_levels TEXT,
    resource_types TEXT,
    learning_activities TEXT,
    categories TEXT,
    learner_needs TEXT,
    tree_id INTEGER,
    lft INTEGER,
    rght INTEGER,
    depth INTEGER NOT NULL,
    path_json TEXT NOT NULL,
    path_text TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (channel_id, node_id),
    FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_nodes_parent ON nodes(channel_id, parent_id, is_active);
CREATE INDEX IF NOT EXISTS ix_nodes_content ON nodes(channel_id, content_id);
CREATE INDEX IF NOT EXISTS ix_nodes_kind ON nodes(channel_id, kind, is_active);
CREATE INDEX IF NOT EXISTS ix_nodes_path ON nodes(channel_id, path_text);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    source_database TEXT NOT NULL,
    node_count INTEGER NOT NULL,
    added INTEGER NOT NULL,
    modified INTEGER NOT NULL,
    moved INTEGER NOT NULL,
    removed INTEGER NOT NULL,
    unchanged INTEGER NOT NULL,
    FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS changes (
    change_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    channel_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    change_type TEXT NOT NULL CHECK(change_type IN ('added', 'modified', 'moved', 'removed')),
    old_hash TEXT,
    new_hash TEXT,
    old_parent_id TEXT,
    new_parent_id TEXT,
    old_path TEXT,
    new_path TEXT,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_changes_snapshot ON changes(snapshot_id, change_type);
CREATE INDEX IF NOT EXISTS ix_changes_node ON changes(channel_id, node_id);
"""


class CatalogRepository:
    def __init__(self, database_path: Path | str, *, initialize: bool = True):
        self.database_path = Path(database_path)
        if initialize:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self.initialize()
        elif not self.database_path.exists():
            raise FileNotFoundError(self.database_path)

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            connection = sqlite3.connect(
                f"file:{self.database_path.resolve()}?mode=ro",
                uri=True,
            )
        else:
            connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(_SCHEMA)
            self._ensure_fts(connection)

    @staticmethod
    def _ensure_fts(connection: sqlite3.Connection) -> None:
        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                    channel_id UNINDEXED,
                    node_id UNINDEXED,
                    title,
                    description,
                    path_text
                )
                """
            )
        except sqlite3.OperationalError:
            pass

    @staticmethod
    def _node_values(node: CurriculumNode, now: str) -> tuple[Any, ...]:
        return (
            node.channel_id,
            node.node_id,
            node.content_id,
            node.parent_id,
            node.kind,
            node.title,
            node.description,
            node.author,
            node.sort_order,
            node.duration_seconds,
            node.language,
            None if node.available is None else int(node.available),
            node.license_name,
            node.license_owner,
            json.dumps(node.options, ensure_ascii=False, default=str),
            node.grade_levels,
            node.resource_types,
            node.learning_activities,
            node.categories,
            node.learner_needs,
            node.tree_id,
            node.left,
            node.right,
            node.depth,
            json.dumps(node.path, ensure_ascii=False),
            node.path_text,
            node.row_hash,
            now,
            now,
        )

    def sync_catalog(self, catalog: Catalog, export_directory: Path | str = "") -> SyncSummary:
        now = utc_now_iso()
        channel_id = catalog.channel.channel_id
        current_nodes = {node.node_id: node for node in catalog.nodes}

        with self.transaction() as connection:
            existing_rows = connection.execute(
                """
                SELECT node_id, row_hash, parent_id, path_text, is_active
                FROM nodes WHERE channel_id = ?
                """,
                (channel_id,),
            ).fetchall()
            existing = {str(row["node_id"]): row for row in existing_rows}

            added: list[CurriculumNode] = []
            modified: list[tuple[CurriculumNode, sqlite3.Row]] = []
            moved: list[tuple[CurriculumNode, sqlite3.Row]] = []
            unchanged = 0
            for node in catalog.nodes:
                old = existing.get(node.node_id)
                if old is None or not bool(old["is_active"]):
                    added.append(node)
                elif old["row_hash"] == node.row_hash:
                    unchanged += 1
                elif old["parent_id"] != node.parent_id or old["path_text"] != node.path_text:
                    moved.append((node, old))
                else:
                    modified.append((node, old))

            removed_ids = [
                node_id
                for node_id, row in existing.items()
                if bool(row["is_active"]) and node_id not in current_nodes
            ]

            channel = catalog.channel
            connection.execute(
                """
                INSERT INTO channels (
                    channel_id, name, description, tagline, author, version,
                    last_updated, root_id, source_database, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    tagline=excluded.tagline,
                    author=excluded.author,
                    version=excluded.version,
                    last_updated=excluded.last_updated,
                    root_id=excluded.root_id,
                    source_database=excluded.source_database,
                    updated_at=excluded.updated_at
                """,
                (
                    channel.channel_id,
                    channel.name,
                    channel.description,
                    channel.tagline,
                    channel.author,
                    channel.version,
                    channel.last_updated,
                    channel.root_id,
                    str(catalog.source_database),
                    now,
                ),
            )

            node_sql = """
                INSERT INTO nodes (
                    channel_id, node_id, content_id, parent_id, kind, title,
                    description, author, sort_order, duration_seconds, language,
                    available, license_name, license_owner, options_json,
                    grade_levels, resource_types, learning_activities, categories,
                    learner_needs, tree_id, lft, rght, depth, path_json, path_text,
                    row_hash, is_active, first_seen_at, last_seen_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, 1, ?, ?
                )
                ON CONFLICT(channel_id, node_id) DO UPDATE SET
                    content_id=excluded.content_id,
                    parent_id=excluded.parent_id,
                    kind=excluded.kind,
                    title=excluded.title,
                    description=excluded.description,
                    author=excluded.author,
                    sort_order=excluded.sort_order,
                    duration_seconds=excluded.duration_seconds,
                    language=excluded.language,
                    available=excluded.available,
                    license_name=excluded.license_name,
                    license_owner=excluded.license_owner,
                    options_json=excluded.options_json,
                    grade_levels=excluded.grade_levels,
                    resource_types=excluded.resource_types,
                    learning_activities=excluded.learning_activities,
                    categories=excluded.categories,
                    learner_needs=excluded.learner_needs,
                    tree_id=excluded.tree_id,
                    lft=excluded.lft,
                    rght=excluded.rght,
                    depth=excluded.depth,
                    path_json=excluded.path_json,
                    path_text=excluded.path_text,
                    row_hash=excluded.row_hash,
                    is_active=1,
                    last_seen_at=excluded.last_seen_at
            """
            connection.executemany(node_sql, [self._node_values(node, now) for node in catalog.nodes])

            if removed_ids:
                placeholders = ",".join("?" for _ in removed_ids)
                connection.execute(
                    f"UPDATE nodes SET is_active=0, last_seen_at=? "
                    f"WHERE channel_id=? AND node_id IN ({placeholders})",
                    (now, channel_id, *removed_ids),
                )

            cursor = connection.execute(
                """
                INSERT INTO snapshots (
                    channel_id, imported_at, source_database, node_count,
                    added, modified, moved, removed, unchanged
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    channel_id,
                    now,
                    str(catalog.source_database),
                    len(catalog.nodes),
                    len(added),
                    len(modified),
                    len(moved),
                    len(removed_ids),
                    unchanged,
                ),
            )
            snapshot_id = int(cursor.lastrowid)

            change_rows: list[tuple[Any, ...]] = []
            for node in added:
                change_rows.append(
                    (snapshot_id, channel_id, node.node_id, "added", None, node.row_hash,
                     None, node.parent_id, None, node.path_text)
                )
            for node, old in modified:
                change_rows.append(
                    (snapshot_id, channel_id, node.node_id, "modified", old["row_hash"],
                     node.row_hash, old["parent_id"], node.parent_id, old["path_text"],
                     node.path_text)
                )
            for node, old in moved:
                change_rows.append(
                    (snapshot_id, channel_id, node.node_id, "moved", old["row_hash"],
                     node.row_hash, old["parent_id"], node.parent_id, old["path_text"],
                     node.path_text)
                )
            for node_id in removed_ids:
                old = existing[node_id]
                change_rows.append(
                    (snapshot_id, channel_id, node_id, "removed", old["row_hash"], None,
                     old["parent_id"], None, old["path_text"], None)
                )
            connection.executemany(
                """
                INSERT INTO changes (
                    snapshot_id, channel_id, node_id, change_type,
                    old_hash, new_hash, old_parent_id, new_parent_id, old_path, new_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                change_rows,
            )
            self._rebuild_fts(connection, channel_id)

        return SyncSummary(
            channel_id=channel_id,
            snapshot_id=snapshot_id,
            node_count=len(catalog.nodes),
            added=len(added),
            modified=len(modified),
            moved=len(moved),
            removed=len(removed_ids),
            unchanged=unchanged,
            database_path=str(self.database_path.resolve()),
            export_directory=str(Path(export_directory).resolve()) if export_directory else "",
        )

    @staticmethod
    def _rebuild_fts(connection: sqlite3.Connection, channel_id: str) -> None:
        try:
            connection.execute("DELETE FROM nodes_fts WHERE channel_id=?", (channel_id,))
            connection.execute(
                """
                INSERT INTO nodes_fts(channel_id, node_id, title, description, path_text)
                SELECT channel_id, node_id, title, description, path_text
                FROM nodes WHERE channel_id=? AND is_active=1
                """,
                (channel_id,),
            )
        except sqlite3.OperationalError:
            pass

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        for key in ("path_json", "options_json"):
            if key in data and isinstance(data[key], str):
                try:
                    data[key.removesuffix("_json") if key == "path_json" else "options"] = json.loads(data[key])
                except json.JSONDecodeError:
                    pass
        data.pop("path_json", None)
        data.pop("options_json", None)
        if "available" in data and data["available"] is not None:
            data["available"] = bool(data["available"])
        if "is_active" in data:
            data["is_active"] = bool(data["is_active"])
        return data

    def get_node(self, channel_id: str, node_id: str, *, include_inactive: bool = False) -> dict | None:
        where_active = "" if include_inactive else " AND is_active=1"
        with self.connect(readonly=True) as connection:
            row = connection.execute(
                f"SELECT * FROM nodes WHERE channel_id=? AND node_id=?{where_active}",
                (channel_id, node_id),
            ).fetchone()
            return self._row_to_dict(row) if row else None

    def list_children(self, channel_id: str, parent_id: str | None) -> list[dict]:
        with self.connect(readonly=True) as connection:
            if parent_id is None:
                rows = connection.execute(
                    """
                    SELECT * FROM nodes
                    WHERE channel_id=? AND parent_id IS NULL AND is_active=1
                    ORDER BY tree_id, lft, sort_order, title
                    """,
                    (channel_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM nodes
                    WHERE channel_id=? AND parent_id=? AND is_active=1
                    ORDER BY tree_id, lft, sort_order, title
                    """,
                    (channel_id, parent_id),
                ).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def get_subtree(self, channel_id: str, node_id: str, max_depth: int | None = None) -> list[dict]:
        root = self.get_node(channel_id, node_id)
        if root is None:
            return []
        base_depth = int(root["depth"])
        depth_clause = ""
        depth_params: list[Any] = []
        if max_depth is not None:
            depth_clause = " AND depth <= ?"
            depth_params.append(base_depth + max_depth)

        with self.connect(readonly=True) as connection:
            if root.get("tree_id") is not None and root.get("lft") is not None and root.get("rght") is not None:
                rows = connection.execute(
                    """
                    SELECT * FROM nodes
                    WHERE channel_id=? AND is_active=1
                      AND tree_id=? AND lft>=? AND rght<=?
                    """ + depth_clause + " ORDER BY tree_id, lft, sort_order, title",
                    [
                        channel_id,
                        root["tree_id"],
                        root["lft"],
                        root["rght"],
                        *depth_params,
                    ],
                ).fetchall()
            else:
                escaped = (
                    str(root["path_text"])
                    .replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                rows = connection.execute(
                    """
                    SELECT * FROM nodes
                    WHERE channel_id=? AND is_active=1
                      AND (path_text=? OR path_text LIKE ? ESCAPE '\\')
                    """ + depth_clause + " ORDER BY tree_id, lft, sort_order, title",
                    [channel_id, root["path_text"], escaped + " / %", *depth_params],
                ).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def search(self, query: str, channel_id: str | None = None, limit: int = 20) -> list[dict]:
        tokens = re.findall(r"[\w-]+", query, flags=re.UNICODE)
        if not tokens:
            return []
        with self.connect(readonly=True) as connection:
            try:
                match = " AND ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
                sql = """
                    SELECT n.* FROM nodes_fts f
                    JOIN nodes n ON n.channel_id=f.channel_id AND n.node_id=f.node_id
                    WHERE nodes_fts MATCH ? AND n.is_active=1
                """
                params: list[Any] = [match]
                if channel_id:
                    sql += " AND n.channel_id=?"
                    params.append(channel_id)
                sql += " ORDER BY bm25(nodes_fts), n.depth, n.title LIMIT ?"
                params.append(limit)
                rows = connection.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                pattern = "%" + "%".join(tokens) + "%"
                sql = """
                    SELECT * FROM nodes
                    WHERE is_active=1 AND (
                        title LIKE ? OR description LIKE ? OR path_text LIKE ?
                    )
                """
                params = [pattern, pattern, pattern]
                if channel_id:
                    sql += " AND channel_id=?"
                    params.append(channel_id)
                sql += " ORDER BY depth, title LIMIT ?"
                params.append(limit)
                rows = connection.execute(sql, params).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def list_channels(self) -> list[dict]:
        with self.connect(readonly=True) as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM channels ORDER BY name")]

    def list_changes(
        self,
        *,
        channel_id: str | None = None,
        snapshot_id: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if channel_id:
            clauses.append("channel_id=?")
            params.append(channel_id)
        if snapshot_id is not None:
            clauses.append("snapshot_id=?")
            params.append(snapshot_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        with self.connect(readonly=True) as connection:
            rows = connection.execute(
                "SELECT * FROM changes" + where + " ORDER BY change_id DESC LIMIT ?",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

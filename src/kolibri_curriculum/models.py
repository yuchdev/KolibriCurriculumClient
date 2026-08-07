from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class ChannelMetadata:
    channel_id: str
    name: str = ""
    description: str = ""
    tagline: str = ""
    author: str = ""
    version: int | None = None
    last_updated: str | None = None
    root_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CurriculumNode:
    node_id: str
    content_id: str | None
    channel_id: str
    parent_id: str | None
    kind: str
    title: str
    description: str = ""
    author: str = ""
    sort_order: float | None = None
    duration_seconds: int | None = None
    language: str | None = None
    available: bool | None = None
    license_name: str | None = None
    license_owner: str | None = None
    options: Any = None
    grade_levels: str | None = None
    resource_types: str | None = None
    learning_activities: str | None = None
    categories: str | None = None
    learner_needs: str | None = None
    tree_id: int | None = None
    left: int | None = None
    right: int | None = None
    depth: int = 0
    path: list[str] = field(default_factory=list)
    row_hash: str = ""

    @property
    def path_text(self) -> str:
        return " / ".join(self.path)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path_text"] = self.path_text
        return data


@dataclass(slots=True)
class Catalog:
    channel: ChannelMetadata
    nodes: list[CurriculumNode]
    source_database: Path
    exported_at: str = field(default_factory=utc_now_iso)

    def to_manifest(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        max_depth = 0
        for node in self.nodes:
            kinds[node.kind] = kinds.get(node.kind, 0) + 1
            max_depth = max(max_depth, node.depth)
        return {
            "format_version": 1,
            "exported_at": self.exported_at,
            "source_database": str(self.source_database),
            "channel": self.channel.to_dict(),
            "node_count": len(self.nodes),
            "max_depth": max_depth,
            "kinds": dict(sorted(kinds.items())),
        }


@dataclass(slots=True)
class SyncSummary:
    channel_id: str
    snapshot_id: int
    node_count: int
    added: int
    modified: int
    moved: int
    removed: int
    unchanged: int
    database_path: str
    export_directory: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

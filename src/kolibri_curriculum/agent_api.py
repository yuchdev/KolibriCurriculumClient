from __future__ import annotations

from pathlib import Path
from typing import Any

from .repository import CatalogRepository


class CatalogQueryService:
    """Read-only, allowlisted operations suitable for a future agent tool layer.

    The service intentionally does not expose arbitrary SQL. An agent adapter can
    serialize these methods as function tools without granting write access or
    filesystem access to the model.
    """

    def __init__(self, database_path: Path | str):
        self.repository = CatalogRepository(database_path, initialize=False)

    def channels(self) -> list[dict[str, Any]]:
        return self.repository.list_channels()

    def search(
        self,
        query: str,
        *,
        channel_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self.repository.search(query, channel_id=channel_id, limit=min(limit, 100))

    def node(self, channel_id: str, node_id: str) -> dict[str, Any] | None:
        return self.repository.get_node(channel_id, node_id)

    def children(self, channel_id: str, parent_id: str | None) -> list[dict[str, Any]]:
        return self.repository.list_children(channel_id, parent_id)

    def subtree(
        self,
        channel_id: str,
        node_id: str,
        *,
        max_depth: int = 3,
    ) -> list[dict[str, Any]]:
        return self.repository.get_subtree(channel_id, node_id, max_depth=min(max_depth, 10))

    def recent_changes(
        self,
        *,
        channel_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.repository.list_changes(channel_id=channel_id, limit=min(limit, 200))

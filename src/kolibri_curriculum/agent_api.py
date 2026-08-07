from __future__ import annotations

from pathlib import Path
from typing import Any

from .repository import CatalogRepository

_MAX_ID_LENGTH = 256
_MAX_QUERY_LENGTH = 512
_MAX_LIMIT = 100
_MAX_DEPTH = 10
_MAX_DESCRIPTION_LENGTH = 2000
_PATH_KEYS = {"source_database", "database_path", "export_directory"}


def _validate_identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    if len(normalized) > _MAX_ID_LENGTH:
        raise ValueError(f"{field} exceeds max length {_MAX_ID_LENGTH}")
    return normalized


def _bounded_limit(
    value: int,
    *,
    field: str = "limit",
    upper: int = _MAX_LIMIT,
    lower: int = 1,
) -> int:
    if not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < lower:
        raise ValueError(f"{field} must be >= {lower}")
    return min(value, upper)


def _truncate_description(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= _MAX_DESCRIPTION_LENGTH:
        return value
    return value[: _MAX_DESCRIPTION_LENGTH - 1] + "…"


def _sanitize_record(record: dict[str, Any]) -> dict[str, Any]:
    sanitized = {key: value for key, value in record.items() if key not in _PATH_KEYS}
    if "description" in sanitized:
        sanitized["description"] = _truncate_description(sanitized["description"])
    return sanitized


class CatalogQueryService:
    """Read-only, allowlisted operations suitable for a future agent tool layer.

    The service intentionally does not expose arbitrary SQL. An agent adapter can
    serialize these methods as function tools without granting write access or
    filesystem access to the model.
    """

    def __init__(self, database_path: Path | str):
        self.repository = CatalogRepository(database_path, initialize=False)

    def channels(self) -> list[dict[str, Any]]:
        return [_sanitize_record(channel) for channel in self.repository.list_channels()]

    def search(
        self,
        query: str,
        *,
        channel_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        query = query.strip()
        if not query:
            raise ValueError("query cannot be empty")
        if len(query) > _MAX_QUERY_LENGTH:
            raise ValueError(f"query exceeds max length {_MAX_QUERY_LENGTH}")
        normalized_channel_id = (
            _validate_identifier(channel_id, field="channel_id") if channel_id is not None else None
        )
        bounded_limit = _bounded_limit(limit)
        return [
            _sanitize_record(row)
            for row in self.repository.search(
                query,
                channel_id=normalized_channel_id,
                limit=bounded_limit,
            )
        ]

    def node(self, channel_id: str, node_id: str) -> dict[str, Any] | None:
        result = self.repository.get_node(
            _validate_identifier(channel_id, field="channel_id"),
            _validate_identifier(node_id, field="node_id"),
        )
        return _sanitize_record(result) if result is not None else None

    def children(self, channel_id: str, parent_id: str | None) -> list[dict[str, Any]]:
        normalized_parent_id = (
            _validate_identifier(parent_id, field="parent_id") if parent_id is not None else None
        )
        return [
            _sanitize_record(row)
            for row in self.repository.list_children(
                _validate_identifier(channel_id, field="channel_id"),
                normalized_parent_id,
            )
        ]

    def subtree(
        self,
        channel_id: str,
        node_id: str,
        *,
        max_depth: int = 3,
    ) -> list[dict[str, Any]]:
        bounded_depth = _bounded_limit(max_depth, field="max_depth", upper=_MAX_DEPTH, lower=0)
        return [
            _sanitize_record(row)
            for row in self.repository.get_subtree(
                _validate_identifier(channel_id, field="channel_id"),
                _validate_identifier(node_id, field="node_id"),
                max_depth=bounded_depth,
            )
        ]

    def recent_changes(
        self,
        *,
        channel_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        normalized_channel_id = (
            _validate_identifier(channel_id, field="channel_id") if channel_id is not None else None
        )
        bounded_limit = _bounded_limit(limit)
        return [
            _sanitize_record(change)
            for change in self.repository.list_changes(
                channel_id=normalized_channel_id,
                limit=bounded_limit,
            )
        ]

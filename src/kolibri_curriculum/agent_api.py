from __future__ import annotations

from pathlib import Path
from typing import Any

from .discovery import ChannelDiscovery, language_display_name
from .repository import CatalogRepository
from .resolver import ResolvedChannel, SourceResolver
from .source_registry import SourceDefinition

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

    Source-aware methods are available when a ``ChannelDiscovery`` backend is
    supplied at construction time.  Without one, source/language resolution will
    return empty results gracefully.
    """

    def __init__(
        self,
        database_path: Path | str,
        discovery: ChannelDiscovery | None = None,
    ):
        self.repository = CatalogRepository(database_path, initialize=False)
        self._resolver = SourceResolver(discovery=discovery)

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

    # ------------------------------------------------------------------
    # Source-aware agent methods
    # ------------------------------------------------------------------

    def sources(
        self,
        *,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return a list of known educational sources.

        Each entry contains ``provider_id``, ``name``, ``languages``, and
        ``channel_count``.  No channel IDs are included.
        """
        lang = _validate_identifier(language, field="language") if language else None
        return [s.to_dict() for s in self._resolver.list_sources(language=lang)]

    def source(self, name: str) -> dict[str, Any]:
        """Resolve a source name/alias and return its definition.

        Returns a dict with ``provider_id``, ``display_name``, and ``aliases``.
        Raises ``ValueError`` if not found or ambiguous.
        """
        name = _validate_identifier(name, field="name")
        source_def = self._resolver.resolve_source(name)
        return {
            "provider_id": source_def.provider_id,
            "display_name": source_def.display_name,
            "aliases": list(source_def.aliases),
        }

    def source_languages(self, name: str) -> list[dict[str, Any]]:
        """Return the languages available for a source.

        Each entry contains ``code`` and ``name``.
        """
        name = _validate_identifier(name, field="name")
        codes = self._resolver.available_languages(name)
        return [{"code": code, "name": language_display_name(code)} for code in codes]

    def resolve_source(
        self,
        name: str,
        *,
        language: str | None = None,
        variant: str | None = None,
    ) -> dict[str, Any]:
        """Resolve source + language + optional variant to a ``ResolvedChannel`` dict.

        The returned dict includes ``channel_id`` for internal use, along with
        ``provider_id``, ``provider_name``, ``language_code``, ``language_name``,
        and ``variant``.
        """
        name = _validate_identifier(name, field="name")
        resolved = self._resolver.resolve_channel(
            name,
            language=language,
            variant=variant,
        )
        return resolved.to_dict()

    def search_source(
        self,
        query: str,
        source: str,
        *,
        language: str | None = None,
        variant: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search within a specific source (resolved by name + language).

        Every returned node includes ``channel_id`` and ``node_id`` for
        authoritative references.
        """
        query = _validate_identifier(query, field="query")
        source = _validate_identifier(source, field="source")
        bounded_limit = _bounded_limit(limit)
        resolved = self._resolver.resolve_channel(source, language=language, variant=variant)
        return [
            _sanitize_record(row)
            for row in self.repository.search(
                query,
                channel_id=resolved.channel_id,
                limit=bounded_limit,
            )
        ]

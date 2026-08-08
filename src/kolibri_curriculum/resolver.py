"""Source resolver: maps human-readable source names + languages to channel IDs.

Resolution is deterministic and conservative – it never silently picks among
ambiguous matches.
"""
from __future__ import annotations

from dataclasses import dataclass

from .discovery import (
    ChannelDiscovery,
    DiscoveredChannel,
    NullDiscovery,
    language_display_name,
    resolve_language_code,
)
from .source_registry import (
    SourceDefinition,
    all_sources,
    lookup_source,
    suggest_sources,
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedChannel:
    """The result of resolving a source + language (+ optional variant)."""

    provider_id: str
    provider_name: str
    channel_id: str
    channel_name: str
    language_code: str | None
    language_name: str | None
    variant: str | None

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "language_code": self.language_code,
            "language_name": self.language_name,
            "variant": self.variant,
        }


@dataclass(frozen=True, slots=True)
class Source:
    """A source as seen by the user (no internal channel IDs)."""

    provider_id: str
    display_name: str
    languages: list[str]
    channel_count: int

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "name": self.display_name,
            "languages": self.languages,
            "channel_count": self.channel_count,
        }


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SourceResolutionError(ValueError):
    """Raised when source resolution fails with a user-facing message."""


class AmbiguousSourceError(SourceResolutionError):
    """Multiple sources matched."""


class UnknownSourceError(SourceResolutionError):
    """No source matched."""


class LanguageUnavailableError(SourceResolutionError):
    """The source does not expose a channel for the requested language."""


class MissingLanguageError(SourceResolutionError):
    """Source has multiple languages but none was specified."""


class AmbiguousVariantError(SourceResolutionError):
    """Multiple channels match; a variant is required."""


class UnknownVariantError(SourceResolutionError):
    """The specified variant was not found."""


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class SourceResolver:
    """Resolve human-readable source / language / variant to a channel ID.

    Parameters
    ----------
    discovery:
        A ``ChannelDiscovery`` backend that returns available channels.
        Defaults to ``NullDiscovery`` (empty list) so the resolver can be used
        even when no discovery catalog is available.
    """

    def __init__(self, discovery: ChannelDiscovery | None = None) -> None:
        self._discovery: ChannelDiscovery = discovery or NullDiscovery()
        self._cached_channels: list[DiscoveredChannel] | None = None

    # ------------------------------------------------------------------
    # Public API (mirrors the suggested interface from the issue)
    # ------------------------------------------------------------------

    def list_sources(
        self,
        *,
        language: str | None = None,
        installed: bool | None = None,  # noqa: ARG002 – reserved for future use
    ) -> list[Source]:
        """Return all known sources, optionally filtered by language."""
        channels = self._get_channels()
        # Build a map: provider_id -> list of DiscoveredChannel
        by_provider: dict[str, list[DiscoveredChannel]] = {}
        for ch in channels:
            by_provider.setdefault(ch.provider_id, []).append(ch)

        # Also include providers from the registry that have no discovered channels
        known_ids = {s.provider_id for s in all_sources()}

        result: list[Source] = []
        seen_ids: set[str] = set()

        for pid, provider_channels in by_provider.items():
            if language:
                lang_code = resolve_language_code(language) or language.lower()
                provider_channels = [
                    c for c in provider_channels if c.language_code == lang_code
                ]
                if not provider_channels:
                    continue
            langs = sorted(
                {c.language_code for c in provider_channels if c.language_code}
            )
            source_def = lookup_source(pid)
            name = source_def.display_name if source_def else (provider_channels[0].provider_name or pid)
            result.append(
                Source(
                    provider_id=pid,
                    display_name=name,
                    languages=langs,
                    channel_count=len(provider_channels),
                )
            )
            seen_ids.add(pid)

        # Add known registry providers that had no discovered channels
        if not language:
            for source_def in all_sources():
                if source_def.provider_id not in seen_ids and source_def.provider_id != "generic":
                    result.append(
                        Source(
                            provider_id=source_def.provider_id,
                            display_name=source_def.display_name,
                            languages=[],
                            channel_count=0,
                        )
                    )

        return result

    def resolve_source(self, query: str) -> SourceDefinition:
        """Resolve a source name/alias to a ``SourceDefinition``.

        Raises
        ------
        UnknownSourceError
            If no source matches (with did-you-mean suggestions).
        AmbiguousSourceError
            If the query is a partial match that hits multiple sources.
        """
        # Try exact / alias match first
        exact = lookup_source(query)
        if exact is not None:
            return exact

        # Try unique substring match against display names
        q = query.strip().lower()
        partial_matches = [
            s for s in all_sources() if q in s.display_name.lower()
        ]

        # Also check against provider_ids
        if not partial_matches:
            partial_matches = [
                s for s in all_sources() if q in s.provider_id.lower()
            ]

        if len(partial_matches) == 1:
            return partial_matches[0]

        if len(partial_matches) > 1:
            names = "\n  ".join(s.display_name for s in partial_matches)
            raise AmbiguousSourceError(
                f'"{query}" matches multiple sources:\n\n  {names}\n\n'
                "Please provide a more specific source name."
            )

        # No matches at all – produce did-you-mean
        suggestions = suggest_sources(query)
        if suggestions:
            names = "\n  ".join(s.display_name for s in suggestions)
            raise UnknownSourceError(
                f'Educational source "{query}" was not found.\n\n'
                f"Did you mean:\n\n  {names}\n\n"
                "List available sources with:\n  curriculum sources"
            )
        raise UnknownSourceError(
            f'Educational source "{query}" was not found.\n\n'
            "List available sources with:\n  curriculum sources"
        )

    def available_languages(self, source: str) -> list[str]:
        """Return language codes available for the given source name/alias."""
        source_def = self.resolve_source(source)
        channels = self._get_channels()
        codes = sorted(
            {
                c.language_code
                for c in channels
                if c.provider_id == source_def.provider_id and c.language_code
            }
        )
        return codes

    def available_channels(
        self,
        source: str,
        *,
        language: str | None = None,
    ) -> list[DiscoveredChannel]:
        """Return discovered channels for a source, optionally filtered by language."""
        source_def = self.resolve_source(source)
        channels = [
            c for c in self._get_channels() if c.provider_id == source_def.provider_id
        ]
        if language:
            lang_code = resolve_language_code(language) or language.lower()
            channels = [c for c in channels if c.language_code == lang_code]
        return channels

    def resolve_channel(
        self,
        source: str,
        *,
        language: str | None = None,
        variant: str | None = None,
    ) -> ResolvedChannel:
        """Resolve source + language (+ optional variant) to a ``ResolvedChannel``.

        Raises various ``SourceResolutionError`` subclasses on failure.
        """
        source_def = self.resolve_source(source)
        candidates = [
            c for c in self._get_channels() if c.provider_id == source_def.provider_id
        ]

        if not candidates:
            raise LanguageUnavailableError(
                f'No channels are available for "{source_def.display_name}".\n\n'
                "Run 'curriculum sources --refresh' to update the catalog."
            )

        # Apply language filter
        if language:
            lang_code = resolve_language_code(language)
            if lang_code is None:
                raise LanguageUnavailableError(
                    f'Unknown language "{language}".'
                )
            filtered = [c for c in candidates if c.language_code == lang_code]
            if not filtered:
                available = sorted({c.language_code for c in candidates if c.language_code})
                avail_str = "\n  ".join(
                    f"{code}  {language_display_name(code)}" for code in available
                )
                raise LanguageUnavailableError(
                    f'{source_def.display_name} does not currently expose a discovered '
                    f'channel for "{language}".\n\n'
                    f"Available languages:\n\n  {avail_str}"
                )
            candidates = filtered
        else:
            # If multiple languages are available, require one
            langs = sorted({c.language_code for c in candidates if c.language_code})
            if len(langs) > 1:
                lang_str = "\n  ".join(
                    f"{code}  {language_display_name(code)}" for code in langs
                )
                raise MissingLanguageError(
                    f"{source_def.display_name} is available in multiple languages:\n\n"
                    f"  {lang_str}\n\n"
                    "Specify one with:\n"
                    f'  curriculum sync "{source_def.display_name}" --language LANGUAGE'
                )

        # Apply variant filter
        if variant:
            var_lower = variant.strip().lower()
            var_candidates = [
                c for c in candidates if (c.variant or "").lower() == var_lower
            ]
            if not var_candidates:
                variants = sorted({c.variant for c in candidates if c.variant})
                vstr = "\n  ".join(variants) if variants else "(none)"
                raise UnknownVariantError(
                    f'Variant "{variant}" was not found for '
                    f"{source_def.display_name}.\n\nAvailable:\n\n  {vstr}"
                )
            candidates = var_candidates

        if len(candidates) > 1:
            # Multiple variants – require user to specify
            variants = sorted({c.variant for c in candidates if c.variant})
            if variants:
                vstr = "\n  ".join(variants)
                raise AmbiguousVariantError(
                    f"Multiple {source_def.display_name} channels match.\n\n"
                    f"VARIANT\n  {vstr}\n\n"
                    "Specify one with:\n"
                    '  --variant "VARIANT_NAME"'
                )
            # No variant metadata – just pick the first (edge case)
            candidates = [candidates[0]]

        ch = candidates[0]
        return ResolvedChannel(
            provider_id=ch.provider_id,
            provider_name=ch.provider_name,
            channel_id=ch.channel_id,
            channel_name=ch.channel_name,
            language_code=ch.language_code,
            language_name=language_display_name(ch.language_code) if ch.language_code else None,
            variant=ch.variant,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_channels(self) -> list[DiscoveredChannel]:
        if self._cached_channels is None:
            try:
                self._cached_channels = self._discovery.list_public_channels()
            except Exception:
                self._cached_channels = []
        return self._cached_channels

    def invalidate_cache(self) -> None:
        """Force re-fetch from the discovery backend on next access."""
        self._cached_channels = None

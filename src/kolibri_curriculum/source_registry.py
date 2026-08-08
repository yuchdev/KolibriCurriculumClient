"""Registry of known educational source providers.

This module defines human-recognisable provider names, normalised provider IDs,
and aliases. Channel IDs are NOT stored here; they come from discovery metadata.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    """A known educational content provider."""

    provider_id: str
    display_name: str
    aliases: tuple[str, ...]


# ---------------------------------------------------------------------------
# Known providers
# ---------------------------------------------------------------------------

_REGISTRY: tuple[SourceDefinition, ...] = (
    SourceDefinition(
        provider_id="khan_academy",
        display_name="Khan Academy",
        aliases=("khan", "ka"),
    ),
    SourceDefinition(
        provider_id="ck12",
        display_name="CK-12",
        aliases=("ck12",),
    ),
    SourceDefinition(
        provider_id="openstax",
        display_name="OpenStax",
        aliases=("open stax",),
    ),
    SourceDefinition(
        provider_id="phet",
        display_name="PhET",
        aliases=("phet simulations",),
    ),
    SourceDefinition(
        provider_id="mit_blossoms",
        display_name="MIT BLOSSOMS",
        aliases=("blossoms", "mit blossoms"),
    ),
    SourceDefinition(
        provider_id="blockly_games",
        display_name="Blockly Games",
        aliases=("blockly",),
    ),
    SourceDefinition(
        provider_id="african_storybook",
        display_name="African Storybook",
        aliases=("african storybook",),
    ),
    SourceDefinition(
        provider_id="storyweaver",
        display_name="StoryWeaver",
        aliases=("story weaver",),
    ),
    SourceDefinition(
        provider_id="sikana",
        display_name="Sikana",
        aliases=(),
    ),
    SourceDefinition(
        provider_id="hp_life",
        display_name="HP LIFE",
        aliases=("hp life",),
    ),
    SourceDefinition(
        provider_id="tess",
        display_name="TESS",
        aliases=(),
    ),
    SourceDefinition(
        provider_id="generic",
        display_name="Community / Unknown",
        aliases=("community", "unknown"),
    ),
)

# Build lookup tables
_BY_PROVIDER_ID: dict[str, SourceDefinition] = {s.provider_id: s for s in _REGISTRY}
_BY_DISPLAY_NAME_LOWER: dict[str, SourceDefinition] = {
    s.display_name.lower(): s for s in _REGISTRY
}
_BY_ALIAS_LOWER: dict[str, SourceDefinition] = {}
for _source in _REGISTRY:
    for _alias in _source.aliases:
        _BY_ALIAS_LOWER[_alias.lower()] = _source


def all_sources() -> tuple[SourceDefinition, ...]:
    """Return all registered source definitions."""
    return _REGISTRY


def lookup_source(query: str) -> SourceDefinition | None:
    """Return a source definition for *query*, or ``None`` if not found.

    Resolution order:
    1. Exact display name (case-insensitive).
    2. Exact provider ID.
    3. Known alias (case-insensitive).

    Does **not** do fuzzy matching; call :func:`suggest_sources` for that.
    """
    q = query.strip().lower()
    result = (
        _BY_DISPLAY_NAME_LOWER.get(q)
        or _BY_PROVIDER_ID.get(q)
        or _BY_ALIAS_LOWER.get(q)
    )
    return result


def suggest_sources(query: str) -> list[SourceDefinition]:
    """Return sources whose display name contains *query* as a substring.

    Used only to produce "did you mean?" suggestions in error messages.
    """
    q = query.strip().lower()
    results: list[SourceDefinition] = []
    for source in _REGISTRY:
        if q in source.display_name.lower():
            results.append(source)
    return results

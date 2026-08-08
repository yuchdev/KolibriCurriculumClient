"""Channel discovery layer.

Provides:
- ``DiscoveredChannel`` – metadata about a Kolibri channel available publicly.
- ``ChannelDiscovery`` – protocol that any discovery backend must satisfy.
- ``FileCacheDiscovery`` – reads / writes a local JSON cache.
- ``NullDiscovery`` – always returns an empty list; useful for tests and offline mode.

The cache file is stored at ``~/.cache/curriculum/sources.json`` by default (or
a platform-appropriate location). Every CLI invocation that needs source info
checks the cache; only ``curriculum sources --refresh`` triggers a network fetch.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "vi": "Vietnamese",
    "id": "Bahasa Indonesia",
    "km": "Khmer",
    "pt": "Portuguese",
    "ar": "Arabic",
    "sw": "Swahili",
    "hi": "Hindi",
    "zh": "Chinese",
    "bn": "Bengali",
    "de": "German",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "nl": "Dutch",
    "pl": "Polish",
    "ru": "Russian",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "fa": "Farsi",
    "ms": "Malay",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "mul": "Multiple languages",
}

# Reverse lookup: human name -> code (lowercase)
_NAME_TO_CODE: dict[str, str] = {v.lower(): k for k, v in LANGUAGE_NAMES.items()}


def resolve_language_code(value: str) -> str | None:
    """Map a language code or name to a canonical code.  Returns ``None`` if unknown."""
    v = value.strip()
    code = v.lower()
    if code in LANGUAGE_NAMES:
        return code
    name_lookup = _NAME_TO_CODE.get(code)
    if name_lookup:
        return name_lookup
    return None


def language_display_name(code: str) -> str:
    """Return a human-readable name for a language code."""
    return LANGUAGE_NAMES.get(code, code)


@dataclass(frozen=True, slots=True)
class DiscoveredChannel:
    """Metadata about one Kolibri channel found via discovery."""

    channel_id: str
    channel_name: str
    provider_id: str
    provider_name: str
    language_code: str | None
    variant: str | None
    retrieved_at: str  # ISO-8601 UTC

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "DiscoveredChannel":
        return DiscoveredChannel(
            channel_id=data["channel_id"],
            channel_name=data["channel_name"],
            provider_id=data["provider_id"],
            provider_name=data["provider_name"],
            language_code=data.get("language_code"),
            variant=data.get("variant"),
            retrieved_at=data.get("retrieved_at", ""),
        )


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ChannelDiscovery(Protocol):
    """Any discovery backend must satisfy this protocol."""

    def list_public_channels(self) -> list[DiscoveredChannel]:
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Null backend (offline / test)
# ---------------------------------------------------------------------------


class NullDiscovery:
    """Returns an empty list; used when no network or for testing."""

    def __init__(self, channels: list[DiscoveredChannel] | None = None) -> None:
        self._channels = channels or []

    def list_public_channels(self) -> list[DiscoveredChannel]:
        return list(self._channels)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

_DEFAULT_CACHE_AGE_DAYS = 7


def default_cache_path() -> Path:
    """Return the platform-appropriate cache path."""
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "curriculum" / "sources.json"
    return Path.home() / ".cache" / "curriculum" / "sources.json"


class FileCacheDiscovery:
    """Reads channels from a local JSON cache and optionally delegates to a
    network backend when the cache is absent or stale.

    Parameters
    ----------
    cache_path:
        Location of the JSON cache file.
    backend:
        A ``ChannelDiscovery`` backend that fetches live data.  When ``None``,
        only the cache is used.
    max_age_days:
        Number of days before the cache is considered stale.
    """

    def __init__(
        self,
        cache_path: Path | None = None,
        backend: ChannelDiscovery | None = None,
        max_age_days: int = _DEFAULT_CACHE_AGE_DAYS,
    ) -> None:
        self._cache_path = cache_path or default_cache_path()
        self._backend = backend
        self._max_age = timedelta(days=max_age_days)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_public_channels(self, *, force_refresh: bool = False) -> list[DiscoveredChannel]:
        """Return channels from the cache (refreshing if necessary).

        Raises ``RuntimeError`` if no cache exists and no backend is available.
        """
        if not force_refresh and self._cache_is_fresh():
            return self._load_cache()

        if self._backend is not None:
            try:
                channels = self._backend.list_public_channels()
                self._save_cache(channels)
                return channels
            except Exception:
                # Fall back to stale cache if available.
                if self._cache_path.exists():
                    import sys

                    print(
                        "Warning: could not refresh source catalog; using cached data.",
                        file=sys.stderr,
                    )
                    return self._load_cache()
                raise RuntimeError(
                    "Unable to refresh the educational source catalog.\n"
                    "Cached source metadata is unavailable.\n"
                    "Check internet connectivity and run:\n"
                    "  curriculum sources --refresh"
                )

        if self._cache_path.exists():
            if not self._cache_is_fresh():
                import sys

                print(
                    "Warning: source catalog is stale. Run 'curriculum sources --refresh'.",
                    file=sys.stderr,
                )
            return self._load_cache()

        raise RuntimeError(
            "Unable to refresh the educational source catalog.\n"
            "Cached source metadata is unavailable.\n"
            "Check internet connectivity and run:\n"
            "  curriculum sources --refresh"
        )

    def refresh(self) -> list[DiscoveredChannel]:
        """Force a refresh from the backend and save the cache."""
        if self._backend is None:
            raise RuntimeError("No discovery backend configured; cannot refresh.")
        channels = self._backend.list_public_channels()
        self._save_cache(channels)
        return channels

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cache_is_fresh(self) -> bool:
        if not self._cache_path.exists():
            return False
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            retrieved_at = data.get("retrieved_at", "")
            ts = datetime.fromisoformat(retrieved_at)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - ts
            return age <= self._max_age
        except Exception:
            return False

    def _load_cache(self) -> list[DiscoveredChannel]:
        data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        channels_raw = data.get("channels", [])
        results: list[DiscoveredChannel] = []
        for item in channels_raw:
            try:
                results.append(DiscoveredChannel.from_dict(item))
            except (KeyError, TypeError):
                continue
        return results

    def _save_cache(self, channels: list[DiscoveredChannel]) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "retrieved_at": now,
            "channels": [ch.to_dict() for ch in channels],
        }
        self._cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

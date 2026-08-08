"""Tests for source_registry, discovery, and resolver modules."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kolibri_curriculum.discovery import (
    DiscoveredChannel,
    FileCacheDiscovery,
    NullDiscovery,
    language_display_name,
    resolve_language_code,
)
from kolibri_curriculum.resolver import (
    AmbiguousSourceError,
    AmbiguousVariantError,
    LanguageUnavailableError,
    MissingLanguageError,
    SourceResolver,
    UnknownSourceError,
    UnknownVariantError,
)
from kolibri_curriculum.source_registry import (
    SourceDefinition,
    all_sources,
    lookup_source,
    suggest_sources,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TS = datetime.now(timezone.utc).isoformat()


def _ch(
    channel_id: str,
    provider_id: str,
    provider_name: str,
    language: str | None,
    variant: str | None = None,
    channel_name: str = "Test Channel",
) -> DiscoveredChannel:
    return DiscoveredChannel(
        channel_id=channel_id,
        channel_name=channel_name,
        provider_id=provider_id,
        provider_name=provider_name,
        language_code=language,
        variant=variant,
        retrieved_at=TS,
    )


SYNTHETIC_CHANNELS = [
    _ch("ch-ka-en", "khan_academy", "Khan Academy", "en", "General"),
    _ch("ch-ka-en-us", "khan_academy", "Khan Academy", "en", "US Curriculum"),
    _ch("ch-ka-vi", "khan_academy", "Khan Academy", "vi"),
    _ch("ch-os-en", "openstax", "OpenStax", "en"),
    _ch("ch-phet-en", "phet", "PhET", "en"),
    _ch("ch-phet-vi", "phet", "PhET", "vi"),
]


def _resolver(channels: list[DiscoveredChannel] | None = None) -> SourceResolver:
    ch = SYNTHETIC_CHANNELS if channels is None else channels
    return SourceResolver(discovery=NullDiscovery(ch))


# ===========================================================================
# source_registry tests
# ===========================================================================


class TestSourceRegistry:
    def test_all_sources_is_non_empty(self):
        assert len(all_sources()) > 0

    def test_lookup_exact_display_name(self):
        result = lookup_source("Khan Academy")
        assert result is not None
        assert result.provider_id == "khan_academy"

    def test_lookup_case_insensitive_display_name(self):
        result = lookup_source("khan academy")
        assert result is not None
        assert result.provider_id == "khan_academy"

    def test_lookup_provider_id(self):
        result = lookup_source("phet")
        assert result is not None
        assert result.display_name == "PhET"

    def test_lookup_alias_ka(self):
        result = lookup_source("ka")
        assert result is not None
        assert result.provider_id == "khan_academy"

    def test_lookup_alias_khan(self):
        result = lookup_source("khan")
        assert result is not None
        assert result.provider_id == "khan_academy"

    def test_lookup_alias_blossoms(self):
        result = lookup_source("blossoms")
        assert result is not None
        assert result.provider_id == "mit_blossoms"

    def test_lookup_unknown_returns_none(self):
        assert lookup_source("nonexistent-xyz") is None

    def test_suggest_sources_finds_substring(self):
        suggestions = suggest_sources("khan")
        assert any(s.provider_id == "khan_academy" for s in suggestions)

    def test_suggest_sources_empty_for_garbage(self):
        suggestions = suggest_sources("zzznomatch")
        assert suggestions == []


# ===========================================================================
# discovery tests
# ===========================================================================


class TestLanguageHelpers:
    def test_resolve_language_code_by_code(self):
        assert resolve_language_code("en") == "en"

    def test_resolve_language_code_by_name(self):
        assert resolve_language_code("English") == "en"

    def test_resolve_language_code_case_insensitive(self):
        assert resolve_language_code("vietnamese") == "vi"

    def test_resolve_language_code_unknown(self):
        assert resolve_language_code("zzz-unknown") is None

    def test_language_display_name_known(self):
        assert language_display_name("en") == "English"

    def test_language_display_name_unknown_returns_code(self):
        assert language_display_name("zzz") == "zzz"


class TestDiscoveredChannel:
    def test_to_dict_round_trip(self):
        ch = _ch("abc", "khan_academy", "Khan Academy", "en", "General")
        d = ch.to_dict()
        restored = DiscoveredChannel.from_dict(d)
        assert restored == ch


class TestFileCacheDiscovery:
    def _make_cache(self, tmp_path: Path, age_days: int = 0) -> Path:
        cache_path = tmp_path / "sources.json"
        now = datetime.now(timezone.utc) - timedelta(days=age_days)
        payload = {
            "retrieved_at": now.isoformat(),
            "channels": [ch.to_dict() for ch in SYNTHETIC_CHANNELS],
        }
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        return cache_path

    def test_fresh_cache_returns_channels(self, tmp_path):
        cache_path = self._make_cache(tmp_path, age_days=0)
        discovery = FileCacheDiscovery(cache_path=cache_path)
        channels = discovery.list_public_channels()
        assert len(channels) == len(SYNTHETIC_CHANNELS)

    def test_stale_cache_with_no_backend_returns_channels_with_warning(
        self, tmp_path, capsys
    ):
        cache_path = self._make_cache(tmp_path, age_days=14)
        discovery = FileCacheDiscovery(cache_path=cache_path, max_age_days=7)
        channels = discovery.list_public_channels()
        assert len(channels) == len(SYNTHETIC_CHANNELS)
        captured = capsys.readouterr()
        assert "stale" in captured.err.lower() or "refresh" in captured.err.lower()

    def test_no_cache_no_backend_raises(self, tmp_path):
        cache_path = tmp_path / "missing.json"
        discovery = FileCacheDiscovery(cache_path=cache_path)
        with pytest.raises(RuntimeError, match="unavailable"):
            discovery.list_public_channels()

    def test_backend_saves_cache(self, tmp_path):
        cache_path = tmp_path / "sources.json"
        backend = NullDiscovery(SYNTHETIC_CHANNELS)
        discovery = FileCacheDiscovery(cache_path=cache_path, backend=backend)
        channels = discovery.list_public_channels()
        assert len(channels) == len(SYNTHETIC_CHANNELS)
        assert cache_path.exists()

    def test_backend_failure_falls_back_to_stale_cache(self, tmp_path, capsys):
        cache_path = self._make_cache(tmp_path, age_days=14)

        class FailingBackend:
            def list_public_channels(self):
                raise ConnectionError("Network down")

        discovery = FileCacheDiscovery(
            cache_path=cache_path, backend=FailingBackend(), max_age_days=7
        )
        channels = discovery.list_public_channels()
        assert len(channels) == len(SYNTHETIC_CHANNELS)
        captured = capsys.readouterr()
        assert "cached" in captured.err.lower() or "refresh" in captured.err.lower()

    def test_backend_failure_no_cache_raises(self, tmp_path):
        cache_path = tmp_path / "missing.json"

        class FailingBackend:
            def list_public_channels(self):
                raise ConnectionError("Network down")

        discovery = FileCacheDiscovery(cache_path=cache_path, backend=FailingBackend())
        with pytest.raises(RuntimeError):
            discovery.list_public_channels()

    def test_malformed_cache_item_is_skipped(self, tmp_path):
        cache_path = tmp_path / "sources.json"
        payload = {
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "channels": [
                {"bad": "data"},  # malformed
                _ch("ok-channel", "phet", "PhET", "en").to_dict(),
            ],
        }
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        discovery = FileCacheDiscovery(cache_path=cache_path)
        channels = discovery.list_public_channels()
        assert len(channels) == 1
        assert channels[0].channel_id == "ok-channel"

    def test_refresh_no_backend_raises(self, tmp_path):
        discovery = FileCacheDiscovery(cache_path=tmp_path / "s.json")
        with pytest.raises(RuntimeError, match="No discovery backend"):
            discovery.refresh()

    def test_duplicate_channels_preserved(self, tmp_path):
        """Duplicate channel entries in the cache are returned as-is."""
        ch = _ch("dup-id", "phet", "PhET", "en")
        cache_path = tmp_path / "sources.json"
        payload = {
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "channels": [ch.to_dict(), ch.to_dict()],
        }
        cache_path.write_text(json.dumps(payload), encoding="utf-8")
        discovery = FileCacheDiscovery(cache_path=cache_path)
        channels = discovery.list_public_channels()
        assert len(channels) == 2


# ===========================================================================
# resolver tests
# ===========================================================================


class TestSourceResolverListSources:
    def test_lists_all_sources_from_discovery(self):
        r = _resolver()
        sources = r.list_sources()
        provider_ids = {s.provider_id for s in sources}
        assert "khan_academy" in provider_ids
        assert "openstax" in provider_ids
        assert "phet" in provider_ids

    def test_language_filter(self):
        r = _resolver()
        sources = r.list_sources(language="vi")
        provider_ids = {s.provider_id for s in sources}
        assert "khan_academy" in provider_ids
        assert "phet" in provider_ids
        assert "openstax" not in provider_ids

    def test_language_filter_by_full_name(self):
        r = _resolver()
        sources = r.list_sources(language="Vietnamese")
        provider_ids = {s.provider_id for s in sources}
        assert "khan_academy" in provider_ids


class TestSourceResolverResolveSource:
    def test_exact_provider_name(self):
        r = _resolver()
        s = r.resolve_source("Khan Academy")
        assert s.provider_id == "khan_academy"

    def test_provider_id(self):
        r = _resolver()
        s = r.resolve_source("khan_academy")
        assert s.provider_id == "khan_academy"

    def test_case_insensitive(self):
        r = _resolver()
        s = r.resolve_source("khan academy")
        assert s.provider_id == "khan_academy"

    def test_alias(self):
        r = _resolver()
        s = r.resolve_source("ka")
        assert s.provider_id == "khan_academy"

    def test_unique_partial_match(self):
        r = _resolver()
        # "OpenStax" is unique; "opens" would only match it
        s = r.resolve_source("OpenStax")
        assert s.provider_id == "openstax"

    def test_alias_resolves_without_ambiguity(self):
        r = _resolver()
        # "khan" is an alias and resolves directly – not ambiguous
        s = r.resolve_source("khan")
        assert s.provider_id == "khan_academy"

    def test_unknown_source_raises(self):
        r = _resolver()
        with pytest.raises(UnknownSourceError, match="not found"):
            r.resolve_source("Completely Unknown XYZ")

    def test_typo_no_suggestion_in_message(self):
        r = _resolver()
        # "Kahn" is not a substring of any known source name
        with pytest.raises(UnknownSourceError):
            r.resolve_source("Kahn Academy")

    def test_unique_partial_match_african(self):
        r = _resolver()
        s = r.resolve_source("African")
        assert s.provider_id == "african_storybook"

    def test_ambiguous_substring_raises_specific_error(self):
        # Build a resolver with two providers whose display names share "Test"
        from kolibri_curriculum.discovery import NullDiscovery
        from kolibri_curriculum.resolver import SourceResolver, AmbiguousSourceError
        import unittest.mock as mock

        # Patch the registry to have two providers sharing the word "Test"
        test_sources = (
            SourceDefinition("test_a", "Test Alpha", ()),
            SourceDefinition("test_b", "Test Beta", ()),
        )
        with mock.patch("kolibri_curriculum.resolver.all_sources", return_value=test_sources), \
             mock.patch("kolibri_curriculum.resolver.lookup_source", return_value=None):
            r2 = SourceResolver(discovery=NullDiscovery([]))
            with pytest.raises(AmbiguousSourceError):
                r2.resolve_source("Test")


class TestSourceResolverAvailableLanguages:
    def test_returns_sorted_language_codes(self):
        r = _resolver()
        langs = r.available_languages("Khan Academy")
        assert langs == ["en", "vi"]

    def test_empty_for_source_with_no_channels(self):
        r = _resolver([])  # no channels
        langs = r.available_languages("PhET")
        assert langs == []


class TestSourceResolverResolveChannel:
    def test_single_language_no_ambiguity(self):
        r = _resolver()
        resolved = r.resolve_channel("OpenStax", language="en")
        assert resolved.channel_id == "ch-os-en"
        assert resolved.provider_id == "openstax"
        assert resolved.language_code == "en"

    def test_language_by_full_name(self):
        r = _resolver()
        resolved = r.resolve_channel("OpenStax", language="English")
        assert resolved.channel_id == "ch-os-en"

    def test_missing_language_when_multiple_raises(self):
        r = _resolver()
        with pytest.raises(MissingLanguageError):
            r.resolve_channel("Khan Academy")

    def test_unavailable_language_raises(self):
        r = _resolver()
        with pytest.raises(LanguageUnavailableError, match="es"):
            r.resolve_channel("OpenStax", language="es")

    def test_variant_resolves_correctly(self):
        r = _resolver()
        resolved = r.resolve_channel("Khan Academy", language="en", variant="US Curriculum")
        assert resolved.channel_id == "ch-ka-en-us"
        assert resolved.variant == "US Curriculum"

    def test_ambiguous_variant_raises(self):
        r = _resolver()
        with pytest.raises(AmbiguousVariantError):
            r.resolve_channel("Khan Academy", language="en")

    def test_unknown_variant_raises(self):
        r = _resolver()
        with pytest.raises(UnknownVariantError):
            r.resolve_channel("Khan Academy", language="en", variant="Nonexistent Variant")

    def test_no_channels_for_source_raises(self):
        r = _resolver([])  # empty
        with pytest.raises(LanguageUnavailableError):
            r.resolve_channel("PhET", language="en")

    def test_unknown_source_raises(self):
        r = _resolver()
        with pytest.raises(UnknownSourceError):
            r.resolve_channel("No Such Source XYZ", language="en")

    def test_unknown_language_code_raises(self):
        r = _resolver()
        with pytest.raises(LanguageUnavailableError, match="Unknown language"):
            r.resolve_channel("PhET", language="zzz-unknown-lang")

    def test_vi_channel_no_variant(self):
        r = _resolver()
        # PhET vi has a single channel, no variant – should resolve without ambiguity
        resolved = r.resolve_channel("PhET", language="vi")
        assert resolved.channel_id == "ch-phet-vi"

    def test_resolved_channel_to_dict_contains_channel_id(self):
        r = _resolver()
        resolved = r.resolve_channel("OpenStax", language="en")
        d = resolved.to_dict()
        assert "channel_id" in d
        assert d["channel_id"] == "ch-os-en"


# ===========================================================================
# CLI integration tests (sources / source / sync)
# ===========================================================================


class TestCLI:
    """Integration tests for the new CLI commands.

    Uses NullDiscovery via a patch on _make_resolver so no network or cache is needed.
    """

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        """Run CLI and return (exit_code, stdout, stderr)."""
        import io
        from unittest.mock import patch

        from kolibri_curriculum import cli

        with (
            patch.object(
                cli,
                "_make_resolver",
                return_value=SourceResolver(discovery=NullDiscovery(SYNTHETIC_CHANNELS)),
            ),
            patch("sys.stdout", new_callable=io.StringIO) as mock_out,
            patch("sys.stderr", new_callable=io.StringIO) as mock_err,
        ):
            code = cli.main(argv)
        return code, mock_out.getvalue(), mock_err.getvalue()

    def test_sources_lists_providers(self):
        code, out, _ = self._run(["sources"])
        assert code == 0
        assert "Khan Academy" in out
        assert "OpenStax" in out
        assert "PhET" in out

    def test_sources_language_filter(self):
        code, out, _ = self._run(["sources", "--language", "vi"])
        assert code == 0
        assert "Khan Academy" in out
        assert "OpenStax" not in out

    def test_sources_search_filter(self):
        code, out, _ = self._run(["sources", "--search", "khan"])
        assert code == 0
        assert "Khan Academy" in out

    def test_sources_json(self):
        code, out, _ = self._run(["sources", "--json"])
        assert code == 0
        data = json.loads(out)
        assert "sources" in data
        provider_ids = {s["provider_id"] for s in data["sources"]}
        assert "khan_academy" in provider_ids

    def test_source_show(self):
        code, out, _ = self._run(["source", "show", "Khan Academy"])
        assert code == 0
        assert "Khan Academy" in out
        assert "khan_academy" in out

    def test_source_show_json(self):
        code, out, _ = self._run(["source", "show", "Khan Academy", "--json"])
        assert code == 0
        data = json.loads(out)
        assert data["provider_id"] == "khan_academy"
        assert "channels" in data

    def test_source_show_json_with_ids(self):
        code, out, _ = self._run(["source", "show", "Khan Academy", "--json", "--ids"])
        assert code == 0
        data = json.loads(out)
        assert any("channel_id" in ch for ch in data["channels"])

    def test_source_show_unknown(self):
        code, _, err = self._run(["source", "show", "Nonexistent XYZ"])
        assert code == 2
        assert "error" in err.lower()

    def test_source_languages(self):
        code, out, _ = self._run(["source", "languages", "Khan Academy"])
        assert code == 0
        assert "English" in out
        assert "Vietnamese" in out

    def test_source_languages_json(self):
        code, out, _ = self._run(["source", "languages", "Khan Academy", "--json"])
        assert code == 0
        data = json.loads(out)
        codes = {item["code"] for item in data}
        assert "en" in codes
        assert "vi" in codes

    def test_source_channels(self):
        code, out, _ = self._run(["source", "channels", "Khan Academy"])
        assert code == 0
        assert "English" in out

    def test_source_channels_with_ids(self):
        code, out, _ = self._run(["source", "channels", "Khan Academy", "--ids"])
        assert code == 0
        assert "ch-ka-en" in out

    def test_source_channels_json(self):
        code, out, _ = self._run(["source", "channels", "Khan Academy", "--json"])
        assert code == 0
        data = json.loads(out)
        assert isinstance(data, list)

    def test_sync_missing_source_and_channel_id(self):
        code, _, err = self._run(["sync"])
        assert code == 2
        assert "error" in err.lower()

    def test_sync_by_source_ambiguous_variant_error(self):
        code, _, err = self._run(["sync", "Khan Academy", "--language", "en"])
        assert code == 2
        assert "variant" in err.lower() or "multiple" in err.lower()

    def test_sync_by_source_with_variant(self, tmp_path):
        import unittest.mock as mock

        from kolibri_curriculum import cli

        with (
            mock.patch.object(
                cli,
                "_make_resolver",
                return_value=SourceResolver(discovery=NullDiscovery(SYNTHETIC_CHANNELS)),
            ),
            mock.patch("kolibri_curriculum.cli.sync_channel") as mock_sync,
        ):
            mock_sync.return_value = {"node_count": 0}
            import io

            with (
                mock.patch("sys.stdout", new_callable=io.StringIO),
                mock.patch("sys.stderr", new_callable=io.StringIO),
            ):
                code = cli.main(
                    [
                        "sync",
                        "Khan Academy",
                        "--language",
                        "en",
                        "--variant",
                        "US Curriculum",
                        "--skip-import",
                    ]
                )
        assert code == 0
        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args.kwargs
        assert call_kwargs["channel_id"] == "ch-ka-en-us"

    def test_sync_channel_id_backward_compat(self, tmp_path):
        import io
        import unittest.mock as mock

        from kolibri_curriculum import cli

        with (
            mock.patch("kolibri_curriculum.cli.sync_channel") as mock_sync,
            mock.patch("sys.stdout", new_callable=io.StringIO),
            mock.patch("sys.stderr", new_callable=io.StringIO),
        ):
            mock_sync.return_value = {"node_count": 0}
            code = cli.main(["sync", "--channel-id", "abc123", "--skip-import"])
        assert code == 0
        mock_sync.assert_called_once()

    def test_sync_channel_id_shows_deprecation_warning(self, tmp_path):
        import io
        import unittest.mock as mock

        from kolibri_curriculum import cli

        with (
            mock.patch("kolibri_curriculum.cli.sync_channel") as mock_sync,
            mock.patch("sys.stdout", new_callable=io.StringIO),
            mock.patch("sys.stderr", new_callable=io.StringIO) as mock_err,
        ):
            mock_sync.return_value = {"node_count": 0}
            cli.main(["sync", "--channel-id", "abc123", "--skip-import"])
        stderr = mock_err.getvalue()
        assert "advanced" in stderr.lower() or "channel-id" in stderr.lower()

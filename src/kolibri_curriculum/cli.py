from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .discovery import FileCacheDiscovery, NullDiscovery, language_display_name
from .exporters import export_catalog
from .kolibri import database_inventory, default_kolibri_home, import_channel
from .reader import read_catalog
from .repository import CatalogRepository
from .resolver import (
    AmbiguousSourceError,
    AmbiguousVariantError,
    LanguageUnavailableError,
    MissingLanguageError,
    SourceResolutionError,
    SourceResolver,
    UnknownSourceError,
    UnknownVariantError,
)
from .sync import sync_channel


def _json_print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _path(value: str) -> Path:
    return Path(value).expanduser()


def _default_catalog_db() -> Path:
    configured = os.getenv("CURRICULUM_DB")
    return _path(configured) if configured else Path("data/catalog.sqlite3")


def _make_resolver() -> SourceResolver:
    """Build a SourceResolver backed by the filesystem cache (no live network)."""
    cache = FileCacheDiscovery()
    return SourceResolver(discovery=cache)


# ---------------------------------------------------------------------------
# sources / source commands
# ---------------------------------------------------------------------------


def _cmd_sources(args: argparse.Namespace) -> int:
    resolver = _make_resolver()

    if args.refresh:
        cache = FileCacheDiscovery()
        try:
            channels = cache.refresh()
            print(f"Source catalog updated: {len(channels)} channels.")
        except RuntimeError as err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        resolver.invalidate_cache()

    try:
        sources = resolver.list_sources(language=args.language or None)
    except RuntimeError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2

    if args.search:
        q = args.search.lower()
        sources = [s for s in sources if q in s.display_name.lower() or q in s.provider_id]

    if args.json:
        _json_print({"sources": [s.to_dict() for s in sources]})
        return 0

    if not sources:
        print("No educational sources found.")
        return 0

    print("Available educational sources\n")
    header = f"{'SOURCE':<28} {'LANGUAGES':<22} {'CHANNELS':>8}"
    print(header)
    print("-" * len(header))
    for s in sources:
        langs = ", ".join(s.languages) if s.languages else "—"
        if len(langs) > 20:
            langs = langs[:19] + "…"
        print(f"{s.display_name:<28} {langs:<22} {s.channel_count:>8}")
    return 0


def _cmd_source_show(args: argparse.Namespace) -> int:
    resolver = _make_resolver()
    try:
        source_def = resolver.resolve_source(args.name)
        channels = resolver.available_channels(args.name)
    except SourceResolutionError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    except RuntimeError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2

    langs = resolver.available_languages(args.name)

    if args.json:
        payload: dict[str, Any] = {
            "provider_id": source_def.provider_id,
            "name": source_def.display_name,
            "aliases": list(source_def.aliases),
            "languages": langs,
            "channels": [],
        }
        for ch in channels:
            entry: dict[str, Any] = {
                "language": ch.language_code,
                "variant": ch.variant,
                "channel_name": ch.channel_name,
            }
            if args.ids:
                entry["channel_id"] = ch.channel_id
            payload["channels"].append(entry)
        _json_print(payload)
        return 0

    print(f"{source_def.display_name}\n")
    print(f"Provider ID: {source_def.provider_id}")
    if langs:
        print("Available languages:")
        for code in langs:
            print(f"  {language_display_name(code)}")
    else:
        print("No discovered channels yet. Run 'curriculum sources --refresh'.")
        return 0

    if channels:
        print("\nAvailable channels:\n")
        col_lang = 12
        col_var = 20
        col_status = 10
        header = f"  {'LANGUAGE':<{col_lang}} {'VARIANT':<{col_var}} {'STATUS':<{col_status}}"
        if args.ids:
            header += "  CHANNEL_ID"
        print(header)
        print("  " + "-" * (col_lang + col_var + col_status + 4))
        for ch in channels:
            lang_name = language_display_name(ch.language_code) if ch.language_code else "—"
            variant = ch.variant or "General"
            status = "available"
            row = f"  {lang_name:<{col_lang}} {variant:<{col_var}} {status:<{col_status}}"
            if args.ids:
                row += f"  {ch.channel_id}"
            print(row)
    return 0


def _cmd_source_languages(args: argparse.Namespace) -> int:
    resolver = _make_resolver()
    try:
        langs = resolver.available_languages(args.name)
    except SourceResolutionError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    except RuntimeError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2

    if args.json:
        _json_print(
            [{"code": code, "name": language_display_name(code)} for code in langs]
        )
        return 0

    for code in langs:
        print(language_display_name(code))
    return 0


def _cmd_source_channels(args: argparse.Namespace) -> int:
    resolver = _make_resolver()
    try:
        channels = resolver.available_channels(args.name)
    except SourceResolutionError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    except RuntimeError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2

    if args.json:
        rows = []
        for ch in channels:
            entry: dict[str, Any] = {
                "language": ch.language_code,
                "variant": ch.variant,
                "channel_name": ch.channel_name,
            }
            if args.ids:
                entry["channel_id"] = ch.channel_id
            rows.append(entry)
        _json_print(rows)
        return 0

    if not channels:
        print("No channels found.")
        return 0

    col_lang = 12
    col_var = 20
    col_status = 10
    header = f"{'LANGUAGE':<{col_lang}} {'VARIANT':<{col_var}} {'STATUS':<{col_status}}"
    if args.ids:
        header += "  CHANNEL_ID"
    print(header)
    print("-" * (col_lang + col_var + col_status + 4))
    for ch in channels:
        lang_name = language_display_name(ch.language_code) if ch.language_code else "—"
        variant = ch.variant or "General"
        status = "available"
        row = f"{lang_name:<{col_lang}} {variant:<{col_var}} {status:<{col_status}}"
        if args.ids:
            row += f"  {ch.channel_id}"
        print(row)
    return 0


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="curriculum",
        description="Kolibri curriculum metadata tool. Access educational sources by name.",
        epilog=(
            "Examples:\n"
            '  curriculum sources\n'
            '  curriculum source show "Khan Academy"\n'
            '  curriculum sync "Khan Academy" --language en\n'
            '  curriculum sync "PhET" --language vi\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # -----------------------------------------------------------------------
    # sources  (list all providers)
    # -----------------------------------------------------------------------
    sources_parser = subparsers.add_parser(
        "sources",
        help="List available educational sources.",
        epilog=(
            "Examples:\n"
            "  curriculum sources\n"
            "  curriculum sources --language vi\n"
            '  curriculum sources --search khan\n'
            "  curriculum sources --json\n"
            "  curriculum sources --refresh\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sources_parser.add_argument("--language", help="Filter by language code or name.")
    sources_parser.add_argument("--search", help="Filter by source name substring.")
    sources_parser.add_argument("--refresh", action="store_true", help="Force refresh of the discovery cache.")
    sources_parser.add_argument("--json", action="store_true", help="Output JSON.")

    # -----------------------------------------------------------------------
    # source  (sub-commands for a single provider)
    # -----------------------------------------------------------------------
    source_parser = subparsers.add_parser("source", help="Inspect a specific educational source.")
    source_subparsers = source_parser.add_subparsers(dest="source_command", required=True)

    _ss_show = source_subparsers.add_parser(
        "show",
        help="Show details about a source.",
        epilog=(
            "Examples:\n"
            '  curriculum source show "Khan Academy"\n'
            '  curriculum source show khan\n'
            '  curriculum source show "Khan Academy" --ids\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _ss_show.add_argument("name", help="Source name or alias.")
    _ss_show.add_argument("--ids", action="store_true", help="Include internal channel IDs.")
    _ss_show.add_argument("--json", action="store_true", help="Output JSON.")

    _ss_langs = source_subparsers.add_parser(
        "languages",
        help="List languages available for a source.",
        epilog=(
            "Examples:\n"
            '  curriculum source languages "Khan Academy"\n'
            '  curriculum source languages "Khan Academy" --json\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _ss_langs.add_argument("name", help="Source name or alias.")
    _ss_langs.add_argument("--json", action="store_true", help="Output JSON.")

    _ss_channels = source_subparsers.add_parser(
        "channels",
        help="List channel variants for a source.",
        epilog=(
            "Examples:\n"
            '  curriculum source channels "Khan Academy"\n'
            '  curriculum source channels "Khan Academy" --ids\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _ss_channels.add_argument("name", help="Source name or alias.")
    _ss_channels.add_argument("--ids", action="store_true", help="Include internal channel IDs.")
    _ss_channels.add_argument("--json", action="store_true", help="Output JSON.")

    # -----------------------------------------------------------------------
    # import-channel  (advanced / internal)
    # -----------------------------------------------------------------------
    import_parser = subparsers.add_parser(
        "import-channel",
        help="[Advanced] Download or refresh a Kolibri channel database by ID.",
    )
    import_parser.add_argument("channel_id")
    import_parser.add_argument("--kolibri-command", default="kolibri")
    import_parser.add_argument("--kolibri-home", type=_path)

    # -----------------------------------------------------------------------
    # discover  (list local Kolibri databases)
    # -----------------------------------------------------------------------
    discover_parser = subparsers.add_parser(
        "discover",
        help="List imported Kolibri channel databases.",
    )
    discover_parser.add_argument("--kolibri-home", type=_path, default=default_kolibri_home())

    # -----------------------------------------------------------------------
    # export  (export a single channel database)
    # -----------------------------------------------------------------------
    export_parser = subparsers.add_parser(
        "export",
        help="Export one existing Kolibri channel database.",
        epilog=(
            "Examples:\n"
            '  curriculum export path/to/channel.sqlite3 --output out/\n'
            '  curriculum export path/to/channel.sqlite3 --output out/ --source "OpenStax" --language en\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    export_parser.add_argument("database", type=_path)
    export_parser.add_argument("--output", type=_path, required=True)
    export_parser.add_argument("--max-depth", type=int)
    export_parser.add_argument(
        "--include-kinds",
        help="Comma-separated source kinds. Default: all metadata nodes.",
    )

    # -----------------------------------------------------------------------
    # sync  (primary user-facing command)
    # -----------------------------------------------------------------------
    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync a source by name and language.",
        epilog=(
            "Examples:\n"
            '  curriculum sync "Khan Academy" --language en\n'
            '  curriculum sync "PhET" --language vi\n'
            '  curriculum sync "Khan Academy" --language en --variant "US Curriculum"\n'
            "\n"
            "Advanced (internal) usage:\n"
            "  curriculum sync --channel-id <ID>  # not recommended for normal use\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sync_parser.add_argument(
        "source_name",
        nargs="?",
        default=None,
        help="Educational source name or alias (e.g. 'Khan Academy').",
    )
    sync_parser.add_argument("--language", help="Language code or name (e.g. en, English).")
    sync_parser.add_argument("--variant", help="Variant name when multiple channels match.")
    sync_parser.add_argument(
        "--channel-id",
        help="[Advanced] Use a specific Kolibri channel ID directly.",
    )
    sync_parser.add_argument("--data-dir", type=_path, default=Path("data"))
    sync_parser.add_argument("--kolibri-home", type=_path, default=default_kolibri_home())
    sync_parser.add_argument("--database", type=_path)
    sync_parser.add_argument("--skip-import", action="store_true")
    sync_parser.add_argument("--kolibri-command", default="kolibri")
    sync_parser.add_argument("--max-depth", type=int)

    # -----------------------------------------------------------------------
    # query  (internal/advanced catalog queries)
    # -----------------------------------------------------------------------
    query_parser = subparsers.add_parser("query", help="Query the generated SQLite catalog.")
    query_parser.add_argument("--db", type=_path, default=_default_catalog_db())
    query_subparsers = query_parser.add_subparsers(dest="query_command", required=True)

    query_subparsers.add_parser("channels")

    search_parser = query_subparsers.add_parser(
        "search",
        epilog=(
            "Examples:\n"
            '  curriculum query search "linear equations" --source "Khan Academy" --language en\n'
            '  curriculum query search "algebra"  # search across all imported channels\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    search_parser.add_argument("query")
    search_parser.add_argument(
        "--channel-id",
        help="[Advanced] Filter by specific channel ID.",
    )
    search_parser.add_argument("--source", help="Filter by educational source name.")
    search_parser.add_argument("--language", help="Filter by language (requires --source).")
    search_parser.add_argument("--limit", type=int, default=20)

    node_parser = query_subparsers.add_parser("node")
    node_parser.add_argument("channel_id")
    node_parser.add_argument("node_id")

    children_parser = query_subparsers.add_parser("children")
    children_parser.add_argument("channel_id")
    children_parser.add_argument("parent_id", nargs="?", default=None)

    subtree_parser = query_subparsers.add_parser("subtree")
    subtree_parser.add_argument("channel_id")
    subtree_parser.add_argument("node_id")
    subtree_parser.add_argument("--max-depth", type=int, default=3)

    changes_parser = query_subparsers.add_parser(
        "changes",
        epilog=(
            "Examples:\n"
            '  curriculum query changes --source "Khan Academy"\n'
            '  curriculum query changes --source "Khan Academy" --language en\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    changes_parser.add_argument(
        "--channel-id",
        help="[Advanced] Filter by specific channel ID.",
    )
    changes_parser.add_argument("--source", help="Filter by educational source name.")
    changes_parser.add_argument("--language", help="Filter by language (requires --source).")
    changes_parser.add_argument("--snapshot-id", type=int)
    changes_parser.add_argument("--limit", type=int, default=100)

    return parser


# ---------------------------------------------------------------------------
# Helpers for resolving --source/--language to a channel_id
# ---------------------------------------------------------------------------


def _resolve_channel_id_for_query(
    args: argparse.Namespace,
    attribute: str = "channel_id",
) -> str | None:
    """Return a channel_id from --channel-id OR --source/--language resolution."""
    raw_id = getattr(args, attribute.replace("-", "_"), None)
    source = getattr(args, "source", None)
    language = getattr(args, "language", None)

    if raw_id:
        return raw_id
    if source:
        resolver = _make_resolver()
        resolved = resolver.resolve_channel(source, language=language)
        return resolved.channel_id
    return None


def _run_query(args: argparse.Namespace) -> int:
    repository = CatalogRepository(args.db)
    if args.query_command == "channels":
        result = repository.list_channels()
    elif args.query_command == "search":
        channel_id = _resolve_channel_id_for_query(args)
        result = repository.search(args.query, channel_id=channel_id, limit=args.limit)
    elif args.query_command == "node":
        result = repository.get_node(args.channel_id, args.node_id)
    elif args.query_command == "children":
        parent_id = None if args.parent_id in (None, "null", "root") else args.parent_id
        result = repository.list_children(args.channel_id, parent_id)
    elif args.query_command == "subtree":
        result = repository.get_subtree(
            args.channel_id,
            args.node_id,
            max_depth=args.max_depth,
        )
    elif args.query_command == "changes":
        channel_id = _resolve_channel_id_for_query(args)
        result = repository.list_changes(
            channel_id=channel_id,
            snapshot_id=args.snapshot_id,
            limit=args.limit,
        )
    else:  # pragma: no cover
        raise AssertionError(args.query_command)
    _json_print(result)
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "sources":
            return _cmd_sources(args)

        if args.command == "source":
            if args.source_command == "show":
                return _cmd_source_show(args)
            if args.source_command == "languages":
                return _cmd_source_languages(args)
            if args.source_command == "channels":
                return _cmd_source_channels(args)
            raise AssertionError(args.source_command)  # pragma: no cover

        if args.command == "import-channel":
            import_channel(
                args.channel_id,
                kolibri_command=args.kolibri_command,
                kolibri_home=args.kolibri_home,
            )
            _json_print({"ok": True, "channel_id": args.channel_id})
            return 0

        if args.command == "discover":
            _json_print(database_inventory(args.kolibri_home))
            return 0

        if args.command == "export":
            kinds = None
            if args.include_kinds:
                kinds = {value.strip() for value in args.include_kinds.split(",") if value.strip()}
            catalog = read_catalog(args.database, include_kinds=kinds)
            result = export_catalog(catalog, args.output, max_depth=args.max_depth)
            _json_print({"channel": catalog.channel.to_dict(), "files": result})
            return 0

        if args.command == "sync":
            channel_id = args.channel_id

            if channel_id:
                # Advanced / backward-compatible mode
                print(
                    "Warning: --channel-id is an advanced option.\n"
                    "Prefer: curriculum sync \"SOURCE NAME\" --language LANG",
                    file=sys.stderr,
                )
            elif args.source_name:
                # Resolve from source name + language
                resolver = _make_resolver()
                resolved = resolver.resolve_channel(
                    args.source_name,
                    language=args.language or None,
                    variant=args.variant or None,
                )
                channel_id = resolved.channel_id
            else:
                print(
                    "error: provide a source name (e.g. curriculum sync \"Khan Academy\" "
                    "--language en) or --channel-id.",
                    file=sys.stderr,
                )
                return 2

            result = sync_channel(
                channel_id=channel_id,
                data_directory=args.data_dir,
                kolibri_home=args.kolibri_home,
                source_database=args.database,
                refresh_from_network=not args.skip_import,
                kolibri_command=args.kolibri_command,
                max_depth=args.max_depth,
            )
            _json_print(result)
            return 0

        if args.command == "query":
            return _run_query(args)

        raise AssertionError(args.command)  # pragma: no cover
    except SourceResolutionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .exporters import export_catalog
from .kolibri import database_inventory, default_kolibri_home, import_channel
from .reader import read_catalog
from .repository import CatalogRepository
from .sync import sync_channel


def _json_print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _path(value: str) -> Path:
    return Path(value).expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kcurriculum",
        description="Export Kolibri curriculum metadata to JSON and SQLite.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser(
        "import-channel",
        help="Download or refresh only a Kolibri channel database.",
    )
    import_parser.add_argument("channel_id")
    import_parser.add_argument("--kolibri-command", default="kolibri")
    import_parser.add_argument("--kolibri-home", type=_path)

    discover_parser = subparsers.add_parser(
        "discover",
        help="List imported Kolibri channel databases.",
    )
    discover_parser.add_argument("--kolibri-home", type=_path, default=default_kolibri_home())

    export_parser = subparsers.add_parser(
        "export",
        help="Export one existing Kolibri channel database.",
    )
    export_parser.add_argument("database", type=_path)
    export_parser.add_argument("--output", type=_path, required=True)
    export_parser.add_argument("--max-depth", type=int)
    export_parser.add_argument(
        "--include-kinds",
        help="Comma-separated source kinds. Default: all metadata nodes.",
    )

    sync_parser = subparsers.add_parser(
        "sync",
        help="Refresh/import, export JSON, and update the SQLite catalog.",
    )
    sync_parser.add_argument("--channel-id", required=True)
    sync_parser.add_argument("--data-dir", type=_path, default=Path("data"))
    sync_parser.add_argument("--kolibri-home", type=_path, default=default_kolibri_home())
    sync_parser.add_argument("--database", type=_path)
    sync_parser.add_argument("--skip-import", action="store_true")
    sync_parser.add_argument("--kolibri-command", default="kolibri")
    sync_parser.add_argument("--max-depth", type=int)

    query_parser = subparsers.add_parser("query", help="Query the generated SQLite catalog.")
    query_parser.add_argument("--db", type=_path, default=Path("data/catalog.sqlite3"))
    query_subparsers = query_parser.add_subparsers(dest="query_command", required=True)

    channels_parser = query_subparsers.add_parser("channels")

    search_parser = query_subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--channel-id")
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

    changes_parser = query_subparsers.add_parser("changes")
    changes_parser.add_argument("--channel-id")
    changes_parser.add_argument("--snapshot-id", type=int)
    changes_parser.add_argument("--limit", type=int, default=100)

    return parser


def _run_query(args: argparse.Namespace) -> int:
    repository = CatalogRepository(args.db)
    if args.query_command == "channels":
        result = repository.list_channels()
    elif args.query_command == "search":
        result = repository.search(args.query, channel_id=args.channel_id, limit=args.limit)
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
        result = repository.list_changes(
            channel_id=args.channel_id,
            snapshot_id=args.snapshot_id,
            limit=args.limit,
        )
    else:  # pragma: no cover
        raise AssertionError(args.query_command)
    _json_print(result)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
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
            result = sync_channel(
                channel_id=args.channel_id,
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
    except (FileNotFoundError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

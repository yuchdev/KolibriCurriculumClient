from __future__ import annotations

import os
import shlex
import sqlite3
import subprocess
from pathlib import Path

from .reader import inspect_channel_ids


def default_kolibri_home() -> Path:
    configured = os.getenv("KOLIBRI_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".kolibri"


def import_channel(
    channel_id: str,
    *,
    kolibri_command: str = "kolibri",
    kolibri_home: Path | None = None,
    timeout_seconds: int = 1800,
) -> None:
    """Download/refresh only the channel database; never import content files."""
    command = [*shlex.split(kolibri_command), "manage", "importchannel", "network", channel_id]
    environment = os.environ.copy()
    if kolibri_home is not None:
        environment["KOLIBRI_HOME"] = str(kolibri_home.expanduser())
    subprocess.run(command, check=True, timeout=timeout_seconds, env=environment)


def _is_sqlite(path: Path) -> bool:
    if not path.is_file() or path.name.endswith(("-wal", "-shm", "-journal")):
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def discover_databases(kolibri_home: Path | None = None) -> list[Path]:
    home = (kolibri_home or default_kolibri_home()).expanduser()
    directory = home / "content" / "databases"
    if not directory.exists():
        return []
    return sorted(path for path in directory.iterdir() if _is_sqlite(path))


def database_inventory(kolibri_home: Path | None = None) -> list[dict]:
    inventory: list[dict] = []
    for path in discover_databases(kolibri_home):
        try:
            ids = sorted(inspect_channel_ids(path))
            inventory.append(
                {
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "channel_ids": ids,
                }
            )
        except (OSError, sqlite3.Error):
            continue
    return inventory


def find_database_for_channel(channel_id: str, kolibri_home: Path | None = None) -> Path:
    matches: list[Path] = []
    for path in discover_databases(kolibri_home):
        if channel_id in inspect_channel_ids(path):
            matches.append(path)
        elif channel_id.casefold() in path.stem.casefold():
            matches.append(path)
    if not matches:
        home = kolibri_home or default_kolibri_home()
        raise FileNotFoundError(
            f"No imported channel database for {channel_id!r} under "
            f"{Path(home).expanduser() / 'content' / 'databases'}"
        )
    return max(matches, key=lambda path: path.stat().st_mtime_ns)

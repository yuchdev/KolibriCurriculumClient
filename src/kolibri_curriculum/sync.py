from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from .exporters import export_catalog
from .kolibri import find_database_for_channel, import_channel
from .reader import read_catalog
from .repository import CatalogRepository


def sync_channel(
    *,
    channel_id: str,
    data_directory: Path,
    kolibri_home: Path | None = None,
    source_database: Path | None = None,
    refresh_from_network: bool = True,
    kolibri_command: str = "kolibri",
    max_depth: int | None = None,
) -> dict:
    data_directory = Path(data_directory)
    data_directory.mkdir(parents=True, exist_ok=True)

    if refresh_from_network:
        import_channel(
            channel_id,
            kolibri_command=kolibri_command,
            kolibri_home=kolibri_home,
        )

    database_path = source_database or find_database_for_channel(channel_id, kolibri_home)
    catalog = read_catalog(database_path)
    if catalog.channel.channel_id and catalog.channel.channel_id != channel_id:
        raise ValueError(
            f"Selected database reports channel {catalog.channel.channel_id!r}, "
            f"not requested channel {channel_id!r}"
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    snapshots_root = data_directory / "snapshots" / channel_id
    snapshot_directory = snapshots_root / timestamp
    current_directory = data_directory / "exports" / channel_id / "current"

    exported = export_catalog(catalog, snapshot_directory, max_depth=max_depth)
    if current_directory.exists():
        shutil.rmtree(current_directory)
    current_directory.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(snapshot_directory, current_directory)

    repository = CatalogRepository(data_directory / "catalog.sqlite3")
    summary = repository.sync_catalog(catalog, current_directory)

    result = summary.to_dict()
    result.update(
        {
            "source_database": str(database_path.resolve()),
            "snapshot_directory": str(snapshot_directory.resolve()),
            "current_directory": str(current_directory.resolve()),
            "exports": exported,
        }
    )
    return result

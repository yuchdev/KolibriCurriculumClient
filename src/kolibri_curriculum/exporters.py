from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .models import Catalog
from .planning import build_planning_records
from .tree import nested_nodes


def _atomic_json(path: Path, value: Any, *, indent: int | None = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=indent, default=str)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _atomic_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str))
            handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def export_catalog(
    catalog: Catalog,
    output_directory: Path,
    *,
    max_depth: int | None = None,
) -> dict[str, str]:
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    node_rows = [node.to_dict() for node in catalog.nodes]
    outline = nested_nodes(catalog.nodes, max_depth=max_depth, topics_only=True)
    full_tree = nested_nodes(catalog.nodes, max_depth=max_depth, topics_only=False)
    lessons = build_planning_records(catalog.nodes)

    paths = {
        "manifest": output_directory / "manifest.json",
        "nodes": output_directory / "nodes.jsonl",
        "outline": output_directory / "outline.json",
        "catalog": output_directory / "catalog.json",
        "lessons": output_directory / "lessons.json",
    }
    _atomic_json(paths["manifest"], catalog.to_manifest())
    _atomic_jsonl(paths["nodes"], node_rows)
    _atomic_json(
        paths["outline"],
        {
            "channel": catalog.channel.to_dict(),
            "max_depth": max_depth,
            "tree": outline,
        },
    )
    _atomic_json(
        paths["catalog"],
        {
            "channel": catalog.channel.to_dict(),
            "max_depth": max_depth,
            "tree": full_tree,
        },
    )
    _atomic_json(
        paths["lessons"],
        {
            "channel": catalog.channel.to_dict(),
            "description": (
                "Planning-oriented records inferred from the original Kolibri hierarchy. "
                "Use source_path and node_id as authoritative fields."
            ),
            "records": lessons,
        },
    )
    return {name: str(path) for name, path in paths.items()}

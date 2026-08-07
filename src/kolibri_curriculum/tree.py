from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Iterable

from .models import CurriculumNode


def _sort_key(node: CurriculumNode) -> tuple:
    return (
        node.tree_id if node.tree_id is not None else 0,
        node.left if node.left is not None else 10**12,
        node.sort_order if node.sort_order is not None else 10**12,
        node.title.casefold(),
        node.node_id,
    )


def enrich_tree(nodes: Iterable[CurriculumNode]) -> list[CurriculumNode]:
    ordered = sorted(nodes, key=_sort_key)
    by_id = {node.node_id: node for node in ordered}
    cache: dict[str, tuple[int, list[str]]] = {}

    def resolve(node_id: str, stack: frozenset[str] = frozenset()) -> tuple[int, list[str]]:
        if node_id in cache:
            return cache[node_id]
        node = by_id[node_id]
        if node_id in stack:
            result = (0, ["[cycle]", node.title])
            cache[node_id] = result
            return result
        if node.parent_id and node.parent_id in by_id:
            parent_depth, parent_path = resolve(node.parent_id, stack | {node_id})
            result = (parent_depth + 1, [*parent_path, node.title])
        else:
            result = (0, [node.title])
        cache[node_id] = result
        return result

    for node in ordered:
        node.depth, node.path = resolve(node.node_id)
        node.row_hash = compute_row_hash(node)
    return ordered


def compute_row_hash(node: CurriculumNode) -> str:
    payload = {
        "node_id": node.node_id,
        "content_id": node.content_id,
        "channel_id": node.channel_id,
        "parent_id": node.parent_id,
        "kind": node.kind,
        "title": node.title,
        "description": node.description,
        "author": node.author,
        "sort_order": node.sort_order,
        "duration_seconds": node.duration_seconds,
        "language": node.language,
        "available": node.available,
        "license_name": node.license_name,
        "license_owner": node.license_owner,
        "options": node.options,
        "grade_levels": node.grade_levels,
        "resource_types": node.resource_types,
        "learning_activities": node.learning_activities,
        "categories": node.categories,
        "learner_needs": node.learner_needs,
        "path": node.path,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def nested_nodes(
    nodes: Iterable[CurriculumNode],
    *,
    max_depth: int | None = None,
    topics_only: bool = False,
) -> list[dict]:
    selected = [
        node
        for node in nodes
        if (max_depth is None or node.depth <= max_depth)
        and (not topics_only or node.kind == "topic")
    ]
    selected_ids = {node.node_id for node in selected}
    children: dict[str | None, list[CurriculumNode]] = defaultdict(list)

    for node in selected:
        parent_id = node.parent_id if node.parent_id in selected_ids else None
        children[parent_id].append(node)
    for siblings in children.values():
        siblings.sort(key=_sort_key)

    def build(node: CurriculumNode) -> dict:
        data = node.to_dict()
        data["children"] = [build(child) for child in children.get(node.node_id, [])]
        return data

    return [build(root) for root in children.get(None, [])]

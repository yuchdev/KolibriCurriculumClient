from __future__ import annotations

import re
from typing import Iterable

from .models import CurriculumNode

_UNIT_RE = re.compile(r"^unit\b", re.IGNORECASE)
_LESSON_RE = re.compile(r"^lesson\b", re.IGNORECASE)
_GENERIC = {
    "khan academy",
    "root",
    "content",
    "courses",
    "course",
    "math",
    "mathematics",
    "science",
    "computing",
    "economics",
    "arts and humanities",
    "test prep",
}


def _nearest_matching(values: list[str], pattern: re.Pattern[str]) -> tuple[int | None, str | None]:
    for index in range(len(values) - 1, -1, -1):
        if pattern.search(values[index]):
            return index, values[index]
    return None, None


def _course_name(topic_path: list[str], boundary: int | None) -> str | None:
    candidates = topic_path[:boundary] if boundary is not None else topic_path
    for title in reversed(candidates):
        if title.strip().casefold() not in _GENERIC:
            return title
    return candidates[-1] if candidates else None


def build_planning_records(nodes: Iterable[CurriculumNode]) -> list[dict]:
    records: list[dict] = []
    for node in nodes:
        if node.kind == "topic":
            continue
        topic_path = node.path[:-1]
        unit_index, unit = _nearest_matching(topic_path, _UNIT_RE)
        lesson_index, lesson = _nearest_matching(topic_path, _LESSON_RE)

        inferred = []
        if lesson is None and topic_path:
            lesson_index = len(topic_path) - 1
            lesson = topic_path[-1]
            inferred.append("lesson=nearest_topic_parent")
        boundary_candidates = [i for i in (unit_index, lesson_index) if i is not None]
        boundary = min(boundary_candidates) if boundary_candidates else None
        course = _course_name(topic_path, boundary)
        if course is not None:
            inferred.append("course=nearest_specific_ancestor")

        subject = None
        for title in topic_path:
            if title.strip().casefold() in _GENERIC and title.strip().casefold() not in {
                "khan academy",
                "root",
                "content",
                "courses",
                "course",
            }:
                subject = title
                break

        records.append(
            {
                "channel_id": node.channel_id,
                "node_id": node.node_id,
                "content_id": node.content_id,
                "subject": subject,
                "course": course,
                "unit": unit,
                "lesson": lesson,
                "item": node.title,
                "item_type": node.kind,
                "about": node.description,
                "author": node.author,
                "duration_seconds": node.duration_seconds,
                "language": node.language,
                "source_path": node.path,
                "source_path_text": node.path_text,
                "inference": inferred,
            }
        )
    return records

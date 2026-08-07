from kolibri_curriculum.planning import build_planning_records
from kolibri_curriculum.reader import read_catalog


def test_builds_lesson_planning_record(sample_channel_db):
    catalog = read_catalog(sample_channel_db)
    records = build_planning_records(catalog.nodes)

    assert len(records) == 1
    record = records[0]
    assert record["subject"] == "Math"
    assert record["course"] == "Algebra 1"
    assert record["unit"] == "Unit 6"
    assert record["lesson"] == "Lesson 1"
    assert record["item"] == "Graphing systems of equations"
    assert record["author"] == "Sal Khan"
    assert "intersection point" in record["about"]

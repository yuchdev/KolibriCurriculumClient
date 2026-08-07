from copy import deepcopy

from kolibri_curriculum.reader import read_catalog
from kolibri_curriculum.repository import CatalogRepository
from kolibri_curriculum.tree import enrich_tree


def test_sync_and_query(sample_channel_db, tmp_path):
    catalog = read_catalog(sample_channel_db)
    repository = CatalogRepository(tmp_path / "catalog.sqlite3")

    first = repository.sync_catalog(catalog)
    assert first.added == 6
    assert first.removed == 0

    results = repository.search("intersection point", channel_id="channel-1")
    assert results[0]["node_id"] == "video1"

    children = repository.list_children("channel-1", "unit6")
    assert [row["node_id"] for row in children] == ["lesson1"]

    subtree = repository.get_subtree("channel-1", "unit6", max_depth=2)
    assert [row["node_id"] for row in subtree] == ["unit6", "lesson1", "video1"]


def test_records_modified_and_removed(sample_channel_db, tmp_path):
    catalog = read_catalog(sample_channel_db)
    repository = CatalogRepository(tmp_path / "catalog.sqlite3")
    repository.sync_catalog(catalog)

    updated = deepcopy(catalog)
    updated.nodes = [node for node in updated.nodes if node.node_id != "video1"]
    lesson = next(node for node in updated.nodes if node.node_id == "lesson1")
    lesson.description = "Updated lesson description"
    updated.nodes = enrich_tree(updated.nodes)

    second = repository.sync_catalog(updated)
    assert second.modified == 1
    assert second.removed == 1

    changes = repository.list_changes(snapshot_id=second.snapshot_id)
    assert {change["change_type"] for change in changes} == {"modified", "removed"}


def test_agent_facade_is_read_only(sample_channel_db, tmp_path):
    from kolibri_curriculum.agent_api import CatalogQueryService

    catalog = read_catalog(sample_channel_db)
    database = tmp_path / "catalog.sqlite3"
    CatalogRepository(database).sync_catalog(catalog)

    service = CatalogQueryService(database)
    assert service.channels()[0]["channel_id"] == "channel-1"
    assert any(
        row["node_id"] == "video1"
        for row in service.search("graphing", channel_id="channel-1")
    )

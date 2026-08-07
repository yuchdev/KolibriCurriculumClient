from kolibri_curriculum.sync import sync_channel


def test_sync_channel_end_to_end(sample_channel_db, tmp_path):
    result = sync_channel(
        channel_id="channel-1",
        data_directory=tmp_path / "data",
        source_database=sample_channel_db,
        refresh_from_network=False,
    )

    assert result["node_count"] == 6
    assert (tmp_path / "data" / "catalog.sqlite3").exists()
    current = tmp_path / "data" / "exports" / "channel-1" / "current"
    assert (current / "catalog.json").exists()
    assert (current / "lessons.json").exists()

from kolibri_curriculum.reader import inspect_channel_ids, read_catalog


def test_reads_channel_tree(sample_channel_db):
    catalog = read_catalog(sample_channel_db)

    assert catalog.channel.channel_id == "channel-1"
    assert catalog.channel.name == "Khan Academy Test"
    assert len(catalog.nodes) == 6

    video = next(node for node in catalog.nodes if node.node_id == "video1")
    assert video.depth == 5
    assert video.path == [
        "Khan Academy",
        "Math",
        "Algebra 1",
        "Unit 6",
        "Lesson 1",
        "Graphing systems of equations",
    ]
    assert video.author == "Sal Khan"
    assert video.language == "en"
    assert video.options == {"youtube_id": "abc"}
    assert video.row_hash


def test_inspects_channel_id(sample_channel_db):
    assert inspect_channel_ids(sample_channel_db) == {"channel-1"}

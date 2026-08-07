import json

from kolibri_curriculum.exporters import export_catalog
from kolibri_curriculum.reader import read_catalog


def test_exports_json_files(sample_channel_db, tmp_path):
    catalog = read_catalog(sample_channel_db)
    files = export_catalog(catalog, tmp_path / "export")

    assert set(files) == {"manifest", "nodes", "outline", "catalog", "lessons"}
    lessons = json.loads((tmp_path / "export" / "lessons.json").read_text())
    assert lessons["records"][0]["course"] == "Algebra 1"
    outline = json.loads((tmp_path / "export" / "outline.json").read_text())
    assert outline["tree"][0]["title"] == "Khan Academy"

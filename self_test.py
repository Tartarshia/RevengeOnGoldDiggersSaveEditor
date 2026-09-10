from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import rogd_model
from rogd_model import SavePaths, atomic_write, encode_json, load_json, save_archive, save_setting, sha256_bytes, validate_setting
from steam_schema import load_achievements
from story_graph import load_story_graphs, plan_chapter_unlock, plan_story_unlock


def main() -> None:
    sample = {
        "roleProfile": {"1-test-1": {"unLock": False, "newFlag": False}},
        "loveDrama": {"1": {"unLock": True, "newFlag": True}},
        "language": "zh_cn",
    }
    validate_setting(sample)
    encoded = encode_json(sample)
    assert json.loads(encoded.decode("utf-8")) == sample
    assert len(sha256_bytes(encoded)) == 64
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        path = temp_root / "setting.save"
        atomic_write(path, encoded)
        assert load_json(path) == sample
        archive_path = temp_root / "archive.save"
        archive_path.write_text('{"majorMap":{},"nodeMap":{}}', encoding="utf-8")
        paths = SavePaths(temp_root, archive_path, path)
        updated = json.loads(json.dumps(sample))
        updated["roleProfile"]["1-test-1"]["unLock"] = True
        expected_hash = sha256_bytes(encode_json(updated))
        fake_cloud = {"ok": True, "sha256": expected_hash}
        with (
            patch.object(rogd_model, "PROJECT_DIR", temp_root),
            patch.object(rogd_model, "ensure_game_closed"),
            patch.object(rogd_model, "run_steam_helper", return_value=fake_cloud),
        ):
            backup_dir, digest = save_setting(paths, updated)
        assert digest == expected_hash
        assert load_json(path) == updated
        assert (backup_dir / "archive.save").is_file()
        assert (backup_dir / "setting.save").read_bytes() == encoded

        archive = {"majorMap": {}, "nodeMap": {}, "currentNode": "keep-me"}
        expected_archive_hash = sha256_bytes(encode_json(archive))
        archive_cloud = {"ok": True, "sha256": expected_archive_hash}
        with (
            patch.object(rogd_model, "PROJECT_DIR", temp_root),
            patch.object(rogd_model, "ensure_game_closed"),
            patch.object(rogd_model, "run_steam_helper", return_value=archive_cloud),
        ):
            archive_backup, archive_digest = save_archive(paths, archive)
        assert archive_digest == expected_archive_hash
        assert load_json(archive_path) == archive
        assert (archive_backup / "archive.save").is_file()

    graphs = load_story_graphs()
    original_archive = {"majorMap": {}, "nodeMap": {}, "currentNode": "keep-me"}
    planned, added = plan_story_unlock(original_archive, graphs, "n1302")
    assert "n1302" in added
    assert {"n1123a1", "n1230a1", "n1301", "n1302"}.issubset(planned["nodeMap"])
    assert planned["currentNode"] == "keep-me"
    planned_again, added_again = plan_story_unlock(planned, graphs, "n1302")
    assert added_again == []
    assert planned_again == planned
    chapter_planned, chapter_added = plan_chapter_unlock(original_archive, graphs, "2")
    chapter_ids = {node["id"] for node in graphs["2"]["nodes"]}
    assert chapter_ids.issubset(chapter_planned["nodeMap"])
    assert len(chapter_added) == len(set(chapter_added))
    assert chapter_planned["currentNode"] == "keep-me"

    achievements = load_achievements()
    assert len(achievements) == 39, len(achievements)
    assert achievements[0].achievement_id == "a01"
    assert achievements[-1].achievement_id == "a39"
    assert len({item.achievement_id for item in achievements}) == 39
    print("PASS: JSON round-trip, guarded save writes, story graph/path idempotence, Steam schema (39 achievements)")


if __name__ == "__main__":
    main()

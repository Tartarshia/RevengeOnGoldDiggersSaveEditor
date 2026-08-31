from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rogd_model import atomic_write, encode_json, load_json, sha256_bytes, validate_archive, validate_setting
from story_graph import all_story_nodes, load_story_graphs, plan_story_unlock


class SaveModelTests(unittest.TestCase):
    def test_json_round_trip_with_synthetic_save(self) -> None:
        setting = {
            "roleProfile": {"test": {"unLock": False, "newFlag": False}},
            "loveDrama": {"1": {"unLock": True, "newFlag": True}},
        }
        validate_setting(setting)
        encoded = encode_json(setting)
        self.assertEqual(len(sha256_bytes(encoded)), 64)
        with tempfile.TemporaryDirectory(prefix="rogd-public-test-") as temporary:
            path = Path(temporary) / "setting.save"
            atomic_write(path, encoded)
            self.assertEqual(load_json(path), setting)


class StoryGraphTests(unittest.TestCase):
    def test_graph_and_unlock_plan(self) -> None:
        graphs = load_story_graphs()
        self.assertEqual(len(all_story_nodes(graphs)), 632)
        archive = {"majorMap": {}, "nodeMap": {}, "currentNode": "preserve-me"}
        validate_archive(archive)
        planned, added = plan_story_unlock(archive, graphs, "n1302")
        self.assertIn("n1302", added)
        self.assertTrue({"n1123a1", "n1230a1", "n1301", "n1302"}.issubset(planned["nodeMap"]))
        self.assertEqual(planned["currentNode"], "preserve-me")
        planned_again, added_again = plan_story_unlock(planned, graphs, "n1302")
        self.assertEqual(added_again, [])
        self.assertEqual(planned_again, planned)


if __name__ == "__main__":
    unittest.main()

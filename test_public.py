from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from rogd_model import atomic_write, encode_json, load_json, sha256_bytes, validate_archive, validate_setting
from story_graph import (
    all_story_nodes,
    chapter_unlock_status,
    load_story_graphs,
    plan_chapter_unlock,
    plan_maximum_relationship_route,
    plan_relationship_gate_route,
    plan_story_unlock,
    relationship_requirement_status,
    story_route_score,
)


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

    def test_chapter_unlock_adds_every_node_and_is_idempotent(self) -> None:
        graphs = load_story_graphs()
        archive = {
            "majorMap": {},
            "nodeMap": {},
            "currentNode": "preserve-me",
            "currentRoute": {"nodes": ["preserve-route"]},
        }
        planned, added = plan_chapter_unlock(archive, graphs, "2")
        chapter_ids = {node["id"] for node in graphs["2"]["nodes"]}
        self.assertTrue(chapter_ids.issubset(planned["nodeMap"]))
        self.assertEqual(len(chapter_ids), 83)
        self.assertEqual(len(added), len(set(added)))
        self.assertEqual(planned["currentNode"], "preserve-me")
        self.assertEqual(planned["currentRoute"], {"nodes": ["preserve-route"]})
        missing, unfinished = chapter_unlock_status(planned, graphs, "2")
        self.assertEqual(missing, set())
        self.assertEqual(unfinished, set())
        planned_again, added_again = plan_chapter_unlock(planned, graphs, "2")
        self.assertEqual(added_again, [])
        self.assertEqual(planned_again, planned)

    def test_chapter_unlock_repairs_entered_but_unfinished_nodes(self) -> None:
        graphs = load_story_graphs()
        archive = {
            "majorMap": {},
            "nodeMap": {"n1501": {"id": "n1501", "lastNode": ""}},
        }
        missing_before, unfinished_before = chapter_unlock_status(archive, graphs, "5")
        self.assertIn("n1501", unfinished_before)
        planned, changed = plan_chapter_unlock(archive, graphs, "5")
        self.assertIn("n1501", changed)
        self.assertIn("lastNext", planned["nodeMap"]["n1501"])
        missing_after, unfinished_after = chapter_unlock_status(planned, graphs, "5")
        self.assertEqual(missing_after, set())
        self.assertEqual(unfinished_after, set())

    def test_maximum_chapter_five_relationship_route_reaches_270(self) -> None:
        graphs = load_story_graphs()
        archive = {
            "majorMap": {},
            "nodeMap": {},
            "currentNode": "preserve-me",
            "currentRoute": {"nodes": ["preserve-route"]},
        }
        planned, path, score = plan_maximum_relationship_route(
            archive, graphs, "5", "yy", "n1537b"
        )
        self.assertEqual(score, 270)
        self.assertEqual(story_route_score(planned, graphs["5"], "n1537b", "yy"), 270)
        self.assertIn("n1534a", path)
        self.assertIn("n1517b", path)
        self.assertEqual(planned["currentNode"], "preserve-me")
        self.assertEqual(planned["currentRoute"], {"nodes": ["preserve-route"]})

    def test_relationship_presets_cover_every_heroine_and_finale(self) -> None:
        graphs = load_story_graphs()
        archive = {
            "majorMap": {},
            "nodeMap": {},
            "currentNode": "preserve-me",
            "currentRoute": {"nodes": ["preserve-route"]},
        }
        targets = (
            "n1121a",  # 陈欣欣 / yl
            "n1229c",  # 唐晓甜 / xt
            "n1325",   # 陈欣如 / xrza
            "n1433",   # 宋诗琪 / sq
            "n1537b",  # 何月盈 / yy
            "n1633",   # 潘梦娜 / mn
            "n1732",   # 第七章继承唐晓甜
            "n1733",   # 第七章继承何月盈
            "n1734",   # 第七章继承宋诗琪
            "n1735b",  # 第七章陈欣欣真爱
            "n1725",   # 第七章潘梦娜高值
        )
        for target in targets:
            with self.subTest(target=target):
                planned, path, values = plan_relationship_gate_route(archive, graphs, target)
                actual, satisfied = relationship_requirement_status(planned, graphs, target)
                self.assertTrue(satisfied)
                self.assertEqual(actual, values)
                self.assertTrue(path)
                self.assertEqual(planned["currentNode"], "preserve-me")
                self.assertEqual(planned["currentRoute"], {"nodes": ["preserve-route"]})


class SteamHelperTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_cloud_bridge_passes_utf8_string_and_reads_it_back(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rogd-steam-helper-test-") as temporary:
            root = Path(temporary)
            module_dir = root / "resources" / "app" / "node_modules" / "steamworks.js"
            module_dir.mkdir(parents=True)
            (module_dir / "index.js").write_text(
                "let stored = ''; module.exports.init = () => ({ cloud: {"
                "writeFile: (_name, value) => { if (typeof value !== 'string') "
                "throw new Error('expected string'); stored = value; return true; },"
                "readFile: () => stored } });",
                encoding="utf-8",
            )
            save_path = root / "archive.save"
            save_path.write_text(json.dumps({"测试": "云存档"}, ensure_ascii=False), encoding="utf-8")
            environment = os.environ.copy()
            environment["ROGD_GAME_DIR"] = str(root)
            result = subprocess.run(
                [
                    "node",
                    str(Path(__file__).resolve().parent / "steam_helper.js"),
                    "cloud-write",
                    "archive.save",
                    str(save_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            payload_line = next(line for line in result.stdout.splitlines() if line.startswith("ROGD_RESULT="))
            payload = json.loads(payload_line.removeprefix("ROGD_RESULT="))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["size"], len(save_path.read_bytes()))


if __name__ == "__main__":
    unittest.main()

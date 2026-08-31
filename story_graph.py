from __future__ import annotations

import copy
import json
from collections import deque
from pathlib import Path
from typing import Any

from rogd_model import BUNDLE_DIR, EditorError, validate_archive


STORY_GRAPHS_PATH = BUNDLE_DIR / "references" / "story_graphs.json"


def load_story_graphs(path: Path = STORY_GRAPHS_PATH) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        raise EditorError(f"缺少故事关系图：{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EditorError(f"无法读取故事关系图：{exc}") from exc
    if not isinstance(value, dict) or set(value) != {str(i) for i in range(1, 8)}:
        raise EditorError("故事关系图必须包含第一至第七章")
    for chapter, graph in value.items():
        if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
            raise EditorError(f"第 {chapter} 章故事关系图结构异常")
        ids = [node.get("id") for node in graph["nodes"] if isinstance(node, dict)]
        if len(ids) != len(graph["nodes"]) or len(set(ids)) != len(ids):
            raise EditorError(f"第 {chapter} 章存在无效或重复节点")
    return value


def all_story_nodes(graphs: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (chapter, node)
        for chapter in map(str, range(1, 8))
        for node in graphs[chapter]["nodes"]
    ]


def _node_index(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["id"]: node for node in graph["nodes"]}


def _shortest_path(graph: dict[str, Any], target: str) -> list[str]:
    nodes = _node_index(graph)
    if target not in nodes:
        raise EditorError(f"故事关系图中不存在节点 {target}")
    incoming = {edge["target"] for edge in graph["edges"]}
    roots = [node_id for node_id in nodes if node_id not in incoming]
    if len(roots) != 1:
        raise EditorError(f"节点 {target} 所在章节的入口数量异常：{roots}")
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for edge in graph["edges"]:
        source, destination = edge.get("source"), edge.get("target")
        if source in nodes and destination in nodes:
            adjacency[source].append(destination)
    queue = deque([roots[0]])
    previous: dict[str, str | None] = {roots[0]: None}
    while queue:
        current = queue.popleft()
        if current == target:
            break
        for destination in adjacency[current]:
            if destination not in previous:
                previous[destination] = current
                queue.append(destination)
    if target not in previous:
        raise EditorError(f"无法从章节入口抵达节点 {target}")
    result: list[str] = []
    cursor: str | None = target
    while cursor is not None:
        result.append(cursor)
        cursor = previous[cursor]
    return list(reversed(result))


def _chapter_completion(graph: dict[str, Any]) -> str:
    matches = [node["id"] for node in graph["nodes"] if node.get("category") == "chapEndFlag"]
    if len(matches) != 1:
        raise EditorError(f"章节完成节点数量异常：{matches}")
    return matches[0]


def plan_story_unlock(
    archive: dict[str, Any],
    graphs: dict[str, dict[str, Any]],
    target: str,
) -> tuple[dict[str, Any], list[str]]:
    validate_archive(archive)
    target_chapter = next(
        (chapter for chapter, node in all_story_nodes(graphs) if node.get("id") == target),
        None,
    )
    if target_chapter is None:
        raise EditorError(f"未知故事节点：{target}")
    if target in archive["nodeMap"]:
        return copy.deepcopy(archive), []

    full_path: list[str] = []
    metadata: dict[str, dict[str, Any]] = {}
    for chapter_number in range(1, int(target_chapter) + 1):
        chapter = str(chapter_number)
        graph = graphs[chapter]
        goal = target if chapter == target_chapter else _chapter_completion(graph)
        chapter_path = _shortest_path(graph, goal)
        if full_path and full_path[-1] == chapter_path[0]:
            chapter_path = chapter_path[1:]
        full_path.extend(chapter_path)
        metadata.update(_node_index(graph))

    updated = copy.deepcopy(archive)
    node_map = updated["nodeMap"]
    major_map = updated["majorMap"]
    added: list[str] = []

    segment_start = 0
    for index, node_id in enumerate(full_path):
        node = metadata[node_id]
        major_id = node.get("majorId")
        if not isinstance(major_id, str) or not major_id:
            raise EditorError(f"节点 {node_id} 缺少 majorId")
        if index == 0 or metadata[full_path[index - 1]].get("majorId") != major_id:
            segment_start = index
        previous_id = full_path[index - 1] if index else ""
        next_id = full_path[index + 1] if index + 1 < len(full_path) else ""
        record: dict[str, Any] = {
            "id": node_id,
            "lastNode": previous_id,
            "lastRoute": {"nodes": full_path[segment_start : index + 1]},
        }
        if next_id:
            record["lastNext"] = next_id
        if node_id not in node_map:
            node_map[node_id] = record
            added.append(node_id)

    segments: list[tuple[str, list[str]]] = []
    for node_id in full_path:
        major_id = metadata[node_id]["majorId"]
        if not segments or segments[-1][0] != major_id:
            segments.append((major_id, [node_id]))
        else:
            segments[-1][1].append(node_id)
    for index, (major_id, route) in enumerate(segments):
        previous_major = segments[index - 1][0] if index else ""
        next_major = segments[index + 1][0] if index + 1 < len(segments) else ""
        record = major_map.setdefault(
            major_id,
            {"lastMajorId": previous_major, "nextMajorId": next_major, "majorPaths": {}},
        )
        paths = record.setdefault("majorPaths", {})
        if next_major:
            paths.setdefault(next_major, route)

    validate_archive(updated)
    return updated, added

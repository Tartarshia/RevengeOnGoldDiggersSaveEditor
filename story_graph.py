from __future__ import annotations

import copy
import json
import re
from collections import deque
from pathlib import Path
from typing import Any

from rogd_model import BUNDLE_DIR, EditorError, validate_archive


STORY_GRAPHS_PATH = BUNDLE_DIR / "references" / "story_graphs.json"

RELATIONSHIP_CHARACTERS = {
    "yl": "陈欣欣（第一章）",
    "xt": "唐晓甜",
    "xr": "陈欣如",
    "xrza": "陈欣如·真爱",
    "sq": "宋诗琪",
    "yy": "何月盈",
    "mn": "潘梦娜",
    "xx": "陈欣欣·真爱",
    "sqfb": "宋诗琪分支标记",
    "yyfb": "何月盈分支标记",
}

CHAPTER_RELATIONSHIP_DEFAULTS = {
    "1": ("yl", "陈欣欣"),
    "2": ("xt", "唐晓甜"),
    "3": ("xrza", "陈欣如·真爱"),
    "4": ("sq", "宋诗琪"),
    "5": ("yy", "何月盈"),
    "6": ("mn", "潘梦娜"),
    "7": ("mn", "潘梦娜·终章"),
}


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


def plan_chapter_unlock(
    archive: dict[str, Any],
    graphs: dict[str, dict[str, Any]],
    chapter: str,
) -> tuple[dict[str, Any], list[str]]:
    validate_archive(archive)
    if chapter not in graphs:
        raise EditorError(f"未知章节：{chapter}")

    updated = copy.deepcopy(archive)
    changed: list[str] = []
    for node in graphs[chapter]["nodes"]:
        node_id = node["id"]
        if node_id in updated["nodeMap"]:
            continue
        updated, newly_added = plan_story_unlock(updated, graphs, node_id)
        changed.extend(newly_added)

    # A node without lastNext means "entered but not finished" in the game's
    # archive format.  That raises map completion, but does not unlock the
    # normal replay/fast-forward behavior.  Complete each non-terminal chapter
    # record with one valid outgoing edge, without replacing a route the player
    # actually recorded.
    outgoing: dict[str, list[str]] = {}
    for edge in graphs[chapter]["edges"]:
        outgoing.setdefault(edge["source"], []).append(edge["target"])
    for node in graphs[chapter]["nodes"]:
        node_id = node["id"]
        record = updated["nodeMap"].get(node_id)
        destinations = outgoing.get(node_id, [])
        if record is None or not destinations or record.get("lastNext"):
            continue
        record["lastNext"] = destinations[0]
        if node_id not in changed:
            changed.append(node_id)

    validate_archive(updated)
    return updated, changed


def chapter_unlock_status(
    archive: dict[str, Any],
    graphs: dict[str, dict[str, Any]],
    chapter: str,
) -> tuple[set[str], set[str]]:
    if chapter not in graphs:
        raise EditorError(f"未知章节：{chapter}")
    graph = graphs[chapter]
    chapter_ids = {node["id"] for node in graph["nodes"]}
    missing = chapter_ids.difference(archive["nodeMap"])
    nonterminal = {edge["source"] for edge in graph["edges"]}
    unfinished = {
        node_id
        for node_id in chapter_ids.intersection(archive["nodeMap"])
        if node_id in nonterminal and not archive["nodeMap"][node_id].get("lastNext")
    }
    return missing, unfinished


def story_route_score(
    archive: dict[str, Any],
    graph: dict[str, Any],
    target: str,
    field: str,
) -> int:
    nodes = _node_index(graph)
    score = 0
    cursor = target
    visited: set[str] = set()
    while cursor in nodes and cursor in archive["nodeMap"] and cursor not in visited:
        visited.add(cursor)
        relationship = nodes[cursor].get("relationship") or {}
        value = relationship.get(field, 0)
        if isinstance(value, (int, float)):
            score += int(value)
        cursor = archive["nodeMap"][cursor].get("lastNode", "")
    return score


def relationship_gate_nodes(
    graphs: dict[str, dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    """Return every node whose availability depends on a relationship value."""
    return [
        (chapter, node)
        for chapter, node in all_story_nodes(graphs)
        if "r." in (node.get("requirement") or "")
    ]


def story_route_values(
    archive: dict[str, Any],
    graphs: dict[str, dict[str, Any]],
    target: str,
    fields: list[str] | tuple[str, ...] | set[str],
) -> dict[str, int]:
    metadata = {node["id"]: node for _, node in all_story_nodes(graphs)}
    values = {field: 0 for field in fields}
    cursor = target
    visited: set[str] = set()
    while cursor in metadata and cursor in archive["nodeMap"] and cursor not in visited:
        visited.add(cursor)
        relationship = metadata[cursor].get("relationship") or {}
        for field in values:
            raw = relationship.get(field, 0)
            if isinstance(raw, (int, float)):
                values[field] += int(raw)
        cursor = archive["nodeMap"][cursor].get("lastNode", "")
    return values


def relationship_fields(requirement: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"r\.([A-Za-z_][A-Za-z0-9_]*)", requirement)))


def _requirement_satisfied(
    requirement: str,
    values: dict[str, int],
    seen_nodes: set[str],
) -> bool:
    def term_satisfied(term: str) -> bool:
        term = term.strip()
        node_match = re.fullmatch(r"n\.([A-Za-z0-9_]+)", term)
        if node_match:
            return node_match.group(1) in seen_nodes
        comparison = re.fullmatch(
            r"r\.([A-Za-z_][A-Za-z0-9_]*)\s*(<=|>=|==|!=|<|>)\s*"
            r"(?:r\.([A-Za-z_][A-Za-z0-9_]*)|(-?\d+))",
            term,
        )
        if not comparison:
            raise EditorError(f"暂不支持的隐藏数值规则：{term}")
        left = values.get(comparison.group(1), 0)
        right = values.get(comparison.group(3), 0) if comparison.group(3) else int(comparison.group(4))
        operator = comparison.group(2)
        return {
            "<=": left <= right,
            ">=": left >= right,
            "==": left == right,
            "!=": left != right,
            "<": left < right,
            ">": left > right,
        }[operator]

    return any(
        all(term_satisfied(term) for term in and_group.split("&&"))
        for and_group in requirement.split("||")
    )


def relationship_requirement_status(
    archive: dict[str, Any],
    graphs: dict[str, dict[str, Any]],
    target: str,
) -> tuple[dict[str, int], bool]:
    node = next((node for _, node in all_story_nodes(graphs) if node["id"] == target), None)
    if node is None:
        raise EditorError(f"未知故事节点：{target}")
    requirement = node.get("requirement") or ""
    fields = relationship_fields(requirement)
    values = story_route_values(archive, graphs, target, fields)
    return values, target in archive["nodeMap"] and _requirement_satisfied(
        requirement, values, set(archive["nodeMap"])
    )


def _topological_graph(graph: dict[str, Any]) -> tuple[str, list[str], dict[str, list[str]]]:
    nodes = _node_index(graph)
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    indegree = {node_id: 0 for node_id in nodes}
    for edge in graph["edges"]:
        source, destination = edge.get("source"), edge.get("target")
        if source in nodes and destination in nodes:
            adjacency[source].append(destination)
            indegree[destination] += 1
    roots = [node_id for node_id, degree in indegree.items() if degree == 0]
    if len(roots) != 1:
        raise EditorError(f"章节入口数量异常：{roots}")
    queue = deque(roots)
    order: list[str] = []
    while queue:
        node_id = queue.popleft()
        order.append(node_id)
        for destination in adjacency[node_id]:
            indegree[destination] -= 1
            if indegree[destination] == 0:
                queue.append(destination)
    if len(order) != len(nodes):
        raise EditorError("故事关系图存在循环，无法规划隐藏数值路线")
    return roots[0], order, adjacency


def _paths_to_goal(
    graph: dict[str, Any],
    goal: str,
    fields: list[str],
    incoming: dict[tuple[int, ...], list[str]],
) -> dict[tuple[int, ...], list[str]]:
    nodes = _node_index(graph)
    if goal not in nodes:
        raise EditorError(f"故事关系图中不存在节点 {goal}")
    root, order, adjacency = _topological_graph(graph)
    states: dict[str, dict[tuple[int, ...], list[str]]] = {node_id: {} for node_id in nodes}

    def add_values(values: tuple[int, ...], node_id: str) -> tuple[int, ...]:
        relationship = nodes[node_id].get("relationship") or {}
        return tuple(values[index] + int(relationship.get(field, 0)) for index, field in enumerate(fields))

    for values, path in incoming.items():
        states[root].setdefault(add_values(values, root), path + [root])
    for source in order:
        if source == goal:
            continue
        for destination in adjacency[source]:
            for values, path in states[source].items():
                states[destination].setdefault(add_values(values, destination), path + [destination])
        if sum(len(item) for item in states.values()) > 250_000:
            raise EditorError("可选路线组合过多，已停止以避免修改器无响应")
    return states[goal]


def _rewrite_selected_route(
    archive: dict[str, Any],
    graphs: dict[str, dict[str, Any]],
    path: list[str],
) -> dict[str, Any]:
    updated = copy.deepcopy(archive)
    metadata = {node["id"]: node for _, node in all_story_nodes(graphs)}
    node_map = updated["nodeMap"]
    major_map = updated["majorMap"]
    root_previous = node_map.get(path[0], {}).get("lastNode", "")
    segment_start = 0
    for index, node_id in enumerate(path):
        major_id = metadata[node_id]["majorId"]
        if index == 0 or metadata[path[index - 1]]["majorId"] != major_id:
            segment_start = index
        next_id = path[index + 1] if index + 1 < len(path) else node_map.get(node_id, {}).get("lastNext", "")
        record: dict[str, Any] = {
            "id": node_id,
            "lastNode": path[index - 1] if index else root_previous,
            "lastRoute": {"nodes": path[segment_start : index + 1]},
        }
        if next_id:
            record["lastNext"] = next_id
        node_map[node_id] = record

    segments: list[tuple[str, list[str]]] = []
    for node_id in path:
        major_id = metadata[node_id]["majorId"]
        if not segments or segments[-1][0] != major_id:
            segments.append((major_id, [node_id]))
        else:
            segments[-1][1].append(node_id)
    for index, (major_id, route) in enumerate(segments):
        record = major_map.setdefault(major_id, {"lastMajorId": "", "nextMajorId": "", "majorPaths": {}})
        if index:
            record["lastMajorId"] = segments[index - 1][0]
        if index + 1 < len(segments):
            next_major = segments[index + 1][0]
            record["nextMajorId"] = next_major
            record.setdefault("majorPaths", {})[next_major] = route
    return updated


def plan_relationship_gate_route(
    archive: dict[str, Any],
    graphs: dict[str, dict[str, Any]],
    target: str,
) -> tuple[dict[str, Any], list[str], dict[str, int]]:
    """Build a real recorded route that satisfies one selected relationship gate."""
    validate_archive(archive)
    target_entry = next(
        ((chapter, node) for chapter, node in all_story_nodes(graphs) if node["id"] == target),
        None,
    )
    if target_entry is None:
        raise EditorError(f"未知故事节点：{target}")
    target_chapter, target_node = target_entry
    requirement = target_node.get("requirement") or ""
    fields = relationship_fields(requirement)
    if not fields:
        raise EditorError(f"节点 {target} 没有隐藏数值门槛")

    # Never rewrite earlier chapters to satisfy a later gate. The game keeps
    # additional private playback indexes alongside these records and rejects
    # a syntactically valid archive if old chapter choices are replaced en
    # masse. Only the selected chapter may be rebuilt here.
    updated, _ = plan_chapter_unlock(archive, graphs, target_chapter)
    graph = graphs[target_chapter]
    root, _, _ = _topological_graph(graph)
    root_previous = updated["nodeMap"].get(root, {}).get("lastNode", "")
    incoming_values = story_route_values(updated, graphs, root_previous, fields)
    states = _paths_to_goal(
        graph,
        target,
        fields,
        {tuple(incoming_values[field] for field in fields): []},
    )
    seen_nodes = set(updated["nodeMap"])
    candidates = [
        (values, path)
        for values, path in states.items()
        if _requirement_satisfied(requirement, dict(zip(fields, values)), seen_nodes)
    ]
    if not candidates:
        inherited = "、".join(
            RELATIONSHIP_CHARACTERS.get(field, field) for field in fields
        )
        raise EditorError(
            f"仅修改第 {target_chapter} 章无法满足 {requirement}。"
            f"它依赖前章的 {inherited} 数值；为保护已完成章节，本版本不会跨章改写。"
        )
    # Prefer the strongest route that still belongs to the selected outcome.
    # This leaves headroom for later deductions instead of merely touching the
    # threshold (for example yy=170 for a >=170 gate).
    values_tuple, path = max(
        candidates,
        key=lambda item: (sum(item[0]), -len(item[1])),
    )

    chapter_ids = {node["id"] for node in graph["nodes"]}
    protected_nodes = {
        node_id: copy.deepcopy(record)
        for node_id, record in archive["nodeMap"].items()
        if node_id not in chapter_ids
    }
    chapter_major_ids = {node["majorId"] for node in graph["nodes"]}
    protected_majors = {
        major_id: copy.deepcopy(record)
        for major_id, record in archive["majorMap"].items()
        if major_id not in chapter_major_ids
    }
    # plan_chapter_unlock may opportunistically add alternate majorPaths while
    # discovering missing nodes. Restore every pre-existing outside-chapter
    # record before applying the selected route.
    updated["nodeMap"].update(copy.deepcopy(protected_nodes))
    updated["majorMap"].update(copy.deepcopy(protected_majors))
    updated = _rewrite_selected_route(updated, graphs, path)
    if any(updated["nodeMap"].get(key) != value for key, value in protected_nodes.items()):
        raise EditorError("安全检查失败：规划过程试图修改前章节点，已取消写入")
    if any(updated["majorMap"].get(key) != value for key, value in protected_majors.items()):
        raise EditorError("安全检查失败：规划过程试图修改前章路线索引，已取消写入")
    values = story_route_values(updated, graphs, target, fields)
    if not _requirement_satisfied(requirement, values, set(updated["nodeMap"])):
        raise EditorError("隐藏数值路线写入后未通过所选门槛复算")
    validate_archive(updated)
    return updated, path, values


def _maximum_score_path(graph: dict[str, Any], target: str, field: str) -> tuple[list[str], int]:
    nodes = _node_index(graph)
    if target not in nodes:
        raise EditorError(f"故事关系图中不存在节点 {target}")
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    indegree = {node_id: 0 for node_id in nodes}
    for edge in graph["edges"]:
        source, destination = edge.get("source"), edge.get("target")
        if source in nodes and destination in nodes:
            adjacency[source].append(destination)
            indegree[destination] += 1
    queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while queue:
        node_id = queue.popleft()
        order.append(node_id)
        for destination in adjacency[node_id]:
            indegree[destination] -= 1
            if indegree[destination] == 0:
                queue.append(destination)
    if len(order) != len(nodes):
        raise EditorError("故事关系图存在循环，无法规划隐藏数值路线")

    def value(node_id: str) -> int:
        raw = (nodes[node_id].get("relationship") or {}).get(field, 0)
        return int(raw) if isinstance(raw, (int, float)) else 0

    unreachable = -10**9
    scores = {node_id: unreachable for node_id in nodes}
    previous: dict[str, str] = {}
    roots = [node_id for node_id in order if all(node_id not in values for values in adjacency.values())]
    if len(roots) != 1:
        raise EditorError(f"章节入口数量异常：{roots}")
    scores[roots[0]] = value(roots[0])
    for source in order:
        if scores[source] == unreachable:
            continue
        for destination in adjacency[source]:
            candidate = scores[source] + value(destination)
            if candidate > scores[destination]:
                scores[destination] = candidate
                previous[destination] = source
    if scores[target] == unreachable:
        raise EditorError(f"无法抵达隐藏数值目标节点 {target}")
    path: list[str] = []
    cursor = target
    while cursor in nodes:
        path.append(cursor)
        if cursor == roots[0]:
            break
        cursor = previous[cursor]
    return list(reversed(path)), scores[target]


def _maximum_valid_score_path(
    archive: dict[str, Any],
    graphs: dict[str, dict[str, Any]],
    chapter: str,
    target: str,
    primary_field: str,
) -> tuple[list[str], int]:
    graph = graphs[chapter]
    nodes = _node_index(graph)
    fields = list(
        dict.fromkeys(
            [primary_field]
            + [
                field
                for node in graph["nodes"]
                for field in relationship_fields(node.get("requirement") or "")
            ]
        )
    )
    root, order, adjacency = _topological_graph(graph)
    root_previous = archive["nodeMap"].get(root, {}).get("lastNode", "")
    incoming = story_route_values(archive, graphs, root_previous, fields)
    seen_nodes = set(archive["nodeMap"])
    states: dict[str, dict[tuple[int, ...], list[str]]] = {node_id: {} for node_id in nodes}

    def add(values: tuple[int, ...], node_id: str) -> tuple[int, ...]:
        relationship = nodes[node_id].get("relationship") or {}
        return tuple(values[index] + int(relationship.get(field, 0)) for index, field in enumerate(fields))

    def allowed(node_id: str, values: tuple[int, ...]) -> bool:
        requirement = nodes[node_id].get("requirement") or ""
        return not requirement or _requirement_satisfied(
            requirement, dict(zip(fields, values)), seen_nodes
        )

    root_values = add(tuple(incoming[field] for field in fields), root)
    if allowed(root, root_values):
        states[root][root_values] = [root]
    for source in order:
        for destination in adjacency[source]:
            for values, path in states[source].items():
                candidate = add(values, destination)
                if allowed(destination, candidate):
                    states[destination].setdefault(candidate, path + [destination])
        if sum(len(item) for item in states.values()) > 250_000:
            raise EditorError("最高值路线组合过多，已停止以避免修改器无响应")
    if not states.get(target):
        raise EditorError(f"在当前前章数值下，找不到抵达 {target} 的合法最高值路线")
    primary_index = fields.index(primary_field)
    values, path = max(
        states[target].items(),
        key=lambda item: (item[0][primary_index], sum(item[0]), -len(item[1])),
    )
    return path, values[primary_index]


def plan_maximum_relationship_route(
    archive: dict[str, Any],
    graphs: dict[str, dict[str, Any]],
    chapter: str,
    field: str,
    target: str,
) -> tuple[dict[str, Any], list[str], int]:
    validate_archive(archive)
    if chapter not in graphs:
        raise EditorError(f"未知章节：{chapter}")
    graph = graphs[chapter]
    chapter_ids = {node["id"] for node in graph["nodes"]}
    protected_nodes = {
        node_id: copy.deepcopy(record)
        for node_id, record in archive["nodeMap"].items()
        if node_id not in chapter_ids
    }
    chapter_major_ids = {node["majorId"] for node in graph["nodes"]}
    protected_majors = {
        major_id: copy.deepcopy(record)
        for major_id, record in archive["majorMap"].items()
        if major_id not in chapter_major_ids
    }
    updated, _ = plan_chapter_unlock(archive, graphs, chapter)
    updated["nodeMap"].update(copy.deepcopy(protected_nodes))
    updated["majorMap"].update(copy.deepcopy(protected_majors))
    path, score = _maximum_valid_score_path(updated, graphs, chapter, target, field)
    updated = _rewrite_selected_route(updated, graphs, path)

    if any(updated["nodeMap"].get(key) != value for key, value in protected_nodes.items()):
        raise EditorError("安全检查失败：最高值路线试图修改其他章节节点")
    if any(updated["majorMap"].get(key) != value for key, value in protected_majors.items()):
        raise EditorError("安全检查失败：最高值路线试图修改其他章节索引")

    validate_archive(updated)
    if story_route_values(updated, graphs, target, [field])[field] != score:
        raise EditorError("隐藏数值路线写入后复算不一致")
    for node_id in path:
        requirement = _node_index(graph)[node_id].get("requirement") or ""
        if "r." in requirement:
            _, satisfied = relationship_requirement_status(updated, graphs, node_id)
            if not satisfied:
                raise EditorError(f"最高值路线在 {node_id} 未通过中途门槛 {requirement}")
    return updated, path, score


def plan_maximum_chapter_relationship_route(
    archive: dict[str, Any],
    graphs: dict[str, dict[str, Any]],
    chapter: str,
) -> tuple[dict[str, Any], list[str], str, int, int]:
    if chapter not in CHAPTER_RELATIONSHIP_DEFAULTS:
        raise EditorError(f"第 {chapter} 章没有默认沉沦值路线")
    field, _ = CHAPTER_RELATIONSHIP_DEFAULTS[chapter]
    target = "n1725a1" if chapter == "7" else _chapter_completion(graphs[chapter])
    before = story_route_values(archive, graphs, target, [field])[field]
    updated, path, _ = plan_maximum_relationship_route(
        archive, graphs, chapter, field, target
    )
    after = story_route_values(updated, graphs, target, [field])[field]
    return updated, path, field, before, after

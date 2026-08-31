from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rogd_model import APP_ID, EditorError, find_steam_root


@dataclass(frozen=True)
class Achievement:
    achievement_id: str
    name: str
    description: str
    hidden: bool


class BinaryVdfReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self, count: int) -> bytes:
        end = self.pos + count
        if end > len(self.data):
            raise EditorError("Steam 成就 schema 意外结束")
        value = self.data[self.pos:end]
        self.pos = end
        return value

    def cstring(self, encoding: str = "utf-8") -> str:
        end = self.data.find(b"\0", self.pos)
        if end < 0:
            raise EditorError("Steam 成就 schema 缺少字符串结束符")
        raw = self.data[self.pos:end]
        self.pos = end + 1
        return raw.decode(encoding, errors="replace")

    def obj(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while self.pos < len(self.data):
            value_type = self.read(1)[0]
            if value_type in (8, 11):
                return result
            key = self.cstring()
            if value_type == 0:
                value: Any = self.obj()
            elif value_type == 1:
                value = self.cstring()
            elif value_type == 2:
                value = struct.unpack("<i", self.read(4))[0]
            elif value_type == 3:
                value = struct.unpack("<f", self.read(4))[0]
            elif value_type == 4:
                value = struct.unpack("<I", self.read(4))[0]
            elif value_type == 5:
                char_count = struct.unpack("<H", self.read(2))[0]
                raw = self.read(char_count * 2)
                value = raw.decode("utf-16-le", errors="replace").rstrip("\0")
            elif value_type == 6:
                value = self.read(4)
            elif value_type == 7:
                value = struct.unpack("<Q", self.read(8))[0]
            elif value_type == 10:
                value = struct.unpack("<q", self.read(8))[0]
            else:
                raise EditorError(f"不支持的 Steam schema 值类型：{value_type}")
            result[key] = value
        return result


def schema_path() -> Path:
    path = find_steam_root() / "appcache" / "stats" / f"UserGameStatsSchema_{APP_ID}.bin"
    if not path.is_file():
        raise EditorError(f"没有找到 Steam 成就 schema：{path}")
    return path


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)


def _localized(value: Any, language: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get(language) or value.get("english") or "")
    return ""


def load_achievements(language: str = "schinese") -> list[Achievement]:
    reader = BinaryVdfReader(schema_path().read_bytes())
    root = reader.obj()
    found: dict[str, Achievement] = {}
    for record in _walk(root):
        achievement_id = record.get("name")
        if not isinstance(achievement_id, str) or not re.fullmatch(r"a\d+", achievement_id):
            continue
        display = record.get("display")
        if not isinstance(display, dict):
            continue
        name = _localized(display.get("name"), language)
        description = _localized(display.get("desc"), language)
        if name:
            found[achievement_id] = Achievement(
                achievement_id,
                name,
                description,
                bool(display.get("hidden", 0)),
            )
    if len(found) < 39:
        raise EditorError(f"只从 Steam schema 解析到 {len(found)} 项成就，预期至少 39 项。")
    return sorted(found.values(), key=lambda item: int(item.achievement_id[1:]))

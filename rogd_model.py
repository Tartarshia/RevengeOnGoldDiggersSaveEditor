from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


APP_ID = "3350200"
GAME_EXE = "RevengeOnGoldDiggers.exe"
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
PROJECT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
STEAM_HELPER = BUNDLE_DIR / "steam_helper.js"


class EditorError(RuntimeError):
    pass


@dataclass(frozen=True)
class SavePaths:
    remote_dir: Path
    archive: Path
    setting: Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def find_steam_root() -> Path:
    candidates: list[Path] = [
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Steam",
    ]
    if os.name == "nt":
        try:
            import winreg

            for hive, key_name, value_name in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            ):
                try:
                    with winreg.OpenKey(hive, key_name) as key:
                        candidates.insert(0, Path(winreg.QueryValueEx(key, value_name)[0]))
                except OSError:
                    pass
        except ImportError:
            pass
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen and (resolved / "userdata").is_dir():
            return resolved
        seen.add(resolved)
    raise EditorError("没有找到 Steam userdata 目录。")


def find_game_dir() -> Path:
    override = os.environ.get("ROGD_GAME_DIR")
    if override:
        candidate = Path(override)
        if (candidate / GAME_EXE).is_file():
            return candidate
        raise EditorError(f"ROGD_GAME_DIR 中没有找到游戏：{candidate}")
    steam_root = find_steam_root()
    libraries = [steam_root]
    library_file = steam_root / "steamapps" / "libraryfolders.vdf"
    if library_file.is_file():
        try:
            content = library_file.read_text(encoding="utf-8", errors="replace")
            import re

            for raw_path in re.findall(r'"path"\s+"([^"]+)"', content):
                libraries.append(Path(raw_path.replace(r"\\", "\\")))
        except OSError:
            pass
    for library in libraries:
        candidate = library / "steamapps" / "common" / "RevengeOnGoldDiggers"
        if (candidate / GAME_EXE).is_file():
            return candidate
    raise EditorError("没有在 Steam 库中找到《情感反诈模拟器》。")


def discover_save_paths() -> SavePaths:
    steam_root = find_steam_root()
    matches: list[Path] = []
    for user_dir in (steam_root / "userdata").iterdir():
        remote = user_dir / APP_ID / "remote"
        if (remote / "archive.save").is_file() and (remote / "setting.save").is_file():
            matches.append(remote)
    if not matches:
        raise EditorError(f"没有找到 AppID {APP_ID} 的 archive.save / setting.save。")
    matches.sort(
        key=lambda p: max((p / "archive.save").stat().st_mtime, (p / "setting.save").stat().st_mtime),
        reverse=True,
    )
    remote = matches[0]
    return SavePaths(remote, remote / "archive.save", remote / "setting.save")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EditorError(f"无法读取 JSON 存档 {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EditorError(f"存档顶层不是 JSON 对象：{path}")
    return value


def validate_setting(value: dict[str, Any]) -> None:
    for section in ("roleProfile", "loveDrama"):
        records = value.get(section)
        if not isinstance(records, dict):
            raise EditorError(f"setting.save 缺少对象字段 {section}")
        for item_id, record in records.items():
            if not isinstance(item_id, str) or not isinstance(record, dict):
                raise EditorError(f"{section} 中存在异常记录")
            if not isinstance(record.get("unLock"), bool):
                raise EditorError(f"{section}.{item_id}.unLock 不是布尔值")


def validate_archive(value: dict[str, Any]) -> None:
    if not isinstance(value.get("nodeMap"), dict):
        raise EditorError("archive.save 缺少 nodeMap")
    if not isinstance(value.get("majorMap"), dict):
        raise EditorError("archive.save 缺少 majorMap")


def is_game_running() -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {GAME_EXE}", "/NH"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    return GAME_EXE.lower() in result.stdout.lower()


def ensure_game_closed() -> None:
    if is_game_running():
        raise EditorError("游戏仍在运行。请先退到桌面并完全关闭游戏，再执行写入。")


def create_backup(paths: SavePaths) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_dir = PROJECT_DIR / "backups" / stamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    for source in (paths.archive, paths.setting):
        shutil.copy2(source, backup_dir / source.name)
    manifest = {
        "created": datetime.now().astimezone().isoformat(),
        "source": str(paths.remote_dir),
        "files": {
            name: sha256_file(backup_dir / name)
            for name in ("archive.save", "setting.save")
        },
    }
    (backup_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return backup_dir


def encode_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def run_steam_helper(*args: str, timeout: int = 20) -> dict[str, Any]:
    if not STEAM_HELPER.is_file():
        raise EditorError(f"缺少 Steam 辅助程序：{STEAM_HELPER}")
    game_dir = find_game_dir()
    command = [str(game_dir / GAME_EXE), str(STEAM_HELPER), *args]
    environment = os.environ.copy()
    environment["ELECTRON_RUN_AS_NODE"] = "1"
    environment["ROGD_GAME_DIR"] = str(game_dir)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except FileNotFoundError as exc:
        raise EditorError("无法启动游戏自带的 Electron/Node 运行时。") from exc
    except subprocess.TimeoutExpired as exc:
        raise EditorError("Steam 接口响应超时。") from exc
    marker = "ROGD_RESULT="
    payload = None
    for line in reversed(result.stdout.splitlines()):
        if line.startswith(marker):
            payload = line[len(marker) :]
            break
    if payload is None:
        detail = (result.stderr or result.stdout or "无输出").strip()
        raise EditorError(f"Steam 接口失败（exit {result.returncode}）：{detail[-1000:]}")
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise EditorError("Steam 接口返回了无效结果。") from exc
    if result.returncode != 0 or not decoded.get("ok"):
        raise EditorError(str(decoded.get("error") or "Steam 接口操作失败"))
    return decoded


def save_setting(paths: SavePaths, setting: dict[str, Any]) -> tuple[Path, str]:
    ensure_game_closed()
    validate_setting(setting)
    data = encode_json(setting)
    json.loads(data.decode("utf-8"))
    backup_dir = create_backup(paths)
    original = paths.setting.read_bytes()
    try:
        atomic_write(paths.setting, data)
        if paths.setting.read_bytes() != data:
            raise EditorError("本地原子写入后的字节复读不一致。")
        cloud_result = run_steam_helper("cloud-write", "setting.save", str(paths.setting))
        expected = sha256_bytes(data)
        if cloud_result.get("sha256") != expected:
            raise EditorError("Steam Cloud 写入后的哈希复读不一致。")
        if paths.setting.read_bytes() != data:
            raise EditorError("Steam Cloud 操作后，本地文件字节发生了意外变化。")
    except Exception:
        atomic_write(paths.setting, original)
        try:
            run_steam_helper("cloud-write", "setting.save", str(paths.setting))
        except Exception:
            pass
        raise
    return backup_dir, sha256_bytes(data)


def save_archive(paths: SavePaths, archive: dict[str, Any]) -> tuple[Path, str]:
    ensure_game_closed()
    validate_archive(archive)
    data = encode_json(archive)
    decoded = json.loads(data.decode("utf-8"))
    validate_archive(decoded)
    backup_dir = create_backup(paths)
    original = paths.archive.read_bytes()
    try:
        atomic_write(paths.archive, data)
        if paths.archive.read_bytes() != data:
            raise EditorError("本地原子写入后的字节复读不一致。")
        cloud_result = run_steam_helper("cloud-write", "archive.save", str(paths.archive))
        expected = sha256_bytes(data)
        if cloud_result.get("sha256") != expected:
            raise EditorError("Steam Cloud 写入后的哈希复读不一致。")
        if paths.archive.read_bytes() != data:
            raise EditorError("Steam Cloud 操作后，本地文件字节发生了意外变化。")
    except Exception:
        atomic_write(paths.archive, original)
        try:
            run_steam_helper("cloud-write", "archive.save", str(paths.archive))
        except Exception:
            pass
        raise
    return backup_dir, sha256_bytes(data)

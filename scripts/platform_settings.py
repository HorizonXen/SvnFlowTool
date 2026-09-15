"""Load application settings without binding the merge engine to macOS defaults."""

from __future__ import annotations

import json
import os
import pathlib
import plistlib
import subprocess
import sys


LEGACY_BUNDLE_ID = "com.self.svnflow"
DEV_COPY_ID = "39af147e-c164-4dd0-a66a-000000000001"
RELEASE_COPY_ID = "39af147e-c164-4dd0-a66a-000000000002"


def default_config_path() -> pathlib.Path:
    override = os.environ.get("SVNFLOW_CONFIG")
    if override:
        return pathlib.Path(override).expanduser()
    if os.name == "nt":
        root = pathlib.Path(os.environ.get("APPDATA", pathlib.Path.home()))
        return root / "SvnFlow" / "config.json"
    root = pathlib.Path(os.environ.get("XDG_CONFIG_HOME", pathlib.Path.home() / ".config"))
    return root / "svnflow" / "config.json"


def _json_config() -> dict | None:
    path = default_config_path()
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"配置文件必须是 JSON 对象：{path}")
    return value


def _legacy_macos_config() -> dict | None:
    if sys.platform != "darwin":
        return None
    try:
        data = subprocess.check_output(
            ["defaults", "export", LEGACY_BUNDLE_ID, "-"],
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return plistlib.loads(data)


def load_config() -> dict:
    value = _json_config() or _legacy_macos_config()
    if value is None:
        raise RuntimeError(
            "未找到工作副本配置。请在应用中完成配置，或设置 SVNFLOW_CONFIG 指向配置 JSON。"
        )
    return value


def fixed_copies() -> list[dict]:
    value = load_config()
    copies = value.get("fixedCopies", value.get("SvnFlow.fixedCopies.v1"))
    if isinstance(copies, (bytes, bytearray)):
        copies = bytes(copies).decode("utf-8")
    if isinstance(copies, str):
        copies = json.loads(copies)
    if not isinstance(copies, list):
        raise RuntimeError("工作副本配置缺少 fixedCopies 数组。")
    required = {"id", "path"}
    if any(not isinstance(item, dict) or not required <= item.keys() for item in copies):
        raise RuntimeError("工作副本配置格式无效。")
    return copies


def merge_copies() -> tuple[dict, dict]:
    copies = fixed_copies()

    def choose(role: str, stable_id: str, legacy_suffix: str) -> dict:
        role_names = {role, "source" if role == "dev" else "target"}
        explicit = [item for item in copies if str(item.get("role", "")).lower() in role_names]
        stable = [item for item in copies if str(item.get("id", "")).lower() == stable_id]
        legacy = [item for item in copies if str(item.get("id", "")).endswith(legacy_suffix)]
        candidates = explicit or stable or legacy
        if len(candidates) != 1 or not str(candidates[0].get("path", "")).strip():
            label = "Dev" if role == "dev" else "Release"
            raise RuntimeError(f"请先手动配置有效的 {label} 工作副本目录。")
        return candidates[0]

    dev = choose("dev", DEV_COPY_ID, "1")
    release = choose("release", RELEASE_COPY_ID, "2")
    if dev is release or pathlib.Path(dev["path"]).resolve() == pathlib.Path(release["path"]).resolve():
        raise RuntimeError("Dev 和 Release 必须配置为两个不同的工作副本目录。")
    return dev, release


def endpoint_name(path: str, fallback: str) -> str:
    normalized = str(path).strip().replace("\\", "/").strip("/")
    if not normalized:
        return fallback
    name = normalized.rsplit("/", 1)[-1]
    return fallback if not name or name.endswith(":") else name

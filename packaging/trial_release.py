#!/usr/bin/env python3
"""Bind a human trial approval to one exact release archive."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys


def safe_print(message: str, *, file=None) -> None:
    """Avoid legacy Windows console encodings breaking release checks."""
    stream = sys.stdout if file is None else file
    encoding = getattr(stream, "encoding", None) or "utf-8"
    printable = message.encode(encoding, errors="replace").decode(encoding)
    print(printable, file=stream)


def release_identity(root: pathlib.Path) -> dict:
    release = json.loads((root / "release.json").read_text(encoding="utf-8"))
    version, build = str(release["version"]), int(release["build"])
    archive = root / "dist" / f"SvnFlow-macOS-arm64-{version}-{build}.zip"
    if not archive.is_file():
        raise RuntimeError(f"找不到当前试用包：{archive}")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return {"schema": 1, "version": version, "build": build, "archive": archive.name, "sha256": digest}


def approval_path(root: pathlib.Path) -> pathlib.Path:
    return root / ".build" / "trial-approval.json"


def approve(root: pathlib.Path) -> None:
    value = release_identity(root)
    value["approvedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    path = approval_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    safe_print(f"已确认试用通过：{value['version']} ({value['build']}) · {value['sha256']}")


def verify(root: pathlib.Path) -> None:
    expected = release_identity(root)
    path = approval_path(root)
    if not path.is_file():
        raise RuntimeError("尚未确认当前试用包。请先实际试用，再运行 packaging/approve-trial.sh。")
    actual = json.loads(path.read_text(encoding="utf-8"))
    for key in ("schema", "version", "build", "archive", "sha256"):
        if actual.get(key) != expected[key]:
            raise RuntimeError("试用确认与当前安装包不匹配；请重新试用当前包后再确认。")
    safe_print(f"试用确认有效：{expected['version']} ({expected['build']})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("approve", "verify"))
    parser.add_argument("root", type=pathlib.Path)
    args = parser.parse_args()
    try:
        (approve if args.mode == "approve" else verify)(args.root.resolve())
    except (OSError, ValueError, KeyError, json.JSONDecodeError, RuntimeError) as error:
        safe_print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

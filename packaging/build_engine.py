#!/usr/bin/env python3
"""Build the restricted merge runtime for the current operating system."""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".build" / "engine-dist"
RUNTIME_MODULES = [
    "branch_sync",
    "deletion_guard",
    "file_sync",
    "galaxy_sync",
    "lua_sync",
    "platform_lock",
    "platform_settings",
    "revision_cache",
    "staged_sync",
    "sync_progress",
    "text_review",
    "workbook_cells",
    "workbook_compact",
    "workbook_dom",
    "workbook_history",
    "workbook_inspect",
    "workbook_native",
    "workbook_sparse",
    "workbook_sync",
    "xtools_export",
]


def main() -> int:
    work = ROOT / ".build" / "pyinstaller"
    shutil.rmtree(work, ignore_errors=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "svnflow-python",
        "--distpath",
        str(OUTPUT),
        "--workpath",
        str(work / "work"),
        "--specpath",
        str(work / "spec"),
    ]
    for module in ["lxml.etree", *RUNTIME_MODULES]:
        command += ["--hidden-import", module]
    command.append(str(ROOT / "scripts" / "engine_entry.py"))
    subprocess.run(command, cwd=ROOT, check=True)
    suffix = ".exe" if sys.platform == "win32" else ""
    product = OUTPUT / ("svnflow-python" + suffix)
    if not product.is_file():
        raise RuntimeError(f"engine product is missing: {product}")
    print(product)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

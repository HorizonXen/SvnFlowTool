#!/usr/bin/env python3
"""Build the installable Windows x64 SvnFlow command-line package."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
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
    if sys.platform != "win32":
        raise RuntimeError("The Windows executable must be built on a Windows runner.")
    release = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
    version, build = str(release["version"]), int(release["build"])
    work = ROOT / ".build" / "pyinstaller-windows"
    shutil.rmtree(work, ignore_errors=True)
    DIST.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "SvnFlow",
        "--distpath",
        str(work / "dist"),
        "--workpath",
        str(work / "work"),
        "--specpath",
        str(work / "spec"),
        "--paths",
        str(ROOT / "scripts"),
        "--add-data",
        f"{ROOT / 'release.json'};.",
    ]
    for module in ["lxml.etree", *RUNTIME_MODULES]:
        command += ["--hidden-import", module]
    command.append(str(ROOT / "packaging" / "windows_entry.py"))
    subprocess.run(command, cwd=ROOT, check=True)

    executable = work / "dist" / "SvnFlow.exe"
    subprocess.run([str(executable), "--version"], check=True)
    archive = DIST / f"SvnFlow-Windows-x64-{version}-{build}.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        output.write(executable, "SvnFlow.exe")
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

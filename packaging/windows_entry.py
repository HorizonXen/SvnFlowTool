#!/usr/bin/env python3
"""Windows command-line entry point for the packaged SvnFlow engine."""

from __future__ import annotations

import json
import pathlib
import runpy
import sys


COMMANDS = {
    "merge": "branch_sync",
    "progress": "sync_progress",
}


def resource_path(name: str) -> pathlib.Path:
    bundle = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).resolve().parents[1]))
    return bundle / name


def release_identity() -> tuple[str, int]:
    value = json.loads(resource_path("release.json").read_text(encoding="utf-8"))
    return str(value["version"]), int(value["build"])


def print_help() -> None:
    print(
        "SvnFlow for Windows\n\n"
        "Usage:\n"
        "  SvnFlow.exe --version\n"
        "  SvnFlow.exe merge <action> --folder <report-folder> [options]\n"
        "  SvnFlow.exe progress <arguments>\n\n"
        "The merge command uses the same guarded merge engine as the macOS app.\n"
        "Set SVNFLOW_CONFIG to a JSON configuration file, or place config.json in\n"
        "%APPDATA%\\SvnFlow. Subversion (svn.exe) must be available on PATH."
    )


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments in (["--version"], ["-V"]):
        version, build = release_identity()
        print(f"SvnFlow {version} ({build})")
        return 0
    if not arguments:
        print_help()
        if sys.platform == "win32" and sys.stdin.isatty():
            try:
                input("\nThis is the Windows command-line edition. Press Enter to close...")
            except (EOFError, KeyboardInterrupt):
                pass
        return 0
    if arguments[0] in {"-h", "--help"}:
        print_help()
        return 0
    module = COMMANDS.get(arguments[0])
    if module is None:
        print(f"Unknown command: {arguments[0]}", file=sys.stderr)
        print_help()
        return 2
    sys.argv = [f"{module}.py", *arguments[1:]]
    runpy.run_module(module, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

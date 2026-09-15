#!/usr/bin/env python3
"""Restricted Python launcher embedded in public macOS and Windows packages.

It is intentionally not a general Python interpreter. Only the two application
entry scripts can be executed, which keeps the packaged runtime's surface small.
"""

from __future__ import annotations

import pathlib
import runpy
import sys


ALLOWED = {"branch_sync.py", "sync_progress.py"}


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        print("SvnFlow embedded engine: missing entry script", file=sys.stderr)
        return 2
    script = pathlib.Path(arguments[0]).resolve()
    if script.name not in ALLOWED or not script.is_file():
        print("SvnFlow embedded engine: unsupported entry script", file=sys.stderr)
        return 2
    sys.path.insert(0, str(script.parent))
    sys.argv = [str(script), *arguments[1:]]
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

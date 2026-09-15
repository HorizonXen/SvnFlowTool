#!/usr/bin/env python3
"""Fail when files selected for Git contain local/private release material."""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
TEXT_LIMIT = 8 * 1024 * 1024
FORBIDDEN_PATH_PARTS = {
    ".build", ".impeccable", "archives", "dist", "reports", "vendor", "__pycache__"
}
RULES = {
    "absolute macOS user path": re.compile(rb"/Users/(?!Shared(?:/|\b))[^/\s\"']+"),
    "absolute Windows user path": re.compile(rb"[A-Za-z]:\\Users\\[^\\\s\"']+", re.I),
    "email address": re.compile(rb"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I),
    "known private author fixture": re.compile(rb"zipan[.]he", re.I),
    "Penpot private identifier": re.compile(rb"673184ea-f0b5-80a9-8008-[0-9a-f-]+", re.I),
    "embedded credential": re.compile(
        rb"(?i)(password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*[\"'][^\"']{4,}[\"']"
    ),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
EMAIL_ALLOWLIST = {
    b"security@example.com",
    b"user@example.com",
}


def git_files() -> list[pathlib.Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=False, capture_output=True
    )
    if result.returncode == 0 and result.stdout:
        return [ROOT / pathlib.Path(value.decode()) for value in result.stdout.split(b"\0") if value]
    return [
        path for path in ROOT.rglob("*")
        if path.is_file() and not (set(path.relative_to(ROOT).parts) & FORBIDDEN_PATH_PARTS)
    ]


def scan(path: pathlib.Path) -> list[str]:
    relative = path.relative_to(ROOT)
    if relative == pathlib.Path("scripts/check_public_tree.py"):
        return []
    if set(relative.parts) & FORBIDDEN_PATH_PARTS:
        return ["forbidden private/build directory"]
    try:
        data = path.read_bytes()
    except OSError as error:
        return [f"cannot read: {error}"]
    if len(data) > TEXT_LIMIT or b"\0" in data[:4096]:
        return []
    failures = []
    for label, pattern in RULES.items():
        matches = pattern.findall(data)
        if label == "email address":
            matches = [value for value in matches if value.lower() not in EMAIL_ALLOWLIST]
        if matches:
            failures.append(label)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    failures = [(path.relative_to(ROOT), scan(path)) for path in git_files()]
    failures = [(path, reasons) for path, reasons in failures if reasons]
    if failures:
        print("Public-tree safety check failed:", file=sys.stderr)
        for path, reasons in failures:
            print(f"- {path}: {', '.join(reasons)}", file=sys.stderr)
        return 1
    if not args.quiet:
        print("Public-tree safety check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
/usr/bin/python3 "$ROOT/packaging/trial_release.py" verify "$ROOT"
OUTPUT=${1:-${SVNFLOW_DELIVERY_DIR:-}}
if [ -z "$OUTPUT" ] && [ -f "$ROOT/.svnflow-delivery-path" ]; then
    IFS= read -r OUTPUT < "$ROOT/.svnflow-delivery-path"
fi
[ -n "$OUTPUT" ] || { printf '%s\n' "Usage: $0 OUTPUT_DIRECTORY" >&2; exit 2; }

case "$OUTPUT" in
    /|"$HOME")
        printf '%s\n' "Refusing broad delivery directory: $OUTPUT" >&2
        exit 2
        ;;
esac

VERSION=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$ROOT/release.json")
BUILD=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["build"])' "$ROOT/release.json")
MAC_ARCHIVE="$ROOT/dist/SvnFlow-macOS-arm64-$VERSION-$BUILD.zip"
[ -f "$MAC_ARCHIVE" ] || { printf '%s\n' "Missing macOS package: $MAC_ARCHIVE" >&2; exit 1; }
[ -f "$MAC_ARCHIVE.sha256" ] || { printf '%s\n' "Missing macOS checksum" >&2; exit 1; }

mkdir -p "$OUTPUT/packages"
cp "$ROOT/packaging/install-macos.sh" "$OUTPUT/install-macos.sh"
cp "$ROOT/packaging/install-windows.ps1" "$OUTPUT/install-windows.ps1"
cp "$ROOT/packaging/DELIVERY_README.md" "$OUTPUT/README.md"
cp "$ROOT/release.json" "$OUTPUT/release.json"
cp "$MAC_ARCHIVE" "$OUTPUT/packages/"
cp "$MAC_ARCHIVE.sha256" "$OUTPUT/packages/"
chmod +x "$OUTPUT/install-macos.sh"

WINDOWS_ARCHIVE="$ROOT/dist/SvnFlow-Windows-x64-$VERSION-$BUILD.zip"
WINDOWS_STATUS=pending
if [ -f "$WINDOWS_ARCHIVE" ] && [ -f "$WINDOWS_ARCHIVE.sha256" ]; then
    cp "$WINDOWS_ARCHIVE" "$OUTPUT/packages/"
    cp "$WINDOWS_ARCHIVE.sha256" "$OUTPUT/packages/"
    WINDOWS_STATUS=available
fi

/usr/bin/python3 - "$OUTPUT/manifest.json" "$VERSION" "$BUILD" "$WINDOWS_STATUS" <<'PY'
import json
import pathlib
import sys

path, version, build, windows = sys.argv[1:]
value = {
    "schema": 1,
    "version": version,
    "build": int(build),
    "artifacts": {
        "macos-arm64": {
            "status": "available",
            "file": f"packages/SvnFlow-macOS-arm64-{version}-{build}.zip",
            "installer": "install-macos.sh",
        },
        "windows-x64": {
            "status": windows,
            "file": f"packages/SvnFlow-Windows-x64-{version}-{build}.zip" if windows == "available" else None,
            "installer": "install-windows.ps1",
        },
    },
}
pathlib.Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

printf '%s\n' "Delivery assembled at $OUTPUT"

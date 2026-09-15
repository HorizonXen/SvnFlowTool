#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$ROOT/release.json")
BUILD=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["build"])' "$ROOT/release.json")
ARCHIVE="$ROOT/dist/SvnFlow-macOS-arm64-$VERSION-$BUILD.zip"

rm -f "$ROOT/.build/trial-approval.json"
zsh "$ROOT/scripts/build-app.sh"
ditto -c -k --sequesterRsrc --keepParent "$ROOT/dist/提交合并分支工具.app" "$ARCHIVE"
(
    cd "$ROOT/dist"
    shasum -a 256 "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256"
)
printf '%s\n' "Trial package built: $ARCHIVE"
printf '%s\n' "After human trial: packaging/approve-trial.sh"
printf '%s\n' "Then publish: packaging/publish-approved-release.sh"

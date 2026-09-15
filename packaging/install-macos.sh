#!/bin/sh
set -eu

APP_NAME="提交合并分支工具.app"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR="${SVNFLOW_INSTALL_DIR:-$HOME/Applications}"
PACKAGE_DIR="${SVNFLOW_PACKAGE_DIR:-$SCRIPT_DIR/packages}"

usage() {
    printf '%s\n' "Usage: $0 [--install-dir DIRECTORY] [--help]"
    printf '%s\n' "Default: $HOME/Applications (no administrator permission required)"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --install-dir)
            [ "$#" -ge 2 ] || { printf '%s\n' "--install-dir requires a directory" >&2; exit 2; }
            INSTALL_DIR=$2
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            printf '%s\n' "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

[ "$(uname -s)" = "Darwin" ] || { printf '%s\n' "This installer only supports macOS." >&2; exit 1; }
[ "$(uname -m)" = "arm64" ] || { printf '%s\n' "This release requires an Apple Silicon Mac." >&2; exit 1; }

VERSION=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$SCRIPT_DIR/release.json")
BUILD=$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["build"])' "$SCRIPT_DIR/release.json")
ARCHIVE="$PACKAGE_DIR/SvnFlow-macOS-arm64-$VERSION-$BUILD.zip"
CHECKSUM_FILE="$ARCHIVE.sha256"

[ -f "$ARCHIVE" ] || { printf '%s\n' "Missing release package: $ARCHIVE" >&2; exit 1; }
[ -f "$CHECKSUM_FILE" ] || { printf '%s\n' "Missing checksum: $CHECKSUM_FILE" >&2; exit 1; }

EXPECTED=$(awk 'NR == 1 {print $1}' "$CHECKSUM_FILE")
ACTUAL=$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')
[ "$EXPECTED" = "$ACTUAL" ] || { printf '%s\n' "Package checksum verification failed." >&2; exit 1; }

STAGING=$(mktemp -d "${TMPDIR:-/tmp}/svnflow-install.XXXXXX")
trap 'rm -rf "$STAGING"' EXIT HUP INT TERM
ditto -x -k "$ARCHIVE" "$STAGING"
SOURCE="$STAGING/$APP_NAME"
[ -d "$SOURCE" ] || { printf '%s\n' "The archive does not contain $APP_NAME." >&2; exit 1; }

PACKAGE_VERSION=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$SOURCE/Contents/Info.plist")
PACKAGE_BUILD=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$SOURCE/Contents/Info.plist")
[ "$PACKAGE_VERSION" = "$VERSION" ] && [ "$PACKAGE_BUILD" = "$BUILD" ] || {
    printf '%s\n' "Package version does not match release.json." >&2
    exit 1
}
codesign --verify --deep --strict "$SOURCE"

mkdir -p "$INSTALL_DIR"
DESTINATION="$INSTALL_DIR/$APP_NAME"
BACKUP="$INSTALL_DIR/.SvnFlow.previous.$$"
if [ -e "$DESTINATION" ]; then
    mv "$DESTINATION" "$BACKUP"
fi
if mv "$SOURCE" "$DESTINATION"; then
    rm -rf "$BACKUP"
else
    [ ! -e "$BACKUP" ] || mv "$BACKUP" "$DESTINATION"
    printf '%s\n' "Installation failed; the previous application was restored." >&2
    exit 1
fi

printf '%s\n' "Installed $APP_NAME $VERSION ($BUILD)"
printf '%s\n' "$DESTINATION"

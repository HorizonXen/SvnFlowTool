#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPOSITORY_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
RELEASE_FILE="$REPOSITORY_DIR/release.json"

fail() {
    printf '%s\n' "Public release check failed: $1" >&2
    exit 1
}

[ "$(uname -s)" = "Darwin" ] || fail "this check currently requires macOS"
[ -f "$RELEASE_FILE" ] || fail "release.json is missing"

VERSION=$(/usr/bin/plutil -extract version raw -o - "$RELEASE_FILE")
BUILD=$(/usr/bin/plutil -extract build raw -o - "$RELEASE_FILE")
ARCHIVE="$REPOSITORY_DIR/packages/SvnFlow-macOS-arm64-$VERSION-$BUILD.zip"
CHECKSUM_FILE="$ARCHIVE.sha256"

[ -f "$ARCHIVE" ] || fail "release archive is missing"
[ -f "$CHECKSUM_FILE" ] || fail "release checksum is missing"

EXPECTED=$(awk 'NR == 1 {print $1}' "$CHECKSUM_FILE")
ACTUAL=$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')
[ "$EXPECTED" = "$ACTUAL" ] || fail "release checksum does not match"

STAGING=$(mktemp -d "${TMPDIR:-/tmp}/svnflow-public-check.XXXXXX")
trap 'rm -rf "$STAGING"' EXIT HUP INT TERM
ditto -x -k "$ARCHIVE" "$STAGING"

APP="$STAGING/提交合并分支工具.app"
[ -d "$APP" ] || fail "archive does not contain the expected application"

PACKAGE_VERSION=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")
PACKAGE_BUILD=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP/Contents/Info.plist")
[ "$PACKAGE_VERSION" = "$VERSION" ] && [ "$PACKAGE_BUILD" = "$BUILD" ] || fail "package version does not match release.json"
codesign --verify --deep --strict "$APP" || fail "code-signature verification failed"

SCAN_TEXT="$STAGING/scan-text.txt"
find "$REPOSITORY_DIR" -type f \
    ! -path "$REPOSITORY_DIR/.git/*" \
    ! -path "$REPOSITORY_DIR/packages/*" \
    ! -path "$SCRIPT_DIR/check-public-release.sh" \
    -exec strings {} \; > "$SCAN_TEXT"
find "$APP" -type f -exec strings {} \; >> "$SCAN_TEXT"

if grep -E -i -q '(/Users/[^/[:space:]]+|/home/[^/[:space:]]+|[A-Z]:\\Users\\[^\\[:space:]]+)' "$SCAN_TEXT"; then
    fail "a developer or user home-directory path was found"
fi
if grep -E -i -q '(https?|svn|svn\+ssh)://(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)' "$SCAN_TEXT"; then
    fail "a private-network URL was found"
fi
if grep -E -i -q '(svn|svn\+ssh)://[^[:space:]"<>]+' "$SCAN_TEXT"; then
    fail "an SVN repository URL was found"
fi
if grep -E -i -q '[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}' "$SCAN_TEXT"; then
    fail "an email address was found"
fi
if grep -E -q '(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY)' "$SCAN_TEXT"; then
    fail "a credential-like value was found"
fi
if find "$STAGING" \( -name '.svn' -o -name '*.log' -o -name '*.sqlite' -o -name '*.db' -o -name '*.pem' -o -name '*.key' \) -print -quit | grep -q .; then
    fail "a report, database, credential, or working-copy metadata file was found"
fi

printf '%s\n' "Public release check passed for SvnFlow $VERSION ($BUILD)."

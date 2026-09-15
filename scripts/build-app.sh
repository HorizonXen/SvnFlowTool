#!/bin/zsh
set -euo pipefail
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--package-only" ) ]]; then
    echo "Usage: $0 [--package-only]" >&2
    exit 2
fi
ROOT="${0:A:h:h}"
cd "$ROOT"
if [[ -x "$ROOT/vendor/python/bin/python3.12" ]]; then
    BUILD_PYTHON="$ROOT/vendor/python/bin/python3.12"
else
    BUILD_PYTHON="${SVNFLOW_BUILD_PYTHON:-python3}"
fi
swift build -c release --product SvnFlow
ENGINE="$ROOT/.build/engine-dist/svnflow-python"
if [[ ! -x "$ENGINE" ]]; then
    "$BUILD_PYTHON" "$ROOT/scripts/build-merge-engine.py"
fi
zsh "$ROOT/scripts/build-icon.sh"
APP="$ROOT/.build/app-package/提交合并分支工具.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ROOT/.build/release/SvnFlow" "$APP/Contents/MacOS/SvnFlow"
cp "$ROOT/Resources/Brand/SvnFlow-v3.icns" "$APP/Contents/Resources/AppIcon-v3.icns"
cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>提交合并分支工具</string><key>CFBundleDisplayName</key><string>提交合并分支工具</string>
<key>CFBundleIdentifier</key><string>com.self.svnflow</string>
<key>CFBundleExecutable</key><string>SvnFlow</string>
<key>CFBundleDevelopmentRegion</key><string>zh-Hans</string>
<key>CFBundleLocalizations</key><array><string>zh-Hans</string><string>en</string></array>
<key>CFBundlePackageType</key><string>APPL</string><key>LSMinimumSystemVersion</key><string>14.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>CFBundleIconFile</key><string>AppIcon-v3</string>
</dict></plist>
EOF
"$BUILD_PYTHON" - "$ROOT/release.json" "$APP/Contents/Info.plist" <<'PYVERSION'
import json, plistlib, re, sys
from pathlib import Path
release = json.loads(Path(sys.argv[1]).read_text())
assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', release['version']), '版本号必须为 major.minor.patch'
assert type(release['build']) is int and 0 < release['build'] < 10000, '构建号必须为正整数且小于 10000'
assert release['name'] == '提交合并分支工具', '应用名称不一致'
path = Path(sys.argv[2])
info = plistlib.loads(path.read_bytes())
info.update(CFBundleName=release['name'], CFBundleDisplayName=release['name'],
            CFBundleShortVersionString=release['version'], CFBundleVersion=str(release['build']))
path.write_bytes(plistlib.dumps(info))
print(release['name'], 'v'+release['version'], 'build', release['build'])
PYVERSION
cp "$ROOT/release.json" "$APP/Contents/Resources/release.json"
cp "$ROOT/scripts/branch_sync.py" "$APP/Contents/Resources/branch_sync.py"
cp "$ROOT/scripts/platform_lock.py" "$APP/Contents/Resources/platform_lock.py"
cp "$ROOT/scripts/platform_settings.py" "$APP/Contents/Resources/platform_settings.py"
cp "$ROOT/scripts/xtools_export.py" "$APP/Contents/Resources/xtools_export.py"
if [[ -x "$ENGINE" ]]; then
    /usr/bin/python3 "$ROOT/scripts/bundle_xtools.py" "$APP/Contents/Resources" --optional
else
    "$ROOT/vendor/python/bin/python3.12" "$ROOT/scripts/bundle_xtools.py" "$APP/Contents/Resources"
fi
cp "$ROOT/scripts/sync_progress.py" "$APP/Contents/Resources/sync_progress.py"
cp "$ROOT/scripts/revision_cache.py" "$APP/Contents/Resources/revision_cache.py"
cp "$ROOT/scripts/file_sync.py" "$APP/Contents/Resources/file_sync.py"
cp "$ROOT/scripts/staged_sync.py" "$APP/Contents/Resources/staged_sync.py"
cp "$ROOT/scripts/workbook_sync.py" "$APP/Contents/Resources/workbook_sync.py"
cp "$ROOT/scripts/text_review.py" "$APP/Contents/Resources/text_review.py"
cp "$ROOT/scripts/lua_sync.py" "$APP/Contents/Resources/lua_sync.py"
cp "$ROOT/scripts/galaxy_sync.py" "$APP/Contents/Resources/galaxy_sync.py"
cp "$ROOT/scripts/deletion_guard.py" "$APP/Contents/Resources/deletion_guard.py"
cp "$ROOT/scripts/workbook_cells.py" "$APP/Contents/Resources/workbook_cells.py"
cp "$ROOT/scripts/workbook_history.py" "$APP/Contents/Resources/workbook_history.py"
cp "$ROOT/scripts/workbook_inspect.py" "$APP/Contents/Resources/workbook_inspect.py"
cp "$ROOT/scripts/workbook_dom.py" "$APP/Contents/Resources/workbook_dom.py"
cp "$ROOT/scripts/workbook_sparse.py" "$APP/Contents/Resources/workbook_sparse.py"
cp "$ROOT/scripts/workbook_native.py" "$APP/Contents/Resources/workbook_native.py"
cp "$ROOT/scripts/workbook_compact.py" "$APP/Contents/Resources/workbook_compact.py"
if [[ -x "$ENGINE" ]]; then
    cp "$ENGINE" "$APP/Contents/Resources/svnflow-python"
    chmod +x "$APP/Contents/Resources/svnflow-python"
else
    cp "$ROOT/.build/merge-engine/"*.cpython-312-darwin.so "$APP/Contents/Resources/"
    cp "$ROOT/.build/merge-engine/merge-engine.json" "$APP/Contents/Resources/merge-engine.json"
    cp -R "$ROOT/vendor/python" "$APP/Contents/Resources/python"
    "$APP/Contents/Resources/python/bin/python3.12" -I -B -c 'import lxml.etree, ssl, sqlite3; print("内置合并运行环境检查通过")'
    "$APP/Contents/Resources/python/bin/python3.12" -I -B - "$APP/Contents/Resources" <<'PYENGINE'
import pathlib,sys
sys.path.insert(0,sys.argv[1])
import workbook_cells,workbook_dom,workbook_history
assert all(pathlib.Path(module.__file__).suffix=='.so' for module in (workbook_cells,workbook_dom,workbook_history)), '编译合并核心未加载'
print('已加载 Cython 编译合并核心')
PYENGINE
fi
# Runtime reports are user data. Never copy a developer's local report into a
# distributable application; the app creates its own report directory on use.
mkdir -p "$APP/Contents/Resources/BranchSync"
codesign --force --deep --sign - "$APP"
if [[ "${1:-}" == "--package-only" ]]; then
    echo "$APP"
    exit 0
fi
mkdir -p "$ROOT/dist"
rm -rf "$ROOT/dist/提交合并分支工具.app"
mv "$APP" "$ROOT/dist/提交合并分支工具.app"
echo "$ROOT/dist/提交合并分支工具.app"

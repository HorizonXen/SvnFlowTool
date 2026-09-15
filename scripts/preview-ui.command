#!/bin/zsh
set -euo pipefail
PREVIEW_PROJECT_DIR="${0:A:h:h}"
cd "$PREVIEW_PROJECT_DIR"
python3 scripts/create-ui-preview.py
open -n "$PREVIEW_PROJECT_DIR/dist/提交合并分支工具.app" --args --ui-preview "$PREVIEW_PROJECT_DIR/.build/ui-preview"

#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
/usr/bin/python3 "$ROOT/packaging/trial_release.py" approve "$ROOT"

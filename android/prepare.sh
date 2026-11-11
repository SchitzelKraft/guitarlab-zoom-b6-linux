#!/usr/bin/env bash
# Generates the app assets and the test fixtures from B6 Lab and the local Zoom data.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python tools/android_prepare.py "$@"

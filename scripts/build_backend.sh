#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
mkdir -p "$DIST_DIR"

# Build a standalone Python zipapp (no external dependencies)
python3 -m zipapp "$ROOT_DIR/backend" \
  -m "app.main:run_server" \
  -o "$DIST_DIR/wm_backend.pyz" \
  -p "/usr/bin/env python3"

echo "Build success: $DIST_DIR/wm_backend.pyz"
echo "Run with: python3 $DIST_DIR/wm_backend.pyz"

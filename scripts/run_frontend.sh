#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

if command -v python >/dev/null 2>&1; then
	PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
	PYTHON_BIN="python3"
else
	echo "Error: python/python3 is not installed on PATH."
	exit 1
fi

echo "Serving frontend from $FRONTEND_DIR"
echo "Open http://localhost:5500"

cd "$FRONTEND_DIR"
exec "$PYTHON_BIN" -m http.server 5500 --bind 0.0.0.0

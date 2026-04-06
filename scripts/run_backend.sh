#!/usr/bin/env bash
set -e
BACKEND_DIR="$(dirname "$0")/../backend"
cd "$BACKEND_DIR"

if [ -x ".venv/bin/python" ]; then
	PYTHON_BIN=".venv/bin/python"
else
	PYTHON_BIN="python"
fi

"$PYTHON_BIN" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

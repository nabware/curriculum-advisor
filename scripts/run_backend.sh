#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
VENV_DIR="$BACKEND_DIR/.venv"
REQUIREMENTS_FILE="$BACKEND_DIR/requirements.txt"
STAMP_FILE="$VENV_DIR/.requirements.sha256"

NEW_VENV=0

if [ ! -x "$VENV_DIR/bin/python" ]; then
	if command -v python >/dev/null 2>&1; then
		HOST_PYTHON="python"
	elif command -v python3 >/dev/null 2>&1; then
		HOST_PYTHON="python3"
	else
		echo "Error: python/python3 is not installed on PATH."
		exit 1
	fi

	echo "Creating backend virtual environment at $VENV_DIR"
	"$HOST_PYTHON" -m venv "$VENV_DIR"
	NEW_VENV=1
fi

VENV_PYTHON="$VENV_DIR/bin/python"

CURRENT_HASH="$(sha256sum "$REQUIREMENTS_FILE" | awk '{print $1}')"
STAMP_HASH=""
if [ -f "$STAMP_FILE" ]; then
	STAMP_HASH="$(cat "$STAMP_FILE")"
fi

if [ "$NEW_VENV" -eq 1 ]; then
	echo "Bootstrapping pip in backend virtual environment"
	"$VENV_PYTHON" -m pip install --upgrade pip
fi

if [ "$NEW_VENV" -eq 1 ] || [ "$CURRENT_HASH" != "$STAMP_HASH" ]; then
	echo "Installing backend dependencies from $REQUIREMENTS_FILE"
	"$VENV_PYTHON" -m pip install -r "$REQUIREMENTS_FILE"
	echo "$CURRENT_HASH" > "$STAMP_FILE"
else
	echo "Backend dependencies are up to date"
fi

cd "$BACKEND_DIR"
exec "$VENV_PYTHON" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

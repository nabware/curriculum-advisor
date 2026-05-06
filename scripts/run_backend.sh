#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
VENV_DIR="$BACKEND_DIR/.venv"
REQUIREMENTS_FILE="$BACKEND_DIR/requirements.txt"
STAMP_FILE="$VENV_DIR/.requirements.sha256"

# Parse command line arguments
ENABLE_OLLAMA=0
for arg in "$@"; do
	case "$arg" in
		--with-ollama)
			ENABLE_OLLAMA=1
			;;
		--help|-h)
			echo "Usage: $0 [OPTIONS]"
			echo ""
			echo "Options:"
			echo "  --with-ollama    Start Ollama service (for professor sentiment scoring)"
			echo "  --help, -h       Show this help message"
			exit 0
			;;
		*)
			echo "Unknown option: $arg"
			echo "Use --help for usage information"
			exit 1
			;;
	esac
done

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

# Handle Ollama service if requested
if [ "$ENABLE_OLLAMA" -eq 1 ]; then
	echo "Starting Ollama service..."
	if ! systemctl is-active --quiet ollama; then
		echo "Ollama service is not running. Attempting to start it..."
		if sudo systemctl start ollama 2>/dev/null; then
			echo "Ollama service started successfully."
		else
			echo "WARNING: Could not start Ollama service. Please ensure it's running:"
			echo "  systemctl status ollama"
			echo "  sudo systemctl start ollama  # if not running"
		fi
	else
		echo "Ollama service is already running."
	fi
	# Wait a moment for Ollama to be ready
	sleep 2
else
	echo "Ollama service disabled. Use --with-ollama to enable sentiment scoring features."
fi

echo "Backend dependencies ready. Starting FastAPI server on port 8000..."
cd "$BACKEND_DIR"
exec "$VENV_PYTHON" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

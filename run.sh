#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python3"

if [ ! -f "$PYTHON" ]; then
  echo "Error: .venv not found. Run ./install.sh first."
  exit 1
fi

echo "Starting LeRobot UI at http://localhost:8000"
cd "$SCRIPT_DIR"
exec "$PYTHON" -m backend.main

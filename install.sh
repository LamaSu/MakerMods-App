#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_DIR="$SCRIPT_DIR/python"
PYTHON_VERSION="3.10.20"
BUILD_TAG="20260310"

# Detect OS and architecture
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Darwin)
    case "$ARCH" in
      arm64)  TRIPLE="aarch64-apple-darwin" ;;
      x86_64) TRIPLE="x86_64-apple-darwin" ;;
      *) echo "Unsupported macOS architecture: $ARCH"; exit 1 ;;
    esac
    ;;
  Linux)
    case "$ARCH" in
      x86_64)  TRIPLE="x86_64-unknown-linux-gnu" ;;
      aarch64) TRIPLE="aarch64-unknown-linux-gnu" ;;
      *) echo "Unsupported Linux architecture: $ARCH"; exit 1 ;;
    esac
    ;;
  *)
    echo "Unsupported OS: $OS"
    exit 1
    ;;
esac

FILENAME="cpython-${PYTHON_VERSION}+${BUILD_TAG}-${TRIPLE}-install_only.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${BUILD_TAG}/${FILENAME}"

echo "=== LeRobot UI — Standalone Installer ==="
echo ""

# Download and extract standalone Python
if [ -d "$PYTHON_DIR" ]; then
  echo "Python already installed at $PYTHON_DIR, skipping download."
else
  echo "Downloading Python ${PYTHON_VERSION} for ${TRIPLE}..."
  curl -L --fail --progress-bar -o "/tmp/${FILENAME}" "$URL"
  echo "Extracting..."
  tar -xzf "/tmp/${FILENAME}" -C "$SCRIPT_DIR"
  rm "/tmp/${FILENAME}"
  echo "Python installed at $PYTHON_DIR"
fi

# Create venv using the standalone Python (isolates packages from system)
if [ -d "$SCRIPT_DIR/.venv" ]; then
  echo "Virtual environment already exists at .venv, skipping creation."
else
  echo "Creating virtual environment..."
  "$PYTHON_DIR/bin/python3" -m venv "$SCRIPT_DIR/.venv"
  echo "Virtual environment created at .venv"
fi

# Install dependencies into the venv
# WARNING: Large install (~2-4GB with PyTorch). First run takes time.
echo ""
echo "Installing dependencies (this may take 5-15 minutes, ~2-4GB download)..."
"$SCRIPT_DIR/.venv/bin/pip" install --upgrade pip
"$SCRIPT_DIR/.venv/bin/pip" install -r "$SCRIPT_DIR/requirements-standalone.txt"

chmod +x "$SCRIPT_DIR/run.sh"

echo ""
echo "=========================================="
echo "Installation complete!"
echo ""
echo "Run the app:  ./run.sh"
echo "Dev/inspect:  source .venv/bin/activate"
echo "=========================================="

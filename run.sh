#!/usr/bin/env bash
# Hand Mouse launcher: sets up a private Python environment on first run, then starts the app.
# Usage: ./run.sh [options]     (./run.sh --help for all options)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  PY=""
  # 3.12 / 3.11 first: Intel Macs only get mediapipe wheels for Python <= 3.12
  for c in python3.12 python3.11 python3.13 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
  if [ -z "$PY" ]; then
    echo "Python 3 not found. Install it with:  brew install python   (or from python.org)"; exit 1
  fi
  echo "Setting up (one time) with $($PY --version)..."
  "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip -q
fi

if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  if ! .venv/bin/pip install -r requirements.txt -q; then
    echo
    echo "Install failed. On an Intel Mac, mediapipe needs Python 3.12 or older:"
    echo "  brew install python@3.12 && rm -rf .venv && ./run.sh"
    exit 1
  fi
  touch .venv/.installed
fi

if [ ! -f models/hand_landmarker.task ]; then
  mkdir -p models
  echo "Downloading hand tracking model (~8 MB)..."
  curl -fsSL -o models/hand_landmarker.task.part \
    https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
  mv models/hand_landmarker.task.part models/hand_landmarker.task
fi

exec .venv/bin/python hand_mouse.py "$@"

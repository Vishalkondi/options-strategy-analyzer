#!/usr/bin/env bash
# Options Strategy Analyzer - dev startup (macOS / Linux / WSL).
# Windows users: keep using start-dev.bat.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
if [ -x ".venv/bin/python" ]; then PYTHON=".venv/bin/python"
elif [ -x "venv/bin/python" ]; then PYTHON="venv/bin/python"
fi

echo "[1/4] Installing Python dependencies..."
"$PYTHON" -m pip install -q -r requirements.txt

echo "[2/4] Verifying the backend..."
"$PYTHON" check_backend.py || echo "  (continuing anyway - see the failures above)"

echo "[3/4] Starting backend on http://127.0.0.1:8000 ..."
"$PYTHON" -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT

echo "[4/4] Starting frontend on http://localhost:5173 ..."
cd frontend
[ -d node_modules ] || npm install
npm run dev

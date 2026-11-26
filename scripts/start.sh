#!/usr/bin/env bash
# Start StutterCut on macOS / Linux with one command: ./scripts/start.sh
# Builds the UI when its sources changed, starts the API (which starts the worker process and
# serves the UI) on http://127.0.0.1:${STUTTERCUT_PORT:-8000}, and opens the browser.
# Ctrl+C stops everything. STUTTERCUT_NO_BROWSER=1 skips the browser. Setup: docs/guides/setup-mac.md
set -euo pipefail

cd "$(dirname "$0")/.."
PORT="${STUTTERCUT_PORT:-8000}"
URL="http://127.0.0.1:$PORT"

PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python.exe # Git Bash on Windows
if [ ! -x "$PY" ]; then
  echo "No .venv found. Set up first: docs/guides/setup-mac.md (python3.11 -m venv .venv ...)" >&2
  exit 1
fi
export PYTHONPATH="$PWD/backend${PYTHONPATH:+:$PYTHONPATH}" # same import path as the .venv install
for tool in ffmpeg ffprobe node npm; do
  command -v "$tool" >/dev/null || { echo "$tool is not installed (see the setup guide)." >&2; exit 1; }
done

if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm ci)
fi
if [ ! -f frontend/dist/index.html ] ||
  [ -n "$(find frontend/src frontend/index.html -newer frontend/dist/index.html -print -quit)" ]; then
  echo "Building the UI..."
  (cd frontend && npm run build)
fi

# Open the browser once the API answers (in the background, so Ctrl+C reaches uvicorn).
[ -n "${STUTTERCUT_NO_BROWSER:-}" ] || (
  for _ in $(seq 1 120); do
    if curl -fs "$URL/api/health" >/dev/null 2>&1; then
      case "$(uname -s)" in
        Darwin) open "$URL" ;;
        Linux) command -v xdg-open >/dev/null && xdg-open "$URL" >/dev/null 2>&1 ;;
        *) cmd.exe /c start "" "$URL" >/dev/null 2>&1 || true ;;
      esac
      exit 0
    fi
    sleep 0.5
  done
) &

echo "StutterCut on $URL (Ctrl+C to stop)"
exec "$PY" -m uvicorn stuttercut.api.main:app --host 127.0.0.1 --port "$PORT"

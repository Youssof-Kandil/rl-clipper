#!/usr/bin/env bash
# Start RL Clipper on macOS / Linux: installs deps on first run, builds the UI, opens the browser.
#   ./run.sh            normal start (http://127.0.0.1:8765)
#   ./run.sh --dev      backend with reload + Vite dev server on :5173
#   PORT=9000 ./run.sh  another port
set -euo pipefail

root="$(cd "$(dirname "$0")" && pwd)"
port="${PORT:-8765}"
dev=0
[[ "${1:-}" == "--dev" ]] && dev=1

need() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "$1 not found. $2" >&2
        exit 1
    fi
}
if [[ "$(uname)" == "Darwin" ]]; then
    need ffmpeg "Install it with: brew install ffmpeg"
else
    need ffmpeg "Install it with: sudo apt install ffmpeg (or your distro's package)"
fi
need uv "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
need npm "Install Node.js 20+ (https://nodejs.org)"

# NVIDIA card: also install cuBLAS/cuDNN (~1 GB) so captions transcribe on the GPU.
groups=()
command -v nvidia-smi >/dev/null 2>&1 && groups=(--group gpu)

(cd "$root/backend" && uv sync --quiet ${groups[@]+"${groups[@]}"})

cd "$root/frontend"
[[ -d node_modules ]] || npm install --silent
if [[ $dev == 1 ]]; then
    npm run dev &
    url="http://localhost:5173"
else
    npm run build --silent
    url="http://127.0.0.1:$port"
fi

echo "RL Clipper running at $url"
( sleep 2; (command -v xdg-open >/dev/null && xdg-open "$url") || (command -v open >/dev/null && open "$url") || true ) >/dev/null 2>&1 &

cd "$root/backend"
reload=()
[[ $dev == 1 ]] && reload=(--reload)
exec uv run ${groups[@]+"${groups[@]}"} uvicorn app.main:app --host 127.0.0.1 --port "$port" ${reload[@]+"${reload[@]}"}

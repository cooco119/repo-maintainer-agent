#!/usr/bin/env bash
# Repo Maintainer Agent — local runner
#   ./run.sh            run with Docker Compose (recommended)
#   ./run.sh local      run with local Python (needs 3.11+)
#   ./run.sh tunnel     expose the dashboard via a free Cloudflare quick tunnel
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "No .env found — copying .env.example. Fill in your tokens, then re-run."
  cp .env.example .env
  exit 1
fi

case "${1:-docker}" in
  docker)
    docker compose up --build
    ;;
  local)
    python -m venv .venv 2>/dev/null || true
    . .venv/bin/activate
    pip install -q -e .
    set -a; . ./.env; set +a
    exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  tunnel)
    command -v cloudflared >/dev/null || {
      echo "Installing cloudflared..."
      curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
        -o /usr/local/bin/cloudflared 2>/dev/null || {
          curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o ./cloudflared
          chmod +x ./cloudflared; PATH="$PWD:$PATH"
        }
      chmod +x /usr/local/bin/cloudflared 2>/dev/null || true
    }
    echo "Tunnel starting — copy the printed https://*.trycloudflare.com URL into DASHBOARD_URL in .env and restart the server."
    exec cloudflared tunnel --url http://localhost:8000
    ;;
  *)
    echo "Usage: ./run.sh [docker|local|tunnel]"; exit 1
    ;;
esac

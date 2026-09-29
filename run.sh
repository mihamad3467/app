#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example to .env and fill in BOT_TOKEN and ADMIN_ID."
  exit 1
fi

set -a
source .env
set +a

exec python3 main.py
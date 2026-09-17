#!/usr/bin/env bash
# Start the Web UI on this machine only; no API key is needed for this workflow.
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_dir"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker Desktop, then run this script again." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker Desktop, then run this script again." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required (the 'docker compose' command)." >&2
  exit 1
fi

if [[ ! -f config.toml ]]; then
  cp config.example.toml config.toml
  echo "Created config.toml from config.example.toml."
fi

chmod 600 config.toml
echo "Starting the local Web UI at http://127.0.0.1:8501"
exec docker compose up --build webui

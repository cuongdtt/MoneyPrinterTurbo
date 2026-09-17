#!/usr/bin/env sh

# Serve the documentation root without installing project dependencies. This
# keeps links from features/index.html to sibling docs pages working.
port="${1:-8080}"
docs_dir="$(dirname "$0")/.."

exec python3 -m http.server "$port" --directory "$docs_dir"

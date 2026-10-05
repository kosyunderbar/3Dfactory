#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
local_node="$project_root/.build-cache/tools/node/node-v24.21.0-darwin-arm64/bin"
if [ -x "$local_node/node" ]; then
  PATH="$local_node:$PATH"
  export PATH
fi
NPM_CONFIG_CACHE="$project_root/.build-cache/npm"
export NPM_CONFIG_CACHE
cd "$project_root/services/factory-console"
case "${1:-}" in
  install) exec npm ci ;;
  dev|build|preview|test) command=$1; shift; exec npm run "$command" -- "$@" ;;
  *) printf '%s\n' 'Usage: scripts/console.sh install|dev|build|preview|test' >&2; exit 2 ;;
esac

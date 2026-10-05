#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"
. "$project_root/scripts/docker-env.sh"
if [ "${1:-}" = env ]; then
  exec python3 scripts/create-dev-env.py
fi
if command -v docker >/dev/null 2>&1; then
  compose_mode=docker
elif [ -x "$project_root/.build-cache/tools/docker-compose" ]; then
  compose_mode=standalone
else
  printf '%s\n' 'Docker Engine and Compose are required; see infrastructure/README.md.' >&2
  exit 2
fi
compose() {
  if [ "$compose_mode" = docker ]; then
    docker compose --project-name "${FACTORY_COMPOSE_PROJECT:-factory-dev}" --env-file "$project_root/.env" -f "$project_root/compose.yaml" "$@"
  else
    "$project_root/.build-cache/tools/docker-compose" --project-name "${FACTORY_COMPOSE_PROJECT:-factory-dev}" --env-file "$project_root/.env" -f "$project_root/compose.yaml" "$@"
  fi
}
case "${1:-}" in
  up) compose up --build --wait --wait-timeout 180 ;;
  down) compose down --timeout 10 ;;
  status) compose ps --all ;;
  logs) shift; compose logs --tail 100 "$@" ;;
  check) compose config --quiet ;;
  compose) shift; compose "$@" ;;
  *) printf '%s\n' 'Usage: scripts/dev-stack.sh env|up|down|status|logs [service]|check|compose <args>' >&2; exit 2 ;;
esac

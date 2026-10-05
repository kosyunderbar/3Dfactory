#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
venv="$project_root/.build-cache/simulator-venv"
if [ "${1:-}" = setup ]; then
  python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 required"'
  python3 -m venv --without-pip "$venv"
  printf '%s\n' 'Python 3.12 environment prepared; no third-party dependencies.'
  exit 0
fi
if [ ! -x "$venv/bin/python" ]; then
  printf '%s\n' 'Run scripts/simulator.sh setup first.' >&2
  exit 2
fi
cd "$project_root/services/factory-simulator"
case "${1:-}" in
  test) exec "$venv/bin/python" -m unittest discover -s tests -v ;;
  run) shift; exec "$venv/bin/python" -m factory_simulator "$@" ;;
  *) printf '%s\n' 'Usage: scripts/simulator.sh setup|test|run [--check-config]' >&2; exit 2 ;;
esac

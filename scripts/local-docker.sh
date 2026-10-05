#!/bin/sh
# Optional local verification Engine for this macOS arm64 workspace.
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
limactl="$project_root/.build-cache/tools/lima-2.2.1/bin/limactl"
LIMA_HOME=/tmp/factory-lima-s01
export LIMA_HOME
if [ ! -x "$limactl" ]; then
  printf '%s\n' 'Run python3 scripts/prepare-dev-tools.py docker first.' >&2
  exit 2
fi
case "${1:-}" in
  start)
    if [ -f "$LIMA_HOME/factory/lima.yaml" ]; then
      exec "$limactl" start --yes --timeout=12m factory
    fi
    exec "$limactl" start --yes --name=factory --vm-type=vz --cpus=2 --memory=4 --disk=20 --mount-only="$project_root" --timeout=12m template:docker
    ;;
  stop) exec "$limactl" stop factory ;;
  status) exec "$limactl" list factory ;;
  *) printf '%s\n' 'Usage: scripts/local-docker.sh start|stop|status' >&2; exit 2 ;;
esac

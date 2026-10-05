# Source after defining project_root. Uses only repository-local CLI configuration.
if ! command -v docker >/dev/null 2>&1 && [ -x "$project_root/.build-cache/tools/docker/docker" ]; then
  PATH="$project_root/.build-cache/tools/docker:$PATH"
  DOCKER_CONFIG="$project_root/.build-cache/docker-config"
  export PATH DOCKER_CONFIG
  if [ -z "${DOCKER_HOST:-}" ] && [ -S /private/tmp/factory-lima-s01/factory/sock/docker.sock ]; then
    DOCKER_HOST=unix:///private/tmp/factory-lima-s01/factory/sock/docker.sock
    export DOCKER_HOST
  fi
fi

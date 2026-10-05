#!/bin/sh
# Run one service with the pinned Wrapper and a repository inside this workspace.
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$#" -lt 2 ]; then
  printf '%s\n' 'Usage: scripts/service-maven.sh ingestion-service|operations-service <Maven goals/options>' >&2
  exit 2
fi
service_name=$1
shift
case "$service_name" in
  ingestion-service|operations-service) ;;
  *) printf '%s\n' 'Unknown service. Use ingestion-service or operations-service.' >&2; exit 2 ;;
esac
if [ -z "${JAVA_HOME:-}" ] && [ -x /usr/libexec/java_home ]; then
  JAVA_HOME=$(/usr/libexec/java_home -v 21)
  export JAVA_HOME
fi
MAVEN_USER_HOME="${FACTORY_MAVEN_CACHE:-$project_root/.build-cache/maven}"
export MAVEN_USER_HOME
cd "$project_root/services/$service_name"
exec ./mvnw "-Dmaven.repo.local=$MAVEN_USER_HOME/repository" "$@"

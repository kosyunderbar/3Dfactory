#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
: "${INGESTION_DB_PASSWORD:?Set INGESTION_DB_PASSWORD}"
: "${INGESTION_MIGRATION_PASSWORD:?Set INGESTION_MIGRATION_PASSWORD}"
: "${OPERATIONS_DB_PASSWORD:?Set OPERATIONS_DB_PASSWORD}"
: "${OPERATIONS_MIGRATION_PASSWORD:?Set OPERATIONS_MIGRATION_PASSWORD}"
exec "${FACTORY_PSQL:-psql}" --no-psqlrc --dbname=postgres --set=ON_ERROR_STOP=1 --file="$project_root/infrastructure/postgresql/init-databases.psql"

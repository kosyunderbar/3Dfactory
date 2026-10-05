#!/bin/sh
# Optional local verification tool, not a production/Compose installation.
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
pg_build_root=$(mktemp -d /tmp/factory-postgresql-build.XXXXXX)
pg_source_url=https://ftp.postgresql.org/pub/source/v17.11/postgresql-17.11.tar.gz
curl --fail --silent --show-error --location --connect-timeout 10 --max-time 120 "$pg_source_url" -o "$pg_build_root/source.tar.gz"
python3 - "$pg_build_root/source.tar.gz" <<'PY'
import hashlib,sys
from pathlib import Path
expected='5367f6fb2ec97efe1eb2e0c7926bb33438e51b0bd3a9733b88498056a7dc9a7e'
if hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest()!=expected:
    raise SystemExit('PostgreSQL 17.11 source SHA-256 mismatch')
PY
tar -xzf "$pg_build_root/source.tar.gz" -C "$pg_build_root"
cd "$pg_build_root/postgresql-17.11"
./configure --prefix="$pg_build_root/install" --without-icu --without-readline > "$pg_build_root/configure.log" 2>&1
make -j4 > "$pg_build_root/build.log" 2>&1
make install > "$pg_build_root/install.log" 2>&1
python3 - "$project_root" "$pg_build_root/install/bin" <<'PY'
from pathlib import Path
import json,sys
p=Path(sys.argv[1])/'.build-cache/postgresql-toolchain.json'
p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(json.dumps({'version':'17.11','bin':sys.argv[2]},indent=2)+'\n')
PY
printf 'PostgreSQL verification tools ready: %s\n' "$pg_build_root/install/bin"

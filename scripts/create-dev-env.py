#!/usr/bin/env python3
"""Generate local credentials once; never replace existing configuration."""
from pathlib import Path
import os
import secrets

root = Path(__file__).resolve().parents[1]
path = root / ".env"
keys = ("POSTGRES_PASSWORD", "INGESTION_APP_PASSWORD", "INGESTION_MIGRATOR_PASSWORD",
        "OPERATIONS_APP_PASSWORD", "OPERATIONS_MIGRATOR_PASSWORD")
try:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(".env already exists; kept unchanged. Edit it manually if needed.")
with os.fdopen(descriptor, "w") as output:
    output.write("# Local development credentials; keep this file private.\n")
    for key in keys:
        output.write(f"{key}={secrets.token_hex(24)}\n")
    output.write("INGESTION_HTTP_PORT=8081\nOPERATIONS_HTTP_PORT=8082\nCONSOLE_HTTP_PORT=5173\n")
print("Created .env (permissions 0600). Passwords are not printed.")

#!/usr/bin/env bash
# Sets the api_app role's password from APP_DB_PASSWORD, so no password lives in committed SQL.
# The postgres image runs it on first start, after init.sql. docs/deploy.md covers production.
set -euo pipefail

: "${APP_DB_PASSWORD:?Set APP_DB_PASSWORD to the password for the api_app role}"
psql -v ON_ERROR_STOP=1 -v app_password="$APP_DB_PASSWORD" \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
ALTER ROLE api_app PASSWORD :'app_password';
SQL

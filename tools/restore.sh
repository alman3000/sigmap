#!/usr/bin/env bash
# Restore a pg_dump backup into the running db container.
# Usage: ./restore.sh <backup.sql.gz>
#
# The app container is stopped before restore and restarted after,
# so no writes happen during the import.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE="$PROJECT_DIR/docker-compose.yml"

# ── argument ──────────────────────────────────────────────────────────────────

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <backup.sql.gz>" >&2
  echo "Available backups:" >&2
  ls -1t "$PROJECT_DIR/backups/"*.sql.gz 2>/dev/null | head -10 >&2 || echo "  (none)" >&2
  exit 1
fi

INFILE="$1"

# Allow bare filename — look in backups/ if the file isn't found as-is
if [[ ! -f "$INFILE" ]]; then
  CANDIDATE="$PROJECT_DIR/backups/$INFILE"
  if [[ -f "$CANDIDATE" ]]; then
    INFILE="$CANDIDATE"
  else
    echo "Error: file not found: $1" >&2
    exit 1
  fi
fi

# ── credentials from .env ────────────────────────────────────────────────────

if [[ -f "$PROJECT_DIR/.env" ]]; then
  _val() { grep -E "^$1=" "$PROJECT_DIR/.env" | tail -1 | cut -d= -f2-; }
  POSTGRES_DB="${POSTGRES_DB:-$(_val POSTGRES_DB)}"
  POSTGRES_USER="${POSTGRES_USER:-$(_val POSTGRES_USER)}"
fi

PGDB="${POSTGRES_DB:-graffmap}"
PGUSER="${POSTGRES_USER:-graffmap}"

# ── confirm ───────────────────────────────────────────────────────────────────

echo "┌─────────────────────────────────────────────────────┐"
echo "│  RESTORE — this will REPLACE all data in '$PGDB'  │"
echo "└─────────────────────────────────────────────────────┘"
echo "  File   : $INFILE ($(du -sh "$INFILE" | cut -f1))"
echo "  DB     : $PGDB @ container db"
echo ""
read -r -p "Continue? [y/N] " CONFIRM
if [[ "${CONFIRM,,}" != "y" ]]; then
  echo "Aborted."
  exit 0
fi

# ── stop app, restore, restart ────────────────────────────────────────────────

echo "Stopping app container…"
docker compose -f "$COMPOSE" stop app

echo "Dropping and recreating database…"
docker compose -f "$COMPOSE" exec -T db \
  psql -U "$PGUSER" -d postgres \
  -c "DROP DATABASE IF EXISTS \"$PGDB\";" \
  -c "CREATE DATABASE \"$PGDB\" OWNER \"$PGUSER\";"

echo "Importing $INFILE…"
gunzip -c "$INFILE" | \
  docker compose -f "$COMPOSE" exec -T db \
  psql -U "$PGUSER" -d "$PGDB" -q

echo "Restarting app container…"
docker compose -f "$COMPOSE" start app

echo "Restore complete."

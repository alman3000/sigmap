#!/usr/bin/env bash
# Dump the PostgreSQL database to backups/<timestamp>.sql.gz
# Usage: ./backup.sh [--keep N]   (default: keep last 14 dumps)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_DIR/backups"
KEEP=14

while [[ $# -gt 0 ]]; do
  case $1 in
    --keep) KEEP="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
OUTFILE="$BACKUP_DIR/${TIMESTAMP}.sql.gz"

# Read only the two Postgres vars from .env (avoids sourcing arbitrary shell values)
if [[ -f "$PROJECT_DIR/.env" ]]; then
  _val() { grep -E "^$1=" "$PROJECT_DIR/.env" | tail -1 | cut -d= -f2-; }
  POSTGRES_DB="${POSTGRES_DB:-$(_val POSTGRES_DB)}"
  POSTGRES_USER="${POSTGRES_USER:-$(_val POSTGRES_USER)}"
fi

PGDB="${POSTGRES_DB:-graffmap}"
PGUSER="${POSTGRES_USER:-graffmap}"

echo "Backing up database '$PGDB' → $OUTFILE"

docker compose -f "$PROJECT_DIR/docker-compose.yml" exec -T db \
  pg_dump -U "$PGUSER" "$PGDB" | gzip > "$OUTFILE"

echo "Backup complete: $(du -sh "$OUTFILE" | cut -f1)"

# Rotate: remove oldest dumps beyond KEEP
mapfile -t OLD < <(ls -1t "$BACKUP_DIR"/*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)))
if [[ ${#OLD[@]} -gt 0 ]]; then
  echo "Removing ${#OLD[@]} old backup(s):"
  printf '  %s\n' "${OLD[@]}"
  rm -f "${OLD[@]}"
fi

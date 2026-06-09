#!/usr/bin/env bash
# Dump the PostgreSQL database to backups/<timestamp>.sql.gz
# Usage: ./backup.sh [--keep N]   (default: keep last 14 dumps)

set -euo pipefail

BACKUP_DIR="$(cd "$(dirname "$0")" && pwd)/backups"
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

# Load .env so we can read POSTGRES_* without requiring them to be exported
if [[ -f "$(dirname "$0")/.env" ]]; then
  set -o allexport
  # shellcheck disable=SC1091
  source "$(dirname "$0")/.env"
  set +o allexport
fi

PGDB="${POSTGRES_DB:-graffmap}"
PGUSER="${POSTGRES_USER:-graffmap}"

echo "Backing up database '$PGDB' → $OUTFILE"

docker compose -f "$(dirname "$0")/docker-compose.yml" exec -T db \
  pg_dump -U "$PGUSER" "$PGDB" | gzip > "$OUTFILE"

echo "Backup complete: $(du -sh "$OUTFILE" | cut -f1)"

# Rotate: remove oldest dumps beyond KEEP
mapfile -t OLD < <(ls -1t "$BACKUP_DIR"/*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)))
if [[ ${#OLD[@]} -gt 0 ]]; then
  echo "Removing ${#OLD[@]} old backup(s):"
  printf '  %s\n' "${OLD[@]}"
  rm -f "${OLD[@]}"
fi

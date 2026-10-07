#!/bin/bash
# Scénario Playwright du Daily log v9 (lot 10), sur une base jetable.
# Prérequis : PostgreSQL 16 (PGHOST/PGUSER/PGPASSWORD), Node + Playwright
# (PLAYWRIGHT_MODULE = chemin du module si non installé localement,
# PLAYWRIGHT_BROWSERS_PATH pour Chromium), psycopg2 (ou un équivalent sur
# PYTHONPATH). Usage : bash tests_e2e/lancer.sh [dossier_captures]
set -euo pipefail
racine=$(cd "$(dirname "$0")/.." && pwd)
export PGHOST=${PGHOST:-127.0.0.1} PGUSER=${PGUSER:-kairos} PGPASSWORD=${PGPASSWORD:-kairos}
base=${KAIROS_E2E_BASE_PG:-kairos_e2e_dailylog}
port=${KAIROS_E2E_PORT:-8798}
psql -X -q -d postgres -c "DROP DATABASE IF EXISTS $base" -c "CREATE DATABASE $base"
psql -X -q -v ON_ERROR_STOP=1 -d "$base" -f "$racine/schema.sql" >/dev/null 2>&1
python3 "$racine/tests_e2e/seed_dailylog.py" "$base"
export DATABASE_URL="postgresql://$PGUSER:$PGPASSWORD@$PGHOST:5432/$base"
export SECRET_KEY=${SECRET_KEY:-e2e-0123456789abcdef0123456789abcdef0123456789}
export UPLOAD_DIR=$(mktemp -d) APP_BASE_URL="http://127.0.0.1:$port"
(cd "$racine" && exec python3 -m flask --app wsgi run -p "$port" --no-reload > /tmp/kairos-e2e-serveur.log 2>&1) &
serveur=$!
trap 'kill $serveur 2>/dev/null || true' EXIT
for _ in $(seq 40); do curl -fs -o /dev/null "http://127.0.0.1:$port/connexion" && break; sleep 0.25; done
KAIROS_E2E_URL="http://127.0.0.1:$port" KAIROS_E2E_DB="$base" KAIROS_E2E_CAPTURES="${1:-}" \
  node "$racine/tests_e2e/dailylog.e2e.js"

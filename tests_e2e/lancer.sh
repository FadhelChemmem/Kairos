#!/bin/bash
# Scénarios Playwright sur une base jetable : Daily log v9 (lot 10, par
# défaut), fiche projet (lot 11 : KAIROS_E2E_SCENARIO=projet), modes de
# l'Admin (lot 12 : KAIROS_E2E_SCENARIO=modes, serveur lancé avec
# KAIROS_MODE_TEST=true sauf valeur déjà posée) ou socle des mises à jour
# partielles (lot 13 : KAIROS_E2E_SCENARIO=partiel, même mode test) ou pages
# converties en phase 2 (KAIROS_E2E_SCENARIO=pages, même mode test) ou
# stabilité de la mise en page (KAIROS_E2E_SCENARIO=stabilite, même mode test)
# ou tâche bloquée avec raison et message de clôture (lot 14 :
# KAIROS_E2E_SCENARIO=blocage, même mode test), ou tableaux de bord de
# l'accueil (lot 14 : KAIROS_E2E_SCENARIO=tableaux, même mode test), ou Daily log de l'équipe (lot 14 :
# KAIROS_E2E_SCENARIO=dailylog_equipe, même mode test), ou fil filtrable (lot 14 :
# KAIROS_E2E_SCENARIO=fil, même mode test), ou accueil sobre, Daily log, posts
# modifiables et page d'une personne (lot 15 : KAIROS_E2E_SCENARIO=lot15).
# Prérequis : PostgreSQL 16 (PGHOST/PGUSER/PGPASSWORD), Node + Playwright
# (PLAYWRIGHT_MODULE = chemin du module si non installé localement,
# PLAYWRIGHT_BROWSERS_PATH pour Chromium), psycopg2 (ou un équivalent sur
# PYTHONPATH). Usage : [KAIROS_E2E_SCENARIO=dailylog|projet|modes|partiel|pages|stabilite|blocage|tableaux|dailylog_equipe|fil|lot15] bash tests_e2e/lancer.sh [dossier_captures]
set -euo pipefail
racine=$(cd "$(dirname "$0")/.." && pwd)
export PGHOST=${PGHOST:-127.0.0.1} PGUSER=${PGUSER:-kairos} PGPASSWORD=${PGPASSWORD:-kairos}
scenario=${KAIROS_E2E_SCENARIO:-dailylog}
case "$scenario" in dailylog|projet|modes|partiel|pages|stabilite|blocage|tableaux|dailylog_equipe|fil|lot15) ;; *) echo "Scénario inconnu : $scenario (dailylog, projet, modes, partiel, pages, stabilite, blocage, tableaux, dailylog_equipe, fil ou lot15)" >&2; exit 1 ;; esac
# « Agir comme » et date simulée n'existent qu'en mode test (lot 12).
if [ "$scenario" = modes ] || [ "$scenario" = partiel ] || [ "$scenario" = pages ] || [ "$scenario" = stabilite ] || [ "$scenario" = blocage ] || [ "$scenario" = tableaux ] || [ "$scenario" = dailylog_equipe ] || [ "$scenario" = fil ] || [ "$scenario" = lot15 ]; then export KAIROS_MODE_TEST=${KAIROS_MODE_TEST:-true}; fi
base=${KAIROS_E2E_BASE_PG:-kairos_e2e_$scenario}
port=${KAIROS_E2E_PORT:-8798}
psql -X -q -d postgres -c "DROP DATABASE IF EXISTS $base" -c "CREATE DATABASE $base"
psql -X -q -v ON_ERROR_STOP=1 -d "$base" -f "$racine/schema.sql" >/dev/null 2>&1
python3 "$racine/tests_e2e/seed_$scenario.py" "$base"
# Lot 21 (revue R34) : même port PostgreSQL que psql (PGPORT), journal
# propre au scénario et au port, dossier des pièces jointes effacé à la fin.
export DATABASE_URL="postgresql://$PGUSER:$PGPASSWORD@$PGHOST:${PGPORT:-5432}/$base"
export SECRET_KEY=${SECRET_KEY:-e2e-0123456789abcdef0123456789abcdef0123456789}
export UPLOAD_DIR=$(mktemp -d) APP_BASE_URL="http://127.0.0.1:$port"
journal="${TMPDIR:-/tmp}/kairos-e2e-serveur-$scenario-$port.log"
# Port déjà pris : le scénario parlerait à un AUTRE serveur (revue 3).
if curl -fs -o /dev/null "http://127.0.0.1:$port/connexion"; then
  echo "Port $port déjà utilisé : choisir KAIROS_E2E_PORT=<port libre>." >&2; exit 1
fi
(cd "$racine" && exec python3 -m flask --app wsgi run -p "$port" --no-reload > "$journal" 2>&1) &
serveur=$!
trap 'kill $serveur 2>/dev/null || true; rm -rf "$UPLOAD_DIR"' EXIT
for _ in $(seq 40); do curl -fs -o /dev/null "http://127.0.0.1:$port/connexion" && break; sleep 0.25; done
kill -0 "$serveur" 2>/dev/null || { echo "Serveur Flask arrêté : voir $journal" >&2; exit 1; }
KAIROS_E2E_URL="http://127.0.0.1:$port" KAIROS_E2E_DB="$base" KAIROS_E2E_CAPTURES="${1:-}" \
  node "$racine/tests_e2e/$scenario.e2e.js"

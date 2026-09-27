#!/usr/bin/env bash
# Restauration d'une sauvegarde faite par scripts/backup_db.sh (audit n°2 :
# aucune procédure n'existait, et la restauration "évidente" — gunzip | psql
# dans une base fraîchement créée par docker compose — échouait sur
# "type phase_enum already exists", schema.sql y étant déjà appliqué).
#
# Usage (depuis n'importe où) :
#   ./scripts/restore_db.sh backups/kairos_AAAA-MM-JJ_HHMM.sql.gz \
#       [backups/kairos_uploads_AAAA-MM-JJ_HHMM.tar.gz]
#
# ATTENTION : remplace TOUTES les données actuelles de la base (et, si une
# archive est fournie, ajoute/écrase les pièces jointes). Une confirmation
# est demandée ; `--oui` en premier argument la saute (scripts).
set -euo pipefail
cd "$(dirname "$0")/.."

confirmer=1
if [ "${1:-}" = "--oui" ]; then
  confirmer=0
  shift
fi

FICHIER_DB="${1:-}"
FICHIER_UPLOADS="${2:-}"
if [ -z "$FICHIER_DB" ] || [ ! -f "$FICHIER_DB" ]; then
  echo "Usage : $0 [--oui] backups/kairos_XXXX.sql.gz [backups/kairos_uploads_XXXX.tar.gz]" >&2
  exit 2
fi
if [ -n "$FICHIER_UPLOADS" ] && [ ! -f "$FICHIER_UPLOADS" ]; then
  echo "Archive des pièces jointes introuvable : $FICHIER_UPLOADS" >&2
  exit 2
fi

# Vérifie les archives AVANT de toucher à quoi que ce soit.
gzip -t "$FICHIER_DB" || { echo "Sauvegarde de base corrompue : $FICHIER_DB" >&2; exit 1; }
if [ -n "$FICHIER_UPLOADS" ]; then
  gzip -t "$FICHIER_UPLOADS" || { echo "Archive de pièces jointes corrompue : $FICHIER_UPLOADS" >&2; exit 1; }
fi

# Même lecture de .env que backup_db.sh (jamais de `source`).
lire_env() {
  local cle="$1" defaut="$2" valeur=""
  if [ -f .env ]; then
    valeur="$(grep -E "^${cle}=" .env | tail -n1 | cut -d '=' -f2-)"
  fi
  valeur="${valeur%% #*}"
  valeur="$(printf '%s' "$valeur" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\\(.*\\)'$/\\1/")"
  echo "${valeur:-$defaut}"
}
POSTGRES_USER="$(lire_env POSTGRES_USER kairos)"
POSTGRES_DB="$(lire_env POSTGRES_DB kairos)"

if [ "$confirmer" -eq 1 ]; then
  echo "Cette opération REMPLACE toutes les données de la base « $POSTGRES_DB » par $FICHIER_DB."
  read -r -p "Tapez RESTAURER pour continuer : " reponse
  [ "$reponse" = "RESTAURER" ] || { echo "Annulé."; exit 1; }
fi

PSQL=(sudo docker compose exec -T db psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB")

echo "1/4 Démarrage des services…"
sudo docker compose up -d db web

echo "2/4 Remise à zéro du schéma…"
# Fonctionne aussi pour les sauvegardes antérieures à --clean (backup_db.sh
# d'avant l'audit n°2) : le schéma est vidé avant de recharger le dump.
"${PSQL[@]}" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

echo "3/4 Restauration de la base…"
gunzip -c "$FICHIER_DB" | "${PSQL[@]}"

if [ -n "$FICHIER_UPLOADS" ]; then
  echo "3b/4 Restauration des pièces jointes…"
  sudo docker compose exec -T web tar xzf - -C /app/uploads < "$FICHIER_UPLOADS"
fi

echo "4/4 Application des migrations plus récentes que la sauvegarde…"
sudo docker compose exec -T web flask migrer

echo "Restauration terminée."

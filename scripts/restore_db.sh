#!/usr/bin/env bash
# Restauration d'une sauvegarde faite par scripts/backup_db.sh.
#
# Usage (depuis n'importe où) :
#   sudo bash scripts/restore_db.sh [--oui] backups/kairos_AAAA-MM-JJ_HHMM.sql.gz \
#       [backups/kairos_uploads_AAAA-MM-JJ_HHMM.tar.gz]
#
# ATTENTION : remplace TOUTES les données actuelles de la base (et, si une
# archive est fournie, ajoute/écrase les pièces jointes). Une confirmation
# est demandée ; `--oui` en premier argument la saute (scripts, CI).
#
# Garde-fous (audits données I1 et QA B3 du lot 10 — l'ancienne version
# vidait la base AVANT tout contrôle, et un dump tronqué « réussissait »
# avec 0 ligne) :
# - un dump incomplet (sans la ligne finale de pg_dump) est refusé AVANT de
#   toucher à la base ;
# - `web` est arrêté pendant la restauration (personne n'écrit dedans) ;
# - la base actuelle est d'abord sauvegardée (avant_restauration_*.sql.gz,
#   dans KAIROS_BACKUP_DIR ou backups/) — abandon si cette copie échoue ;
# - vidage du schéma + rechargement dans UNE transaction : à la moindre
#   erreur, la base reste exactement comme avant ;
# - au redémarrage, `web` applique lui-même les migrations plus récentes que
#   la sauvegarde (précédées de la sauvegarde automatique du service
#   sauvegarde-migrations, voir docker-compose.yml).
set -euo pipefail

confirmer=1
if [ "${1:-}" = "--oui" ]; then
  confirmer=0
  shift
fi

# Chemins absolus AVANT de changer de dossier (audit QA m9 : un chemin
# relatif donné depuis un autre dossier était introuvable).
absolu() {
  if [ -n "$1" ] && [ -e "$1" ]; then
    echo "$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
  else
    echo "$1"
  fi
}
FICHIER_DB="$(absolu "${1:-}")"
FICHIER_UPLOADS="$(absolu "${2:-}")"
cd "$(dirname "$0")/.."

if [ -z "$FICHIER_DB" ] || [ ! -f "$FICHIER_DB" ]; then
  echo "Usage : $0 [--oui] backups/kairos_XXXX.sql.gz [backups/kairos_uploads_XXXX.tar.gz]" >&2
  exit 2
fi
if [ -n "$FICHIER_UPLOADS" ] && [ ! -f "$FICHIER_UPLOADS" ]; then
  echo "Archive des pièces jointes introuvable : $FICHIER_UPLOADS" >&2
  exit 2
fi

# 1. Vérifier les archives AVANT de toucher à quoi que ce soit. gzip -t ne
#    prouve que la compression : un pg_dump interrompu donne un fichier
#    valide mais sans sa dernière ligne.
gzip -t "$FICHIER_DB" || { echo "Sauvegarde de base corrompue : $FICHIER_DB — rien n'a été modifié." >&2; exit 1; }
if ! gunzip -c "$FICHIER_DB" | tail -n 20 | grep -q -- '-- PostgreSQL database dump complete'; then
  echo "Sauvegarde de base incomplète (pg_dump interrompu ?) : $FICHIER_DB — rien n'a été modifié." >&2
  exit 1
fi
if [ -n "$FICHIER_UPLOADS" ]; then
  tar -tzf "$FICHIER_UPLOADS" > /dev/null \
    || { echo "Archive de pièces jointes corrompue : $FICHIER_UPLOADS — rien n'a été modifié." >&2; exit 1; }
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
DEST="${KAIROS_BACKUP_DIR:-$(lire_env KAIROS_BACKUP_DIR backups)}"

if [ "$confirmer" -eq 1 ]; then
  echo "Cette opération REMPLACE toutes les données de la base « $POSTGRES_DB » par $FICHIER_DB."
  read -r -p "Tapez RESTAURER pour continuer : " reponse
  [ "$reponse" = "RESTAURER" ] || { echo "Annulé."; exit 1; }
fi

PSQL=(sudo docker compose exec -T db psql -X -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB")
umask 077
mkdir -p "$DEST"

echo "1/5 Base de données démarrée, application arrêtée…"
sudo docker compose up -d --wait db
sudo docker compose stop web

echo "2/5 Copie de sécurité de la base actuelle…"
FILET="$DEST/avant_restauration_$(date +%Y-%m-%d_%H%M%S).sql.gz"
if ! sudo docker compose exec -T db pg_dump --clean --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$FILET" \
   || ! gzip -t "$FILET"; then
  rm -f "$FILET"
  echo "Copie de sécurité impossible — restauration annulée, rien n'a été modifié. Redémarrage de l'application…" >&2
  sudo docker compose up -d web
  exit 1
fi
echo "   -> $FILET"

echo "3/5 Restauration de la base (une seule transaction)…"
# Fonctionne aussi pour les sauvegardes antérieures à --clean : le schéma
# est vidé dans la même transaction que le rechargement.
if ! { echo "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"; gunzip -c "$FICHIER_DB"; } \
     | "${PSQL[@]}" --single-transaction; then
  echo "ÉCHEC : la base n'a PAS été modifiée. Redémarrage de l'application…" >&2
  sudo docker compose up -d web
  exit 1
fi
# Fuseau de la base (audit données M15) : c'est un réglage de la BASE, pas
# du dump — perdu si la base cible n'a pas été créée par schema.sql.
"${PSQL[@]}" -c "ALTER DATABASE \"$POSTGRES_DB\" SET timezone = 'Africa/Tunis'"

if [ -n "$FICHIER_UPLOADS" ]; then
  echo "4/5 Restauration des pièces jointes…"
  # Conteneur ponctuel (web est arrêté) qui monte le volume kairos_uploads.
  sudo docker compose run --rm --no-deps -T web tar xzf - -C /app/uploads < "$FICHIER_UPLOADS"
fi

echo "5/5 Redémarrage (les migrations plus récentes que la sauvegarde sont appliquées au démarrage)…"
sudo docker compose up -d web
comptage="$("${PSQL[@]}" -At -c "SELECT (SELECT count(*) FROM utilisateur) || ' utilisateurs, ' || (SELECT count(*) FROM projet) || ' projets'" 2>/dev/null || echo "comptage indisponible")"
echo "Restauration terminée : $comptage."
echo "Vérifier : sudo docker compose ps (web « healthy ») et sudo docker compose logs web --tail 40."
echo "Copie de sécurité d'avant restauration : $FILET"

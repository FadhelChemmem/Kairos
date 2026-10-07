#!/usr/bin/env bash
# Sauvegarde automatique AVANT toute migration (audit QA du lot 10, B4) :
# `flask migrer` s'exécute au démarrage du conteneur `web` et modifie la
# base de façon irréversible. Ce script tourne juste avant, dans le service
# `sauvegarde-migrations` de docker-compose.yml (image postgres:16, donc le
# pg_dump de la même version que le serveur) : si au moins une migration
# du dossier migrations/ n'est pas encore inscrite dans schema_migrations,
# la base est sauvegardée dans $DEST/avant_migration_<date>.sql.gz. Sinon
# il ne fait rien. Un échec empêche `web` de démarrer (donc de migrer).
#
# Variables : PGHOST, PGUSER, PGPASSWORD, PGDATABASE (connexion libpq),
# MIGRATIONS_DIR (défaut /migrations), DEST (défaut /sauvegardes),
# GARDER (nombre de sauvegardes « avant migration » conservées, défaut 10).
set -euo pipefail
umask 077

MIGRATIONS_DIR="${MIGRATIONS_DIR:-/migrations}"
DEST="${DEST:-/sauvegardes}"
GARDER="${GARDER:-10}"
PSQL=(psql -X -A -t -q -v ON_ERROR_STOP=1)

# Affectations séparées : une erreur de connexion doit arrêter le script
# (set -e), pas passer pour une base vide.
base_initialisee="$("${PSQL[@]}" -c "SELECT to_regclass('public.utilisateur') IS NOT NULL")"
table_migrations="$("${PSQL[@]}" -c "SELECT to_regclass('public.schema_migrations') IS NOT NULL")"
if [ "$base_initialisee" != "t" ]; then
  echo "Base vide (première installation) : rien à sauvegarder."
  exit 0
fi

attendues="$(find "$MIGRATIONS_DIR" -maxdepth 1 -name '*.sql' -printf '%f\n' | sed 's/\.sql$//' | sort)"
appliquees=""
if [ "$table_migrations" = "t" ]; then
  appliquees="$("${PSQL[@]}" -c "SELECT version FROM schema_migrations" | sort)"
fi
en_attente="$(comm -23 <(printf '%s\n' "$attendues") <(printf '%s\n' "$appliquees") | sed '/^$/d')"

if [ -z "$en_attente" ]; then
  echo "Aucune migration en attente : pas de sauvegarde."
  exit 0
fi

echo "Migration(s) en attente : $(echo "$en_attente" | tr '\n' ' ')"
mkdir -p "$DEST"
fichier="$DEST/avant_migration_$(date +%Y-%m-%d_%H%M%S).sql.gz"
tmp="$fichier.tmp"
if ! pg_dump --clean --if-exists | gzip > "$tmp" \
   || ! gzip -t "$tmp" \
   || ! gunzip -c "$tmp" | tail -n 20 | grep -q -- '-- PostgreSQL database dump complete'; then
  rm -f "$tmp"
  echo "ÉCHEC de la sauvegarde avant migration : l'application ne démarre pas (rien n'a été migré)." >&2
  exit 1
fi
mv "$tmp" "$fichier"
echo "Sauvegarde avant migration : $fichier"

# Rotation : seules les $GARDER dernières sauvegardes « avant migration »
# sont gardées (les sauvegardes quotidiennes de backup_db.sh ne sont pas
# concernées).
find "$DEST" -maxdepth 1 -name 'avant_migration_*.sql.gz' -printf '%T@ %p\n' \
  | sort -rn | tail -n +"$((GARDER + 1))" | cut -d' ' -f2- | xargs -r rm --

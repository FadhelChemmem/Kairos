#!/usr/bin/env bash
# Sauvegarde de la base Kairos (pg_dump) ET des pièces jointes (volume
# kairos_uploads), recommandation "architecte logiciel" du 2026-09-20 : les
# données vivent aujourd'hui uniquement dans des volumes Docker nommés sur
# le NAS — sans copie séparée, un disque mort emporte tout l'historique
# projets/tâches/heures ET tous les fichiers déjà envoyés.
#
# Usage : ./scripts/backup_db.sh
# (à lancer depuis le dossier du projet, ou de n'importe où : le script
# se replace tout seul dans son dossier)
#
# Automatisation recommandée : TrueNAS SCALE > Système > Tâches planifiées
# (Advanced Settings > Cron Jobs) — commande à y coller :
#   /chemin/vers/kairos-app/scripts/backup_db.sh
# Une fois par jour, en dehors des heures de bureau, suffit largement.
set -euo pipefail
cd "$(dirname "$0")/.."

# Umask restrictif (PROMPT_CORRECTIONS.md P1 #15) : une sauvegarde contient
# TOUTES les données de l'entreprise (base + pièces jointes) — sans ça, les
# fichiers créés ici héritent de l'umask du système (souvent 022, donc
# lisibles par tout le monde sur la machine).
umask 077

# Lecture de .env SANS `source` (PROMPT_CORRECTIONS.md P1 #15) : `source`
# exécute le fichier comme un script shell — une valeur mal échappée (ex.
# un mot de passe contenant par accident un `$(...)` ou des backticks) y
# exécuterait du code arbitraire. On extrait ici uniquement les deux
# variables dont ce script a besoin, sans jamais évaluer le contenu du
# fichier ; dernière occurrence retenue en cas de doublon, comme le ferait
# un vrai `source`.
lire_env() {
  local cle="$1" defaut="$2" valeur=""
  if [ -f .env ]; then
    valeur="$(grep -E "^${cle}=" .env | tail -n1 | cut -d '=' -f2-)"
  fi
  echo "${valeur:-$defaut}"
}
POSTGRES_USER="$(lire_env POSTGRES_USER kairos)"
POSTGRES_DB="$(lire_env POSTGRES_DB kairos)"

DATE="$(date +%Y-%m-%d_%H%M)"
mkdir -p backups

# --- Base de données (pg_dump) ---
FICHIER_DB="backups/kairos_${DATE}.sql.gz"
TMP_DB="${FICHIER_DB}.tmp"

# Écriture atomique + vérification d'intégrité (PROMPT_CORRECTIONS.md P1 #15) :
# sans ça, un pg_dump interrompu en cours de route (base éteinte, disque
# plein, conteneur tué en cours de sauvegarde) laissait quand même un
# fichier .sql.gz tronqué — donc invalide — directement sous son nom final,
# indiscernable d'une vraie sauvegarde jusqu'au jour où on essaie de la
# restaurer. On écrit donc d'abord dans un .tmp, jamais exposé sous le nom
# final tant qu'il n'a pas été relu et validé (gzip -t).
set +e
sudo docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$TMP_DB"
statut_db=$?
set -e
if [ "$statut_db" -ne 0 ] || ! gzip -t "$TMP_DB" 2>/dev/null; then
  echo "Erreur : sauvegarde de la base invalide (pg_dump interrompu ?) — abandon, rien n'est remplacé." >&2
  rm -f "$TMP_DB"
  exit 1
fi
mv "$TMP_DB" "$FICHIER_DB"
echo "Sauvegarde base écrite : $FICHIER_DB"

# --- Pièces jointes (volume kairos_uploads) (PROMPT_CORRECTIONS.md P1 #15) :
# tache_piece_jointe/post_piece_jointe (voir app/storage.py) vivent sur
# disque, en dehors de la base — sans ce second volet, restaurer à partir
# de la seule sauvegarde Postgres perdait silencieusement tous les fichiers
# déjà envoyés (notes de calcul, plans...). On passe par le conteneur `web`,
# qui monte déjà ce volume (/app/uploads, docker-compose.yml) — pas besoin
# de tirer une image supplémentaire. Même principe d'écriture atomique que
# ci-dessus. ---
FICHIER_UPLOADS="backups/kairos_uploads_${DATE}.tar.gz"
TMP_UPLOADS="${FICHIER_UPLOADS}.tmp"

set +e
sudo docker compose exec -T web tar czf - -C /app/uploads . > "$TMP_UPLOADS"
statut_uploads=$?
set -e
if [ "$statut_uploads" -ne 0 ] || ! gzip -t "$TMP_UPLOADS" 2>/dev/null; then
  echo "Erreur : sauvegarde des pièces jointes invalide — abandon, rien n'est remplacé." >&2
  rm -f "$TMP_UPLOADS"
  exit 1
fi
mv "$TMP_UPLOADS" "$FICHIER_UPLOADS"
echo "Sauvegarde pièces jointes écrite : $FICHIER_UPLOADS"

# Garde les 30 dernières sauvegardes de chaque type, supprime le reste —
# évite de remplir le disque silencieusement au fil des mois. Ne compte que
# le nouveau préfixe "kairos_" (retour Fadhel, 2026-09-21, renommage
# workflowbook → Kairos) : les anciens fichiers "workflowbook_*.sql.gz"
# ne sont plus reconnus par ce nettoyage automatique et doivent être
# supprimés à la main si besoin (voir README, section Dépannage).
ls -1t backups/kairos_*.sql.gz 2>/dev/null | tail -n +31 | xargs -r rm --
ls -1t backups/kairos_uploads_*.tar.gz 2>/dev/null | tail -n +31 | xargs -r rm --

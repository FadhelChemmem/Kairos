#!/usr/bin/env bash
# Sauvegarde de la base Kairos (pg_dump), recommandation "architecte
# logiciel" du 2026-09-20 : les données vivent aujourd'hui uniquement dans
# un volume Docker nommé sur le NAS — sans copie séparée, un disque mort
# emporte tout l'historique projets/tâches/heures.
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

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

DATE="$(date +%Y-%m-%d_%H%M)"
mkdir -p backups
FICHIER="backups/kairos_${DATE}.sql.gz"

sudo docker compose exec -T db pg_dump -U "${POSTGRES_USER:-kairos}" "${POSTGRES_DB:-kairos}" \
  | gzip > "$FICHIER"

echo "Sauvegarde écrite : $FICHIER"

# Garde les 30 dernières sauvegardes, supprime le reste — évite de remplir
# le disque silencieusement au fil des mois. Ne compte que les sauvegardes
# au nouveau préfixe "kairos_" (retour Fadhel, 2026-09-21, renommage
# workflowbook → Kairos) : les anciens fichiers "workflowbook_*.sql.gz"
# ne sont plus reconnus par ce nettoyage automatique et doivent être
# supprimés à la main si besoin (voir README, section Dépannage).
ls -1t backups/kairos_*.sql.gz 2>/dev/null | tail -n +31 | xargs -r rm --

#!/usr/bin/env bash
# Déploiement Kairos en une commande, sur le serveur (TrueNAS), en SSH :
#
#     cd /mnt/Pool/Kairos && sudo bash deploy.sh
#
# Étapes : contrôle du dépôt -> récupération de master (GitHub) ->
# sauvegarde (base + pièces jointes) -> repères de retour arrière ->
# reconstruction et redémarrage -> attente de « healthy » -> contrôle des
# migrations et des journaux. S'arrête au premier problème avec un message
# clair ; rien n'est redémarré tant que la sauvegarde n'a pas réussi.
#
# Retour arrière (affiché à la fin) :
#   sudo bash scripts/restore_db.sh <sauvegarde>.sql.gz
#   git switch --detach avant-deploiement
#   sudo docker tag kairos-web:avant-deploiement kairos-web:latest
#   sudo docker compose up -d --no-build
set -euo pipefail
cd "$(dirname "$0")"

rouge() { printf '\033[31m%s\033[0m\n' "$*"; }
vert()  { printf '\033[32m%s\033[0m\n' "$*"; }
etape() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
stop()  { rouge "PROBLÈME : $*"; rouge "Rien d'autre n'a été fait après cette étape. Envoie ce message."; exit 1; }

etape "1/6 Contrôle du dépôt"
branche="$(git rev-parse --abbrev-ref HEAD)"
[ "$branche" = "master" ] || stop "branche « $branche » au lieu de master (git switch master)."
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  git status --short --untracked-files=no
  stop "des fichiers suivis sont modifiés localement (voir ci-dessus)."
fi
avant="$(git rev-parse --short HEAD)"
echo "Version actuelle : $avant $(git log -1 --format=%s)"

etape "2/6 Récupération de la nouvelle version (GitHub)"
git fetch origin master || stop "impossible de joindre GitHub (réessayer dans quelques minutes)."
if [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/master)" ]; then
  vert "Déjà à jour : rien à déployer."
  exit 0
fi
git log --oneline HEAD..origin/master
git merge --ff-only origin/master || stop "master local a divergé de GitHub (ne pas forcer : m'envoyer « git log --oneline -5 »)."
apres="$(git rev-parse --short HEAD)"

etape "3/6 Sauvegarde"
bash scripts/backup_db.sh || stop "la sauvegarde a échoué : déploiement annulé (le code est à jour mais l'appli n'a pas redémarré)."

etape "4/6 Repères de retour arrière"
git tag -f avant-deploiement "$avant" >/dev/null
image="$(docker compose images web --format json 2>/dev/null | grep -o '"Repository":"[^"]*"' | head -1 | cut -d'"' -f4 || true)"
image="${image:-kairos-web}"
if docker image inspect "$image:latest" >/dev/null 2>&1; then
  docker tag "$image:latest" "$image:avant-deploiement"
  echo "Image précédente gardée : $image:avant-deploiement"
fi

etape "5/6 Reconstruction et redémarrage"
debut="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
docker compose up -d --build || stop "docker compose up a échoué."
echo -n "Attente de l'appli"
etat=""
for _ in $(seq 1 36); do
  etat="$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q web)" 2>/dev/null || echo inconnu)"
  [ "$etat" = "healthy" ] && break
  [ "$etat" = "unhealthy" ] && break
  echo -n "."; sleep 5
done
echo
[ "$etat" = "healthy" ] || { docker compose logs web --since "$debut" --tail 80; stop "l'appli n'est pas « healthy » (état : $etat)."; }

etape "6/6 Contrôle des migrations et des journaux"
journaux="$(docker compose logs web --since "$debut" 2>&1 || true)"
echo "$journaux" | grep -E "Application de|-> OK|migration\(s\) appliquée|Rien à faire" || true
if echo "$journaux" | grep -Eq "Traceback|ERROR|ECHEC|Erreur"; then
  echo "$journaux" | grep -E -B2 -A8 "Traceback|ERROR|ECHEC|Erreur" | tail -60
  stop "erreur dans les journaux (voir ci-dessus)."
fi
docker compose exec -T db sh -c 'psql -X -At -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  <<< "SELECT 'Dernière migration : ' || max(version) FROM schema_migrations;" || true

vert ""
vert "OK : Kairos déployé ($avant -> $apres)."
echo "Retour arrière si besoin :"
echo "  sudo bash scripts/restore_db.sh <sauvegarde ci-dessus>.sql.gz"
echo "  git switch --detach avant-deploiement"
echo "  sudo docker tag $image:avant-deploiement $image:latest && sudo docker compose up -d --no-build"

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
# Deux façons d'amener la nouvelle version (lot 12) :
#   - poussée sur GitHub depuis un autre poste : le script la récupère ;
#   - patch appliqué SUR CE SERVEUR (git am) puis poussé : le dépôt est déjà
#     à jour, mais l'appli n'a pas été reconstruite — le script la déploie
#     quand même. Le tag `deploye` retient la dernière version réellement
#     déployée (« rien à déployer » seulement si c'est déjà elle) ; la
#     version de retour arrière est ce tag, à défaut l'état d'avant git am
#     (ORIG_HEAD).
#
# Retour arrière (affiché à la fin), DANS CET ORDRE (lot 20, revue QA n° 6) :
#   git switch --detach avant-deploiement
#   git tag -f deploye HEAD
#   sudo docker tag kairos-web:avant-deploiement kairos-web:latest
#   sudo bash scripts/restore_db.sh <sauvegarde>.sql.gz
# restore_db.sh redémarre `web`, qui applique les migrations de SON image :
# restaurer avec la nouvelle image encore en place re-migrait aussitôt la
# base restaurée (ancien code sur une base migrée, sans message). Le tag
# `deploye` remis sur l'ancienne version : un nouveau `deploy.sh` (après
# `git switch master`) redéploie la nouvelle au lieu de dire « Déjà à jour ».
#
# Lot 21 (revue R4) : tout le script est une fonction lue d'un bloc — la
# mise à jour du code (git merge) ne change plus le script en cours de
# lecture ; s'il a changé, il est relancé dans sa nouvelle version.
# Lot 21 (revue R5) : `.deploiement_en_cours` garde les repères d'une
# tentative qui a échoué (version, image et sauvegarde d'AVANT) : une
# relance ne les remplace pas par ceux de la nouvelle version.
# Lot 24 (contre-expertise MD-4 à MD-6) : chemin absolu du script gardé
# avant le `cd` (relance possible quel que soit le dossier de départ) ; un
# échec imprime le retour arrière ; les repères gardés disent leur date.
set -euo pipefail
SCRIPT="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
cd "$(dirname "$SCRIPT")"

REPERES=".deploiement_en_cours"

main() {

rouge() { printf '\033[31m%s\033[0m\n' "$*"; }
vert()  { printf '\033[32m%s\033[0m\n' "$*"; }
etape() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
stop()  {
  rouge "PROBLÈME : $*"
  rouge "Rien d'autre n'a été fait après cette étape. Envoie ce message."
  if [ -f "$REPERES" ]; then
    echo "Pour revenir à la version d'avant (seulement si on te le demande), dans cet ordre :"
    echo "  git switch --detach avant-deploiement"
    echo "  git tag -f deploye HEAD"
    echo "  sudo docker tag ${image:-kairos-web}:avant-deploiement ${image:-kairos-web}:latest"
    echo "  sudo bash scripts/restore_db.sh $(sed -n 's/^sauvegarde=//p' "$REPERES")"
    echo "  rm -f $REPERES"
  fi
  exit 1
}

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
deploye="$(git rev-parse -q --verify 'refs/tags/deploye^{commit}' 2>/dev/null || true)"
if [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/master)" ]; then
  if [ "$deploye" = "$(git rev-parse HEAD)" ]; then
    vert "Déjà à jour : rien à déployer."
    exit 0
  fi
  # Patch appliqué ici (git am) puis poussé : à déployer. Version en
  # service : le dernier déploiement, sinon l'état d'avant git am.
  echo "Code déjà à jour sur ce serveur (patch appliqué ou relance) : déploiement de $(git log -1 --format='%h %s')."
  orig="$(git rev-parse -q --verify 'ORIG_HEAD^{commit}' 2>/dev/null || true)"
  if [ -n "$deploye" ]; then
    avant="$(git rev-parse --short "$deploye")"
  elif [ -n "$orig" ] && [ "$orig" != "$(git rev-parse HEAD)" ] && git merge-base --is-ancestor "$orig" HEAD; then
    avant="$(git rev-parse --short "$orig")"
  else
    rouge "Version précédente introuvable : le repère de retour arrière sera la version actuelle."
  fi
  git log --oneline "$avant..HEAD"
else
  git log --oneline HEAD..origin/master
  ancien="$(git rev-parse HEAD)"
  git merge --ff-only origin/master || stop "master local a divergé de GitHub (ne pas forcer : m'envoyer « git log --oneline -5 »)."
  if [ -z "${KAIROS_DEPLOY_RELANCE:-}" ] && ! git diff --quiet "$ancien" HEAD -- deploy.sh; then
    echo "deploy.sh a changé avec cette version : relance dans sa nouvelle version."
    KAIROS_DEPLOY_RELANCE=1 exec bash "$SCRIPT" "$@"
  fi
fi
apres="$(git rev-parse --short HEAD)"

etape "3/6 Sauvegarde"
sortie_sauvegarde="$(bash scripts/backup_db.sh)" || { printf '%s\n' "$sortie_sauvegarde"; stop "la sauvegarde a échoué : déploiement annulé (le code est à jour mais l'appli n'a pas redémarré)."; }
printf '%s\n' "$sortie_sauvegarde"
sauvegarde="$(printf '%s\n' "$sortie_sauvegarde" | sed -n 's/^Sauvegarde base écrite : //p' | tail -1)"

etape "4/6 Repères de retour arrière"
image="$(docker compose images web --format json 2>/dev/null | grep -o '"Repository":"[^"]*"' | head -1 | cut -d'"' -f4 || true)"
image="${image:-kairos-web}"
if [ -f "$REPERES" ]; then
  # Relance après un échec : les repères d'AVANT la première tentative
  # restent (l'image en place peut déjà être la nouvelle, la base déjà migrée).
  avant="$(sed -n 's/^avant=//p' "$REPERES")"
  sauvegarde="$(sed -n 's/^sauvegarde=//p' "$REPERES")"
  quand="$(sed -n 's/^date=//p' "$REPERES")"
  rouge "Tentative précédente inachevée${quand:+ du $quand} : repères de retour arrière gardés ($avant, ${sauvegarde:-sauvegarde inconnue})."
  rouge "Si un retour arrière a été fait depuis, supprime $REPERES puis relance."
else
  git tag -f avant-deploiement "$avant" >/dev/null
  if docker image inspect "$image:latest" >/dev/null 2>&1; then
    docker tag "$image:latest" "$image:avant-deploiement"
    echo "Image précédente gardée : $image:avant-deploiement"
  fi
  printf 'avant=%s\nsauvegarde=%s\ndate=%s\n' "$avant" "$sauvegarde" "$(date '+%d/%m/%Y %H:%M')" > "$REPERES"
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
# Lot 20 (revue QA n° 17b) : les lignes d'accès de gunicorn (« GET
# /recherche/api?q=Erreur … 200 ») ne sont pas des erreurs.
journaux="$(printf '%s\n' "$journaux" | grep -Ev '"(GET|POST|HEAD|PUT|PATCH|DELETE|OPTIONS) [^"]* HTTP/[0-9.]+" [0-9]{3} ' || true)"
echo "$journaux" | grep -E "Application de|-> OK|migration\(s\) appliquée|Rien à faire" || true
if echo "$journaux" | grep -Eq "Traceback|ERROR|ECHEC|Erreur"; then
  echo "$journaux" | grep -E -B2 -A8 "Traceback|ERROR|ECHEC|Erreur" | tail -60
  stop "erreur dans les journaux (voir ci-dessus)."
fi
docker compose exec -T db sh -c 'psql -X -At -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  <<< "SELECT 'Dernière migration : ' || max(version) FROM schema_migrations;" || true

git tag -f deploye HEAD >/dev/null
rm -f "$REPERES"
vert ""
vert "OK : Kairos déployé ($avant -> $apres)."
echo "Retour arrière si besoin (dans cet ordre : code, repère, image, puis base) :"
echo "  git switch --detach avant-deploiement"
echo "  git tag -f deploye HEAD"
echo "  sudo docker tag $image:avant-deploiement $image:latest"
echo "  sudo bash scripts/restore_db.sh ${sauvegarde:-<sauvegarde faite avant le déploiement>.sql.gz}"
}

main "$@"
exit $?

# Kairos

Reconstruction interne de l'ancien outil Kairos (initialement développé
par un prestataire) — Projets, Tâches, DailyLog, Utilisateurs,
Notifications et fil de posts (étape 1, complète). Flask + PostgreSQL
(SQL brut, pas d'ORM) + Jinja2, déployé via Docker Compose.

## Ce qui est livré (étape 1 — complète)

- Le schéma de base complet et durci (`schema.sql`), déjà validé en
  conditions réelles (voir les commentaires en tête du fichier).
- Authentification (connexion/déconnexion, mots de passe hachés), écran
  de connexion restylé (`app/templates/login.html`).
- Traçabilité automatique (`created_by`/`updated_by` + `audit_log`) sur
  toute écriture, via le mécanisme `app.current_user_id` documenté dans
  `app/db.py`.
- Pages **Accueil** et **Page projet**, fidèles aux maquettes validées
  ensemble (palette verte, sticky header, etc.).
- **Nouveau projet** : formulaire de création (code proposé automatiquement,
  modifiable, comme décidé) — `/projets/nouveau`.
- Tâches : création, changement d'état, clôture (avec le post
  automatique et son tag, comme décidé). Vérifiée, Arrêtée et Abandonnée
  sont réservées au chef de projet titulaire, aux co-chefs et à l'Admin,
  pour y entrer comme pour en sortir ; un intervenant de la tâche garde
  En cours, Bloquée et Terminée (décision du gérant, lot 10 — contrôlé par
  la route, sous verrou par le repository et en base par la migration 0015).
- **Composeur "Nouveau post"** (Tâche/Information/Requête) avec personnes
  taguées, lien et pièce jointe en glisser-déposer sur les panneaux
  Information et Requête.
- Fil de posts : création manuelle, réactions, commentaires, et
  "rebond" (créer un post lié à un autre — voir `app/repositories/posts.py`
  pour la convention interne ; le mot n'apparaît nulle part dans
  l'interface, uniquement une icône flèche, comme demandé).
- **Pièces jointes** : upload/téléchargement de fichiers sur une tâche ou
  un post (stockage sur disque, hors base — voir `app/storage.py`).
- **Deadlines** : vue calendrier/Gantt à défilement horizontal, fidèle à
  la maquette (`/deadlines`) — barres colorées par urgence (rouge
  en retard/imminent, orange cette semaine, vert plus tard).
- "Tous les projets" avec filtres par état et par phase, visibilité par
  équipe ; pages de 50 projets avec le vrai total, recherche sans accents
  sur tous les projets visibles (lot 11). Un projet sans équipe reçoit
  celle de son chef, à défaut MIDGARD (migration 0016, reprise et
  rechargement Chronos).
- **Recherche globale** (barre du haut) : projets, tâches et personnes
  (comptes désactivés signalés), insensible aux accents et à la casse
  (extension PostgreSQL `unaccent`, créée par la migration 0016 : elle est
  fournie par l'image `postgres:16` et peut être créée par le propriétaire
  de la base).
- **Utilisateurs** (`/utilisateurs`, admin/RH, et en lecture seule pour
  les chefs de projet — voir plus bas) : liste avec filtres, bascule
  actif/inactif (admin/RH), création de compte (`/utilisateurs/nouveau`)
  avec règle RH singleton et champs personnalisés (JSONB), fiche complète
  modifiable par admin/RH (`/utilisateurs/<id>`, y compris changement de
  rôle et de mot de passe — sauf son propre rôle, protégé). Photo de
  profil optionnelle (création, fiche, "Infos perso").
- **Chef de projet** (`/utilisateurs` et `/utilisateurs/<id>`) : accès en
  lecture seule à n'importe quel utilisateur — nom, téléphone et Daily
  log de la semaine dernière uniquement, rien de modifiable, pas
  d'actions admin (création de compte, activer/désactiver).
- **Mot de passe oublié** (`/mot-de-passe-oublie` puis lien reçu par
  email, valable 1 heure, à usage unique) et **création de compte sans
  mot de passe initial** : l'admin/RH ne définit rien, un email (même
  lien, même mécanisme) est envoyé pour que le nouvel utilisateur
  choisisse lui-même son mot de passe — tant qu'il ne l'a pas fait, le
  compte reste "Non vérifié". Chacun peut aussi changer son propre mot
  de passe depuis "Infos perso" (`/utilisateurs/moi`). Anti-bourrinage
  sur la connexion et la demande de réinitialisation (5 tentatives /
  15 min par email).
- **Daily log v9** (`/dailylog`, lot 10) : −/+ par 30 min ou saisie au
  clavier (2,5 · 2h30 · 45min), 10 h au plus par jour, objectif de journée
  personnel (4 à 10 h, repère non bloquant), jours absents, « Copier le
  dernier jour rempli », enregistrement automatique au changement de jour
  et en arrière-plan, calendrier rempli / absent / non renseigné, bannière
  des jours manqués. Saisie libre aujourd'hui et les 14 jours précédents
  (au fuseau de la personne : Tunis ou Guyane, réglé sur sa fiche) ;
  au-delà, correction par le chef de projet (lignes de ses projets) ou
  l'Admin, tracée à son nom. API JSON : voir `app/routes/dailylog.py`.
- **Notifications** : cloche dans la barre du haut avec compteur temps
  réel, page `/notifications`, déclenchées par mention (post/commentaire),
  affectation à une tâche, ajout comme intervenant, et rappel automatique
  si le dernier jour ouvré n'a pas été rempli (le lundi : le vendredi).

**Reste à construire** (étape 2, plus tard) : Congés/Télétravail,
rôle Client, fil "Information" hors-projet ciblé par équipe.

**Sécurité** : toutes les actions (formulaires POST) sont protégées contre
le CSRF (Flask-WTF), la déconnexion se fait en POST, et chaque accès à un
projet, une tâche, un post ou une pièce jointe vérifie que l'utilisateur
voit bien ce projet.

## Démarrer avec Docker (recommandé)

```bash
cp .env.example .env
# éditer .env (voir les commentaires dans le fichier) — au minimum :
#   POSTGRES_PASSWORD, SECRET_KEY (32 caractères minimum, sinon l'appli refuse de démarrer),
#   APP_BASE_URL et SMTP_* (la création de compte envoie un email pour choisir son mot de passe)
#   Derrière un reverse proxy HTTPS : SESSION_COOKIE_SECURE=true, TRUSTED_PROXY_COUNT=1 et
#   TRUSTED_PROXY_IPS = adresse(s) du proxy vue(s) par l'appli (voir « Reverse proxy » plus bas)
#   Mode test des e-mails : MAIL_DESTINATAIRES_AUTORISES (voir « E-mails en mode test » plus bas)

docker compose up -d --build
```

Au premier démarrage, `schema.sql` est exécuté automatiquement (le
service `db` le monte dans `/docker-entrypoint-initdb.d/`). Il ne crée
aucun utilisateur — il faut créer le tout premier compte à la main :

```bash
docker compose exec web flask create-user \
  --email fadhel@midgard.tn --prenom Fadhel --nom Chemmem \
  --password "un-mot-de-passe-solide" --role admin
```

L'application est ensuite accessible sur `http://<adresse-du-serveur>:8000/`.

### Reverse proxy (HTTPS)

Derrière un reverse proxy (Nginx Proxy Manager…), l'appli lit l'IP réelle
du client et le `https` dans les en-têtes `X-Forwarded-*` — mais
**seulement** pour une requête qui arrive d'une adresse de
`TRUSTED_PROXY_IPS` (IP ou réseaux CIDR séparés par des virgules ; voir
`app/proxy.py`). Une requête d'une autre adresse (un poste du LAN qui vise
directement le port 8000) garde son adresse réelle : ces en-têtes sont
ignorés, le limiteur de connexion compte sur la vraie adresse, et un
avertissement l'indique une fois dans `docker compose logs web` :

```
WARNING app.proxy: En-têtes X-Forwarded-* ignorés : requête reçue directement de 172.19.0.4, …
```

Si l'adresse citée est celle du proxy, l'ajouter à `TRUSTED_PROXY_IPS`
puis `docker compose up -d`. Pour la retrouver :
`docker compose logs web | grep "X-Forwarded"`. Dans les lignes d'accès de
gunicorn (`docker compose logs web | grep "GET /"`), la première colonne
est l'adresse du client retenue par l'appli : l'IP réelle du poste pour une
requête passée par un proxy de confiance (ou arrivée directement), l'IP du
proxy s'il n'est pas reconnu.

`TRUSTED_PROXY_IPS` vide avec `TRUSTED_PROXY_COUNT` > 0 : liste par défaut
`172.16.0.0/12` (réseaux Docker) + `127.0.0.1` + `HOST_IP` (IP LAN du
serveur, facultative), avec un avertissement au démarrage si le port 8000
est publié sur le LAN (`WEB_BIND` ≠ `127.0.0.1`). L'appli démarre dans
tous les cas.

Exemple (Nginx Proxy Manager en conteneur sur le serveur 192.168.100.17,
qui renvoie vers le port 8000 publié) :

```
TRUSTED_PROXY_COUNT=1
TRUSTED_PROXY_IPS=172.16.0.0/12
SESSION_COOKIE_SECURE=true
WEB_BIND=0.0.0.0
```

### Compression et cache des fichiers statiques

L'appli compresse elle-même en gzip les pages, le JSON, les CSS et les JS
de plus de 1 Ko (`app/perf.py`). Si le proxy compresse déjà (`gzip on;`
dans la configuration avancée de Nginx Proxy Manager), mettre
`COMPRESSION_GZIP=false` dans `.env` pour ne pas compresser deux fois.

Les URL des fichiers de `/static` portent l'empreinte du fichier
(`app.css?v=1f1263732efa`) et sont servies avec
`Cache-Control: public, max-age=31536000, immutable` : le navigateur ne
les redemande plus, et un fichier modifié change d'URL au déploiement
suivant. Les pages, API, exports et pièces jointes d'un utilisateur
connecté sont en `Cache-Control: no-store` ; seules les photos de profil,
dont l'URL porte l'empreinte de la photo (`/fichiers/avatars/12?v=…`),
restent une heure dans le cache privé du navigateur (`private,
max-age=3600`), et une nouvelle photo change d'URL. Si le proxy réécrit
`Cache-Control` sur `/static`, retirer cette règle.

### E-mails en mode test

Tant que Kairos est en test, `MAIL_DESTINATAIRES_AUTORISES` limite les
destinataires possibles : adresses et/ou domaines `@domaine`, séparés par
des virgules, casse ignorée.

```
MAIL_DESTINATAIRES_AUTORISES=medfadhelchemmem@gmail.com,kairos@midgardengineering.com
```

Un e-mail vers une autre adresse n'est **jamais** envoyé, quel que soit le
chemin (contrôle dans `app/mailer.py`) : il est journalisé sans son contenu,
adresse masquée (`E-mail NON envoyé à me***@exemple.tn (mode test …)`), et
l'écran le dit — « Envoyer un lien de réinitialisation » et création de
compte (« mode test : cette adresse n'est pas dans la liste… »), « Mot de
passe oublié » (message qui ne dépend que de l'adresse saisie, pas de
l'existence d'un compte). Vide ou absente : comportement normal.

## Mettre à jour (après un `git pull`)

```bash
git pull
sudo docker compose up -d --build
sudo docker compose logs sauvegarde-migrations web --tail 60
```

Avant toute mise à jour qui contient une migration : sauvegarde manuelle
(`sudo bash scripts/backup_db.sh`, voir « Sauvegardes ») et repères pour
le retour arrière (tag git et tag de l'image `web`). La procédure pas à pas
d'un lot, retour arrière compris, est livrée avec le lot.

Au démarrage, le service ponctuel `sauvegarde-migrations` sauvegarde
d'abord la base si une migration est en attente
(`avant_migration_*.sql.gz` dans `KAIROS_BACKUP_DIR`, défaut `./backups`) ;
s'il échoue, `web` ne démarre pas et rien n'est migré. Il apparaît ensuite
« Exited (0) » dans `docker compose ps -a` : c'est normal.

`flask migrer` (voir `migrations/`) applique les changements de schéma
qui ne sont pas déjà dans `schema.sql` d'une installation neuve —
renommage d'une équipe, nouvelle colonne, etc. Depuis le 2026-09-29, le
conteneur `web` la lance lui-même à chaque démarrage, AVANT de servir
l'appli (voir le `CMD` du Dockerfile) : une mise à jour faite depuis
l'interface d'un NAS, sans terminal, applique donc aussi les migrations.
La commande manuelle reste utile pour voir ce qui a été appliqué ; elle
ne fait rien si tout est déjà à jour et peut être relancée sans risque.

Si une migration échoue, le conteneur `web` ne démarre pas (il
redémarre en boucle) : l'erreur se lit dans `docker compose logs web`.
Avant cette date, l'ordre comptait : entre le `--build` et la migration,
plus personne ne pouvait se connecter.

### Dépannage : "Permission denied" sur l'upload d'une photo/pièce jointe

Si l'ajout d'une photo de profil (ou d'une pièce jointe) échoue avec une
erreur `PermissionError: [Errno 13] Permission denied` dans les logs
(`docker compose logs web`), c'est que le volume des pièces jointes
appartient à `root` alors que l'appli tourne avec un utilisateur non-root
(`appuser`, par sécurité) — typique d'un volume créé avant le correctif
du Dockerfile du 2026-09-20. Se corrige une seule fois, sans perte de
données (dans un conteneur ponctuel : depuis le lot 10, le conteneur `web`
tourne sans aucune capacité Linux, `cap_drop: ALL`, et même `root` n'y
peut plus changer de propriétaire ; l'image `postgres:16` est déjà
présente sur la machine, `1000` est l'UID d'`appuser`) :

```bash
sudo docker run --rm -v kairos_uploads:/u --entrypoint chown postgres:16 -R 1000:1000 /u
```

### Dépannage : renommage des volumes Docker (workflowbook → Kairos, 2026-09-21)

`docker-compose.yml` nomme désormais les volumes `kairos_pgdata` et
`kairos_uploads` (avant : `workflowbook_pgdata`/`workflowbook_uploads`).
Un nom de volume différent est traité par Docker comme un **volume tout
neuf et vide** — sur une installation déjà en place, il faut donc migrer
les données une seule fois, AVANT de faire `git pull` sur cette mise à
jour, sous peine de démarrer avec une base et des pièces jointes
apparemment vides (les anciennes données ne sont pas perdues, juste plus
utilisées par l'appli) :

```bash
cd /chemin/vers/le/dossier/de/l-appli   # ex. /mnt/Pool/Kairos sur TrueNAS

# 1. Repérer les noms exacts des volumes actuels
docker volume ls | grep -i workflowbook

# 2. Arrêter les conteneurs SANS supprimer les volumes (pas de -v !)
sudo docker compose down

# 3. Créer les deux nouveaux volumes et y copier les données des anciens
#    (remplacer <ancien_pgdata>/<ancien_uploads> par les noms trouvés à
#    l'étape 1, ex. kairos_workflowbook_pgdata)
sudo docker volume create kairos_pgdata
sudo docker volume create kairos_uploads
sudo docker run --rm -v <ancien_pgdata>:/from -v kairos_pgdata:/to alpine sh -c "cp -a /from/. /to/"
sudo docker run --rm -v <ancien_uploads>:/from -v kairos_uploads:/to alpine sh -c "cp -a /from/. /to/"

# 4. Seulement maintenant : récupérer cette mise à jour et redémarrer
git pull
sudo docker compose up -d --build
docker compose exec web flask migrer
```

Une fois l'appli vérifiée (connexion, données, pièces jointes toutes
présentes), les anciens volumes peuvent être supprimés pour libérer la
place : `docker volume rm <ancien_pgdata> <ancien_uploads>`. Pas d'urgence
à le faire — ils ne gênent rien tant qu'ils sont là.

## Sauvegardes

`scripts/backup_db.sh` fait un `pg_dump` compressé de la base **et** une
archive des pièces jointes (volume `kairos_uploads`) dans
`KAIROS_BACKUP_DIR` (variable d'environnement ou ligne du `.env` ; défaut
`./backups/`, dans la copie de travail — à éviter : un `git clean` ou le
partage SMB peuvent l'effacer). Fichiers lisibles par leur seul
propriétaire (root via `sudo` ou le cron) : lancer les scripts avec `sudo`.
(30 dernières copies conservées, le reste est supprimé automatiquement,
sous le préfixe `kairos_` depuis le 2026-09-21 — les anciens fichiers
`workflowbook_*.sql.gz` restent sur disque mais ne sont plus comptés dans
ce nettoyage automatique, à supprimer à la main si besoin). À planifier
une fois par jour via **TrueNAS SCALE > Système > Tâches planifiées
(Cron Jobs)**, utilisateur root, commande (`bash` devant : ne dépend pas
du bit exécutable, fragile sur le partage SMB) :

```
KAIROS_BACKUP_DIR=/mnt/Pool/sauvegardes/kairos bash /mnt/Pool/Kairos/scripts/backup_db.sh
```

Sans ça, toutes les données (projets, tâches, heures, historique) ne
vivent que dans un seul volume Docker sur ce NAS. Les sauvegardes restent
elles aussi sur ce NAS : copiez régulièrement le dossier de sauvegarde
ailleurs (autre disque, autre machine), sinon un disque mort emporte tout.

### Restaurer une sauvegarde

```bash
sudo bash scripts/restore_db.sh /mnt/Pool/sauvegardes/kairos/kairos_AAAA-MM-JJ_HHMM.sql.gz \
    /mnt/Pool/sauvegardes/kairos/kairos_uploads_AAAA-MM-JJ_HHMM.tar.gz
```

Le script refuse une archive corrompue ou un dump incomplet AVANT de
toucher à quoi que ce soit, demande confirmation (taper `RESTAURER` ;
`--oui` en premier argument la saute), arrête `web`, fait une copie de
sécurité de la base actuelle (`avant_restauration_*.sql.gz`), recharge le
dump en UNE transaction (à la moindre erreur, la base reste telle
qu'avant), restaure les pièces jointes, puis redémarre `web`, qui applique
lui-même les migrations plus récentes que la sauvegarde (précédées de la
sauvegarde automatique de `sauvegarde-migrations`). Pour revenir à une
version PRÉCÉDENTE de l'appli, remettre d'abord l'ancien code et l'ancienne
image : sinon la nouvelle image rejoue aussitôt ses migrations sur la base
restaurée (voir la procédure de retour arrière du lot). Il fonctionne aussi sur une
installation toute neuve (`docker compose up` vient de créer une base
vide avec `schema.sql`) — c'est exactement le cas "le disque est mort,
je repars de zéro". **Remplace toutes les données actuelles.** Testez-le
de temps en temps sur une machine de test : une sauvegarde jamais
restaurée n'est pas une sauvegarde vérifiée.

## Migration des données depuis l'ancien Kairos (MySQL "chronos")

`scripts/migrate_from_chronos.py` transforme un export mysqldump de
l'ancien Kairos (table `chronos`) en un fichier SQL prêt à charger dans
la nouvelle base Postgres. Pensé pour être rejoué plusieurs fois (à
chaque nouvel export), sans rien modifier à la main : aucune dépendance
à installer (Python standard uniquement), pas besoin d'un serveur MySQL.

```
python3 scripts/migrate_from_chronos.py chronos_AAAAMMJJHHMM.sql \
    --out-dir migration_sorties/2026-09-21
```

Produit trois fichiers dans le dossier de sortie (**jamais commités dans
git**, voir `.gitignore`) :
- `migration.sql` — à rejouer sur une base **fraîche** (schema.sql tout
  juste appliqué, aucune donnée métier existante) :
  `docker compose exec -T db psql -v ON_ERROR_STOP=1 -U kairos -d kairos < migration_sorties/2026-09-21/migration.sql`
  (`ON_ERROR_STOP=1` : sans ça, une erreur au milieu annule tout le
  chargement mais la commande se termine quand même "avec succès")
- `identifiants_NE_PAS_COMMITER.csv` — un mot de passe temporaire par
  personne migrée, à transmettre **en main propre** (jamais par email) ;
  à supprimer une fois distribué.
- `rapport.md` — le détail des choix faits automatiquement (emails
  anonymisés en `nom_prenom@kairos.tn`, rôles, dates, etc.) et des
  lignes qui n'ont pas pu être migrées, avec la raison.

Les deux scripts (reprise complète et `scripts/recharger_projets_chronos.py`,
rechargement des projets et tâches sans toucher aux comptes) appliquent la
même cohérence des états (lot 11) : une tâche En cours ou Bloquée d'un
projet Terminé devient Terminée (Abandonnée si le projet est Abandonné), un
projet ouvert est Bloqué si et seulement si une de ses tâches l'est. Le
rechargement exige une base à jour (migration 0016) et signale les projets
ouverts sans tâche ouverte et ceux dont le chef est désactivé.

Volontairement laissé hors périmètre (pas encore modélisé en étape 1) :
Congés/Télétravail, notifications historiques, jours fériés, sessions,
jetons de réinitialisation — voir le rapport généré pour le détail.

## Déploiement sur un Synology (Container Manager)

Marche à suivre pour un DS720+ ou équivalent, DSM 7.2+ :

1. **Vérifier les prérequis** — Panneau de configuration > Terminal & SNMP :
   activer SSH. Centre de paquets : installer **Container Manager** s'il
   ne l'est pas déjà.
2. **Copier le dossier `kairos-app`** sur le NAS, par exemple dans
   `/volume1/docker/kairos/` — le plus simple : File Station >
   glisser-déposer le `.zip` reçu, puis clic droit > Extraire ici.
3. **Créer le fichier `.env`** dans ce dossier (copie de `.env.example`
   avec de vraies valeurs pour `POSTGRES_PASSWORD` et `SECRET_KEY`) —
   éditable directement depuis File Station (Text Editor) ou par SSH.
4. **Lancer les conteneurs**, deux façons possibles :
   - **Sans terminal (le plus simple)** : Container Manager > Projet >
     Créer > donner un nom, pointer sur le dossier
     `/volume1/docker/kairos/`, DSM détecte `docker-compose.yml`
     automatiquement > Suivant > Construire.
   - **Par SSH**, si tu préfères la ligne de commande :
     ```bash
     ssh <utilisateur>@192.168.1.45
     cd /volume1/docker/kairos
     sudo docker compose up -d --build
     ```
5. **Créer le premier compte** (admin), par SSH obligatoirement (pas
   d'équivalent GUI) :
   ```bash
   sudo docker compose exec web flask create-user \
     --email fadhel@midgard.tn --prenom Fadhel --nom Chemmem \
     --password "un-mot-de-passe-solide" --role admin
   ```
6. **Ouvrir** `http://192.168.1.45:8000/` — l'écran de connexion doit
   s'afficher.

Aucune commande ci-dessus ne demande de mot de passe à l'IA qui a écrit
ce guide : SSH, DSM et Container Manager restent toujours saisis/pilotés
par toi.

## Démarrer en local sans Docker (développement)

Nécessite un PostgreSQL local et les dépendances Python (`pip install -r
requirements.txt`) — voir la note ci-dessous sur l'environnement où ce
code a été écrit.

```bash
createdb kairos
psql kairos -f schema.sql
export DATABASE_URL=postgresql://localhost/kairos
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export UPLOAD_DIR=$PWD/uploads
export FLASK_APP=wsgi.py
export FLASK_ENV=development
flask create-user --email test@midgard.tn --prenom Test --nom Utilisateur --password test1234
flask run
```

## Tests

| Suite | Commande | Base réelle |
|---|---|---|
| Fumée et unitaires (psycopg2 simulé) | `python3 -m unittest discover -s tests` | non (9 tests sautés sans `KAIROS_TEST_DATABASE_URL`) |
| Intégration (vrai SQL, vrai psycopg2) | `KAIROS_TEST_DATABASE_URL=postgresql://kairos:kairos@127.0.0.1:5432/kairos_it python3 -m unittest discover -s tests_integration -t .` | oui : base chargée avec `schema.sql` + `migrations/` |
| SQL | `psql -d <base> -v ON_ERROR_STOP=1 -f tests/sql/<fichier>.sql` | oui |
| JavaScript | `node --test tests_js/*.test.mjs` | non |
| Scénarios navigateur (Playwright) | `bash tests_e2e/lancer.sh` (Daily log), `KAIROS_E2E_SCENARIO=projet bash tests_e2e/lancer.sh` (fiche projet) | oui (base jetable) ; non lancés par la CI |

Ne jamais lancer `tests_integration/` dans le même processus que `tests/`
(qui installe un faux psycopg2). Sous Windows, les 8 tests de
`test_backup_db` exigent `bash` et échouent : c'est attendu.

La CI (`.github/workflows/tests.yml`, à chaque push sur `master` et à
chaque pull request) joue : unitaires ; migrations publiées inchangées ;
schéma neuf = schéma migré = schéma « comme en production » et
`tests/sql` sur les trois ; intégration et scripts de sauvegarde /
restauration sur PostgreSQL 16 ; shellcheck et tests JavaScript ;
déploiement Docker complet avec sauvegarde puis restauration.

## Structure du projet

```
app/
  __init__.py       point d'entrée (create_app), commande CLI create-user
  config.py         configuration (variables d'environnement)
  db.py             pool de connexions + mécanisme app.current_user_id
  auth.py           connexion/déconnexion (POST, protégée CSRF), hachage mot de passe
  utils.py          helpers d'affichage (avatars, pills, dates relatives, calcul du Gantt Deadlines)
  storage.py        stockage des pièces jointes sur disque (UPLOAD_DIR)
  repositories/     tout le SQL, une fonction = une requête (ou une petite transaction)
  routes/           les vues Flask (accueil, projets, posts, dailylog, deadlines, fichiers, utilisateurs, notifications)
  templates/        Jinja2, porté fidèlement des maquettes .dc.html
  static/           CSS partagé, JS (sélecteur à puces, composeur de post, Daily log) + logo Kairos
schema.sql          schéma canonique (source de vérité, appliqué tel quel à l'installation)
migrations/         changements de schéma à appliquer sur une base déjà en place (`flask migrer`)
scripts/            exploitation : backup_db.sh, restore_db.sh, sauvegarde_avant_migration.sh,
                    empreinte_schema.sql (CI), migrate_from_chronos.py (+ mysqldump_parser.py)
tests/              tests de fumée (rendu des pages) + tests unitaires purs + tests/sql
tests_integration/  tests sur vrai PostgreSQL (KAIROS_TEST_DATABASE_URL)
tests_js/           tests JavaScript (node --test)
tests_e2e/          scénario Playwright du Daily log
.github/workflows/  CI (tests automatiques à chaque push/pull request)
docker-compose.yml, Dockerfile, gunicorn.conf.py, .env.example
```

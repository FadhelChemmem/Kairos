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
  automatique et son tag, comme décidé).
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
  équipe.
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
- **DailyLog façon curseur** (`/dailylog`) : répartition visuelle des
  heures de la journée par glisser-déposer, catalogue d'ajout de ligne,
  calendrier de navigation, sauvegarde explicite de toute la journée.
- **Notifications** : cloche dans la barre du haut avec compteur temps
  réel, page `/notifications`, déclenchées par mention (post/commentaire),
  affectation à une tâche, ajout comme intervenant, et rappel automatique
  si le DailyLog de la veille n'a pas été rempli.

**Reste à construire** (étape 2, plus tard) : RH, Congés/Télétravail,
rôle Client, fil "Information" hors-projet ciblé par équipe.

## Démarrer avec Docker (recommandé)

```bash
cp .env.example .env
# éditer .env : POSTGRES_PASSWORD et SECRET_KEY (voir les commentaires dans le fichier)

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

## Mettre à jour (après un `git pull`)

```bash
git pull
docker compose up -d --build
docker compose exec web flask migrer
```

`flask migrer` (voir `migrations/`) applique les changements de schéma
qui ne sont pas déjà dans `schema.sql` d'une installation neuve —
renommage d'une équipe, nouvelle colonne, etc. C'est la seule commande à
ne pas oublier ; elle ne fait rien si tout est déjà à jour, et peut être
relancée sans risque. L'ordre avec `docker compose up -d --build`
n'a pas d'importance particulière, mais autant prendre l'habitude de
toujours lancer la migration juste après.

### Dépannage : "Permission denied" sur l'upload d'une photo/pièce jointe

Si l'ajout d'une photo de profil (ou d'une pièce jointe) échoue avec une
erreur `PermissionError: [Errno 13] Permission denied` dans les logs
(`docker compose logs web`), c'est que le volume des pièces jointes
appartient à `root` alors que l'appli tourne avec un utilisateur non-root
(`appuser`, par sécurité) — typique d'un volume créé avant le correctif
du Dockerfile du 2026-09-20. Se corrige une seule fois, sans perte de
données :

```bash
docker compose exec -u root web chown -R appuser:appuser /app/uploads
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

`./scripts/backup_db.sh` fait un `pg_dump` compressé dans `./backups/`
(30 dernières copies conservées, le reste est supprimé automatiquement,
sous le préfixe `kairos_` depuis le 2026-09-21 — les anciens fichiers
`workflowbook_*.sql.gz` restent sur disque mais ne sont plus comptés dans
ce nettoyage automatique, à supprimer à la main si besoin). À planifier
une fois par jour via **TrueNAS SCALE > Système > Tâches planifiées
(Cron Jobs)**, commande :

```
/chemin/vers/kairos-app/scripts/backup_db.sh
```

Sans ça, toutes les données (projets, tâches, heures, historique) ne
vivent que dans un seul volume Docker sur ce NAS.

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
  `docker compose exec -T db psql -U kairos -d kairos -f /chemin/vers/migration.sql`
- `identifiants_NE_PAS_COMMITER.csv` — un mot de passe temporaire par
  personne migrée, à transmettre **en main propre** (jamais par email) ;
  à supprimer une fois distribué.
- `rapport.md` — le détail des choix faits automatiquement (emails
  anonymisés en `nom_prenom@kairos.tn`, rôles, dates, etc.) et des
  lignes qui n'ont pas pu être migrées, avec la raison.

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
export SECRET_KEY=dev
export FLASK_APP=wsgi.py
export FLASK_ENV=development
flask create-user --email test@midgard.tn --prenom Test --nom Utilisateur --password test1234
flask run
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

113 tests au total, tous verts (lancés automatiquement sur GitHub à
chaque push/pull request, voir `.github/workflows/tests.yml`). Ces tests
ne nécessitent PAS de base de
données réelle : ils simulent psycopg2 et remplacent les fonctions de
repository par des données de test, pour vérifier que les pages se
construisent sans erreur (Jinja2, routage, `url_for`) — c'est le risque
principal sur du code jamais exécuté de bout en bout dans cet
environnement. La logique SQL elle-même (transactions, upserts, requêtes
du fil, contraintes RH/équipe, notifications) a été validée séparément,
en conditions réelles, sur un PostgreSQL 16 local à chaque fonctionnalité
livrée — voir les sections "Implémentation" de la spec pour le détail
des scénarios rejoués.

**Note de transparence :** ce code a été écrit dans un environnement où
psycopg2 (le pilote PostgreSQL pour Python) ne peut pas être installé
(accès réseau restreint côté pip/apt) — il n'a donc jamais pu tourner de
bout en bout, avec sa vraie configuration Docker/gunicorn, avant cette
livraison. Ton premier `docker compose up` sera le premier run réel de
l'application complète telle qu'elle sera réellement déployée. Le risque
a été limité au maximum : le schéma et toutes les requêtes SQL un peu
sensibles ont été rejouées, en réel, via `psql` (pas juste relues) à
chaque fonctionnalité ; l'assemblage Flask/Jinja2/routes est couvert par
les tests ci-dessus. Si quelque chose casse au premier démarrage, ce sera
très probablement un détail d'environnement (variable manquante, port
déjà utilisé) plutôt qu'un problème de fond dans le code.

## Structure du projet

```
app/
  __init__.py       point d'entrée (create_app), commande CLI create-user
  config.py         configuration (variables d'environnement)
  db.py             pool de connexions + mécanisme app.current_user_id
  auth.py           connexion/déconnexion, hachage mot de passe
  utils.py          helpers d'affichage (avatars, pills, dates relatives, calcul du Gantt Deadlines)
  storage.py        stockage des pièces jointes sur disque (UPLOAD_DIR)
  repositories/     tout le SQL, une fonction = une requête (ou une petite transaction)
  routes/           les vues Flask (accueil, projets, posts, dailylog, deadlines, fichiers, utilisateurs, notifications)
  templates/        Jinja2, porté fidèlement des maquettes .dc.html
  static/           CSS partagé + logo Kairos
schema.sql          schéma canonique (source de vérité, appliqué tel quel à l'installation)
migrations/         changements de schéma à appliquer sur une base déjà en place (`flask migrer`)
scripts/            scripts d'exploitation (backup_db.sh)
tests/              tests de fumée (rendu des pages) + tests unitaires purs
.github/workflows/  CI (tests automatiques à chaque push/pull request)
docker-compose.yml, Dockerfile, .env.example
```

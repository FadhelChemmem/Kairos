-- =====================================================================
-- Kairos — schema de base de données (étape 1)
-- PostgreSQL 14+
--
-- Portée : Projets, Tâches, DailyLog, Posts (fil d'activité, y compris
-- Requêtes en tant que type de post), Utilisateurs.
-- Hors périmètre étape 1 (colonnes/tables prévues mais non utilisées) :
-- Congé/Télétravail, Notifications RH, posts hors-projet (RH/Information),
-- rôle Client, Honoraires.
--
-- Choix de conception :
--  - ENUM Postgres pour les listes fermées et stables (phase, état projet,
--    état tâche, type de deadline, rôle utilisateur).
--  - Table de référence (au lieu d'ENUM) pour tout ce qui est amené à
--    s'étendre sans migration lourde : lot (CM/GO/...), équipe/bureau
--    (Midgard/URBS/SS/Q/IPCO/...), type de post (Envoi/Réponse/Question/
--    Requête/[Information]), type de réaction.
--  - "heures cumulées" (projet et tâche) ne sont PAS des colonnes stockées :
--    ce sont des vues calculées à partir du DailyLog, pour éviter toute
--    désynchronisation. Voir v_projet_heures / v_tache_heures en bas.
--  - Le code projet (ex. "24091X") reste semi-automatique côté application
--    (proposition modifiable) ; la base se contente de le garantir UNIQUE.
--  - Traçabilité : chaque table métier a created_by/updated_by, et TOUTE
--    modification (INSERT/UPDATE/DELETE) est aussi journalisée dans
--    audit_log, consultable par l'admin et utile pour le débogage.
--    Ce mécanisme repose sur UNE seule chose côté application : définir,
--    au début de chaque requête/transaction, une variable de session avec
--    l'id de l'utilisateur connecté :
--        SET LOCAL app.current_user_id = '42';
--    Cette unique ligne alimente automatiquement updated_by ET audit_log
--    (voir set_updated_at_and_by() et fn_audit_log() ci-dessous). Sans
--    cette variable définie, les colonnes/lignes correspondantes restent
--    simplement NULL (pas d'erreur).
--
-- Ajouté 2026-09-16 (règles de rôle validées avec Fadhel) :
--  - RH est un rôle singleton : au plus un compte ACTIF avec role='rh' à
--    la fois (idx_utilisateur_rh_singleton, index partiel). Désactiver le
--    titulaire libère le rôle pour quelqu'un d'autre.
--  - "Chaque personne a un seul rôle" est déjà garanti par construction
--    (une seule colonne role, pas de table de jointage rôle<->personne).
--  - Le RH ne peut être ni chef de projet, ni co-chef, ni intervenant
--    (projet ou tâche) : posé en triggers (fn_check_role_non_rh et les
--    trois triggers trg_check_*_role), pas seulement côté appli.
--  - Visibilité des projets par équipe : projet.equipe_code (nouvelle
--    colonne) + vue v_projet_visibilite, voir tout en bas du fichier.
-- =====================================================================


-- ---------------------------------------------------------------------
-- Fonction utilitaire : mise à jour automatique de updated_at/updated_by
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at_and_by()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  BEGIN
    NEW.updated_by = current_setting('app.current_user_id', true)::BIGINT;
  EXCEPTION WHEN OTHERS THEN
    NEW.updated_by = NULL;
  END;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- =====================================================================
-- ENUMS
-- =====================================================================

-- Phase du projet (APS/APD partagent la lettre "P" dans le code projet,
-- DCE -> "D", EXE -> "X", DOE -> "E" ; ce mapping reste géré côté appli)
CREATE TYPE phase_enum AS ENUM ('APS', 'APD', 'DCE', 'EXE', 'DOE');

-- État global d'un projet
CREATE TYPE projet_etat_enum AS ENUM ('en_cours', 'bloque', 'termine', 'abandonne');

-- État d'une tâche
CREATE TYPE tache_etat_enum AS ENUM (
  'en_cours', 'termine', 'verifie', 'arret', 'abandonne', 'bloque'
);

-- Type de deadline d'une tâche : tag interne servant à ce que le
-- co-traitant IPCO ne se trompe pas sur ce qui part réellement au client.
-- N'entraîne aucune logique particulière au-delà du tag / de la couleur
-- sur la vue calendaire (#interne).
CREATE TYPE type_deadline_enum AS ENUM ('rendu_client', 'interne');

-- Rôle utilisateur. RH et Client existent dans l'énum dès étape 1 pour
-- éviter une migration future, mais ne sont pas exploités avant l'étape 2.
CREATE TYPE role_enum AS ENUM ('admin', 'chef_de_projet', 'intervenant', 'rh', 'client');


-- =====================================================================
-- TABLES DE RÉFÉRENCE (extensibles sans migration de type)
-- =====================================================================

-- Bureaux / entités du groupe (Midgard, URBS, SS, Q, IPCO, ...)
-- ISBG renommé en URBS + ajout d'IPCO (retour Fadhel, 2026-09-20) — sur une
-- base déjà installée, ce INSERT ne joue aucun rôle (il ne tourne qu'à la
-- création du schéma) : voir la migration correspondante à lancer à la main.
CREATE TABLE equipe (
  code       VARCHAR(20) PRIMARY KEY,
  libelle    VARCHAR(100) NOT NULL,
  actif      BOOLEAN NOT NULL DEFAULT true
);
INSERT INTO equipe (code, libelle) VALUES
  ('MIDGARD', 'Midgard'),
  ('URBS',    'URBS'),
  ('SS',      'SS'),
  ('Q',       'Q'),
  ('IPCO',    'IPCO');

-- Lots techniques (CM = Charpente Métallique, GO = Gros Œuvre, ...)
CREATE TABLE lot (
  code       VARCHAR(20) PRIMARY KEY,
  libelle    VARCHAR(100) NOT NULL,
  actif      BOOLEAN NOT NULL DEFAULT true
);
INSERT INTO lot (code, libelle) VALUES
  ('CM', 'Charpente Métallique'),
  ('GO', 'Gros Œuvre');

-- Types de post ("tags", au sens de Fadhel : catégorisation, pas de
-- logique dédiée). Information est réservé à l'étape 2 (posts RH /
-- hors-projet) et désactivé pour l'instant.
CREATE TABLE post_type (
  code       VARCHAR(20) PRIMARY KEY,
  libelle    VARCHAR(100) NOT NULL,
  actif      BOOLEAN NOT NULL DEFAULT true
);
INSERT INTO post_type (code, libelle, actif) VALUES
  ('envoi',       'Envoi',       true),
  ('reponse',     'Réponse',     true),
  ('question',    'Question',    true),
  ('requete',     'Requête',     true),
  ('information', 'Information', false); -- étape 2

-- Types de réaction sur un post (façon réseau social)
CREATE TABLE reaction_type (
  code       VARCHAR(20) PRIMARY KEY,
  libelle    VARCHAR(50) NOT NULL
);
INSERT INTO reaction_type (code, libelle) VALUES
  ('ok',    'OK / validé'),
  ('pouce', 'Pouce levé');


-- =====================================================================
-- UTILISATEUR
-- =====================================================================
CREATE TABLE utilisateur (
  id               BIGSERIAL PRIMARY KEY,
  email            VARCHAR(255) NOT NULL, -- unicité gérée par idx_utilisateur_email_lower (insensible à la casse), voir plus bas
  mot_de_passe_hash VARCHAR(255) NOT NULL,
  nom              VARCHAR(100) NOT NULL,
  prenom           VARCHAR(100) NOT NULL,
  telephone        VARCHAR(30),
  poste            VARCHAR(150),           -- intitulé libre ("Ingénieur", "Technicien"...)
  adresse          TEXT,
  date_embauche    DATE,
  equipe_code      VARCHAR(20) REFERENCES equipe(code),
  role             role_enum NOT NULL DEFAULT 'intervenant',
  verifie          BOOLEAN NOT NULL DEFAULT false,  -- email vérifié
  actif            BOOLEAN NOT NULL DEFAULT true,   -- false = a quitté l'entreprise (historique conservé)
  champs_perso     JSONB NOT NULL DEFAULT '{}'::jsonb, -- champs additionnels libres ("rajouter des champs")
  avatar_chemin    TEXT, -- photo de profil (chemin relatif sous UPLOAD_DIR, voir app/storage.py) ; NULL = avatar par défaut (initiales), voir app/routes/fichiers.py:avatar
  reset_token_hash        VARCHAR(64), -- empreinte SHA-256 du jeton "mot de passe oublié" envoyé par email (jamais le jeton en clair) ; NULL = pas de réinitialisation en cours
  reset_token_expires_at  TIMESTAMPTZ, -- le jeton n'est valable qu'avant cette date (1h, voir app/auth.py) ; à usage unique, effacé dès qu'il sert
  created_by       BIGINT REFERENCES utilisateur(id), -- admin qui a créé la fiche (NULL pour le tout premier compte)
  updated_by       BIGINT REFERENCES utilisateur(id),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_utilisateur_updated_at
  BEFORE UPDATE ON utilisateur
  FOR EACH ROW EXECUTE FUNCTION set_updated_at_and_by();

CREATE INDEX idx_utilisateur_actif ON utilisateur(actif);
CREATE INDEX idx_utilisateur_equipe ON utilisateur(equipe_code);

-- Unicité de l'email insensible à la casse (sans ça, "Fadhel@..." et
-- "fadhel@..." seraient deux comptes différents). L'appli doit comparer/
-- chercher par lower(email) pour que ce soit cohérent au login.
CREATE UNIQUE INDEX idx_utilisateur_email_lower ON utilisateur (lower(email));

-- Rôle RH singleton (2026-09-16) : un seul compte ACTIF peut porter le
-- rôle RH à la fois (l'Admin cumule les droits du RH mais n'occupe pas
-- "la place" du rôle RH — index partiel, ne compte que role='rh').
-- Désactiver le titulaire actuel (actif=false) libère automatiquement
-- le rôle pour quelqu'un d'autre, sans rien à faire de plus.
CREATE UNIQUE INDEX idx_utilisateur_rh_singleton ON utilisateur (role) WHERE role = 'rh' AND actif = true;


-- =====================================================================
-- PROJET
-- =====================================================================
CREATE TABLE projet (
  id               BIGSERIAL PRIMARY KEY,
  code             VARCHAR(20) NOT NULL UNIQUE, -- ex. "24091X" — proposé semi-auto, éditable
  nom              VARCHAR(200) NOT NULL,
  phase            phase_enum NOT NULL,
  date_debut       DATE,
  date_fin         DATE,                    -- renseigné à la clôture
  etat             projet_etat_enum NOT NULL DEFAULT 'en_cours',
  chef_projet_id   BIGINT NOT NULL REFERENCES utilisateur(id),
  phase_liee_id    BIGINT REFERENCES projet(id), -- ex. le 24091X (EXE) pointe vers le 24091D (DCE)
  equipe_code      VARCHAR(20) REFERENCES equipe(code), -- équipe "propriétaire" du projet, pour la visibilité (2026-09-16, voir plus bas) ; proposée automatiquement (équipe du chef de projet) à la création, modifiable
  honoraires       NUMERIC(12,2),           -- réservé, non exploité en étape 1
  created_by       BIGINT REFERENCES utilisateur(id),
  updated_by       BIGINT REFERENCES utilisateur(id),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_projet_updated_at
  BEFORE UPDATE ON projet
  FOR EACH ROW EXECUTE FUNCTION set_updated_at_and_by();

CREATE INDEX idx_projet_etat ON projet(etat);
CREATE INDEX idx_projet_chef ON projet(chef_projet_id);
CREATE INDEX idx_projet_phase_liee ON projet(phase_liee_id);
CREATE INDEX idx_projet_equipe ON projet(equipe_code);

-- Lots d'un projet (plusieurs possibles, ex. CM + GO)
CREATE TABLE projet_lot (
  projet_id  BIGINT NOT NULL REFERENCES projet(id) ON DELETE CASCADE,
  lot_code   VARCHAR(20) NOT NULL REFERENCES lot(code),
  PRIMARY KEY (projet_id, lot_code)
);

-- Chef(s) de projet additionnels ("co-chef") — le chef principal reste
-- projet.chef_projet_id ; cette table porte les co-chefs qui obtiennent
-- les mêmes droits (dont la création de tâches) sur ce projet.
CREATE TABLE projet_co_chef (
  projet_id      BIGINT NOT NULL REFERENCES projet(id) ON DELETE CASCADE,
  utilisateur_id BIGINT NOT NULL REFERENCES utilisateur(id),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (projet_id, utilisateur_id)
);

-- Intervenants affectés au projet (vue "Intervenants" de la page projet)
CREATE TABLE projet_intervenant (
  projet_id      BIGINT NOT NULL REFERENCES projet(id) ON DELETE CASCADE,
  utilisateur_id BIGINT NOT NULL REFERENCES utilisateur(id),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (projet_id, utilisateur_id)
);
CREATE INDEX idx_projet_intervenant_user ON projet_intervenant(utilisateur_id);

-- ---------------------------------------------------------------------
-- Contrainte métier (2026-09-16) : un utilisateur avec le rôle RH ne
-- peut être ni chef de projet, ni co-chef, ni intervenant — chaque
-- personne n'a qu'un seul rôle, et le RH est dédié à son rôle. Garanti
-- au niveau base (pas seulement applicatif) pour ne jamais dépendre
-- d'un oubli côté code. Les triggers équivalents pour les intervenants
-- de tâche sont posés juste après la table tache_intervenant plus bas.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_check_role_non_rh(p_utilisateur_id BIGINT, p_contexte TEXT)
RETURNS VOID AS $$
DECLARE
  v_role role_enum;
BEGIN
  SELECT role INTO v_role FROM utilisateur WHERE id = p_utilisateur_id;
  IF v_role = 'rh' THEN
    RAISE EXCEPTION 'Un utilisateur avec le rôle RH ne peut pas être % (utilisateur id=%).', p_contexte, p_utilisateur_id;
  END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_check_projet_chef_role()
RETURNS TRIGGER AS $$
BEGIN
  PERFORM fn_check_role_non_rh(NEW.chef_projet_id, 'chef de projet');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_check_projet_chef_role
  BEFORE INSERT OR UPDATE OF chef_projet_id ON projet
  FOR EACH ROW EXECUTE FUNCTION fn_check_projet_chef_role();

CREATE OR REPLACE FUNCTION fn_check_projet_co_chef_role()
RETURNS TRIGGER AS $$
BEGIN
  PERFORM fn_check_role_non_rh(NEW.utilisateur_id, 'co-chef de projet');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_check_projet_co_chef_role
  BEFORE INSERT OR UPDATE ON projet_co_chef
  FOR EACH ROW EXECUTE FUNCTION fn_check_projet_co_chef_role();

CREATE OR REPLACE FUNCTION fn_check_projet_intervenant_role()
RETURNS TRIGGER AS $$
BEGIN
  PERFORM fn_check_role_non_rh(NEW.utilisateur_id, 'intervenant');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_check_projet_intervenant_role
  BEFORE INSERT OR UPDATE ON projet_intervenant
  FOR EACH ROW EXECUTE FUNCTION fn_check_projet_intervenant_role();


-- =====================================================================
-- TÂCHE
-- =====================================================================
CREATE TABLE tache (
  id               BIGSERIAL PRIMARY KEY,
  -- PAS de ON DELETE CASCADE ici, volontairement : un projet qui a des
  -- tâches ne doit jamais pouvoir être supprimé "en cascade" par erreur.
  -- Comme pour l'utilisateur (actif/inactif), on désactive un projet
  -- (état = 'abandonne') au lieu de le supprimer ; la contrainte FK sert
  -- de garde-fou technique contre une suppression accidentelle.
  projet_id        BIGINT NOT NULL REFERENCES projet(id),
  titre            VARCHAR(255) NOT NULL,
  etat             tache_etat_enum NOT NULL DEFAULT 'en_cours',
  type_deadline    type_deadline_enum NOT NULL DEFAULT 'rendu_client',
  date_debut       DATE,
  date_echeance    DATE,
  date_fin         DATE,                    -- renseigné à la clôture
  dossier_lien     TEXT,                    -- lien/chemin vers le dossier de pièces
  created_by       BIGINT NOT NULL REFERENCES utilisateur(id),
  updated_by       BIGINT REFERENCES utilisateur(id),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_tache_updated_at
  BEFORE UPDATE ON tache
  FOR EACH ROW EXECUTE FUNCTION set_updated_at_and_by();

CREATE INDEX idx_tache_projet ON tache(projet_id);
CREATE INDEX idx_tache_etat ON tache(etat);
CREATE INDEX idx_tache_echeance ON tache(date_echeance);

-- Intervenant(s) sur une tâche — non requis à la création
CREATE TABLE tache_intervenant (
  tache_id       BIGINT NOT NULL REFERENCES tache(id) ON DELETE CASCADE,
  utilisateur_id BIGINT NOT NULL REFERENCES utilisateur(id),
  PRIMARY KEY (tache_id, utilisateur_id)
);
CREATE INDEX idx_tache_intervenant_user ON tache_intervenant(utilisateur_id);

-- Même contrainte que pour projet_intervenant/co-chef ci-dessus : le RH
-- ne peut pas être intervenant sur une tâche.
CREATE OR REPLACE FUNCTION fn_check_tache_intervenant_role()
RETURNS TRIGGER AS $$
BEGIN
  PERFORM fn_check_role_non_rh(NEW.utilisateur_id, 'intervenant');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_check_tache_intervenant_role
  BEFORE INSERT OR UPDATE ON tache_intervenant
  FOR EACH ROW EXECUTE FUNCTION fn_check_tache_intervenant_role();

-- Pièces jointes d'une tâche
CREATE TABLE tache_piece_jointe (
  id             BIGSERIAL PRIMARY KEY,
  tache_id       BIGINT NOT NULL REFERENCES tache(id) ON DELETE CASCADE,
  nom_fichier    VARCHAR(255) NOT NULL,
  chemin         TEXT NOT NULL,
  uploaded_by    BIGINT NOT NULL REFERENCES utilisateur(id),
  uploaded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_tache_pj_tache ON tache_piece_jointe(tache_id);


-- =====================================================================
-- DAILYLOG
-- =====================================================================
-- Une ligne = les heures qu'un utilisateur a passées un jour donné sur un
-- projet (et, optionnellement, une tâche précise de ce projet). Permet de
-- cibler un projet seul (sans tâche) comme demandé.
CREATE TABLE dailylog_entree (
  id             BIGSERIAL PRIMARY KEY,
  utilisateur_id BIGINT NOT NULL REFERENCES utilisateur(id),
  date           DATE NOT NULL,
  projet_id      BIGINT NOT NULL REFERENCES projet(id),
  tache_id       BIGINT REFERENCES tache(id),  -- NULL = temps passé sur le projet sans tâche précise
  heures         NUMERIC(4,2) NOT NULL CHECK (heures > 0),
  updated_by     BIGINT REFERENCES utilisateur(id), -- normalement = utilisateur_id, sauf correction faite par un admin
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
  -- Pas de contrainte UNIQUE(...) classique ici : en SQL, NULL n'est
  -- jamais égal à NULL, donc UNIQUE(utilisateur_id, date, projet_id,
  -- tache_id) laisserait passer PLUSIEURS lignes "projet seul, sans
  -- tâche" (tache_id NULL) le même jour pour la même personne — exactement
  -- le cas que tu as demandé de permettre. On force donc l'unicité via un
  -- index avec COALESCE (0 = valeur sentinelle, jamais prise par un vrai
  -- id de tâche puisque BIGSERIAL démarre à 1). Voir idx_dailylog_unique
  -- plus bas.
);
CREATE TRIGGER trg_dailylog_updated_at
  BEFORE UPDATE ON dailylog_entree
  FOR EACH ROW EXECUTE FUNCTION set_updated_at_and_by();

CREATE INDEX idx_dailylog_user_date ON dailylog_entree(utilisateur_id, date);
CREATE INDEX idx_dailylog_projet ON dailylog_entree(projet_id);
CREATE INDEX idx_dailylog_tache ON dailylog_entree(tache_id);

-- Une seule ligne par (utilisateur, jour, projet, tâche) — y compris
-- quand tache_id est vide (COALESCE(tache_id, 0) traite alors toutes les
-- lignes "projet seul" du même jour comme le même couple, donc une seule
-- autorisée, modifiable, comme les lignes avec tâche).
CREATE UNIQUE INDEX idx_dailylog_unique
  ON dailylog_entree (utilisateur_id, date, projet_id, COALESCE(tache_id, 0));

-- Un rappel de saisie (notification) est déclenché côté appli quand un
-- utilisateur n'a pas rempli son DailyLog la veille — pas de table dédiée
-- ici, voir la table notification générique plus bas.


-- =====================================================================
-- POST — le fil d'activité unifié
-- =====================================================================
-- projet_id est NULLABLE : un post lié à un projet vit dans son fil ; un
-- post "hors-projet" (RH / info générale) n'a pas de projet — non utilisé
-- avant l'étape 2 mais la colonne est prête.
CREATE TABLE post (
  id             BIGSERIAL PRIMARY KEY,
  projet_id      BIGINT REFERENCES projet(id),
  tache_id       BIGINT REFERENCES tache(id),      -- renseigné si le post vient de la clôture d'une tâche
  parent_post_id BIGINT REFERENCES post(id),        -- "rebondir" : ce post répond à un autre post
  auteur_id      BIGINT NOT NULL REFERENCES utilisateur(id),
  type_code      VARCHAR(20) NOT NULL REFERENCES post_type(code),
  contenu        TEXT,
  lien           TEXT,                              -- lien optionnel (ex. vers le NAS interne), demandé 2026-09-18
  updated_by     BIGINT REFERENCES utilisateur(id), -- si le post est modifié après publication
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER trg_post_updated_at
  BEFORE UPDATE ON post
  FOR EACH ROW EXECUTE FUNCTION set_updated_at_and_by();

CREATE INDEX idx_post_projet_date ON post(projet_id, created_at DESC);
CREATE INDEX idx_post_tache ON post(tache_id);
CREATE INDEX idx_post_parent ON post(parent_post_id);
CREATE INDEX idx_post_type ON post(type_code);

-- Pièces jointes d'un post (ex. le dossier envoyé dans un post "Envoi")
CREATE TABLE post_piece_jointe (
  id             BIGSERIAL PRIMARY KEY,
  post_id        BIGINT NOT NULL REFERENCES post(id) ON DELETE CASCADE,
  nom_fichier    VARCHAR(255) NOT NULL,
  chemin         TEXT NOT NULL,
  uploaded_by    BIGINT REFERENCES utilisateur(id), -- pour cohérence avec tache_piece_jointe
  uploaded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_post_pj_post ON post_piece_jointe(post_id);

-- Personnes taguées sur un post (composeur Requête/Information, demandé
-- 2026-09-18) — distinct de post_commentaire.mentionne_user_id, qui tague
-- une personne dans un commentaire, pas dans le post lui-même.
CREATE TABLE post_mention (
  post_id        BIGINT NOT NULL REFERENCES post(id) ON DELETE CASCADE,
  utilisateur_id BIGINT NOT NULL REFERENCES utilisateur(id),
  PRIMARY KEY (post_id, utilisateur_id)
);
CREATE INDEX idx_post_mention_utilisateur ON post_mention(utilisateur_id);

-- Réactions (une réaction par utilisateur par post, modifiable)
CREATE TABLE post_reaction (
  post_id        BIGINT NOT NULL REFERENCES post(id) ON DELETE CASCADE,
  utilisateur_id BIGINT NOT NULL REFERENCES utilisateur(id),
  reaction_code  VARCHAR(20) NOT NULL REFERENCES reaction_type(code),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (post_id, utilisateur_id)
);

-- Commentaires (façon réseau social), avec possibilité de taguer une personne
CREATE TABLE post_commentaire (
  id                BIGSERIAL PRIMARY KEY,
  post_id           BIGINT NOT NULL REFERENCES post(id) ON DELETE CASCADE,
  auteur_id         BIGINT NOT NULL REFERENCES utilisateur(id),
  contenu           TEXT NOT NULL,
  mentionne_user_id BIGINT REFERENCES utilisateur(id),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_post_commentaire_post ON post_commentaire(post_id);


-- =====================================================================
-- NOTIFICATION (structure minimale — le détail complet est étape 2)
-- =====================================================================
-- Une seule notification + bouton dans l'UI, avec une catégorie qui
-- permet de distinguer "projet/travail" de "autre info & RH" côté
-- affichage, comme décidé avec Fadhel.
CREATE TABLE notification (
  id             BIGSERIAL PRIMARY KEY,
  utilisateur_id BIGINT NOT NULL REFERENCES utilisateur(id),
  categorie      VARCHAR(30) NOT NULL, -- 'projet' | 'rh_info' (ouvert, non contraint en étape 1)
  post_id        BIGINT REFERENCES post(id),
  tache_id       BIGINT REFERENCES tache(id),
  message        TEXT NOT NULL,
  lu             BOOLEAN NOT NULL DEFAULT false,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_notification_user_lu ON notification(utilisateur_id, lu);


-- =====================================================================
-- AUDIT LOG — journal générique de toutes les modifications
-- =====================================================================
-- Table unique qui capture toute création/modification/suppression sur
-- les tables métier ci-dessus, consultable par l'admin (débogage, "qui a
-- fait quoi et quand"). Une ligne = un évènement, avec un instantané
-- JSON avant/après — donc rien n'est perdu même pour les tables de
-- jointure (co-chef, intervenant...) qui n'ont pas de colonne "id" unique.
CREATE TABLE audit_log (
  id             BIGSERIAL PRIMARY KEY,
  table_cible    VARCHAR(50) NOT NULL,   -- ex. 'tache', 'projet', 'post'...
  ligne_id       BIGINT,                 -- id de la ligne concernée, si la table en a un
  action         VARCHAR(10) NOT NULL,   -- 'INSERT' | 'UPDATE' | 'DELETE'
  utilisateur_id BIGINT REFERENCES utilisateur(id), -- qui a fait le changement (via app.current_user_id)
  donnees_avant  JSONB,                  -- ligne complète avant (UPDATE/DELETE)
  donnees_apres  JSONB,                  -- ligne complète après (INSERT/UPDATE)
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_table_ligne ON audit_log(table_cible, ligne_id);
CREATE INDEX idx_audit_user ON audit_log(utilisateur_id);
CREATE INDEX idx_audit_date ON audit_log(created_at DESC);

-- Limite de tentatives (revue sécurité, 2026-09-20) : connexion et "mot de
-- passe oublié" — évite le bourrinage de mots de passe et le spam d'un
-- collègue par emails de réinitialisation. Une ligne = une tentative ;
-- voir app/repositories/securite.py pour la fenêtre glissante (compte les
-- lignes récentes, ne bloque jamais durablement — pas de colonne "jusqu'à
-- telle heure" à gérer).
CREATE TABLE tentative_securite (
  id          BIGSERIAL PRIMARY KEY,
  type        VARCHAR(30) NOT NULL,   -- 'connexion' | 'mot_de_passe_oublie'
  cle         VARCHAR(255) NOT NULL,  -- email normalisé (lower) visé par la tentative
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_tentative_securite_lookup ON tentative_securite (type, cle, created_at);

-- Fonction générique attachée à chaque table à auditer : fonctionne quelle
-- que soit la structure de la table (avec ou sans colonne "id" unique).
CREATE OR REPLACE FUNCTION fn_audit_log()
RETURNS TRIGGER AS $$
DECLARE
  v_user_id BIGINT;
BEGIN
  BEGIN
    v_user_id := current_setting('app.current_user_id', true)::BIGINT;
  EXCEPTION WHEN OTHERS THEN
    v_user_id := NULL;
  END;

  -- Le "-" retire une clé du JSON si elle existe (ne fait rien sinon) :
  -- on retire systématiquement mot_de_passe_hash pour ne JAMAIS stocker
  -- de hash de mot de passe dans le journal d'audit, même historique.
  -- reset_token_hash (2026-09-20) suit la même règle : même si ce n'est
  -- qu'une empreinte d'un jeton à usage unique et de courte durée de vie,
  -- pas de raison de la garder dans un historique.
  IF (TG_OP = 'DELETE') THEN
    INSERT INTO audit_log(table_cible, ligne_id, action, utilisateur_id, donnees_avant)
    VALUES (TG_TABLE_NAME, (to_jsonb(OLD)->>'id')::BIGINT, TG_OP, v_user_id, to_jsonb(OLD) - 'mot_de_passe_hash' - 'reset_token_hash');
    RETURN OLD;
  ELSIF (TG_OP = 'UPDATE') THEN
    INSERT INTO audit_log(table_cible, ligne_id, action, utilisateur_id, donnees_avant, donnees_apres)
    VALUES (TG_TABLE_NAME, (to_jsonb(NEW)->>'id')::BIGINT, TG_OP, v_user_id, to_jsonb(OLD) - 'mot_de_passe_hash' - 'reset_token_hash', to_jsonb(NEW) - 'mot_de_passe_hash' - 'reset_token_hash');
    RETURN NEW;
  ELSIF (TG_OP = 'INSERT') THEN
    INSERT INTO audit_log(table_cible, ligne_id, action, utilisateur_id, donnees_apres)
    VALUES (TG_TABLE_NAME, (to_jsonb(NEW)->>'id')::BIGINT, TG_OP, v_user_id, to_jsonb(NEW) - 'mot_de_passe_hash' - 'reset_token_hash');
    RETURN NEW;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Tables métier auditées (créations/modifications/suppressions/affectations).
-- Les tables de référence (equipe, lot, post_type, reaction_type) ne sont
-- pas auditées ici : elles changent rarement et ne sont pas des
-- "interventions utilisateur" au sens opérationnel — à ajouter facilement
-- de la même façon si besoin.
CREATE TRIGGER trg_audit_utilisateur AFTER INSERT OR UPDATE OR DELETE ON utilisateur FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_projet AFTER INSERT OR UPDATE OR DELETE ON projet FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_projet_lot AFTER INSERT OR UPDATE OR DELETE ON projet_lot FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_projet_co_chef AFTER INSERT OR UPDATE OR DELETE ON projet_co_chef FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_projet_intervenant AFTER INSERT OR UPDATE OR DELETE ON projet_intervenant FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_tache AFTER INSERT OR UPDATE OR DELETE ON tache FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_tache_intervenant AFTER INSERT OR UPDATE OR DELETE ON tache_intervenant FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_tache_piece_jointe AFTER INSERT OR UPDATE OR DELETE ON tache_piece_jointe FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_dailylog AFTER INSERT OR UPDATE OR DELETE ON dailylog_entree FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_post AFTER INSERT OR UPDATE OR DELETE ON post FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_post_piece_jointe AFTER INSERT OR UPDATE OR DELETE ON post_piece_jointe FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_post_mention AFTER INSERT OR UPDATE OR DELETE ON post_mention FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_post_commentaire AFTER INSERT OR UPDATE OR DELETE ON post_commentaire FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
-- post_reaction est volontairement exclue par défaut (très haute fréquence,
-- faible valeur de débogage) — à activer de la même façon si tu la veux :
-- CREATE TRIGGER trg_audit_post_reaction AFTER INSERT OR UPDATE OR DELETE ON post_reaction FOR EACH ROW EXECUTE FUNCTION fn_audit_log();


-- =====================================================================
-- VUES CALCULÉES
-- =====================================================================

-- Heures cumulées par tâche (somme du DailyLog rattaché à la tâche)
CREATE VIEW v_tache_heures AS
SELECT tache_id, SUM(heures) AS heures_cumulees
FROM dailylog_entree
WHERE tache_id IS NOT NULL
GROUP BY tache_id;

-- Heures cumulées par projet (tout le DailyLog du projet, avec ou sans tâche)
CREATE VIEW v_projet_heures AS
SELECT projet_id, SUM(heures) AS heures_cumulees
FROM dailylog_entree
GROUP BY projet_id;

-- Visibilité des projets par équipe (2026-09-16, voir la doc) : un
-- utilisateur voit un projet s'il appartient à la même équipe que le
-- projet, OU s'il y est explicitement rattaché (chef, co-chef,
-- intervenant du projet ou d'une de ses tâches) même hors de son
-- équipe — cas d'une collaboration ponctuelle inter-équipes. Admin et
-- RH voient tout, quelle que soit l'équipe. Une ligne (projet_id,
-- utilisateur_id) = "cet utilisateur peut voir ce projet" ; l'appli
-- filtre ses requêtes de liste de projets avec un JOIN/EXISTS dessus
-- plutôt que de dupliquer cette logique à chaque endroit.
CREATE VIEW v_projet_visibilite AS
SELECT p.id AS projet_id, u.id AS utilisateur_id
FROM projet p
CROSS JOIN utilisateur u
WHERE u.actif = true
  AND (
    u.role IN ('admin', 'rh')
    OR u.equipe_code = p.equipe_code
    OR u.id = p.chef_projet_id
    OR EXISTS (SELECT 1 FROM projet_co_chef pc WHERE pc.projet_id = p.id AND pc.utilisateur_id = u.id)
    OR EXISTS (SELECT 1 FROM projet_intervenant pi WHERE pi.projet_id = p.id AND pi.utilisateur_id = u.id)
    OR EXISTS (
      SELECT 1 FROM tache t
      JOIN tache_intervenant ti ON ti.tache_id = t.id
      WHERE t.projet_id = p.id AND ti.utilisateur_id = u.id
    )
  );

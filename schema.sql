-- =====================================================================
-- Kairos — schema de base de données (étape 1)
-- PostgreSQL 14+
--
-- Portée : Projets, Tâches, DailyLog, Posts (fil d'activité, y compris
-- Requêtes en tant que type de post), Utilisateurs.
-- Hors périmètre pour l'instant (colonnes/tables prévues mais non
-- utilisées) : Congé/Télétravail, posts hors-projet (Information), rôle
-- Client, Honoraires. Le rôle RH, lui, est actif.
--
-- Choix de conception :
--  - ENUM Postgres pour les listes fermées et stables (phase, état projet,
--    état tâche, type de deadline, rôle utilisateur).
--  - Table de référence (au lieu d'ENUM) pour tout ce qui est amené à
--    s'étendre sans migration lourde : lot (CM/GO/...), équipe/bureau
--    (Midgard/URBS/VD/SS/Q/...), type de post (Envoi/Réponse/Question/
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
-- Id de l'utilisateur applicatif courant (SET LOCAL app.current_user_id,
-- voir app/db.py), NULL si absent / vide / invalide (migration 0013).
CREATE OR REPLACE FUNCTION fn_app_user_id()
RETURNS BIGINT AS $$
  SELECT CASE WHEN s ~ '^[0-9]{1,18}$' THEN s::BIGINT END
  FROM (SELECT current_setting('app.current_user_id', true) AS s) x
$$ LANGUAGE sql STABLE;

-- Id de l'Admin réel quand il « agit comme » un autre compte (SET LOCAL
-- app.admin_reel_id, mode test du lot 12, migration 0018), NULL sinon.
CREATE OR REPLACE FUNCTION fn_app_admin_reel_id()
RETURNS BIGINT AS $$
  SELECT CASE WHEN s ~ '^[0-9]{1,18}$' THEN s::BIGINT END
  FROM (SELECT current_setting('app.admin_reel_id', true) AS s) x
$$ LANGUAGE sql STABLE;

-- updated_by n'est jamais écrasé par NULL quand aucune variable de session
-- n'est posée (script, migration) : la valeur explicite de la requête, ou
-- l'auteur précédent, est conservée (migration 0013).
CREATE OR REPLACE FUNCTION set_updated_at_and_by()
RETURNS TRIGGER AS $$
DECLARE
  v_user_id BIGINT := fn_app_user_id();
BEGIN
  NEW.updated_at = fn_maintenant();
  IF v_user_id IS NOT NULL THEN
    NEW.updated_by = v_user_id;
  END IF;
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

-- Rôle utilisateur. RH est actif (compte unique, voir
-- idx_utilisateur_rh_singleton) ; Client existe dans l'énum pour éviter une
-- migration future mais n'est pas encore proposé dans l'interface.
CREATE TYPE role_enum AS ENUM ('admin', 'chef_de_projet', 'intervenant', 'rh', 'client');


-- =====================================================================
-- TABLES DE RÉFÉRENCE (extensibles sans migration de type)
-- =====================================================================

-- Bureaux / entités du groupe (Midgard, URBS, VD, SS, Q)
-- ISBG renommé en URBS (2026-09-20) ; IPCO retirée et VD ajoutée (lot 18,
-- migration 0023) — sur une
-- base déjà installée, ce INSERT ne joue aucun rôle (il ne tourne qu'à la
-- création du schéma) : voir migrations/0001, appliquée par `flask migrer`.
CREATE TABLE equipe (
  code       VARCHAR(20) PRIMARY KEY,
  libelle    VARCHAR(100) NOT NULL,
  actif      BOOLEAN NOT NULL DEFAULT true
);
INSERT INTO equipe (code, libelle) VALUES
  ('MIDGARD', 'Midgard'),
  ('URBS',    'URBS'),
  ('VD',      'VD'),
  ('SS',      'SS'),
  ('Q',       'Q');

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
-- logique dédiée). Information : publiable depuis la migration 0009
-- (projet optionnel ; sans projet, destiné à des équipes — post_equipe).
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
  ('information', 'Information', true);  -- migration 0009

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
  fuseau           VARCHAR(40) NOT NULL DEFAULT 'Africa/Tunis', -- bureau de la personne (migration 0014) : « aujourd'hui » du Daily log, fenêtre de 14 jours, rappel
  reset_token_hash        VARCHAR(64), -- empreinte SHA-256 du jeton "mot de passe oublié" envoyé par email (jamais le jeton en clair) ; NULL = pas de réinitialisation en cours
  reset_token_expires_at  TIMESTAMPTZ, -- le jeton n'est valable qu'avant cette date (1h, voir app/auth.py) ; à usage unique, effacé dès qu'il sert
  created_by       BIGINT REFERENCES utilisateur(id), -- admin qui a créé la fiche (NULL pour le tout premier compte)
  updated_by       BIGINT REFERENCES utilisateur(id),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT utilisateur_fuseau_valide CHECK (fuseau IN ('Africa/Tunis', 'America/Cayenne'))
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
  code             VARCHAR(20) NOT NULL,        -- ex. "24091X" — proposé semi-auto, éditable ; unique PAR PHASE (lot 20, index projet_code_phase_uniq)
  nom              VARCHAR(200) NOT NULL,
  phase            phase_enum NOT NULL,
  date_debut       DATE,
  date_fin         DATE,                    -- fin prévue (affichée "Échéance"), saisie par le chef
  date_cloture     DATE,                    -- posée automatiquement au passage à Terminé/Abandonné, effacée à la réouverture (migration 0011)
  etat             projet_etat_enum NOT NULL DEFAULT 'en_cours',
  chef_projet_id   BIGINT NOT NULL REFERENCES utilisateur(id),
  phase_liee_id    BIGINT REFERENCES projet(id), -- ex. le 24091X (EXE) pointe vers le 24091D (DCE)
  equipe_code      VARCHAR(20) REFERENCES equipe(code), -- équipe "propriétaire" du projet, pour la visibilité (2026-09-16, voir plus bas) ; proposée automatiquement (équipe du chef de projet) à la création, modifiable ; projets repris de Chronos : équipe du chef, à défaut MIDGARD (migration 0016)
  honoraires       NUMERIC(12,2),           -- montant des honoraires, saisi par le chef de projet (migration 0010)
  client           VARCHAR(150) NOT NULL DEFAULT 'IPCO', -- migration 0010 (retour Fadhel : « IPCO » par défaut)
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
-- Lot 20 (migration 0024) : APS et APD d'une même affaire gardent le même code.
CREATE UNIQUE INDEX projet_code_phase_uniq ON projet (code, phase);

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

-- Lot 21 (migration 0025) : personnes qui ont participé à un projet puis en
-- ont été retirées — lecture seule gardée (v_projet_visibilite). Défaut
-- fn_maintenant() posé plus bas (fonction définie plus loin).
CREATE TABLE projet_ancien_membre (
  projet_id      BIGINT NOT NULL REFERENCES projet(id) ON DELETE CASCADE,
  utilisateur_id BIGINT NOT NULL REFERENCES utilisateur(id),
  depuis         TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (projet_id, utilisateur_id)
);
CREATE INDEX idx_projet_ancien_membre_user ON projet_ancien_membre(utilisateur_id);
COMMENT ON TABLE projet_ancien_membre IS
  'Personnes qui ont participé à un projet puis en ont été retirées (0025) : lecture seule gardée (v_projet_visibilite).';

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
  -- Client : jamais rattaché à un projet ou une tâche (migration 0011).
  IF v_role = 'client' THEN
    RAISE EXCEPTION 'Un utilisateur avec le rôle Client ne peut pas être % (utilisateur id=%).', p_contexte, p_utilisateur_id;
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
  -- Dernier blocage (migration 0020, lot 14 : « Qu'est-ce qui bloque ? ») :
  -- motif, début et auteur ; affichés tant que la tâche est bloquée.
  bloque_motif     TEXT CONSTRAINT tache_bloque_motif_longueur
                     CHECK (bloque_motif IS NULL OR char_length(bloque_motif) BETWEEN 1 AND 500),
  bloque_le        TIMESTAMPTZ,
  bloque_par       BIGINT REFERENCES utilisateur(id),
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
CREATE INDEX idx_tache_bloquee ON tache (projet_id) WHERE etat = 'bloque';
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
  -- Ni NaN (accepté par NUMERIC et par heures > 0), ni plus de 24 h (migration 0005).
  CONSTRAINT dailylog_entree_heures_valides CHECK (heures <> 'NaN' AND heures <= 24),
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

CREATE INDEX idx_dailylog_projet ON dailylog_entree(projet_id);
CREATE INDEX idx_dailylog_tache ON dailylog_entree(tache_id);

-- Une seule ligne par (utilisateur, jour, projet, tâche) — y compris
-- quand tache_id est vide (COALESCE(tache_id, 0) traite alors toutes les
-- lignes "projet seul" du même jour comme le même couple, donc une seule
-- autorisée, modifiable, comme les lignes avec tâche).
CREATE UNIQUE INDEX idx_dailylog_unique
  ON dailylog_entree (utilisateur_id, date, projet_id, COALESCE(tache_id, 0));

-- Durée de la journée / absence, jour par jour (Daily log v2, retour
-- Fadhel, 2026-09-29 — migration 0008) : double-clic sur « 8 h » pour
-- régler la journée de 4 h à 10 h, ou la marquer « Absent » (pastille
-- bleue du calendrier). Sans ligne ici, la journée vaut 8 h, ou pour une
-- journée saisie avant cette version, le total de ses heures (on ne
-- modifie jamais des heures déjà enregistrées). La contrainte accepte
-- jusqu'à 24 h pour ces anciennes journées ; l'écran, lui, borne à 4-10 h.
CREATE TABLE dailylog_jour (
  id             BIGSERIAL PRIMARY KEY,
  utilisateur_id BIGINT NOT NULL REFERENCES utilisateur(id),
  date           DATE NOT NULL,
  duree_heures   NUMERIC(4,2),            -- v2 : durée réglée pour ce jour ; plus écrite depuis la v9 (migration 0014)
  absent         BOOLEAN NOT NULL DEFAULT false,
  version        INTEGER NOT NULL DEFAULT 1, -- verrou optimiste (migration 0014) : +1 à chaque enregistrement ; pas de ligne = 0
  updated_by     BIGINT REFERENCES utilisateur(id),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT dailylog_jour_duree_valide CHECK (duree_heures > 0 AND duree_heures <= 24),
  CONSTRAINT dailylog_jour_version_valide CHECK (version >= 0),
  CONSTRAINT dailylog_jour_unique UNIQUE (utilisateur_id, date)
);
COMMENT ON COLUMN utilisateur.fuseau IS
  'Fuseau du bureau (0014) : « aujourd''hui » du Daily log, fenêtre de 14 jours, rappel.';
COMMENT ON COLUMN dailylog_jour.duree_heures IS
  'Daily log v2 (0008) : durée réglée pour ce jour. Plus écrite depuis la v9 (0014) — historique seulement.';
COMMENT ON COLUMN dailylog_jour.version IS
  'Verrou optimiste (0014) : +1 à chaque enregistrement du jour ; pas de ligne = 0.';
CREATE TRIGGER trg_dailylog_jour_updated_at
  BEFORE UPDATE ON dailylog_jour
  FOR EACH ROW EXECUTE FUNCTION set_updated_at_and_by();

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
  tache_id       BIGINT REFERENCES tache(id),      -- renseigné si le post vient de la création/clôture d'une tâche
  parent_post_id BIGINT REFERENCES post(id),        -- "rebondir" : ce post répond à un autre post
  auteur_id      BIGINT NOT NULL REFERENCES utilisateur(id),
  type_code      VARCHAR(20) NOT NULL REFERENCES post_type(code),
  contenu        TEXT,
  lien           TEXT,                              -- lien optionnel (ex. vers le NAS interne), demandé 2026-09-18
  -- Marqueur explicite d'évènement de tâche (migration 0004,
  -- PROMPT_CORRECTIONS.md P1 #9) : remplace l'ancienne heuristique
  -- post.created_at == tache.created_at/updated_at, cassée par
  -- trg_tache_updated_at qui réécrit updated_at à CHAQUE modification de
  -- la tâche, pas seulement à sa clôture (voir repositories/taches.py).
  -- 'repost' ajouté en migration 0007 (Lot 5, retour Fadhel, 2026-09-28) :
  -- un post créé par posts.repost(), toujours avec parent_post_id renseigné
  -- (le post reposté) — même colonne que "rebondir", évènement différent.
  -- Migration 0009 (retour Fadhel, 2026-09-29, P1) : posts automatiques de
  -- création de projet, changement d'état de tâche/projet et modification
  -- du titre d'une tâche. Migration 0017 (lot 11 b) : 'chef_projet', le
  -- changement de chef depuis la fenêtre Informations.
  evenement      VARCHAR(20) CONSTRAINT post_evenement_check CHECK (evenement IS NULL OR evenement IN (
                   'creation_tache', 'cloture_tache', 'repost',
                   'creation_projet', 'etat_tache', 'etat_projet', 'titre_tache', 'chef_projet',
                   'intervenant_tache', 'echeance_tache', 'intervenant_projet',
                   'blocage_tache', 'deblocage_tache')),
  updated_by     BIGINT REFERENCES utilisateur(id), -- si le post est modifié après publication
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Lot 15 (migration 0021) : texte modifié par l'auteur ; suppression
  -- LOGIQUE par l'auteur, le chef, un co-chef ou l'Admin (« Annuler »).
  modifie_le     TIMESTAMPTZ,
  supprime_le    TIMESTAMPTZ,
  supprime_par   BIGINT REFERENCES utilisateur(id),
  -- Lot 21 (migration 0025) : Information épinglée en tête du fil du projet.
  epingle_le     TIMESTAMPTZ,
  epingle_par    BIGINT REFERENCES utilisateur(id),
  CONSTRAINT post_epingle_check CHECK (
    epingle_le IS NULL
    OR (projet_id IS NOT NULL AND type_code = 'information' AND evenement IS NULL AND supprime_le IS NULL))
);
CREATE UNIQUE INDEX ux_post_epingle_projet ON post(projet_id) WHERE epingle_le IS NOT NULL;
COMMENT ON COLUMN post.epingle_le IS 'Épinglé en tête du fil du projet (0025) : un seul post par projet.';
COMMENT ON COLUMN post.epingle_par IS 'Qui a épinglé le post (chef, co-chef ou Admin).';
CREATE TRIGGER trg_post_updated_at
  BEFORE UPDATE ON post
  FOR EACH ROW EXECUTE FUNCTION set_updated_at_and_by();

CREATE INDEX idx_post_projet_date ON post(projet_id, created_at DESC);
CREATE INDEX idx_post_tache ON post(tache_id);
CREATE INDEX idx_post_parent ON post(parent_post_id);
CREATE INDEX idx_post_type ON post(type_code);
CREATE INDEX idx_post_created_at ON post(created_at DESC); -- fil d'accueil (migration 0005)

-- Pièces jointes d'un post (ex. le dossier envoyé dans un post "Envoi")
CREATE TABLE post_piece_jointe (
  id             BIGSERIAL PRIMARY KEY,
  post_id        BIGINT NOT NULL REFERENCES post(id) ON DELETE CASCADE,
  nom_fichier    VARCHAR(255) NOT NULL,
  chemin         TEXT NOT NULL,
  uploaded_by    BIGINT REFERENCES utilisateur(id), -- pour cohérence avec tache_piece_jointe
  uploaded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Retrait (migration 0021) : plus téléchargeable, fichier effacé 30 jours après.
  retire_le      TIMESTAMPTZ,
  retire_par     BIGINT REFERENCES utilisateur(id)
);
CREATE INDEX idx_post_pj_post ON post_piece_jointe(post_id);
CREATE INDEX idx_post_pj_retiree ON post_piece_jointe (retire_le) WHERE retire_le IS NOT NULL;

-- Personnes taguées sur un post (composeur Requête/Information, demandé
-- 2026-09-18) — distinct de post_commentaire.mentionne_user_id, qui tague
-- une personne dans un commentaire, pas dans le post lui-même.
CREATE TABLE post_mention (
  post_id        BIGINT NOT NULL REFERENCES post(id) ON DELETE CASCADE,
  utilisateur_id BIGINT NOT NULL REFERENCES utilisateur(id),
  PRIMARY KEY (post_id, utilisateur_id)
);
CREATE INDEX idx_post_mention_utilisateur ON post_mention(utilisateur_id);

-- Équipes destinataires d'un post "Information" SANS projet (migration
-- 0009, retour Fadhel, 2026-09-29) : visible des membres de ces équipes,
-- de l'auteur, des personnes taguées et des Admin/RH.
CREATE TABLE post_equipe (
  id          BIGSERIAL PRIMARY KEY,
  post_id     BIGINT NOT NULL REFERENCES post(id) ON DELETE CASCADE,
  equipe_code VARCHAR(20) NOT NULL REFERENCES equipe(code),
  CONSTRAINT post_equipe_unique UNIQUE (post_id, equipe_code)
);
CREATE INDEX idx_post_equipe_equipe ON post_equipe(equipe_code);

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
  id                    BIGSERIAL PRIMARY KEY,
  post_id               BIGINT NOT NULL REFERENCES post(id) ON DELETE CASCADE,
  auteur_id             BIGINT NOT NULL REFERENCES utilisateur(id),
  contenu               TEXT NOT NULL,
  mentionne_user_id     BIGINT REFERENCES utilisateur(id),
  -- Réponse en ligne (migration 0007, Lot 5, retour Fadhel, 2026-09-28) :
  -- un commentaire peut répondre à un AUTRE commentaire du même post,
  -- affiché en retrait sous lui. Un seul niveau de profondeur, imposé
  -- côté application (routes/posts.py:commenter) plutôt qu'en base : le
  -- commentaire visé par parent_commentaire_id doit lui-même être de
  -- premier niveau (parent_commentaire_id IS NULL), pour garder un rendu
  -- simple (façon Facebook/Twitter, pas de fil imbriqué à l'infini).
  parent_commentaire_id BIGINT REFERENCES post_commentaire(id) ON DELETE CASCADE,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  modifie_le            TIMESTAMPTZ, -- modifié par son auteur (migration 0009), affiché "modifié"
  -- Suppression logique, réponses comprises (migration 0021).
  supprime_le           TIMESTAMPTZ,
  supprime_par          BIGINT REFERENCES utilisateur(id)
);
CREATE INDEX idx_post_commentaire_post ON post_commentaire(post_id);
CREATE INDEX idx_post_commentaire_parent ON post_commentaire(parent_commentaire_id);

-- Pièces jointes d'un commentaire (migration 0007, Lot 5, retour Fadhel,
-- 2026-09-28 : "glisser-déposer, aperçu image") — même structure que
-- post_piece_jointe/tache_piece_jointe, au niveau du commentaire.
CREATE TABLE post_commentaire_piece_jointe (
  id             BIGSERIAL PRIMARY KEY,
  commentaire_id BIGINT NOT NULL REFERENCES post_commentaire(id) ON DELETE CASCADE,
  nom_fichier    VARCHAR(255) NOT NULL,
  chemin         TEXT NOT NULL,
  uploaded_by    BIGINT REFERENCES utilisateur(id),
  uploaded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  retire_le      TIMESTAMPTZ, -- retrait (migration 0021)
  retire_par     BIGINT REFERENCES utilisateur(id)
);
CREATE INDEX idx_post_commentaire_pj_commentaire ON post_commentaire_piece_jointe(commentaire_id);
CREATE INDEX idx_commentaire_pj_retiree ON post_commentaire_piece_jointe (retire_le)
  WHERE retire_le IS NOT NULL;

-- Personnes taguées avec "@Prénom Nom" dans le texte d'un commentaire
-- (migration 0009) — plusieurs possibles ; mentionne_user_id ci-dessus
-- reste pour les commentaires plus anciens (un seul tag, champ séparé).
CREATE TABLE post_commentaire_mention (
  id             BIGSERIAL PRIMARY KEY,
  commentaire_id BIGINT NOT NULL REFERENCES post_commentaire(id) ON DELETE CASCADE,
  utilisateur_id BIGINT NOT NULL REFERENCES utilisateur(id),
  CONSTRAINT post_commentaire_mention_unique UNIQUE (commentaire_id, utilisateur_id)
);
CREATE INDEX idx_post_commentaire_mention_utilisateur ON post_commentaire_mention(utilisateur_id);


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
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Rappel Daily log (migration 0017) : les jours oubliés qu'il cite —
  -- clé du dédoublonnage et du marquage « lu » (plus de LIKE sur le texte).
  rappel_jours   DATE[] CONSTRAINT notification_rappel_jours_check
                   CHECK (rappel_jours IS NULL OR cardinality(rappel_jours) BETWEEN 1 AND 31),
  -- Migration 0019 : projet ouvert par une notification sans post ni tâche
  -- (« ajouté au projet ») ; rappel créé par « Simuler le rappel du jour »
  -- (mode test), ignoré par le dédoublonnage des vrais rappels.
  projet_id      BIGINT REFERENCES projet(id),
  simulee        BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX idx_notification_user_lu ON notification(utilisateur_id, lu);
CREATE INDEX idx_notification_user_date ON notification(utilisateur_id, created_at DESC); -- migration 0005
CREATE INDEX idx_notification_rappel_jours ON notification (utilisateur_id) WHERE rappel_jours IS NOT NULL; -- migration 0017
CREATE INDEX idx_notification_projet ON notification (projet_id) WHERE projet_id IS NOT NULL; -- migration 0019


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
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Admin réel quand il « agit comme » utilisateur_id (migration 0018,
  -- mode test) ; NULL sinon.
  admin_reel_id  BIGINT REFERENCES utilisateur(id)
);
COMMENT ON COLUMN audit_log.admin_reel_id IS
  'Admin réel quand il agit comme un autre compte (0018, mode test) ; NULL sinon.';
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
  v_user_id BIGINT := fn_app_user_id();
  v_admin_reel BIGINT := fn_app_admin_reel_id();
BEGIN
  -- Le "-" retire une clé du JSON si elle existe (ne fait rien sinon) :
  -- on retire systématiquement mot_de_passe_hash pour ne JAMAIS stocker
  -- de hash de mot de passe dans le journal d'audit, même historique.
  -- reset_token_hash (2026-09-20) suit la même règle : même si ce n'est
  -- qu'une empreinte d'un jeton à usage unique et de courte durée de vie,
  -- pas de raison de la garder dans un historique.
  -- admin_reel_id (0018) : l'Admin qui « agit comme » utilisateur_id.
  IF (TG_OP = 'DELETE') THEN
    INSERT INTO audit_log(table_cible, ligne_id, action, utilisateur_id, donnees_avant, admin_reel_id)
    VALUES (TG_TABLE_NAME, (to_jsonb(OLD)->>'id')::BIGINT, TG_OP, v_user_id, to_jsonb(OLD) - 'mot_de_passe_hash' - 'reset_token_hash', v_admin_reel);
    RETURN OLD;
  ELSIF (TG_OP = 'UPDATE') THEN
    INSERT INTO audit_log(table_cible, ligne_id, action, utilisateur_id, donnees_avant, donnees_apres, admin_reel_id)
    VALUES (TG_TABLE_NAME, (to_jsonb(NEW)->>'id')::BIGINT, TG_OP, v_user_id, to_jsonb(OLD) - 'mot_de_passe_hash' - 'reset_token_hash', to_jsonb(NEW) - 'mot_de_passe_hash' - 'reset_token_hash', v_admin_reel);
    RETURN NEW;
  ELSIF (TG_OP = 'INSERT') THEN
    INSERT INTO audit_log(table_cible, ligne_id, action, utilisateur_id, donnees_apres, admin_reel_id)
    VALUES (TG_TABLE_NAME, (to_jsonb(NEW)->>'id')::BIGINT, TG_OP, v_user_id, to_jsonb(NEW) - 'mot_de_passe_hash' - 'reset_token_hash', v_admin_reel);
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
CREATE TRIGGER trg_audit_dailylog_jour AFTER INSERT OR UPDATE OR DELETE ON dailylog_jour FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_post AFTER INSERT OR UPDATE OR DELETE ON post FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_post_piece_jointe AFTER INSERT OR UPDATE OR DELETE ON post_piece_jointe FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_post_mention AFTER INSERT OR UPDATE OR DELETE ON post_mention FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_post_commentaire AFTER INSERT OR UPDATE OR DELETE ON post_commentaire FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_post_commentaire_piece_jointe AFTER INSERT OR UPDATE OR DELETE ON post_commentaire_piece_jointe FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_post_equipe AFTER INSERT OR UPDATE OR DELETE ON post_equipe FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
CREATE TRIGGER trg_audit_post_commentaire_mention AFTER INSERT OR UPDATE OR DELETE ON post_commentaire_mention FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
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

-- Répartition des heures par rôle (retour Fadhel, 2026-09-28, Lot 5 —
-- "répartition des heures par rôle (8h intervenant/5h chef) affichée
-- dans Informations/liste projets/lignes de tâches" ; voir
-- workflowbook-spec.md). v_projet_heures/v_tache_heures ci-dessus
-- donnent un TOTAL, sans distinguer qui a logué ces heures : ces deux
-- vues ajoutent la répartition demandée, en deux catégories (le
-- parenthétage "8h/5h" de la demande est un exemple de résultat affiché,
-- pas un ratio ou une conversion à appliquer) :
--   - heures_chef : heures loguées par le chef de projet titulaire ou un
--     co-chef du projet concerné (rôle défini au niveau PROJET, voir
--     projet_co_chef — pas un rôle par tâche) ;
--   - heures_intervenant : toutes les autres heures loguées sur ce
--     projet/cette tâche (intervenant déclaré, ou toute personne ayant
--     simplement logué du temps dessus).
-- Rôle évalué à la date de lecture (chef_projet_id/projet_co_chef
-- actuels), pas un instantané historique — même choix que
-- v_projet_visibilite juste en dessous, qui ne fige pas non plus le
-- rôle au moment de l'action.
CREATE VIEW v_projet_heures_par_role AS
SELECT
  de.projet_id,
  SUM(CASE WHEN de.utilisateur_id = p.chef_projet_id
             OR EXISTS (SELECT 1 FROM projet_co_chef pc
                        WHERE pc.projet_id = de.projet_id AND pc.utilisateur_id = de.utilisateur_id)
           THEN de.heures ELSE 0 END) AS heures_chef,
  SUM(CASE WHEN de.utilisateur_id = p.chef_projet_id
             OR EXISTS (SELECT 1 FROM projet_co_chef pc
                        WHERE pc.projet_id = de.projet_id AND pc.utilisateur_id = de.utilisateur_id)
           THEN 0 ELSE de.heures END) AS heures_intervenant
FROM dailylog_entree de
JOIN projet p ON p.id = de.projet_id
GROUP BY de.projet_id;

-- Même répartition, au niveau tâche (rôle toujours évalué sur le PROJET
-- de la tâche : une tâche elle-même n'a pas de "chef" propre).
CREATE VIEW v_tache_heures_par_role AS
SELECT
  de.tache_id,
  SUM(CASE WHEN de.utilisateur_id = p.chef_projet_id
             OR EXISTS (SELECT 1 FROM projet_co_chef pc
                        WHERE pc.projet_id = t.projet_id AND pc.utilisateur_id = de.utilisateur_id)
           THEN de.heures ELSE 0 END) AS heures_chef,
  SUM(CASE WHEN de.utilisateur_id = p.chef_projet_id
             OR EXISTS (SELECT 1 FROM projet_co_chef pc
                        WHERE pc.projet_id = t.projet_id AND pc.utilisateur_id = de.utilisateur_id)
           THEN 0 ELSE de.heures END) AS heures_intervenant
FROM dailylog_entree de
JOIN tache t ON t.id = de.tache_id
JOIN projet p ON p.id = t.projet_id
WHERE de.tache_id IS NOT NULL
GROUP BY de.tache_id;

-- Visibilité des projets par équipe (2026-09-16, voir la doc) : un
-- utilisateur voit un projet s'il appartient à la même équipe que le
-- projet, OU s'il y est explicitement rattaché (chef, co-chef,
-- intervenant du projet ou d'une de ses tâches) même hors de son
-- équipe — cas d'une collaboration ponctuelle inter-équipes. L'Admin
-- voit tout ; le RH ne voit AUCUN projet ; un Client ne voit que les
-- projets de son équipe (migration 0011). Une ligne (projet_id,
-- utilisateur_id) = "cet utilisateur peut voir ce projet" ; l'appli
-- filtre ses requêtes de liste de projets avec un JOIN/EXISTS dessus
-- plutôt que de dupliquer cette logique à chaque endroit.
CREATE VIEW v_projet_visibilite AS
SELECT p.id AS projet_id, u.id AS utilisateur_id
FROM projet p
CROSS JOIN utilisateur u
WHERE u.actif = true
  AND u.role <> 'rh'
  AND (
    u.role = 'admin'
    OR u.equipe_code = p.equipe_code
    OR (u.role <> 'client' AND (
      u.id = p.chef_projet_id
      OR EXISTS (SELECT 1 FROM projet_co_chef pc WHERE pc.projet_id = p.id AND pc.utilisateur_id = u.id)
      OR EXISTS (SELECT 1 FROM projet_intervenant pi WHERE pi.projet_id = p.id AND pi.utilisateur_id = u.id)
      OR EXISTS (
        SELECT 1 FROM tache t
        JOIN tache_intervenant ti ON ti.tache_id = t.id
        WHERE t.projet_id = p.id AND ti.utilisateur_id = u.id
      )
      OR EXISTS (SELECT 1 FROM projet_ancien_membre am WHERE am.projet_id = p.id AND am.utilisateur_id = u.id)
    ))
  );

-- Lot 20 (migration 0024) : droit d'AGIR (une tâche close ne donne que la lecture).
CREATE OR REPLACE VIEW v_projet_action AS
SELECT p.id AS projet_id, u.id AS utilisateur_id
FROM projet p
CROSS JOIN utilisateur u
WHERE u.actif = true
  AND u.role <> 'rh'
  AND (
    u.role = 'admin'
    OR u.equipe_code = p.equipe_code
    OR (u.role <> 'client' AND (
      u.id = p.chef_projet_id
      OR EXISTS (SELECT 1 FROM projet_co_chef pc WHERE pc.projet_id = p.id AND pc.utilisateur_id = u.id)
      OR EXISTS (SELECT 1 FROM projet_intervenant pi WHERE pi.projet_id = p.id AND pi.utilisateur_id = u.id)
      OR EXISTS (
        SELECT 1 FROM tache t
        JOIN tache_intervenant ti ON ti.tache_id = t.id
        WHERE t.projet_id = p.id AND ti.utilisateur_id = u.id AND t.etat IN ('en_cours', 'bloque')
      )
    ))
  );
COMMENT ON VIEW v_projet_action IS
  'Droit d''agir sur un projet (0024) : comme v_projet_visibilite, mais une tâche close ne donne que la lecture.';


-- ---------------------------------------------------------------------
-- Règle "un RH n'est ni chef, ni co-chef, ni intervenant" aussi lors d'un
-- CHANGEMENT de rôle (migration 0005) — les triggers plus haut ne
-- couvrent que l'ajout d'une personne à un projet/une tâche.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_check_passage_role_rh()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.role IN ('rh', 'client') AND OLD.role IS DISTINCT FROM NEW.role AND (
       EXISTS (SELECT 1 FROM projet WHERE chef_projet_id = NEW.id)
    OR EXISTS (SELECT 1 FROM projet_co_chef WHERE utilisateur_id = NEW.id)
    OR EXISTS (SELECT 1 FROM projet_intervenant WHERE utilisateur_id = NEW.id)
    OR EXISTS (SELECT 1 FROM tache_intervenant WHERE utilisateur_id = NEW.id)
  ) THEN
    RAISE EXCEPTION 'Un utilisateur avec le rôle % ne peut pas être chef de projet, co-chef ou intervenant (utilisateur id=%) : retirez-le d''abord de ses projets et tâches.',
      CASE NEW.role WHEN 'rh' THEN 'RH' ELSE 'Client' END, NEW.id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_check_passage_role_rh ON utilisateur;
CREATE TRIGGER trg_check_passage_role_rh
  BEFORE UPDATE OF role ON utilisateur
  FOR EACH ROW EXECUTE FUNCTION fn_check_passage_role_rh();


-- ---------------------------------------------------------------------
-- Fuseau horaire de la base (migration 0005) : CURRENT_DATE et
-- created_at::date doivent suivre l'heure de Tunis, pas UTC.
-- ---------------------------------------------------------------------
DO $$
BEGIN
  EXECUTE format('ALTER DATABASE %I SET timezone = %L', current_database(), 'Africa/Tunis');
END $$;


-- ---------------------------------------------------------------------
-- Dates ordonnées et honoraires positifs (migration 0012, lot 8). Chaque
-- règle ne s'évalue que si SES colonnes changent (migration 0013).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_check_dates_projet()
RETURNS TRIGGER AS $$
DECLARE
  v_dates_changent BOOLEAN := true;
  v_honoraires_changent BOOLEAN := true;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    v_dates_changent := NEW.date_debut IS DISTINCT FROM OLD.date_debut
                        OR NEW.date_fin IS DISTINCT FROM OLD.date_fin;
    v_honoraires_changent := NEW.honoraires IS DISTINCT FROM OLD.honoraires;
  END IF;
  IF v_dates_changent AND NEW.date_fin IS NOT NULL AND NEW.date_debut IS NOT NULL
     AND NEW.date_fin < NEW.date_debut THEN
    RAISE EXCEPTION 'Date de fin du projet (%) antérieure à sa date de début (%).', NEW.date_fin, NEW.date_debut;
  END IF;
  IF v_honoraires_changent AND NEW.honoraires IS NOT NULL AND NEW.honoraires < 0 THEN
    RAISE EXCEPTION 'Honoraires négatifs refusés.';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_check_dates_projet ON projet;
CREATE TRIGGER trg_check_dates_projet
  BEFORE INSERT ON projet
  FOR EACH ROW EXECUTE FUNCTION fn_check_dates_projet();
DROP TRIGGER IF EXISTS trg_check_dates_projet_maj ON projet;
CREATE TRIGGER trg_check_dates_projet_maj
  BEFORE UPDATE OF date_debut, date_fin, honoraires ON projet
  FOR EACH ROW
  WHEN (OLD.date_debut IS DISTINCT FROM NEW.date_debut
        OR OLD.date_fin IS DISTINCT FROM NEW.date_fin
        OR OLD.honoraires IS DISTINCT FROM NEW.honoraires)
  EXECUTE FUNCTION fn_check_dates_projet();

CREATE OR REPLACE FUNCTION fn_check_dates_tache()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.date_echeance IS NOT NULL AND NEW.date_debut IS NOT NULL AND NEW.date_echeance < NEW.date_debut THEN
    RAISE EXCEPTION 'Échéance de la tâche (%) antérieure à sa date de début (%).', NEW.date_echeance, NEW.date_debut;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_check_dates_tache ON tache;
CREATE TRIGGER trg_check_dates_tache
  BEFORE INSERT ON tache
  FOR EACH ROW EXECUTE FUNCTION fn_check_dates_tache();
DROP TRIGGER IF EXISTS trg_check_dates_tache_maj ON tache;
CREATE TRIGGER trg_check_dates_tache_maj
  BEFORE UPDATE OF date_debut, date_echeance ON tache
  FOR EACH ROW
  WHEN (OLD.date_debut IS DISTINCT FROM NEW.date_debut
        OR OLD.date_echeance IS DISTINCT FROM NEW.date_echeance)
  EXECUTE FUNCTION fn_check_dates_tache();


-- ---------------------------------------------------------------------
-- Migration 0013 (lot 10) : intégrité, index, garde des comptes Admin,
-- co-chef automatique. Mêmes définitions que
-- migrations/0013_rattrapage_et_integrite.sql (une base neuve doit avoir
-- exactement le catalogue d'une base migrée — vérifié en CI).
-- ---------------------------------------------------------------------
-- Une ligne d'heures (ou un post) ne pointe que la tâche de SON projet.
ALTER TABLE tache ADD CONSTRAINT tache_id_projet_unique UNIQUE (id, projet_id);
ALTER TABLE dailylog_entree ADD CONSTRAINT dailylog_entree_tache_du_projet_fk
  FOREIGN KEY (tache_id, projet_id) REFERENCES tache (id, projet_id);
ALTER TABLE post ADD CONSTRAINT post_tache_du_projet_fk
  FOREIGN KEY (tache_id, projet_id) REFERENCES tache (id, projet_id);
-- Pas d'auto-référence.
ALTER TABLE projet ADD CONSTRAINT projet_phase_liee_pas_soi_meme CHECK (phase_liee_id <> id);
ALTER TABLE post ADD CONSTRAINT post_parent_pas_soi_meme CHECK (parent_post_id <> id);
-- Vocabulaires fermés.
ALTER TABLE notification ADD CONSTRAINT notification_categorie_valide
  CHECK (categorie IN ('projet', 'rh_info'));
ALTER TABLE tentative_securite ADD CONSTRAINT tentative_securite_type_valide
  CHECK (type IN ('connexion', 'connexion_ip', 'mot_de_passe_oublie', 'mot_de_passe_oublie_ip'));
-- ENTREE / SORTIE : modes « Voir comme », « Agir comme », date simulée (0018).
ALTER TABLE audit_log ADD CONSTRAINT audit_log_action_valide
  CHECK (action IN ('INSERT', 'UPDATE', 'DELETE', 'ENTREE', 'SORTIE'));
-- Email : ni vide, ni espaces autour.
ALTER TABLE utilisateur ADD CONSTRAINT utilisateur_email_forme
  CHECK (email = btrim(email) AND position('@' IN email) > 1);

-- Compteur de la cloche (notifications non lues).
CREATE INDEX IF NOT EXISTS idx_notification_non_lues ON notification (utilisateur_id) WHERE NOT lu;
-- Onglet Log filtré par table, trié par date.
CREATE INDEX IF NOT EXISTS idx_audit_table_date ON audit_log (table_cible, created_at DESC, id DESC);
-- « Collaborateurs récents », « Mes projets récents », profil. Composites
-- et non mono-colonne : un index (auteur_id) seul fait choisir au
-- planificateur un mauvais plan pour list_mes_projets_recents (x2,5 mesuré).
CREATE INDEX IF NOT EXISTS idx_post_auteur_projet ON post (auteur_id, projet_id, created_at);
CREATE INDEX IF NOT EXISTS idx_post_commentaire_auteur_post ON post_commentaire (auteur_id, post_id)
  INCLUDE (created_at, modifie_le);
CREATE INDEX IF NOT EXISTS idx_tache_created_by ON tache (created_by);
-- Jeton « mot de passe oublié » : recherche par empreinte, unique.
CREATE UNIQUE INDEX IF NOT EXISTS idx_utilisateur_reset_token ON utilisateur (reset_token_hash)
  WHERE reset_token_hash IS NOT NULL;

-- Décision 1 : le RH ne crée, ne modifie, ne désactive ni ne promeut
-- jamais un compte Admin ; il reste toujours au moins un Admin actif.
CREATE OR REPLACE FUNCTION fn_garde_comptes_admin()
RETURNS TRIGGER AS $$
DECLARE
  v_acteur BIGINT := fn_app_user_id();
  v_role_acteur role_enum;
BEGIN
  IF v_acteur IS NOT NULL THEN
    SELECT role INTO v_role_acteur FROM utilisateur WHERE id = v_acteur;
    IF v_role_acteur = 'rh' AND (
         (TG_OP IN ('UPDATE', 'DELETE') AND OLD.role = 'admin')
      OR (TG_OP IN ('INSERT', 'UPDATE') AND NEW.role = 'admin')
    ) THEN
      RAISE EXCEPTION 'Le RH ne peut ni créer, ni modifier, ni désactiver un compte Admin.'
        USING ERRCODE = 'insufficient_privilege';
    END IF;
  END IF;
  IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.role = 'admin' AND OLD.actif
     AND (TG_OP = 'DELETE' OR NEW.role <> 'admin' OR NOT NEW.actif) THEN
    PERFORM pg_advisory_xact_lock(hashtext('kairos:admins_actifs'));
    IF NOT EXISTS (SELECT 1 FROM utilisateur WHERE role = 'admin' AND actif AND id <> OLD.id) THEN
      RAISE EXCEPTION 'Impossible : ce compte est le dernier Admin actif.'
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_garde_comptes_admin ON utilisateur;
CREATE TRIGGER trg_garde_comptes_admin
  BEFORE INSERT OR UPDATE OR DELETE ON utilisateur
  FOR EACH ROW EXECUTE FUNCTION fn_garde_comptes_admin();

-- Décision 3 : un chef de projet ajouté comme intervenant d'un projet ou
-- d'une tâche devient co-chef du projet.
CREATE OR REPLACE FUNCTION fn_chef_intervenant_co_chef()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO projet_co_chef (projet_id, utilisateur_id)
  SELECT NEW.projet_id, NEW.utilisateur_id
  FROM utilisateur u
  JOIN projet p ON p.id = NEW.projet_id
  WHERE u.id = NEW.utilisateur_id
    AND u.role = 'chef_de_projet'
    AND p.chef_projet_id <> u.id
  ON CONFLICT DO NOTHING;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_chef_intervenant_co_chef ON projet_intervenant;
CREATE TRIGGER trg_chef_intervenant_co_chef
  AFTER INSERT ON projet_intervenant
  FOR EACH ROW EXECUTE FUNCTION fn_chef_intervenant_co_chef();

CREATE OR REPLACE FUNCTION fn_chef_intervenant_tache_co_chef()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO projet_co_chef (projet_id, utilisateur_id)
  SELECT t.projet_id, NEW.utilisateur_id
  FROM tache t
  JOIN projet p ON p.id = t.projet_id
  JOIN utilisateur u ON u.id = NEW.utilisateur_id
  WHERE t.id = NEW.tache_id
    AND u.role = 'chef_de_projet'
    AND p.chef_projet_id <> u.id
  ON CONFLICT DO NOTHING;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_chef_intervenant_tache_co_chef ON tache_intervenant;
CREATE TRIGGER trg_chef_intervenant_tache_co_chef
  AFTER INSERT ON tache_intervenant
  FOR EACH ROW EXECUTE FUNCTION fn_chef_intervenant_tache_co_chef();


-- ---------------------------------------------------------------------
-- Révocation des sessions (migration 0013, audit sécurité I7) : le cookie de session
--    porte la « génération » de sessions de son titulaire. La déconnexion
--    (app/auth.py:logout) et la DÉSACTIVATION d'un compte l'incrémentent :
--    un cookie copié avant reste refusé, y compris après une réactivation.
--    Table à part (pas de colonne sur utilisateur) : ni ligne d'audit ni
--    updated_at réécrit à chaque déconnexion.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS utilisateur_session (
  utilisateur_id BIGINT PRIMARY KEY REFERENCES utilisateur(id) ON DELETE CASCADE,
  generation     INTEGER NOT NULL DEFAULT 0
);
CREATE OR REPLACE FUNCTION fn_revoquer_sessions_si_desactive()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO utilisateur_session (utilisateur_id, generation) VALUES (NEW.id, 1)
  ON CONFLICT (utilisateur_id) DO UPDATE SET generation = utilisateur_session.generation + 1;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_revoquer_sessions_si_desactive ON utilisateur;
CREATE TRIGGER trg_revoquer_sessions_si_desactive
  AFTER UPDATE OF actif ON utilisateur
  FOR EACH ROW
  WHEN (OLD.actif AND NOT NEW.actif)
  EXECUTE FUNCTION fn_revoquer_sessions_si_desactive();

-- ---------------------------------------------------------------------
-- Migration 0014 (lot 10) : Daily log v9. Mêmes définitions que
-- migrations/0014_dailylog_v9.sql (catalogue d'une base neuve = catalogue
-- d'une base migrée, vérifié en CI). Colonnes utilisateur.fuseau et
-- dailylog_jour.version : voir les CREATE TABLE plus haut.
-- Objectif de journée : réglage PAR PERSONNE (repère 4-10 h, 8 h sans
-- ligne), non audité.
-- ---------------------------------------------------------------------
-- Réglages d'affichage du compte (migration 0021, lot 15) : Deadlines
-- dépliées sur l'accueil, tâches en cours proposées dans le Daily log.
CREATE TABLE IF NOT EXISTS utilisateur_preference (
  utilisateur_id        BIGINT PRIMARY KEY REFERENCES utilisateur(id),
  accueil_deadlines     BOOLEAN,                -- NULL = jamais choisie (lot 20, migration 0024)
  dailylog_proposer     BOOLEAN NOT NULL DEFAULT true,
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 0022 (lot 17) : dernière consultation du fil de l'accueil par catégorie.
CREATE TABLE IF NOT EXISTS utilisateur_fil_vu (
  utilisateur_id  BIGINT NOT NULL REFERENCES utilisateur(id),
  categorie       TEXT NOT NULL CHECK (categorie IN ('echanges', 'activite')),
  vu_le           TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (utilisateur_id, categorie)
);
COMMENT ON TABLE utilisateur_fil_vu IS
  'Dernière consultation du fil de l''accueil par catégorie (0022) : les posts plus récents sont « nouveaux ».';

CREATE TABLE IF NOT EXISTS dailylog_preference (
  utilisateur_id    BIGINT PRIMARY KEY REFERENCES utilisateur(id),
  objectif_minutes  SMALLINT NOT NULL DEFAULT 480,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT dailylog_preference_objectif_valide
    CHECK (objectif_minutes BETWEEN 240 AND 600 AND objectif_minutes % 30 = 0)
);


-- ---------------------------------------------------------------------
-- 4. Contrôle d'une ligne d'heures : pas de 30 min, seulement si la valeur
--    CHANGE (une ancienne valeur au quart d'heure se réenregistre telle
--    quelle).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_dailylog_entree_controle()
RETURNS TRIGGER AS $$
BEGIN
  IF current_setting('kairos.reprise_historique', true) = 'on' THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.heures = NEW.heures THEN
    RETURN NEW;
  END IF;
  IF NEW.heures * 2 <> trunc(NEW.heures * 2) THEN
    RAISE EXCEPTION 'Daily log : les heures vont par pas de 30 minutes (% h refusé).', NEW.heures
      USING ERRCODE = 'check_violation', CONSTRAINT = 'dailylog_pas_30_min';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_dailylog_entree_controle ON dailylog_entree;
CREATE TRIGGER trg_dailylog_entree_controle
  BEFORE INSERT OR UPDATE OF heures ON dailylog_entree
  FOR EACH ROW EXECUTE FUNCTION fn_dailylog_entree_controle();

-- Lot 21 (migration 0025) : pas d'heures nouvelles sur une tâche close après
-- sa date de fin (gardé en base : la saisie et la clôture peuvent se croiser).
CREATE OR REPLACE FUNCTION fn_dailylog_tache_close()
RETURNS TRIGGER AS $$
DECLARE
  v_etat TEXT;
  v_fin  DATE;
BEGIN
  IF NEW.tache_id IS NULL OR current_setting('kairos.reprise_historique', true) = 'on' THEN
    RETURN NEW;
  END IF;
  -- Ligne inchangée ou baissée (correction) : jamais refusée.
  IF TG_OP = 'UPDATE' AND NEW.tache_id IS NOT DISTINCT FROM OLD.tache_id AND NEW.date = OLD.date
     AND NEW.heures <= OLD.heures THEN
    RETURN NEW;
  END IF;
  -- FOR SHARE : une clôture en cours (FOR UPDATE) passe d'abord, ou attend.
  SELECT etat::TEXT, date_fin INTO v_etat, v_fin FROM tache WHERE id = NEW.tache_id FOR SHARE;
  IF v_etat IN ('termine', 'verifie', 'abandonne', 'arret') AND v_fin IS NOT NULL AND NEW.date > v_fin THEN
    RAISE EXCEPTION 'Daily log : la tâche % est close depuis le % (pas d''heures après sa date de fin).', NEW.tache_id, v_fin
      USING ERRCODE = 'check_violation', CONSTRAINT = 'dailylog_tache_close';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_dailylog_tache_close ON dailylog_entree;
CREATE TRIGGER trg_dailylog_tache_close
  BEFORE INSERT OR UPDATE ON dailylog_entree
  FOR EACH ROW EXECUTE FUNCTION fn_dailylog_tache_close();

-- ---------------------------------------------------------------------
-- 5. Cohérence du jour, DIFFÉRÉE au COMMIT (l'ordre des écritures dans la
--    transaction n'importe pas : échanger des heures entre deux lignes ne
--    déclenche pas de faux refus) :
--    - 10 h au plus, vérifié quand une ligne est ajoutée ou AUGMENTÉE (une
--      ancienne journée Chronos de 12 h peut être réduite ligne à ligne) ;
--    - un jour « absent » ne porte aucune heure (dans les deux sens).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_dailylog_jour_coherent()
RETURNS TRIGGER AS $$
DECLARE
  v_total  NUMERIC;
  v_absent BOOLEAN;
BEGIN
  IF current_setting('kairos.reprise_historique', true) = 'on' THEN
    RETURN NULL;
  END IF;
  SELECT COALESCE(SUM(heures), 0) INTO v_total
    FROM dailylog_entree WHERE utilisateur_id = NEW.utilisateur_id AND date = NEW.date;
  SELECT absent INTO v_absent
    FROM dailylog_jour WHERE utilisateur_id = NEW.utilisateur_id AND date = NEW.date;
  IF TG_TABLE_NAME = 'dailylog_entree' AND v_total > 10 THEN
    RAISE EXCEPTION 'Daily log : % h le % pour l''utilisateur % (10 h au plus par jour).',
      v_total, NEW.date, NEW.utilisateur_id
      USING ERRCODE = 'check_violation', CONSTRAINT = 'dailylog_max_10h_par_jour';
  END IF;
  IF COALESCE(v_absent, false) AND v_total > 0 THEN
    RAISE EXCEPTION 'Daily log : le % est marqué absent mais porte % h (utilisateur %).',
      NEW.date, v_total, NEW.utilisateur_id
      USING ERRCODE = 'check_violation', CONSTRAINT = 'dailylog_absent_sans_heures';
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_dailylog_entree_jour_coherent_ins ON dailylog_entree;
CREATE CONSTRAINT TRIGGER trg_dailylog_entree_jour_coherent_ins
  AFTER INSERT ON dailylog_entree
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION fn_dailylog_jour_coherent();
DROP TRIGGER IF EXISTS trg_dailylog_entree_jour_coherent_maj ON dailylog_entree;
CREATE CONSTRAINT TRIGGER trg_dailylog_entree_jour_coherent_maj
  AFTER UPDATE OF heures, date, utilisateur_id ON dailylog_entree
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW
  WHEN (NEW.heures > OLD.heures OR OLD.date IS DISTINCT FROM NEW.date
        OR OLD.utilisateur_id IS DISTINCT FROM NEW.utilisateur_id)
  EXECUTE FUNCTION fn_dailylog_jour_coherent();
DROP TRIGGER IF EXISTS trg_dailylog_jour_absent_coherent ON dailylog_jour;
CREATE CONSTRAINT TRIGGER trg_dailylog_jour_absent_coherent
  AFTER INSERT OR UPDATE OF absent ON dailylog_jour
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW
  WHEN (NEW.absent)
  EXECUTE FUNCTION fn_dailylog_jour_coherent();

-- ---------------------------------------------------------------------
-- 6. Qui écrit quel jour (décisions du gérant, lot 10) — garde-fou en
--    base, l'appli donne le message clair avant :
--    - jamais avant 2000 ni après « aujourd'hui » AU FUSEAU DU TITULAIRE ;
--    - jamais pour un compte RH ou Client ;
--    - le titulaire : aujourd'hui et les 14 jours précédents ;
--    - l'Admin : tout ;
--    - au-delà (ou pour quelqu'un d'autre) : le chef titulaire ou un
--      co-chef du PROJET de la ligne ; pour la ligne `dailylog_jour`
--      (version), un chef de projet — mais l'absence, elle, reste au
--      titulaire dans la fenêtre et à l'Admin.
--    Sans app.current_user_id (scripts, migrations) : seules les deux
--    premières règles. Seule une valeur qui CHANGE est contrôlée.
-- ---------------------------------------------------------------------
-- Lot 20 (migration 0024) : ligne d'avant une modification contrôlée aussi ;
-- le chef n'a plus de passe-droit sur ses propres jours au-delà de 14 jours.
CREATE OR REPLACE FUNCTION fn_dailylog_droit(p_table TEXT, p_op TEXT, p_ligne JSONB, p_acteur BIGINT)
RETURNS BOOLEAN AS $$
DECLARE
  v_proprio BIGINT := (p_ligne->>'utilisateur_id')::BIGINT;
  v_date    DATE   := (p_ligne->>'date')::DATE;
  v_projet  BIGINT := (p_ligne->>'projet_id')::BIGINT;
  v_fuseau  TEXT;
  v_role    role_enum;
  v_actif   BOOLEAN;
BEGIN
  SELECT fuseau INTO v_fuseau FROM utilisateur WHERE id = v_proprio;
  IF p_acteur = v_proprio AND v_date >= fn_aujourdhui(v_fuseau) - 14 THEN
    RETURN true;
  END IF;
  SELECT role, actif INTO v_role, v_actif FROM utilisateur WHERE id = p_acteur;
  IF v_role = 'admin' AND v_actif THEN
    RETURN true;
  END IF;
  IF v_actif AND v_role = 'chef_de_projet' AND p_acteur <> v_proprio THEN
    IF p_table = 'dailylog_entree' THEN
      RETURN EXISTS (SELECT 1 FROM projet p WHERE p.id = v_projet AND p.chef_projet_id = p_acteur)
          OR EXISTS (SELECT 1 FROM projet_co_chef cc WHERE cc.projet_id = v_projet AND cc.utilisateur_id = p_acteur);
    ELSIF p_op = 'INSERT' AND NOT (p_ligne->>'absent')::BOOLEAN THEN
      RETURN true;  -- première ligne « état du jour » d'une correction (sans absence)
    END IF;
  END IF;
  RETURN false;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION fn_dailylog_garde()
RETURNS TRIGGER AS $$
DECLARE
  v_ligne        JSONB;
  v_proprio      BIGINT;
  v_date         DATE;
  v_acteur       BIGINT := fn_app_user_id();
  v_role_proprio role_enum;
  v_fuseau       TEXT;
  v_aujourdhui   DATE;
BEGIN
  IF current_setting('kairos.reprise_historique', true) = 'on' THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  -- IF imbriqués : une expression qui cite OLD.heures ne doit jamais être
  -- préparée pour une ligne de dailylog_jour (et inversement).
  IF TG_OP = 'UPDATE' THEN
    IF TG_TABLE_NAME = 'dailylog_entree' THEN
      IF OLD.heures = NEW.heures AND OLD.date = NEW.date AND OLD.utilisateur_id = NEW.utilisateur_id
         AND OLD.projet_id = NEW.projet_id AND OLD.tache_id IS NOT DISTINCT FROM NEW.tache_id THEN
        RETURN NEW;
      END IF;
    ELSIF OLD.absent = NEW.absent AND OLD.date = NEW.date AND OLD.utilisateur_id = NEW.utilisateur_id THEN
      RETURN NEW;  -- simple passage de version : les lignes sont contrôlées une à une
    END IF;
  END IF;

  v_ligne   := to_jsonb(CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END);
  v_proprio := (v_ligne->>'utilisateur_id')::BIGINT;
  v_date    := (v_ligne->>'date')::DATE;
  SELECT role, fuseau INTO v_role_proprio, v_fuseau FROM utilisateur WHERE id = v_proprio;
  -- Date (ou instant) simulée en mode test, ou aujourd'hui au fuseau du titulaire.
  v_aujourdhui := fn_aujourdhui(v_fuseau);

  IF TG_OP <> 'DELETE' THEN
    IF v_date < DATE '2000-01-01' OR v_date > v_aujourdhui THEN
      RAISE EXCEPTION 'Daily log : date % hors limites (aujourd''hui : % pour l''utilisateur %).',
        v_date, v_aujourdhui, v_proprio
        USING ERRCODE = 'check_violation', CONSTRAINT = 'dailylog_date_plausible';
    END IF;
    -- Lot 13 (décision 5) : la date simulée montre le futur, elle n'y écrit pas.
    IF v_date > fn_aujourdhui_reel(v_fuseau) THEN
      RAISE EXCEPTION 'Daily log : date % postérieure à la vraie date du jour (% pour l''utilisateur %), même en mode test.',
        v_date, fn_aujourdhui_reel(v_fuseau), v_proprio
        USING ERRCODE = 'check_violation', CONSTRAINT = 'dailylog_futur_reel';
    END IF;
    IF v_role_proprio IN ('rh', 'client') THEN
      RAISE EXCEPTION 'Daily log : un compte RH ou Client n''a pas de Daily log (utilisateur %).', v_proprio
        USING ERRCODE = 'check_violation', CONSTRAINT = 'dailylog_compte_sans_daily_log';
    END IF;
  END IF;

  IF v_acteur IS NULL THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  -- Lot 20 : la ligne d'avant une modification est contrôlée elle aussi
  -- (une ligne verrouillée ne se déplace pas vers un jour ouvert).
  IF fn_dailylog_droit(TG_TABLE_NAME, TG_OP, v_ligne, v_acteur)
     AND (TG_OP <> 'UPDATE' OR fn_dailylog_droit(TG_TABLE_NAME, TG_OP, to_jsonb(OLD), v_acteur)) THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  RAISE EXCEPTION 'Daily log du % verrouillé : au-delà de 14 jours (ou pour une autre personne), seul le chef du projet ou un Admin peut corriger (utilisateur %).',
    v_date, v_proprio
    USING ERRCODE = 'insufficient_privilege', CONSTRAINT = 'dailylog_fenetre';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_dailylog_entree_garde ON dailylog_entree;
CREATE TRIGGER trg_dailylog_entree_garde
  BEFORE INSERT OR UPDATE OF heures, date, utilisateur_id, projet_id, tache_id OR DELETE ON dailylog_entree
  FOR EACH ROW EXECUTE FUNCTION fn_dailylog_garde();
DROP TRIGGER IF EXISTS trg_dailylog_jour_garde ON dailylog_jour;
CREATE TRIGGER trg_dailylog_jour_garde
  BEFORE INSERT OR UPDATE OF absent, date, utilisateur_id OR DELETE ON dailylog_jour
  FOR EACH ROW EXECUTE FUNCTION fn_dailylog_garde();

-- ---------------------------------------------------------------------
-- 7. Recherche sans accents (catalogue du Daily log : « ete » trouve
--    « Résidence Été »), sans l'extension unaccent (qui exige un
--    superutilisateur). Même table de correspondance que
--    app/repositories/dailylog.py:sans_accents.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_sans_accents(t TEXT)
RETURNS TEXT AS $$
  SELECT translate(lower(t),
    'àáâãäåçèéêëìíîïñòóôõöùúûüýÿœæÀÁÂÃÄÅÇÈÉÊËÌÍÎÏÑÒÓÔÕÖÙÚÛÜÝ',
    'aaaaaaceeeeiiiinooooouuuuyyoaaaaaaaceeeeiiiinooooouuuuy');
$$ LANGUAGE sql IMMUTABLE PARALLEL SAFE;


-- ---------------------------------------------------------------------
-- Migration 0015 (lot 10) : états de tâche réservés. Mêmes définitions que
-- migrations/0015_etats_taches_reserves.sql (décision du gérant : seuls le
-- chef titulaire, les co-chefs et l'Admin passent une tâche en Vérifiée,
-- Arrêtée ou Abandonnée, ou l'en font sortir).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_garde_etat_tache()
RETURNS TRIGGER AS $$
DECLARE
  v_acteur BIGINT := fn_app_user_id();
BEGIN
  IF v_acteur IS NULL OR current_setting('kairos.reprise_historique', true) = 'on' THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF OLD.etat = NEW.etat THEN
      RETURN NEW;
    END IF;
    IF OLD.etat NOT IN ('verifie', 'arret', 'abandonne')
       AND NEW.etat NOT IN ('verifie', 'arret', 'abandonne') THEN
      RETURN NEW;
    END IF;
  ELSIF NEW.etat NOT IN ('verifie', 'arret', 'abandonne') THEN
    RETURN NEW;
  END IF;
  IF EXISTS (
    SELECT 1
    FROM utilisateur u
    JOIN projet p ON p.id = NEW.projet_id
    WHERE u.id = v_acteur
      AND u.actif AND u.role NOT IN ('client', 'rh')
      AND (u.role = 'admin'
           OR p.chef_projet_id = u.id
           OR EXISTS (SELECT 1 FROM projet_co_chef cc
                      WHERE cc.projet_id = p.id AND cc.utilisateur_id = u.id))
  ) THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'Tâche % : seuls le chef de projet, un co-chef ou un Admin peuvent la passer en Vérifiée, Arrêtée ou Abandonnée, ou la faire sortir de ces états.',
    NEW.id
    USING ERRCODE = 'insufficient_privilege', CONSTRAINT = 'tache_etat_reserve';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_garde_etat_tache ON tache;
CREATE TRIGGER trg_garde_etat_tache
  BEFORE INSERT OR UPDATE OF etat ON tache
  FOR EACH ROW EXECUTE FUNCTION fn_garde_etat_tache();


-- ---------------------------------------------------------------------
-- Migration 0016 (lot 11) : recherche insensible aux accents et à la
-- casse — mêmes définitions que migrations/0016_equipe_projets_et_recherche.sql
-- (extension unaccent, « trusted » depuis PostgreSQL 13 ; fn_recherche est
-- utilisée des deux côtés du LIKE : projets, personnes, tâches, catalogue
-- du Daily log). fn_sans_accents (0014) reste pour la comparaison des noms
-- du rechargement Chronos.
-- ---------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;

CREATE OR REPLACE FUNCTION fn_recherche(t TEXT)
RETURNS TEXT AS $$
  SELECT lower(public.unaccent('public.unaccent'::regdictionary, t));
$$ LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT;


-- ---------------------------------------------------------------------
-- Migration 0017 (lot 11 b) : changement du chef de projet depuis la
-- fenêtre Informations — mêmes définitions que
-- migrations/0017_chef_projet_et_rappels_dailylog.sql. Dernier rempart
-- quand chef_projet_id CHANGE : nouveau chef actif, Chef de projet ou
-- Admin ; acteur Admin, chef titulaire ou co-chef ; projet clos : Admin
-- seulement. Sans app.current_user_id ou pendant la reprise Chronos :
-- aucune restriction (comme trg_garde_etat_tache).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_garde_chef_projet()
RETURNS TRIGGER AS $$
DECLARE
  v_acteur BIGINT := fn_app_user_id();
BEGIN
  IF NEW.chef_projet_id IS NOT DISTINCT FROM OLD.chef_projet_id
     OR v_acteur IS NULL
     OR current_setting('kairos.reprise_historique', true) = 'on' THEN
    RETURN NEW;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM utilisateur u
    WHERE u.id = NEW.chef_projet_id AND u.actif AND u.role IN ('chef_de_projet', 'admin')
  ) THEN
    RAISE EXCEPTION 'Projet % : le nouveau chef de projet (utilisateur %) doit avoir un compte actif et le rôle Chef de projet ou Admin.',
      NEW.id, NEW.chef_projet_id
      USING ERRCODE = 'check_violation', CONSTRAINT = 'projet_chef_valide';
  END IF;
  IF EXISTS (SELECT 1 FROM utilisateur u WHERE u.id = v_acteur AND u.actif AND u.role = 'admin') THEN
    RETURN NEW;
  END IF;
  IF OLD.etat IN ('termine', 'abandonne') THEN
    RAISE EXCEPTION 'Projet % clos : rouvrez-le avant de changer de chef de projet (un Admin peut toujours le réaffecter).',
      NEW.id
      USING ERRCODE = 'insufficient_privilege', CONSTRAINT = 'projet_chef_change';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM utilisateur u
    WHERE u.id = v_acteur AND u.actif AND u.role NOT IN ('client', 'rh')
      AND (OLD.chef_projet_id = u.id
           OR EXISTS (SELECT 1 FROM projet_co_chef cc
                      WHERE cc.projet_id = OLD.id AND cc.utilisateur_id = u.id))
  ) THEN
    RAISE EXCEPTION 'Projet % : seuls le chef de projet, un co-chef ou un Admin peuvent changer de chef de projet.',
      NEW.id
      USING ERRCODE = 'insufficient_privilege', CONSTRAINT = 'projet_chef_change';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_garde_chef_projet ON projet;
CREATE TRIGGER trg_garde_chef_projet
  BEFORE UPDATE OF chef_projet_id ON projet
  FOR EACH ROW EXECUTE FUNCTION fn_garde_chef_projet();


-- ---------------------------------------------------------------------
-- Migration 0018 (lot 12) : modes « Voir comme » / « Agir comme » et date
-- simulée — mêmes définitions que migrations/0018_modes_admin_et_date_simulee.sql
-- (audit_log.admin_reel_id et fn_audit_log : voir plus haut ;
-- fn_dailylog_garde : section 0014). fn_aujourdhui rend la date du réglage
-- kairos.date_simulee (posé par l'appli seulement si KAIROS_MODE_TEST=true)
-- ou « aujourd'hui » au fuseau donné.
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_audit_admin_reel ON audit_log (admin_reel_id) WHERE admin_reel_id IS NOT NULL;

CREATE OR REPLACE FUNCTION fn_date_simulee()
RETURNS DATE AS $$
DECLARE
  v TEXT := current_setting('kairos.date_simulee', true);
BEGIN
  IF v IS NULL OR v !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
    RETURN NULL;
  END IF;
  RETURN v::DATE;
EXCEPTION WHEN others THEN
  RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;


-- ---------------------------------------------------------------------
-- Migration 0019 (lot 13) : état du projet recalculé, instant simulé,
-- vraie date — mêmes définitions que
-- migrations/0019_lot13_etat_projet_et_temps.sql (notification.projet_id,
-- notification.simulee et post_evenement_check : voir plus haut ;
-- fn_dailylog_garde : section 0014).
-- ---------------------------------------------------------------------
-- Lots 18 et 20 (migrations 0023, 0024) : Bloqué tant qu'une tâche bloquée
-- n'a pas été suivie d'une tâche En cours créée après son blocage.
CREATE OR REPLACE FUNCTION fn_etat_projet_recalcule(p_etat projet_etat_enum, p_projet BIGINT)
RETURNS projet_etat_enum AS $$
  SELECT CASE
    WHEN p_etat NOT IN ('en_cours', 'bloque') THEN p_etat
    WHEN EXISTS (
      SELECT 1 FROM tache b
      WHERE b.projet_id = p_projet AND b.etat = 'bloque'
        AND NOT EXISTS (SELECT 1 FROM tache c
                        WHERE c.projet_id = p_projet AND c.etat = 'en_cours'
                          AND c.created_at > COALESCE(b.bloque_le, b.created_at))
    ) THEN 'bloque'::projet_etat_enum
    ELSE 'en_cours'::projet_etat_enum
  END
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION fn_instant_simule()
RETURNS TIMESTAMPTZ AS $$
DECLARE
  v TEXT := current_setting('kairos.instant_simule', true);
  t TIMESTAMPTZ;
BEGIN
  IF v IS NULL OR v !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{1,6})?)?([+-][0-9]{2}:[0-9]{2}|Z)$' THEN
    RETURN NULL;
  END IF;
  t := v::TIMESTAMPTZ;
  IF t < TIMESTAMPTZ '2000-01-01 00:00+00' OR t >= TIMESTAMPTZ '2100-01-01 00:00+00' THEN
    RETURN NULL;
  END IF;
  RETURN t;
EXCEPTION WHEN others THEN
  RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION fn_aujourdhui(p_fuseau TEXT DEFAULT 'Africa/Tunis')
RETURNS DATE AS $$
  SELECT COALESCE((fn_instant_simule() AT TIME ZONE COALESCE(p_fuseau, 'Africa/Tunis'))::DATE,
                  fn_date_simulee(),
                  (now() AT TIME ZONE COALESCE(p_fuseau, 'Africa/Tunis'))::DATE)
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION fn_aujourdhui_reel(p_fuseau TEXT DEFAULT 'Africa/Tunis')
RETURNS DATE AS $$
  SELECT (now() AT TIME ZONE COALESCE(p_fuseau, 'Africa/Tunis'))::DATE
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION fn_date_ecriture(p_fuseau TEXT DEFAULT 'Africa/Tunis')
RETURNS DATE AS $$
  SELECT LEAST(fn_aujourdhui(p_fuseau), fn_aujourdhui_reel(p_fuseau))
$$ LANGUAGE sql STABLE;

-- Lot 20 (migration 0024) : « maintenant » en mode test (date simulée) pour
-- l'horodatage des créations ; l'audit garde l'heure réelle.
CREATE OR REPLACE FUNCTION fn_maintenant()
RETURNS TIMESTAMPTZ AS $$
  SELECT LEAST(COALESCE(fn_instant_simule(), clock_timestamp()), clock_timestamp())
$$ LANGUAGE sql VOLATILE;
COMMENT ON FUNCTION fn_maintenant() IS
  'Horodatage d''une écriture (0024, 0025) : instant simulé (mode test) ou instant réel de l''écriture, jamais après l''instant réel.';

ALTER TABLE projet ALTER COLUMN created_at SET DEFAULT fn_maintenant();
ALTER TABLE tache ALTER COLUMN created_at SET DEFAULT fn_maintenant();
ALTER TABLE post ALTER COLUMN created_at SET DEFAULT fn_maintenant();
ALTER TABLE post_commentaire ALTER COLUMN created_at SET DEFAULT fn_maintenant();
ALTER TABLE notification ALTER COLUMN created_at SET DEFAULT fn_maintenant();
ALTER TABLE projet_co_chef ALTER COLUMN created_at SET DEFAULT fn_maintenant();
ALTER TABLE projet_intervenant ALTER COLUMN created_at SET DEFAULT fn_maintenant();
ALTER TABLE post_reaction ALTER COLUMN created_at SET DEFAULT fn_maintenant();
ALTER TABLE projet_ancien_membre ALTER COLUMN depuis SET DEFAULT fn_maintenant();

-- Lot 21 (migration 0025) : anciens participants, lecture seule gardée.
CREATE OR REPLACE FUNCTION fn_garder_ancien_membre()
RETURNS TRIGGER AS $$
DECLARE
  v_projet BIGINT;
  v_user   BIGINT;
BEGIN
  IF TG_TABLE_NAME = 'tache_intervenant' THEN
    SELECT projet_id INTO v_projet FROM tache WHERE id = OLD.tache_id;
    v_user := OLD.utilisateur_id;
  ELSIF TG_TABLE_NAME = 'projet' THEN
    IF NEW.chef_projet_id IS NOT DISTINCT FROM OLD.chef_projet_id THEN
      RETURN NULL;
    END IF;
    v_projet := OLD.id;
    v_user := OLD.chef_projet_id;
  ELSE
    v_projet := OLD.projet_id;
    v_user := OLD.utilisateur_id;
  END IF;
  -- Projet en cours de suppression (cascade) : rien à garder.
  IF v_projet IS NOT NULL AND v_user IS NOT NULL
     AND EXISTS (SELECT 1 FROM projet WHERE id = v_projet) THEN
    INSERT INTO projet_ancien_membre (projet_id, utilisateur_id)
    VALUES (v_projet, v_user)
    ON CONFLICT DO NOTHING;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ancien_membre_co_chef ON projet_co_chef;
CREATE TRIGGER trg_ancien_membre_co_chef AFTER DELETE ON projet_co_chef
  FOR EACH ROW EXECUTE FUNCTION fn_garder_ancien_membre();
DROP TRIGGER IF EXISTS trg_ancien_membre_intervenant ON projet_intervenant;
CREATE TRIGGER trg_ancien_membre_intervenant AFTER DELETE ON projet_intervenant
  FOR EACH ROW EXECUTE FUNCTION fn_garder_ancien_membre();
DROP TRIGGER IF EXISTS trg_ancien_membre_tache ON tache_intervenant;
CREATE TRIGGER trg_ancien_membre_tache AFTER DELETE ON tache_intervenant
  FOR EACH ROW EXECUTE FUNCTION fn_garder_ancien_membre();
DROP TRIGGER IF EXISTS trg_ancien_membre_chef ON projet;
CREATE TRIGGER trg_ancien_membre_chef AFTER UPDATE OF chef_projet_id ON projet
  FOR EACH ROW EXECUTE FUNCTION fn_garder_ancien_membre();

-- Lot 20 (migration 0024) : notifications liées à un commentaire ; index des
-- clés étrangères post_id et tache_id.
ALTER TABLE notification ADD COLUMN commentaire_id BIGINT REFERENCES post_commentaire(id);
CREATE INDEX idx_notification_post ON notification (post_id) WHERE post_id IS NOT NULL;
CREATE INDEX idx_notification_tache ON notification (tache_id) WHERE tache_id IS NOT NULL;
CREATE INDEX idx_notification_commentaire ON notification (commentaire_id) WHERE commentaire_id IS NOT NULL;


-- Commentaires posés par les migrations 0019 à 0021 (lot 20, revue QA n° 17a :
-- la base créée par schema.sql seul doit être identique à la base migrée).
COMMENT ON COLUMN notification.projet_id IS 'Projet ouvert par la notification quand elle ne porte ni post ni tâche (0019).';
COMMENT ON COLUMN notification.simulee IS 'Rappel créé en mode test (« Simuler le rappel du jour », 0019) : ignoré par le dédoublonnage des vrais rappels.';
COMMENT ON COLUMN post.modifie_le IS 'Dernière modification du texte par son auteur (0021).';
COMMENT ON COLUMN post.supprime_le IS 'Suppression logique (0021) : le post n''apparaît plus nulle part ; « Annuler » la lève.';
COMMENT ON COLUMN post.supprime_par IS 'Personne qui a supprimé le post (auteur, chef, co-chef ou Admin, 0021).';
COMMENT ON COLUMN post_commentaire.supprime_le IS 'Suppression logique (0021), réponses comprises.';
COMMENT ON COLUMN post_commentaire_piece_jointe.retire_le IS 'Retrait (0021) : plus téléchargeable ; fichier effacé 30 jours après.';
COMMENT ON COLUMN post_piece_jointe.retire_le IS 'Retrait (0021) : plus téléchargeable ; fichier effacé 30 jours après.';
COMMENT ON COLUMN tache.bloque_le IS 'Début du dernier blocage (0020) : nombre de jours de blocage.';
COMMENT ON COLUMN tache.bloque_motif IS 'Motif du dernier blocage (« Qu''est-ce qui bloque ? », 0020) ; affiché tant que la tâche est bloquée.';
COMMENT ON COLUMN tache.bloque_par IS 'Personne qui a signalé le dernier blocage (0020).';
COMMENT ON TABLE utilisateur_preference IS 'Réglages d''affichage du compte (0021) : Deadlines dépliées sur l''accueil, tâches proposées dans le Daily log.';

-- ---------------------------------------------------------------------
-- Migrations déjà intégrées à ce fichier : une base créée depuis
-- schema.sql les marque comme appliquées, pour que le premier
-- `flask migrer` ne les rejoue pas (voir app/__init__.py). À compléter à
-- chaque nouvelle migration reportée ici.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     VARCHAR(255) PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Empreinte SHA-256 du fichier, enregistrée par `flask migrer` (0013) :
  -- une migration modifiée après son application est signalée.
  checksum    VARCHAR(64)
);
INSERT INTO schema_migrations (version) VALUES
  ('0001_equipe_urbs_ipco'),
  ('0002_avatar_chemin'),
  ('0003_reset_password_et_securite'),
  ('0004_post_evenement_tache'),
  ('0005_integrite_et_performance'),
  ('0006_heures_par_role'),
  ('0007_commentaires_reseau_social'),
  ('0008_dailylog_jour'),
  ('0009_fil_information_commentaires'),
  ('0010_projet_client'),
  ('0011_roles_et_projets_clos'),
  ('0012_controle_des_dates'),
  ('0013_rattrapage_et_integrite'),
  ('0014_dailylog_v9'),
  ('0015_etats_taches_reserves'),
  ('0016_equipe_projets_et_recherche'),
  ('0017_chef_projet_et_rappels_dailylog'),
  ('0018_modes_admin_et_date_simulee'),
  ('0019_lot13_etat_projet_et_temps'),
  ('0020_lot14_blocage_et_cloture'),
  ('0021_lot15_posts_et_preferences'),
  ('0022_lot17_fil_vu'),
  ('0023_equipes_vd_et_etat_projet'),
  ('0024_lot20_droits_dates_et_garde'),
  ('0025_lot21_participants_horloge_et_gardes')
ON CONFLICT (version) DO NOTHING;

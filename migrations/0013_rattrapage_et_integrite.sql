-- 0013 — Rattrapage des migrations 0011/0012 modifiées après publication,
-- intégrité des données, index, garde-fous des décisions validées
-- (audit données du lot 10, 2026-10-07 ; fusionnée avec la migration
-- « co-chef automatique » de l'audit sécurité : une seule migration 0013,
-- 0014 étant réservée au Daily log).
--
-- Pourquoi : `flask migrer` ne rejoue jamais une migration déjà inscrite
-- dans schema_migrations. Une base installée entre la 1re et la 2e version
-- de 0011 (80ccd42 -> 505757e) ou de 0012 (dfc8464 -> 1c2d32f) garde
-- l'ancienne fonction / les anciens triggers, sans que rien ne le signale.
-- Cette migration RÉÉCRIT donc tous les objets concernés à leur définition
-- de référence (CREATE OR REPLACE / DROP ... IF EXISTS + CREATE), quel que
-- soit l'état de départ. Règle pour la suite : on n'édite JAMAIS une
-- migration publiée, on en ajoute une.
--
-- Rejouable : peut être jouée deux fois (ou sur une base neuve) sans
-- erreur ni effet supplémentaire. Aucune ligne supprimée. Une donnée
-- ancienne qui viole une nouvelle contrainte ne fait jamais échouer la
-- migration (donc le démarrage du conteneur) : WARNING dans les journaux,
-- voir la section 3.

-- Ne jamais rester bloqué au démarrage du conteneur derrière une session
-- qui tient un verrou (psql ouvert, sauvegarde) : échec net au bout de 15 s.
SELECT set_config('lock_timeout', '15s', true);

-- ---------------------------------------------------------------------
-- 0. Utilitaire : id de l'utilisateur applicatif courant (SET LOCAL
--    app.current_user_id, voir app/db.py), NULL si absent / vide / invalide.
--    Remplace le bloc EXCEPTION (une sous-transaction par ligne modifiée).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_app_user_id()
RETURNS BIGINT AS $$
  SELECT CASE WHEN s ~ '^[0-9]{1,18}$' THEN s::BIGINT END
  FROM (SELECT current_setting('app.current_user_id', true) AS s) x
$$ LANGUAGE sql STABLE;

-- updated_by n'est plus écrasé par NULL quand aucune variable de session
-- n'est posée (script, migration) : la valeur explicite de la requête, ou
-- l'auteur précédent, est conservée.
CREATE OR REPLACE FUNCTION set_updated_at_and_by()
RETURNS TRIGGER AS $$
DECLARE
  v_user_id BIGINT := fn_app_user_id();
BEGIN
  NEW.updated_at = now();
  IF v_user_id IS NOT NULL THEN
    NEW.updated_by = v_user_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_audit_log()
RETURNS TRIGGER AS $$
DECLARE
  v_user_id BIGINT := fn_app_user_id();
BEGIN
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

-- ---------------------------------------------------------------------
-- 1. Rattrapage 0011 (version de référence 505757e).
-- ---------------------------------------------------------------------
ALTER TABLE projet ADD COLUMN IF NOT EXISTS date_cloture DATE;

CREATE OR REPLACE VIEW v_projet_visibilite AS
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
    ))
  );

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

-- Triggers d'ajout (présents depuis schema.sql d'origine, recréés pour
-- garantir leur forme quel que soit l'historique de la base).
DROP TRIGGER IF EXISTS trg_check_projet_chef_role ON projet;
CREATE TRIGGER trg_check_projet_chef_role
  BEFORE INSERT OR UPDATE OF chef_projet_id ON projet
  FOR EACH ROW EXECUTE FUNCTION fn_check_projet_chef_role();
DROP TRIGGER IF EXISTS trg_check_projet_co_chef_role ON projet_co_chef;
CREATE TRIGGER trg_check_projet_co_chef_role
  BEFORE INSERT OR UPDATE ON projet_co_chef
  FOR EACH ROW EXECUTE FUNCTION fn_check_projet_co_chef_role();
DROP TRIGGER IF EXISTS trg_check_projet_intervenant_role ON projet_intervenant;
CREATE TRIGGER trg_check_projet_intervenant_role
  BEFORE INSERT OR UPDATE ON projet_intervenant
  FOR EACH ROW EXECUTE FUNCTION fn_check_projet_intervenant_role();
DROP TRIGGER IF EXISTS trg_check_tache_intervenant_role ON tache_intervenant;
CREATE TRIGGER trg_check_tache_intervenant_role
  BEFORE INSERT OR UPDATE ON tache_intervenant
  FOR EACH ROW EXECUTE FUNCTION fn_check_tache_intervenant_role();

-- ---------------------------------------------------------------------
-- 2. Rattrapage 0012 (version de référence 1c2d32f) + correctif : changer
--    seulement les honoraires d'un projet ancien aux dates incohérentes
--    n'est plus refusé (chaque règle ne s'évalue que si SES colonnes
--    changent).
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
-- 3. Contraintes d'intégrité, ajoutées sans jamais faire échouer la
--    migration sur des données anciennes :
--    - clé étrangère : ajoutée NOT VALID (s'applique aux nouvelles
--      écritures), validée si l'existant la respecte ;
--    - CHECK : ajoutée seulement si AUCUNE ligne existante ne la viole —
--      un CHECK NOT VALID serait revérifié à chaque UPDATE de la ligne
--      fautive (même pour changer une autre colonne) et bloquerait son
--      utilisation. Sinon WARNING : nettoyer, puis rejouer ce fichier à la
--      main (il est idempotent).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION pg_temp.ajouter_contrainte(p_table TEXT, p_nom TEXT, p_def TEXT, p_violations TEXT)
RETURNS VOID AS $$
DECLARE
  v_n BIGINT;
  v_est_check BOOLEAN := p_def ILIKE 'CHECK%';
  v_existe BOOLEAN := EXISTS (SELECT 1 FROM pg_constraint WHERE conname = p_nom AND conrelid = p_table::regclass);
  v_valide BOOLEAN := EXISTS (SELECT 1 FROM pg_constraint WHERE conname = p_nom AND conrelid = p_table::regclass AND convalidated);
BEGIN
  IF v_valide THEN
    RETURN;
  END IF;
  EXECUTE 'SELECT count(*) FROM (' || p_violations || ') v' INTO v_n;
  IF v_n > 0 AND v_est_check AND NOT v_existe THEN
    RAISE WARNING 'Contrainte %.% NON posée : % ligne(s) existante(s) la violent. Corriger puis rejouer 0013 (requête : %).',
      p_table, p_nom, v_n, p_violations;
    RETURN;
  END IF;
  IF NOT v_existe THEN
    EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s NOT VALID', p_table, p_nom, p_def);
  END IF;
  IF v_n = 0 THEN
    EXECUTE format('ALTER TABLE %I VALIDATE CONSTRAINT %I', p_table, p_nom);
  ELSE
    RAISE WARNING 'Contrainte %.% laissée NOT VALID : % ligne(s) existante(s) la violent (requête : %).',
      p_table, p_nom, v_n, p_violations;
  END IF;
END;
$$ LANGUAGE plpgsql;

-- 3a. Contrainte de 0005 restée NOT VALID sur toute base migrée.
SELECT pg_temp.ajouter_contrainte('dailylog_entree', 'dailylog_entree_heures_valides',
  'CHECK (heures <> ''NaN'' AND heures <= 24)',
  'SELECT 1 FROM dailylog_entree WHERE NOT (heures <> ''NaN'' AND heures <= 24)');

-- 3b. Une ligne d'heures (ou un post) ne peut pointer que la tâche de SON
--     projet. Clé (id, projet_id) unique sur tache pour servir de cible.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tache_id_projet_unique') THEN
    ALTER TABLE tache ADD CONSTRAINT tache_id_projet_unique UNIQUE (id, projet_id);
  END IF;
END $$;
SELECT pg_temp.ajouter_contrainte('dailylog_entree', 'dailylog_entree_tache_du_projet_fk',
  'FOREIGN KEY (tache_id, projet_id) REFERENCES tache (id, projet_id)',
  'SELECT 1 FROM dailylog_entree d JOIN tache t ON t.id = d.tache_id WHERE t.projet_id <> d.projet_id');
SELECT pg_temp.ajouter_contrainte('post', 'post_tache_du_projet_fk',
  'FOREIGN KEY (tache_id, projet_id) REFERENCES tache (id, projet_id)',
  'SELECT 1 FROM post p JOIN tache t ON t.id = p.tache_id WHERE p.projet_id IS NOT NULL AND t.projet_id <> p.projet_id');

-- 3c. Pas d'auto-référence.
SELECT pg_temp.ajouter_contrainte('projet', 'projet_phase_liee_pas_soi_meme',
  'CHECK (phase_liee_id <> id)',
  'SELECT 1 FROM projet WHERE phase_liee_id = id');
SELECT pg_temp.ajouter_contrainte('post', 'post_parent_pas_soi_meme',
  'CHECK (parent_post_id <> id)',
  'SELECT 1 FROM post WHERE parent_post_id = id');

-- 3d. Vocabulaires fermés (valeurs écrites par le code au 2026-10-07).
SELECT pg_temp.ajouter_contrainte('notification', 'notification_categorie_valide',
  'CHECK (categorie IN (''projet'', ''rh_info''))',
  'SELECT 1 FROM notification WHERE categorie NOT IN (''projet'', ''rh_info'')');
SELECT pg_temp.ajouter_contrainte('tentative_securite', 'tentative_securite_type_valide',
  'CHECK (type IN (''connexion'', ''connexion_ip'', ''mot_de_passe_oublie''))',
  'SELECT 1 FROM tentative_securite WHERE type NOT IN (''connexion'', ''connexion_ip'', ''mot_de_passe_oublie'')');
SELECT pg_temp.ajouter_contrainte('audit_log', 'audit_log_action_valide',
  'CHECK (action IN (''INSERT'', ''UPDATE'', ''DELETE''))',
  'SELECT 1 FROM audit_log WHERE action NOT IN (''INSERT'', ''UPDATE'', ''DELETE'')');

-- 3e. Email : ni vide, ni espaces autour (la CLI create-user n'en vérifiait rien).
SELECT pg_temp.ajouter_contrainte('utilisateur', 'utilisateur_email_forme',
  'CHECK (email = btrim(email) AND position(''@'' IN email) > 1)',
  'SELECT 1 FROM utilisateur WHERE NOT (email = btrim(email) AND position(''@'' IN email) > 1)');

-- ---------------------------------------------------------------------
-- 4. Index (mesurés sur 1 200 projets / 153 000 lignes d'heures /
--    300 000 lignes d'audit, voir le rapport d'audit données).
-- ---------------------------------------------------------------------
-- Préfixe exact de idx_dailylog_unique (utilisateur_id, date, ...) : redondant.
DROP INDEX IF EXISTS idx_dailylog_user_date;
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

-- ---------------------------------------------------------------------
-- 5. Décision 1 (validée) : le RH ne peut rien faire sur un compte Admin
--    (créer, modifier, changer le mot de passe, désactiver, promouvoir).
--    + Il reste toujours au moins un Admin actif (sérialisé par un verrou
--    consultatif : deux rétrogradations simultanées ne peuvent pas passer).
--    Sans app.current_user_id (CLI, scripts) : seule la règle « dernier
--    Admin » s'applique.
-- ---------------------------------------------------------------------
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

-- ---------------------------------------------------------------------
-- 6. Décision 3 (validée) : un utilisateur de rôle Chef de projet ajouté
--    comme intervenant d'un projet OU d'une tâche en devient co-chef
--    automatiquement (quel que soit le chemin : route, script, SQL). Le
--    chef titulaire n'est jamais inscrit co-chef de son propre projet.
--    Rattrapage des rattachements existants. Effet de bord connu : ses
--    heures passent de « intervenant » à « chef » dans la répartition par
--    rôle.
-- ---------------------------------------------------------------------
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

INSERT INTO projet_co_chef (projet_id, utilisateur_id)
SELECT pi.projet_id, pi.utilisateur_id
FROM projet_intervenant pi
JOIN utilisateur u ON u.id = pi.utilisateur_id
JOIN projet p ON p.id = pi.projet_id
WHERE u.role = 'chef_de_projet' AND p.chef_projet_id <> u.id
ON CONFLICT DO NOTHING;

INSERT INTO projet_co_chef (projet_id, utilisateur_id)
SELECT DISTINCT t.projet_id, ti.utilisateur_id
FROM tache_intervenant ti
JOIN tache t ON t.id = ti.tache_id
JOIN utilisateur u ON u.id = ti.utilisateur_id
JOIN projet p ON p.id = t.projet_id
WHERE u.role = 'chef_de_projet' AND p.chef_projet_id <> u.id
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------
-- 7. Projets clos sans date de clôture (reprise Chronos chargée après
--    0011) : même règle que 0011, mais jamais avant la dernière heure
--    saisie, et sans réécrire updated_at (trigger désactivé le temps de
--    l'UPDATE : sinon tous les projets semblent « modifiés aujourd'hui »).
-- ---------------------------------------------------------------------
ALTER TABLE projet DISABLE TRIGGER trg_projet_updated_at;
UPDATE projet p SET date_cloture = COALESCE(
    (SELECT max(po.created_at)::date FROM post po
      WHERE po.projet_id = p.id AND po.evenement = 'etat_projet'),
    GREATEST(p.date_fin, (SELECT max(de.date) FROM dailylog_entree de WHERE de.projet_id = p.id)),
    p.updated_at::date)
WHERE p.etat IN ('termine', 'abandonne') AND p.date_cloture IS NULL;
ALTER TABLE projet ENABLE TRIGGER trg_projet_updated_at;

-- ---------------------------------------------------------------------
-- 9. Révocation des sessions (audit sécurité I7) : le cookie de session
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
-- 8. Empreinte des migrations (remplie par `flask migrer`, voir le
--    correctif de app/__init__.py) : détecte une migration modifiée après
--    application.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     VARCHAR(255) PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS checksum VARCHAR(64);

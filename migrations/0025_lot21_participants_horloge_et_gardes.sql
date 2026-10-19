-- 0025 — Lot 21 (contre-expertise du lot 20 et test Chrome du 19/10/2026,
-- décisions du gérant).
--
-- 1. Anciens participants (décision du gérant) : toute personne qui a
--    participé à un projet (tâche, post, commentaire, heures, rattachement)
--    garde la LECTURE après en avoir été retirée, même sans tâche close.
--    Table projet_ancien_membre, remplie à chaque retrait (triggers) et
--    reprise de l'historique ; v_projet_visibilite la lit, jamais
--    v_projet_action (lecture seule).
-- 2. Horloge (mode test) : fn_maintenant suit l'instant simulé à la
--    microseconde (fn_instant_simule accepte les fractions de seconde),
--    l'instant d'écriture (clock_timestamp) sinon, et n'est JAMAIS après
--    l'instant réel (décision 5 du lot 13 : aucune écriture datée dans le
--    futur réel). updated_at et les rattachements suivent fn_maintenant.
-- 3. updated_at réécrit par la migration 0024 (recalcul des états,
--    bloque_le comblé) : rendu depuis le journal d'audit.
-- 4. Date de fin des tâches closes sans date (Abandonnée, Arrêtée,
--    Vérifiée) : posée depuis la dernière modification.
-- 5. Daily log : pas d'heures nouvelles sur une tâche close après sa date
--    de fin, gardé en base (la saisie et la clôture peuvent se croiser).
-- 6. Préférence « Deadlines de l'accueil » des clients : les valeurs
--    « repliées » héritées du lot 19 (jamais choisies) redeviennent NULL.
-- 7. Post épinglé (demande du gérant) : une Information par projet, en tête
--    du fil de la fiche.
--
-- Rejouable : CREATE OR REPLACE, IF [NOT] EXISTS, ON CONFLICT, UPDATE
-- idempotents. Mêmes définitions dans schema.sql.

SELECT set_config('lock_timeout', '15s', true);

-- 2. Horloge --------------------------------------------------------------
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

CREATE OR REPLACE FUNCTION fn_maintenant()
RETURNS TIMESTAMPTZ AS $$
  SELECT LEAST(COALESCE(fn_instant_simule(), clock_timestamp()), clock_timestamp())
$$ LANGUAGE sql VOLATILE;
COMMENT ON FUNCTION fn_maintenant() IS
  'Horodatage d''une écriture (0024, 0025) : instant simulé (mode test) ou instant réel de l''écriture, jamais après l''instant réel.';

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

ALTER TABLE projet_co_chef ALTER COLUMN created_at SET DEFAULT fn_maintenant();
ALTER TABLE projet_intervenant ALTER COLUMN created_at SET DEFAULT fn_maintenant();
ALTER TABLE post_reaction ALTER COLUMN created_at SET DEFAULT fn_maintenant();

-- 1. Anciens participants ---------------------------------------------------
CREATE TABLE IF NOT EXISTS projet_ancien_membre (
  projet_id      BIGINT NOT NULL REFERENCES projet(id) ON DELETE CASCADE,
  utilisateur_id BIGINT NOT NULL REFERENCES utilisateur(id),
  depuis         TIMESTAMPTZ NOT NULL DEFAULT fn_maintenant(),
  PRIMARY KEY (projet_id, utilisateur_id)
);
CREATE INDEX IF NOT EXISTS idx_projet_ancien_membre_user ON projet_ancien_membre(utilisateur_id);
COMMENT ON TABLE projet_ancien_membre IS
  'Personnes qui ont participé à un projet puis en ont été retirées (0025) : lecture seule gardée (v_projet_visibilite).';

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

-- Reprise : tous ceux qui ont participé (tâche, post, commentaire, heures)
-- et ceux qui ont été retirés avant ce lot (journal d'audit).
INSERT INTO projet_ancien_membre (projet_id, utilisateur_id)
SELECT DISTINCT x.projet_id, x.utilisateur_id
FROM (
  SELECT projet_id, auteur_id AS utilisateur_id FROM post WHERE projet_id IS NOT NULL
  UNION
  SELECT p.projet_id, c.auteur_id FROM post_commentaire c JOIN post p ON p.id = c.post_id
  WHERE p.projet_id IS NOT NULL
  UNION
  SELECT projet_id, utilisateur_id FROM dailylog_entree
  UNION
  SELECT t.projet_id, ti.utilisateur_id FROM tache_intervenant ti JOIN tache t ON t.id = ti.tache_id
  UNION
  SELECT (a.donnees_avant->>'projet_id')::BIGINT, (a.donnees_avant->>'utilisateur_id')::BIGINT
  FROM audit_log a
  WHERE a.action = 'DELETE' AND a.table_cible IN ('projet_intervenant', 'projet_co_chef')
  UNION
  SELECT t.projet_id, (a.donnees_avant->>'utilisateur_id')::BIGINT
  FROM audit_log a JOIN tache t ON t.id = (a.donnees_avant->>'tache_id')::BIGINT
  WHERE a.action = 'DELETE' AND a.table_cible = 'tache_intervenant'
) x
JOIN projet p ON p.id = x.projet_id
JOIN utilisateur u ON u.id = x.utilisateur_id
WHERE u.role NOT IN ('client', 'rh', 'admin')
ON CONFLICT DO NOTHING;

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
      OR EXISTS (SELECT 1 FROM projet_ancien_membre am WHERE am.projet_id = p.id AND am.utilisateur_id = u.id)
    ))
  );

-- 3. updated_at rendus (réécrits par 0024, même transaction que son
--    inscription dans schema_migrations) --------------------------------------
ALTER TABLE tache DISABLE TRIGGER trg_tache_updated_at;
ALTER TABLE projet DISABLE TRIGGER trg_projet_updated_at;
WITH t0 AS (
  SELECT applied_at FROM schema_migrations WHERE version = '0024_lot20_droits_dates_et_garde'
), avant AS (
  SELECT DISTINCT ON (a.table_cible, a.ligne_id) a.table_cible, a.ligne_id,
         (a.donnees_avant->>'updated_at')::TIMESTAMPTZ AS updated_at
  FROM audit_log a JOIN t0 ON a.created_at = t0.applied_at
  WHERE a.action = 'UPDATE' AND a.utilisateur_id IS NULL AND a.table_cible IN ('tache', 'projet')
    AND a.donnees_avant ? 'updated_at'
  ORDER BY a.table_cible, a.ligne_id, a.id
)
UPDATE tache t SET updated_at = avant.updated_at
FROM avant, t0
WHERE avant.table_cible = 'tache' AND avant.ligne_id = t.id AND t.updated_at = t0.applied_at;
WITH t0 AS (
  SELECT applied_at FROM schema_migrations WHERE version = '0024_lot20_droits_dates_et_garde'
), avant AS (
  SELECT DISTINCT ON (a.ligne_id) a.ligne_id, (a.donnees_avant->>'updated_at')::TIMESTAMPTZ AS updated_at
  FROM audit_log a JOIN t0 ON a.created_at = t0.applied_at
  WHERE a.action = 'UPDATE' AND a.utilisateur_id IS NULL AND a.table_cible = 'projet'
    AND a.donnees_avant ? 'updated_at'
  ORDER BY a.ligne_id, a.id
)
UPDATE projet p SET updated_at = avant.updated_at
FROM avant, t0
WHERE avant.ligne_id = p.id AND p.updated_at = t0.applied_at;

-- 4. Date de fin des tâches closes sans date --------------------------------
UPDATE tache SET date_fin = (updated_at AT TIME ZONE 'Africa/Tunis')::DATE
WHERE etat IN ('termine', 'verifie', 'abandonne', 'arret') AND date_fin IS NULL;
ALTER TABLE tache ENABLE TRIGGER trg_tache_updated_at;
ALTER TABLE projet ENABLE TRIGGER trg_projet_updated_at;

-- 5. Daily log : tâche close ------------------------------------------------
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

-- 6. Préférence des clients -------------------------------------------------
UPDATE utilisateur_preference up SET accueil_deadlines = NULL
FROM utilisateur u
WHERE u.id = up.utilisateur_id AND u.role = 'client' AND up.accueil_deadlines = false;

-- 7. Post épinglé (demande du gérant, 19/10) -----------------------------------
-- Une Information écrite par une personne (pas un évènement automatique)
-- peut être épinglée en tête du fil de son projet : un seul post par
-- projet, par le chef, un co-chef ou l'Admin.
ALTER TABLE post ADD COLUMN IF NOT EXISTS epingle_le TIMESTAMPTZ;
ALTER TABLE post ADD COLUMN IF NOT EXISTS epingle_par BIGINT REFERENCES utilisateur(id);
ALTER TABLE post DROP CONSTRAINT IF EXISTS post_epingle_check;
ALTER TABLE post ADD CONSTRAINT post_epingle_check CHECK (
  epingle_le IS NULL
  OR (projet_id IS NOT NULL AND type_code = 'information' AND evenement IS NULL AND supprime_le IS NULL));
CREATE UNIQUE INDEX IF NOT EXISTS ux_post_epingle_projet ON post(projet_id) WHERE epingle_le IS NOT NULL;
COMMENT ON COLUMN post.epingle_le IS 'Épinglé en tête du fil du projet (0025) : un seul post par projet.';
COMMENT ON COLUMN post.epingle_par IS 'Qui a épinglé le post (chef, co-chef ou Admin).';

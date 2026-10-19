-- 0024 — Lot 20 (revue d'experts et tests du 19/10/2026, décisions du gérant).
--
-- 1. Droit d'AGIR sur un projet (v_projet_action) : comme la visibilité,
--    mais une tâche close ne donne plus que la lecture. Une personne
--    retirée d'un projet d'une autre équipe garde la lecture (historique)
--    et ne peut plus agir (décision du gérant, 19/10).
-- 2. Date simulée (mode test) : tâches, posts, commentaires, notifications
--    et projets créés sont datés de l'instant simulé (fn_maintenant) ;
--    l'audit garde l'heure réelle.
-- 3. État du projet : bloque_le comblé, repli sur created_at (plus sur
--    updated_at, réécrit à chaque modification), états recalculés.
-- 4. Notifications : index sur post_id et tache_id, lien au commentaire.
-- 5. Code projet unique PAR PHASE (APS et APD d'une même affaire gardent
--    le même numéro, décision du gérant). Préférence « Deadlines de
--    l'accueil » : NULL tant qu'elle n'a pas été choisie.
-- 6. Garde du Daily log : la ligne d'avant une modification est contrôlée
--    aussi ; le chef n'a plus de passe-droit sur ses propres jours au-delà
--    de 14 jours (décision du gérant).
--
-- Rejouable : CREATE OR REPLACE, IF [NOT] EXISTS, UPDATE idempotents.
-- Mêmes définitions dans schema.sql.

SELECT set_config('lock_timeout', '15s', true);

-- 1. Droit d'agir ---------------------------------------------------------
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

-- 2. « Maintenant » en mode test -------------------------------------------
CREATE OR REPLACE FUNCTION fn_maintenant()
RETURNS TIMESTAMPTZ AS $$
  SELECT COALESCE(fn_instant_simule(), now())
$$ LANGUAGE sql STABLE;
COMMENT ON FUNCTION fn_maintenant() IS
  'Instant simulé de la requête (mode test) ou now() : horodatage des créations (0024).';

ALTER TABLE projet ALTER COLUMN created_at SET DEFAULT fn_maintenant();
ALTER TABLE tache ALTER COLUMN created_at SET DEFAULT fn_maintenant();
ALTER TABLE post ALTER COLUMN created_at SET DEFAULT fn_maintenant();
ALTER TABLE post_commentaire ALTER COLUMN created_at SET DEFAULT fn_maintenant();
ALTER TABLE notification ALTER COLUMN created_at SET DEFAULT fn_maintenant();

-- 3. État du projet --------------------------------------------------------
UPDATE tache SET bloque_le = updated_at WHERE etat = 'bloque' AND bloque_le IS NULL;

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

UPDATE projet SET etat = fn_etat_projet_recalcule(etat, id)
WHERE etat IN ('en_cours', 'bloque') AND etat <> fn_etat_projet_recalcule(etat, id);

-- 4. Notifications ---------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_notification_post ON notification (post_id) WHERE post_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_notification_tache ON notification (tache_id) WHERE tache_id IS NOT NULL;
ALTER TABLE notification ADD COLUMN IF NOT EXISTS commentaire_id BIGINT REFERENCES post_commentaire(id);
CREATE INDEX IF NOT EXISTS idx_notification_commentaire ON notification (commentaire_id) WHERE commentaire_id IS NOT NULL;

-- 5. Code projet unique par phase -----------------------------------------
ALTER TABLE projet DROP CONSTRAINT IF EXISTS projet_code_key;
CREATE UNIQUE INDEX IF NOT EXISTS projet_code_phase_uniq ON projet (code, phase);

-- 5 bis. Préférence « Deadlines de l'accueil » : NULL = jamais choisie (le
-- client voit ses deadlines dépliées tant qu'il n'a rien choisi, lot 19).
ALTER TABLE utilisateur_preference ALTER COLUMN accueil_deadlines DROP NOT NULL;
ALTER TABLE utilisateur_preference ALTER COLUMN accueil_deadlines DROP DEFAULT;

-- 5 ter. Demandes de lien de réinitialisation comptées aussi par adresse IP.
ALTER TABLE tentative_securite DROP CONSTRAINT IF EXISTS tentative_securite_type_valide;
ALTER TABLE tentative_securite ADD CONSTRAINT tentative_securite_type_valide
  CHECK (type IN ('connexion', 'connexion_ip', 'mot_de_passe_oublie', 'mot_de_passe_oublie_ip'));

-- 6. Garde du Daily log ----------------------------------------------------
-- Droit d'un acteur sur UNE ligne (nouvelle, supprimée, ou ancienne version
-- d'une ligne modifiée) : la personne elle-même dans les 14 jours, un Admin,
-- ou le chef / co-chef du projet de la ligne pour les heures D'UNE AUTRE
-- personne (jamais pour les siennes au-delà de 14 jours).
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

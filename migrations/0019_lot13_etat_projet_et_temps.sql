-- 0019 — Lot 13 (audits rôles et temps du 09/10/2026, décisions du gérant).
--
-- 1. Notifications : notification.projet_id (« ajouté au projet », « a
--    rejoint votre projet » ouvrent la fiche du projet) ; notification.simulee
--    (rappel Daily log créé par « Simuler le rappel du jour » en mode test :
--    il ne bloque jamais un vrai rappel, voir creer_rappel_dailylog).
--
-- 2. Posts automatiques : 'intervenant_tache' (ajout / retrait d'un
--    intervenant d'une tâche), 'echeance_tache' (échéance ou type changés),
--    'intervenant_projet' (intervenant retiré du projet).
--
-- 3. État du projet (décision 1) : un projet OUVERT est Bloqué si et
--    seulement si une de ses tâches est bloquée, En cours sinon.
--    fn_etat_projet_recalcule(etat, projet) donne l'état attendu ; l'appli
--    l'applique après chaque écriture de tâche ou de projet, dans la même
--    transaction (repositories/taches.py:recalculer_etat_projet) ; les
--    projets ouverts incohérents sont réalignés ici une fois (journal
--    d'audit sans auteur).
--
-- 4. Temps (mode test) :
--    - instant simulé : réglage de transaction kairos.instant_simule
--      (AAAA-MM-JJTHH:MM[:SS]±HH:MM, posé par l'appli seulement si
--      KAIROS_MODE_TEST=true) ; fn_aujourdhui(fuseau) en rend la date AU
--      FUSEAU DONNÉ (23 h 30 à Tunis = 19 h 30 à Cayenne, même jour ;
--      2 h à Tunis = la veille à Cayenne). kairos.date_simulee (0018) reste
--      lu à défaut ;
--    - fn_aujourdhui_reel(fuseau) : la vraie date, jamais simulée ;
--    - fn_date_ecriture(fuseau) = LEAST(date simulée, vraie date) : date de
--      clôture d'une tâche ou d'un projet (décision 5 : une date simulée
--      peut reculer une clôture, jamais la porter dans le futur réel) ;
--    - fn_dailylog_garde : une ligne ou une absence datée après la vraie
--      date du jour (au fuseau du titulaire) est refusée, même sous date
--      simulée (décision 5 : la date simulée sert à VOIR le futur).
--
-- Rejouable : ADD COLUMN IF NOT EXISTS, DROP … IF EXISTS / ADD, CREATE OR
-- REPLACE, CREATE INDEX IF NOT EXISTS, UPDATE idempotent. Mêmes définitions
-- dans schema.sql.

SELECT set_config('lock_timeout', '15s', true);

-- 1. Notifications ------------------------------------------------------
ALTER TABLE notification ADD COLUMN IF NOT EXISTS projet_id BIGINT REFERENCES projet(id);
ALTER TABLE notification ADD COLUMN IF NOT EXISTS simulee BOOLEAN NOT NULL DEFAULT false;
COMMENT ON COLUMN notification.projet_id IS
  'Projet ouvert par la notification quand elle ne porte ni post ni tâche (0019).';
COMMENT ON COLUMN notification.simulee IS
  'Rappel créé en mode test (« Simuler le rappel du jour », 0019) : ignoré par le dédoublonnage des vrais rappels.';
CREATE INDEX IF NOT EXISTS idx_notification_projet ON notification (projet_id) WHERE projet_id IS NOT NULL;

-- 2. Posts automatiques -------------------------------------------------
ALTER TABLE post DROP CONSTRAINT IF EXISTS post_evenement_check;
ALTER TABLE post ADD CONSTRAINT post_evenement_check
  CHECK (evenement IS NULL OR evenement IN (
    'creation_tache', 'cloture_tache', 'repost',
    'creation_projet', 'etat_tache', 'etat_projet', 'titre_tache', 'chef_projet',
    'intervenant_tache', 'echeance_tache', 'intervenant_projet'));

-- 3. État du projet -----------------------------------------------------
-- État attendu d'un projet : un projet clos (Terminé, Abandonné) garde son
-- état ; un projet ouvert est Bloqué si une de ses tâches l'est, sinon En
-- cours.
CREATE OR REPLACE FUNCTION fn_etat_projet_recalcule(p_etat projet_etat_enum, p_projet BIGINT)
RETURNS projet_etat_enum AS $$
  SELECT CASE
    WHEN p_etat NOT IN ('en_cours', 'bloque') THEN p_etat
    WHEN EXISTS (SELECT 1 FROM tache t WHERE t.projet_id = p_projet AND t.etat = 'bloque') THEN 'bloque'::projet_etat_enum
    ELSE 'en_cours'::projet_etat_enum
  END
$$ LANGUAGE sql STABLE;

UPDATE projet p SET etat = fn_etat_projet_recalcule(p.etat, p.id)
WHERE p.etat IN ('en_cours', 'bloque') AND p.etat <> fn_etat_projet_recalcule(p.etat, p.id);

-- 4. Temps --------------------------------------------------------------
-- Instant simulé de la transaction (kairos.instant_simule), NULL s'il est
-- absent, vide, invalide ou hors de 2000-2099 (une valeur forgée est
-- ignorée, jamais d'erreur).
CREATE OR REPLACE FUNCTION fn_instant_simule()
RETURNS TIMESTAMPTZ AS $$
DECLARE
  v TEXT := current_setting('kairos.instant_simule', true);
  t TIMESTAMPTZ;
BEGIN
  IF v IS NULL OR v !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2})?([+-][0-9]{2}:[0-9]{2}|Z)$' THEN
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

-- « Aujourd'hui » au fuseau donné (Tunis par défaut) : instant simulé lu à
-- ce fuseau, à défaut la date simulée (0018), sinon la vraie date.
CREATE OR REPLACE FUNCTION fn_aujourdhui(p_fuseau TEXT DEFAULT 'Africa/Tunis')
RETURNS DATE AS $$
  SELECT COALESCE((fn_instant_simule() AT TIME ZONE COALESCE(p_fuseau, 'Africa/Tunis'))::DATE,
                  fn_date_simulee(),
                  (now() AT TIME ZONE COALESCE(p_fuseau, 'Africa/Tunis'))::DATE)
$$ LANGUAGE sql STABLE;

-- La vraie date au fuseau donné, jamais simulée.
CREATE OR REPLACE FUNCTION fn_aujourdhui_reel(p_fuseau TEXT DEFAULT 'Africa/Tunis')
RETURNS DATE AS $$
  SELECT (now() AT TIME ZONE COALESCE(p_fuseau, 'Africa/Tunis'))::DATE
$$ LANGUAGE sql STABLE;

-- Date posée par une écriture (clôture d'une tâche ou d'un projet) : la
-- date simulée si elle est passée, jamais après la vraie date.
CREATE OR REPLACE FUNCTION fn_date_ecriture(p_fuseau TEXT DEFAULT 'Africa/Tunis')
RETURNS DATE AS $$
  SELECT LEAST(fn_aujourdhui(p_fuseau), fn_aujourdhui_reel(p_fuseau))
$$ LANGUAGE sql STABLE;

-- fn_dailylog_garde (0014, 0018) : en plus, rien après la vraie date du
-- jour du titulaire (contrainte dailylog_futur_reel), date simulée ou non.
CREATE OR REPLACE FUNCTION fn_dailylog_garde()
RETURNS TRIGGER AS $$
DECLARE
  v_ligne        JSONB;
  v_proprio      BIGINT;
  v_date         DATE;
  v_projet       BIGINT;
  v_acteur       BIGINT := fn_app_user_id();
  v_role_proprio role_enum;
  v_fuseau       TEXT;
  v_role_acteur  role_enum;
  v_actif_acteur BOOLEAN;
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
  v_projet  := (v_ligne->>'projet_id')::BIGINT;
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
  IF v_acteur = v_proprio AND v_date >= v_aujourdhui - 14 THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  SELECT role, actif INTO v_role_acteur, v_actif_acteur FROM utilisateur WHERE id = v_acteur;
  IF v_role_acteur = 'admin' AND v_actif_acteur THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  IF v_actif_acteur AND v_role_acteur = 'chef_de_projet' THEN
    IF TG_TABLE_NAME = 'dailylog_entree' THEN
      IF EXISTS (SELECT 1 FROM projet p WHERE p.id = v_projet AND p.chef_projet_id = v_acteur)
         OR EXISTS (SELECT 1 FROM projet_co_chef cc WHERE cc.projet_id = v_projet AND cc.utilisateur_id = v_acteur) THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
      END IF;
    ELSIF TG_OP = 'INSERT' AND NOT (v_ligne->>'absent')::BOOLEAN THEN
      RETURN NEW;  -- première ligne « état du jour » d'une correction (sans absence)
    END IF;
  END IF;
  RAISE EXCEPTION 'Daily log du % verrouillé : au-delà de 14 jours (ou pour une autre personne), seul le chef du projet ou un Admin peut corriger (utilisateur %).',
    v_date, v_proprio
    USING ERRCODE = 'insufficient_privilege', CONSTRAINT = 'dailylog_fenetre';
END;
$$ LANGUAGE plpgsql;

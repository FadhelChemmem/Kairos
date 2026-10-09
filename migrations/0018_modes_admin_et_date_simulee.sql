-- 0018 — Lot 12 (demande du gérant) : « Voir comme… », « Agir comme… » et
-- date simulée pour la phase de test.
--
-- 1. Journal d'audit : audit_log.admin_reel_id, l'Admin qui a réellement
--    agi quand il « agit comme » un autre compte (KAIROS_MODE_TEST=true).
--    L'appli pose SET LOCAL app.admin_reel_id = '<id>' dans la même
--    transaction que app.current_user_id (= le compte cible) ; fn_audit_log
--    le recopie. Lu par la page « Journal d'audit » : « X (par l'Admin Y) ».
--    Les lignes existantes restent à NULL (rien n'est réécrit).
--
-- 2. Entrées et sorties des modes (« Voir comme », « Agir comme », date
--    simulée) : une ligne d'audit_log écrite par l'appli, action 'ENTREE'
--    ou 'SORTIE', table_cible 'mode_voir_comme' | 'mode_agir_comme' |
--    'date_simulee', ligne_id = compte vu (NULL pour la date), auteur =
--    l'Admin réel. La contrainte audit_log_action_valide (0013) accepte ces
--    deux actions en plus de INSERT / UPDATE / DELETE.
--
-- 3. Date simulée (mode test seulement) : fn_aujourdhui(fuseau) rend la
--    date du réglage de transaction kairos.date_simulee (AAAA-MM-JJ) quand
--    il est posé et valide, sinon « aujourd'hui » au fuseau donné. L'appli
--    ne pose ce réglage QUE si KAIROS_MODE_TEST=true et pour la session de
--    l'Admin qui l'a choisi (SET LOCAL : annulé au COMMIT). fn_dailylog_garde
--    (0014) l'utilise à la place de now() : jour futur et fenêtre de 14 jours
--    suivent la date simulée. Les horodatages (created_at, updated_at,
--    audit_log) restent réels : now() n'est pas touché.
--
-- Rejouable : ADD COLUMN IF NOT EXISTS, DROP … IF EXISTS / ADD, CREATE OR
-- REPLACE, CREATE INDEX IF NOT EXISTS. Mêmes définitions dans schema.sql.

SELECT set_config('lock_timeout', '15s', true);

-- 1. Admin réel ---------------------------------------------------------
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS admin_reel_id BIGINT REFERENCES utilisateur(id);
COMMENT ON COLUMN audit_log.admin_reel_id IS
  'Admin réel quand il agit comme un autre compte (0018, mode test) ; NULL sinon.';
CREATE INDEX IF NOT EXISTS idx_audit_admin_reel ON audit_log (admin_reel_id) WHERE admin_reel_id IS NOT NULL;

-- Id de l'Admin réel (SET LOCAL app.admin_reel_id, voir app/db.py), NULL si
-- absent / vide / invalide — même forme que fn_app_user_id (0013).
CREATE OR REPLACE FUNCTION fn_app_admin_reel_id()
RETURNS BIGINT AS $$
  SELECT CASE WHEN s ~ '^[0-9]{1,18}$' THEN s::BIGINT END
  FROM (SELECT current_setting('app.admin_reel_id', true) AS s) x
$$ LANGUAGE sql STABLE;

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

-- 2. Entrées / sorties des modes ----------------------------------------
ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_action_valide;
ALTER TABLE audit_log ADD CONSTRAINT audit_log_action_valide
  CHECK (action IN ('INSERT', 'UPDATE', 'DELETE', 'ENTREE', 'SORTIE'));

-- 3. Date simulée -------------------------------------------------------
-- Réglage kairos.date_simulee de la transaction, NULL s'il est absent,
-- vide ou invalide (jamais d'erreur : une valeur forgée est ignorée).
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

-- « Aujourd'hui » au fuseau donné (Tunis par défaut), ou la date simulée.
CREATE OR REPLACE FUNCTION fn_aujourdhui(p_fuseau TEXT DEFAULT 'Africa/Tunis')
RETURNS DATE AS $$
  SELECT COALESCE(fn_date_simulee(), (now() AT TIME ZONE COALESCE(p_fuseau, 'Africa/Tunis'))::DATE)
$$ LANGUAGE sql STABLE;

-- fn_dailylog_garde (0014) : seul changement, v_aujourdhui vient de
-- fn_aujourdhui (date simulée comprise) au lieu de now().
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
  -- Date simulée (0018, mode test) ou aujourd'hui au fuseau du titulaire.
  v_aujourdhui := fn_aujourdhui(v_fuseau);

  IF TG_OP <> 'DELETE' THEN
    IF v_date < DATE '2000-01-01' OR v_date > v_aujourdhui THEN
      RAISE EXCEPTION 'Daily log : date % hors limites (aujourd''hui : % pour l''utilisateur %).',
        v_date, v_aujourdhui, v_proprio
        USING ERRCODE = 'check_violation', CONSTRAINT = 'dailylog_date_plausible';
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

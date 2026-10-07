-- 0014 — Daily log v9 (lot 10, maquette validée par Fadhel le 2026-10-06) :
-- saisie −/+ par 30 min, 10 h au plus par jour, jours « absent » exclusifs
-- des heures, objectif de journée personnel (repère 4-10 h), verrou
-- optimiste (version), fuseau horaire par personne, fenêtre de saisie
-- libre de 14 jours (au-delà : chef / co-chef du projet de la ligne, ou
-- Admin).
--
-- Choix de schéma (spécification d'intégration + audit données) :
-- - dailylog_entree.heures reste NUMERIC(4,2) et reste la seule vérité :
--   les vues v_*_heures*, les heures chef/intervenant, les profils,
--   l'export Excel et la reprise Chronos la lisent telle quelle. L'API
--   parle en minutes entières ; le repository convertit (minutes / 60,
--   exact pour un multiple de 30). Pas de colonne `minutes` synchronisée
--   (proposition de l'audit données) : un second écrivain à tenir cohérent
--   pour aucun lecteur.
-- - Les données existantes ne sont JAMAIS réécrites ni revérifiées (v2 au
--   quart d'heure, Chronos à 2,67 h, journées > 10 h). Les nouvelles
--   règles sont des triggers qui ne jouent que sur une valeur qui CHANGE :
--   un CHECK, même NOT VALID, revérifierait la ligne à chaque UPDATE (le
--   piège de la 0012). Les vrais CHECK ne portent que sur les nouvelles
--   colonnes (fuseau, objectif, version).
-- - Garde-fous en base (l'appli donne le message clair avant) : pas de
--   30 min, 10 h par jour (contrainte différée au COMMIT), absence
--   exclusive, jamais un jour futur AU FUSEAU DU TITULAIRE, jamais pour un
--   compte RH ou Client, fenêtre de 14 jours selon l'acteur
--   (app.current_user_id).
--
-- Reprise de l'historique Chronos : scripts/migrate_from_chronos.py écrit,
-- juste après BEGIN, SET LOCAL kairos.reprise_historique = 'on'; — les
-- triggers ci-dessous la laissent alors passer telle quelle.
--
-- Rejouable : IF NOT EXISTS, CREATE OR REPLACE, DROP TRIGGER IF EXISTS.

-- Ne jamais rester bloqué au démarrage du conteneur derrière une session
-- qui tient un verrou (psql ouvert, sauvegarde) : échec net au bout de 15 s.
SELECT set_config('lock_timeout', '15s', true);

-- ---------------------------------------------------------------------
-- 1. Fuseau de la personne : « aujourd'hui » est calculé par le serveur à
--    l'heure de son bureau (Tunis UTC+1, Guyane UTC−3, sans heure d'été
--    ni d'un côté ni de l'autre). Modifiable par l'Admin et le RH (fiche).
-- ---------------------------------------------------------------------
ALTER TABLE utilisateur ADD COLUMN IF NOT EXISTS fuseau VARCHAR(40) NOT NULL DEFAULT 'Africa/Tunis';
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'utilisateur_fuseau_valide') THEN
    ALTER TABLE utilisateur ADD CONSTRAINT utilisateur_fuseau_valide
      CHECK (fuseau IN ('Africa/Tunis', 'America/Cayenne'));
  END IF;
END $$;
COMMENT ON COLUMN utilisateur.fuseau IS
  'Fuseau du bureau (0014) : « aujourd''hui » du Daily log, fenêtre de 14 jours, rappel.';

-- ---------------------------------------------------------------------
-- 2. Objectif de journée (repère « Journée » de la maquette) : réglage PAR
--    PERSONNE, pas par jour (pas de « fuite » d'un jour à l'autre). 4 h à
--    10 h par 30 min ; pas de ligne = 8 h. Non audité : simple préférence
--    d'affichage, sans effet sur les heures.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dailylog_preference (
  utilisateur_id    BIGINT PRIMARY KEY REFERENCES utilisateur(id),
  objectif_minutes  SMALLINT NOT NULL DEFAULT 480,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT dailylog_preference_objectif_valide
    CHECK (objectif_minutes BETWEEN 240 AND 600 AND objectif_minutes % 30 = 0)
);

-- ---------------------------------------------------------------------
-- 3. dailylog_jour devient l'« état du jour » : une ligne dès qu'un jour
--    est enregistré (heures OU absence), avec un numéro de version pour le
--    verrou optimiste (deux onglets, autosave et clic, correction par le
--    chef). Lignes existantes : version 1 ; pas de ligne : version 0.
--    duree_heures (durée v2, réglée jour par jour) n'est plus écrite.
-- ---------------------------------------------------------------------
ALTER TABLE dailylog_jour ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE dailylog_jour ALTER COLUMN duree_heures DROP NOT NULL;
ALTER TABLE dailylog_jour ALTER COLUMN duree_heures DROP DEFAULT;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'dailylog_jour_version_valide') THEN
    ALTER TABLE dailylog_jour ADD CONSTRAINT dailylog_jour_version_valide CHECK (version >= 0);
  END IF;
END $$;
COMMENT ON COLUMN dailylog_jour.duree_heures IS
  'Daily log v2 (0008) : durée réglée pour ce jour. Plus écrite depuis la v9 (0014) — historique seulement.';
COMMENT ON COLUMN dailylog_jour.version IS
  'Verrou optimiste (0014) : +1 à chaque enregistrement du jour ; pas de ligne = 0.';

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
  v_aujourdhui := (now() AT TIME ZONE COALESCE(v_fuseau, 'Africa/Tunis'))::DATE;

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

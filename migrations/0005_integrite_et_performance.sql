-- Correctifs de l'audit n°2 (2026-09-27) : intégrité des données,
-- fuseau horaire, index manquants. Idempotente comme les précédentes
-- (`flask migrer` rejoue toutes les migrations sur une base neuve créée
-- depuis schema.sql, voir app/__init__.py).

-- ---------------------------------------------------------------------
-- 1. Rétro-remplissage complet de post.evenement (complète 0004).
-- Aucun chemin de code, passé ou présent, n'a jamais donné un tache_id à
-- un post saisi à la main (create_post n'est jamais appelé avec, et le
-- script de migration Chronos ne le remplit pas) : tout post portant un
-- tache_id est donc soit le post de création, soit le post de clôture de
-- sa tâche. 0004 a déjà marqué les posts de création ; ceux qui restent
-- sans évènement sont les posts de clôture que l'ancienne heuristique ne
-- retrouvait plus (tâche modifiée après sa clôture, ex. "Vérifié").
-- ---------------------------------------------------------------------
UPDATE post p
SET evenement = 'creation_tache'
FROM tache t
WHERE p.tache_id = t.id
  AND p.created_at = t.created_at
  AND p.evenement IS NULL;

UPDATE post
SET evenement = 'cloture_tache'
WHERE tache_id IS NOT NULL
  AND evenement IS NULL;

-- ---------------------------------------------------------------------
-- 2. Heures DailyLog : ni NaN, ni plus de 24 h sur une ligne.
-- NUMERIC accepte 'NaN', et CHECK (heures > 0) le laisse passer (NaN est
-- considéré plus grand que tout nombre) : une seule ligne NaN rendait le
-- total d'heures du projet égal à NaN dans v_projet_heures. Les lignes
-- NaN existantes sont inexploitables et supprimées ; la borne des 24 h
-- est posée en NOT VALID pour ne pas bloquer la migration si une valeur
-- aberrante ancienne existe (elle reste visible, mais plus aucune
-- nouvelle ne peut être écrite).
-- ---------------------------------------------------------------------
DELETE FROM dailylog_entree WHERE heures = 'NaN';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'dailylog_entree_heures_valides'
  ) THEN
    ALTER TABLE dailylog_entree
      ADD CONSTRAINT dailylog_entree_heures_valides
      CHECK (heures <> 'NaN' AND heures <= 24) NOT VALID;
  END IF;
END $$;

-- ---------------------------------------------------------------------
-- 3. Règle "un RH n'est ni chef, ni co-chef, ni intervenant" aussi lors
-- d'un CHANGEMENT de rôle. Les triggers existants (schema.sql) ne
-- vérifient que l'ajout d'une personne à un projet/une tâche : passer au
-- rôle RH quelqu'un qui est déjà chef ou intervenant contournait la
-- règle.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_check_passage_role_rh()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.role = 'rh' AND OLD.role IS DISTINCT FROM 'rh' AND (
       EXISTS (SELECT 1 FROM projet WHERE chef_projet_id = NEW.id)
    OR EXISTS (SELECT 1 FROM projet_co_chef WHERE utilisateur_id = NEW.id)
    OR EXISTS (SELECT 1 FROM projet_intervenant WHERE utilisateur_id = NEW.id)
    OR EXISTS (SELECT 1 FROM tache_intervenant WHERE utilisateur_id = NEW.id)
  ) THEN
    RAISE EXCEPTION 'Un utilisateur avec le rôle RH ne peut pas être chef de projet, co-chef ou intervenant (utilisateur id=%) : retirez-le d''abord de ses projets et tâches.', NEW.id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_check_passage_role_rh ON utilisateur;
CREATE TRIGGER trg_check_passage_role_rh
  BEFORE UPDATE OF role ON utilisateur
  FOR EACH ROW EXECUTE FUNCTION fn_check_passage_role_rh();

-- ---------------------------------------------------------------------
-- 4. Index manquants (mesurés sur ~200 000 posts / notifications) :
-- fil d'accueil trié par date (72 ms -> 24 ms) et liste des
-- notifications d'un utilisateur (11 ms -> 0,1 ms).
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_post_created_at ON post(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notification_user_date ON notification(utilisateur_id, created_at DESC);

-- ---------------------------------------------------------------------
-- 5. Fuseau horaire de la base. TZ/PGTZ dans docker-compose.yml ne
-- s'appliquent qu'à la CRÉATION du volume (initdb) : une base créée avant
-- reste en UTC, et CURRENT_DATE / created_at::date y donnaient la date
-- de la veille entre minuit et 1 h (heure de Tunis). Réglage au niveau
-- de la base, pris en compte par toute nouvelle connexion.
-- ---------------------------------------------------------------------
DO $$
BEGIN
  EXECUTE format('ALTER DATABASE %I SET timezone = %L', current_database(), 'Africa/Tunis');
END $$;

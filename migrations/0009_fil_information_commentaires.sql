-- Fil d'activité, retours Fadhel du 2026-09-28/29 (voir
-- claude/kairos-ecarts-2026-09-29.md dans le projet) :
--
-- 1. Posts "Information" publiables (N5) : projet optionnel ; sans projet,
--    le post est destiné à une ou plusieurs équipes (post_equipe). Le type
--    'information' existait déjà (désactivé, "étape 2").
-- 2. Posts automatiques (P1) : création de projet, changement d'état d'une
--    tâche ou d'un projet, modification du titre d'une tâche — nouvelles
--    valeurs de post.evenement.
-- 3. Commentaires : @tag de plusieurs personnes directement dans le texte
--    (post_commentaire_mention) et modification par l'auteur
--    (post_commentaire.modifie_le, affiché "modifié").
--
-- Rejouable : IF NOT EXISTS / DROP IF EXISTS partout, triggers créés
-- seulement s'ils manquent.

-- 1. Information
UPDATE post_type SET actif = true WHERE code = 'information';

CREATE TABLE IF NOT EXISTS post_equipe (
  id          BIGSERIAL PRIMARY KEY,
  post_id     BIGINT NOT NULL REFERENCES post(id) ON DELETE CASCADE,
  equipe_code VARCHAR(20) NOT NULL REFERENCES equipe(code),
  CONSTRAINT post_equipe_unique UNIQUE (post_id, equipe_code)
);
CREATE INDEX IF NOT EXISTS idx_post_equipe_equipe ON post_equipe(equipe_code);

-- 2. Posts automatiques
ALTER TABLE post DROP CONSTRAINT IF EXISTS post_evenement_check;
ALTER TABLE post ADD CONSTRAINT post_evenement_check
  CHECK (evenement IS NULL OR evenement IN (
    'creation_tache', 'cloture_tache', 'repost',
    'creation_projet', 'etat_tache', 'etat_projet', 'titre_tache'));

-- 3. Commentaires
ALTER TABLE post_commentaire ADD COLUMN IF NOT EXISTS modifie_le TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS post_commentaire_mention (
  id             BIGSERIAL PRIMARY KEY,
  commentaire_id BIGINT NOT NULL REFERENCES post_commentaire(id) ON DELETE CASCADE,
  utilisateur_id BIGINT NOT NULL REFERENCES utilisateur(id),
  CONSTRAINT post_commentaire_mention_unique UNIQUE (commentaire_id, utilisateur_id)
);
CREATE INDEX IF NOT EXISTS idx_post_commentaire_mention_utilisateur ON post_commentaire_mention(utilisateur_id);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_audit_post_equipe') THEN
    CREATE TRIGGER trg_audit_post_equipe
      AFTER INSERT OR UPDATE OR DELETE ON post_equipe
      FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_audit_post_commentaire_mention') THEN
    CREATE TRIGGER trg_audit_post_commentaire_mention
      AFTER INSERT OR UPDATE OR DELETE ON post_commentaire_mention
      FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
  END IF;
END $$;

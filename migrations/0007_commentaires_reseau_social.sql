-- Lot 5 (retour Fadhel, 2026-09-28) : "refonte du fil de commentaires
-- façon réseau social (réponse en ligne, tag, glisser-déposer, aperçu
-- image, 'reposter')" — voir les commentaires détaillés dans schema.sql,
-- juste au-dessus des tables/colonnes concernées.

-- 1. Réponse en ligne : un commentaire peut répondre à un autre.
ALTER TABLE post_commentaire
  ADD COLUMN IF NOT EXISTS parent_commentaire_id BIGINT REFERENCES post_commentaire(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_post_commentaire_parent ON post_commentaire(parent_commentaire_id);

-- 2. Pièces jointes de commentaire (glisser-déposer + aperçu image).
CREATE TABLE IF NOT EXISTS post_commentaire_piece_jointe (
  id             BIGSERIAL PRIMARY KEY,
  commentaire_id BIGINT NOT NULL REFERENCES post_commentaire(id) ON DELETE CASCADE,
  nom_fichier    VARCHAR(255) NOT NULL,
  chemin         TEXT NOT NULL,
  uploaded_by    BIGINT REFERENCES utilisateur(id),
  uploaded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_post_commentaire_pj_commentaire ON post_commentaire_piece_jointe(commentaire_id);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_audit_post_commentaire_piece_jointe'
  ) THEN
    CREATE TRIGGER trg_audit_post_commentaire_piece_jointe
      AFTER INSERT OR UPDATE OR DELETE ON post_commentaire_piece_jointe
      FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
  END IF;
END $$;

-- 3. "Reposter" : nouvelle valeur possible pour post.evenement (toujours
-- avec parent_post_id renseigné, comme un rebond — voir posts.repost()).
ALTER TABLE post DROP CONSTRAINT IF EXISTS post_evenement_check;
ALTER TABLE post ADD CONSTRAINT post_evenement_check
  CHECK (evenement IS NULL OR evenement IN ('creation_tache', 'cloture_tache', 'repost'));

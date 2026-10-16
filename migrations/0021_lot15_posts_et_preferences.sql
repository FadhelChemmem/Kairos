-- 0021 — Lot 15 (validé par le gérant le 16/10/2026).
--
-- 1. Posts et commentaires modifiables et supprimables : l'auteur modifie
--    ou supprime son post ; le chef, un co-chef du projet ou l'Admin
--    suppriment celui d'un autre. Suppression LOGIQUE (supprime_le,
--    supprime_par) : « Annuler » la rétablit ; un post supprimé disparaît
--    du fil, de ses compteurs et de ses actions. Même chose pour un
--    commentaire.
-- 2. Pièces jointes retirées d'un post ou d'un commentaire : retrait
--    logique (retire_le, retire_par), fichier effacé du disque 30 jours
--    après (purge automatique, app/storage.py).
-- 3. Préférences du compte (et non plus du navigateur) : Deadlines dépliées
--    sur l'accueil, tâches en cours proposées dans le Daily log.
--
-- Rejouable : ADD COLUMN IF NOT EXISTS, CREATE … IF NOT EXISTS. Mêmes
-- définitions dans schema.sql.

SELECT set_config('lock_timeout', '15s', true);

-- 1. Suppression logique et modification ---------------------------------
ALTER TABLE post ADD COLUMN IF NOT EXISTS modifie_le TIMESTAMPTZ;
ALTER TABLE post ADD COLUMN IF NOT EXISTS supprime_le TIMESTAMPTZ;
ALTER TABLE post ADD COLUMN IF NOT EXISTS supprime_par BIGINT REFERENCES utilisateur(id);
COMMENT ON COLUMN post.modifie_le IS 'Dernière modification du texte par son auteur (0021).';
COMMENT ON COLUMN post.supprime_le IS 'Suppression logique (0021) : le post n''apparaît plus nulle part ; « Annuler » la lève.';
COMMENT ON COLUMN post.supprime_par IS 'Personne qui a supprimé le post (auteur, chef, co-chef ou Admin, 0021).';

ALTER TABLE post_commentaire ADD COLUMN IF NOT EXISTS supprime_le TIMESTAMPTZ;
ALTER TABLE post_commentaire ADD COLUMN IF NOT EXISTS supprime_par BIGINT REFERENCES utilisateur(id);
COMMENT ON COLUMN post_commentaire.supprime_le IS 'Suppression logique (0021), réponses comprises.';

-- 2. Pièces jointes retirées ----------------------------------------------
ALTER TABLE post_piece_jointe ADD COLUMN IF NOT EXISTS retire_le TIMESTAMPTZ;
ALTER TABLE post_piece_jointe ADD COLUMN IF NOT EXISTS retire_par BIGINT REFERENCES utilisateur(id);
ALTER TABLE post_commentaire_piece_jointe ADD COLUMN IF NOT EXISTS retire_le TIMESTAMPTZ;
ALTER TABLE post_commentaire_piece_jointe ADD COLUMN IF NOT EXISTS retire_par BIGINT REFERENCES utilisateur(id);
COMMENT ON COLUMN post_piece_jointe.retire_le IS 'Retrait (0021) : plus téléchargeable ; fichier effacé 30 jours après.';
COMMENT ON COLUMN post_commentaire_piece_jointe.retire_le IS 'Retrait (0021) : plus téléchargeable ; fichier effacé 30 jours après.';
CREATE INDEX IF NOT EXISTS idx_post_pj_retiree ON post_piece_jointe (retire_le) WHERE retire_le IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_commentaire_pj_retiree ON post_commentaire_piece_jointe (retire_le)
  WHERE retire_le IS NOT NULL;

-- 3. Préférences du compte -------------------------------------------------
CREATE TABLE IF NOT EXISTS utilisateur_preference (
  utilisateur_id        BIGINT PRIMARY KEY REFERENCES utilisateur(id),
  accueil_deadlines     BOOLEAN NOT NULL DEFAULT false,
  dailylog_proposer     BOOLEAN NOT NULL DEFAULT true,
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE utilisateur_preference IS
  'Réglages d''affichage du compte (0021) : Deadlines dépliées sur l''accueil, tâches proposées dans le Daily log.';

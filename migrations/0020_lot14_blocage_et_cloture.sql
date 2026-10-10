-- 0020 — Lot 14 (revue produit P0-1 et P0-2, validées par le gérant le 10/10/2026).
--
-- 1. Tâche bloquée avec raison : passer une tâche en « Bloquée » demande
--    « Qu'est-ce qui bloque ? ». Le motif du DERNIER blocage est gardé sur
--    la tâche (tache.bloque_motif, bloque_le, bloque_par) ; il n'est
--    affiché que tant que la tâche est bloquée. L'historique complet est
--    dans le fil (posts automatiques ci-dessous) et le journal d'audit
--    (trg_audit_tache). Tâches déjà bloquées : date du blocage reprise du
--    dernier post « … → Bloqué » de la tâche, à défaut de sa dernière
--    modification ; motif inconnu (NULL : « motif non renseigné »).
--
-- 2. Posts automatiques : 'blocage_tache' (« a signalé un blocage », le
--    motif en contenu) et 'deblocage_tache' (« a levé le blocage »).
--
-- Rejouable : ADD COLUMN IF NOT EXISTS, DROP … IF EXISTS / ADD, UPDATE
-- idempotent. Mêmes définitions dans schema.sql.

SELECT set_config('lock_timeout', '15s', true);

-- 1. Motif du blocage ----------------------------------------------------
ALTER TABLE tache ADD COLUMN IF NOT EXISTS bloque_motif TEXT;
ALTER TABLE tache ADD COLUMN IF NOT EXISTS bloque_le TIMESTAMPTZ;
ALTER TABLE tache ADD COLUMN IF NOT EXISTS bloque_par BIGINT REFERENCES utilisateur(id);
ALTER TABLE tache DROP CONSTRAINT IF EXISTS tache_bloque_motif_longueur;
ALTER TABLE tache ADD CONSTRAINT tache_bloque_motif_longueur
  CHECK (bloque_motif IS NULL OR char_length(bloque_motif) BETWEEN 1 AND 500);
COMMENT ON COLUMN tache.bloque_motif IS
  'Motif du dernier blocage (« Qu''est-ce qui bloque ? », 0020) ; affiché tant que la tâche est bloquée.';
COMMENT ON COLUMN tache.bloque_le IS 'Début du dernier blocage (0020) : nombre de jours de blocage.';
COMMENT ON COLUMN tache.bloque_par IS 'Personne qui a signalé le dernier blocage (0020).';

UPDATE tache t
SET bloque_le = COALESCE(
      (SELECT max(po.created_at) FROM post po
       WHERE po.tache_id = t.id AND po.evenement = 'etat_tache' AND po.contenu LIKE '%→ Bloqué'),
      t.updated_at)
WHERE t.etat = 'bloque' AND t.bloque_le IS NULL;

CREATE INDEX IF NOT EXISTS idx_tache_bloquee ON tache (projet_id) WHERE etat = 'bloque';

-- 2. Posts automatiques --------------------------------------------------
ALTER TABLE post DROP CONSTRAINT IF EXISTS post_evenement_check;
ALTER TABLE post ADD CONSTRAINT post_evenement_check
  CHECK (evenement IS NULL OR evenement IN (
    'creation_tache', 'cloture_tache', 'repost',
    'creation_projet', 'etat_tache', 'etat_projet', 'titre_tache', 'chef_projet',
    'intervenant_tache', 'echeance_tache', 'intervenant_projet',
    'blocage_tache', 'deblocage_tache'));

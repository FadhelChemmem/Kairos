-- Marqueur explicite d'évènement de tâche sur les posts système (création
-- / clôture), pour remplacer l'heuristique fragile
-- post.created_at == tache.created_at / tache.updated_at (voir
-- repositories/taches.py, note en tête de fichier, et
-- PROMPT_CORRECTIONS.md P1 #9).
--
-- Le bug : trg_tache_updated_at (schema.sql) réécrit tache.updated_at à
-- CHAQUE mise à jour de la tâche, pas seulement à sa clôture. Un post de
-- clôture (post.created_at == tache.updated_at AU MOMENT DE LA CLÔTURE)
-- perdait donc son statut de "post de clôture" dès que la tâche était
-- ensuite modifiée une seule fois (ex. passage à "Vérifié" après
-- clôture) : le marqueur visuel "tâche terminée" disparaissait alors du
-- fil, silencieusement, sans que rien n'ait été supprimé.

ALTER TABLE post ADD COLUMN IF NOT EXISTS evenement VARCHAR(20);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'post_evenement_check'
  ) THEN
    ALTER TABLE post
      ADD CONSTRAINT post_evenement_check
      CHECK (evenement IS NULL OR evenement IN ('creation_tache', 'cloture_tache'));
  END IF;
END $$;

-- Rétro-remplissage (2026-09-27) : recalcule `evenement` pour les posts
-- système déjà en base à partir de l'ancienne heuristique. Limite connue,
-- inévitable : pour une tâche déjà touchée par le bug ci-dessus (post de
-- clôture dont created_at ne correspond plus à l'updated_at ACTUEL de la
-- tâche, parce que celle-ci a été modifiée depuis), cette requête ne peut
-- plus retrouver quel post était le post de clôture — cette donnée
-- historique reste perdue. Le code applicatif écrit désormais `evenement`
-- directement à la création/clôture (voir repositories/taches.py), donc
-- le bug ne se reproduit plus pour les nouvelles tâches.
UPDATE post p
SET evenement = 'creation_tache'
FROM tache t
WHERE p.tache_id = t.id
  AND p.created_at = t.created_at
  AND p.evenement IS NULL;

UPDATE post p
SET evenement = 'cloture_tache'
FROM tache t
WHERE p.tache_id = t.id
  AND t.date_fin IS NOT NULL
  AND p.created_at = t.updated_at
  AND p.created_at <> t.created_at
  AND p.evenement IS NULL;

-- 0026 — Lot 23 (décision du gérant du 20/10) : filtres mémorisés par
-- personne (« Tous les projets », « Équipe », « Journal d'audit ») au lieu
-- d'un cookie du navigateur (lot 22) : retrouvés sur tout PC, propres à
-- chaque compte, et un ancien onglet rechargé ne les écrase plus.
-- Une chaîne de requête par page (app/filtres_memoire.py).
--
-- Rejouable : ADD COLUMN IF NOT EXISTS.

SELECT set_config('lock_timeout', '15s', true);

ALTER TABLE utilisateur_preference ADD COLUMN IF NOT EXISTS filtres JSONB NOT NULL DEFAULT '{}'::jsonb;
COMMENT ON COLUMN utilisateur_preference.filtres IS
  'Filtres mémorisés par page (0026) : {"projets": "etat=…&chef_id=…", "equipe": …, "journal": …}.';

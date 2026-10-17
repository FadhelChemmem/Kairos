-- 0022 — Lot 17 (demande du gérant, 17/10/2026) : posts pas encore vus
-- dans le fil de l'accueil. Pour chaque personne et chaque catégorie du fil
-- (Échanges, Activité), l'instant où elle l'a regardée pour la dernière
-- fois : les posts publiés après (sauf les siens) sont « nouveaux »
-- (pastille sur l'onglet, repère sur le post). Pas d'audit : simple
-- marque-page, réécrit à chaque visite.
--
-- Rejouable : CREATE … IF NOT EXISTS. Même définition dans schema.sql.

SELECT set_config('lock_timeout', '15s', true);

CREATE TABLE IF NOT EXISTS utilisateur_fil_vu (
  utilisateur_id  BIGINT NOT NULL REFERENCES utilisateur(id),
  categorie       TEXT NOT NULL CHECK (categorie IN ('echanges', 'activite')),
  vu_le           TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (utilisateur_id, categorie)
);
COMMENT ON TABLE utilisateur_fil_vu IS
  'Dernière consultation du fil de l''accueil par catégorie (0022) : les posts plus récents sont « nouveaux ».';

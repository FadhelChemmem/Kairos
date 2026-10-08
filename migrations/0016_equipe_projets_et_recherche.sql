-- 0016 — Lot 11 (décisions du gérant après la mise en service).
--
-- 1. Équipe des projets. Les projets repris de Chronos n'ont pas d'équipe
--    (Chronos n'en a pas) : avec v_projet_visibilite, un chef de projet ou
--    un intervenant de l'équipe Midgard ne voyait que les projets où il est
--    rattaché (2 sur 653 pour un chef en production). Chaque projet sans
--    équipe reçoit celle de son chef de projet titulaire, à défaut
--    l'équipe MIDGARD. Un projet qui a déjà une équipe n'est pas touché ;
--    la création d'un projet garde sa règle (équipe du chef, modifiable).
--    updated_at n'est pas réécrit (trg_projet_updated_at coupé le temps de
--    la mise à jour) : le tri « récemment modifiés » reste celui d'avant.
--    Chaque ligne modifiée est tracée dans audit_log (trigger d'audit).
--
-- 2. Recherche insensible aux accents et à la casse (« residence » trouve
--    « Résidence », « oeuvre » trouve « Œuvre ») : extension unaccent
--    (contrib, présente dans l'image postgres:16 ; « trusted » depuis
--    PostgreSQL 13 : le propriétaire de la base peut la créer) et
--    fn_recherche(), IMMUTABLE (dictionnaire nommé explicitement), utilisée
--    des deux côtés du LIKE : projets (code, nom), personnes (prénom, nom,
--    « prénom nom »), tâches (titre), catalogue du Daily log.
--
-- Rejouable : la mise à jour ne vise que les projets sans équipe ;
-- IF NOT EXISTS, CREATE OR REPLACE.

SELECT set_config('lock_timeout', '15s', true);

INSERT INTO equipe (code, libelle) VALUES ('MIDGARD', 'Midgard') ON CONFLICT (code) DO NOTHING;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM projet WHERE equipe_code IS NULL) THEN
    ALTER TABLE projet DISABLE TRIGGER trg_projet_updated_at;
    UPDATE projet p
       SET equipe_code = COALESCE((SELECT u.equipe_code FROM utilisateur u WHERE u.id = p.chef_projet_id), 'MIDGARD')
     WHERE p.equipe_code IS NULL;
    ALTER TABLE projet ENABLE TRIGGER trg_projet_updated_at;
  END IF;
END $$;

CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;

CREATE OR REPLACE FUNCTION fn_recherche(t TEXT)
RETURNS TEXT AS $$
  SELECT lower(public.unaccent('public.unaccent'::regdictionary, t));
$$ LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT;

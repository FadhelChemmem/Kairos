-- Lot 11 (migration 0016) sur un vrai PostgreSQL : recherche sans accents
-- ni casse (fn_recherche, extension unaccent) et équipe des projets. Tout
-- est annulé (ROLLBACK). Lancé par la CI avec psql -v ON_ERROR_STOP=1 sur
-- la base neuve, la base montée de version et la base « comme en
-- production ».
BEGIN;

DO $$
BEGIN
  IF fn_recherche('Résidence ÉTÉ') <> 'residence ete' THEN
    RAISE EXCEPTION 'fn_recherche : %', fn_recherche('Résidence ÉTÉ');
  END IF;
  IF fn_recherche('Œuvre Ça Ñandú') <> 'oeuvre ca nandu' THEN
    RAISE EXCEPTION 'fn_recherche (ligatures) : %', fn_recherche('Œuvre Ça Ñandú');
  END IF;
  IF fn_recherche(NULL) IS NOT NULL THEN
    RAISE EXCEPTION 'fn_recherche(NULL) doit rester NULL';
  END IF;
  -- Jokers LIKE échappés par l'appli (_like.motif_recherche) : intacts.
  IF fn_recherche('%50\%\_é%') <> '%50\%\_e%' THEN
    RAISE EXCEPTION 'fn_recherche touche aux jokers : %', fn_recherche('%50\%\_é%');
  END IF;
  IF NOT ('collège sainte-anne' LIKE '%' AND fn_recherche('Collège Sainte-Anne') LIKE fn_recherche('%COLLEGE%')) THEN
    RAISE EXCEPTION 'LIKE sans accents : échec';
  END IF;
  IF (SELECT provolatile FROM pg_proc WHERE proname = 'fn_recherche') <> 'i' THEN
    RAISE EXCEPTION 'fn_recherche doit être IMMUTABLE (index d''expression possible)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'unaccent') THEN
    RAISE EXCEPTION 'extension unaccent absente';
  END IF;
END $$;

-- Utilisable dans un index d'expression (IMMUTABLE réel, pas seulement déclaré).
CREATE TEMP TABLE t_lot11 (nom TEXT);
INSERT INTO t_lot11 VALUES ('Résidence Les Palmiers'), ('Villa Louison');
CREATE INDEX ON t_lot11 (fn_recherche(nom));
DO $$
BEGIN
  IF (SELECT count(*) FROM t_lot11 WHERE fn_recherche(nom) LIKE fn_recherche('%RESIDENCE%')) <> 1 THEN
    RAISE EXCEPTION 'recherche via index : échec';
  END IF;
END $$;

-- Équipe des projets : la mise à jour de 0016, rejouée sur des projets sans équipe.
INSERT INTO utilisateur (email, mot_de_passe_hash, prenom, nom, role, equipe_code) VALUES
  ('t16-chef-urbs@test.tn', 'x', 'T', 'ChefUrbs', 'chef_de_projet', 'URBS'),
  ('t16-chef-sans@test.tn', 'x', 'T', 'ChefSans', 'chef_de_projet', NULL),
  ('t16-inter@test.tn', 'x', 'T', 'Inter', 'intervenant', 'MIDGARD');
INSERT INTO projet (code, nom, phase, chef_projet_id)
SELECT 'T1601X', 'Urbs', 'EXE', id FROM utilisateur WHERE email = 't16-chef-urbs@test.tn';
INSERT INTO projet (code, nom, phase, chef_projet_id)
SELECT 'T1602X', 'Sans', 'EXE', id FROM utilisateur WHERE email = 't16-chef-sans@test.tn';
UPDATE projet p
   SET equipe_code = COALESCE((SELECT u.equipe_code FROM utilisateur u WHERE u.id = p.chef_projet_id), 'MIDGARD')
 WHERE p.equipe_code IS NULL AND p.code IN ('T1601X', 'T1602X');
DO $$
DECLARE
  it BIGINT := (SELECT id FROM utilisateur WHERE email = 't16-inter@test.tn');
BEGIN
  IF (SELECT string_agg(code || '=' || equipe_code, ',' ORDER BY code) FROM projet WHERE code LIKE 'T16%')
     <> 'T1601X=URBS,T1602X=MIDGARD' THEN
    RAISE EXCEPTION 'équipe des projets : %', (SELECT string_agg(code || '=' || coalesce(equipe_code, '?'), ',') FROM projet WHERE code LIKE 'T16%');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM v_projet_visibilite v JOIN projet p ON p.id = v.projet_id
                 WHERE p.code = 'T1602X' AND v.utilisateur_id = it)
     OR EXISTS (SELECT 1 FROM v_projet_visibilite v JOIN projet p ON p.id = v.projet_id
                WHERE p.code = 'T1601X' AND v.utilisateur_id = it) THEN
    RAISE EXCEPTION 'visibilité par équipe : un intervenant MIDGARD doit voir T1602X et pas T1601X';
  END IF;
END $$;

ROLLBACK;

-- Tests SQL sur un vrai PostgreSQL (lot 7, point K de l'audit) : les tests
-- Python stubent psycopg2 et ne vérifient donc jamais les règles écrites
-- en SQL. Ce script, joué par la CI (.github/workflows/tests.yml, job
-- "schema") sur une base à jour, vérifie la visibilité des projets par
-- rôle (v_projet_visibilite) et les garde-fous RH/Client en base. Tout est
-- annulé à la fin (ROLLBACK) ; une assertion fausse lève une exception et
-- fait échouer le job (psql -v ON_ERROR_STOP=1).
BEGIN;

-- Un seul RH actif autorisé (idx_utilisateur_rh_singleton) : sur une base
-- qui en a déjà un, on le désactive le temps du test.
UPDATE utilisateur SET actif = false WHERE role = 'rh';

INSERT INTO utilisateur (email, mot_de_passe_hash, prenom, nom, role, equipe_code) VALUES
  ('t-admin@test.tn',  'x', 'T', 'Admin',    'admin',          NULL),
  ('t-rh@test.tn',     'x', 'T', 'Rh',       'rh',             'MIDGARD'),
  ('t-client@test.tn', 'x', 'T', 'Client',   'client',         'MIDGARD'),
  ('t-chefm@test.tn',  'x', 'T', 'ChefM',    'chef_de_projet', 'MIDGARD'),
  ('t-chefu@test.tn',  'x', 'T', 'ChefU',    'chef_de_projet', 'URBS'),
  ('t-interu@test.tn', 'x', 'T', 'InterU',   'intervenant',    'URBS');

INSERT INTO projet (code, nom, phase, chef_projet_id, equipe_code)
SELECT 'T0001X', 'Projet Midgard', 'EXE', id, 'MIDGARD' FROM utilisateur WHERE email = 't-chefm@test.tn';
INSERT INTO projet (code, nom, phase, chef_projet_id, equipe_code)
SELECT 'T0002X', 'Projet Urbs', 'EXE', id, 'URBS' FROM utilisateur WHERE email = 't-chefu@test.tn';
-- InterU (URBS) intervient ponctuellement sur le projet Midgard.
INSERT INTO projet_intervenant (projet_id, utilisateur_id)
SELECT p.id, u.id FROM projet p, utilisateur u WHERE p.code = 'T0001X' AND u.email = 't-interu@test.tn';

CREATE TEMP TABLE attendu (email TEXT, codes TEXT);
INSERT INTO attendu VALUES
  ('t-admin@test.tn',  'T0001X,T0002X'),  -- Admin : tout
  ('t-rh@test.tn',     ''),               -- RH : aucun projet
  ('t-client@test.tn', 'T0001X'),         -- Client : son équipe
  ('t-chefm@test.tn',  'T0001X'),
  ('t-chefu@test.tn',  'T0002X'),
  ('t-interu@test.tn', 'T0001X,T0002X');  -- son équipe + projet rejoint

DO $$
DECLARE
  r RECORD;
  vus TEXT;
BEGIN
  FOR r IN SELECT * FROM attendu LOOP
    SELECT COALESCE(string_agg(p.code, ',' ORDER BY p.code), '') INTO vus
    FROM v_projet_visibilite vv
    JOIN projet p ON p.id = vv.projet_id
    JOIN utilisateur u ON u.id = vv.utilisateur_id
    WHERE u.email = r.email AND p.code LIKE 'T000%';
    IF vus <> r.codes THEN
      RAISE EXCEPTION 'Visibilité de % : attendu [%], obtenu [%]', r.email, r.codes, vus;
    END IF;
  END LOOP;
END $$;

-- Un Client ne peut être ni intervenant (projet, tâche), ni co-chef, ni chef.
DO $$
DECLARE
  v_client BIGINT := (SELECT id FROM utilisateur WHERE email = 't-client@test.tn');
  v_projet BIGINT := (SELECT id FROM projet WHERE code = 'T0001X');
  v_tache  BIGINT;
  v_refus  INT := 0;
BEGIN
  INSERT INTO tache (projet_id, titre, created_by)
  VALUES (v_projet, 'Tâche test', (SELECT chef_projet_id FROM projet WHERE id = v_projet))
  RETURNING id INTO v_tache;

  BEGIN
    INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (v_projet, v_client);
  EXCEPTION WHEN raise_exception THEN v_refus := v_refus + 1;
  END;
  BEGIN
    INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (v_tache, v_client);
  EXCEPTION WHEN raise_exception THEN v_refus := v_refus + 1;
  END;
  BEGIN
    INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (v_projet, v_client);
  EXCEPTION WHEN raise_exception THEN v_refus := v_refus + 1;
  END;
  BEGIN
    UPDATE projet SET chef_projet_id = v_client WHERE id = v_projet;
  EXCEPTION WHEN raise_exception THEN v_refus := v_refus + 1;
  END;
  IF v_refus <> 4 THEN
    RAISE EXCEPTION 'Client rattaché à un projet/une tâche : % refus sur 4 attendus', v_refus;
  END IF;
END $$;

-- Colonne de date de clôture (migration 0011) présente.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'projet' AND column_name = 'date_cloture') THEN
    RAISE EXCEPTION 'Colonne projet.date_cloture absente';
  END IF;
END $$;

ROLLBACK;

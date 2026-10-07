-- États de tâche réservés (migration 0015) sur un vrai PostgreSQL : seuls
-- le chef titulaire, un co-chef ou un Admin actifs font entrer une tâche
-- en Vérifiée / Arrêtée / Abandonnée ou l'en font sortir ; sans acteur
-- (scripts) ou pendant la reprise Chronos, aucune restriction. Tout est
-- annulé (ROLLBACK). Lancé par la CI avec psql -v ON_ERROR_STOP=1 sur la
-- base neuve, la base montée de version et la base « comme en production ».
BEGIN;

INSERT INTO utilisateur (email, mot_de_passe_hash, prenom, nom, role, equipe_code) VALUES
  ('t15-chef@test.tn', 'x', 'T', 'Chef', 'chef_de_projet', 'MIDGARD'),
  ('t15-cochef@test.tn', 'x', 'T', 'CoChef', 'chef_de_projet', 'MIDGARD'),
  ('t15-autrechef@test.tn', 'x', 'T', 'AutreChef', 'chef_de_projet', 'MIDGARD'),
  ('t15-admin@test.tn', 'x', 'T', 'Admin', 'admin', 'MIDGARD'),
  ('t15-inter@test.tn', 'x', 'T', 'Inter', 'intervenant', 'MIDGARD');
INSERT INTO projet (code, nom, phase, chef_projet_id, equipe_code)
SELECT 'T1501X', 'Projet 15', 'EXE', id, 'MIDGARD' FROM utilisateur WHERE email = 't15-chef@test.tn';
INSERT INTO projet_co_chef (projet_id, utilisateur_id)
SELECT p.id, u.id FROM projet p, utilisateur u WHERE p.code = 'T1501X' AND u.email = 't15-cochef@test.tn';
INSERT INTO tache (projet_id, titre, created_by)
SELECT p.id, 'Tâche 15', p.chef_projet_id FROM projet p WHERE p.code = 'T1501X';

DO $$
DECLARE
  ch  BIGINT := (SELECT id FROM utilisateur WHERE email = 't15-chef@test.tn');
  cc  BIGINT := (SELECT id FROM utilisateur WHERE email = 't15-cochef@test.tn');
  ac  BIGINT := (SELECT id FROM utilisateur WHERE email = 't15-autrechef@test.tn');
  ad  BIGINT := (SELECT id FROM utilisateur WHERE email = 't15-admin@test.tn');
  it  BIGINT := (SELECT id FROM utilisateur WHERE email = 't15-inter@test.tn');
  pid BIGINT := (SELECT id FROM projet WHERE code = 'T1501X');
  t   BIGINT := (SELECT id FROM tache WHERE titre = 'Tâche 15');
  e   TEXT;
  n   INT := 0;
  attendu INT := 0;
BEGIN
  -- 1. Intervenant : états libres oui, états réservés non (dans les deux sens).
  PERFORM set_config('app.current_user_id', it::text, true);
  UPDATE tache SET etat = 'bloque' WHERE id = t;
  UPDATE tache SET etat = 'termine' WHERE id = t;
  UPDATE tache SET etat = 'en_cours' WHERE id = t;
  FOREACH e IN ARRAY ARRAY['verifie', 'arret', 'abandonne'] LOOP
    attendu := attendu + 1;
    BEGIN UPDATE tache SET etat = e::tache_etat_enum WHERE id = t;
    EXCEPTION WHEN insufficient_privilege THEN n := n + 1; END;
  END LOOP;
  -- Création directe dans un état réservé : refusée aussi.
  attendu := attendu + 1;
  BEGIN INSERT INTO tache (projet_id, titre, created_by, etat) VALUES (pid, 'Directe', it, 'verifie');
  EXCEPTION WHEN insufficient_privilege THEN n := n + 1; END;
  -- Un autre chef de projet, ni titulaire ni co-chef : comme un intervenant.
  PERFORM set_config('app.current_user_id', ac::text, true);
  attendu := attendu + 1;
  BEGIN UPDATE tache SET etat = 'verifie' WHERE id = t;
  EXCEPTION WHEN insufficient_privilege THEN n := n + 1; END;

  -- 2. Sortie d'un état réservé par un intervenant : refusée.
  FOREACH e IN ARRAY ARRAY['verifie', 'arret', 'abandonne'] LOOP
    PERFORM set_config('app.current_user_id', ch::text, true);
    UPDATE tache SET etat = e::tache_etat_enum WHERE id = t;
    PERFORM set_config('app.current_user_id', it::text, true);
    attendu := attendu + 1;
    BEGIN UPDATE tache SET etat = 'en_cours' WHERE id = t;
    EXCEPTION WHEN insufficient_privilege THEN n := n + 1; END;
    attendu := attendu + 1;
    BEGIN UPDATE tache SET etat = 'termine' WHERE id = t;
    EXCEPTION WHEN insufficient_privilege THEN n := n + 1; END;
    -- Autre colonne modifiée sans toucher à l'état : libre.
    UPDATE tache SET titre = 'Tâche 15' WHERE id = t;
  END LOOP;

  -- 3. Chef titulaire, co-chef, Admin : tout passe.
  FOREACH e IN ARRAY ARRAY[ch::text, cc::text, ad::text] LOOP
    PERFORM set_config('app.current_user_id', e, true);
    UPDATE tache SET etat = 'verifie' WHERE id = t;
    UPDATE tache SET etat = 'en_cours' WHERE id = t;
    UPDATE tache SET etat = 'arret' WHERE id = t;
    UPDATE tache SET etat = 'termine' WHERE id = t;
  END LOOP;

  -- 4. Chef titulaire désactivé : refusé.
  UPDATE utilisateur SET actif = false WHERE id = ch;
  PERFORM set_config('app.current_user_id', ch::text, true);
  attendu := attendu + 1;
  BEGIN UPDATE tache SET etat = 'verifie' WHERE id = t;
  EXCEPTION WHEN insufficient_privilege THEN n := n + 1; END;

  -- 5. Sans acteur (scripts, psql) et reprise Chronos : libres.
  PERFORM set_config('app.current_user_id', '', true);
  UPDATE tache SET etat = 'abandonne' WHERE id = t;
  PERFORM set_config('app.current_user_id', it::text, true);
  PERFORM set_config('kairos.reprise_historique', 'on', true);
  UPDATE tache SET etat = 'en_cours' WHERE id = t;
  PERFORM set_config('kairos.reprise_historique', 'off', true);

  IF n <> attendu THEN
    RAISE EXCEPTION 'etats_taches_reserves.sql : % refus obtenus, % attendus', n, attendu;
  END IF;
  RAISE NOTICE 'etats_taches_reserves.sql : % refus attendus obtenus', n;
END $$;

ROLLBACK;

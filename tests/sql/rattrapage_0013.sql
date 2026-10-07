-- Migration 0013 : objets de 0011/0012 à leur forme de référence,
-- intégrité, décisions 1 (RH sans prise sur un Admin, dernier Admin) et
-- 3 (chef ajouté comme intervenant d'un projet OU d'une tâche = co-chef).
-- Tout est annulé (ROLLBACK).
BEGIN;
SET CONSTRAINTS ALL IMMEDIATE;

INSERT INTO utilisateur (email, mot_de_passe_hash, prenom, nom, role, equipe_code) VALUES
  ('t13-admin1@test.tn', 'x', 'A', 'Un', 'admin', 'MIDGARD'),
  ('t13-admin2@test.tn', 'x', 'A', 'Deux', 'admin', 'MIDGARD'),
  ('t13-rh@test.tn', 'x', 'R', 'H', 'intervenant', 'MIDGARD'),
  ('t13-chef@test.tn', 'x', 'C', 'Hef', 'chef_de_projet', 'MIDGARD'),
  ('t13-chef2@test.tn', 'x', 'C', 'Hef2', 'chef_de_projet', 'MIDGARD'),
  ('t13-int@test.tn', 'x', 'I', 'Nt', 'intervenant', 'MIDGARD');
-- Le RH de test : on désactive l'éventuel RH existant de la base pour respecter le singleton.
UPDATE utilisateur SET actif = false WHERE role = 'rh' AND email <> 't13-rh@test.tn';
UPDATE utilisateur SET role = 'rh' WHERE email = 't13-rh@test.tn';

INSERT INTO projet (code, nom, phase, chef_projet_id, equipe_code, date_debut)
SELECT 'T1301X', 'Projet 13', 'EXE', id, 'MIDGARD', DATE '2026-03-01' FROM utilisateur WHERE email = 't13-chef@test.tn';
INSERT INTO projet (code, nom, phase, chef_projet_id, equipe_code, date_debut)
SELECT 'T1302X', 'Projet 13 bis', 'EXE', id, 'MIDGARD', DATE '2026-03-01' FROM utilisateur WHERE email = 't13-chef@test.tn';

DO $$
DECLARE
  v_a1 BIGINT := (SELECT id FROM utilisateur WHERE email = 't13-admin1@test.tn');
  v_a2 BIGINT := (SELECT id FROM utilisateur WHERE email = 't13-admin2@test.tn');
  v_rh BIGINT := (SELECT id FROM utilisateur WHERE email = 't13-rh@test.tn');
  v_chef BIGINT := (SELECT id FROM utilisateur WHERE email = 't13-chef@test.tn');
  v_chef2 BIGINT := (SELECT id FROM utilisateur WHERE email = 't13-chef2@test.tn');
  v_int BIGINT := (SELECT id FROM utilisateur WHERE email = 't13-int@test.tn');
  v_p1 BIGINT := (SELECT id FROM projet WHERE code = 'T1301X');
  v_p2 BIGINT := (SELECT id FROM projet WHERE code = 'T1302X');
  v_t2 BIGINT;
  v_refus INT := 0;
  v_n INT;
BEGIN
  -- Formes de référence (rattrapage 0011/0012).
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_check_dates_projet_maj')
     OR NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_check_dates_tache_maj')
     OR position('client' IN (SELECT prosrc FROM pg_proc WHERE proname = 'fn_check_passage_role_rh')) = 0 THEN
    RAISE EXCEPTION 'Rattrapage 0011/0012 incomplet';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE connamespace = 'public'::regnamespace AND NOT convalidated) THEN
    RAISE EXCEPTION 'Contrainte(s) restée(s) NOT VALID sur une base propre';
  END IF;

  -- Décision 1 : le RH n'agit pas sur un Admin.
  PERFORM set_config('app.current_user_id', v_rh::text, true);
  BEGIN UPDATE utilisateur SET telephone = '1' WHERE id = v_a1; EXCEPTION WHEN insufficient_privilege THEN v_refus := v_refus + 1; END;
  BEGIN UPDATE utilisateur SET actif = false WHERE id = v_a1; EXCEPTION WHEN insufficient_privilege THEN v_refus := v_refus + 1; END;
  BEGIN UPDATE utilisateur SET role = 'admin' WHERE id = v_int; EXCEPTION WHEN insufficient_privilege THEN v_refus := v_refus + 1; END;
  BEGIN INSERT INTO utilisateur (email, mot_de_passe_hash, prenom, nom, role) VALUES ('t13-x@test.tn', 'x', 'X', 'X', 'admin');
    EXCEPTION WHEN insufficient_privilege THEN v_refus := v_refus + 1; END;
  IF v_refus <> 4 THEN RAISE EXCEPTION 'RH sur Admin : % refus sur 4', v_refus; END IF;
  UPDATE utilisateur SET telephone = '2' WHERE id = v_int;  -- le RH garde la main sur les autres comptes

  -- Toujours un Admin actif.
  PERFORM set_config('app.current_user_id', v_a1::text, true);
  UPDATE utilisateur SET actif = false WHERE role = 'admin' AND id NOT IN (v_a1, v_a2);
  UPDATE utilisateur SET actif = false WHERE id = v_a2;
  v_refus := 0;
  BEGIN UPDATE utilisateur SET actif = false WHERE id = v_a1; EXCEPTION WHEN check_violation THEN v_refus := 1; END;
  IF v_refus <> 1 THEN RAISE EXCEPTION 'Dernier Admin désactivable'; END IF;

  -- Décision 3 : chef ajouté comme intervenant => co-chef.
  INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (v_p1, v_chef2), (v_p1, v_int);
  SELECT count(*) INTO v_n FROM projet_co_chef WHERE projet_id = v_p1;
  IF v_n <> 1 OR NOT EXISTS (SELECT 1 FROM projet_co_chef WHERE projet_id = v_p1 AND utilisateur_id = v_chef2) THEN
    RAISE EXCEPTION 'Co-chef automatique : % co-chef(s)', v_n;
  END IF;
  -- ... y compris intervenant d'une TÂCHE ; jamais le titulaire lui-même.
  INSERT INTO tache (projet_id, titre, created_by) VALUES (v_p2, 'Tâche co-chef', v_chef) RETURNING id INTO v_t2;
  INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (v_t2, v_chef2), (v_t2, v_chef), (v_t2, v_int);
  IF NOT EXISTS (SELECT 1 FROM projet_co_chef WHERE projet_id = v_p2 AND utilisateur_id = v_chef2) THEN
    RAISE EXCEPTION 'Co-chef automatique (tâche) absent';
  END IF;
  SELECT count(*) INTO v_n FROM projet_co_chef WHERE projet_id = v_p2;
  IF v_n <> 1 THEN RAISE EXCEPTION 'Co-chef automatique (tâche) : % co-chef(s) au lieu de 1', v_n; END IF;

  -- Révocation des sessions : désactiver un compte incrémente sa génération.
  UPDATE utilisateur SET actif = false WHERE id = v_int;
  UPDATE utilisateur SET actif = true WHERE id = v_int;
  UPDATE utilisateur SET telephone = '3' WHERE id = v_int;
  IF (SELECT generation FROM utilisateur_session WHERE utilisateur_id = v_int) IS DISTINCT FROM 1 THEN
    RAISE EXCEPTION 'Génération de session non incrémentée à la désactivation (et seulement elle)';
  END IF;

  -- Une ligne d'heures / un post ne pointe que la tâche de son projet.
  INSERT INTO tache (projet_id, titre, created_by) VALUES (v_p2, 'Tâche du projet 2', v_chef) RETURNING id INTO v_t2;
  v_refus := 0;
  BEGIN INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures) VALUES (v_int, CURRENT_DATE, v_p1, v_t2, 1);
    EXCEPTION WHEN foreign_key_violation THEN v_refus := v_refus + 1; END;
  BEGIN INSERT INTO post (projet_id, tache_id, auteur_id, type_code) VALUES (v_p1, v_t2, v_chef, 'envoi');
    EXCEPTION WHEN foreign_key_violation THEN v_refus := v_refus + 1; END;
  BEGIN UPDATE projet SET phase_liee_id = id WHERE id = v_p1; EXCEPTION WHEN check_violation THEN v_refus := v_refus + 1; END;
  BEGIN INSERT INTO notification (utilisateur_id, categorie, message) VALUES (v_int, 'autre', 'x');
    EXCEPTION WHEN check_violation THEN v_refus := v_refus + 1; END;
  BEGIN INSERT INTO utilisateur (email, mot_de_passe_hash, prenom, nom) VALUES ('t13-y@test.tn ', 'x', 'Y', 'Y');
    EXCEPTION WHEN check_violation THEN v_refus := v_refus + 1; END;
  IF v_refus <> 5 THEN RAISE EXCEPTION 'Intégrité : % refus sur 5', v_refus; END IF;

  -- Projet ancien aux dates incohérentes : les honoraires restent modifiables.
  ALTER TABLE projet DISABLE TRIGGER trg_check_dates_projet_maj;
  UPDATE projet SET date_fin = DATE '2026-01-01' WHERE id = v_p2;
  ALTER TABLE projet ENABLE TRIGGER trg_check_dates_projet_maj;
  UPDATE projet SET honoraires = 1000 WHERE id = v_p2;
  v_refus := 0;
  BEGIN UPDATE projet SET date_fin = DATE '2026-01-02' WHERE id = v_p2; EXCEPTION WHEN raise_exception THEN v_refus := 1; END;
  IF v_refus <> 1 THEN RAISE EXCEPTION 'Dates incohérentes acceptées'; END IF;

  -- updated_by explicite conservé sans variable de session.
  PERFORM set_config('app.current_user_id', '', true);
  UPDATE projet SET nom = 'Renommé', updated_by = v_chef WHERE id = v_p1;
  IF (SELECT updated_by FROM projet WHERE id = v_p1) IS DISTINCT FROM v_chef THEN
    RAISE EXCEPTION 'updated_by explicite écrasé';
  END IF;
END $$;

ROLLBACK;

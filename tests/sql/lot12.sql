-- Lot 12 (migration 0018) sur un vrai PostgreSQL : date simulée
-- (fn_date_simulee, fn_aujourdhui, fn_dailylog_garde : jour futur et
-- fenêtre de 14 jours décalés, valeur forgée ignorée), Admin réel dans le
-- journal d'audit (audit_log.admin_reel_id via app.admin_reel_id), actions
-- ENTREE / SORTIE des modes. Tout est annulé (ROLLBACK). Lancé par la CI
-- avec psql -v ON_ERROR_STOP=1 sur la base neuve, la base montée de version
-- et la base « comme en production ».
BEGIN;
SET CONSTRAINTS ALL IMMEDIATE;

INSERT INTO utilisateur (email, mot_de_passe_hash, prenom, nom, role, equipe_code, fuseau) VALUES
  ('t12-i@test.tn', 'x', 'T', 'Inter', 'intervenant', 'MIDGARD', 'Africa/Tunis'),
  ('t12-g@test.tn', 'x', 'T', 'Guyane', 'intervenant', 'MIDGARD', 'America/Cayenne'),
  ('t12-c@test.tn', 'x', 'T', 'Chef', 'chef_de_projet', 'MIDGARD', 'Africa/Tunis'),
  ('t12-a@test.tn', 'x', 'T', 'Admin', 'admin', 'MIDGARD', 'Africa/Tunis');
INSERT INTO projet (code, nom, phase, chef_projet_id, equipe_code)
SELECT 'T1201X', 'Projet 12', 'EXE', id, 'MIDGARD' FROM utilisateur WHERE email = 't12-c@test.tn';

DO $$
DECLARE
  u   BIGINT := (SELECT id FROM utilisateur WHERE email = 't12-i@test.tn');
  gy  BIGINT := (SELECT id FROM utilisateur WHERE email = 't12-g@test.tn');
  ad  BIGINT := (SELECT id FROM utilisateur WHERE email = 't12-a@test.tn');
  p   BIGINT := (SELECT id FROM projet WHERE code = 'T1201X');
  auj DATE := (now() AT TIME ZONE 'Africa/Tunis')::DATE;
  sim DATE := (now() AT TIME ZONE 'Africa/Tunis')::DATE + 30;
  v   TEXT;
  n   INT := 0;
  attendu INT := 0;
  ligne RECORD;
BEGIN
  -- 1. fn_aujourdhui : sans réglage, aujourd'hui au fuseau ; avec, la date
  --    simulée (quel que soit le fuseau) ; valeur vide ou forgée : ignorée.
  IF fn_aujourdhui() <> auj OR fn_aujourdhui('Africa/Tunis') <> auj THEN
    RAISE EXCEPTION 'fn_aujourdhui sans date simulée : %', fn_aujourdhui();
  END IF;
  IF fn_aujourdhui('America/Cayenne') <> (now() AT TIME ZONE 'America/Cayenne')::DATE THEN
    RAISE EXCEPTION 'fn_aujourdhui en Guyane : %', fn_aujourdhui('America/Cayenne');
  END IF;
  FOREACH v IN ARRAY ARRAY['', 'abc', '2026-02-31', '2026-13-01', '15/10/2026', '2026-10-15; DROP TABLE x', ' 2026-10-15'] LOOP
    PERFORM set_config('kairos.date_simulee', v, true);
    IF fn_date_simulee() IS NOT NULL OR fn_aujourdhui() <> auj THEN
      RAISE EXCEPTION 'valeur forgée « % » non ignorée : %', v, fn_aujourdhui();
    END IF;
  END LOOP;
  PERFORM set_config('kairos.date_simulee', sim::TEXT, true);
  IF fn_aujourdhui() <> sim OR fn_aujourdhui('America/Cayenne') <> sim OR fn_date_simulee() <> sim THEN
    RAISE EXCEPTION 'date simulée non lue : %', fn_aujourdhui();
  END IF;
  PERFORM set_config('kairos.date_simulee', '', true);

  -- 2. Garde du Daily log : J+3 refusé sans date simulée…
  PERFORM set_config('app.current_user_id', u::TEXT, true);
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, auj + 3, p, 2);
  EXCEPTION WHEN check_violation THEN n := n + 1; END;
  --    … accepté avec la date simulée à J+3 (titulaire, dans sa fenêtre).
  PERFORM set_config('kairos.date_simulee', (auj + 3)::TEXT, true);
  INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, auj + 3, p, 2);
  --    Fenêtre de 14 jours décalée : avec la date simulée à J+30, le
  --    titulaire écrit J+16 (= simulée − 14), pas J+15 ni aujourd'hui réel.
  PERFORM set_config('kairos.date_simulee', sim::TEXT, true);
  INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, sim - 14, p, 1);
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, sim - 15, p, 1);
  EXCEPTION WHEN insufficient_privilege THEN n := n + 1; END;
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, auj, p, 1);
  EXCEPTION WHEN insufficient_privilege THEN n := n + 1; END;
  --    Jour futur par rapport à la date simulée : refusé, même en Guyane.
  PERFORM set_config('app.current_user_id', gy::TEXT, true);
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (gy, sim + 1, p, 1);
  EXCEPTION WHEN check_violation THEN n := n + 1; END;
  INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (gy, sim, p, 1);
  --    Sans date simulée : retour à la règle réelle (J+16 hors limites).
  PERFORM set_config('kairos.date_simulee', '', true);
  PERFORM set_config('app.current_user_id', u::TEXT, true);
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, sim - 13, p, 1);
  EXCEPTION WHEN check_violation THEN n := n + 1; END;

  -- 3. Journal d'audit : l'Admin réel est recopié, l'auteur reste le compte cible.
  PERFORM set_config('app.admin_reel_id', ad::TEXT, true);
  INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, auj - 1, p, 1);
  SELECT utilisateur_id, admin_reel_id INTO ligne FROM audit_log
   WHERE table_cible = 'dailylog_entree' AND action = 'INSERT' ORDER BY id DESC LIMIT 1;
  IF ligne.utilisateur_id IS DISTINCT FROM u OR ligne.admin_reel_id IS DISTINCT FROM ad THEN
    RAISE EXCEPTION 'audit agir comme : auteur %, admin réel % (attendus %, %)', ligne.utilisateur_id, ligne.admin_reel_id, u, ad;
  END IF;
  UPDATE dailylog_entree SET heures = 1.5 WHERE utilisateur_id = u AND date = auj - 1;
  DELETE FROM dailylog_entree WHERE utilisateur_id = u AND date = auj - 1;
  IF (SELECT count(*) FROM audit_log WHERE table_cible = 'dailylog_entree' AND admin_reel_id = ad
        AND action IN ('UPDATE', 'DELETE')) <> 2 THEN
    RAISE EXCEPTION 'audit agir comme : UPDATE / DELETE sans admin réel';
  END IF;
  --    Valeur forgée ou absente : NULL.
  FOREACH v IN ARRAY ARRAY['', 'x', '1; DROP TABLE audit_log', '-1'] LOOP
    PERFORM set_config('app.admin_reel_id', v, true);
    IF fn_app_admin_reel_id() IS NOT NULL THEN
      RAISE EXCEPTION 'admin réel forgé « % » accepté', v;
    END IF;
  END LOOP;
  INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, auj - 2, p, 1);
  IF (SELECT admin_reel_id FROM audit_log WHERE table_cible = 'dailylog_entree' ORDER BY id DESC LIMIT 1) IS NOT NULL THEN
    RAISE EXCEPTION 'audit sans admin réel : admin_reel_id renseigné';
  END IF;

  -- 4. Entrées / sorties des modes : ENTREE et SORTIE acceptées, rien d'autre.
  INSERT INTO audit_log (table_cible, ligne_id, action, utilisateur_id, admin_reel_id, donnees_apres)
  VALUES ('mode_voir_comme', u, 'ENTREE', ad, ad, '{"mode": "voir"}'),
         ('mode_voir_comme', u, 'SORTIE', ad, ad, '{"mode": "voir"}');
  attendu := attendu + 1;
  BEGIN INSERT INTO audit_log (table_cible, action, utilisateur_id) VALUES ('mode_voir_comme', 'VOIR', ad);
  EXCEPTION WHEN check_violation THEN n := n + 1; END;
  --    admin_reel_id : clé étrangère vers utilisateur.
  attendu := attendu + 1;
  BEGIN INSERT INTO audit_log (table_cible, action, utilisateur_id, admin_reel_id) VALUES ('t', 'ENTREE', ad, -42);
  EXCEPTION WHEN foreign_key_violation THEN n := n + 1; END;

  IF n <> attendu THEN
    RAISE EXCEPTION 'lot12.sql : % refus sur % attendus', n, attendu;
  END IF;
  RAISE NOTICE 'lot12.sql : % refus attendus obtenus', n;
END $$;

ROLLBACK;

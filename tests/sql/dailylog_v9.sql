-- Daily log v9 (migration 0014) sur un vrai PostgreSQL : nouvelles règles
-- (pas de 30 min, 10 h par jour, absence exclusive, date plausible au
-- fuseau du titulaire, comptes sans Daily log, fenêtre de 14 jours selon
-- l'acteur) appliquées aux seules valeurs qui CHANGENT ; données
-- anciennes intactes ; reprise Chronos possible. Tout est annulé
-- (ROLLBACK). Lancé par la CI avec psql -v ON_ERROR_STOP=1 sur la base
-- neuve, la base montée de version et la base « comme en production ».
BEGIN;
SET CONSTRAINTS ALL IMMEDIATE;  -- les contraintes différées jouent à chaque ordre

INSERT INTO utilisateur (email, mot_de_passe_hash, prenom, nom, role, equipe_code) VALUES
  ('t-dl9-i@test.tn', 'x', 'T', 'Inter', 'intervenant', 'MIDGARD'),
  ('t-dl9-c@test.tn', 'x', 'T', 'Chef', 'chef_de_projet', 'MIDGARD'),
  ('t-dl9-c2@test.tn', 'x', 'T', 'Chef2', 'chef_de_projet', 'MIDGARD'),
  ('t-dl9-a@test.tn', 'x', 'T', 'Admin', 'admin', 'MIDGARD'),
  ('t-dl9-g@test.tn', 'x', 'T', 'Guyane', 'intervenant', 'MIDGARD');
INSERT INTO projet (code, nom, phase, chef_projet_id, equipe_code)
SELECT 'T0901X', 'Projet A', 'EXE', id, 'MIDGARD' FROM utilisateur WHERE email = 't-dl9-c@test.tn';
INSERT INTO projet (code, nom, phase, chef_projet_id, equipe_code)
SELECT 'T0902X', 'Projet B', 'EXE', id, 'MIDGARD' FROM utilisateur WHERE email = 't-dl9-c2@test.tn';

DO $$
DECLARE
  u  BIGINT := (SELECT id FROM utilisateur WHERE email = 't-dl9-i@test.tn');
  ch BIGINT := (SELECT id FROM utilisateur WHERE email = 't-dl9-c@test.tn');
  c2 BIGINT := (SELECT id FROM utilisateur WHERE email = 't-dl9-c2@test.tn');
  ad BIGINT := (SELECT id FROM utilisateur WHERE email = 't-dl9-a@test.tn');
  gy BIGINT := (SELECT id FROM utilisateur WHERE email = 't-dl9-g@test.tn');
  pa BIGINT := (SELECT id FROM projet WHERE code = 'T0901X');
  pb BIGINT := (SELECT id FROM projet WHERE code = 'T0902X');
  auj DATE := (now() AT TIME ZONE 'Africa/Tunis')::DATE;
  d  DATE := (now() AT TIME ZONE 'Africa/Tunis')::DATE - 3;
  vieux DATE := (now() AT TIME ZONE 'Africa/Tunis')::DATE - 120;
  n  INT := 0;
  attendu INT := 0;
  etape TEXT;
BEGIN
  -- 1. Reprise de l'historique : valeurs hors grille et journée de 12 h acceptées.
  PERFORM set_config('kairos.reprise_historique', 'on', true);
  INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES
    (u, vieux, pa, 6.67), (u, vieux, pb, 5.33);
  PERFORM set_config('kairos.reprise_historique', 'off', true);

  -- 2. Ancienne valeur réécrite à l'identique : acceptée. Réduite : acceptée
  --    (la journée de 12 h se rapproche de la règle). Suppression : acceptée.
  UPDATE dailylog_entree SET heures = 6.67 WHERE utilisateur_id = u AND date = vieux AND projet_id = pa;
  UPDATE dailylog_entree SET heures = 5 WHERE utilisateur_id = u AND date = vieux AND projet_id = pb;
  DELETE FROM dailylog_entree WHERE utilisateur_id = u AND date = vieux AND projet_id = pb;

  -- 3. Pas de 30 min.
  INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, d, pa, 2.5);
  etape := 'quart d''heure';
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, d, pb, 0.25);
  EXCEPTION WHEN check_violation THEN n := n + 1; END;
  attendu := attendu + 1;
  BEGIN UPDATE dailylog_entree SET heures = 6.75 WHERE utilisateur_id = u AND date = vieux AND projet_id = pa;
  EXCEPTION WHEN check_violation THEN n := n + 1; END;

  -- 4. 10 h par jour au plus (insertion et mise à jour à la hausse).
  INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, d, pb, 7.5);  -- 10 h pile
  attendu := attendu + 1;
  BEGIN UPDATE dailylog_entree SET heures = 8 WHERE utilisateur_id = u AND date = d AND projet_id = pb;
  EXCEPTION WHEN check_violation THEN n := n + 1; END;
  -- Ancienne journée hors grille : la modifier impose la grille…
  UPDATE dailylog_entree SET heures = 7 WHERE utilisateur_id = u AND date = vieux AND projet_id = pa;
  -- … et au-delà de 10 h, refusé.
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, vieux, pb, 3.5);
  EXCEPTION WHEN check_violation THEN n := n + 1; END;

  -- 5. Échange d'heures entre deux lignes dans une même transaction : la
  --    contrainte est différée, l'état intermédiaire à 12 h n'est pas refusé.
  SET CONSTRAINTS ALL DEFERRED;
  UPDATE dailylog_entree SET heures = 4.5 WHERE utilisateur_id = u AND date = d AND projet_id = pb;  -- 7 h au total
  UPDATE dailylog_entree SET heures = 5.5 WHERE utilisateur_id = u AND date = d AND projet_id = pa;  -- 10 h
  SET CONSTRAINTS ALL IMMEDIATE;  -- vérifie maintenant : aucun refus
  IF (SELECT sum(heures) FROM dailylog_entree WHERE utilisateur_id = u AND date = d) <> 10 THEN
    RAISE EXCEPTION 'échange d''heures : total inattendu';
  END IF;

  -- 6. Absence exclusive des heures, dans les deux sens.
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_jour (utilisateur_id, date, absent) VALUES (u, d, true);
  EXCEPTION WHEN check_violation THEN n := n + 1; END;
  INSERT INTO dailylog_jour (utilisateur_id, date, absent) VALUES (u, d - 1, true);
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, d - 1, pa, 1);
  EXCEPTION WHEN check_violation THEN n := n + 1; END;
  -- Absence posée après suppression des lignes, dans la même transaction : acceptée.
  SET CONSTRAINTS ALL DEFERRED;
  INSERT INTO dailylog_jour (utilisateur_id, date, absent) VALUES (u, d, true);
  DELETE FROM dailylog_entree WHERE utilisateur_id = u AND date = d;
  SET CONSTRAINTS ALL IMMEDIATE;

  -- 7. Dates : futur au fuseau du titulaire, an 1.
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, auj + 1, pa, 1);
  EXCEPTION WHEN check_violation THEN n := n + 1; END;
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, DATE '0001-01-05', pa, 1);
  EXCEPTION WHEN check_violation THEN n := n + 1; END;
  UPDATE utilisateur SET fuseau = 'America/Cayenne' WHERE id = gy;
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures)
        VALUES (gy, (now() AT TIME ZONE 'America/Cayenne')::DATE + 1, pa, 1);
  EXCEPTION WHEN check_violation THEN n := n + 1; END;
  INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures)
  VALUES (gy, (now() AT TIME ZONE 'America/Cayenne')::DATE, pa, 1);  -- aujourd'hui en Guyane : accepté

  -- 8. Pas de Daily log pour un compte RH ou Client.
  attendu := attendu + 1;
  BEGIN
    INSERT INTO utilisateur (email, mot_de_passe_hash, prenom, nom, role) VALUES ('t-dl9-cl@test.tn', 'x', 'T', 'Client', 'client');
    INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures)
    VALUES ((SELECT id FROM utilisateur WHERE email = 't-dl9-cl@test.tn'), d, pa, 1);
  EXCEPTION WHEN check_violation THEN n := n + 1; END;

  -- 9. Fenêtre de 14 jours selon l'acteur (app.current_user_id).
  PERFORM set_config('app.current_user_id', u::text, true);
  INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, auj - 14, pa, 1);  -- J-14 : libre
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, auj - 15, pa, 1);
  EXCEPTION WHEN insufficient_privilege THEN n := n + 1; END;
  attendu := attendu + 1;
  BEGIN DELETE FROM dailylog_entree WHERE utilisateur_id = u AND date = vieux;
  EXCEPTION WHEN insufficient_privilege THEN n := n + 1; END;
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_jour (utilisateur_id, date, absent) VALUES (u, auj - 20, true);
  EXCEPTION WHEN insufficient_privilege THEN n := n + 1; END;
  -- Le chef du projet A corrige la ligne A au-delà de 14 jours (et crée l'état du jour)…
  PERFORM set_config('app.current_user_id', ch::text, true);
  INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, auj - 30, pa, 2);
  INSERT INTO dailylog_jour (utilisateur_id, date, absent, version) VALUES (u, auj - 30, false, 1);
  UPDATE dailylog_jour SET version = version + 1 WHERE utilisateur_id = u AND date = auj - 30;
  UPDATE dailylog_entree SET heures = 7.5 WHERE utilisateur_id = u AND date = vieux AND projet_id = pa;
  -- … mais pas la ligne du projet B (autre chef), ni l'absence.
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, auj - 30, pb, 2);
  EXCEPTION WHEN insufficient_privilege THEN n := n + 1; END;
  attendu := attendu + 1;
  BEGIN UPDATE dailylog_jour SET absent = true WHERE utilisateur_id = u AND date = auj - 30;
  EXCEPTION WHEN insufficient_privilege THEN n := n + 1; END;
  -- Co-chef : mêmes droits que le chef titulaire.
  INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (pb, ch);
  INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, auj - 30, pb, 2);
  -- L'Admin corrige tout, absence comprise.
  PERFORM set_config('app.current_user_id', ad::text, true);
  DELETE FROM dailylog_entree WHERE utilisateur_id = u AND date = auj - 30;
  UPDATE dailylog_jour SET absent = true WHERE utilisateur_id = u AND date = auj - 30;
  PERFORM set_config('app.current_user_id', '', true);

  -- 10. Objectif de journée et fuseau.
  INSERT INTO dailylog_preference (utilisateur_id, objectif_minutes) VALUES (u, 510);
  UPDATE dailylog_preference SET objectif_minutes = 240 WHERE utilisateur_id = u;
  UPDATE dailylog_preference SET objectif_minutes = 600 WHERE utilisateur_id = u;
  attendu := attendu + 1;
  BEGIN UPDATE dailylog_preference SET objectif_minutes = 275 WHERE utilisateur_id = u;
  EXCEPTION WHEN check_violation THEN n := n + 1; END;
  attendu := attendu + 1;
  BEGIN UPDATE dailylog_preference SET objectif_minutes = 210 WHERE utilisateur_id = u;
  EXCEPTION WHEN check_violation THEN n := n + 1; END;
  attendu := attendu + 1;
  BEGIN UPDATE dailylog_preference SET objectif_minutes = 630 WHERE utilisateur_id = u;
  EXCEPTION WHEN check_violation THEN n := n + 1; END;
  attendu := attendu + 1;
  BEGIN UPDATE utilisateur SET fuseau = 'Europe/Paris' WHERE id = u;
  EXCEPTION WHEN check_violation THEN n := n + 1; END;

  IF n <> attendu THEN
    RAISE EXCEPTION 'Daily log v9 : % refus sur % attendus', n, attendu;
  END IF;
  IF fn_sans_accents('Résidence ÉTÉ') <> 'residence ete' THEN
    RAISE EXCEPTION 'fn_sans_accents : %', fn_sans_accents('Résidence ÉTÉ');
  END IF;
  -- Une base neuve et une base migrée marquent la version de la même façon.
  IF (SELECT column_default FROM information_schema.columns
      WHERE table_name = 'dailylog_jour' AND column_name = 'version') <> '1' THEN
    RAISE EXCEPTION 'dailylog_jour.version : défaut inattendu';
  END IF;
  RAISE NOTICE 'dailylog_v9.sql : % refus attendus obtenus', n;
END $$;

ROLLBACK;

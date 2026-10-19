-- Lot 13 (migration 0019) sur un vrai PostgreSQL : état du projet recalculé
-- (fn_etat_projet_recalcule), instant simulé lu au fuseau de chacun
-- (fn_instant_simule, fn_aujourdhui), vraie date (fn_aujourdhui_reel), date
-- d'une clôture (fn_date_ecriture = LEAST), garde du Daily log contre le
-- futur réel (dailylog_futur_reel), notification.projet_id / simulee et
-- nouveaux posts automatiques. Tout est annulé (ROLLBACK). Lancé par la CI
-- avec psql -v ON_ERROR_STOP=1 sur la base neuve, la base montée de version
-- et la base « comme en production ».
BEGIN;
SET CONSTRAINTS ALL IMMEDIATE;

INSERT INTO utilisateur (email, mot_de_passe_hash, prenom, nom, role, equipe_code, fuseau) VALUES
  ('t13-i@test.tn', 'x', 'T', 'Inter', 'intervenant', 'MIDGARD', 'Africa/Tunis'),
  ('t13-g@test.tn', 'x', 'T', 'Guyane', 'intervenant', 'MIDGARD', 'America/Cayenne'),
  ('t13-c@test.tn', 'x', 'T', 'Chef', 'chef_de_projet', 'MIDGARD', 'Africa/Tunis');
INSERT INTO projet (code, nom, phase, chef_projet_id, equipe_code)
SELECT 'T1301X', 'Projet 13', 'EXE', id, 'MIDGARD' FROM utilisateur WHERE email = 't13-c@test.tn';

DO $$
DECLARE
  u   BIGINT := (SELECT id FROM utilisateur WHERE email = 't13-i@test.tn');
  gy  BIGINT := (SELECT id FROM utilisateur WHERE email = 't13-g@test.tn');
  c   BIGINT := (SELECT id FROM utilisateur WHERE email = 't13-c@test.tn');
  p   BIGINT := (SELECT id FROM projet WHERE code = 'T1301X');
  auj DATE := (now() AT TIME ZONE 'Africa/Tunis')::DATE;
  t1  BIGINT;
  t2  BIGINT;
  v   TEXT;
  n   INT := 0;
  attendu INT := 0;
BEGIN
  -- 1. État attendu du projet : Bloqué ⇔ une tâche bloquée (projet ouvert).
  INSERT INTO tache (projet_id, titre, created_by) VALUES (p, 'A', c) RETURNING id INTO t1;
  INSERT INTO tache (projet_id, titre, created_by) VALUES (p, 'B', c) RETURNING id INTO t2;
  IF fn_etat_projet_recalcule('bloque', p) <> 'en_cours' OR fn_etat_projet_recalcule('en_cours', p) <> 'en_cours' THEN
    RAISE EXCEPTION 'projet sans tâche bloquée : %', fn_etat_projet_recalcule('bloque', p);
  END IF;
  UPDATE tache SET etat = 'bloque', bloque_le = fn_maintenant() WHERE id = t1;  -- comme l'appli (0025 : horodatage à l'écriture)
  IF fn_etat_projet_recalcule('en_cours', p) <> 'bloque' THEN
    RAISE EXCEPTION 'projet avec une tâche bloquée : %', fn_etat_projet_recalcule('en_cours', p);
  END IF;
  IF fn_etat_projet_recalcule('termine', p) <> 'termine' OR fn_etat_projet_recalcule('abandonne', p) <> 'abandonne' THEN
    RAISE EXCEPTION 'un projet clos garde son état';
  END IF;

  -- 2. Instant simulé : lu au fuseau de chacun ; valeur forgée ignorée.
  PERFORM set_config('kairos.instant_simule', '2026-10-20T23:30:00+01:00', true);
  IF fn_aujourdhui() <> DATE '2026-10-20' OR fn_aujourdhui('America/Cayenne') <> DATE '2026-10-20' THEN
    RAISE EXCEPTION 'instant 23 h 30 Tunis : % / %', fn_aujourdhui(), fn_aujourdhui('America/Cayenne');
  END IF;
  PERFORM set_config('kairos.instant_simule', '2026-10-21T02:00:00+01:00', true);
  IF fn_aujourdhui() <> DATE '2026-10-21' OR fn_aujourdhui('America/Cayenne') <> DATE '2026-10-20' THEN
    RAISE EXCEPTION 'instant 2 h Tunis : Cayenne encore la veille attendu : % / %', fn_aujourdhui(), fn_aujourdhui('America/Cayenne');
  END IF;
  --    L'instant simulé passe avant la date simulée (0018).
  PERFORM set_config('kairos.date_simulee', '2030-01-01', true);
  IF fn_aujourdhui() <> DATE '2026-10-21' THEN
    RAISE EXCEPTION 'instant simulé prioritaire : %', fn_aujourdhui();
  END IF;
  PERFORM set_config('kairos.date_simulee', '', true);
  FOREACH v IN ARRAY ARRAY['', 'abc', '2026-10-20', '2026-10-20 23:30', '2026-13-20T23:30:00+01:00',
                           '1999-12-31T23:00:00+00:00', '2100-01-01T00:00:00+00:00',
                           '2026-10-20T23:30:00+01:00; DROP TABLE projet', ' 2026-10-20T23:30:00+01:00'] LOOP
    PERFORM set_config('kairos.instant_simule', v, true);
    IF fn_instant_simule() IS NOT NULL OR fn_aujourdhui() <> auj THEN
      RAISE EXCEPTION 'instant forgé « % » non ignoré : %', v, fn_aujourdhui();
    END IF;
  END LOOP;

  -- 3. Vraie date et date d'une écriture (LEAST).
  PERFORM set_config('kairos.instant_simule', ((auj + 10)::TEXT || 'T12:00:00+01:00'), true);
  IF fn_aujourdhui_reel() <> auj OR fn_aujourdhui() <> auj + 10 OR fn_date_ecriture() <> auj THEN
    RAISE EXCEPTION 'futur simulé : réel %, simulé %, écriture %', fn_aujourdhui_reel(), fn_aujourdhui(), fn_date_ecriture();
  END IF;
  PERFORM set_config('kairos.instant_simule', ((auj - 10)::TEXT || 'T12:00:00+01:00'), true);
  IF fn_date_ecriture() <> auj - 10 THEN
    RAISE EXCEPTION 'passé simulé : écriture % au lieu de %', fn_date_ecriture(), auj - 10;
  END IF;
  PERFORM set_config('kairos.instant_simule', '', true);
  IF fn_date_ecriture('America/Cayenne') <> (now() AT TIME ZONE 'America/Cayenne')::DATE THEN
    RAISE EXCEPTION 'écriture en Guyane : %', fn_date_ecriture('America/Cayenne');
  END IF;

  -- 4. Garde du Daily log : rien après la vraie date, même sous date
  --    simulée ; le passé simulé reste saisissable dans sa fenêtre.
  PERFORM set_config('app.current_user_id', u::TEXT, true);
  PERFORM set_config('kairos.instant_simule', ((auj + 5)::TEXT || 'T12:00:00+01:00'), true);
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, auj + 2, p, 1);
  EXCEPTION WHEN check_violation THEN
    IF SQLERRM LIKE '%vraie date du jour%' THEN n := n + 1; END IF;
  END;
  attendu := attendu + 1;
  BEGIN INSERT INTO dailylog_jour (utilisateur_id, date, absent, version) VALUES (u, auj + 1, true, 1);
  EXCEPTION WHEN check_violation THEN n := n + 1; END;
  INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, auj, p, 1);
  PERFORM set_config('kairos.instant_simule', ((auj - 20)::TEXT || 'T12:00:00+01:00'), true);
  INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (u, auj - 30, p, 1);
  PERFORM set_config('kairos.instant_simule', '', true);
  --    Une ligne future déjà en base (écrite avant 0019) se supprime toujours.
  PERFORM set_config('app.current_user_id', '', true);
  PERFORM set_config('kairos.reprise_historique', 'on', true);
  INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (gy, auj + 3, p, 1);
  PERFORM set_config('kairos.reprise_historique', '', true);
  DELETE FROM dailylog_entree WHERE utilisateur_id = gy AND date > auj;
  IF EXISTS (SELECT 1 FROM dailylog_entree WHERE utilisateur_id = gy) THEN
    RAISE EXCEPTION 'purge des lignes futures impossible';
  END IF;

  -- 5. Notifications et posts automatiques du lot 13.
  INSERT INTO notification (utilisateur_id, categorie, message, projet_id) VALUES (u, 'projet', 'ajouté', p);
  INSERT INTO notification (utilisateur_id, categorie, message, rappel_jours, simulee)
  VALUES (u, 'rh_info', 'simulé', ARRAY[auj - 1], true);
  IF (SELECT count(*) FROM notification WHERE utilisateur_id = u AND (projet_id = p OR simulee)) <> 2 THEN
    RAISE EXCEPTION 'notification.projet_id / simulee';
  END IF;
  IF (SELECT simulee FROM notification WHERE utilisateur_id = u AND projet_id = p) THEN
    RAISE EXCEPTION 'notification.simulee : faux par défaut';
  END IF;
  INSERT INTO post (projet_id, tache_id, auteur_id, type_code, contenu, evenement) VALUES
    (p, t1, c, 'information', 'x', 'intervenant_tache'),
    (p, t1, c, 'information', 'x', 'echeance_tache'),
    (p, NULL, c, 'information', 'x', 'intervenant_projet');
  attendu := attendu + 1;
  BEGIN INSERT INTO post (projet_id, auteur_id, type_code, contenu, evenement) VALUES (p, c, 'information', 'x', 'inconnu');
  EXCEPTION WHEN check_violation THEN n := n + 1; END;

  IF n <> attendu THEN
    RAISE EXCEPTION 'lot13.sql : % refus sur % attendus', n, attendu;
  END IF;
  RAISE NOTICE 'lot13.sql : % refus attendus obtenus', n;
END $$;

ROLLBACK;

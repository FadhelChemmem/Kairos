-- Lot 11 b (migration 0017) sur un vrai PostgreSQL : garde du changement de
-- chef de projet (trg_garde_chef_projet), post automatique 'chef_projet',
-- notification.rappel_jours (contrainte, rattrapage des rappels de
-- l'ancien format). Tout est annulé (ROLLBACK). Lancé par la CI avec psql
-- -v ON_ERROR_STOP=1 sur la base neuve, la base montée de version et la base
-- « comme en production ».
BEGIN;

INSERT INTO utilisateur (email, mot_de_passe_hash, prenom, nom, role, equipe_code, actif) VALUES
  ('t17-admin@test.tn', 'x', 'T', 'Admin', 'admin', 'MIDGARD', true),
  ('t17-chef@test.tn', 'x', 'T', 'Chef', 'chef_de_projet', 'MIDGARD', true),
  ('t17-cochef@test.tn', 'x', 'T', 'Cochef', 'chef_de_projet', 'MIDGARD', true),
  ('t17-autre@test.tn', 'x', 'T', 'Autre', 'chef_de_projet', 'MIDGARD', true),
  ('t17-inactif@test.tn', 'x', 'T', 'Inactif', 'chef_de_projet', 'MIDGARD', false),
  ('t17-inter@test.tn', 'x', 'T', 'Inter', 'intervenant', 'MIDGARD', true);
INSERT INTO projet (code, nom, phase, chef_projet_id, equipe_code)
SELECT 'T1701X', 'Chef', 'EXE', id, 'MIDGARD' FROM utilisateur WHERE email = 't17-chef@test.tn';
INSERT INTO projet_co_chef (projet_id, utilisateur_id)
SELECT p.id, u.id FROM projet p, utilisateur u WHERE p.code = 'T1701X' AND u.email = 't17-cochef@test.tn';

CREATE TEMP TABLE t17 (cle TEXT PRIMARY KEY, id BIGINT);
INSERT INTO t17 SELECT replace(replace(email, 't17-', ''), '@test.tn', ''), id FROM utilisateur WHERE email LIKE 't17-%';
INSERT INTO t17 SELECT 'projet', id FROM projet WHERE code = 'T1701X';

CREATE FUNCTION pg_temp.changer(acteur TEXT, nouveau TEXT) RETURNS TEXT AS $$
DECLARE
  v_etat TEXT;
BEGIN
  PERFORM set_config('app.current_user_id', coalesce((SELECT id::text FROM t17 WHERE cle = acteur), ''), true);
  BEGIN
    UPDATE projet SET chef_projet_id = (SELECT id FROM t17 WHERE cle = nouveau)
     WHERE id = (SELECT id FROM t17 WHERE cle = 'projet');
    v_etat := 'ok';
  EXCEPTION
    WHEN insufficient_privilege THEN v_etat := 'refus_droits';
    WHEN check_violation THEN v_etat := 'refus_chef';
  END;
  PERFORM set_config('app.current_user_id', '', true);
  RETURN v_etat;
END $$ LANGUAGE plpgsql;

DO $$
DECLARE
  v TEXT;
BEGIN
  -- Intervenant (ni chef ni co-chef) : refusé.
  v := pg_temp.changer('inter', 'autre');
  IF v <> 'refus_droits' THEN RAISE EXCEPTION 'intervenant : % (attendu refus_droits)', v; END IF;
  -- Nouveau chef désactivé ou de rôle intervenant : refusé.
  v := pg_temp.changer('chef', 'inactif');
  IF v <> 'refus_chef' THEN RAISE EXCEPTION 'chef désactivé : % (attendu refus_chef)', v; END IF;
  v := pg_temp.changer('chef', 'inter');
  IF v <> 'refus_chef' THEN RAISE EXCEPTION 'intervenant comme chef : % (attendu refus_chef)', v; END IF;
  -- Co-chef : accepté ; puis le titulaire (devenu « autre ») vers l'Admin.
  v := pg_temp.changer('cochef', 'autre');
  IF v <> 'ok' THEN RAISE EXCEPTION 'co-chef : %', v; END IF;
  v := pg_temp.changer('autre', 'admin');
  IF v <> 'ok' THEN RAISE EXCEPTION 'vers un Admin : %', v; END IF;
  -- Projet clos : le titulaire est refusé, l'Admin passe.
  UPDATE projet SET etat = 'termine' WHERE id = (SELECT id FROM t17 WHERE cle = 'projet');
  v := pg_temp.changer('admin', 'chef');
  IF v <> 'ok' THEN RAISE EXCEPTION 'Admin sur projet clos : %', v; END IF;
  v := pg_temp.changer('chef', 'autre');
  IF v <> 'refus_droits' THEN RAISE EXCEPTION 'chef sur projet clos : % (attendu refus_droits)', v; END IF;
  -- Sans utilisateur applicatif (script, psql) : aucune restriction.
  v := pg_temp.changer('personne', 'inactif');
  IF v <> 'ok' THEN RAISE EXCEPTION 'sans acteur : %', v; END IF;
  -- Une autre colonne ne déclenche rien, même chef désactivé et acteur intervenant.
  PERFORM set_config('app.current_user_id', (SELECT id::text FROM t17 WHERE cle = 'inter'), true);
  UPDATE projet SET nom = 'Renommé' WHERE id = (SELECT id FROM t17 WHERE cle = 'projet');
  PERFORM set_config('app.current_user_id', '', true);
  -- La création n'est pas concernée (règle de création inchangée).
  PERFORM set_config('app.current_user_id', (SELECT id::text FROM t17 WHERE cle = 'inter'), true);
  INSERT INTO projet (code, nom, phase, chef_projet_id) VALUES ('T1702X', 'Création', 'EXE', (SELECT id FROM t17 WHERE cle = 'inter'));
  PERFORM set_config('app.current_user_id', '', true);
END $$;

-- Post automatique du changement de chef.
INSERT INTO post (projet_id, auteur_id, type_code, contenu, evenement)
VALUES ((SELECT id FROM t17 WHERE cle = 'projet'), (SELECT id FROM t17 WHERE cle = 'admin'), 'information',
        'T Admin a confié le projet à T Chef.', 'chef_projet');
DO $$
BEGIN
  BEGIN
    INSERT INTO post (projet_id, auteur_id, type_code, contenu, evenement)
    VALUES ((SELECT id FROM t17 WHERE cle = 'projet'), (SELECT id FROM t17 WHERE cle = 'admin'), 'information', 'x', 'inconnu');
    RAISE EXCEPTION 'evenement inconnu accepté';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

-- Rappels Daily log : contrainte et rattrapage de l'ancien format (rejouable).
INSERT INTO notification (utilisateur_id, categorie, message) VALUES
  ((SELECT id FROM t17 WHERE cle = 'inter'), 'rh_info', 'Rappel DailyLog : vous n''avez pas rempli votre journée du 07/10/2026.'),
  ((SELECT id FROM t17 WHERE cle = 'inter'), 'projet', 'Rappel DailyLog : réunion du 06/10/2026.'),
  ((SELECT id FROM t17 WHERE cle = 'inter'), 'rh_info', 'Daily log du 03/10/2026 corrigé par T Chef.');
INSERT INTO notification (utilisateur_id, categorie, message, rappel_jours) VALUES
  ((SELECT id FROM t17 WHERE cle = 'inter'), 'rh_info', '2 jours de Daily log non remplis : lundi 5 et mardi 6 octobre',
   ARRAY['2026-10-05', '2026-10-06']::date[]);
DO $$
BEGIN
  BEGIN
    INSERT INTO notification (utilisateur_id, categorie, message, rappel_jours)
    VALUES ((SELECT id FROM t17 WHERE cle = 'inter'), 'rh_info', 'vide', '{}'::date[]);
    RAISE EXCEPTION 'rappel_jours vide accepté';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;
-- Même instruction que la migration 0017, jouée deux fois.
UPDATE notification
   SET rappel_jours = ARRAY[to_date(substring(message from '([0-9]{2}/[0-9]{2}/[0-9]{4})'), 'DD/MM/YYYY')]
 WHERE rappel_jours IS NULL AND categorie = 'rh_info' AND message LIKE 'Rappel DailyLog%'
   AND message ~ '[0-9]{2}/[0-9]{2}/[0-9]{4}';
UPDATE notification
   SET rappel_jours = ARRAY[to_date(substring(message from '([0-9]{2}/[0-9]{2}/[0-9]{4})'), 'DD/MM/YYYY')]
 WHERE rappel_jours IS NULL AND categorie = 'rh_info' AND message LIKE 'Rappel DailyLog%'
   AND message ~ '[0-9]{2}/[0-9]{2}/[0-9]{4}';
DO $$
DECLARE
  v TEXT;
BEGIN
  SELECT string_agg(coalesce(rappel_jours::text, 'NULL'), ' | ' ORDER BY id) INTO v
  FROM notification WHERE utilisateur_id = (SELECT id FROM t17 WHERE cle = 'inter');
  IF v <> '{2026-10-07} | NULL | NULL | {2026-10-05,2026-10-06}' THEN
    RAISE EXCEPTION 'rappel_jours après rattrapage : %', v;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_notification_rappel_jours') THEN
    RAISE EXCEPTION 'index idx_notification_rappel_jours absent';
  END IF;
END $$;

ROLLBACK;

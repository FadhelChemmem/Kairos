"""Jeu de données du scénario Playwright « Daily log de l'équipe » (lot 14,
A3) : un chef (Ali) et ses projets 1 et 2, une co-cheffe (Nadia, projet 1),
deux intervenants (Rim : tâche du projet 1 ; Sami : projet 2), une équipe
URBS (Omar, chef du projet 3, et Lina) que le chef ne voit pas, un RH et un
client. Daily log de la semaine dernière : Rim remplie lundi à mercredi
(7 h 30), absente jeudi, rien vendredi, 3 h le samedi ; Sami lundi seulement.

Usage : python tests_e2e/seed_dailylog_equipe.py <base>   (base créée depuis schema.sql)
Comptes (mot de passe Kairos2026!) : admin@x.tn, ali@x.tn, nadia@x.tn,
rim@x.tn, sami@x.tn, omar@x.tn, lina@x.tn, rh@x.tn, client@x.tn.
"""
import os
import subprocess
import sys

from werkzeug.security import generate_password_hash

H = generate_password_hash("Kairos2026!")
sql = f"""
SET kairos.reprise_historique = 'on';
INSERT INTO utilisateur (id, email, mot_de_passe_hash, prenom, nom, role, equipe_code, created_at, verifie, fuseau) VALUES
 (1, 'admin@x.tn', '{H}', 'Fadhel', 'Admin', 'admin', 'MIDGARD', now() - interval '200 days', true, 'Africa/Tunis'),
 (2, 'ali@x.tn', '{H}', 'Ali', 'Chef', 'chef_de_projet', 'MIDGARD', now() - interval '200 days', true, 'Africa/Tunis'),
 (3, 'rim@x.tn', '{H}', 'Rim', 'Inter', 'intervenant', 'MIDGARD', now() - interval '200 days', true, 'Africa/Tunis'),
 (4, 'sami@x.tn', '{H}', 'Sami', 'Calcul', 'intervenant', 'MIDGARD', now() - interval '200 days', true, 'Africa/Tunis'),
 (5, 'nadia@x.tn', '{H}', 'Nadia', 'Cochef', 'chef_de_projet', 'MIDGARD', now() - interval '200 days', true, 'Africa/Tunis'),
 (6, 'omar@x.tn', '{H}', 'Omar', 'Urbs', 'chef_de_projet', 'URBS', now() - interval '200 days', true, 'Africa/Tunis'),
 (7, 'lina@x.tn', '{H}', 'Lina', 'Urbs', 'intervenant', 'URBS', now() - interval '200 days', true, 'America/Cayenne'),
 (8, 'rh@x.tn', '{H}', 'Rania', 'RH', 'rh', NULL, now() - interval '200 days', true, 'Africa/Tunis'),
 (9, 'client@x.tn', '{H}', 'Cli', 'Ent', 'client', 'VD', now() - interval '200 days', true, 'Africa/Tunis'),
 (10, 'ancien@x.tn', '{H}', 'Ancien', 'Compte', 'intervenant', 'MIDGARD', now() - interval '200 days', true, 'Africa/Tunis');
UPDATE utilisateur SET actif = false WHERE id = 10;
SELECT setval(pg_get_serial_sequence('utilisateur','id'), 10);
INSERT INTO projet (id, code, nom, phase, chef_projet_id, equipe_code, etat) VALUES
 (1, '26069D', 'Fondations Hangar GRL2', 'EXE', 2, 'MIDGARD', 'en_cours'),
 (2, '26006P', 'The hub', 'EXE', 2, 'MIDGARD', 'en_cours'),
 (3, '26210X', 'Passerelle Kourou', 'EXE', 6, 'URBS', 'en_cours');
SELECT setval(pg_get_serial_sequence('projet','id'), 3);
INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (1, 5);
INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (2, 4), (3, 7), (1, 10);
INSERT INTO tache (id, projet_id, titre, created_by, etat, date_echeance) VALUES
 (1, 1, 'Note de calcul', 2, 'en_cours', CURRENT_DATE + 7),
 (2, 3, 'Ferraillage passerelle', 6, 'en_cours', CURRENT_DATE + 7);
SELECT setval(pg_get_serial_sequence('tache','id'), 2);
INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (1, 3), (2, 7);
WITH s AS (SELECT (date_trunc('week', CURRENT_DATE)::date - 7) AS lundi)
INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures, updated_by)
SELECT 3, lundi + i, 1, 1, 7.5, 3 FROM s, generate_series(0, 2) AS i
UNION ALL SELECT 3, lundi + 5, 1, NULL, 3, 3 FROM s
UNION ALL SELECT 4, lundi, 2, NULL, 8, 4 FROM s
UNION ALL SELECT 7, lundi, 3, 2, 6, 7 FROM s;
WITH s AS (SELECT (date_trunc('week', CURRENT_DATE)::date - 7) AS lundi)
INSERT INTO dailylog_jour (utilisateur_id, date, absent, version, updated_by)
SELECT 3, lundi + 3, true, 1, 3 FROM s;
"""
base = sys.argv[1]
env = dict(os.environ)
env.setdefault("PGHOST", "127.0.0.1")
env.setdefault("PGUSER", "kairos")
env.setdefault("PGPASSWORD", "kairos")
subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", base],
               input=sql, text=True, check=True, env=env, stdout=subprocess.DEVNULL)
print("Jeu de données « Daily log de l’équipe » chargé dans", base)

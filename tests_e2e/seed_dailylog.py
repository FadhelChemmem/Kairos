"""Jeu de données du scénario Playwright du Daily log v9 (lot 10).

Usage : python tests_e2e/seed_dailylog.py <base>   (base créée depuis schema.sql)
Variables PGHOST / PGUSER / PGPASSWORD habituelles (défaut 127.0.0.1 / kairos).
Comptes : admin@x.tn, ali@x.tn (chef MIDGARD), rim@x.tn (intervenante),
omar@x.tn (chef URBS), guyane@x.tn (Cayenne) — mot de passe Kairos2026!
Historique de Rim : journées remplies, absence, quart d'heure v2 (2,25 h),
journée Chronos de 12 h (J-60), journée au-delà de 14 jours (J-20).
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
 (4, 'omar@x.tn', '{H}', 'Omar', 'Urbs', 'chef_de_projet', 'URBS', now() - interval '200 days', true, 'Africa/Tunis'),
 (5, 'guyane@x.tn', '{H}', 'Gaël', 'Guyane', 'intervenant', 'MIDGARD', now() - interval '200 days', true, 'America/Cayenne'),
 (6, 'rh@x.tn', '{H}', 'Rania', 'RH', 'rh', NULL, now() - interval '200 days', true, 'Africa/Tunis'),
 (7, 'client@x.tn', '{H}', 'Cli', 'Ent', 'client', 'MIDGARD', now() - interval '200 days', true, 'Africa/Tunis'),
 (8, 'nouveau@x.tn', '{H}', 'Nina', 'Nouvelle', 'intervenant', 'MIDGARD', now() - interval '3 days', true, 'Africa/Tunis');
SELECT setval(pg_get_serial_sequence('utilisateur','id'), 8);
INSERT INTO projet (id, code, nom, phase, chef_projet_id, equipe_code, etat, date_debut, date_cloture) VALUES
 (1, '26069D', 'Fondations Hangar GRL2', 'EXE', 2, 'MIDGARD', 'en_cours', NULL, NULL),
 (2, '26006P', 'The hub', 'EXE', 2, 'MIDGARD', 'en_cours', NULL, NULL),
 (3, '26921P', 'Point bois', 'EXE', 2, 'MIDGARD', 'bloque', NULL, NULL),
 (4, '25140P', 'Résidence Été', 'EXE', 2, 'MIDGARD', 'en_cours', NULL, NULL),
 (5, '26210X', 'Passerelle Kourou', 'EXE', 4, 'URBS', 'en_cours', NULL, NULL),
 (6, '24088D', 'Entrepôt Degrad', 'EXE', 2, 'MIDGARD', 'termine', NULL, CURRENT_DATE - 10),
 (7, '26077X', 'Villa YVALBI', 'EXE', 2, 'MIDGARD', 'en_cours', NULL, NULL),
 (8, '26083X', 'Villa OLOL', 'EXE', 2, 'MIDGARD', 'en_cours', CURRENT_DATE + 30, NULL);
SELECT setval(pg_get_serial_sequence('projet','id'), 8);
INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (1, 3), (2, 3), (3, 3), (5, 3), (1, 5), (2, 8);
INSERT INTO tache (id, projet_id, titre, created_by, etat, date_echeance) VALUES
 (1, 1, 'Note de calcul', 2, 'en_cours', CURRENT_DATE + 7),
 (2, 1, 'Plans de ferraillage', 2, 'en_cours', CURRENT_DATE + 14),
 (3, 2, 'Descente de charges', 2, 'bloque', CURRENT_DATE + 3);
SELECT setval(pg_get_serial_sequence('tache','id'), 3);
-- Lot 20 : le Daily log propose ce qui était en cours LE JOUR AFFICHÉ —
-- projets et tâches créés bien avant le scénario.
UPDATE projet SET created_at = now() - interval '200 days';
UPDATE tache SET created_at = now() - interval '60 days';
INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (1, 3);
-- Historique de Rim : journées remplies, absence, quart d'heure v2, Chronos 12 h
INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures, updated_by) VALUES
 (3, CURRENT_DATE - 6, 1, NULL, 3, 3), (3, CURRENT_DATE - 6, 2, NULL, 3, 3), (3, CURRENT_DATE - 6, 7, NULL, 2, 3),
 (3, CURRENT_DATE - 5, 1, 1, 2.25, 3), (3, CURRENT_DATE - 5, 2, NULL, 5.75, 3),
 (3, CURRENT_DATE - 20, 1, NULL, 4, 3), (3, CURRENT_DATE - 20, 5, NULL, 4, 3),
 (3, CURRENT_DATE - 60, 1, NULL, 7, 3), (3, CURRENT_DATE - 60, 2, NULL, 5, 3);
INSERT INTO dailylog_jour (utilisateur_id, date, absent, version, updated_by) VALUES
 (3, CURRENT_DATE - 6, false, 1, 3), (3, CURRENT_DATE - 5, false, 1, 3), (3, CURRENT_DATE - 7, true, 1, 3);
"""
base = sys.argv[1]
env = dict(os.environ)
env.setdefault("PGHOST", "127.0.0.1")
env.setdefault("PGUSER", "kairos")
env.setdefault("PGPASSWORD", "kairos")
subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", base],
               input=sql, text=True, check=True, env=env, stdout=subprocess.DEVNULL)
print("Jeu de données Daily log chargé dans", base)

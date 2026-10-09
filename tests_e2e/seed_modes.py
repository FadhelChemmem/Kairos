"""Jeu de données du scénario Playwright du lot 12 (« Voir comme », « Agir
comme », date simulée, liens vers les tâches, Deadlines de l'Admin).

Usage : python tests_e2e/seed_modes.py <base>   (base créée depuis schema.sql)
Variables PGHOST / PGUSER / PGPASSWORD habituelles (défaut 127.0.0.1 / kairos).
Comptes (mot de passe Kairos2026!) : admin@x.tn (Fadhel Admin), autre@x.tn
(second Admin, jamais proposé), ali@x.tn (chef du projet 1), rim@x.tn
(intervenante du projet 1 et des tâches 1 et 2), rh@x.tn, client@x.tn,
ancien@x.tn (désactivé, jamais proposé), omar@x.tn (chef URBS, projet 2).
"""
import os
import subprocess
import sys

from werkzeug.security import generate_password_hash

H = generate_password_hash("Kairos2026!")
sql = f"""
INSERT INTO utilisateur (id, email, mot_de_passe_hash, prenom, nom, role, equipe_code, poste, created_at, verifie, actif, fuseau) VALUES
 (1, 'admin@x.tn', '{H}', 'Fadhel', 'Admin', 'admin', 'MIDGARD', NULL, now() - interval '200 days', true, true, 'Africa/Tunis'),
 (2, 'ali@x.tn', '{H}', 'Ali', 'Chef', 'chef_de_projet', 'MIDGARD', 'Ingénieur', now() - interval '200 days', true, true, 'Africa/Tunis'),
 (3, 'rim@x.tn', '{H}', 'Rim', 'Inter', 'intervenant', 'MIDGARD', 'Technicienne', now() - interval '200 days', true, true, 'Africa/Tunis'),
 (4, 'rh@x.tn', '{H}', 'Rania', 'RH', 'rh', NULL, NULL, now() - interval '200 days', true, true, 'Africa/Tunis'),
 (5, 'client@x.tn', '{H}', 'Cli', 'Ent', 'client', 'MIDGARD', NULL, now() - interval '200 days', true, true, 'Africa/Tunis'),
 (6, 'ancien@x.tn', '{H}', 'Ancien', 'Compte', 'intervenant', 'MIDGARD', NULL, now() - interval '200 days', true, false, 'Africa/Tunis'),
 (7, 'omar@x.tn', '{H}', 'Omar', 'Urbs', 'chef_de_projet', 'URBS', NULL, now() - interval '200 days', true, true, 'Africa/Tunis'),
 (8, 'autre@x.tn', '{H}', 'Autre', 'Admin', 'admin', 'MIDGARD', NULL, now() - interval '200 days', true, true, 'Africa/Tunis');
SELECT setval(pg_get_serial_sequence('utilisateur','id'), 8);
INSERT INTO projet (id, code, nom, phase, chef_projet_id, equipe_code, etat) VALUES
 (1, '21114X', 'Siemens', 'EXE', 2, 'MIDGARD', 'en_cours'),
 (2, '21115X', 'Urbs', 'EXE', 7, 'URBS', 'en_cours');
SELECT setval(pg_get_serial_sequence('projet','id'), 2);
INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (1, 3);
INSERT INTO tache (id, projet_id, titre, created_by, etat, date_echeance, type_deadline) VALUES
 (1, 1, 'Note de calcul fondations', 2, 'en_cours', CURRENT_DATE + 7, 'rendu_client'),
 (2, 1, 'Plans de ferraillage', 2, 'en_cours', CURRENT_DATE + 14, 'interne'),
 (3, 1, 'Descente de charges', 2, 'en_cours', NULL, 'rendu_client'),
 (4, 2, 'Ferraillage Urbs', 7, 'en_cours', CURRENT_DATE + 9, 'rendu_client'),
 (5, 2, 'Métré Urbs', 7, 'en_cours', NULL, 'rendu_client');
SELECT setval(pg_get_serial_sequence('tache','id'), 5);
INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (1, 3), (2, 3);
INSERT INTO notification (utilisateur_id, categorie, message) VALUES
 (3, 'projet', 'Vous avez été ajoutée à la tâche « Note de calcul fondations ».');
"""
base = sys.argv[1]
env = dict(os.environ)
env.setdefault("PGHOST", "127.0.0.1")
env.setdefault("PGUSER", "kairos")
env.setdefault("PGPASSWORD", "kairos")
subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", base],
               input=sql, text=True, check=True, env=env, stdout=subprocess.DEVNULL)
print("Jeu de données du lot 12 chargé dans", base)

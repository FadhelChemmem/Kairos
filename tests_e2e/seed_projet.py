"""Jeu de données du scénario Playwright de la fiche projet (lot 11).

Usage : python tests_e2e/seed_projet.py <base>   (base créée depuis schema.sql)
Variables PGHOST / PGUSER / PGPASSWORD habituelles (défaut 127.0.0.1 / kairos).
Comptes (mot de passe Kairos2026!) : ali@x.tn (chef du projet 1),
rim@x.tn (intervenante du projet), helene@x.tn (« Hélène », à ajouter),
sami@x.tn (chef de projet, deviendra co-chef), rh@x.tn, client@x.tn,
ancien@x.tn (désactivé). Projet 1 : 12 tâches dont 5 closes
(terminée, vérifiée, arrêtée, abandonnée). Lot 11 b : projet 2 de
l'équipe URBS (invisible pour Rim), avec la tâche 13.
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
 (4, 'helene@x.tn', '{H}', 'Hélène', 'Bénard', 'intervenant', 'MIDGARD', 'Dessinatrice', now() - interval '200 days', true, true, 'Africa/Tunis'),
 (5, 'sami@x.tn', '{H}', 'Sami', 'Chérif', 'chef_de_projet', 'MIDGARD', NULL, now() - interval '200 days', true, true, 'Africa/Tunis'),
 (6, 'rh@x.tn', '{H}', 'Rania', 'RH', 'rh', NULL, NULL, now() - interval '200 days', true, true, 'Africa/Tunis'),
 (7, 'client@x.tn', '{H}', 'Cli', 'Ent', 'client', 'MIDGARD', NULL, now() - interval '200 days', true, true, 'Africa/Tunis'),
 (8, 'ancien@x.tn', '{H}', 'Ancien', 'Compte', 'intervenant', 'MIDGARD', NULL, now() - interval '200 days', true, false, 'Africa/Tunis'),
 (9, 'omar@x.tn', '{H}', 'Omar', 'Mahjoub', 'intervenant', 'MIDGARD', 'Technicien', now() - interval '200 days', true, true, 'Africa/Tunis');
SELECT setval(pg_get_serial_sequence('utilisateur','id'), 9);
INSERT INTO projet (id, code, nom, phase, chef_projet_id, equipe_code, etat) VALUES
 (1, '21114X', 'Siemens', 'EXE', 2, 'MIDGARD', 'en_cours'),
 (2, '21115X', 'Urbs', 'EXE', 1, 'URBS', 'en_cours');
SELECT setval(pg_get_serial_sequence('projet','id'), 2);
INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (1, 3);
INSERT INTO tache (id, projet_id, titre, created_by, etat, date_echeance, type_deadline) VALUES
 (1, 1, 'Note de calcul fondations', 2, 'en_cours', CURRENT_DATE + 7, 'rendu_client'),
 (2, 1, 'Plans de ferraillage', 2, 'en_cours', CURRENT_DATE + 14, 'interne'),
 (3, 1, 'Descente de charges', 2, 'bloque', CURRENT_DATE + 3, 'rendu_client'),
 (4, 1, 'Coffrage dalle R+1', 2, 'en_cours', CURRENT_DATE + 20, 'rendu_client'),
 (5, 1, 'Métré béton', 2, 'en_cours', CURRENT_DATE + 30, 'rendu_client'),
 (6, 1, 'Reprise des réserves', 2, 'en_cours', CURRENT_DATE + 40, 'rendu_client'),
 (7, 1, 'Synthèse des plans', 2, 'en_cours', CURRENT_DATE + 50, 'rendu_client'),
 (8, 1, 'Dossier DOE', 2, 'termine', CURRENT_DATE - 30, 'rendu_client'),
 (9, 1, 'Contrôle externe', 2, 'verifie', CURRENT_DATE - 40, 'rendu_client'),
 (10, 1, 'Variante charpente', 2, 'arret', CURRENT_DATE - 50, 'interne'),
 (11, 1, 'Étude pieux', 2, 'abandonne', CURRENT_DATE - 60, 'rendu_client'),
 (12, 1, 'Note hypothèses', 2, 'termine', CURRENT_DATE - 70, 'rendu_client'),
 (13, 2, 'Ferraillage Urbs', 1, 'en_cours', CURRENT_DATE + 9, 'rendu_client');
SELECT setval(pg_get_serial_sequence('tache','id'), 13);
INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (1, 3), (8, 3);
"""
base = sys.argv[1]
env = dict(os.environ)
env.setdefault("PGHOST", "127.0.0.1")
env.setdefault("PGUSER", "kairos")
env.setdefault("PGPASSWORD", "kairos")
subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", base],
               input=sql, text=True, check=True, env=env, stdout=subprocess.DEVNULL)
print("Jeu de données fiche projet chargé dans", base)

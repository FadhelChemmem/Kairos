"""Jeu de données du scénario Playwright « tableaux » (lot 14, A2) : celui
du lot 12 (seed_modes.py : comptes, mot de passe Kairos2026!) + de quoi
remplir la Vue d'ensemble de l'Admin et la carte « À traiter » d'Ali (chef
du projet 1) :
- tâche 6 en retard de 3 jours (Rim), tâche 7 bloquée (projet 1 Bloqué) ;
- projet 3 d'Ali sans tâche ouverte (une tâche terminée) ;
- Rim a rempli son Daily log du dernier jour ouvré, Ali et Omar non.

Attendu (Admin) : 1 en retard, 1 bloquée, 1 projet sans tâche ouverte, 2
Daily log manquants. Ali : 1 en retard, 1 bloquée, 2 sans intervenant, 1
sans échéance, 1 projet sans tâche ouverte, 1 Daily log manquant (le sien :
même périmètre que la page « Daily log de l'équipe », recette du lot 14 n° 9).

Usage : python tests_e2e/seed_tableaux.py <base>   (base créée depuis schema.sql)
"""
import os
import pathlib
import subprocess
import sys

base = sys.argv[1]
ici = pathlib.Path(__file__).resolve().parent
subprocess.run([sys.executable, str(ici / "seed_modes.py"), base], check=True)
sql = """
INSERT INTO tache (id, projet_id, titre, created_by, etat, date_echeance, type_deadline) VALUES
 (6, 1, 'Plans de coffrage en retard', 2, 'en_cours', CURRENT_DATE - 3, 'rendu_client'),
 (7, 1, 'Note de calcul bloquée', 2, 'bloque', CURRENT_DATE + 20, 'rendu_client');
INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (6, 3);
UPDATE projet SET etat = 'bloque' WHERE id = 1;
INSERT INTO projet (id, code, nom, phase, chef_projet_id, equipe_code, etat) VALUES
 (3, '21116X', 'Passerelle', 'APS', 2, 'MIDGARD', 'en_cours');
INSERT INTO tache (id, projet_id, titre, created_by, etat, date_echeance, type_deadline) VALUES
 (8, 3, 'Relevé topographique', 2, 'termine', CURRENT_DATE - 10, 'interne');
SELECT setval(pg_get_serial_sequence('projet','id'), 3);
SELECT setval(pg_get_serial_sequence('tache','id'), 8);
INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures, updated_by)
SELECT 3, CURRENT_DATE - CASE extract(isodow FROM CURRENT_DATE)::int WHEN 1 THEN 3 WHEN 7 THEN 2 ELSE 1 END, 1, NULL, 6, 3;
"""
env = dict(os.environ)
env.setdefault("PGHOST", "127.0.0.1")
env.setdefault("PGUSER", "kairos")
env.setdefault("PGPASSWORD", "kairos")
subprocess.run(["psql", "-X", "-q", "-o", "/dev/null", "-v", "ON_ERROR_STOP=1", "-d", base], input=sql, text=True, env=env, check=True)
print(f"Jeu de données du scénario tableaux chargé dans {base}")

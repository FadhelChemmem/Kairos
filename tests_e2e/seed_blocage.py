"""Jeu de données du scénario Playwright « blocage » (lot 14, revue produit
P0-1 et P0-2) : celui du lot 12 (seed_modes.py : comptes, mot de passe
Kairos2026!) — Rim intervenante des tâches 1 et 2 du projet 1 d'Ali — plus
un co-chef (Sami) sur le projet 1, prévenu lui aussi, et la tâche 1 en
retard de 2 jours (elle sort du Gantt quand elle est bloquée).

Usage : python tests_e2e/seed_blocage.py <base>   (base créée depuis schema.sql)
"""
import os
import pathlib
import subprocess
import sys

from werkzeug.security import generate_password_hash

base = sys.argv[1]
ici = pathlib.Path(__file__).resolve().parent
subprocess.run([sys.executable, str(ici / "seed_modes.py"), base], check=True)
H = generate_password_hash("Kairos2026!")
sql = f"""
INSERT INTO utilisateur (id, email, mot_de_passe_hash, prenom, nom, role, equipe_code, poste, verifie, actif) VALUES
 (150, 'sami@x.tn', '{H}', 'Sami', 'Cochef', 'chef_de_projet', 'MIDGARD', 'Ingénieur', true, true);
SELECT setval(pg_get_serial_sequence('utilisateur','id'), 150);
INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (1, 150);
INSERT INTO projet_lot (projet_id, lot_code) VALUES (1, 'GO') ON CONFLICT DO NOTHING;
UPDATE tache SET date_echeance = CURRENT_DATE - 2 WHERE id = 1;
"""
env = dict(os.environ)
env.setdefault("PGHOST", "127.0.0.1")
env.setdefault("PGUSER", "kairos")
env.setdefault("PGPASSWORD", "kairos")
subprocess.run(["psql", "-X", "-q", "-o", "/dev/null", "-v", "ON_ERROR_STOP=1", "-d", base], input=sql, text=True, env=env, check=True)
print(f"Jeu de données du scénario blocage chargé dans {base}")

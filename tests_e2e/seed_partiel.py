"""Jeu de données du scénario Playwright du lot 13 (socle des mises à jour
partielles, pilotes de la page Utilisateurs) : celui du lot 12
(seed_modes.py, mêmes comptes et mot de passe) + 30 comptes pour que la
liste défile, et un second compte RH désactivé (refus « un seul RH actif »).

Usage : python tests_e2e/seed_partiel.py <base>   (base créée depuis schema.sql)
"""
import os
import pathlib
import subprocess
import sys

base = sys.argv[1]
ici = pathlib.Path(__file__).resolve().parent
subprocess.run([sys.executable, str(ici / "seed_modes.py"), base], check=True)
lignes = ",\n".join(
    f" ({100 + i}, 'compte{i:02d}@x.tn', 'x', 'Compte{i:02d}', 'Liste', 'intervenant', 'MIDGARD', 'Technicien', true, true)"
    for i in range(30))
sql = f"""
INSERT INTO utilisateur (id, email, mot_de_passe_hash, prenom, nom, role, equipe_code, poste, verifie, actif) VALUES
{lignes},
 (140, 'rh2@x.tn', 'x', 'Second', 'RH', 'rh', NULL, NULL, true, false);
SELECT setval(pg_get_serial_sequence('utilisateur','id'), 140);
"""
env = dict(os.environ)
env.setdefault("PGHOST", "127.0.0.1")
env.setdefault("PGUSER", "kairos")
env.setdefault("PGPASSWORD", "kairos")
subprocess.run(["psql", "-X", "-q", "-o", "/dev/null", "-v", "ON_ERROR_STOP=1", "-d", base], input=sql, text=True, env=env, check=True)
print(f"Jeu de données du socle partiel chargé dans {base}")
# Lot 13, phase 2 C : fiche projet, panneau de tâche, fil, « Tous les projets ».
subprocess.run([sys.executable, str(ici / "seed_partiel_fiche.py"), base], check=True)

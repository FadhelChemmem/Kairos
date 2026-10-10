"""Jeu de données du scénario Playwright « stabilité » (lot 13, H1) : celui
des pages (seed_pages.py : comptes du lot 12, mot de passe Kairos2026!,
fiche projet, notifications, journal) + un Daily log pour l'Admin (lignes
aujourd'hui, la veille et l'avant-veille sur le projet 1, dont il devient
intervenant) : « Copier », « Marquer absent », lignes à désactiver.

Usage : python tests_e2e/seed_stabilite.py <base>   (base créée depuis schema.sql)
"""
import os
import pathlib
import subprocess
import sys

base = sys.argv[1]
ici = pathlib.Path(__file__).resolve().parent
subprocess.run([sys.executable, str(ici / "seed_pages.py"), base], check=True)
sql = """
INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (1, 1) ON CONFLICT DO NOTHING;
INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures, updated_by)
SELECT 1, d::date, 1, NULL, 4, 1 FROM generate_series(CURRENT_DATE - 3, CURRENT_DATE, interval '1 day') AS d
WHERE extract(isodow FROM d) < 6 OR d::date = CURRENT_DATE;
"""
env = dict(os.environ)
env.setdefault("PGHOST", "127.0.0.1")
env.setdefault("PGUSER", "kairos")
env.setdefault("PGPASSWORD", "kairos")
subprocess.run(["psql", "-X", "-q", "-o", "/dev/null", "-v", "ON_ERROR_STOP=1", "-d", base], input=sql, text=True, env=env, check=True)
print(f"Jeu de données du scénario stabilité chargé dans {base}")

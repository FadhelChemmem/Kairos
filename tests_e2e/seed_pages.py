"""Jeu de données du scénario Playwright du lot 13, phase 2 (D) : pages
Deadlines, Notifications, Journal d'audit, Utilisateurs, Daily log et
bandeau des modes. Celui du socle partiel (seed_partiel.py : comptes du
lot 12, mot de passe Kairos2026!, 30 comptes en plus) + des notifications
non lues pour l'Admin, 160 entrées de journal (pour « Charger 100 de
plus ») et un Daily log sur les jours passés de Rim (profil, semaine
précédente).

Usage : python tests_e2e/seed_pages.py <base>   (base créée depuis schema.sql)
"""
import os
import pathlib
import subprocess
import sys

base = sys.argv[1]
ici = pathlib.Path(__file__).resolve().parent
subprocess.run([sys.executable, str(ici / "seed_partiel.py"), base], check=True)
sql = """
INSERT INTO notification (utilisateur_id, categorie, message, created_at) VALUES
 (1, 'projet', 'Ali Chef vous a mentionné dans un post.', now() - interval '5 minutes'),
 (1, 'projet', 'Vous avez été ajouté au projet 21114X_Siemens.', now() - interval '2 hours'),
 (1, 'rh_info', 'Information d’équipe : réunion lundi.', now() - interval '1 day'),
 (1, 'projet', 'Ancienne notification déjà lue.', now() - interval '3 days');
UPDATE notification SET lu = true WHERE message = 'Ancienne notification déjà lue.';
INSERT INTO audit_log (table_cible, ligne_id, action, utilisateur_id, donnees_avant, donnees_apres, created_at)
SELECT 'tache', 1, 'UPDATE', 2, jsonb_build_object('etat', 'en_cours', 'titre', 'Note de calcul fondations', 'n', g),
       jsonb_build_object('etat', 'bloque', 'titre', 'Note de calcul fondations', 'n', g),
       now() - (g || ' minutes')::interval
FROM generate_series(1, 160) AS g;
INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures, updated_by)
SELECT 3, d::date, 1, NULL, 4, 3 FROM generate_series(CURRENT_DATE - 13, CURRENT_DATE - 1, interval '1 day') AS d
WHERE extract(isodow FROM d) < 6;
"""
env = dict(os.environ)
env.setdefault("PGHOST", "127.0.0.1")
env.setdefault("PGUSER", "kairos")
env.setdefault("PGPASSWORD", "kairos")
subprocess.run(["psql", "-X", "-q", "-o", "/dev/null", "-v", "ON_ERROR_STOP=1", "-d", base], input=sql, text=True, env=env, check=True)
print(f"Jeu de données des pages (lot 13, phase 2) chargé dans {base}")

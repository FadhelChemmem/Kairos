"""Jeu de données du scénario Playwright « fil » (lot 14, revue produit
P1-3 : fil filtrable) — celui du lot 12 (seed_modes.py : comptes, mot de
passe Kairos2026!, projet 1 d'Ali avec Rim intervenante) + sur le projet 1 :
- 40 Informations de Rim, une par heure (fiche : « Afficher plus » au-delà
  de 30) ;
- 5 créations de tâche d'Ali dans la même heure (regroupement « Ali Chef a
  créé 3 tâches… ») et 2 changements d'état d'une tâche, il y a 3 h ;
- une clôture avec message (Échanges) et une sans (Activité).

Usage : python tests_e2e/seed_fil.py <base>   (base créée depuis schema.sql)
"""
import os
import pathlib
import subprocess
import sys

base = sys.argv[1]
ici = pathlib.Path(__file__).resolve().parent
subprocess.run([sys.executable, str(ici / "seed_modes.py"), base], check=True)
infos = ",\n".join(
    f" ({100 + i}, 1, NULL, 3, 'information', 'Information de Rim numéro {i:02d}', NULL, now() - interval '{i + 1} hours 30 minutes')"
    for i in range(40))
sql = f"""
INSERT INTO post (id, projet_id, tache_id, auteur_id, type_code, contenu, evenement, created_at) VALUES
{infos},
 (200, 1, 1, 2, 'information', 'Note de calcul fondations', 'creation_tache', now() - interval '5 minutes'),
 (201, 1, 2, 2, 'information', 'Plans de ferraillage', 'creation_tache', now() - interval '8 minutes'),
 (202, 1, 3, 2, 'information', 'Descente de charges', 'creation_tache', now() - interval '11 minutes'),
 (203, 1, 1, 2, 'information', 'En cours → Bloqué', 'etat_tache', now() - interval '3 hours'),
 (204, 1, 1, 2, 'information', 'Bloqué → En cours', 'etat_tache', now() - interval '3 hours 5 minutes'),
 (205, 1, 2, 3, 'envoi', 'Plans envoyés au client.', 'cloture_tache', now() - interval '20 minutes'),
 (206, 1, 3, 3, 'envoi', NULL, 'cloture_tache', now() - interval '25 minutes');
SELECT setval(pg_get_serial_sequence('post','id'), 300);
INSERT INTO post_commentaire (post_id, auteur_id, contenu, created_at) VALUES
 (100, 2, 'Bien reçu, merci.', now() - interval '1 hour');
"""
env = dict(os.environ)
env.setdefault("PGHOST", "127.0.0.1")
env.setdefault("PGUSER", "kairos")
env.setdefault("PGPASSWORD", "kairos")
subprocess.run(["psql", "-X", "-q", "-o", "/dev/null", "-v", "ON_ERROR_STOP=1", "-d", base], input=sql, text=True,
               env=env, check=True)
print(f"Jeu de données du fil (lot 14) chargé dans {base}")

"""Jeu de données du scénario partiel, phase 2 C du lot 13 (fiche projet,
panneau de tâche, fil, « Tous les projets ») — ajouté à celui de
seed_partiel.py (mêmes comptes, mot de passe Kairos2026!) :
- projet 1 (Ali chef, Rim intervenante) : 14 tâches de plus (dont une en
  retard, une close), lot GO, 6 posts avec commentaires ;
- 70 projets d'Ali (pagination de « Tous les projets », 50 par page) ;
- Sami (150) et Hélène (151), intervenants de l'équipe non rattachés.

Usage : python tests_e2e/seed_partiel_fiche.py <base>
"""
import os
import subprocess
import sys

from werkzeug.security import generate_password_hash

H = generate_password_hash("Kairos2026!")
taches = ",\n".join(
    f" ({20 + i}, 1, 'Tâche de liste {i:02d}', 2, '{'termine' if i == 13 else 'en_cours'}', "
    f"CURRENT_DATE + {i * 2 - 4}, '{'interne' if i % 3 == 0 else 'rendu_client'}')"
    for i in range(14))
projets = ",\n".join(
    f" ({300 + i}, '26{300 + i}X', 'Projet de liste {i:02d}', 'EXE', 2, 'MIDGARD', 'en_cours')" for i in range(70))
posts = ",\n".join(
    f" ({50 + i}, 1, {3 if i % 2 else 2}, 'information', 'Post de la fiche numéro {i}', now() - interval '{i + 1} hours')"
    for i in range(6))
sql = f"""
INSERT INTO utilisateur (id, email, mot_de_passe_hash, prenom, nom, role, equipe_code, poste, verifie, actif) VALUES
 (150, 'sami@x.tn', '{H}', 'Sami', 'Nouveau', 'intervenant', 'MIDGARD', 'Technicien', true, true),
 (151, 'helene@x.tn', '{H}', 'Hélène', 'Bénard', 'intervenant', 'MIDGARD', 'Dessinatrice', true, true);
SELECT setval(pg_get_serial_sequence('utilisateur','id'), 151);
INSERT INTO projet_lot (projet_id, lot_code) VALUES (1, 'GO') ON CONFLICT DO NOTHING;
INSERT INTO tache (id, projet_id, titre, created_by, etat, date_echeance, type_deadline) VALUES
{taches};
UPDATE tache SET date_fin = CURRENT_DATE WHERE id = 33;
INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (20, 3), (21, 3), (22, 3);
SELECT setval(pg_get_serial_sequence('tache','id'), 100);
INSERT INTO projet (id, code, nom, phase, chef_projet_id, equipe_code, etat) VALUES
{projets};
SELECT setval(pg_get_serial_sequence('projet','id'), 400);
INSERT INTO post (id, projet_id, auteur_id, type_code, contenu, created_at) VALUES
{posts};
SELECT setval(pg_get_serial_sequence('post','id'), 100);
INSERT INTO post_commentaire (post_id, auteur_id, contenu, created_at) VALUES
 (50, 3, 'Premier commentaire', now() - interval '30 minutes'),
 (50, 2, 'Deuxième commentaire', now() - interval '20 minutes');
INSERT INTO post_reaction (post_id, utilisateur_id, reaction_code) VALUES (51, 3, 'pouce');
"""
env = dict(os.environ)
env.setdefault("PGHOST", "127.0.0.1")
env.setdefault("PGUSER", "kairos")
env.setdefault("PGPASSWORD", "kairos")
subprocess.run(["psql", "-X", "-q", "-o", "/dev/null", "-v", "ON_ERROR_STOP=1", "-d", sys.argv[1]], input=sql, text=True,
               env=env, check=True)
print(f"Jeu de données de la fiche projet (phase 2 C) chargé dans {sys.argv[1]}")

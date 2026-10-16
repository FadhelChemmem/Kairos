"""Jeu de données du scénario Playwright « lot15 » (accueil sobre, Daily log,
posts modifiables, page d'une personne) : celui du lot 12 (seed_modes.py :
comptes, mot de passe Kairos2026!) + un bureau fictif plus réaliste :
- 4 intervenants de plus (Sami, Inès, Karim, Leïla) et une cheffe (Nadia) ;
- 12 projets (Ali chef de 7, co-chef d'un projet d'Omar), tâches en retard,
  bloquées avec motif, à venir, terminées ;
- un fil varié : informations, requêtes (dont une qui cite une tâche),
  créations et clôtures de tâches, blocage, commentaires, une pièce jointe ;
- Daily log : Rim à jour sauf hier, Ali sans saisie depuis 6 jours ouvrés.

Toutes les données sont inventées. Usage : python tests_e2e/seed_lot15.py <base>
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

PROJETS = [
    # id, code, nom, phase, chef, équipe
    (3, "96085X", "Dépôt logistique Nord", "EXE", 2, "MIDGARD"),
    (4, "94058X", "Résidence Les Pins", "EXE", 2, "MIDGARD"),
    (5, "95012X", "Villas du Parc", "EXE", 2, "MIDGARD"),
    (6, "93034X", "Les Terrasses", "EXE", 2, "MIDGARD"),
    (7, "96084P", "Lycée Est", "APD", 2, "MIDGARD"),
    (8, "96087X", "Immeuble Horizon", "DCE", 2, "MIDGARD"),
    (9, "92075X", "Réhabilitation Centre", "EXE", 13, "MIDGARD"),
    (10, "96090P", "Hangar Sud", "APS", 7, "URBS"),
    (11, "96091D", "Passerelle Rivière", "DCE", 13, "MIDGARD"),
    (12, "96073X", "Résidence Les Oliviers", "EXE", 13, "MIDGARD"),
    (13, "95020X", "Collège Ouest", "DOE", 2, "MIDGARD"),
    (14, "96100A", "Clinique des Lilas", "APS", 13, "MIDGARD"),
]
# id, projet, titre, état, échéance (jours depuis aujourd'hui), intervenants, motif de blocage
TACHES = [
    (20, 3, "Coffrage (pour validation)", "en_cours", -9, [3], None),
    (21, 3, "Coffrage et ferraillage MS", "en_cours", -7, [9], None),
    (22, 8, "Plans de ferraillage", "en_cours", -6, [3, 10], None),
    (23, 9, "Reprise fondation", "en_cours", -5, [11], None),
    (24, 12, "Note de calcul plancher", "en_cours", -1, [12], None),
    (25, 9, "Relevé des fissures", "en_cours", 2, [3], None),
    (26, 4, "Ferraillage MS", "bloque", 6, [9], "En attente des plans architecte indice C"),
    (27, 5, "Descente de charges villa 3", "bloque", 12, [10], "Sondages de sol non reçus"),
    (28, 4, "Coffrage BAT B/C", "bloque", 20, [3], "Validation du bureau de contrôle"),
    (29, 7, "Pré-dimensionnement structure", "en_cours", 9, [11], None),
    (30, 8, "Carnet de détails DCE", "en_cours", 13, [], None),
    (31, 6, "Plans de récolement", "termine", -15, [12], None),
    (32, 11, "Pré-dimensionnement tablier", "en_cours", 13, [3], None),
    (33, 10, "Charpente métallique APS", "en_cours", 5, [9], None),
    (34, 13, "DOE lot GO", "en_cours", 30, [], None),
    (35, 3, "Plan de calepinage dallage", "en_cours", 4, [3], None),
]


def sql_liste(valeurs):
    return ",\n".join(valeurs)


utilisateurs = sql_liste([
    f" ({i}, '{e}', '{H}', '{p}', '{n}', '{r}', 'MIDGARD', '{poste}', now() - interval '150 days', true, true, 'Africa/Tunis')"
    for i, e, p, n, r, poste in [
        (9, "sami@x.tn", "Sami", "Ben Salah", "intervenant", "Projeteur"),
        (10, "ines@x.tn", "Inès", "Trabelsi", "intervenant", "Ingénieure structure"),
        (11, "karim@x.tn", "Karim", "Mansour", "intervenant", "Technicien supérieur"),
        (12, "leila@x.tn", "Leïla", "Haddad", "intervenant", "Dessinatrice"),
        (13, "nadia@x.tn", "Nadia", "Gharbi", "chef_de_projet", "Cheffe de projet"),
    ]])
projets = sql_liste([
    f" ({i}, '{c}', '{n}', '{ph}', {ch}, '{eq}', 'en_cours', CURRENT_DATE - 120)" for i, c, n, ph, ch, eq in PROJETS])
lots = sql_liste([f" ({i}, '{'CM' if i == 10 else 'GO'}')" for i, *_ in PROJETS])
intervenants_projet = {(p, u) for _, p, _, _, _, us, _ in TACHES for u in us}
intervenants_projet |= {(3, 3), (4, 3), (9, 3), (11, 3), (5, 9)}
ip = sql_liste([f" ({p}, {u})" for p, u in sorted(intervenants_projet)])
taches = sql_liste([
    f" ({i}, {p}, '{t}', 2, '{e}', CURRENT_DATE + ({d}), 'rendu_client', "
    + (f"'{m}', now() - interval '{3 + i % 5} days', 2" if m else "NULL, NULL, NULL") + ")"
    for i, p, t, e, d, _, m in TACHES])
ti = sql_liste([f" ({i}, {u})" for i, _, _, _, _, us, _ in TACHES for u in us])
sql = f"""
INSERT INTO utilisateur (id, email, mot_de_passe_hash, prenom, nom, role, equipe_code, poste, created_at, verifie, actif, fuseau) VALUES
{utilisateurs};
SELECT setval(pg_get_serial_sequence('utilisateur','id'), 13);
UPDATE utilisateur SET poste = 'Technicienne supérieure' WHERE id = 3;
INSERT INTO projet (id, code, nom, phase, chef_projet_id, equipe_code, etat, date_debut) VALUES
{projets};
SELECT setval(pg_get_serial_sequence('projet','id'), 14);
INSERT INTO projet_lot (projet_id, lot_code) VALUES {lots} ON CONFLICT DO NOTHING;
INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (10, 2);
INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES
{ip} ON CONFLICT DO NOTHING;
INSERT INTO tache (id, projet_id, titre, created_by, etat, date_echeance, type_deadline, bloque_motif, bloque_le, bloque_par) VALUES
{taches};
SELECT setval(pg_get_serial_sequence('tache','id'), 40);
INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES
{ti};
UPDATE projet SET etat = 'bloque' WHERE id IN (SELECT projet_id FROM tache WHERE etat = 'bloque');
INSERT INTO post (id, projet_id, tache_id, auteur_id, type_code, contenu, evenement, created_at) VALUES
 (400, 3, 20, 3, 'envoi', 'Mise à jour selon le visa du bureau de contrôle.', 'cloture_tache', now() - interval '29 minutes'),
 (401, 4, 26, 9, 'information', 'En attente des plans architecte indice C', 'blocage_tache', now() - interval '1 hour'),
 (402, 3, NULL, 2, 'requete', 'Plans de réservation du lot CVC' || chr(10) || chr(10) || 'Merci de m’envoyer les réservations avant vendredi pour caler le coffrage.', NULL, now() - interval '2 hours'),
 (403, 5, NULL, 1, 'information', 'Réunion de chantier déplacée à jeudi 9 h, sur site.', NULL, now() - interval '3 hours'),
 (404, 8, 30, 2, 'information', 'Carnet de détails DCE', 'creation_tache', now() - interval '5 hours'),
 (405, 6, 31, 12, 'envoi', 'Plans transmis au maître d’ouvrage.', 'cloture_tache', now() - interval '1 day'),
 (406, NULL, NULL, 4, 'information', 'Rappel : les congés de fin d’année se posent avant le 15 novembre.', NULL, now() - interval '1 day 2 hours'),
 (407, 9, 23, 13, 'requete', 'Photos de la reprise' || chr(10) || chr(10) || 'Pouvez-vous joindre les photos prises lors de la visite ?', NULL, now() - interval '2 days');
INSERT INTO post_equipe (post_id, equipe_code) VALUES (406, 'MIDGARD');
SELECT setval(pg_get_serial_sequence('post','id'), 500);
INSERT INTO post_commentaire (post_id, auteur_id, contenu, created_at) VALUES
 (402, 3, 'Je regarde avec le BET fluides et je reviens vers toi.', now() - interval '90 minutes'),
 (402, 2, 'Merci Rim.', now() - interval '80 minutes'),
 (403, 2, 'Bien noté.', now() - interval '150 minutes');
INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures, updated_by)
SELECT 3, d::date, 3, 20, 8, 3 FROM generate_series(CURRENT_DATE - 14, CURRENT_DATE - 2, interval '1 day') d
WHERE extract(isodow FROM d) < 6;
INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures, updated_by)
SELECT 2, d::date, 4, NULL, 8, 2 FROM generate_series(CURRENT_DATE - 30, CURRENT_DATE - 9, interval '1 day') d
WHERE extract(isodow FROM d) < 6;
"""
env = dict(os.environ)
env.setdefault("PGHOST", "127.0.0.1")
env.setdefault("PGUSER", "kairos")
env.setdefault("PGPASSWORD", "kairos")
subprocess.run(["psql", "-X", "-q", "-o", "/dev/null", "-v", "ON_ERROR_STOP=1", "-d", base], input=sql, text=True,
               env=env, check=True)
print(f"Jeu de données du lot 15 chargé dans {base}")

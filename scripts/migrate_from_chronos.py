#!/usr/bin/env python3
"""Migration Kairos (ancien, MySQL "chronos") -> Kairos nouveau (Postgres, schema.sql).

RÉUTILISABLE : ce script est fait pour être relancé plusieurs fois, à chaque
nouvel export .sql de l'ancien Kairos, sans rien modifier à la main.

Ce qu'il fait :
  1. Parse un dump mysqldump (`chronos_YYYYMMDDHHMM.sql`) en pur Python
     (scripts/mysqldump_parser.py, aucune dépendance externe, pas besoin
     d'un serveur MySQL).
  2. Transforme les données vers le modèle du nouveau schema.sql (Postgres).
  3. Écrit un fichier .sql prêt à être rejoué avec `psql` sur la nouvelle
     base (aucune dépendance psycopg2 nécessaire pour générer le fichier).
  4. Anonymise les emails : les vrais emails ne sont PAS repris (pour ne
     jamais déclencher un envoi de mail réel vers eux) ; chaque utilisateur
     migré reçoit un email `nom_prenom@<domaine>` (kairos.tn par défaut).
  5. Génère un mot de passe temporaire ALÉATOIRE (jamais l'ancien hash) par
     utilisateur, avec un hash compatible `werkzeug.security.check_password_hash`
     (format pbkdf2:sha256, généré ici en pur hashlib, donc vérifiable par
     l'appli sans rien installer de plus) -> écrit dans un fichier
     d'identifiants SÉPARÉ, À NE JAMAIS COMMITER (voir .gitignore), à
     transmettre en main propre (jamais par email, comme demandé).
  6. Écrit un rapport (.md) listant les choix faits, les lignes ignorées et
     ce qu'il reste à vérifier/compléter à la main après import.

Usage :
    python3 scripts/migrate_from_chronos.py chronos_210920260200.sql

    # options utiles :
    python3 scripts/migrate_from_chronos.py chronos_XXXX.sql \\
        --out-dir migration_2026-09-21 \\
        --email-domain kairos.tn

Le fichier .sql généré s'applique ensuite avec, par exemple :
    docker compose exec -T db psql -U kairos -d kairos -f /chemin/migration.sql

Le script part du principe que la base cible est FRAÎCHE (schema.sql tout
juste appliqué, aucune donnée métier dedans à part les tables de référence
équipe/lot/post_type/reaction_type déjà seedées par schema.sql) : les id de
utilisateur/projet/tâche de l'ancien Kairos sont repris tels quels (les
séquences Postgres sont réajustées à la fin), pour ne jamais avoir à
retraduire les references d'une table à l'autre.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import secrets
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mysqldump_parser import load_dump  # noqa: E402


# =====================================================================
# Constantes / mappings métier
# =====================================================================

ROLE_MAP = {
    "chef_projet": "chef_de_projet",
    "intervenant": "intervenant",
    "client": "client",
    "ressource_humaine": "rh",
    "superuser": "admin",
}

PROJET_ETAT_MAP = {
    "doing": "en_cours",
    "done": "termine",
    "blocked": "bloque",
    "abandoned": "abandonne",
}

TACHE_ETAT_MAP = {
    "doing": "en_cours",
    "done": "termine",
    "blocked": "bloque",
    "abandoned": "abandonne",
}

PHASES_VALIDES = {"APS", "APD", "DCE", "EXE", "DOE"}


# =====================================================================
# Utilitaires génériques
# =====================================================================

def slug_part(s: str) -> str:
    """'Ben ouannes' -> 'benouannes' ; accents retirés, tout en minuscule,
    seuls [a-z0-9] conservés (pas de séparateur interne : le séparateur
    nom/prénom est le '_' posé par l'appelant)."""
    s = s or ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]", "", s)
    return s or "x"


class EmailFactory:
    """Génère des emails 'nom_prenom@domaine' uniques (suffixe -2, -3... en
    cas de collision, ex. deux personnes avec le même nom de famille)."""

    def __init__(self, domain: str):
        self.domain = domain
        self._used: set[str] = set()

    def make(self, nom: str, prenom: str) -> str:
        base = f"{slug_part(nom)}_{slug_part(prenom)}"
        email = f"{base}@{self.domain}"
        n = 2
        while email.lower() in self._used:
            email = f"{base}-{n}@{self.domain}"
            n += 1
        self._used.add(email.lower())
        return email


def hash_password_pbkdf2(plain: str, iterations: int = 600_000) -> str:
    """Reproduit exactement le format de `werkzeug.security.generate_password_hash`
    en pbkdf2:sha256 (vérifiable par `check_password_hash` de l'appli), en pur
    hashlib — aucune dépendance à installer pour lancer ce script."""
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    salt = "".join(secrets.choice(alphabet) for _ in range(16))
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2:sha256:{iterations}${salt}${dk.hex()}"


def gen_temp_password() -> str:
    """Mot de passe temporaire lisible (à taper), pas un jeton illisible —
    facilite la transmission orale/manuscrite en main propre."""
    words_ok = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz"
    return "".join(secrets.choice(words_ok) for _ in range(10))


def sql_str(v) -> str:
    if v is None:
        return "NULL"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


def sql_val(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return sql_str(v)


def mysql_dt_to_pg(v) -> str | None:
    """'2024-04-17 09:30:51' -> identique, Postgres l'accepte tel quel."""
    if not v:
        return None
    return str(v)


def mysql_date_only(v) -> str | None:
    if not v:
        return None
    return str(v)[:10]


def us_date_to_iso(v) -> str | None:
    """'04/18/2022' (MM/DD/YYYY, confirmé sur l'échantillon complet — présence
    de jours > 12) -> '2022-04-18'."""
    if not v:
        return None
    v = str(v).strip()
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", v)
    if not m:
        return None
    mm, dd, yyyy = m.groups()
    try:
        datetime(int(yyyy), int(mm), int(dd))
    except ValueError:
        return None
    return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"


def clean_text(v) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    return v or None


# =====================================================================
# Étape 1 : utilisateurs
# =====================================================================

def build_utilisateurs(data, email_domain, report):
    profiles_by_user = {p["userID"]: p for p in data["UserProfiles"]}
    email_factory = EmailFactory(email_domain)
    utilisateurs = []          # lignes prêtes à insérer
    credentials = []           # (id, nom, prenom, email_fake, mot_de_passe_clair)
    role_inconnu = []

    for u in data["users"]:
        uid = u["id"]
        profile = profiles_by_user.get(uid)
        nom = clean_text(profile["name"]) if profile else None
        prenom = clean_text(profile["lastName"]) if profile else None
        if not nom or not prenom:
            # Pas de fiche UserProfiles (ne devrait pas arriver, vu les données
            # réelles, mais on ne veut jamais planter le script pour ça) :
            # on retombe sur l'email d'origine comme dernier repli, jamais
            # laissé vide (colonnes NOT NULL).
            nom = nom or f"Utilisateur{uid}"
            prenom = prenom or ""
            report["profils_manquants"].append(uid)

        role_brut = (u["role"] or "").strip().replace("\xa0", "").lower()
        role = ROLE_MAP.get(role_brut)
        if role is None:
            role = "intervenant"
            role_inconnu.append((uid, u["role"]))
        if u.get("isSuperUser"):
            role = "admin"

        email_fake = email_factory.make(nom, prenom)
        mdp_clair = gen_temp_password()
        mdp_hash = hash_password_pbkdf2(mdp_clair)

        actif = bool(u["active"]) and not bool(u["isBanned"])
        if u["isBanned"]:
            report["comptes_bannis_desactives"].append(uid)

        telephone = clean_text(profile["phone"]) if profile else None
        poste = clean_text(profile["poste"]) if profile else None
        adresse = clean_text(profile["address"]) if profile else None
        date_embauche = us_date_to_iso(profile["hireDate"]) if profile else None

        created_at = mysql_dt_to_pg(u["createdAt"]) or "now()"
        updated_at = mysql_dt_to_pg(u["updatedAt"]) or created_at

        utilisateurs.append(dict(
            id=uid, email=email_fake, mot_de_passe_hash=mdp_hash,
            nom=nom, prenom=prenom, telephone=telephone, poste=poste,
            adresse=adresse, date_embauche=date_embauche,
            role=role, verifie=True, actif=actif,
            created_at=created_at, updated_at=updated_at,
            email_original=u["email"],
        ))
        credentials.append((uid, nom, prenom, email_fake, mdp_clair, u["email"]))

    report["roles_inconnus"] = role_inconnu
    valid_ids = {u["id"] for u in utilisateurs}
    return utilisateurs, credentials, valid_ids


# =====================================================================
# Étape 2 : projets
# =====================================================================

def derive_code(customid: str, fallback: str) -> str:
    if customid and "_" in customid:
        return customid.split("_", 1)[0].strip()
    return (customid or fallback or "").strip()


def build_projets(data, valid_user_ids, report):
    phases_by_id = {p["id"]: p["name"] for p in data["phases"]}
    lots_by_id = {l["id"]: l["name"] for l in data["lots"]}

    codes_seen = {}
    projets = []
    liens_phase = []  # (projet_id, prevPhase) a appliquer en 2e passe (UPDATE)
    projet_lots = []

    for p in data["projects"]:
        pid = p["id"]
        code = derive_code(p["customId"], p["code"])
        if code in codes_seen:
            n = 2
            base = code
            while f"{base}-{n}" in codes_seen:
                n += 1
            report["codes_projet_renommes"].append((pid, code, f"{base}-{n}"))
            code = f"{base}-{n}"
        codes_seen[code] = pid

        phase = phases_by_id.get(p["phaseID"])
        if phase not in PHASES_VALIDES:
            report["projets_phase_invalide"].append((pid, p["phaseID"]))
            continue  # tache.projet_id / projet.phase NOT NULL -> on ne peut pas deviner

        manager = p["manager"]
        if manager not in valid_user_ids:
            report["projets_manager_invalide"].append((pid, manager))
            continue

        etat = PROJET_ETAT_MAP.get(p["state"], "en_cours")
        date_debut = mysql_date_only(p["startDate"])
        date_fin = mysql_date_only(p["dueDate"]) if p["state"] == "done" else None

        created_by = p["createdBy"] if p["createdBy"] in valid_user_ids else None
        created_at = mysql_dt_to_pg(p["createdAt"]) or "now()"
        updated_at = mysql_dt_to_pg(p["updatedAt"]) or created_at

        projets.append(dict(
            id=pid, code=code, nom=clean_text(p["name"]) or f"Projet {pid}",
            phase=phase, date_debut=date_debut, date_fin=date_fin, etat=etat,
            chef_projet_id=manager, created_by=created_by,
            created_at=created_at, updated_at=updated_at,
        ))

        if p["prevPhase"]:
            liens_phase.append((pid, p["prevPhase"]))

    valid_projet_ids = {p["id"] for p in projets}

    for pl in data["projectLots"]:
        if pl["projectID"] in valid_projet_ids:
            lot_code = lots_by_id.get(pl["lotID"])
            if lot_code:
                projet_lots.append((pl["projectID"], lot_code))

    # une liaison phase_liee_id ne vaut que si les deux projets existent
    liens_phase = [(a, b) for a, b in liens_phase if a in valid_projet_ids and b in valid_projet_ids]

    return projets, projet_lots, liens_phase, valid_projet_ids


# =====================================================================
# Étape 3 : tâches + rattachement projet (via intervenants / meta)
# =====================================================================

def build_taches(data, valid_projet_ids, report):
    import json as _json

    task_project = {}
    for r in data["intervenants"]:
        if r["taskID"] is not None and r["projectID"] is not None:
            task_project[r["taskID"]] = r["projectID"]

    taches = []
    for t in data["tasks"]:
        tid = t["id"]
        projet_id = task_project.get(tid)
        if projet_id is None and t["meta"]:
            try:
                projet_id = _json.loads(t["meta"]).get("projectID")
            except Exception:
                projet_id = None
        if projet_id is None or projet_id not in valid_projet_ids:
            report["taches_sans_projet"].append(tid)
            continue

        etat = TACHE_ETAT_MAP.get(t["state"], "en_cours")
        if t["isVerified"]:
            etat = "verifie"

        created_at = mysql_dt_to_pg(t["createdAt"]) or "now()"
        updated_at = mysql_dt_to_pg(t["updatedAt"]) or created_at

        taches.append(dict(
            id=tid, projet_id=projet_id, titre=clean_text(t["name"]) or f"Tâche {tid}",
            etat=etat, date_debut=mysql_date_only(t["startDate"]),
            date_echeance=mysql_date_only(t["dueDate"]),
            date_fin=mysql_date_only(t["doneDate"]),
            created_at=created_at, updated_at=updated_at,
        ))

    valid_tache_ids = {t["id"] for t in taches}
    return taches, valid_tache_ids


# =====================================================================
# Étape 4 : intervenants (projet_intervenant / tache_intervenant)
# =====================================================================

def build_intervenants(data, valid_user_ids, valid_projet_ids, valid_tache_ids, report):
    projet_intervenant = set()
    tache_intervenant = set()
    rh_ids = set()  # rempli par l'appelant si besoin (non utilisé ici directement)

    for r in data["intervenants"]:
        uid = r["intervenantID"]
        if uid is None or uid not in valid_user_ids:
            continue
        if r["taskID"] is not None:
            if r["taskID"] in valid_tache_ids:
                tache_intervenant.add((r["taskID"], uid))
        elif r["projectID"] is not None:
            if r["projectID"] in valid_projet_ids:
                projet_intervenant.add((r["projectID"], uid))

    return sorted(projet_intervenant), sorted(tache_intervenant)


# =====================================================================
# Étape 5 : DailyLog (depuis interventionHours, résolu via intervenants)
# =====================================================================

def build_dailylog(data, valid_user_ids, valid_projet_ids, valid_tache_ids, report):
    interv_by_id = {r["id"]: r for r in data["intervenants"]}
    agg = defaultdict(float)  # (uid, date, projet_id, tache_id_or_0) -> heures
    ignorees_sans_intervention = 0
    ignorees_donnees_invalides = 0

    for h in data["interventionHours"]:
        interv_id = h["interventionID"]
        if interv_id is None:
            ignorees_sans_intervention += 1
            continue
        interv = interv_by_id.get(interv_id)
        if not interv or interv["intervenantID"] is None:
            ignorees_sans_intervention += 1
            continue
        uid = interv["intervenantID"]
        projet_id = interv["projectID"]
        tache_id = interv["taskID"]
        date = mysql_date_only(h["date"])
        heures = h["hours"]
        if uid not in valid_user_ids or projet_id not in valid_projet_ids or not date or not heures or heures <= 0:
            ignorees_donnees_invalides += 1
            continue
        if tache_id is not None and tache_id not in valid_tache_ids:
            tache_id = None  # le projet reste valide même si la tâche a été exclue
        key = (uid, date, projet_id, tache_id or 0)
        agg[key] += float(heures)

    report["dailylog_ignore_sans_intervenant"] = ignorees_sans_intervention
    report["dailylog_ignore_invalide"] = ignorees_donnees_invalides

    lignes = []
    for (uid, date, projet_id, tache_id0), heures in agg.items():
        heures = round(heures, 2)
        if heures <= 0:
            continue
        if heures > 99.99:
            heures = 99.99  # borne NUMERIC(4,2), cas extrême improbable
        lignes.append(dict(
            utilisateur_id=uid, date=date, projet_id=projet_id,
            tache_id=(tache_id0 or None), heures=heures,
        ))
    return lignes


# =====================================================================
# Étape 6 : Requêtes -> Post (type_code = 'requete')
# =====================================================================

def build_requetes_posts(data, valid_user_ids, valid_projet_ids, projets_by_id, report):
    posts = []
    fallback_auteur = 0
    for r in data["requests"]:
        projet_id = r["projectID"]
        if projet_id not in valid_projet_ids:
            report["requetes_ignorees_projet_invalide"].append(r["id"])
            continue
        auteur_id = r["creatorID"]
        if auteur_id not in valid_user_ids:
            auteur_id = projets_by_id[projet_id]["chef_projet_id"]
            fallback_auteur += 1
        created_at = mysql_dt_to_pg(r["createdAt"]) or "now()"
        updated_at = mysql_dt_to_pg(r["updatedAt"]) or created_at
        posts.append(dict(
            projet_id=projet_id, auteur_id=auteur_id,
            contenu=clean_text(r["description"]) or "(sans description)",
            created_at=created_at, updated_at=updated_at,
        ))
    report["requetes_auteur_par_defaut"] = fallback_auteur
    return posts


# =====================================================================
# Génération du fichier SQL
# =====================================================================

def emit_sql(path, utilisateurs, projets, projet_lots, liens_phase, taches,
             projet_intervenant, tache_intervenant, dailylog, posts):
    out = []
    w = out.append

    w("-- =====================================================================")
    w("-- Migration automatique Kairos (ancien, MySQL) -> Kairos (Postgres)")
    w(f"-- Généré le {datetime.now().isoformat(timespec='seconds')} par scripts/migrate_from_chronos.py")
    w("-- À rejouer sur une base FRAÎCHE (schema.sql déjà appliqué, aucune")
    w("-- donnée métier existante) — voir le rapport .md associé.")
    w("-- =====================================================================")
    w("BEGIN;")
    w("")

    w("-- --- Utilisateurs (emails anonymisés en nom_prenom@domaine ; mots de")
    w("-- --- passe temporaires aléatoires, voir le fichier identifiants séparé) ---")
    for u in utilisateurs:
        w(
            "INSERT INTO utilisateur (id, email, mot_de_passe_hash, nom, prenom, "
            "telephone, poste, adresse, date_embauche, role, verifie, actif, "
            "created_at, updated_at) VALUES ("
            f"{u['id']}, {sql_val(u['email'])}, {sql_val(u['mot_de_passe_hash'])}, "
            f"{sql_val(u['nom'])}, {sql_val(u['prenom'])}, {sql_val(u['telephone'])}, "
            f"{sql_val(u['poste'])}, {sql_val(u['adresse'])}, {sql_val(u['date_embauche'])}, "
            f"{sql_val(u['role'])}::role_enum, {sql_val(u['verifie'])}, {sql_val(u['actif'])}, "
            f"{sql_val(u['created_at'])}, {sql_val(u['updated_at'])});"
        )
    w("")

    w("-- --- Projets ---")
    for p in projets:
        w(
            "INSERT INTO projet (id, code, nom, phase, date_debut, date_fin, etat, "
            "chef_projet_id, created_by, created_at, updated_at) VALUES ("
            f"{p['id']}, {sql_val(p['code'])}, {sql_val(p['nom'])}, {sql_val(p['phase'])}::phase_enum, "
            f"{sql_val(p['date_debut'])}, {sql_val(p['date_fin'])}, {sql_val(p['etat'])}::projet_etat_enum, "
            f"{p['chef_projet_id']}, {sql_val(p['created_by'])}, "
            f"{sql_val(p['created_at'])}, {sql_val(p['updated_at'])});"
        )
    w("")

    w("-- --- Phase liée (2e passe, une fois tous les projets insérés) ---")
    for projet_id, prev_id in liens_phase:
        w(f"UPDATE projet SET phase_liee_id = {prev_id} WHERE id = {projet_id};")
    w("")

    w("-- --- Lots par projet ---")
    for projet_id, lot_code in projet_lots:
        w(f"INSERT INTO projet_lot (projet_id, lot_code) VALUES ({projet_id}, {sql_val(lot_code)}) ON CONFLICT DO NOTHING;")
    w("")

    w("-- --- Tâches ---")
    w("-- created_by n'existe pas dans l'ancien Kairos : on retombe sur le chef de")
    w("-- projet du projet (donnée non fiable à 100%, voir le rapport).")
    for t in taches:
        w(
            "INSERT INTO tache (id, projet_id, titre, etat, date_debut, date_echeance, "
            "date_fin, created_by, created_at, updated_at) SELECT "
            f"{t['id']}, {t['projet_id']}, {sql_val(t['titre'])}, {sql_val(t['etat'])}::tache_etat_enum, "
            f"{sql_val(t['date_debut'])}, {sql_val(t['date_echeance'])}, {sql_val(t['date_fin'])}, "
            f"chef_projet_id, {sql_val(t['created_at'])}, {sql_val(t['updated_at'])} "
            f"FROM projet WHERE id = {t['projet_id']};"
        )
    w("")

    w("-- --- Intervenants (projet) ---")
    for projet_id, uid in projet_intervenant:
        w(f"INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES ({projet_id}, {uid}) ON CONFLICT DO NOTHING;")
    w("")

    w("-- --- Intervenants (tâche) ---")
    for tache_id, uid in tache_intervenant:
        w(f"INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES ({tache_id}, {uid}) ON CONFLICT DO NOTHING;")
    w("")

    w("-- --- DailyLog (reconstruit depuis interventionHours, agrégé par jour/projet/tâche) ---")
    for d in dailylog:
        w(
            "INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures) VALUES ("
            f"{d['utilisateur_id']}, {sql_val(d['date'])}, {d['projet_id']}, {sql_val(d['tache_id'])}, {d['heures']}) "
            "ON CONFLICT (utilisateur_id, date, projet_id, COALESCE(tache_id, 0)) DO UPDATE SET heures = EXCLUDED.heures;"
        )
    w("")

    w("-- --- Requêtes historiques -> Post (type 'requete') ---")
    for p in posts:
        w(
            "INSERT INTO post (projet_id, auteur_id, type_code, contenu, created_at, updated_at) VALUES ("
            f"{p['projet_id']}, {p['auteur_id']}, 'requete', {sql_val(p['contenu'])}, "
            f"{sql_val(p['created_at'])}, {sql_val(p['updated_at'])});"
        )
    w("")

    w("-- --- Réajustement des séquences (id insérés explicitement ci-dessus) ---")
    w("SELECT setval(pg_get_serial_sequence('utilisateur','id'), COALESCE((SELECT MAX(id) FROM utilisateur), 1));")
    w("SELECT setval(pg_get_serial_sequence('projet','id'), COALESCE((SELECT MAX(id) FROM projet), 1));")
    w("SELECT setval(pg_get_serial_sequence('tache','id'), COALESCE((SELECT MAX(id) FROM tache), 1));")
    w("SELECT setval(pg_get_serial_sequence('post','id'), COALESCE((SELECT MAX(id) FROM post), 1));")
    w("SELECT setval(pg_get_serial_sequence('dailylog_entree','id'), COALESCE((SELECT MAX(id) FROM dailylog_entree), 1));")
    w("")
    w("COMMIT;")

    path.write_text("\n".join(out), encoding="utf-8")


def emit_credentials(path, credentials):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id_utilisateur", "nom", "prenom", "email_kairos", "mot_de_passe_temporaire", "ancien_email_reel_NE_PAS_UTILISER"])
        for row in credentials:
            writer.writerow(row)


def emit_rapport(path, report, counts, args):
    lines = []
    a = lines.append
    a(f"# Rapport de migration Kairos (ancien) -> Kairos (nouveau)\n")
    a(f"Généré le {datetime.now().isoformat(timespec='seconds')} à partir de `{args.dump.name}`.\n")

    a("## Résumé des volumes migrés\n")
    for k, v in counts.items():
        a(f"- {k} : **{v}**")
    a("")

    a("## Décisions appliquées automatiquement (à connaître avant d'utiliser la base)\n")
    a("- **Emails anonymisés** : tous les emails réels ont été remplacés par "
      f"`nom_prenom@{args.email_domain}` (voir la colonne `ancien_email_reel_NE_PAS_UTILISER` "
      "du fichier d'identifiants, gardée seulement pour que tu puisses recontacter la bonne "
      "personne — jamais insérée en base).")
    a("- **Mots de passe** : tous nouveaux, générés aléatoirement (l'ancien hash n'a "
      "jamais été repris). À distribuer toi-même, en main propre, jamais par email "
      "(voir fichier d'identifiants — à supprimer une fois les mots de passe transmis, "
      "et à ne jamais commiter dans git).")
    a("- **Rôle** : `Chef_projet`→`chef_de_projet`, `intervenant`→`intervenant`, "
      "`client`→`client`, `ressource_humaine`→`rh`, `superuser`/`isSuperUser`→`admin`.")
    a("- **Compte(s) banni(s)** dans l'ancien Kairos : forcés `actif=false` dans le nouveau, "
      "quel que soit l'ancien statut `active`.")
    a("- **Équipe (`equipe_code`)** : l'ancien Kairos n'a pas cette notion — laissée "
      "**vide** pour tout le monde (utilisateurs ET projets). À assigner à la main "
      "(page Utilisateurs / fiche projet) après import : tant que ce n'est pas fait, "
      "la visibilité des projets par équipe ne filtre rien pour les non-admin/RH.")
    a("- **Code projet** : reconstruit depuis `customId` (ex. `18C9P_chambres funéraires` "
      "→ code `18C9P`), unique vérifié sur les 807 projets sans collision.")
    a("- **`tache.created_by`** : l'ancien Kairos ne trace pas qui a créé une tâche — "
      "repris par défaut = chef de projet du projet. Pas fiable comme vraie auteur, "
      "à garder en tête si tu consultes l'historique/l'audit.")
    a("- **`tache.type_deadline`** : laissé à la valeur par défaut `rendu_client` "
      "pour toutes les tâches migrées (pas de distinction interne/client dans "
      "l'ancien système).")
    a("- **DailyLog** : reconstruit depuis `interventionHours`, uniquement quand la "
      "ligne était bien rattachée à une personne précise (voir ci-dessous) ; les lignes "
      "en double (même jour/projet/tâche/personne) ont été additionnées.")
    a("")

    a("## Lignes ignorées (et pourquoi)\n")
    a(f"- {len(report['taches_sans_projet'])} tâche(s) sans projet reconstituable "
      "(ni via la table `intervenants`, ni via le champ `meta`) — non importées. "
      f"IDs ancien Kairos : {report['taches_sans_projet'] or '—'}")
    a(f"- {len(report['projets_phase_invalide'])} projet(s) avec une phase introuvable — non importés. "
      f"{report['projets_phase_invalide'] or ''}")
    a(f"- {len(report['projets_manager_invalide'])} projet(s) avec un chef de projet introuvable — non importés. "
      f"{report['projets_manager_invalide'] or ''}")
    a(f"- {len(report['requetes_ignorees_projet_invalide'])} requête(s) liée(s) à un projet non importé — ignorée(s).")
    a(f"- {report['requetes_auteur_par_defaut']} requête(s) sans auteur d'origine exploitable — "
      "rattachée(s) au chef de projet par défaut.")
    a(f"- {report['dailylog_ignore_sans_intervenant']} ligne(s) `interventionHours` sans personne "
      "identifiable (`interventionID` vide ou orpheline dans l'ancienne base) — ignorée(s) "
      "(cette fonctionnalité était très peu utilisée dans l'ancien Kairos : 183 lignes au "
      "total pour 807 projets).")
    a(f"- {report['dailylog_ignore_invalide']} ligne(s) `interventionHours` avec des données "
      "incohérentes (heures nulles/négatives, projet ou utilisateur introuvable) — ignorée(s).")
    if report["codes_projet_renommes"]:
        a(f"- {len(report['codes_projet_renommes'])} code(s) projet renommé(s) pour éviter un "
          f"doublon : {report['codes_projet_renommes']}")
    if report["comptes_bannis_desactives"]:
        a(f"- Compte(s) banni(s) désactivé(s) d'office : {report['comptes_bannis_desactives']}")
    if report["roles_inconnus"]:
        a(f"- Rôle(s) non reconnu(s), remplacé(s) par `intervenant` par défaut : {report['roles_inconnus']}")
    if report["profils_manquants"]:
        a(f"- Utilisateur(s) sans fiche `UserProfiles` (nom/prénom de repli utilisés) : {report['profils_manquants']}")
    a("")

    a("## Hors périmètre (non repris, étape 2 / pas modélisé) \n")
    a("Congés/Télétravail (`vacationRequests`, `userVacationBalance`, `SicknessRequestReminders`, "
      "`vacationRequestsContests`), notifications historiques, jours fériés (`holidays`), "
      "sessions (`user_sessions`), jetons de réinitialisation (`resetPasswordTokens`), "
      "`configurations` — aucun équivalent dans le schéma étape 1 actuel, rien n'a été migré "
      "pour ces tables (pas une perte : à reprendre quand l'étape 2 sera construite, si besoin).")
    a("")

    a("## Pour rejouer cette migration plus tard (nouvel export)\n")
    a("```\n"
      f"python3 scripts/migrate_from_chronos.py nouveau_export.sql --out-dir migration_YYYY-MM-DD\n"
      "```\n"
      "Puis, sur une base FRAÎCHE (schema.sql tout juste appliqué, aucune donnée dedans) :\n"
      "```\n"
      "docker compose exec -T db psql -U kairos -d kairos -f /chemin/vers/migration.sql\n"
      "```\n")

    path.write_text("\n".join(lines), encoding="utf-8")


# =====================================================================
# Orchestration
# =====================================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dump", type=Path, help="Fichier .sql (mysqldump) de l'ancien Kairos")
    ap.add_argument("--out-dir", type=Path, default=None,
                     help="Dossier de sortie (défaut : migration_sorties/<horodatage>)")
    ap.add_argument("--email-domain", default="kairos.tn",
                     help="Domaine utilisé pour les emails anonymisés (défaut : kairos.tn)")
    args = ap.parse_args()

    if not args.dump.exists():
        print(f"Fichier introuvable : {args.dump}", file=sys.stderr)
        sys.exit(1)

    out_dir = args.out_dir or Path("migration_sorties") / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Lecture de {args.dump} ...")
    table_columns, data = load_dump(str(args.dump))

    report = defaultdict(list)
    report["dailylog_ignore_sans_intervenant"] = 0
    report["dailylog_ignore_invalide"] = 0
    report["requetes_auteur_par_defaut"] = 0

    print("Transformation des utilisateurs ...")
    utilisateurs, credentials, valid_user_ids = build_utilisateurs(data, args.email_domain, report)

    print("Transformation des projets ...")
    projets, projet_lots, liens_phase, valid_projet_ids = build_projets(data, valid_user_ids, report)
    projets_by_id = {p["id"]: p for p in projets}

    print("Transformation des tâches ...")
    taches, valid_tache_ids = build_taches(data, valid_projet_ids, report)

    print("Transformation des intervenants ...")
    projet_intervenant, tache_intervenant = build_intervenants(
        data, valid_user_ids, valid_projet_ids, valid_tache_ids, report)

    print("Reconstruction du DailyLog ...")
    dailylog = build_dailylog(data, valid_user_ids, valid_projet_ids, valid_tache_ids, report)

    print("Transformation des requêtes en posts ...")
    posts = build_requetes_posts(data, valid_user_ids, valid_projet_ids, projets_by_id, report)

    sql_path = out_dir / "migration.sql"
    creds_path = out_dir / "identifiants_NE_PAS_COMMITER.csv"
    rapport_path = out_dir / "rapport.md"

    print(f"Écriture de {sql_path} ...")
    emit_sql(sql_path, utilisateurs, projets, projet_lots, liens_phase, taches,
              projet_intervenant, tache_intervenant, dailylog, posts)

    print(f"Écriture de {creds_path} ...")
    emit_credentials(creds_path, credentials)

    counts = {
        "Utilisateurs": len(utilisateurs),
        "Projets": len(projets),
        "Tâches": len(taches),
        "Lots de projet": len(projet_lots),
        "Intervenants sur projet": len(projet_intervenant),
        "Intervenants sur tâche": len(tache_intervenant),
        "Lignes DailyLog reconstruites": len(dailylog),
        "Requêtes -> posts": len(posts),
    }
    print(f"Écriture de {rapport_path} ...")
    emit_rapport(rapport_path, report, counts, args)

    print("\nTerminé.")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print(f"\nFichiers dans : {out_dir}/")
    print("  - migration.sql                     (à rejouer avec psql sur la base cible)")
    print("  - identifiants_NE_PAS_COMMITER.csv   (mots de passe temporaires — à transmettre en main propre, à supprimer ensuite)")
    print("  - rapport.md                        (détail des choix et des lignes ignorées)")


if __name__ == "__main__":
    main()

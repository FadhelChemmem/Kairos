#!/usr/bin/env python3
"""Rechargement des projets et tâches Chronos dans une base Kairos DÉJÀ en
service (lot 12 : migrations jusqu'à 0018), sans toucher aux comptes.

Cas d'usage : la base a été chargée une première fois par
scripts/migrate_from_chronos.py (reprise COMPLÈTE, id Chronos conservés),
puis utilisée pour des essais. On veut repartir des projets/tâches d'un
export Chronos plus récent en GARDANT les utilisateurs tels qu'ils sont
devenus (rôles, e-mails, mots de passe, fuseaux, équipes, sessions).

Le script lit un dump mysqldump et écrit UN fichier SQL, une seule
transaction (BEGIN … COMMIT, ON_ERROR_STOP), qui :
  1. vérifie que la base est à jour (dernière migration :
     0018_modes_admin_et_date_simulee) et que toutes ses tables sont
     connues ;
  2. vérifie que chaque utilisateur Chronos référencé (chef, créateur,
     intervenant) existe dans Kairos avec le même id et les mêmes
     nom/prénom — sinon RAISE EXCEPTION listant les écarts, rien n'est
     modifié ;
  3. efface les données métier (TRUNCATE … RESTART IDENTITY CASCADE sur la
     liste TABLES_EFFACEES ; la fermeture des clés étrangères est contrôlée
     avant, et une empreinte des tables conservées est comparée après) ;
  4. insère projets, lots, tâches et intervenants avec les id Chronos ; les
     co-chefs sont créés par les triggers du lot 10 (chef de projet ajouté
     comme intervenant) ; un intervenant RH/Client dans Kairos est écarté
     et compté, un projet dont le chef est RH/Client aussi (avec ses
     tâches), comme dans la reprise complète ; chaque projet reçoit
     l'équipe de son chef dans Kairos, à défaut MIDGARD (lot 11) ;
  5. réajuste les séquences, écrit UNE ligne de synthèse dans audit_log
     (les triggers d'audit des tables rechargées sont coupés le temps de la
     transaction : pas de dizaines de milliers de lignes), affiche un
     récapitulatif.
Pas de reprise des heures (interventionHours) ni des requêtes (requests).

La transformation (codes projet, états, dates incohérentes, lots, phase
liée, rattachement tâche -> projet, cohérence des états du lot 11 : tâches
ouvertes d'un projet clos fermées, projet ouvert Bloqué si et seulement si
une de ses tâches l'est) est CELLE de migrate_from_chronos.py, importée
telle quelle : les deux scripts produisent les mêmes projets. Le SQL
compte ces corrections et signale, au moment de l'application, les projets
ouverts sans tâche ouverte et ceux dont le chef est désactivé dans Kairos.

Usage :
    python3 scripts/recharger_projets_chronos.py chronos_XXXX.sql \\
        --sql recharge.sql --rapport recharge.md
    docker compose exec -T db psql -X -v ON_ERROR_STOP=1 -U kairos -d kairos < recharge.sql

Le .sql et le .md contiennent des données réelles : jamais dans git.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from migrate_from_chronos import (  # noqa: E402
    EQUIPE_PAR_DEFAUT, appliquer_coherence, build_intervenants, build_projets, build_taches,
    build_utilisateurs, projets_ouverts_sans_tache_ouverte, sql_val,
)
from mysqldump_parser import load_dump  # noqa: E402

MIGRATION_ATTENDUE = "0018_modes_admin_et_date_simulee"

# Données métier effacées puis rechargées (ou laissées vides) — ordre
# indifférent pour TRUNCATE. Toute table de la base doit figurer ici ou
# dans TABLES_CONSERVEES, sinon le SQL refuse de s'exécuter.
TABLES_EFFACEES = (
    "notification",
    "post_commentaire_mention", "post_commentaire_piece_jointe", "post_commentaire",
    "post_reaction", "post_equipe", "post_mention", "post_piece_jointe", "post",
    "dailylog_jour", "dailylog_entree",
    "tache_piece_jointe", "tache_intervenant", "tache",
    "projet_intervenant", "projet_co_chef", "projet_lot", "projet",
)

# Jamais modifiées (empreinte comparée avant/après), sauf audit_log qui
# reçoit une seule ligne de synthèse.
TABLES_CONSERVEES = (
    "utilisateur", "utilisateur_session", "dailylog_preference",
    "equipe", "lot", "post_type", "reaction_type",
    "audit_log", "tentative_securite", "schema_migrations",
)

# Triggers d'audit coupés pendant les insertions (réactivés avant COMMIT).
TRIGGERS_AUDIT = (
    ("projet", "trg_audit_projet"),
    ("projet_lot", "trg_audit_projet_lot"),
    ("projet_co_chef", "trg_audit_projet_co_chef"),
    ("projet_intervenant", "trg_audit_projet_intervenant"),
    ("tache", "trg_audit_tache"),
    ("tache_intervenant", "trg_audit_tache_intervenant"),
)

TAILLE_LOT = 500


def _rapport_vide():
    report = defaultdict(list)
    report["dailylog_ignore_sans_intervenant"] = 0
    report["dailylog_ignore_invalide"] = 0
    report["requetes_auteur_par_defaut"] = 0
    return report


# =====================================================================
# Préparation (transformation commune avec migrate_from_chronos.py)
# =====================================================================

def preparer(data: dict) -> dict:
    report = _rapport_vide()
    utilisateurs, _, valid_user_ids = build_utilisateurs(
        data, "kairos.tn", report, generer_mots_de_passe=False)
    # Rôles : ceux de la base Kairos font foi, contrôlés par le SQL au moment
    # de l'application (rh_ids vide ici) — le gérant a pu les changer.
    projets, projet_lots, liens_phase, valid_projet_ids = build_projets(data, valid_user_ids, report)
    taches, valid_tache_ids = build_taches(data, valid_projet_ids, report)
    appliquer_coherence(projets, taches, report)
    projet_intervenant, tache_intervenant = build_intervenants(
        data, valid_user_ids, valid_projet_ids, valid_tache_ids, report)
    projet_lots = sorted(set(projet_lots))
    lien = dict(liens_phase)

    usages = defaultdict(set)
    for p in projets:
        usages[p["chef_projet_id"]].add("chef de projet")
        if p["created_by"] is not None:
            usages[p["created_by"]].add("créateur de projet")
    for _, uid in projet_intervenant:
        usages[uid].add("intervenant de projet")
    for _, uid in tache_intervenant:
        usages[uid].add("intervenant de tâche")
    par_id = {u["id"]: u for u in utilisateurs}
    references = [
        dict(id=uid, nom=par_id[uid]["nom"], prenom=par_id[uid]["prenom"],
             role_chronos=par_id[uid]["role"], usages=", ".join(sorted(usages[uid])))
        for uid in sorted(usages)
    ]

    # Comptage des lignes `intervenants` non reprises (information pour le
    # rapport ; la sélection elle-même est celle de build_intervenants).
    stats = Counter()
    for r in data["intervenants"]:
        uid = r["intervenantID"]
        if uid is None:
            stats["sans_personne"] += 1
        elif uid not in valid_user_ids:
            stats["personne_inconnue"] += 1
        elif r["taskID"] is not None and r["taskID"] not in valid_tache_ids:
            stats["tache_non_chargee"] += 1
        elif r["taskID"] is None and r["projectID"] not in valid_projet_ids:
            stats["projet_non_charge"] += 1
        else:
            stats["retenues"] += 1
    stats["doublons"] = stats["retenues"] - len(projet_intervenant) - len(tache_intervenant)

    # Prévision des co-chefs avec les rôles Chronos (= ceux de la reprise
    # complète, si personne ne les a changés depuis) : le vrai nombre est
    # calculé par les triggers et affiché à l'application.
    chef_de = {p["id"]: p["chef_projet_id"] for p in projets}
    projet_de_tache = {t["id"]: t["projet_id"] for t in taches}
    role = {u["id"]: u["role"] for u in utilisateurs}
    co_chefs = {(pid, uid) for pid, uid in projet_intervenant}
    co_chefs |= {(projet_de_tache[tid], uid) for tid, uid in tache_intervenant}
    co_chefs = {(pid, uid) for pid, uid in co_chefs
                if role.get(uid) == "chef_de_projet" and chef_de[pid] != uid
                and role.get(chef_de[pid]) not in ("rh", "client")}
    exclus_prevus = sorted({uid for _, uid in projet_intervenant + tache_intervenant
                            if role.get(uid) in ("rh", "client")})
    projets_exclus_prevus = sorted(p["id"] for p in projets if role.get(p["chef_projet_id"]) in ("rh", "client"))
    actif = {u["id"]: u["actif"] for u in utilisateurs}
    chef_inactif_prevus = sorted(p["code"] for p in projets
                                 if p["etat"] in ("en_cours", "bloque") and not actif.get(p["chef_projet_id"]))

    return dict(
        projets=projets, lien=lien, projet_lots=projet_lots, taches=taches,
        projet_intervenant=projet_intervenant, tache_intervenant=tache_intervenant,
        references=references, report=report, stats_intervenants=stats,
        co_chefs_prevus=len(co_chefs), intervenants_rh_client_prevus=exclus_prevus,
        projets_chef_rh_client_prevus=projets_exclus_prevus,
        sans_tache_ouverte=projets_ouverts_sans_tache_ouverte(projets, taches),
        chef_inactif_prevus=chef_inactif_prevus,
        volumes_dump={k: len(data.get(k, [])) for k in (
            "users", "projects", "tasks", "intervenants", "projectLots", "lots", "phases",
            "interventionHours", "requests")},
    )


# =====================================================================
# Génération du SQL
# =====================================================================

def _valeurs(w, table, colonnes, lignes):
    for i in range(0, len(lignes), TAILLE_LOT):
        lot = lignes[i:i + TAILLE_LOT]
        w(f"INSERT INTO {table} ({', '.join(colonnes)}) VALUES")
        w(",\n".join("(" + ", ".join(sql_val(v) for v in ligne) + ")" for ligne in lot) + ";")


def _tableau_sql(noms):
    return "ARRAY[" + ", ".join(f"'{n}'" for n in noms) + "]"


def generer_sql(prep: dict, nom_dump: str) -> str:
    out = []
    w = out.append
    effacees = _tableau_sql(TABLES_EFFACEES)
    conservees = _tableau_sql(TABLES_CONSERVEES)
    normalise = "regexp_replace(btrim(fn_sans_accents({0})), '\\s+', ' ', 'g')"

    w("-- =====================================================================")
    w("-- Rechargement des projets et tâches Chronos dans une base Kairos à jour (lot 12)")
    w(f"-- Source : {nom_dump} ; généré le {datetime.now().isoformat(timespec='seconds')}")
    w("-- par scripts/recharger_projets_chronos.py. CONTIENT DES DONNÉES RÉELLES.")
    w("-- Conserve utilisateurs, sessions, préférences, tables de référence et")
    w("-- journal d'audit ; efface et recharge projets, tâches, intervenants,")
    w("-- lots ; vide posts, commentaires, Daily log, notifications.")
    w("-- Application : psql -X -v ON_ERROR_STOP=1 … < ce_fichier.sql")
    w("-- Rejouable : chaque passage repart des mêmes données.")
    w("-- =====================================================================")
    w("\\set ON_ERROR_STOP on")
    w("\\set QUIET on")
    w("SET client_encoding = 'UTF8';")
    w("BEGIN;")
    w("SET LOCAL timezone = 'Africa/Tunis';")
    w("-- Mêmes contournements que la reprise historique (migrate_from_chronos.py) :")
    w("-- aucun utilisateur applicatif, garde-fous du Daily log et des états réservés")
    w("-- (migrations 0014, 0015) levés pour cette seule transaction.")
    w("SET LOCAL app.current_user_id = '';")
    w("SET LOCAL kairos.reprise_historique = 'on';")
    w("")

    w(f"-- --- 1. Base à jour ({MIGRATION_ATTENDUE}), tables connues, aucune cascade hors périmètre ---")
    w(f"""DO $$
DECLARE
  v_inconnues TEXT;
  v_hors TEXT;
BEGIN
  IF to_regclass('public.schema_migrations') IS NULL
     OR NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '{MIGRATION_ATTENDUE}') THEN
    RAISE EXCEPTION 'Rechargement annulé : la base n''est pas à jour (migration {MIGRATION_ATTENDUE} absente). Déployer le lot 12 (flask migrer) avant de recharger.';
  END IF;
  IF EXISTS (SELECT 1 FROM schema_migrations WHERE version > '{MIGRATION_ATTENDUE}') THEN
    RAISE EXCEPTION 'Rechargement annulé : la base contient des migrations postérieures à {MIGRATION_ATTENDUE} (%). Ce fichier a été préparé pour le lot 12 : régénérer avec un script à jour.',
      (SELECT string_agg(version, ', ' ORDER BY version) FROM schema_migrations WHERE version > '{MIGRATION_ATTENDUE}');
  END IF;
  SELECT string_agg(c.relname, ', ' ORDER BY c.relname) INTO v_inconnues
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
    AND c.relname <> ALL ({effacees} || {conservees});
  IF v_inconnues IS NOT NULL THEN
    RAISE EXCEPTION 'Rechargement annulé : table(s) inconnue(s) du script : %. Les classer (effacée ou conservée) dans scripts/recharger_projets_chronos.py.', v_inconnues;
  END IF;
  -- TRUNCATE … CASCADE videra aussi toute table qui référence (directement
  -- ou non) une table effacée : elle doit être dans la liste, et jamais
  -- utilisateur ni une table de référence.
  WITH RECURSIVE cible(rel) AS (
    SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relname = ANY ({effacees})
    UNION
    SELECT con.conrelid FROM pg_constraint con JOIN cible ON con.confrelid = cible.rel
    WHERE con.contype = 'f'
  )
  SELECT string_agg(DISTINCT c.relname, ', ') INTO v_hors
  FROM cible JOIN pg_class c ON c.oid = cible.rel
  WHERE c.relname <> ALL ({effacees});
  IF v_hors IS NOT NULL THEN
    RAISE EXCEPTION 'Rechargement annulé : TRUNCATE CASCADE atteindrait des tables conservées (%).', v_hors;
  END IF;
END $$;""")
    w("")

    w("-- --- 2. Données du dump (tables temporaires, supprimées au COMMIT) ---")
    w("CREATE TEMP TABLE rch_utilisateur (id BIGINT PRIMARY KEY, nom TEXT, prenom TEXT, usages TEXT) ON COMMIT DROP;")
    w("CREATE TEMP TABLE rch_projet (id BIGINT PRIMARY KEY, code TEXT, nom TEXT, phase TEXT, date_debut DATE, "
      "date_fin DATE, date_cloture DATE, etat TEXT, etat_chronos TEXT, chef_projet_id BIGINT, phase_liee_id BIGINT, "
      "created_by BIGINT, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ) ON COMMIT DROP;")
    w("CREATE TEMP TABLE rch_projet_lot (projet_id BIGINT, lot_code TEXT) ON COMMIT DROP;")
    w("CREATE TEMP TABLE rch_tache (id BIGINT PRIMARY KEY, projet_id BIGINT, titre TEXT, etat TEXT, etat_chronos TEXT, "
      "date_debut DATE, date_echeance DATE, date_fin DATE, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ) ON COMMIT DROP;")
    w("CREATE TEMP TABLE rch_projet_intervenant (projet_id BIGINT, utilisateur_id BIGINT) ON COMMIT DROP;")
    w("CREATE TEMP TABLE rch_tache_intervenant (tache_id BIGINT, utilisateur_id BIGINT) ON COMMIT DROP;")
    w("CREATE TEMP TABLE rch_recap (ordre INT, rubrique TEXT, nombre BIGINT) ON COMMIT DROP;")
    w("CREATE TEMP TABLE rch_empreinte (nom TEXT PRIMARY KEY, avant TEXT) ON COMMIT DROP;")
    _valeurs(w, "rch_utilisateur", ("id", "nom", "prenom", "usages"),
             [(u["id"], u["nom"], u["prenom"], u["usages"]) for u in prep["references"]])
    _valeurs(w, "rch_projet", ("id", "code", "nom", "phase", "date_debut", "date_fin", "date_cloture", "etat",
                               "etat_chronos", "chef_projet_id", "phase_liee_id", "created_by", "created_at",
                               "updated_at"),
             [(p["id"], p["code"], p["nom"], p["phase"], p["date_debut"], p["date_fin"], p.get("date_cloture"),
               p["etat"], p.get("etat_chronos", p["etat"]), p["chef_projet_id"], prep["lien"].get(p["id"]),
               p["created_by"], p["created_at"], p["updated_at"]) for p in prep["projets"]])
    _valeurs(w, "rch_projet_lot", ("projet_id", "lot_code"), prep["projet_lots"])
    _valeurs(w, "rch_tache", ("id", "projet_id", "titre", "etat", "etat_chronos", "date_debut", "date_echeance",
                              "date_fin", "created_at", "updated_at"),
             [(t["id"], t["projet_id"], t["titre"], t["etat"], t.get("etat_chronos", t["etat"]), t["date_debut"],
               t["date_echeance"], t["date_fin"], t["created_at"], t["updated_at"]) for t in prep["taches"]])
    _valeurs(w, "rch_projet_intervenant", ("projet_id", "utilisateur_id"), prep["projet_intervenant"])
    _valeurs(w, "rch_tache_intervenant", ("tache_id", "utilisateur_id"), prep["tache_intervenant"])
    w("")

    w("-- --- 3. Utilisateurs Chronos référencés = utilisateurs Kairos (id, nom, prénom) ---")
    w(f"""DO $$
DECLARE
  v_n INT;
  v_liste TEXT;
BEGIN
  SELECT count(*), string_agg(
           CASE WHEN u.id IS NULL
             THEN format('  - id %s : absent de Kairos (Chronos : %s %s ; %s)', r.id, r.prenom, r.nom, r.usages)
             ELSE format('  - id %s : nom/prénom différents (Chronos : %s %s ; Kairos : %s %s ; %s)',
                         r.id, r.prenom, r.nom, u.prenom, u.nom, r.usages)
           END, E'\\n' ORDER BY r.id)
    INTO v_n, v_liste
  FROM rch_utilisateur r LEFT JOIN utilisateur u ON u.id = r.id
  WHERE u.id IS NULL
     OR {normalise.format('u.nom')} <> {normalise.format('r.nom')}
     OR {normalise.format('u.prenom')} <> {normalise.format('r.prenom')};
  IF v_n > 0 THEN
    RAISE EXCEPTION USING
      MESSAGE = format('Rechargement annulé, rien n''a été modifié : %s utilisateur(s) Chronos référencé(s) ne correspondent pas à Kairos (même id et mêmes nom/prénom attendus) :', v_n)
                || E'\\n' || v_liste,
      HINT = 'Rétablir le compte (id, nom, prénom) dans Kairos, ou corriger le nom dans Chronos et refaire l''export.';
  END IF;
  -- Écarts de casse, d'accents ou d'espaces seulement : tolérés, signalés.
  SELECT count(*), string_agg(format('  - id %s : Chronos « %s %s », Kairos « %s %s »', r.id, r.prenom, r.nom, u.prenom, u.nom), E'\\n' ORDER BY r.id)
    INTO v_n, v_liste
  FROM rch_utilisateur r JOIN utilisateur u ON u.id = r.id
  WHERE (u.nom, u.prenom) IS DISTINCT FROM (r.nom, r.prenom);
  IF v_n > 0 THEN
    RAISE NOTICE 'Noms identiques à la casse/aux accents près (tolérés) :%', E'\\n' || v_liste;
  END IF;
  INSERT INTO rch_recap VALUES (1, 'Utilisateurs Chronos référencés (tous présents dans Kairos)', (SELECT count(*) FROM rch_utilisateur));
  INSERT INTO rch_recap VALUES (2, 'Noms tolérés (casse/accents)', v_n);
END $$;""")
    w("")
    w("-- --- 3 bis. Projet dont le chef est RH ou Client dans Kairos : écarté avec ses")
    w("-- tâches, lots et intervenants (trigger trg_check_projet_chef_role ; même règle")
    w("-- que la reprise complète), compté et signalé ---")
    w("""DO $$
DECLARE
  v_liste TEXT;
BEGIN
  SELECT string_agg(format('projet %s (chef id %s, %s)', p.id, u.id, u.role), ', ' ORDER BY p.id) INTO v_liste
  FROM rch_projet p JOIN utilisateur u ON u.id = p.chef_projet_id
  WHERE u.role IN ('rh', 'client');
  IF v_liste IS NOT NULL THEN
    RAISE NOTICE 'Projets écartés (chef RH ou Client dans Kairos) : %', v_liste;
  END IF;
END $$;""")
    w("""WITH ecartes AS (
  DELETE FROM rch_projet p USING utilisateur u
  WHERE u.id = p.chef_projet_id AND u.role IN ('rh', 'client') RETURNING p.id
)
INSERT INTO rch_recap SELECT 4, 'Projets écartés (chef RH/Client dans Kairos)', count(*) FROM ecartes;""")
    w("""WITH ecartees AS (
  DELETE FROM rch_tache t WHERE NOT EXISTS (SELECT 1 FROM rch_projet p WHERE p.id = t.projet_id) RETURNING t.id
)
INSERT INTO rch_recap SELECT 5, '  tâches de ces projets, écartées', count(*) FROM ecartees;""")
    w("DELETE FROM rch_projet_lot l WHERE NOT EXISTS (SELECT 1 FROM rch_projet p WHERE p.id = l.projet_id);")
    w("DELETE FROM rch_projet_intervenant i WHERE NOT EXISTS (SELECT 1 FROM rch_projet p WHERE p.id = i.projet_id);")
    w("DELETE FROM rch_tache_intervenant i WHERE NOT EXISTS (SELECT 1 FROM rch_tache t WHERE t.id = i.tache_id);")
    w("UPDATE rch_projet p SET phase_liee_id = NULL "
      "WHERE NOT EXISTS (SELECT 1 FROM rch_projet l WHERE l.id = p.phase_liee_id);")
    w("")

    w("-- --- 4. Empreinte des tables conservées, volumes avant effacement ---")
    w(f"""DO $$
DECLARE
  t TEXT;
  v TEXT;
BEGIN
  FOREACH t IN ARRAY {conservees} LOOP
    EXECUTE format('SELECT count(*) || '':'' || md5(coalesce(string_agg(x::text, E''\\n'' ORDER BY x::text), '''')) FROM %I x', t) INTO v;
    INSERT INTO rch_empreinte VALUES (t, v);
  END LOOP;
END $$;""")
    w("""INSERT INTO rch_recap VALUES
  (20, 'Effacés : projets', (SELECT count(*) FROM projet)),
  (21, 'Effacés : tâches', (SELECT count(*) FROM tache)),
  (22, 'Effacés : posts', (SELECT count(*) FROM post)),
  (23, 'Effacés : commentaires', (SELECT count(*) FROM post_commentaire)),
  (24, 'Effacés : lignes Daily log', (SELECT count(*) FROM dailylog_entree)),
  (25, 'Effacés : jours Daily log (absences, versions)', (SELECT count(*) FROM dailylog_jour)),
  (26, 'Effacés : notifications', (SELECT count(*) FROM notification)),
  (27, 'Effacés : pièces jointes en base (fichiers laissés sur disque)',
       (SELECT count(*) FROM tache_piece_jointe) + (SELECT count(*) FROM post_piece_jointe)
       + (SELECT count(*) FROM post_commentaire_piece_jointe));""")
    w("")

    w("-- --- 5. Effacement (triggers d'audit des tables rechargées coupés) ---")
    for table, trigger in TRIGGERS_AUDIT:
        w(f"ALTER TABLE {table} DISABLE TRIGGER {trigger};")
    w(f"TRUNCATE TABLE {', '.join(TABLES_EFFACEES)} RESTART IDENTITY CASCADE;")
    w("")

    w("-- --- 6. Rechargement (id Chronos ; co-chefs posés par les triggers du lot 10) ---")
    w("-- Équipe du projet (lot 11, migration 0016) : celle de son chef dans Kairos,")
    w(f"-- à défaut {EQUIPE_PAR_DEFAUT} — sinon seuls les rattachés voient le projet.")
    w(f"""INSERT INTO projet (id, code, nom, phase, date_debut, date_fin, date_cloture, etat,
                    chef_projet_id, phase_liee_id, equipe_code, created_by, created_at, updated_at)
SELECT r.id, r.code, r.nom, r.phase::phase_enum, r.date_debut, r.date_fin, r.date_cloture,
       r.etat::projet_etat_enum, r.chef_projet_id, r.phase_liee_id, COALESCE(u.equipe_code, {sql_val(EQUIPE_PAR_DEFAUT)}),
       r.created_by, r.created_at, r.updated_at
FROM rch_projet r JOIN utilisateur u ON u.id = r.chef_projet_id ORDER BY r.id;""")
    w("""INSERT INTO projet_lot (projet_id, lot_code)
SELECT projet_id, lot_code FROM rch_projet_lot ORDER BY 1, 2;""")
    w("-- created_by de la tâche : chef du projet, comme la reprise complète.")
    w("""INSERT INTO tache (id, projet_id, titre, etat, date_debut, date_echeance, date_fin,
                   created_by, created_at, updated_at)
SELECT t.id, t.projet_id, t.titre, t.etat::tache_etat_enum, t.date_debut, t.date_echeance, t.date_fin,
       p.chef_projet_id, t.created_at, t.updated_at
FROM rch_tache t JOIN projet p ON p.id = t.projet_id ORDER BY t.id;""")
    w("""INSERT INTO projet_intervenant (projet_id, utilisateur_id)
SELECT r.projet_id, r.utilisateur_id
FROM rch_projet_intervenant r JOIN utilisateur u ON u.id = r.utilisateur_id
WHERE u.role NOT IN ('rh', 'client') ORDER BY 1, 2;""")
    w("""INSERT INTO tache_intervenant (tache_id, utilisateur_id)
SELECT r.tache_id, r.utilisateur_id
FROM rch_tache_intervenant r JOIN utilisateur u ON u.id = r.utilisateur_id
WHERE u.role NOT IN ('rh', 'client') ORDER BY 1, 2;""")
    for table, trigger in TRIGGERS_AUDIT:
        w(f"ALTER TABLE {table} ENABLE TRIGGER {trigger};")
    w("")

    w("-- --- 7. Séquences (id insérés explicitement) ---")
    w("""DO $$
BEGIN
  PERFORM setval(pg_get_serial_sequence('projet', 'id'), COALESCE(max(id), 1), max(id) IS NOT NULL) FROM projet;
  PERFORM setval(pg_get_serial_sequence('tache', 'id'), COALESCE(max(id), 1), max(id) IS NOT NULL) FROM tache;
END $$;""")
    w("")

    w("-- --- 8. Contrôles et récapitulatif ---")
    w(f"""DO $$
DECLARE
  t TEXT;
  v TEXT;
  v_ecartes TEXT;
BEGIN
  FOREACH t IN ARRAY {conservees} LOOP
    EXECUTE format('SELECT count(*) || '':'' || md5(coalesce(string_agg(x::text, E''\\n'' ORDER BY x::text), '''')) FROM %I x', t) INTO v;
    IF v IS DISTINCT FROM (SELECT avant FROM rch_empreinte WHERE nom = t) THEN
      RAISE EXCEPTION 'Rechargement annulé : la table conservée % a changé pendant la transaction.', t;
    END IF;
  END LOOP;
  IF (SELECT count(*) FROM projet) <> (SELECT count(*) FROM rch_projet)
     OR (SELECT count(*) FROM tache) <> (SELECT count(*) FROM rch_tache) THEN
    RAISE EXCEPTION 'Rechargement annulé : nombre de projets ou de tâches inattendu.';
  END IF;
  SELECT string_agg(DISTINCT format('id %s (%s)', u.id, u.role), ', ') INTO v_ecartes
  FROM (SELECT utilisateur_id FROM rch_projet_intervenant UNION SELECT utilisateur_id FROM rch_tache_intervenant) r
  JOIN utilisateur u ON u.id = r.utilisateur_id
  WHERE u.role IN ('rh', 'client');
  IF v_ecartes IS NOT NULL THEN
    RAISE NOTICE 'Intervenants écartés (rôle RH ou Client dans Kairos) : %', v_ecartes;
  END IF;
END $$;""")
    w("""INSERT INTO rch_recap VALUES
  (3, 'Projets chargés', (SELECT count(*) FROM projet)),
  (6, '  dont avec phase liée', (SELECT count(*) FROM projet WHERE phase_liee_id IS NOT NULL)),
  (7, 'Lots de projet chargés', (SELECT count(*) FROM projet_lot)),
  (8, 'Tâches chargées', (SELECT count(*) FROM tache)),
  (9, 'Intervenants de projet chargés', (SELECT count(*) FROM projet_intervenant)),
  (10, 'Intervenants de tâche chargés', (SELECT count(*) FROM tache_intervenant)),
  (11, 'Co-chefs créés (chef de projet intervenant, lot 10)', (SELECT count(*) FROM projet_co_chef)),
  (12, 'Intervenants de projet écartés (RH/Client)', (SELECT count(*) FROM rch_projet_intervenant r
       JOIN utilisateur u ON u.id = r.utilisateur_id WHERE u.role IN ('rh', 'client'))),
  (13, 'Intervenants de tâche écartés (RH/Client)', (SELECT count(*) FROM rch_tache_intervenant r
       JOIN utilisateur u ON u.id = r.utilisateur_id WHERE u.role IN ('rh', 'client'))),
  (14, 'Journal : projets/tâches créés en test dont l''id est repris par Chronos',
       (SELECT count(DISTINCT (a.table_cible, a.ligne_id)) FROM audit_log a
        WHERE a.action = 'INSERT' AND a.utilisateur_id IS NOT NULL
          AND ((a.table_cible = 'projet' AND a.ligne_id IN (SELECT id FROM projet))
            OR (a.table_cible = 'tache' AND a.ligne_id IN (SELECT id FROM tache))))),
  (15, 'Cohérence : tâches ouvertes de projets terminés, passées Terminée',
       (SELECT count(*) FROM rch_tache WHERE etat = 'termine' AND etat_chronos IN ('en_cours', 'bloque'))),
  (16, 'Cohérence : tâches ouvertes de projets abandonnés, passées Abandonnée',
       (SELECT count(*) FROM rch_tache WHERE etat = 'abandonne' AND etat_chronos IN ('en_cours', 'bloque'))),
  (17, 'Cohérence : projets En cours passés Bloqué (une tâche bloquée)',
       (SELECT count(*) FROM rch_projet WHERE etat = 'bloque' AND etat_chronos = 'en_cours')),
  (18, 'Cohérence : projets Bloqué passés En cours (aucune tâche bloquée)',
       (SELECT count(*) FROM rch_projet WHERE etat = 'en_cours' AND etat_chronos = 'bloque')),
  (19, 'Équipe {EQUIPE_PAR_DEFAUT} par défaut (chef sans équipe dans Kairos)',
       (SELECT count(*) FROM projet p JOIN utilisateur u ON u.id = p.chef_projet_id WHERE u.equipe_code IS NULL)),
  (28, 'À traiter : projets ouverts sans tâche ouverte (à clore ou planifier)',
       (SELECT count(*) FROM projet p WHERE p.etat IN ('en_cours', 'bloque')
          AND NOT EXISTS (SELECT 1 FROM tache t WHERE t.projet_id = p.id AND t.etat IN ('en_cours', 'bloque')))),
  (29, 'À traiter : projets ouverts dont le chef est désactivé',
       (SELECT count(*) FROM projet p JOIN utilisateur u ON u.id = p.chef_projet_id
        WHERE p.etat IN ('en_cours', 'bloque') AND NOT u.actif));""".replace("{EQUIPE_PAR_DEFAUT}", EQUIPE_PAR_DEFAUT))
    w("""DO $$
DECLARE
  v_liste TEXT;
BEGIN
  SELECT string_agg(p.code, ', ' ORDER BY p.code) INTO v_liste
  FROM projet p WHERE p.etat IN ('en_cours', 'bloque')
    AND NOT EXISTS (SELECT 1 FROM tache t WHERE t.projet_id = p.id AND t.etat IN ('en_cours', 'bloque'));
  IF v_liste IS NOT NULL THEN
    RAISE NOTICE 'Projets ouverts sans tâche ouverte (à clore ou à planifier) : %', v_liste;
  END IF;
  SELECT string_agg(format('%s (%s %s)', p.code, u.prenom, u.nom), ', ' ORDER BY p.code) INTO v_liste
  FROM projet p JOIN utilisateur u ON u.id = p.chef_projet_id
  WHERE p.etat IN ('en_cours', 'bloque') AND NOT u.actif;
  IF v_liste IS NOT NULL THEN
    RAISE NOTICE 'Projets ouverts dont le chef est désactivé (à réaffecter) : %', v_liste;
  END IF;
END $$;""")
    w(f"""INSERT INTO audit_log (table_cible, ligne_id, action, utilisateur_id, donnees_apres)
SELECT 'recharge_chronos', NULL, 'INSERT', NULL,
       jsonb_build_object('script', 'scripts/recharger_projets_chronos.py', 'dump', {sql_val(nom_dump)},
                          'tables_effacees', to_jsonb({effacees}))
       || (SELECT jsonb_object_agg(rubrique, nombre) FROM rch_recap);""")
    w("""DO $$
BEGIN
  RAISE NOTICE '%', E'Rechargement Chronos terminé :\\n'
    || (SELECT string_agg(format('  %s : %s', rubrique, nombre), E'\\n' ORDER BY ordre) FROM rch_recap);
END $$;""")
    w("SELECT rubrique AS \"Rechargement Chronos\", nombre FROM rch_recap ORDER BY ordre;")
    w("COMMIT;")
    w("")
    return "\n".join(out)


# =====================================================================
# Rapport
# =====================================================================

def generer_rapport(prep: dict, nom_dump: str, nom_sql: str) -> str:
    r = prep["report"]
    s = prep["stats_intervenants"]
    v = prep["volumes_dump"]
    lignes = []
    a = lignes.append
    a("# Rechargement des projets Chronos dans Kairos (base du lot 12)\n")
    a(f"Généré le {datetime.now().isoformat(timespec='seconds')} à partir de `{nom_dump}` "
      f"par `scripts/recharger_projets_chronos.py` → `{nom_sql}`. **Contient des données réelles : "
      "hors dépôt git.**\n")

    a("## Volumes\n")
    a("| | Dans le dump | Chargé par le SQL |")
    a("|---|---|---|")
    a(f"| Projets | {v['projects']} | {len(prep['projets'])} |")
    a(f"| Tâches | {v['tasks']} | {len(prep['taches'])} |")
    a(f"| Lots de projet | {v['projectLots']} | {len(prep['projet_lots'])} |")
    a(f"| Lignes `intervenants` | {v['intervenants']} | {len(prep['projet_intervenant'])} sur projet + "
      f"{len(prep['tache_intervenant'])} sur tâche |")
    a(f"| Utilisateurs | {v['users']} | 0 (conservés tels quels ; {len(prep['references'])} référencés, contrôlés) |")
    a(f"| Heures (`interventionHours`) | {v['interventionHours']} | 0 (non reprises, décision du gérant) |")
    a(f"| Requêtes (`requests`) | {v['requests']} | 0 (non reprises, décision du gérant) |")
    a(f"| Co-chefs automatiques | — | {prep['co_chefs_prevus']} prévus avec les rôles Chronos "
      "(nombre réel affiché à l'application : rôles actuels de Kairos) |")
    a("")

    a("## Lignes du dump écartées ou corrigées (même transformation que la reprise complète)\n")
    a("| Cas | Nombre | Détail |")
    a("|---|---|---|")

    def ligne(cas, elements, detail=None):
        a(f"| {cas} | {len(elements)} | {detail if detail is not None else (', '.join(map(str, elements)) or '—')} |")

    ligne("Tâches sans projet reconstituable (non chargées)", r["taches_sans_projet"])
    ligne("Projets à phase inconnue (non chargés)", r["projets_phase_invalide"])
    ligne("Projets dont le chef n'existe pas dans Chronos (non chargés)", r["projets_manager_invalide"])
    ligne("Projets : fin prévue antérieure au début (fin effacée)", r["projets_date_fin_effacee"],
          ", ".join(str(x[0]) for x in r["projets_date_fin_effacee"]) or "—")
    ligne("Tâches : échéance antérieure au début (échéance effacée)", r["taches_echeance_effacee"],
          ", ".join(str(x[0]) for x in r["taches_echeance_effacee"]) or "—")
    ligne("Codes projet en double (renommés -2, -3…)", r["codes_projet_renommes"],
          ", ".join(f"{x[0]} : {x[1]} → {x[2]}" for x in r["codes_projet_renommes"]) or "—")
    ligne("Rattachements projet/lot non reconnus", r["lots_non_reconnus"])
    a(f"| Lignes `intervenants` sans personne (lien tâche → projet seulement) | {s['sans_personne']} | normal |")
    a(f"| Lignes `intervenants` vers une personne absente de Chronos | {s['personne_inconnue']} | — |")
    a(f"| Lignes `intervenants` d'une tâche non chargée | {s['tache_non_chargee']} | — |")
    a(f"| Lignes `intervenants` d'un projet non chargé | {s['projet_non_charge']} | — |")
    a(f"| Lignes `intervenants` en double | {s['doublons']} | fusionnées |")
    a("")

    fermees = [(tid, code, {"en_cours": "En cours", "bloque": "Bloquée"}.get(avant, avant), apres)
               for tid, code, avant, apres in r["taches_fermees_projet_clos"]]
    recalcules = r["projets_etat_recalcule"]
    a("## Cohérence des états (lot 11, décision du gérant)\n")
    a("| Correction | Nombre | Détail |")
    a("|---|---|---|")
    a(f"| Tâches ouvertes d'un projet Terminé → Terminée | {sum(1 for x in fermees if x[3] == 'termine')} | "
      + (", ".join(f"{x[0]} ({x[1]}, {x[2]})" for x in fermees if x[3] == "termine") or "—") + " |")
    a(f"| Tâches ouvertes d'un projet Abandonné → Abandonnée | {sum(1 for x in fermees if x[3] == 'abandonne')} | "
      + (", ".join(f"{x[0]} ({x[1]}, {x[2]})" for x in fermees if x[3] == "abandonne") or "—") + " |")
    a(f"| Projets En cours → Bloqué (au moins une tâche bloquée) | {sum(1 for x in recalcules if x[3] == 'bloque')} | "
      + (", ".join(x[1] for x in recalcules if x[3] == "bloque") or "—") + " |")
    a(f"| Projets Bloqué → En cours (aucune tâche bloquée) | {sum(1 for x in recalcules if x[3] == 'en_cours')} | "
      + (", ".join(x[1] for x in recalcules if x[3] == "en_cours") or "—") + " |")
    a("")
    a("Une tâche fermée ainsi garde sa date de fin Chronos, ou prend la date de clôture du projet. "
      "Les mêmes corrections sont appliquées par la reprise complète (`migrate_from_chronos.py`).\n")

    a("## À traiter par les chefs de projet\n")
    a(f"- **Projets ouverts sans tâche ouverte** (à clore ou à planifier) : {len(prep['sans_tache_ouverte'])} — "
      + (", ".join(prep["sans_tache_ouverte"]) or "aucun") + ".")
    a(f"- **Projets ouverts dont le chef est désactivé** (selon Chronos ; la liste réelle, selon les comptes "
      f"Kairos, est affichée à l'application et dans Admin > Utilisateurs) : {len(prep['chef_inactif_prevus'])} — "
      + (", ".join(prep["chef_inactif_prevus"]) or "aucun") + ".")
    a("")

    a("## Contrôles faits par le SQL au moment de l'application\n")
    a("- Base à jour (`" + MIGRATION_ATTENDUE + "` appliquée, aucune migration plus récente), "
      "toutes les tables classées (effacée / conservée), aucune cascade de `TRUNCATE` vers une "
      "table conservée.")
    a(f"- Les {len(prep['references'])} utilisateurs Chronos référencés (chef, créateur, intervenant) "
      "existent dans Kairos avec le même id et les mêmes nom/prénom (casse, accents et espaces "
      "tolérés, signalés). Sinon : échec, liste des écarts, rien n'est modifié. Ids contrôlés : "
      + ", ".join(str(u["id"]) for u in prep["references"]) + ".")
    a("- Rôles lus dans Kairos au moment de l'application : un **intervenant** RH ou Client est écarté "
      "et compté ; un projet dont le **chef** est RH ou Client est écarté avec ses tâches (comme la "
      "reprise complète) ; aucun échec global. Avec les rôles Chronos : intervenants concernés "
      + (", ".join(map(str, prep["intervenants_rh_client_prevus"])) or "aucun") + " ; projets concernés "
      + (", ".join(map(str, prep["projets_chef_rh_client_prevus"])) or "aucun") + ".")
    a("- Empreinte (nombre de lignes + md5 du contenu) de chaque table conservée identique avant/après.")
    a("")

    a("## Effacé / conservé\n")
    a("- **Effacé puis rechargé** : " + ", ".join(f"`{t}`" for t in TABLES_EFFACEES
                                                   if t in ("projet", "projet_lot", "projet_co_chef",
                                                            "projet_intervenant", "tache", "tache_intervenant")) + ".")
    a("- **Effacé, laissé vide** : " + ", ".join(f"`{t}`" for t in TABLES_EFFACEES
                                                 if t not in ("projet", "projet_lot", "projet_co_chef",
                                                              "projet_intervenant", "tache", "tache_intervenant")) + ".")
    a("- **Conservé à l'identique** : " + ", ".join(f"`{t}`" for t in TABLES_CONSERVEES) + " (le journal "
      "d'audit reçoit une seule ligne `recharge_chronos` de synthèse ; ses triggers sont coupés pendant "
      "les insertions, puis réactivés dans la même transaction).")
    a("")

    a("## À savoir\n")
    a("- **Pièces jointes** : les lignes en base sont effacées, pas les fichiers. Tout le contenu des "
      "dossiers `taches/` et `posts/` du volume `kairos_uploads` devient orphelin (les `avatars/` "
      "restent utilisés). Inoffensif ; suppression facultative, après sauvegarde.")
    a("- **Journal d'audit** : les anciennes lignes restent ; celles d'un projet ou d'une tâche créé "
      "pendant les tests peuvent porter un id désormais repris par un projet Chronos plus récent "
      "(compteur « Journal : … » du récapitulatif).")
    a(f"- **Équipe des projets** : celle du chef de projet dans Kairos, à défaut **{EQUIPE_PAR_DEFAUT}** "
      "(Chronos n'en a pas ; lot 11, migration 0016) — toute l'équipe voit ses projets.")
    a("- `tache.created_by` = chef du projet ; `type_deadline` = `rendu_client` ; client = `IPCO` "
      "(valeurs par défaut, comme la reprise complète).")
    a("- Heures et requêtes Chronos non reprises : Daily log et fils d'activité repartent vides.")
    a("")
    return "\n".join(lignes)


# =====================================================================
# Orchestration
# =====================================================================

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dump", type=Path, help="Export mysqldump de Chronos")
    jour = datetime.now().strftime("%Y-%m-%d")
    ap.add_argument("--sql", type=Path, default=None,
                    help=f"Fichier SQL produit (défaut : recharge_chronos_{jour}.sql à côté du dump)")
    ap.add_argument("--rapport", type=Path, default=None,
                    help="Rapport .md (défaut : même nom que le SQL, extension .md)")
    args = ap.parse_args(argv)
    if not args.dump.exists():
        print(f"Fichier introuvable : {args.dump}", file=sys.stderr)
        return 1
    sql_path = args.sql or args.dump.parent / f"recharge_chronos_{jour}.sql"
    rapport_path = args.rapport or sql_path.with_suffix(".md")

    os.umask(0o077)  # données réelles
    _, data = load_dump(str(args.dump))
    prep = preparer(data)
    sql_path.write_text(generer_sql(prep, args.dump.name), encoding="utf-8")
    rapport_path.write_text(generer_rapport(prep, args.dump.name, sql_path.name), encoding="utf-8")
    print(f"Projets : {len(prep['projets'])}, tâches : {len(prep['taches'])}, "
          f"intervenants : {len(prep['projet_intervenant'])} (projet) + {len(prep['tache_intervenant'])} (tâche), "
          f"lots : {len(prep['projet_lots'])}")
    print(f"SQL : {sql_path}\nRapport : {rapport_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

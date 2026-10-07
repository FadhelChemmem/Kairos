"""scripts/recharger_projets_chronos.py : générateur (données fictives, sans
base) puis, avec KAIROS_TEST_DATABASE_URL et psql, scénario complet sur un
vrai PostgreSQL :

  base « reprise complète » (schema.sql + migrate_from_chronos.py) ->
  essais du gérant (comptes modifiés, projet, posts, Daily log…) ->
  rechargement -> utilisateurs identiques, données métier = dump ->
  rechargement rejoué -> échecs propres (utilisateur renommé ou supprimé,
  base pas au lot 10).

Export Chronos utilisé : tests/fixtures_chronos/mini_dump.sql (synthétique),
ou KAIROS_RECHARGE_DUMP pour rejouer le même scénario sur un vrai export
(jamais versionné)."""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "scripts"))

import recharger_projets_chronos as rch  # noqa: E402
from migrate_from_chronos import build_utilisateurs  # noqa: E402

MINI_DUMP = RACINE / "tests" / "fixtures_chronos" / "mini_dump.sql"


def _donnees_fictives():
    """Export Chronos minimal, en mémoire (aucune donnée réelle)."""
    profil = dict(poste=None, phone=None, image=None, address=None, hireDate=None,
                  createdAt="2024-01-01 08:00:00", updatedAt="2024-01-01 08:00:00")
    users = [dict(id=i, email=f"u{i}@exemple.tn", password=None, role=r, isSuperUser=int(i == 1), token=None,
                  active=1, isBanned=0, createdAt="2024-01-01 08:00:00", updatedAt="2024-01-01 08:00:00")
             for i, r in ((1, "superuser"), (2, "Chef_projet"), (3, "Chef_projet"), (4, "intervenant"), (9, "client"))]
    profils = [dict(profil, id=i, userID=i, name=n, lastName=p)
               for i, n, p in ((1, "Admin", "Un"), (2, "Chef", "Deux"), (3, "Chef", "Trois"),
                               (4, "Inter", "Quatre"), (9, "Client", "Neuf"))]
    projet = dict(customId=None, startDate="2025-01-01 00:00:00", dueDate=None, createdBy=1, state="doing",
                  createdAt="2025-01-01 08:00:00", updatedAt="2025-01-02 08:00:00", phaseID=1, prevPhase=None)
    return {
        "users": users, "UserProfiles": profils,
        "phases": [{"id": 1, "name": "EXE"}], "lots": [{"id": 1, "name": "Charpente Métallique"}],
        "projects": [dict(projet, id=10, code="A", customId="99010X_l'atelier", name="L'atelier", manager=2),
                     dict(projet, id=11, code="B", customId="99011X_suite", name="Suite", manager=3, prevPhase=10)],
        "projectLots": [{"projectID": 10, "lotID": 1}, {"projectID": 10, "lotID": 1}],
        "tasks": [dict(id=100, name="Note d'hypothèses", startDate="2025-02-01 00:00:00",
                       dueDate="2025-03-01 00:00:00", doneDate=None, isVerified=0, state="doing",
                       meta='{"projectID":10}', createdAt="2025-02-01 08:00:00", updatedAt="2025-02-01 08:00:00")],
        "intervenants": [
            dict(id=1, intervenantID=4, projectID=10, taskID=None),
            dict(id=2, intervenantID=3, projectID=10, taskID=100),
            dict(id=3, intervenantID=None, projectID=10, taskID=100),
            dict(id=4, intervenantID=4, projectID=10, taskID=None),
        ],
        "interventionHours": [{"id": 1, "hours": 8, "date": "2025-02-03", "interventionID": 1, "projectID": 10}],
        "requests": [{"id": 1, "description": "x", "projectID": 10, "creatorID": 4}],
    }


def _tables_du_schema():
    return set(re.findall(r"^CREATE TABLE (?:IF NOT EXISTS )?(\w+) \(", (RACINE / "schema.sql").read_text(encoding="utf-8"),
                          re.M))


def _references_du_schema():
    """{(table qui référence, table référencée)} d'après schema.sql."""
    texte = (RACINE / "schema.sql").read_text(encoding="utf-8")
    liens = set()
    for m in re.finditer(r"^CREATE TABLE (?:IF NOT EXISTS )?(\w+) \((.*?)\n\);", texte, re.S | re.M):
        for cible in re.findall(r"REFERENCES (\w+)", m.group(2)):
            liens.add((m.group(1), cible))
    for source, cible in re.findall(r"ALTER TABLE (\w+) ADD CONSTRAINT \w+\s+FOREIGN KEY [^;]*?REFERENCES (\w+)", texte):
        liens.add((source, cible))
    return liens


class TestPreparation(unittest.TestCase):
    def setUp(self):
        self.prep = rch.preparer(_donnees_fictives())

    def test_meme_transformation_que_la_reprise_complete(self):
        p = {x["id"]: x for x in self.prep["projets"]}
        self.assertEqual(sorted(p), [10, 11])
        self.assertEqual(p[10]["code"], "99010X")
        self.assertEqual(self.prep["lien"], {11: 10})
        self.assertEqual(self.prep["projet_lots"], [(10, "CM")])  # doublon du dump fusionné
        self.assertEqual([t["id"] for t in self.prep["taches"]], [100])
        self.assertEqual(self.prep["projet_intervenant"], [(10, 4)])
        self.assertEqual(self.prep["tache_intervenant"], [(100, 3)])

    def test_utilisateurs_references_et_leurs_usages(self):
        refs = {u["id"]: u for u in self.prep["references"]}
        self.assertEqual(sorted(refs), [1, 2, 3, 4])  # le Client 9 n'est référencé nulle part
        self.assertEqual((refs[2]["nom"], refs[2]["prenom"]), ("Chef", "Deux"))
        self.assertEqual(refs[1]["usages"], "créateur de projet")
        self.assertEqual(refs[3]["usages"], "chef de projet, intervenant de tâche")

    def test_comptages_du_rapport(self):
        s = self.prep["stats_intervenants"]
        self.assertEqual((s["sans_personne"], s["retenues"], s["doublons"]), (1, 3, 1))
        self.assertEqual(self.prep["co_chefs_prevus"], 1)  # chef 3 intervenant d'une tâche du projet 10

    def test_aucun_mot_de_passe_genere(self):
        report = rch._rapport_vide()
        utilisateurs, identifiants, _ = build_utilisateurs(_donnees_fictives(), "kairos.tn", report,
                                                           generer_mots_de_passe=False)
        self.assertTrue(all(u["mot_de_passe_hash"] is None for u in utilisateurs))
        self.assertTrue(all(c[4] is None for c in identifiants))


class TestSqlGenere(unittest.TestCase):
    def setUp(self):
        self.sql = rch.generer_sql(rch.preparer(_donnees_fictives()), "fictif.sql")

    def test_une_seule_transaction_qui_s_arrete_a_la_premiere_erreur(self):
        lignes = [l for l in self.sql.splitlines() if l and not l.startswith("--")]
        self.assertEqual(lignes[0], "\\set ON_ERROR_STOP on")
        self.assertEqual(self.sql.count("\nBEGIN;"), 1)
        self.assertEqual(lignes[-1], "COMMIT;")
        self.assertEqual(self.sql.count("COMMIT;"), 1)
        self.assertIn("SET LOCAL kairos.reprise_historique = 'on';", self.sql)
        self.assertIn("SET LOCAL app.current_user_id = '';", self.sql)

    def test_controle_du_lot_10_avant_toute_ecriture(self):
        controle = self.sql.index(f"version = '{rch.MIGRATION_ATTENDUE}'")
        self.assertLess(controle, self.sql.index("TRUNCATE TABLE "))
        self.assertLess(self.sql.index("absent de Kairos"), self.sql.index("TRUNCATE TABLE "))
        self.assertIn("RAISE EXCEPTION 'Rechargement annulé : la base n''est pas au lot 10", self.sql)

    def test_truncate_exactement_les_tables_metier(self):
        (ligne,) = [l for l in self.sql.splitlines() if l.startswith("TRUNCATE")]
        tables = re.match(r"TRUNCATE TABLE (.*) RESTART IDENTITY CASCADE;$", ligne).group(1).split(", ")
        self.assertEqual(set(tables), set(rch.TABLES_EFFACEES))
        for protegee in ("utilisateur", "utilisateur_session", "equipe", "lot", "audit_log", "dailylog_preference"):
            self.assertNotIn(protegee, tables)

    def test_triggers_d_audit_coupes_puis_retablis(self):
        truncate, commit = self.sql.index("TRUNCATE TABLE "), self.sql.index("COMMIT;")
        for table, trigger in rch.TRIGGERS_AUDIT:
            coupe = self.sql.index(f"ALTER TABLE {table} DISABLE TRIGGER {trigger};")
            retabli = self.sql.index(f"ALTER TABLE {table} ENABLE TRIGGER {trigger};")
            self.assertLess(coupe, truncate)
            self.assertLess(truncate, retabli)
            self.assertLess(retabli, commit)
        self.assertNotIn("session_replication_role", self.sql)  # garderait aussi les co-chefs et les FK hors jeu

    def test_ni_comptes_ni_heures_ni_requetes(self):
        for interdit in ("INSERT INTO utilisateur", "UPDATE utilisateur", "DELETE FROM utilisateur",
                         "INSERT INTO dailylog_entree", "INSERT INTO post ", "INSERT INTO post(",
                         "INSERT INTO projet_co_chef"):
            self.assertNotIn(interdit, self.sql)
        self.assertEqual(self.sql.count("INSERT INTO audit_log"), 1)

    def test_donnees_echappees_et_id_chronos(self):
        self.assertIn("(10, '99010X', 'L''atelier', 'EXE'", self.sql)
        self.assertIn("'Note d''hypothèses'", self.sql)
        self.assertIn("(11, '99011X', 'Suite', 'EXE', '2025-01-01', NULL, NULL, 'en_cours', 3, 10, 1,", self.sql)
        self.assertIn("(1, 'Admin', 'Un', 'créateur de projet')", self.sql)

    def test_sequences_reajustees(self):
        self.assertIn("setval(pg_get_serial_sequence('projet', 'id')", self.sql)
        self.assertIn("setval(pg_get_serial_sequence('tache', 'id')", self.sql)

    def test_grand_volume_decoupe_en_lots(self):
        data = _donnees_fictives()
        modele = data["tasks"][0]
        data["tasks"] = [dict(modele, id=1000 + i) for i in range(rch.TAILLE_LOT + 1)]
        sql = rch.generer_sql(rch.preparer(data), "fictif.sql")
        self.assertEqual(sql.count("INSERT INTO rch_tache ("), 2)


class TestSchemaCouvert(unittest.TestCase):
    """Le SQL refuse aussi, en base, une table non classée ou une cascade
    vers une table conservée ; ces tests le signalent dès la CI."""

    def test_toutes_les_tables_sont_classees(self):
        self.assertEqual(set(rch.TABLES_EFFACEES) | set(rch.TABLES_CONSERVEES), _tables_du_schema())
        self.assertFalse(set(rch.TABLES_EFFACEES) & set(rch.TABLES_CONSERVEES))

    def test_aucune_table_conservee_ne_reference_une_table_effacee(self):
        fautifs = {(s, c) for s, c in _references_du_schema()
                   if c in rch.TABLES_EFFACEES and s not in rch.TABLES_EFFACEES}
        self.assertEqual(fautifs, set())

    def test_triggers_d_audit_existent(self):
        schema = (RACINE / "schema.sql").read_text(encoding="utf-8")
        for table, trigger in rch.TRIGGERS_AUDIT:
            self.assertIn(f"CREATE TRIGGER {trigger} AFTER INSERT OR UPDATE OR DELETE ON {table} ", schema)

    def test_migration_attendue_est_la_derniere(self):
        dernieres = sorted(p.stem for p in (RACINE / "migrations").glob("*.sql"))
        self.assertEqual(dernieres[-1], rch.MIGRATION_ATTENDUE)


class TestRapportEtFichiers(unittest.TestCase):
    def test_rapport(self):
        rapport = rch.generer_rapport(rch.preparer(_donnees_fictives()), "fictif.sql", "r.sql")
        self.assertIn("| Projets | 2 | 2 |", rapport)
        self.assertIn("| Heures (`interventionHours`) | 1 | 0 (non reprises", rapport)
        self.assertIn("| Lignes `intervenants` en double | 1 | fusionnées |", rapport)
        self.assertIn("pièces jointes", rapport.lower())

    def test_main_ecrit_sql_et_rapport_prives(self):
        dossier = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        ancien = os.umask(0o022)
        self.addCleanup(os.umask, ancien)
        self.assertEqual(rch.main([str(MINI_DUMP), "--sql", str(dossier / "r.sql")]), 0)
        for nom in ("r.sql", "r.md"):
            self.assertEqual(stat.S_IMODE((dossier / nom).stat().st_mode), 0o600)
        self.assertIn("COMMIT;", (dossier / "r.sql").read_text(encoding="utf-8"))


# =====================================================================
# Scénario sur vrai PostgreSQL
# =====================================================================

def _env_pg():
    from urllib.parse import urlsplit
    u = urlsplit(os.environ["KAIROS_TEST_DATABASE_URL"])
    return dict(os.environ, PGHOST=u.hostname or "127.0.0.1", PGPORT=str(u.port or 5432),
                PGUSER=u.username or "", PGPASSWORD=u.password or os.environ.get("PGPASSWORD", ""),
                PGTZ="Africa/Tunis")


@unittest.skipUnless(os.environ.get("KAIROS_TEST_DATABASE_URL") and shutil.which("psql"),
                     "KAIROS_TEST_DATABASE_URL et psql requis")
class TestRechargementSurPostgres(unittest.TestCase):
    TABLES_COMPAREES = {
        "projet": "SELECT * FROM projet ORDER BY id",
        "projet_lot": "SELECT * FROM projet_lot ORDER BY 1, 2",
        "tache": "SELECT * FROM tache ORDER BY id",
    }

    @classmethod
    def setUpClass(cls):
        cls.env = _env_pg()
        cls.dump = Path(os.environ.get("KAIROS_RECHARGE_DUMP") or MINI_DUMP)
        cls.dossier = Path(tempfile.mkdtemp(prefix="kairos_recharge_"))
        os.chmod(cls.dossier, 0o700)
        cls.prefixe = f"kairos_t_rch_{uuid.uuid4().hex[:8]}"
        cls.bases = []
        # Base « reprise complète » (ce qu'a chargé le gérant le 21/09).
        r = subprocess.run([sys.executable, str(RACINE / "scripts" / "migrate_from_chronos.py"), str(cls.dump),
                            "--out-dir", str(cls.dossier / "complete")], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        cls.modele = cls.nouvelle_base("modele")
        cls.psql_ok(cls.modele, "-f", str(RACINE / "schema.sql"))
        cls.psql_ok(cls.modele, "-f", str(cls.dossier / "complete" / "migration.sql"))
        cls.sql_recharge = cls.dossier / "recharge.sql"
        assert rch.main([str(cls.dump), "--sql", str(cls.sql_recharge)]) == 0

    @classmethod
    def tearDownClass(cls):
        for base in cls.bases:
            cls.psql("postgres", "-c", f"DROP DATABASE IF EXISTS {base}")
        shutil.rmtree(cls.dossier, ignore_errors=True)

    # --- outils ---------------------------------------------------------
    @classmethod
    def psql(cls, base, *args, entree=None):
        return subprocess.run(["psql", "-X", "-Atq", "-v", "ON_ERROR_STOP=1", "-d", base, *args],
                              env=cls.env, capture_output=True, text=True, input=entree)

    @classmethod
    def psql_ok(cls, base, *args, entree=None):
        r = cls.psql(base, *args, entree=entree)
        assert r.returncode == 0, r.stderr[-3000:]
        return r.stdout

    @classmethod
    def nouvelle_base(cls, nom, modele=None):
        base = f"{cls.prefixe}_{nom}"
        gabarit = f" TEMPLATE {modele}" if modele else ""
        cls.psql_ok("postgres", "-c", f"CREATE DATABASE {base}{gabarit}")
        cls.bases.append(base)
        return base

    def valeur(self, base, sql):
        return self.psql_ok(base, "-c", sql).strip()

    def contenu(self, base, sql):
        return self.psql_ok(base, "-c", f"COPY ({sql}) TO STDOUT")

    def recharger(self, base):
        # Exactement comme le gérant : entrée standard, sans -q ni -A.
        return subprocess.run(["psql", "-X", "-v", "ON_ERROR_STOP=1", "-d", base],
                              env=self.env, capture_output=True, text=True,
                              input=self.sql_recharge.read_text(encoding="utf-8"))

    def instantane_comptes(self, base):
        return {t: self.contenu(base, f"SELECT * FROM {t} ORDER BY 1")
                for t in ("utilisateur", "utilisateur_session", "dailylog_preference", "equipe", "lot",
                          "post_type", "reaction_type", "tentative_securite", "schema_migrations")}

    def co_chefs_selon_la_regle(self, base):
        """Règle du lot 10 (rattrapage de la migration 0013) sur les rôles actuels."""
        return self.contenu(base, """
            SELECT pi.projet_id, pi.utilisateur_id FROM projet_intervenant pi
            JOIN utilisateur u ON u.id = pi.utilisateur_id JOIN projet p ON p.id = pi.projet_id
            WHERE u.role = 'chef_de_projet' AND p.chef_projet_id <> u.id
            UNION
            SELECT t.projet_id, ti.utilisateur_id FROM tache_intervenant ti JOIN tache t ON t.id = ti.tache_id
            JOIN utilisateur u ON u.id = ti.utilisateur_id JOIN projet p ON p.id = t.projet_id
            WHERE u.role = 'chef_de_projet' AND p.chef_projet_id <> u.id
            ORDER BY 1, 2""")

    def essais_du_gerant(self, base):
        """Ce que le gérant a pu faire depuis la reprise : retourne (id promu chef,
        id passé Client, id du compte ajouté)."""
        admin = int(self.valeur(base, "SELECT min(id) FROM utilisateur WHERE role = 'admin' AND actif"))
        promu = int(self.valeur(base, """
            SELECT min(u.id) FROM utilisateur u WHERE u.role = 'intervenant'
            AND EXISTS (SELECT 1 FROM tache_intervenant ti WHERE ti.utilisateur_id = u.id)"""))
        client = int(self.valeur(base, f"""
            SELECT max(u.id) FROM utilisateur u WHERE u.role = 'intervenant' AND u.id <> {promu}
            AND EXISTS (SELECT 1 FROM projet_intervenant pi WHERE pi.utilisateur_id = u.id)"""))
        chef = int(self.valeur(base, "SELECT chef_projet_id FROM projet ORDER BY id LIMIT 1"))
        self.psql_ok(base, entree=f"""
            BEGIN;
            SET LOCAL app.current_user_id = '{admin}';
            UPDATE utilisateur SET email = 'essai.' || id || '@midgard.tn', mot_de_passe_hash = 'pbkdf2:essai',
                   fuseau = 'America/Cayenne', equipe_code = 'MIDGARD' WHERE id = {chef};
            UPDATE utilisateur SET role = 'chef_de_projet' WHERE id = {promu};
            DELETE FROM tache_intervenant WHERE utilisateur_id = {client};
            DELETE FROM projet_intervenant WHERE utilisateur_id = {client};
            UPDATE utilisateur SET role = 'client' WHERE id = {client};
            INSERT INTO utilisateur (email, mot_de_passe_hash, nom, prenom, role)
              VALUES ('nouveau.compte@midgard.tn', 'pbkdf2:x', 'Compte', 'Nouveau', 'intervenant');
            INSERT INTO utilisateur_session (utilisateur_id, generation) VALUES ({chef}, 3);
            INSERT INTO dailylog_preference (utilisateur_id, objectif_minutes) VALUES ({chef}, 420);
            COMMIT;
            BEGIN;
            SET LOCAL app.current_user_id = '{chef}';
            INSERT INTO projet (code, nom, phase, chef_projet_id, created_by) VALUES ('ESSAI1X', 'Essai', 'EXE', {chef}, {chef});
            INSERT INTO tache (projet_id, titre, created_by) SELECT max(id), 'Tâche essai', {chef} FROM projet;
            INSERT INTO tache_piece_jointe (tache_id, nom_fichier, chemin, uploaded_by)
              SELECT max(id), 'plan.pdf', 'taches/0/x.pdf', {chef} FROM tache;
            INSERT INTO post (projet_id, auteur_id, type_code, contenu) SELECT max(id), {chef}, 'envoi', 'essai' FROM projet;
            INSERT INTO post_piece_jointe (post_id, nom_fichier, chemin) SELECT max(id), 'a.pdf', 'posts/x.pdf' FROM post;
            INSERT INTO post_commentaire (post_id, auteur_id, contenu) SELECT max(id), {chef}, 'ok' FROM post;
            INSERT INTO post_reaction (post_id, utilisateur_id, reaction_code)
              SELECT max(id), {chef}, (SELECT min(code) FROM reaction_type) FROM post;
            INSERT INTO notification (utilisateur_id, categorie, message) VALUES ({chef}, 'projet', 'essai');
            INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures)
              SELECT {chef}, (now() AT TIME ZONE 'America/Cayenne')::date, max(id), 2 FROM projet;
            INSERT INTO dailylog_jour (utilisateur_id, date) VALUES ({chef}, (now() AT TIME ZONE 'America/Cayenne')::date - 1);
            COMMIT;""")
        return promu, client

    # --- scénarios --------------------------------------------------------
    def test_rechargement_garde_les_comptes_et_recharge_le_dump(self):
        reference = self.nouvelle_base("reference", self.modele)  # reprise complète intacte
        base = self.nouvelle_base("gerant", self.modele)
        _promu, client = self.essais_du_gerant(base)
        comptes = self.instantane_comptes(base)
        audit_avant = self.contenu(base, "SELECT * FROM audit_log ORDER BY id")
        self.assertNotEqual(self.contenu(base, "SELECT id FROM projet ORDER BY 1"),
                            self.contenu(reference, "SELECT id FROM projet ORDER BY 1"))

        r = self.recharger(base)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        self.assertIn("Rechargement Chronos", r.stdout)
        self.assertIn("Projets chargés", r.stdout)

        # Comptes (toutes colonnes) et tables conservées strictement identiques.
        self.assertEqual(self.instantane_comptes(base), comptes)
        audit_apres = self.contenu(base, "SELECT * FROM audit_log ORDER BY id")
        self.assertTrue(audit_apres.startswith(audit_avant))
        self.assertEqual(self.valeur(base, "SELECT count(*) FROM audit_log") ,
                         str(len(audit_avant.splitlines()) + 1))
        self.assertEqual(self.valeur(base, "SELECT table_cible FROM audit_log ORDER BY id DESC LIMIT 1"),
                         "recharge_chronos")

        # Données métier = celles de la reprise complète du même dump.
        for table, sql in self.TABLES_COMPAREES.items():
            self.assertEqual(self.contenu(base, sql), self.contenu(reference, sql), table)
        for table, cle in (("projet_intervenant", "projet_id, utilisateur_id"),
                           ("tache_intervenant", "tache_id, utilisateur_id")):
            attendu = self.contenu(reference, f"SELECT {cle} FROM {table} WHERE utilisateur_id <> {client} ORDER BY 1, 2")
            self.assertEqual(self.contenu(base, f"SELECT {cle} FROM {table} ORDER BY 1, 2"), attendu, table)
        ecartes = int(self.valeur(reference, f"""SELECT (SELECT count(*) FROM projet_intervenant WHERE utilisateur_id = {client})
                                                + (SELECT count(*) FROM tache_intervenant WHERE utilisateur_id = {client})"""))
        self.assertGreater(ecartes, 0)
        self.assertRegex(r.stdout, r"Intervenants de projet écartés \(RH/Client\)\s*\|\s*[1-9]")
        self.assertIn(f"id {client} (client)", r.stderr)
        # Co-chefs : règle du lot 10 sur les rôles ACTUELS (le promu en gagne).
        self.assertEqual(self.contenu(base, "SELECT projet_id, utilisateur_id FROM projet_co_chef ORDER BY 1, 2"),
                         self.co_chefs_selon_la_regle(base))
        self.assertNotEqual(self.contenu(base, "SELECT projet_id, utilisateur_id FROM projet_co_chef ORDER BY 1, 2"),
                            self.contenu(reference, "SELECT projet_id, utilisateur_id FROM projet_co_chef ORDER BY 1, 2"))
        for vide in ("post", "post_commentaire", "post_reaction", "post_piece_jointe", "tache_piece_jointe",
                     "notification", "dailylog_entree", "dailylog_jour"):
            self.assertEqual(self.valeur(base, f"SELECT count(*) FROM {vide}"), "0", vide)
        # Séquences : le prochain projet / la prochaine tâche ne heurte aucun id Chronos.
        self.assertEqual(self.valeur(base, "SELECT nextval('projet_id_seq') = max(id) + 1 FROM projet"), "t")
        self.assertEqual(self.valeur(base, "SELECT nextval('tache_id_seq') = max(id) + 1 FROM tache"), "t")
        self.assertEqual(self.valeur(base, "SELECT nextval('post_id_seq')"), "1")
        # Triggers d'audit bien réactivés.
        self.assertEqual(self.valeur(base, """SELECT count(*) FROM pg_trigger
                                              WHERE tgname LIKE 'trg_audit_%' AND tgenabled = 'D'"""), "0")

        # Rejoué une deuxième fois : même résultat, aucune erreur.
        metier = {t: self.contenu(base, sql) for t, sql in self.TABLES_COMPAREES.items()}
        co_chefs = self.contenu(base, "SELECT projet_id, utilisateur_id FROM projet_co_chef ORDER BY 1, 2")
        r = self.recharger(base)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        self.assertEqual(self.instantane_comptes(base), comptes)
        self.assertEqual({t: self.contenu(base, sql) for t, sql in self.TABLES_COMPAREES.items()}, metier)
        self.assertEqual(self.contenu(base, "SELECT projet_id, utilisateur_id FROM projet_co_chef ORDER BY 1, 2"), co_chefs)

    def _echec_sans_rien_modifier(self, base, attendu):
        avant = {t: self.contenu(base, f"SELECT * FROM {t} ORDER BY 1")
                 for t in ("utilisateur", "projet", "tache", "post", "audit_log")}
        r = self.recharger(base)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(attendu, r.stderr)
        self.assertNotIn("Rechargement Chronos", r.stdout)
        self.assertEqual({t: self.contenu(base, f"SELECT * FROM {t} ORDER BY 1")
                          for t in ("utilisateur", "projet", "tache", "post", "audit_log")}, avant)
        return r.stderr

    def test_echec_propre_si_un_utilisateur_a_ete_renomme(self):
        base = self.nouvelle_base("renomme", self.modele)
        uid = self.valeur(base, "SELECT min(chef_projet_id) FROM projet")
        self.psql_ok(base, "-c", f"UPDATE utilisateur SET nom = 'Autre-Nom' WHERE id = {uid}")
        erreur = self._echec_sans_rien_modifier(base, "nom/prénom différents")
        self.assertIn(f"id {uid} : nom/prénom différents", erreur)
        self.assertIn("Kairos : ", erreur)
        self.assertIn("Rechargement annulé, rien n'a été modifié : 1 utilisateur(s)", erreur)

    def test_casse_et_accents_toleres(self):
        base = self.nouvelle_base("casse", self.modele)
        uid = self.valeur(base, "SELECT min(chef_projet_id) FROM projet")
        self.psql_ok(base, "-c", f"UPDATE utilisateur SET nom = upper(nom) || '  ' WHERE id = {uid}")
        r = self.recharger(base)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        self.assertIn("(tolérés)", r.stderr)

    def test_echec_propre_si_un_utilisateur_a_ete_supprime(self):
        base = self.nouvelle_base("supprime", self.modele)
        uid = self.valeur(base, """SELECT min(utilisateur_id) FROM tache_intervenant ti JOIN utilisateur u
                                   ON u.id = ti.utilisateur_id WHERE u.role <> 'admin'""")
        tables = ", ".join(rch.TABLES_EFFACEES)
        self.psql_ok(base, entree=f"TRUNCATE {tables} CASCADE; DELETE FROM utilisateur WHERE id = {uid};"
                                  "INSERT INTO projet (code, nom, phase, chef_projet_id) "
                                  "SELECT 'TEMOIN', 'Témoin', 'EXE', min(id) FROM utilisateur WHERE role = 'admin';")
        erreur = self._echec_sans_rien_modifier(base, "absent de Kairos")
        self.assertIn(f"id {uid} : absent de Kairos", erreur)

    def test_echec_propre_si_la_base_n_est_pas_au_lot_10(self):
        base = self.nouvelle_base("lot9", self.modele)
        self.psql_ok(base, "-c", f"DELETE FROM schema_migrations WHERE version = '{rch.MIGRATION_ATTENDUE}'")
        self._echec_sans_rien_modifier(base, "pas au lot 10")

    def test_echec_propre_si_une_table_inconnue_apparait(self):
        base = self.nouvelle_base("inconnue", self.modele)
        self.psql_ok(base, "-c", "CREATE TABLE projet_note (projet_id BIGINT REFERENCES projet(id))")
        self._echec_sans_rien_modifier(base, "table(s) inconnue(s) du script : projet_note")


if __name__ == "__main__":
    unittest.main()

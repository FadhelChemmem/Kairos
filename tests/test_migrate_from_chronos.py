"""Tests unitaires purs (aucune base de données, aucun fichier réel) pour
scripts/migrate_from_chronos.py — PROMPT_CORRECTIONS.md P1 #13.

Le script n'est pas un module du package `app` (voir la note "RÉUTILISABLE"
en tête de fichier) : on ajoute `scripts/` à sys.path avant de l'importer,
exactement comme le script le fait lui-même pour mysqldump_parser."""
import os
import shutil
import sys
import unittest
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from migrate_from_chronos import (  # noqa: E402
    RawSQL, build_dailylog, build_intervenants, build_projets, build_taches, build_utilisateurs,
    mysql_date_only, mysql_dt_to_pg, sql_str, sql_val,
)


class TestSqlStr(unittest.TestCase):
    def test_quote_simple_est_doublee(self):
        self.assertEqual(sql_str("l'équipe"), "'l''équipe'")

    def test_antislash_nest_pas_double(self):
        """PROMPT_CORRECTIONS.md P1 #13 : Postgres a
        standard_conforming_strings=on par défaut — un antislash dans un
        littéral '...' standard n'est PAS un caractère d'échappement. Le
        doubler ici produisait deux antislashs réels en base pour un seul
        dans la donnée source (ex. un chemin UNC)."""
        self.assertEqual(sql_str(r"\\NAS\Projets\26099X"), "'\\\\NAS\\Projets\\26099X'")

    def test_none_devient_null(self):
        self.assertEqual(sql_str(None), "NULL")


class TestDatesZeroMysql(unittest.TestCase):
    """MySQL autorise la "date zéro" ('0000-00-00' / '0000-00-00 00:00:00')
    comme valeur invalide/par défaut — sans équivalent Postgres, elle
    faisait échouer l'INSERT/UPDATE à l'import (PROMPT_CORRECTIONS.md P1 #13)."""

    def test_date_zero_devient_none(self):
        self.assertIsNone(mysql_date_only("0000-00-00"))

    def test_datetime_zero_devient_none(self):
        self.assertIsNone(mysql_dt_to_pg("0000-00-00 00:00:00"))

    def test_date_valide_est_conservee(self):
        self.assertEqual(mysql_date_only("2024-04-17"), "2024-04-17")
        self.assertEqual(mysql_dt_to_pg("2024-04-17 09:30:51"), "2024-04-17 09:30:51")

    def test_vide_devient_none(self):
        self.assertIsNone(mysql_date_only(None))
        self.assertIsNone(mysql_date_only(""))


class TestLotsCodesInvalides(unittest.TestCase):
    """`projet_lot.lot_code` est une clé étrangère vers `lot.code` (schema.sql,
    ex. "GO"), pas vers le libellé complet de l'ancien Kairos ("Gros Œuvre")
    — insérer ce libellé tel quel violait systématiquement la contrainte FK
    à l'import (PROMPT_CORRECTIONS.md P1 #13)."""

    def _data_minimale(self, lots, project_lots):
        return {
            "projects": [{
                "id": 1, "customId": "26099X_tour", "code": None, "phaseID": 10,
                "manager": 1, "state": "doing", "startDate": None, "dueDate": None,
                "createdBy": 1, "createdAt": None, "updatedAt": None,
                "prevPhase": None, "name": "Tour Meridian",
            }],
            "phases": [{"id": 10, "name": "EXE"}],
            "lots": lots,
            "projectLots": project_lots,
        }

    def test_libelle_reconnu_est_traduit_en_code_court(self):
        data = self._data_minimale(
            lots=[{"id": 5, "name": "Gros Œuvre"}],
            project_lots=[{"projectID": 1, "lotID": 5}],
        )
        report = defaultdict(list)
        _projets, projet_lots, _liens, _ids = build_projets(data, {1}, report)
        self.assertEqual(projet_lots, [(1, "GO")])
        self.assertEqual(report["lots_non_reconnus"], [])

    def test_code_court_deja_present_est_conserve_tel_quel(self):
        """Le nom du lot dans l'ancien Kairos peut déjà être un code court
        ("GO") plutôt que le libellé complet — les deux formes doivent être
        reconnues."""
        data = self._data_minimale(
            lots=[{"id": 5, "name": "go"}],
            project_lots=[{"projectID": 1, "lotID": 5}],
        )
        report = defaultdict(list)
        _projets, projet_lots, _liens, _ids = build_projets(data, {1}, report)
        self.assertEqual(projet_lots, [(1, "GO")])
        self.assertEqual(report["lots_non_reconnus"], [])

    def test_libelle_non_reconnu_est_ignore_et_signale(self):
        data = self._data_minimale(
            lots=[{"id": 5, "name": "Plomberie"}],
            project_lots=[{"projectID": 1, "lotID": 5}],
        )
        report = defaultdict(list)
        _projets, projet_lots, _liens, _ids = build_projets(data, {1}, report)
        self.assertEqual(projet_lots, [])
        self.assertEqual(report["lots_non_reconnus"], [(1, "Plomberie")])


class TestSqlValRawSQL(unittest.TestCase):
    """Audit sécurité/qualité externe, 2026-09-28, item P0-1 : `sql_val()`
    quotait `"now()"` comme n'importe quelle chaîne (`'now()'`, un littéral
    de timestamp invalide en Postgres) au lieu d'émettre l'expression SQL
    now(). RawSQL est le marqueur qui distingue les deux cas."""

    def test_rawsql_est_emis_sans_guillemets(self):
        self.assertEqual(sql_val(RawSQL("now()")), "now()")

    def test_chaine_normale_reste_quotee(self):
        # Non-régression : une vraie chaîne (même valant littéralement
        # "now()") doit rester quotée — seul le marqueur RawSQL change de
        # comportement.
        self.assertEqual(sql_val("now()"), "'now()'")

    def test_date_manquante_devient_rawsql_now(self):
        """Les quatre points d'émission (utilisateurs, projets, tâches,
        requêtes) partagent le motif `mysql_dt_to_pg(...) or RawSQL("now()")`."""
        created_at = mysql_dt_to_pg(None) or RawSQL("now()")
        self.assertIsInstance(created_at, RawSQL)
        self.assertEqual(sql_val(created_at), "now()")


class TestDailyLogHeuresPlafonnees(unittest.TestCase):
    """Audit sécurité/qualité externe, 2026-09-28, item P0-2 : au-delà de
    99.99 (borne NUMERIC(4,2), l'ancien plafond), la valeur violait déjà la
    vraie contrainte métier (`dailylog_entree_heures_valides : heures <= 24`,
    schema.sql) bien avant d'atteindre 99.99 — le plafond doit être 24."""

    def _data(self, heures_par_jour):
        return {
            "intervenants": [{"id": 1, "intervenantID": 7, "taskID": None, "projectID": 1}],
            "interventionHours": [
                {"interventionID": 1, "date": "2026-09-01", "hours": h} for h in heures_par_jour
            ],
        }

    def test_total_sous_24h_non_plafonne(self):
        report = defaultdict(list)
        lignes = build_dailylog(self._data([10, 5]), {7}, {1}, set(), report)
        self.assertEqual(lignes[0]["heures"], 15)
        self.assertEqual(report["dailylog_heures_plafonnees"], [])

    def test_total_au_dela_de_24h_plafonne_a_24_et_signale(self):
        report = defaultdict(list)
        lignes = build_dailylog(self._data([20, 10]), {7}, {1}, set(), report)
        self.assertEqual(lignes[0]["heures"], 24)
        self.assertEqual(len(report["dailylog_heures_plafonnees"]), 1)
        uid, date, projet_id, tache_id, heures_avant = report["dailylog_heures_plafonnees"][0]
        self.assertEqual((uid, date, projet_id, tache_id), (7, "2026-09-01", 1, None))
        self.assertEqual(heures_avant, 30)


class TestComptesRH(unittest.TestCase):
    """Audit n°2 : un RH chef de projet, un RH intervenant ou un second RH
    actif faisaient échouer tout le chargement de migration.sql (triggers
    RH et index idx_utilisateur_rh_singleton du nouveau schéma)."""

    @staticmethod
    def _utilisateur(uid, role):
        return {"id": uid, "role": role, "isSuperUser": False, "active": 1, "isBanned": 0,
                "email": f"u{uid}@x.tn", "createdAt": None, "updatedAt": None}

    def test_second_rh_actif_importe_comme_intervenant(self):
        data = {
            "users": [self._utilisateur(1, "ressource_humaine"), self._utilisateur(2, "ressource_humaine")],
            "UserProfiles": [],
        }
        report = defaultdict(list)
        utilisateurs, _creds, _ids = build_utilisateurs(data, "kairos.tn", report)
        self.assertEqual([u["role"] for u in utilisateurs], ["rh", "intervenant"])
        self.assertEqual(report["rh_supplementaires_retrogrades"], [2])

    def test_projet_dirige_par_un_rh_non_importe_et_signale(self):
        data = TestLotsCodesInvalides._data_minimale(None, lots=[], project_lots=[])
        report = defaultdict(list)
        projets, _lots, _liens, ids = build_projets(data, {1}, report, rh_ids=frozenset({1}))
        self.assertEqual(projets, [])
        self.assertEqual(report["projets_manager_rh"], [(1, 1)])

    def test_rh_intervenant_ignore_et_signale(self):
        data = {"intervenants": [
            {"id": 1, "intervenantID": 7, "taskID": None, "projectID": 1},
            {"id": 2, "intervenantID": 8, "taskID": None, "projectID": 1},
        ]}
        report = defaultdict(list)
        projet_iv, _tache_iv = build_intervenants(data, {7, 8}, {1}, set(), report, rh_ids=frozenset({7}))
        self.assertEqual(projet_iv, [(1, 8)])
        self.assertEqual(report["intervenants_rh_ignores"], [7])


class TestRepriseLot10(unittest.TestCase):
    """Audit données lot 10 : B1 (dates incohérentes rejetées par les
    triggers de 0012 -> tout le chargement échouait), I6 (heures sans
    personne), I7 (projets clos sans date de clôture)."""

    @staticmethod
    def _projet(pid, state, debut, fin, maj="2025-05-10 08:00:00"):
        return {"id": pid, "customId": f"2600{pid}X_P", "code": None, "phaseID": 10, "manager": 1,
                "state": state, "startDate": debut, "dueDate": fin, "createdBy": 1,
                "createdAt": "2025-01-01 08:00:00", "updatedAt": maj, "prevPhase": None, "name": "P"}

    def test_fin_avant_debut_effacee_et_cloture_posee(self):
        data = {"projects": [self._projet(1, "done", "2025-03-01 00:00:00", "2025-02-01 00:00:00"),
                             self._projet(2, "done", "2025-01-01 00:00:00", "2025-02-01 00:00:00")],
                "phases": [{"id": 10, "name": "EXE"}], "lots": [], "projectLots": []}
        report = defaultdict(list)
        projets, _l, _p, _ids = build_projets(data, {1}, report)
        par_id = {p["id"]: p for p in projets}
        self.assertIsNone(par_id[1]["date_fin"])
        self.assertEqual(par_id[1]["date_cloture"], "2025-05-10")
        self.assertEqual(par_id[2]["date_cloture"], "2025-02-01")
        self.assertEqual(report["projets_date_fin_effacee"], [(1, "2025-03-01", "2025-02-01")])

    def test_echeance_avant_debut_effacee(self):
        data = {"intervenants": [], "tasks": [{
            "id": 7, "name": "T", "startDate": "2025-02-01 00:00:00", "dueDate": "2025-01-15 00:00:00",
            "doneDate": None, "isVerified": 0, "state": "doing", "meta": '{"projectID": 1}',
            "createdAt": None, "updatedAt": None}]}
        report = defaultdict(list)
        taches, _ids = build_taches(data, {1}, report)
        self.assertIsNone(taches[0]["date_echeance"])
        self.assertEqual(report["taches_echeance_effacee"], [(7, "2025-02-01", "2025-01-15")])

    def test_heures_sans_personne_chiffrees_par_projet(self):
        data = {"intervenants": [{"id": 1, "intervenantID": None, "projectID": 3, "taskID": None}],
                "interventionHours": [
                    {"interventionID": 1, "projectID": 3, "date": "2025-02-04", "hours": 3.5},
                    {"interventionID": None, "projectID": 3, "date": "2025-02-05", "hours": 2},
                    {"interventionID": None, "projectID": None, "date": "2025-02-05", "hours": 1}]}
        report = defaultdict(list)
        self.assertEqual(build_dailylog(data, set(), set(), set(), report), [])
        self.assertEqual(report["dailylog_ignore_sans_intervenant"], 3)
        self.assertEqual(report["dailylog_heures_orphelines"], {3: 5.5, None: 1.0})


@unittest.skipUnless(os.environ.get("KAIROS_TEST_DATABASE_URL") and shutil.which("psql"),
                     "KAIROS_TEST_DATABASE_URL et psql requis")
class TestRepriseChargeeDansPostgres(unittest.TestCase):
    """Audit QA I12 : migration.sql n'était jamais chargé sur une vraie
    base. Mini export synthétique (tests/fixtures_chronos) -> script ->
    psql -v ON_ERROR_STOP=1 sur une base neuve (schema.sql, triggers
    actifs)."""

    def test_chargement_complet(self):
        import subprocess
        import tempfile
        import uuid
        from urllib.parse import urlsplit
        racine = Path(__file__).resolve().parent.parent
        u = urlsplit(os.environ["KAIROS_TEST_DATABASE_URL"])
        env = dict(os.environ, PGHOST=u.hostname or "127.0.0.1", PGPORT=str(u.port or 5432),
                   PGUSER=u.username or "", PGPASSWORD=u.password or os.environ.get("PGPASSWORD", ""))
        base = f"kairos_t_chronos_{uuid.uuid4().hex[:8]}"

        def psql(db, *args):
            return subprocess.run(["psql", "-X", "-Atq", "-v", "ON_ERROR_STOP=1", "-d", db, *args],
                                  env=env, capture_output=True, text=True)

        psql("postgres", "-c", f"CREATE DATABASE {base}")
        self.addCleanup(psql, "postgres", "-c", f"DROP DATABASE IF EXISTS {base}")
        self.assertEqual(psql(base, "-f", str(racine / "schema.sql")).returncode, 0)
        sortie = Path(tempfile.mkdtemp(prefix="kairos_chronos_"))
        self.addCleanup(shutil.rmtree, sortie, ignore_errors=True)
        r = subprocess.run([sys.executable, str(racine / "scripts" / "migrate_from_chronos.py"),
                            str(racine / "tests" / "fixtures_chronos" / "mini_dump.sql"), "--out-dir", str(sortie)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = psql(base, "-f", str(sortie / "migration.sql"))
        self.assertEqual(r.returncode, 0, r.stderr)

        def valeur(sql):
            return psql(base, "-c", sql).stdout.strip()

        self.assertEqual(valeur("SELECT string_agg(id::text, ',' ORDER BY id) FROM projet"), "1,2,3")  # Client chef exclu
        self.assertEqual(valeur("SELECT coalesce(date_fin::text, 'NULL') || ' ' || date_cloture FROM projet WHERE id = 2"),
                         "NULL 2025-05-10")
        self.assertEqual(valeur("SELECT count(*) FROM projet WHERE etat IN ('termine', 'abandonne') AND date_cloture IS NULL"), "0")
        self.assertEqual(valeur("SELECT phase_liee_id || ' ' || to_char(updated_at, 'YYYY-MM-DD') FROM projet WHERE id = 3"),
                         "2 2025-04-02")  # phase liée posée sans réécrire updated_at
        self.assertEqual(valeur("SELECT coalesce(date_echeance::text, 'NULL') FROM tache WHERE id = 1"), "NULL")
        self.assertEqual(valeur("SELECT string_agg(utilisateur_id::text, ',') FROM projet_co_chef WHERE projet_id = 1"), "3")
        self.assertEqual(valeur("SELECT count(*) FROM projet_intervenant pi JOIN utilisateur u ON u.id = pi.utilisateur_id "
                                "WHERE u.role IN ('client', 'rh')"), "0")
        self.assertEqual(valeur("SELECT sum(heures) FROM dailylog_entree"), "8.00")
        # Lot 11 : équipe du chef, à défaut MIDGARD (aucun compte repris n'a
        # d'équipe) ; tâche bloquée d'un projet Terminé fermée à sa date de
        # clôture ; projet En cours avec une tâche bloquée passé Bloqué.
        self.assertEqual(valeur("SELECT string_agg(DISTINCT coalesce(equipe_code, 'NULL'), ',') FROM projet"), "MIDGARD")
        self.assertEqual(valeur("SELECT etat || ' ' || date_fin FROM tache WHERE id = 3"), "termine 2025-05-10")
        self.assertEqual(valeur("SELECT etat FROM projet WHERE id = 3"), "bloque")
        self.assertEqual(valeur("SELECT etat FROM tache WHERE id = 4"), "bloque")
        rapport = (sortie / "rapport.md").read_text(encoding="utf-8")
        self.assertIn("**5.5 h** au total", rapport)
        self.assertIn("fin effacée", rapport)
        self.assertIn("1 tâche(s) encore ouverte(s) sur un projet clos", rapport)
        self.assertIn("1 projet(s) ouvert(s) dont l'état a été recalculé", rapport)

    def test_historique_hors_regles_du_daily_log_v9_charge_tel_quel(self):
        """Migration 0014 : 30 min, 10 h par jour, date au fuseau… ne
        s'appliquent pas à la reprise (SET LOCAL kairos.reprise_historique)
        — une journée Chronos de 12,67 h passe telle quelle."""
        import subprocess
        import tempfile
        import uuid
        from urllib.parse import urlsplit
        racine = Path(__file__).resolve().parent.parent
        u = urlsplit(os.environ["KAIROS_TEST_DATABASE_URL"])
        env = dict(os.environ, PGHOST=u.hostname or "127.0.0.1", PGPORT=str(u.port or 5432),
                   PGUSER=u.username or "", PGPASSWORD=u.password or os.environ.get("PGPASSWORD", ""))
        base = f"kairos_t_chronos_{uuid.uuid4().hex[:8]}"

        def psql(db, *args):
            return subprocess.run(["psql", "-X", "-Atq", "-v", "ON_ERROR_STOP=1", "-d", db, *args],
                                  env=env, capture_output=True, text=True)

        psql("postgres", "-c", f"CREATE DATABASE {base}")
        self.addCleanup(psql, "postgres", "-c", f"DROP DATABASE IF EXISTS {base}")
        self.assertEqual(psql(base, "-f", str(racine / "schema.sql")).returncode, 0)
        sortie = Path(tempfile.mkdtemp(prefix="kairos_chronos_"))
        self.addCleanup(shutil.rmtree, sortie, ignore_errors=True)
        dump = (racine / "tests" / "fixtures_chronos" / "mini_dump.sql").read_text(encoding="utf-8")
        self.assertIn("(1,8,'2025-02-03'", dump)
        (sortie / "dump.sql").write_text(dump.replace("(1,8,'2025-02-03'", "(1,12.67,'2025-02-03'"), encoding="utf-8")
        r = subprocess.run([sys.executable, str(racine / "scripts" / "migrate_from_chronos.py"),
                            str(sortie / "dump.sql"), "--out-dir", str(sortie / "out")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        sql = (sortie / "out" / "migration.sql").read_text(encoding="utf-8")
        self.assertIn("BEGIN;\nSET LOCAL kairos.reprise_historique = 'on';", sql)
        r = psql(base, "-f", str(sortie / "out" / "migration.sql"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(psql(base, "-c", "SELECT sum(heures) FROM dailylog_entree").stdout.strip(), "12.67")
        # Sans le contournement, la même ligne est refusée par la base.
        r = psql(base, "-c", "INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) "
                             "SELECT utilisateur_id, date + 1, projet_id, 2.67 FROM dailylog_entree LIMIT 1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("30 minutes", r.stderr)


if __name__ == "__main__":
    unittest.main()

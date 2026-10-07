"""Tests du lot 10 (intégration des audits sécurité, données et QA du
2026-10-07) : décisions 1, 2, 3 et 5 du gérant, entrées forgées,
notifications en double, sessions, durcissement, `flask migrer`.

Même principe que tests/test_smoke.py (psycopg2 simulé, repositories
remplacés par des mocks) : on vérifie que l'action protégée n'est JAMAIS
exécutée quand elle doit être refusée. Le SQL lui-même est vérifié sur un
vrai PostgreSQL par tests/sql/ et tests_integration/.
"""
import contextlib
import hashlib
import pathlib
import unittest
from unittest.mock import MagicMock, patch

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
except ImportError:  # python -m unittest tests.test_lot10
    from tests import test_smoke as smoke

from app import create_app, db  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parent.parent


class _FauxCurseur:
    """Curseur minimal pour `flask migrer` : mémorise le SQL exécuté et
    sert le contenu (simulé) de schema_migrations."""

    def __init__(self, journal, deja):
        self.journal, self.deja = journal, deja
        self._lignes = []
        self.connection = MagicMock(notices=[])

    def execute(self, sql, params=None):
        self.journal.append((" ".join(sql.split()), params))
        if sql.startswith("SELECT version, checksum"):
            self._lignes = [{"version": v, "checksum": c} for v, c in self.deja.items()]
        if sql.startswith("INSERT INTO schema_migrations"):
            self.deja[params[0]] = params[1]

    def fetchall(self):
        return self._lignes

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestFlaskMigrer(unittest.TestCase):
    """Audits données (M4) et QA (I5) : verrou, délai de verrouillage,
    empreintes des migrations publiées."""

    def _migrer(self, deja):
        journal = []
        verrou = MagicMock()
        verrou.cursor.side_effect = lambda: _FauxCurseur(journal, deja)
        pool = MagicMock()
        pool.getconn.return_value = verrou

        @contextlib.contextmanager
        def faux_get_cursor(*a, **k):
            yield _FauxCurseur(journal, deja)

        app = create_app(smoke.TestConfig)
        with patch.object(db, "_pool", pool), patch.object(db, "get_cursor", faux_get_cursor):
            res = app.test_cli_runner().invoke(args=["migrer"])
        return res, [sql for sql, _ in journal], pool

    @staticmethod
    def _empreinte(nom):
        return hashlib.sha256((RACINE / "migrations" / f"{nom}.sql").read_bytes()).hexdigest()

    def _toutes(self, sauf=()):
        return {f.stem: self._empreinte(f.stem) for f in sorted((RACINE / "migrations").glob("*.sql"))
                if f.stem not in sauf}

    def test_verrou_pris_puis_rendu(self):
        res, sqls, pool = self._migrer(self._toutes())
        self.assertEqual(res.exit_code, 0, res.output)
        self.assertIn("Rien à faire", res.output)
        self.assertIn("SELECT pg_advisory_lock(hashtext('kairos:flask-migrer'))", sqls)
        self.assertIn("SELECT pg_advisory_unlock(hashtext('kairos:flask-migrer'))", sqls)
        pool.putconn.assert_called_once()

    def test_migration_jouee_avec_lock_timeout_et_empreinte(self):
        deja = self._toutes(sauf=("0013_rattrapage_et_integrite",))
        res, sqls, _ = self._migrer(deja)
        self.assertEqual(res.exit_code, 0, res.output)
        self.assertIn("Application de 0013_rattrapage_et_integrite.sql", res.output)
        self.assertIn("SET LOCAL lock_timeout = '15s'", sqls)
        self.assertEqual(deja["0013_rattrapage_et_integrite"], self._empreinte("0013_rattrapage_et_integrite"))

    def test_migration_modifiee_apres_application_signalee(self):
        deja = self._toutes()
        deja["0011_roles_et_projets_clos"] = "0" * 64
        res, _, _ = self._migrer(deja)
        self.assertEqual(res.exit_code, 0)
        self.assertIn("ATTENTION : 0011_roles_et_projets_clos.sql a été modifiée", res.output)

    def test_empreinte_manquante_enregistree(self):
        deja = self._toutes()
        deja["0001_equipe_urbs_ipco"] = None
        res, sqls, _ = self._migrer(deja)
        self.assertNotIn("ATTENTION", res.output)
        self.assertTrue(any(s.startswith("UPDATE schema_migrations SET checksum") for s in sqls))


if __name__ == "__main__":
    unittest.main()

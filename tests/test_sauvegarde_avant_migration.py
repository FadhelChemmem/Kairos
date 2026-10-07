"""Tests de scripts/sauvegarde_avant_migration.sh (service
`sauvegarde-migrations` de docker-compose.yml, audit QA du lot 10).

Exécutés sur un vrai PostgreSQL quand KAIROS_TEST_DATABASE_URL est défini
(base de test ; une base temporaire est créée à côté puis supprimée) et que
psql/pg_dump sont installés ; ignorés sinon.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit

RACINE = Path(__file__).resolve().parent.parent
SCRIPT = RACINE / "scripts" / "sauvegarde_avant_migration.sh"
URL = os.environ.get("KAIROS_TEST_DATABASE_URL")


@unittest.skipUnless(URL and shutil.which("psql") and shutil.which("pg_dump"),
                     "KAIROS_TEST_DATABASE_URL, psql et pg_dump requis")
class SauvegardeAvantMigrationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        u = urlsplit(URL)
        cls.env_pg = dict(os.environ, PGHOST=u.hostname or "127.0.0.1", PGPORT=str(u.port or 5432),
                          PGUSER=u.username or "", PGPASSWORD=u.password or os.environ.get("PGPASSWORD", ""))
        cls.base = f"kairos_t_sauv_{uuid.uuid4().hex[:8]}"
        cls._psql("postgres", f"CREATE DATABASE {cls.base}")
        subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", cls.base, "-f", str(RACINE / "schema.sql")],
                       env=cls.env_pg, check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls._psql("postgres", f"DROP DATABASE IF EXISTS {cls.base}")

    @classmethod
    def _psql(cls, base, sql):
        return subprocess.run(["psql", "-X", "-Atq", "-v", "ON_ERROR_STOP=1", "-d", base, "-c", sql],
                              env=cls.env_pg, check=True, capture_output=True, text=True).stdout

    def setUp(self):
        self.dest = Path(tempfile.mkdtemp(prefix="kairos_sauv_"))
        self.addCleanup(shutil.rmtree, self.dest, ignore_errors=True)

    def _run(self, **env):
        e = dict(self.env_pg, PGDATABASE=self.base, MIGRATIONS_DIR=str(RACINE / "migrations"),
                 DEST=str(self.dest))
        e.update(env)
        return subprocess.run(["bash", str(SCRIPT)], env=e, capture_output=True, text=True)

    def test_rien_en_attente_aucune_sauvegarde(self):
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Aucune migration en attente", r.stdout)
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_migration_en_attente_sauvegarde_complete_et_privee(self):
        self._psql(self.base, "DELETE FROM schema_migrations WHERE version = '0013_rattrapage_et_integrite'")
        self.addCleanup(self._psql, self.base,
                        "INSERT INTO schema_migrations (version) VALUES ('0013_rattrapage_et_integrite')")
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        fichiers = list(self.dest.glob("avant_migration_*.sql.gz"))
        self.assertEqual(len(fichiers), 1, r.stdout)
        self.assertEqual(fichiers[0].stat().st_mode & 0o077, 0)
        dump = subprocess.run(["gunzip", "-c", str(fichiers[0])], capture_output=True, text=True).stdout
        self.assertIn("-- PostgreSQL database dump complete", dump)
        self.assertIn("CREATE TABLE public.utilisateur", dump)

    def test_echec_de_connexion_code_retour_non_nul(self):
        self._psql(self.base, "DELETE FROM schema_migrations WHERE version = '0013_rattrapage_et_integrite'")
        self.addCleanup(self._psql, self.base,
                        "INSERT INTO schema_migrations (version) VALUES ('0013_rattrapage_et_integrite')")
        r = self._run(PGDATABASE="base_qui_n_existe_pas")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(list(self.dest.glob("*.sql.gz")), [])


if __name__ == "__main__":
    unittest.main()

"""Tests de scripts/restore_db.sh (audits données I1 et QA B3, lot 10).

Le vrai `docker` est remplacé par tests/fixtures_restore/docker, qui envoie
psql/pg_dump vers le PostgreSQL de test : la logique bash réelle est
exercée (refus d'un dump tronqué, transaction unique, copie de sécurité).
Ignorés sans KAIROS_TEST_DATABASE_URL, psql et pg_dump. Une base
temporaire est créée puis supprimée (la base de test n'est pas touchée).
"""
import gzip
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit

RACINE = Path(__file__).resolve().parent.parent
URL = os.environ.get("KAIROS_TEST_DATABASE_URL")
FAUX_DOCKER = Path(__file__).resolve().parent / "fixtures_restore"
FAUX_SUDO = Path(__file__).resolve().parent / "fixtures_backup"


@unittest.skipUnless(URL and shutil.which("psql") and shutil.which("pg_dump"),
                     "KAIROS_TEST_DATABASE_URL, psql et pg_dump requis")
class RestoreDbTestCase(unittest.TestCase):
    def setUp(self):
        u = urlsplit(URL)
        self.base = f"kairos_t_rest_{uuid.uuid4().hex[:8]}"
        self.env = dict(os.environ, PGHOST=u.hostname or "127.0.0.1", PGPORT=str(u.port or 5432),
                        PGPASSWORD=u.password or os.environ.get("PGPASSWORD", ""))
        self.user = u.username or "kairos"
        self._psql("postgres", f"CREATE DATABASE {self.base}")
        self.addCleanup(self._psql, "postgres", f"DROP DATABASE IF EXISTS {self.base}")

        self.tmp = Path(tempfile.mkdtemp(prefix="kairos_restore_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "scripts").mkdir()
        shutil.copy(RACINE / "scripts" / "restore_db.sh", self.tmp / "scripts" / "restore_db.sh")
        (self.tmp / ".env").write_text(f"POSTGRES_USER={self.user}\nPOSTGRES_DB={self.base}\n", encoding="utf-8")
        self.uploads = self.tmp / "uploads_volume"
        self.uploads.mkdir()

    def _psql(self, base, sql):
        return subprocess.run(["psql", "-X", "-Atq", "-v", "ON_ERROR_STOP=1", "-U", self.user, "-d", base, "-c", sql],
                              env=self.env, check=True, capture_output=True, text=True).stdout.strip()

    def _base_actuelle(self, lignes):
        self._psql(self.base, "DROP TABLE IF EXISTS t; CREATE TABLE t (x int); "
                              f"INSERT INTO t SELECT generate_series(1, {lignes})")

    def _dump(self, lignes, couper=False, injecter=None):
        """Dump gzip d'une base source contenant `lignes` lignes."""
        source = f"{self.base}_src"
        self._psql("postgres", f"DROP DATABASE IF EXISTS {source}")
        self._psql("postgres", f"CREATE DATABASE {source}")
        self.addCleanup(self._psql, "postgres", f"DROP DATABASE IF EXISTS {source}")
        self._psql(source, f"CREATE TABLE t (x int); INSERT INTO t SELECT generate_series(1, {lignes})")
        texte = subprocess.run(["pg_dump", "--clean", "--if-exists", "-U", self.user, source], env=self.env,
                               check=True, capture_output=True, text=True).stdout
        if couper:
            texte = texte[:texte.index("COPY public.t")]
        if injecter:
            texte = texte.replace("COPY public.t", injecter + "\nCOPY public.t", 1)
        chemin = self.tmp / f"dump_{uuid.uuid4().hex[:6]}.sql.gz"
        chemin.write_bytes(gzip.compress(texte.encode()))
        return chemin

    def _restaurer(self, *args, cwd=None):
        env = dict(self.env, PATH=f"{FAUX_DOCKER}:{FAUX_SUDO}:{self.env['PATH']}",
                   FAKE_UPLOADS_DIR=str(self.uploads), KAIROS_BACKUP_DIR=str(self.tmp / "sauvegardes"))
        return subprocess.run(["bash", str(self.tmp / "scripts" / "restore_db.sh"), "--oui", *map(str, args)],
                              cwd=cwd or self.tmp, env=env, capture_output=True, text=True)

    def _compter(self):
        return int(self._psql(self.base, "SELECT count(*) FROM t"))

    def test_dump_tronque_refuse_base_intacte(self):
        self._base_actuelle(4)
        r = self._restaurer(self._dump(300, couper=True))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("incomplète", r.stderr)
        self.assertEqual(self._compter(), 4)
        self.assertFalse((self.tmp / "sauvegardes").exists())

    def test_erreur_au_milieu_rien_ne_change(self):
        self._base_actuelle(4)
        r = self._restaurer(self._dump(300, injecter="SELECT 1/0;"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("la base n'a PAS été modifiée", r.stderr)
        self.assertEqual(self._compter(), 4)

    def test_dump_valide_restaure_avec_copie_de_securite(self):
        self._base_actuelle(4)
        archive = self.tmp / "uploads.tar.gz"
        (self.tmp / "src_uploads").mkdir()
        (self.tmp / "src_uploads" / "note.pdf").write_bytes(b"pdf")
        subprocess.run(["tar", "czf", str(archive), "-C", str(self.tmp / "src_uploads"), "."], check=True)
        r = self._restaurer(self._dump(300), archive)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self._compter(), 300)
        self.assertTrue((self.uploads / "note.pdf").exists())
        filets = list((self.tmp / "sauvegardes").glob("avant_restauration_*.sql.gz"))
        self.assertEqual(len(filets), 1)
        self.assertIn("COPY public.t", gzip.decompress(filets[0].read_bytes()).decode())
        self.assertEqual(self._psql(self.base, "SHOW timezone"), "Africa/Tunis")

    def test_chemin_relatif_depuis_un_autre_dossier(self):
        self._base_actuelle(4)
        dump = self._dump(10)
        ailleurs = self.tmp / "ailleurs"
        ailleurs.mkdir()
        r = self._restaurer(os.path.relpath(dump, ailleurs), cwd=ailleurs)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self._compter(), 10)


if __name__ == "__main__":
    unittest.main()

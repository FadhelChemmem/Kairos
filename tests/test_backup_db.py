"""Tests fonctionnels pour scripts/backup_db.sh — PROMPT_CORRECTIONS.md
P1 #15. Le vrai `docker`/`sudo` ne sont jamais invoqués : deux faux
exécutables (tests/fixtures_backup/docker et /sudo) les remplacent en tête
de PATH, pour exercer la vraie logique bash (écriture atomique, umask,
lecture de .env, rétention) sans dépendre d'un Docker/Postgres réel."""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "backup_db.sh"
FIXTURES_BIN = Path(__file__).resolve().parent / "fixtures_backup"


class BackupDbTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kairos_backup_test_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        # Structure minimale attendue par le script : scripts/backup_db.sh
        # sous une racine de "projet", avec un .env à côté.
        (self.tmp / "scripts").mkdir()
        shutil.copy(SCRIPT, self.tmp / "scripts" / "backup_db.sh")
        os.chmod(self.tmp / "scripts" / "backup_db.sh", 0o755)

        (self.tmp / ".env").write_text("POSTGRES_USER=testuser\nPOSTGRES_DB=testdb\n", encoding="utf-8")

        # Contenu bidon du volume kairos_uploads (le faux `docker` s'en sert
        # pour produire un vrai flux tar.gz valide).
        self.uploads_dir = self.tmp / "fake_uploads"
        self.uploads_dir.mkdir()
        (self.uploads_dir / "note.pdf").write_bytes(b"contenu bidon")

    def _run(self, env_extra=None):
        env = dict(os.environ)
        env["PATH"] = f"{FIXTURES_BIN}:{env['PATH']}"
        env["FAKE_UPLOADS_DIR"] = str(self.uploads_dir)
        env.update(env_extra or {})
        return subprocess.run(
            ["bash", str(self.tmp / "scripts" / "backup_db.sh")],
            cwd=self.tmp, env=env, capture_output=True, text=True,
        )

    def _backups(self):
        d = self.tmp / "backups"
        return sorted(p.name for p in d.iterdir()) if d.exists() else []

    def test_sauvegarde_reussie_cree_les_deux_archives_valides_et_privees(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        noms = self._backups()
        sql = [n for n in noms if n.endswith(".sql.gz")]
        tar = [n for n in noms if n.endswith(".tar.gz")]
        self.assertEqual(len(sql), 1, noms)
        self.assertEqual(len(tar), 1, noms)
        # Aucun fichier .tmp ne doit survivre à une sauvegarde réussie.
        self.assertFalse(any(n.endswith(".tmp") for n in noms), noms)
        # Intégrité gzip des deux archives.
        for n in sql + tar:
            self.assertEqual(subprocess.run(["gzip", "-t", str(self.tmp / "backups" / n)]).returncode, 0)
        # Umask 077 (PROMPT_CORRECTIONS.md P1 #15) : ni le groupe ni les
        # autres ne doivent avoir le moindre droit sur une sauvegarde, qui
        # contient l'ensemble des données de l'entreprise.
        for n in sql + tar:
            mode = stat.S_IMODE((self.tmp / "backups" / n).stat().st_mode)
            self.assertEqual(mode & 0o077, 0, f"{n}: permissions {oct(mode)}")

    def test_echec_pg_dump_ne_laisse_aucun_fichier_final_ni_tmp(self):
        """PROMPT_CORRECTIONS.md P1 #15 : avant l'écriture atomique, un
        pg_dump interrompu laissait quand même un .sql.gz tronqué sous son
        nom final, indiscernable d'une vraie sauvegarde."""
        result = self._run(env_extra={"FAKE_DOCKER_FAIL_DB": "1"})
        self.assertNotEqual(result.returncode, 0)
        noms = self._backups()
        self.assertEqual([n for n in noms if n.endswith(".sql.gz")], [])
        self.assertEqual([n for n in noms if n.endswith(".tmp")], [], noms)

    def test_echec_tar_uploads_ne_laisse_aucun_fichier_final_ni_tmp(self):
        """La sauvegarde de la base a déjà réussi à ce stade (elle passe en
        premier) — seule celle des pièces jointes doit être absente/propre."""
        result = self._run(env_extra={"FAKE_DOCKER_FAIL_UPLOADS": "1"})
        self.assertNotEqual(result.returncode, 0)
        noms = self._backups()
        self.assertEqual(len([n for n in noms if n.endswith(".sql.gz")]), 1, noms)
        self.assertEqual([n for n in noms if n.endswith(".tar.gz")], [], noms)
        self.assertEqual([n for n in noms if n.endswith(".tmp")], [], noms)

    def test_env_lu_sans_source_ignore_les_lignes_dangereuses(self):
        """PROMPT_CORRECTIONS.md P1 #15 : `source .env` exécute le fichier
        comme un script shell — une ligne mal formée pourrait exécuter du
        code arbitraire. Le script ne doit lire QUE POSTGRES_USER/
        POSTGRES_DB, sans jamais évaluer le reste du fichier."""
        marqueur = self.tmp / "ne_devrait_jamais_exister"
        (self.tmp / ".env").write_text(
            "POSTGRES_USER=testuser\n"
            "POSTGRES_DB=testdb\n"
            f"MALICIEUX=$(touch {marqueur})\n",
            encoding="utf-8",
        )
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marqueur.exists(), "la ligne MALICIEUX=... a été exécutée : .env a été source-é")

    def test_conserve_seulement_les_30_dernieres_sauvegardes_de_chaque_type(self):
        backups_dir = self.tmp / "backups"
        backups_dir.mkdir()
        anciens_sql = []
        anciens_tar = []
        for i in range(32):
            f_sql = backups_dir / f"kairos_2020-01-{i:02d}_0000.sql.gz"
            f_tar = backups_dir / f"kairos_uploads_2020-01-{i:02d}_0000.tar.gz"
            f_sql.write_bytes(b"x")
            f_tar.write_bytes(b"x")
            os.utime(f_sql, (1000 + i, 1000 + i))
            os.utime(f_tar, (1000 + i, 1000 + i))
            anciens_sql.append(f_sql.name)
            anciens_tar.append(f_tar.name)

        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        noms = set(self._backups())
        sql_restants = [n for n in noms if n.endswith(".sql.gz")]
        tar_restants = [n for n in noms if n.endswith(".tar.gz")]
        # 32 anciens + 1 nouveau de chaque type = 33, on n'en garde que 30.
        self.assertEqual(len(sql_restants), 30, sql_restants)
        self.assertEqual(len(tar_restants), 30, tar_restants)
        # Les plus anciens (les premiers créés) doivent avoir disparu.
        self.assertNotIn(anciens_sql[0], noms)
        self.assertNotIn(anciens_tar[0], noms)


if __name__ == "__main__":
    unittest.main()

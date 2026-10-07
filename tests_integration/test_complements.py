import datetime
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests_integration.base import URL, BaseIntegration


class TestEtatProjetSuitTaches(BaseIntegration):
    def _etat(self, p):
        return self.sql("SELECT etat FROM projet WHERE id=%s", (p,))[0]["etat"]

    def test_bloque_puis_debloque_jamais_termine(self):
        from app.repositories import taches
        chef = self.user("chef_de_projet"); p = self.projet(chef)
        t1, t2 = self.tache(p, chef), self.tache(p, chef)
        taches.set_etat(t1, p, "bloque", chef)
        self.assertEqual(self._etat(p), "bloque")
        taches.set_etat(t2, p, "bloque", chef)
        taches.set_etat(t1, p, "verifie", chef)
        self.assertEqual(self._etat(p), "bloque")       # t2 encore bloquée
        taches.close_tache(t2, p, chef, "information")
        self.assertEqual(self._etat(p), "en_cours")
        taches.close_tache(t1, p, chef, "information")
        self.assertEqual(self._etat(p), "en_cours")     # jamais « terminé » par ce biais


class TestProfilPersonne(BaseIntegration):
    def test_taches_d_un_collegue_filtrees_par_ce_que_je_vois(self):
        from app.repositories import taches
        chef_m, chef_u = self.user("chef_de_projet"), self.user("chef_de_projet", "URBS")
        collegue = self.user("intervenant", "URBS")
        p_m, p_u = self.projet(chef_m), self.projet(chef_u, "URBS")
        p_clos = self.projet(chef_m, etat="termine")              # visible mais clos
        visible = self.tache(p_m, chef_m, intervenants=[collegue])
        self.tache(p_u, chef_u, intervenants=[collegue])          # équipe URBS : invisible pour chef_m
        self.tache(p_clos, chef_m, intervenants=[collegue])
        self.assertEqual([t["id"] for t in taches.list_en_cours_pour_profil(collegue, viewer_id=chef_m)], [visible])


class TestMigrerEchec(unittest.TestCase):
    def test_migration_en_erreur_code_retour_non_nul_et_suivantes_non_jouees(self):
        if not URL:
            self.skipTest("KAIROS_TEST_DATABASE_URL non défini")
        racine = pathlib.Path(__file__).resolve().parent.parent
        copie = pathlib.Path(tempfile.mkdtemp()) / "kairos"
        shutil.copytree(racine, copie, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        (copie / "migrations" / "9998_casse.sql").write_text("SELECT 1/0;", encoding="utf-8")
        (copie / "migrations" / "9999_apres.sql").write_text("SELECT 1;", encoding="utf-8")
        nettoyer = ["psql", URL, "-qc", "DELETE FROM schema_migrations WHERE version LIKE '999%'"]
        self.addCleanup(subprocess.run, nettoyer, capture_output=True)
        env = dict(os.environ, DATABASE_URL=URL, FLASK_APP="wsgi.py", SECRET_KEY="x" * 40,
                   UPLOAD_DIR=tempfile.mkdtemp())
        r = subprocess.run([sys.executable, "-m", "flask", "migrer"], cwd=copie, env=env,
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("9999_apres", r.stdout)
        q = subprocess.run(["psql", URL, "-Atc", "SELECT count(*) FROM schema_migrations WHERE version LIKE '999%'"],
                           capture_output=True, text=True)
        self.assertEqual(q.stdout.strip(), "0")

"""Après scripts/recharger_projets_chronos.py, l'appli tourne : accueil (avec
« Mes tâches »), liste des projets, fiche projet, Deadlines et Daily log
répondent 200 pour un Admin, un chef de projet et un intervenant.

Base : reprise complète (migrate_from_chronos.py) puis rechargement, tous
deux joués par psql comme sur le NAS. Export : mini_dump.sql synthétique, ou
KAIROS_RECHARGE_DUMP (vrai export, jamais versionné). Ignoré sans
KAIROS_TEST_DATABASE_URL ou sans psql."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from tests_integration.base import URL, BaseIntegration

RACINE = Path(__file__).resolve().parent.parent
DUMP = Path(os.environ.get("KAIROS_RECHARGE_DUMP") or RACINE / "tests" / "fixtures_chronos" / "mini_dump.sql")


@unittest.skipUnless(shutil.which("psql"), "psql requis")
class TestPagesApresRechargement(BaseIntegration):
    def psql(self, fichier):
        u = urlsplit(URL)
        env = dict(os.environ, PGHOST=u.hostname or "127.0.0.1", PGPORT=str(u.port or 5432),
                   PGUSER=u.username or "", PGPASSWORD=u.password or os.environ.get("PGPASSWORD", ""))
        r = subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", u.path.lstrip("/")],
                           env=env, capture_output=True, text=True, input=fichier.read_text(encoding="utf-8"))
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])

    def connecter(self, user_id):
        from app.auth import password_fingerprint
        h = self.sql("SELECT mot_de_passe_hash FROM utilisateur WHERE id = %s", (user_id,))[0]["mot_de_passe_hash"]
        self.client = self.app.test_client()
        with self.client.session_transaction() as s:
            s["user_id"] = user_id
            s["pw_fingerprint"] = password_fingerprint(h)

    def test_pages_principales(self):
        sortie = Path(tempfile.mkdtemp(prefix="kairos_rch_it_"))
        self.addCleanup(shutil.rmtree, sortie, ignore_errors=True)
        r = subprocess.run([sys.executable, str(RACINE / "scripts" / "migrate_from_chronos.py"), str(DUMP),
                            "--out-dir", str(sortie)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([sys.executable, str(RACINE / "scripts" / "recharger_projets_chronos.py"), str(DUMP),
                            "--sql", str(sortie / "recharge.sql")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.psql(sortie / "migration.sql")
        self.psql(sortie / "recharge.sql")
        self.psql(sortie / "recharge.sql")  # rejoué

        admin = self.sql("SELECT min(id) AS id FROM utilisateur WHERE role = 'admin' AND actif")[0]["id"]
        chef, projet_chef = (lambda r: (r["chef_projet_id"], r["id"]))(self.sql("""
            SELECT p.chef_projet_id, p.id FROM projet p JOIN utilisateur u ON u.id = p.chef_projet_id
            WHERE u.role = 'chef_de_projet' AND u.actif AND EXISTS (SELECT 1 FROM tache t WHERE t.projet_id = p.id)
            ORDER BY p.id DESC LIMIT 1""")[0])
        inter, projet_inter = (lambda r: (r["utilisateur_id"], r["projet_id"]))(self.sql("""
            SELECT ti.utilisateur_id, t.projet_id FROM tache_intervenant ti JOIN tache t ON t.id = ti.tache_id
            JOIN utilisateur u ON u.id = ti.utilisateur_id WHERE u.role = 'intervenant' AND u.actif
            ORDER BY t.id DESC LIMIT 1""")[0])
        for user_id, projet_id in ((admin, projet_chef), (chef, projet_chef), (inter, projet_inter)):
            self.connecter(user_id)
            for page in ("/accueil", "/projets", f"/projets/{projet_id}", "/deadlines", "/dailylog"):
                reponse = self.client.get(page)
                self.assertEqual(reponse.status_code, 200, f"{page} pour l'utilisateur {user_id}")
                if page == "/accueil":
                    self.assertRegex(reponse.get_data(as_text=True), "Mes tâches|Tâches de mes projets")

"""deploy.sh (lot 12) sur de vrais dépôts git jetables, avec un faux
`docker` en tête de PATH (jamais le vrai) : version poussée depuis un autre
poste (récupérée puis déployée), patch appliqué SUR le serveur par git am
puis poussé (dépôt déjà à jour mais jamais déployé : déployé quand même,
retour arrière vers l'état d'avant git am), rien à faire la seconde fois."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

FAUX_DOCKER = """#!/bin/sh
echo "$*" >> "$FAUX_DOCKER_LOG"
case "$*" in
  "compose images web --format json") echo '[{"Repository":"kairos-web","Tag":"latest"}]' ;;
  "compose ps -q web") echo abc123 ;;
  inspect*) echo healthy ;;
  "compose logs web"*) echo "Rien à faire : toutes les migrations sont déjà appliquées." ;;
  "compose exec -T db"*) cat >/dev/null; echo "Dernière migration : 0018" ;;
  *) : ;;
esac
exit 0
"""


@unittest.skipUnless(shutil.which("git") and shutil.which("bash"), "git et bash requis")
class TestDeploy(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kairos_deploy_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        (self.bin / "docker").write_text(FAUX_DOCKER, encoding="utf-8")
        os.chmod(self.bin / "docker", 0o755)
        self.log = self.tmp / "docker.log"
        self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "FAUX_DOCKER_LOG": str(self.log),
                    "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "T",
                    "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}
        self.git("init", "-q", "--bare", "-b", "master", str(self.tmp / "origin.git"), cwd=self.tmp)
        self.poste = self.tmp / "poste"
        self.git("clone", "-q", str(self.tmp / "origin.git"), str(self.poste), cwd=self.tmp)
        self.git("checkout", "-q", "-b", "master", cwd=self.poste)
        shutil.copy(RACINE / "deploy.sh", self.poste / "deploy.sh")
        (self.poste / "scripts").mkdir()
        (self.poste / "scripts" / "backup_db.sh").write_text("echo sauvegarde faite\n", encoding="utf-8")
        self.commit(self.poste, "A")
        self.git("push", "-q", "origin", "master", cwd=self.poste)
        self.serveur = self.tmp / "serveur"
        self.git("clone", "-q", str(self.tmp / "origin.git"), str(self.serveur), cwd=self.tmp)

    def git(self, *args, cwd):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, depot, nom):
        (depot / f"{nom}.txt").write_text(nom, encoding="utf-8")
        self.git("add", "-A", cwd=depot)
        self.git("commit", "-q", "-m", nom, cwd=depot)
        return self.git("rev-parse", "HEAD", cwd=depot)

    def deployer(self):
        if self.log.exists():
            self.log.unlink()
        r = subprocess.run(["bash", str(self.serveur / "deploy.sh")], env=self.env, capture_output=True, text=True)
        appels = self.log.read_text(encoding="utf-8") if self.log.exists() else ""
        return r, appels

    def tag(self, nom):
        return self.git("rev-parse", f"{nom}^{{commit}}", cwd=self.serveur)

    def test_patch_applique_sur_le_serveur_puis_version_poussee_ailleurs(self):
        a = self.git("rev-parse", "HEAD", cwd=self.serveur)
        # Patch préparé ailleurs, appliqué ici par git am, puis poussé.
        b = self.commit(self.poste, "B")
        patch = self.git("format-patch", "--stdout", "HEAD~1", cwd=self.poste)
        (self.tmp / "lot.patch").write_text(patch + "\n", encoding="utf-8")
        self.git("reset", "-q", "--hard", "HEAD~1", cwd=self.poste)
        self.git("am", "-q", "--3way", str(self.tmp / "lot.patch"), cwd=self.serveur)
        self.git("push", "-q", "origin", "master", cwd=self.serveur)
        r, appels = self.deployer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("patch appliqué sur ce serveur", r.stdout)
        self.assertIn("compose up -d --build", appels)
        self.assertEqual(self.tag("avant-deploiement"), a)
        self.assertEqual(self.tag("deploye"), self.git("rev-parse", "HEAD", cwd=self.serveur))
        self.assertEqual(self.git("log", "-1", "--format=%s", cwd=self.serveur), "B")
        self.assertNotEqual(b, a)
        # Seconde fois : rien à faire, rien de reconstruit.
        r, appels = self.deployer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Déjà à jour : rien à déployer.", r.stdout)
        self.assertNotIn("compose up", appels)
        # Version poussée depuis un autre poste : récupérée et déployée.
        deploye = self.tag("deploye")
        self.git("pull", "-q", "origin", "master", cwd=self.poste)
        c = self.commit(self.poste, "C")
        self.git("push", "-q", "origin", "master", cwd=self.poste)
        r, appels = self.deployer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("compose up -d --build", appels)
        self.assertEqual(self.tag("avant-deploiement"), deploye)
        self.assertEqual(self.tag("deploye"), c)

    def test_deja_a_jour_sans_trace_de_deploiement(self):
        # Dépôt à jour, jamais déployé par le script, sans ORIG_HEAD : on
        # déploie, en le disant (repère de retour arrière = version actuelle).
        r, appels = self.deployer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Version précédente introuvable", r.stdout)
        self.assertIn("compose up -d --build", appels)

    def test_modifications_locales_bloquent(self):
        (self.serveur / "A.txt").write_text("modifié\n", encoding="utf-8")
        r, appels = self.deployer()
        self.assertEqual(r.returncode, 1)
        self.assertIn("des fichiers suivis sont modifiés localement", r.stdout)
        self.assertNotIn("compose up", appels)


if __name__ == "__main__":
    unittest.main()

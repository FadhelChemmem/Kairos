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
  "compose logs web"*) echo "Rien à faire : toutes les migrations sont déjà appliquées."
                       if [ -n "$FAUX_LOG_EN_PLUS" ]; then echo "$FAUX_LOG_EN_PLUS"; fi ;;
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
        (self.poste / "scripts" / "backup_db.sh").write_text(
            "echo \"Sauvegarde base écrite : /sauvegardes/kairos_$(date +%s%N).sql.gz\"\n", encoding="utf-8")
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

    def test_retour_arriere_affiche_code_repere_image_puis_base(self):
        """Lot 20 (revue QA n° 6) : restaurer la base AVANT de remettre
        l'ancienne image la faisait re-migrer aussitôt par la nouvelle. Lot 21
        (revue R5) : le repère `deploye` revient aussi, et la sauvegarde à
        restaurer est nommée."""
        r, _ = self.deployer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        fin = r.stdout[r.stdout.index("Retour arrière si besoin"):]
        positions = [fin.index(m) for m in ("git switch --detach avant-deploiement", "git tag -f deploye HEAD",
                                            "docker tag kairos-web:avant-deploiement kairos-web:latest",
                                            "scripts/restore_db.sh /sauvegardes/kairos_")]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("up -d --no-build", fin)
        self.assertFalse((self.serveur / ".deploiement_en_cours").exists())

    def test_relance_apres_echec_garde_les_reperes_d_avant(self):
        """Lot 21 (revue R5) : une relance après un échec à l'étape 6 ne
        remplace pas l'image et la sauvegarde d'avant par celles de la
        nouvelle version."""
        a = self.git("rev-parse", "HEAD", cwd=self.serveur)
        self.git("tag", "deploye", a, cwd=self.serveur)
        self.git("pull", "-q", "origin", "master", cwd=self.poste)
        self.commit(self.poste, "B")
        self.git("push", "-q", "origin", "master", cwd=self.poste)
        self.env["FAUX_LOG_EN_PLUS"] = "web-1  | Traceback (most recent call last):"
        r, appels = self.deployer()
        self.assertEqual(r.returncode, 1)
        premiere = r.stdout.split("Sauvegarde base écrite : ")[1].split()[0]
        self.assertIn("tag kairos-web:latest kairos-web:avant-deploiement", appels)
        self.assertTrue((self.serveur / ".deploiement_en_cours").exists())
        del self.env["FAUX_LOG_EN_PLUS"]
        r, appels = self.deployer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Tentative précédente inachevée", r.stdout)
        self.assertNotIn("tag kairos-web:latest kairos-web:avant-deploiement", appels)
        self.assertEqual(self.tag("avant-deploiement"), a)
        self.assertIn(f"scripts/restore_db.sh {premiere}", r.stdout)
        self.assertFalse((self.serveur / ".deploiement_en_cours").exists())

    def test_apres_retour_arriere_le_deploiement_suivant_redeploie(self):
        """Lot 21 (revue R5) : après le retour arrière affiché, un nouveau
        deploy.sh sur master redéploie la nouvelle version."""
        a = self.git("rev-parse", "HEAD", cwd=self.serveur)
        self.git("tag", "deploye", a, cwd=self.serveur)
        self.git("pull", "-q", "origin", "master", cwd=self.poste)
        b = self.commit(self.poste, "B")
        self.git("push", "-q", "origin", "master", cwd=self.poste)
        r, _ = self.deployer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # Retour arrière tel qu'affiché (code et repère).
        self.git("switch", "-q", "--detach", "avant-deploiement", cwd=self.serveur)
        self.git("tag", "-f", "deploye", "HEAD", cwd=self.serveur)
        self.git("switch", "-q", "master", cwd=self.serveur)
        r, appels = self.deployer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Déjà à jour", r.stdout)
        self.assertIn("compose up -d --build", appels)
        self.assertEqual(self.tag("deploye"), b)

    def test_nouveau_deploy_sh_relance_dans_sa_nouvelle_version(self):
        """Lot 21 (revue R4) : une version poussée qui change deploy.sh est
        déployée par le NOUVEAU script, pas par celui en cours de lecture."""
        self.git("tag", "deploye", self.git("rev-parse", "HEAD", cwd=self.serveur), cwd=self.serveur)
        self.git("pull", "-q", "origin", "master", cwd=self.poste)
        script = (self.poste / "deploy.sh").read_text(encoding="utf-8")
        (self.poste / "deploy.sh").write_text(script.replace('vert "OK : Kairos déployé', 'vert "NOUVEAU SCRIPT OK : Kairos déployé'),
                                              encoding="utf-8")
        self.commit(self.poste, "B")
        self.git("push", "-q", "origin", "master", cwd=self.poste)
        r, _ = self.deployer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("relance dans sa nouvelle version", r.stdout)
        self.assertIn("NOUVEAU SCRIPT OK", r.stdout)

    def test_ligne_d_acces_contenant_erreur_ignoree(self):
        """Lot 20 (revue QA n° 17b) : une recherche du mot « Erreur » n'est
        pas une erreur ; une vraie trace l'est toujours."""
        acces = ('web-1  | 192.168.1.20 - - [19/Oct/2026:10:00:07 +0100] '
                 '"GET /recherche/api?q=Erreur HTTP/1.1" 200 312 "http://kairos.local/accueil" "Mozilla/5.0"')
        self.env["FAUX_LOG_EN_PLUS"] = acces
        r, _ = self.deployer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.tag("deploye"), self.git("rev-parse", "HEAD", cwd=self.serveur))
        self.git("tag", "-d", "deploye", cwd=self.serveur)
        self.env["FAUX_LOG_EN_PLUS"] = "web-1  | Traceback (most recent call last):"
        r, _ = self.deployer()
        self.assertEqual(r.returncode, 1)
        self.assertIn("erreur dans les journaux", r.stdout)


if __name__ == "__main__":
    unittest.main()

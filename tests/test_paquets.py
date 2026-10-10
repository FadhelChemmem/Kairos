"""Paquets statiques (app/paquets.py, lot 13 — audit a11y-perf N9) :
scripts communs assemblés, CSS sans commentaires, URL à empreinte et cache
long, sans chargement de l'utilisateur (ni « Vary: Cookie »)."""
import gzip
import pathlib
import re
import shutil
import subprocess
import unittest
from unittest.mock import patch

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
except ImportError:  # python -m unittest tests.test_paquets
    from tests import test_smoke as smoke

from app import paquets  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parent.parent


class TestNettoyage(unittest.TestCase):
    def test_css_commentaires_retires_chaines_gardees(self):
        css = ('/* titre */\n.a { content: "/* pas un commentaire */"; }\n\n'
               ".b::before { content: '*/'; } /* fin */\n.c{color:red}/**/\n")
        self.assertEqual(paquets.sans_commentaires_css(css),
                         '.a { content: "/* pas un commentaire */"; }\n'
                         ".b::before { content: '*/'; }\n.c{color:red}\n")

    def test_js_seules_les_lignes_de_commentaire(self):
        js = ("// en-tête\n/* bloc\n * suite */\nvar u = 'http://x/*y*/'; // garde\n"
              "  /** doc */\nf(/* a */ 1);\n/* a */ g();\nvar r = /\\/\\//;\n")
        self.assertEqual(paquets.sans_commentaires_js(js),
                         "var u = 'http://x/*y*/'; // garde\nf(/* a */ 1);\n/* a */ g();\nvar r = /\\/\\//;\n")

    def test_css_du_depot_identique_hors_commentaires(self):
        source = (RACINE / "app" / "static" / "css" / "app.css").read_text(encoding="utf-8")
        nettoye = paquets.sans_commentaires_css(source)
        plat = lambda t: re.sub(r"\s+", "", t)  # noqa: E731
        self.assertEqual(plat(re.sub(r"/\*.*?\*/", "", source, flags=re.S)), plat(nettoye))
        self.assertLess(len(nettoye), len(source) * 0.9)

    @unittest.skipUnless(shutil.which("node"), "node absent")
    def test_commun_js_syntaxe_valide_et_ordre(self):
        class App:
            static_folder = str(RACINE / "app" / "static")
        corps, zippe, empreinte = paquets.assembler(App(), "commun.js")
        self.assertEqual(gzip.decompress(zippe), corps)
        self.assertRegex(empreinte, r"^[0-9a-f]{12}$")
        texte = corps.decode("utf-8")
        positions = [texte.index(f"/* {f} */") for f in paquets.PAQUETS["commun.js"]]
        self.assertEqual(positions, sorted(positions))
        verif = subprocess.run(["node", "--check", "-"], input=corps, capture_output=True)
        self.assertEqual(verif.returncode, 0, verif.stderr.decode())


class TestRoute(smoke.SmokeBase):
    def _get(self, url, en_tetes=None):
        return self.client.get(url, headers=en_tetes or {})

    def test_paquet_versionne_cache_long_gzip_sans_utilisateur(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            html = self.client.get("/accueil").get_data(as_text=True)
        finally:
            for p in reversed(patchers):
                p.stop()
        url = re.search(r'src="(/static/paquets/commun\.js\?v=[0-9a-f]{12})"', html).group(1)
        with patch("app.auth.get_user_by_id") as charger:
            resp = self._get(url, {"Accept-Encoding": "gzip"})
            charger.assert_not_called()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertEqual(resp.headers["Content-Encoding"], "gzip")
        self.assertEqual(resp.mimetype, "application/javascript")
        self.assertNotIn("Cookie", resp.headers.get("Vary", ""))
        self.assertIn(b"window.Kairos", gzip.decompress(resp.data))
        etag = resp.headers["ETag"]
        resp.close()
        resp = self._get(url, {"If-None-Match": etag})
        self.assertEqual(resp.status_code, 304)
        resp.close()

    def test_sans_empreinte_revalide_et_inconnu_404(self):
        resp = self._get("/static/paquets/app.css")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["Cache-Control"], "no-cache")
        self.assertEqual(resp.mimetype, "text/css")
        self.assertNotIn(b"/*", resp.data)
        resp.close()
        resp = self._get("/static/paquets/inconnu.js")
        self.assertEqual(resp.status_code, 404)
        resp.close()

    def test_page_publique_sans_socle_si_aucun_message(self):
        html = self._get("/connexion").get_data(as_text=True)
        self.assertNotIn("kairos-partiel.js", html)
        self.assertNotIn("paquets/commun.js", html)
        self.assertIn("paquets/app.css", html)
        self.assertIn('<svg class="logo-kairos logo-connexion"', html)
        self.assertNotIn("img/kairos-logo", html)


if __name__ == "__main__":
    unittest.main()

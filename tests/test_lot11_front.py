"""Tests du lot 11, partie front et performance (audit front du 2026-10-08) :
compression gzip, statiques versionnés en cache long, fenêtre de tâche
chargée à la demande, tâches closes repliées, « Rejoindre cette tâche »,
sélecteur d'intervenant.

Même principe que tests/test_smoke.py (psycopg2 simulé, repositories
remplacés par des mocks).
"""
import gzip
import io
import re
import unittest
from unittest.mock import patch

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
except ImportError:  # python -m unittest tests.test_lot11_front
    from tests import test_smoke as smoke

from flask import send_file  # noqa: E402

from app import create_app  # noqa: E402

TACHE_OUVERTE = {**smoke.TACHES_PROJET[0], "id": 7, "titre": "Note de calcul", "etat": "en_cours", "intervenants": []}
TACHE_ARRETEE = {**smoke.TACHES_PROJET[0], "id": 8, "titre": "Variante abandonnée", "etat": "arret", "intervenants": []}
TACHES = [smoke.TACHES_PROJET[0], TACHE_OUVERTE, smoke.TACHES_PROJET[1], TACHE_ARRETEE]


class _Base(smoke.SmokeBase):
    def _requete(self, chemin, en_tetes=None, **overrides):
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        try:
            return self.client.get(chemin, headers=en_tetes or {})
        finally:
            for p in reversed(patchers):
                p.stop()


class TestCompressionGzip(_Base):
    def test_page_html_compressee_si_acceptee(self):
        resp = self._requete("/projets/1", {"Accept-Encoding": "gzip, deflate, br"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["Content-Encoding"], "gzip")
        self.assertIn("Accept-Encoding", resp.headers["Vary"])
        html = gzip.decompress(resp.data).decode()
        self.assertIn("Tour Meridian", html)
        self.assertEqual(int(resp.headers["Content-Length"]), len(resp.data))
        brut = self._requete("/projets/1")
        self.assertNotIn("Content-Encoding", brut.headers)
        self.assertIn("Accept-Encoding", brut.headers["Vary"])
        self.assertLess(len(resp.data), len(brut.data) / 3)

    def test_pas_de_gzip_refuse_ou_petite_reponse(self):
        resp = self._requete("/projets/1", {"Accept-Encoding": "gzip;q=0, identity"})
        self.assertNotIn("Content-Encoding", resp.headers)
        # Fragment JSON de moins de 1 Ko : jamais compressé.
        resp = self._requete("/projets/code-propose?phase=EXE", {"Accept-Encoding": "gzip"})
        self.assertEqual(resp.status_code, 200)
        self.assertLess(len(resp.data), 1024)
        self.assertNotIn("Content-Encoding", resp.headers)

    def test_desactivable_par_configuration(self):
        class SansGzip(smoke.TestConfig):
            COMPRESSION_GZIP = False
        self.app = create_app(SansGzip)
        self.client = self.app.test_client()
        resp = self._requete("/projets/1", {"Accept-Encoding": "gzip"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Content-Encoding", resp.headers)

    def test_variable_d_environnement(self):
        import importlib
        from app import config
        with patch.dict("os.environ", {"COMPRESSION_GZIP": "false"}):
            self.assertFalse(importlib.reload(config).Config.COMPRESSION_GZIP)
        self.assertTrue(importlib.reload(config).Config.COMPRESSION_GZIP)

    def test_fichier_envoye_jamais_compresse(self):
        """Un fichier servi tel quel (pièce jointe, export) n'est jamais
        recompressé, même s'il est en text/html."""
        @self.app.route("/_test/fichier")
        def _fichier():
            return send_file(io.BytesIO(b"<p>" + b"x" * 5000 + b"</p>"), mimetype="text/html")
        resp = self.client.get("/_test/fichier", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Content-Encoding", resp.headers)
        self.assertEqual(len(resp.data), 5007)
        resp.close()


class TestStatiquesVersionnes(_Base):
    def _url(self, fichier):
        with self.app.test_request_context():
            from flask import url_for
            return url_for("static", filename=fichier)

    def test_url_avec_empreinte_et_cache_immuable(self):
        url = self._url("css/app.css")
        self.assertRegex(url, r"^/static/css/app\.css\?v=[0-9a-f]{12}$")
        resp = self.client.get(url, headers={"Accept-Encoding": "gzip"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertEqual(resp.headers["Content-Encoding"], "gzip")
        self.assertIn(b".taskrow", gzip.decompress(resp.data))
        self.assertTrue(resp.headers["ETag"].startswith('W/"'))
        # Revalidation : l'ETag faible reste valable (304).
        resp2 = self.client.get(url, headers={"Accept-Encoding": "gzip", "If-None-Match": resp.headers["ETag"]})
        self.assertEqual(resp2.status_code, 304)
        resp.close()
        resp2.close()

    def test_empreinte_perimee_ou_absente_sans_cache_long(self):
        for url in ("/static/css/app.css", "/static/css/app.css?v=000000000000"):
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200)
                self.assertNotIn("immutable", resp.headers.get("Cache-Control", ""))
                resp.close()

    def test_toutes_les_pages_referencent_des_statiques_versionnes(self):
        html = self._requete("/projets/1").data.decode()
        statiques = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
        self.assertTrue(statiques)
        for url in statiques:
            self.assertRegex(url, r"\?v=[0-9a-f]{12}$")

    def test_image_binaire_non_compressee(self):
        url = self._url("img/kairos-logo.png")
        resp = self.client.get(url, headers={"Accept-Encoding": "gzip"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Content-Encoding", resp.headers)
        self.assertIn("immutable", resp.headers["Cache-Control"])
        resp.close()


if __name__ == "__main__":
    unittest.main()

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


class TestFenetreTacheALaDemande(_Base):
    def test_une_seule_fenetre_dans_la_fiche(self):
        html = self._requete("/projets/1", **{"app.repositories.taches.list_taches_projet": TACHES}).data.decode()
        self.assertEqual(html.count('class="post-dialog tache-dialog"'), 1)
        self.assertNotIn('id="dialog-tache-5"', html)
        self.assertNotIn("Marquer comme terminée", html)
        self.assertIn('data-url="/projets/1/taches/0/fenetre"', html)

    def test_fragment_meme_contenu_que_l_ancienne_fenetre(self):
        resp = self._requete("/projets/1/taches/5/fenetre")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["X-Kairos-Fragment"], "tache")
        html = resp.data.decode()
        self.assertNotIn("<html", html)
        self.assertIn('data-tache-fenetre="5"', html)
        self.assertIn('data-titre="Plan ferraillage voile R+2"', html)
        self.assertIn('action="/projets/1/taches/5/titre"', html)
        self.assertIn('action="/projets/1/taches/5/etat"', html)
        self.assertIn("Marquer comme terminée", html)
        self.assertIn("note_calcul.pdf", html)
        # Retour après un envoi de fichier : la fiche, pas le fragment.
        self.assertIn('name="next" value="/projets/1"', html)

    def test_memes_droits_que_la_fiche(self):
        for overrides in ({"app.repositories.projets.user_can_view": False},
                          {"app.repositories.projets.get_projet": None}):
            with self.subTest(overrides=list(overrides)):
                self.assertEqual(self._requete("/projets/1/taches/5/fenetre", **overrides).status_code, 404)
        # Tâche d'un autre projet (absente de la liste de CE projet).
        self.assertEqual(self._requete("/projets/1/taches/999/fenetre").status_code, 404)

    def test_connexion_requise(self):
        resp = self.client.get("/projets/1/taches/5/fenetre")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/connexion", resp.headers["Location"])
        self.assertNotIn("X-Kairos-Fragment", resp.headers)

    def test_lecture_seule_sans_formulaire_d_etat(self):
        html = self._requete("/projets/1/taches/6/fenetre", **{
            "app.auth.get_user_by_id": {**smoke.USER, "id": 3, "role": "intervenant"},
            "app.repositories.projets.user_can_manage": False,
        }).data.decode()
        self.assertIn('class="tache-fenetre-titre"', html)
        self.assertNotIn('action="/projets/1/taches/6/etat"', html)
        self.assertNotIn("Rejoindre cette tâche", html)  # tâche 6 terminée


class TestTachesClosesEtRejoindre(_Base):
    def _fiche(self, **overrides):
        overrides.setdefault("app.repositories.taches.list_taches_projet", TACHES)
        return self._requete("/projets/1", **overrides).data.decode()

    def test_taches_closes_repliees(self):
        html = self._fiche()
        avant, closes = html.split('<details class="taches-closes"', 1)
        closes = closes.split("</details>", 1)[0]
        self.assertIn("Afficher les 2 tâches closes", closes)
        for tid in (6, 8):
            self.assertIn(f'data-open-tache="{tid}"', closes)
            self.assertNotIn(f'data-open-tache="{tid}"', avant)
        for tid in (5, 7):
            self.assertIn(f'data-open-tache="{tid}"', avant)
        self.assertIn('role="table" aria-label="Tâches du projet"', avant)
        self.assertIn('href="#posts-projet"', avant)

    def test_rejoindre_jamais_sur_une_tache_close_et_hors_tabulation(self):
        html = self._fiche()
        self.assertIn('formaction="/projets/1/taches/7/rejoindre"', html)
        for tid in (5, 6, 8):  # 5 : déjà intervenant ; 6 et 8 : closes
            self.assertNotIn(f"/projets/1/taches/{tid}/rejoindre", html)
        bouton = re.search(r'<button[^>]*formaction="/projets/1/taches/7/rejoindre"[^>]*>', html).group(0)
        self.assertIn('tabindex="-1"', bouton)
        self.assertIn('form="form-rejoindre-tache"', bouton)
        self.assertEqual(html.count('id="form-rejoindre-tache"'), 1)
        # Une seule tabulation par ligne : le titre.
        ligne = html.split('data-open-tache="7"', 1)[1].split('role="row"', 1)[0]
        focalisables = re.findall(r"<(?:button|a|input|select)\b(?![^>]*tabindex=\"-1\")[^>]*>", ligne)
        self.assertEqual(len(focalisables), 1, focalisables)
        # Au clavier, « Rejoindre » est dans la fenêtre de la tâche.
        fragment = self._requete("/projets/1/taches/7/fenetre", **{
            "app.repositories.taches.list_taches_projet": TACHES}).data.decode()
        self.assertIn('action="/projets/1/taches/7/rejoindre"', fragment)
        fragment = self._requete("/projets/1/taches/8/fenetre", **{
            "app.repositories.taches.list_taches_projet": TACHES}).data.decode()
        self.assertNotIn("/rejoindre", fragment)

    def test_toutes_closes(self):
        html = self._fiche(**{"app.repositories.taches.list_taches_projet": [smoke.TACHES_PROJET[1]]})
        self.assertIn("Aucune tâche en cours.", html)
        self.assertIn("Afficher la tâche close", html)


class TestSelecteurIntervenant(_Base):
    ACTIFS = smoke.UTILISATEURS_ACTIFS + [
        {"id": 8, "prenom": "Karim", "nom": "Client", "poste": "", "role": "client"},
        {"id": 9, "prenom": "Hélène", "nom": "Ben Salah", "poste": "Dessinatrice", "role": "intervenant"},
        {"id": 10, "prenom": "Sami", "nom": "Chef", "poste": "", "role": "chef_de_projet", "avatar_chemin": "a.png"},
    ]

    def test_champ_de_recherche_avec_candidats(self):
        html = self._requete("/projets/1", **{"app.repositories.utilisateurs.list_actifs": self.ACTIFS}).data.decode()
        self.assertNotIn("+ Ajouter un intervenant</summary>", html)
        select = re.search(r'<select id="ajout-intervenant-choix".*?</select>', html, re.S).group(0)
        for attr in ("data-search-combobox", "data-search-riche", "data-search-action", 'name="utilisateur_id"'):
            self.assertIn(attr, select)
        # Ni membres (1, 3), ni client (8).
        self.assertNotIn('value="1"', select)
        self.assertNotIn('value="3"', select)
        self.assertNotIn("Karim", select)
        self.assertIn('data-sous-titre="Intervenant · Dessinatrice"', select)
        self.assertIn('data-sous-titre="Chef de projet"', select)
        self.assertIn('data-photo="/fichiers/avatars/10"', select)
        self.assertIn('id="carte-intervenants"', html)
        self.assertIn('action="/projets/1/intervenants"', html)
        self.assertIn("js/projet-intervenants.js", html)
        # Sans JavaScript : bouton d'envoi classique.
        self.assertIn("<noscript><button type=\"submit\"", html)

    def test_rien_a_ajouter(self):
        html = self._requete("/projets/1").data.decode()
        self.assertNotIn('id="ajout-intervenant-choix"', html)
        self.assertIn("Toutes les personnes affectables sont déjà sur ce projet.", html)

    def test_reserve_au_gestionnaire_d_un_projet_ouvert(self):
        for overrides in ({"app.repositories.projets.user_can_manage": False},
                          {"app.repositories.projets.get_projet": {**smoke.PROJET, "etat": "termine"}}):
            with self.subTest(overrides=list(overrides)):
                html = self._requete("/projets/1", **{"app.repositories.utilisateurs.list_actifs": self.ACTIFS,
                                                      **overrides}).data.decode()
                self.assertNotIn('id="ajout-intervenant-choix"', html)


if __name__ == "__main__":
    unittest.main()

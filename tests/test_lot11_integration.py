"""Intégration du lot 11 (branche back + branche front) : points de
raccord entre les deux — en-têtes de cache et compression, avatars,
« Rejoindre » une tâche close, fenêtre de tâche (dates, heures),
photos du sélecteur d'intervenant.

Même principe que tests/test_smoke.py (psycopg2 simulé, repositories
remplacés par des mocks).
"""
import datetime
import gzip
import os
import re
import unittest
from unittest.mock import patch

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
except ImportError:  # python -m unittest tests.test_lot11_integration
    from tests import test_smoke as smoke

from app import utils  # noqa: E402
from app.repositories import taches as taches_repo  # noqa: E402

AVATAR = "avatars/1/photo-l11.png"
PIECE = "taches/5/note-l11.pdf"


def _ecrire(relatif: str, contenu: bytes) -> None:
    chemin = os.path.join(smoke._UPLOAD_DIR_TESTS, relatif)
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "wb") as f:
        f.write(contenu)


class _Base(smoke.SmokeBase):
    def _get(self, chemin, en_tetes=None, **overrides):
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        try:
            return self.client.get(chemin, headers=en_tetes or {})
        finally:
            for p in reversed(patchers):
                p.stop()


class TestCacheEtCompression(_Base):
    """Ordre des after_request : _entetes_securite (no-store) PUIS perf
    (gzip) — la compression porte sur les en-têtes définitifs."""

    def test_page_authentifiee_no_store_et_gzip(self):
        resp = self._get("/projets/1", {"Accept-Encoding": "gzip"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["Cache-Control"], "no-store")
        self.assertEqual(resp.headers["Content-Encoding"], "gzip")
        self.assertIn("Accept-Encoding", resp.headers["Vary"])
        self.assertNotIn("ETag", resp.headers)
        self.assertIn("Tour Meridian", gzip.decompress(resp.data).decode())

    def test_statique_versionne_reste_immuable_meme_connecte(self):
        html = self._get("/projets/1").data.decode()
        # Fichier statique et paquet (app/paquets.py, lot 13).
        for motif in (r'src="(/static/js/kairos-amorce\.js\?v=[0-9a-f]{12})"', r'href="(/static/paquets/app\.css\?v=[0-9a-f]{12})"'):
            url = re.search(motif, html).group(1)
            resp = self._get(url, {"Accept-Encoding": "gzip"})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers["Cache-Control"], "public, max-age=31536000, immutable")
            self.assertEqual(resp.headers["Content-Encoding"], "gzip")
            resp.close()

    def test_piece_jointe_no_store_jamais_compressee(self):
        _ecrire(PIECE, b"%PDF-1.4 " + b"x" * 4000)
        resp = self._get("/fichiers/taches/1", {"Accept-Encoding": "gzip"},
                         **{"app.repositories.taches.get_piece_jointe": {**smoke.PIECE_JOINTE_TACHE, "chemin": PIECE}})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["Cache-Control"], "no-store")
        self.assertNotIn("Content-Encoding", resp.headers)
        self.assertNotIn("ETag", resp.headers)
        resp.close()

    def test_fenetre_de_tache_no_store(self):
        resp = self._get("/projets/1/taches/5/fenetre", {"Accept-Encoding": "gzip"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["Cache-Control"], "no-store")
        self.assertEqual(resp.headers["X-Kairos-Fragment"], "tache")


class TestAvatarCachePrive(_Base):
    def setUp(self):
        super().setUp()
        _ecrire(AVATAR, b"\x89PNG\r\n\x1a\n" + b"0" * 200)
        self.profil = {**smoke.UTILISATEUR_PROFIL, "avatar_chemin": AVATAR}

    def test_url_versionnee_cache_prive_une_heure(self):
        v = utils.avatar_version(AVATAR)
        resp = self._get(f"/fichiers/avatars/1?v={v}", **{"app.repositories.utilisateurs.get_utilisateur": self.profil})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["Cache-Control"], "private, max-age=3600")
        self.assertIn("ETag", resp.headers)
        resp.close()

    def test_sans_empreinte_ou_ancienne_photo_no_store(self):
        for url in ("/fichiers/avatars/1", "/fichiers/avatars/1?v=000000000000"):
            with self.subTest(url=url):
                resp = self._get(url, **{"app.repositories.utilisateurs.get_utilisateur": self.profil})
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.headers["Cache-Control"], "no-store")
                resp.close()

    def test_nouvelle_photo_nouvelle_url(self):
        self.assertNotEqual(utils.avatar_version("avatars/1/a.png"), utils.avatar_version("avatars/1/b.png"))

    def test_gabarits_et_selecteur_utilisent_l_url_versionnee(self):
        taches = [{**smoke.TACHES_PROJET[0], "intervenants": [{"id": 1, "prenom": "Foulen", "nom": "Chedly",
                                                                 "avatar_chemin": AVATAR}]}]
        candidats = [{"id": 9, "prenom": "Omar", "nom": "Aziz", "poste": "Technicien", "role": "intervenant",
                      "avatar_chemin": "avatars/9/o.png"}]
        html = self._get("/projets/1", **{"app.repositories.taches.list_taches_projet": taches,
                                          "app.repositories.utilisateurs.list_actifs": candidats}).data.decode()
        self.assertIn(f'src="/fichiers/avatars/1?v={utils.avatar_version(AVATAR)}"', html)
        # Sélecteur d'intervenant : photo (list_actifs renvoie avatar_chemin).
        self.assertIn(f'data-photo="/fichiers/avatars/9?v={utils.avatar_version("avatars/9/o.png")}"', html)


class TestRejoindreTacheClose(_Base):
    def _post(self, **overrides):
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.taches.add_intervenant", side_effect=taches_repo.TacheClose()) as add:
                resp = self.client.post("/projets/1/taches/6/rejoindre", follow_redirects=True)
        finally:
            for p in reversed(patchers):
                p.stop()
        return resp, add

    def test_refus_serveur_avec_message(self):
        resp, add = self._post()
        add.assert_called_once()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Cette tâche est close : on ne peut plus la rejoindre.", resp.data.decode())
        self.assertNotIn("Vous avez rejoint la tâche.", resp.data.decode())

    def test_etats_clos_communs_au_tableau_et_au_refus(self):
        from app.routes import taches_fenetre
        self.assertEqual(taches_fenetre.ETATS_TACHE_CLOSES, taches_repo.ETATS_CLOS)
        self.assertEqual(set(taches_repo.ETATS_CLOS), {"termine", "verifie", "arret", "abandonne"})


class TestFenetreDatesEtHeures(_Base):
    def test_annee_et_heures_en_h_min(self):
        annee_passee = datetime.date.today().year - 1
        tache = {**smoke.TACHES_PROJET[0], "date_echeance": datetime.date(annee_passee, 11, 17),
                 "heures_cumulees": 5.25, "heures_intervenant": 3.5, "heures_chef": 1.75}
        resp = self._get("/projets/1/taches/5/fenetre", **{"app.repositories.taches.list_taches_projet": [tache]})
        html = resp.data.decode()
        # Lot 13 : pour qui gère le projet, l'échéance est un champ date (année
        # comprise) ; sinon, le texte « 17 nov. <année> ».
        self.assertTrue(f'value="{annee_passee}-11-17"' in html or f"17 nov. {annee_passee}" in html)
        self.assertIn("3\u00a0h\u00a030 intervenants / 1\u00a0h\u00a045 chef de projet", html)
        self.assertNotIn("heures_courtes", html)

    def test_une_seule_tache_demandee_a_la_base(self):
        with patch("app.repositories.taches.list_taches_projet", return_value=[smoke.TACHES_PROJET[0]]) as lister:
            self._login()
            patchers = [p for p in self._patched() if getattr(p, "attribute", "") != "list_taches_projet"]
            for p in patchers:
                p.start()
            try:
                resp = self.client.get("/projets/1/taches/5/fenetre")
            finally:
                for p in reversed(patchers):
                    p.stop()
        self.assertEqual(resp.status_code, 200)
        lister.assert_called_once_with(1, tache_id=5)


class TestRevueRecherche(_Base):
    def test_client_ne_trouve_pas_les_comptes_desactives(self):
        for role, attendu in (("client", False), ("chef_de_projet", True), ("admin", True)):
            with self.subTest(role=role):
                self._login()
                patchers = self._patched(**{"app.auth.get_user_by_id": {**smoke.USER, "role": role},
                                            "app.repositories.projets.search": [],
                                            "app.repositories.taches.search": []})
                for p in patchers:
                    p.start()
                try:
                    with patch("app.repositories.utilisateurs.search", return_value=[]) as chercher:
                        self.assertEqual(self.client.get("/recherche/api?q=omrane").status_code, 200)
                finally:
                    for p in reversed(patchers):
                        p.stop()
                chercher.assert_called_once_with("omrane", limit=6, inclure_inactifs=attendu)

    def test_champ_de_recherche_mentionne_les_taches(self):
        html = self._get("/accueil").data.decode()
        self.assertIn('placeholder="Rechercher un projet, une tâche, une personne…"', html)


if __name__ == "__main__":
    unittest.main()

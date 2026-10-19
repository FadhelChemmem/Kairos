"""Lot 20 — corrections de la revue du 19/10/2026, sans base : catégorie du
fil mémorisée lue par le serveur (12d), marque « vu » par catégorie (12c),
contrôle de santé (7), pool de connexions après un redémarrage de
PostgreSQL (N5). Même principe que tests/test_smoke.py."""
import datetime
import unittest
from unittest.mock import MagicMock, patch

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
except ImportError:  # python -m unittest tests.test_lot20
    from tests import test_smoke as smoke

from app import create_app, db, fil  # noqa: E402

T0 = datetime.datetime(2026, 10, 19, 9, 0, tzinfo=datetime.timezone.utc)


class TestCategorieMemorisee(unittest.TestCase):
    def setUp(self):
        self.app = create_app(smoke.TestConfig)

    def test_cookie_de_la_page_si_l_adresse_n_en_donne_pas(self):
        entete = {"Cookie": "kairos_fil_accueil=activite; kairos_fil_projet=tout"}
        with self.app.test_request_context("/accueil", headers=entete):
            self.assertEqual(fil.categorie_demandee("accueil"), "activite")
            self.assertEqual(fil.categorie_demandee("projet"), "tout")
            self.assertEqual(fil.categorie_demandee(), fil.CATEGORIE_DEFAUT)   # page inconnue
        with self.app.test_request_context("/accueil?fil=echanges", headers=entete):
            self.assertEqual(fil.categorie_demandee("accueil"), "echanges")    # l'adresse d'abord
        with self.app.test_request_context("/accueil", headers={"Cookie": "kairos_fil_accueil=nimporte"}):
            self.assertEqual(fil.categorie_demandee("accueil"), fil.CATEGORIE_DEFAUT)


class TestMarqueVu(unittest.TestCase):
    def setUp(self):
        self.app = create_app(smoke.TestConfig)

    def test_chaque_categorie_vue_jusqu_a_son_dernier_post_affiche(self):
        from app.routes import main

        fil_affiche = [
            {"id": 3, "est_activite": True, "created_at": T0, "auteur_id": 2},
            {"id": 2, "est_activite": False, "created_at": T0 - datetime.timedelta(minutes=5), "auteur_id": 2},
            {"id": 1, "est_activite": False, "created_at": T0 - datetime.timedelta(minutes=9), "auteur_id": 2},
        ]
        avant_lecture = T0 + datetime.timedelta(minutes=1)
        with self.app.test_request_context("/accueil"), \
                patch("app.repositories.posts.fil_vu", return_value={}), \
                patch("app.repositories.posts.compter_non_vus", return_value={"echanges": 0, "activite": 0}), \
                patch("app.repositories.posts.marquer_fil_vu") as marquer:
            main.marquer_nouveaux(1, "tout", fil_affiche, avant_lecture)
            categories, instants = marquer.call_args.args[1], marquer.call_args.args[2]
            self.assertEqual(set(categories), {"echanges", "activite"})
            self.assertEqual(instants, {"echanges": T0 - datetime.timedelta(minutes=5), "activite": T0})
            # Catégorie sans post affiché : l'instant relevé avant la lecture.
            main.marquer_nouveaux(1, "activite", [], avant_lecture)
            self.assertEqual(marquer.call_args.args[2], {"activite": avant_lecture})

    def test_marquage_jamais_en_arriere(self):
        from app.repositories import posts

        with patch.object(db, "execute") as execute:
            posts.marquer_fil_vu(1, ("echanges", "inconnue"), {"echanges": T0})
        sql, params = execute.call_args.args
        self.assertIn("GREATEST(utilisateur_fil_vu.vu_le, EXCLUDED.vu_le)", sql)
        self.assertEqual(params, (1, ["echanges"], [T0]))


class TestSante(smoke.SmokeBase):
    def test_base_joignable(self):
        with patch("app.db.query_one", return_value={"ok": 1}):
            r = self.client.get("/sante")
        self.assertEqual((r.status_code, r.get_data(as_text=True)), (200, "ok\n"))
        self.assertEqual(r.headers["Cache-Control"], "no-store")

    def test_base_injoignable(self):
        with patch("app.db.query_one", side_effect=RuntimeError("base arrêtée")):
            r = self.client.get("/sante")
        self.assertEqual(r.status_code, 503)


class TestPoolConnexionMorte(unittest.TestCase):
    def test_connexion_morte_remplacee(self):
        class Erreur(Exception):
            pass

        morte, vivante = MagicMock(closed=0), MagicMock(closed=0)
        morte.cursor.return_value.execute.side_effect = Erreur("server closed the connection unexpectedly")
        pool = MagicMock()
        pool.getconn.side_effect = [morte, vivante]
        with patch.object(db, "_pool", pool), patch.object(db.psycopg2, "OperationalError", Erreur, create=True):
            self.assertIs(db._connexion_vivante(), vivante)
        pool.putconn.assert_called_once_with(morte, close=True)

    def test_connexion_recente_pretee_sans_controle(self):
        import time

        conn = MagicMock(closed=0)
        db._derniere_utilisation[id(conn)] = time.monotonic()
        pool = MagicMock()
        pool.getconn.return_value = conn
        with patch.object(db, "_pool", pool):
            self.assertIs(db._connexion_vivante(), conn)
        conn.cursor.assert_not_called()


if __name__ == "__main__":
    unittest.main()

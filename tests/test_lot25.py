"""Lot 25, tests unitaires (sans base) : vérification complète du 23/10
après le lot 24 — notifications Windows (PU-01 à PU-14)."""
import os
import threading
import time
import unittest
from unittest import mock

from tests.test_lot24 import _b64, _Env, _Navigateur


class TestServicesPushPublics(_Env):
    """PU-01 (SSRF) : seuls les services push publics sont acceptés."""

    def test_adresses_internes_refusees(self):
        ok = self.push.endpoint_valide
        for bon in ("https://fcm.googleapis.com/fcm/send/x", "https://wns2-par02p.notify.windows.com/w/?token=x",
                    "https://updates.push.services.mozilla.com/wpush/v2/x", "https://web.push.apple.com/x",
                    "https://fcm.googleapis.com:443/x"):
            self.assertTrue(ok(bon), bon)
        for mauvais in ("https://127.0.0.1/x", "https://localhost/x", "https://10.0.0.5/x",
                        "https://169.254.169.254/latest", "https://[::1]/x", "https://192.168.1.20/x",
                        "https://2130706433/x", "https://kairos-db/x", "https://fcm.googleapis.com.pirate.example/x",
                        "https://evilfcm.googleapis.com/x", "https://notify.windows.com/x",
                        "https://fcm.googleapis.com:8443/x", "https://fcm.googleapis.com /x", "https://[::1/x"):
            self.assertFalse(ok(mauvais), mauvais)

    def test_audience_sans_port_par_defaut(self):
        """PU-13 : « aud » = origine sérialisée."""
        self.assertEqual(self.push.origine("https://fcm.googleapis.com:443/fcm/send/x"), "https://fcm.googleapis.com")
        self.assertEqual(self.push.origine("https://fcm.googleapis.com/x"), "https://fcm.googleapis.com")

    def test_redirection_jamais_suivie(self):
        """PU-01 : un 302 est rendu tel quel, aucune deuxième requête."""
        appels = []

        class Reponse:
            status = 302

        class Connexion:
            sock = None

            def __init__(self, hote, port, timeout, context):
                appels.append((hote, port))

            def request(self, *a, **k):
                appels.append("POST")

            def getresponse(self):
                return Reponse()

            def close(self):
                pass

        with mock.patch("http.client.HTTPSConnection", Connexion):
            code = self.push.envoyer(_Navigateur().abonnement(), {"titre": "x", "texte": "y"})
        self.assertEqual(code, 302)
        self.assertEqual(appels, [("fcm.googleapis.com", 443), "POST"])

    def test_service_lent_coupe_au_delai_total(self):
        """PU-02 : un service au goutte-à-goutte est coupé."""
        coupe = threading.Event()

        class Prise:
            def shutdown(self, how):
                coupe.set()

        class Connexion:
            def __init__(self, *a, **k):
                self.sock = Prise()

            def request(self, *a, **k):
                pass

            def getresponse(self):
                if not coupe.wait(5):
                    raise AssertionError("jamais coupé")
                raise OSError("connexion coupée")

            def close(self):
                pass

        with mock.patch("http.client.HTTPSConnection", Connexion), \
             mock.patch.object(self.push, "DELAI_TOTAL_ENVOI", 0.2):
            debut = time.monotonic()
            code = self.push.envoyer(_Navigateur().abonnement(), {"titre": "x", "texte": "y"})
        self.assertEqual(code, 0)
        self.assertLess(time.monotonic() - debut, 2)


class TestClesAbonnement(_Env):
    def test_cles_strictes(self):
        """PU-03 (point hors courbe), PU-08 (caractères parasites)."""
        nav = _Navigateur()
        p, a = _b64(nav.publique), _b64(nav.auth)
        self.assertTrue(self.push.cles_valides(p, a))
        self.assertFalse(self.push.cles_valides(_b64(b"\x04" + b"\x01" * 64), a))
        self.assertFalse(self.push.cles_valides(p + "!" * 300, a))
        self.assertFalse(self.push.cles_valides(p, a + "." * 10))
        self.assertFalse(self.push.cles_valides(p, _b64(b"x" * 8)))
        self.assertFalse(self.push.cles_valides(None, a))
        self.assertFalse(self.push.cles_valides(p, 5))

    def test_une_cle_invalide_n_arrete_pas_le_lot(self):
        """PU-03 : l'abonnement inutilisable est supprimé, les autres reçoivent."""
        nav = _Navigateur()
        mauvais = {"endpoint": "https://fcm.googleapis.com/a", "cle_p256dh": _b64(b"\x04" + b"\x01" * 64),
                   "cle_auth": _b64(nav.auth), "cle_serveur": None}
        bon = {**nav.abonnement("https://fcm.googleapis.com/b"), "cle_serveur": None}
        notif = {"id": 7, "utilisateur_id": 3, "message": "Ali vous a mentionné", "projet_code": "26101X"}

        class R:
            status = 201

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("app.repositories.push.notifications_a_pousser", return_value=[notif]), \
             mock.patch("app.repositories.push.reserver", side_effect=lambda ids: list(ids)), \
             mock.patch("app.repositories.push.abonnements", return_value=[mauvais, bon]), \
             mock.patch("app.repositories.push.supprimer_endpoint") as supprimer:
            self.assertEqual(self.push.traiter([7], ouvreur=lambda r, timeout: R()), 1)
        supprimer.assert_called_once_with("https://fcm.googleapis.com/a")

    def test_ancienne_cle_serveur_ignoree_et_403_retire(self):
        """PU-12 : abonnement d'une autre clé VAPID ignoré ; 403 = retiré."""
        nav = _Navigateur()
        ancien = {**nav.abonnement("https://fcm.googleapis.com/a"), "cle_serveur": "autre"}
        actuel = {**nav.abonnement("https://fcm.googleapis.com/b"), "cle_serveur": self.push.cle_publique()}
        with mock.patch("app.repositories.push.abonnements", return_value=[ancien, actuel]):
            self.assertEqual([a["endpoint"] for a in self.push._abonnements_valides(3)],
                             ["https://fcm.googleapis.com/b"])
        self.assertTrue(self.push.a_retirer(403))
        self.assertTrue(self.push.a_retirer(self.push.CLE_INVALIDE))
        self.assertFalse(self.push.a_retirer(500))
        self.assertFalse(self.push.a_retirer(0))


class TestFileEtEssai(_Env):
    def test_delai_au_dela_du_toast_annuler(self):
        """PU-06 : le toast « Annuler » dure 10 s."""
        self.assertGreater(self.push.DELAI_SECONDES, 10)

    def test_essai_limite(self):
        """PU-14 : une notification d'essai toutes les 15 s au plus."""
        from flask import Flask

        app = Flask(__name__)
        app.testing = True
        self.push._derniers_essais.clear()
        with app.app_context(), mock.patch.object(self.push, "essai", return_value=1) as envoi:
            self.assertTrue(self.push.planifier_essai(42))
            self.assertFalse(self.push.planifier_essai(42))
            self.assertTrue(self.push.planifier_essai(43))
        self.assertEqual(envoi.call_count, 2)
        self.push._derniers_essais.clear()

    def test_libelle_appareil(self):
        ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/150.0.0.0 Safari/537.36")
        self.assertEqual(self.push.appareil_libelle(ua), "Chrome · Windows")
        self.assertEqual(self.push.appareil_libelle(ua + " Edg/150.0"), "Edge · Windows")
        self.assertEqual(self.push.appareil_libelle(None), "Navigateur")


class TestHorlogeLot25(unittest.TestCase):
    def test_plus_jamais_fige(self):
        """SA-L25-02 : après 16 h 40 de session, l'instant avance encore."""
        import datetime
        from zoneinfo import ZoneInfo

        from app.horloge import avancer

        tz = ZoneInfo("Africa/Tunis")
        depart = datetime.datetime(2026, 10, 1, 23, 59, tzinfo=tz)
        heures = [16 * 3600 + 23 * 60, 16 * 3600 + 40 * 60, 16 * 3600 + 40 * 60 + 1, 17 * 3600, 30 * 86400]
        instants = [avancer(depart, h) for h in heures]
        self.assertEqual(instants, sorted(set(instants)))
        self.assertTrue(all(i.date() == depart.date() for i in instants))
        self.assertLess(instants[-1].time(), datetime.time(23, 59, 59, 999000))
        # Reprise d'un instant déjà dans la dernière minute : continuité.
        milieu = avancer(depart, 3600)
        self.assertAlmostEqual((avancer(milieu, 3600) - avancer(depart, 7200)).total_seconds(), 0, delta=1e-5)

    def test_sans_heure_pose_juste_avant_minuit_et_garde_fou(self):
        """SB-04 : posée à 23:59:59,5 réelle, la date part de 23:59:00 ; et
        deux instants d'une session ne sont jamais égaux."""
        import datetime
        from zoneinfo import ZoneInfo

        from flask import Flask, g

        from app import horloge

        tz = ZoneInfo("Africa/Tunis")
        app = Flask(__name__)
        app.secret_key = "x" * 40
        pose = datetime.datetime(2026, 10, 19, 23, 59, 59, 500000, tzinfo=tz).timestamp()
        with app.test_request_context("/"):
            g.date_simulee = datetime.date(2026, 10, 17)
            g.heure_simulee = None
            g.simulation_posee_le = pose
            vus = []
            for apres in (60, 400, 600, 601, 3600, 3600, 3600):
                with mock.patch("app.horloge.datetime") as faux:
                    faux.datetime = _HorlogeFigee.a(datetime.datetime.fromtimestamp(pose + apres, datetime.timezone.utc))
                    faux.timezone, faux.timedelta, faux.time, faux.date = (datetime.timezone, datetime.timedelta,
                                                                           datetime.time, datetime.date)
                    vus.append(horloge.instant_simule())
        self.assertEqual(vus, sorted(set(vus)))
        self.assertTrue(all(v.date() == datetime.date(2026, 10, 17) for v in vus))
        self.assertLess(vus[0].time(), datetime.time(23, 59, 1))


class TestMentionsLot25(unittest.TestCase):
    def test_nom_plus_long_non_tague_pas_coupe(self):
        """U8 : « @Ali Ben Salah » non tagué n'est pas coupé par « @Ali Ben »."""
        from flask import Flask

        from app.utils import texte_avec_mentions

        app = Flask(__name__)
        actifs = [{"prenom": "Ali", "nom": "Ben"}, {"prenom": "Ali", "nom": "Ben Salah"}]
        with app.app_context(), mock.patch("app.repositories.utilisateurs.list_actifs", return_value=actifs):
            html = str(texte_avec_mentions("Voir @Ali Ben Salah et @ali ben.", [{"prenom": "Ali", "nom": "Ben"}]))
        self.assertEqual(html.count("post-comment-mention"), 1)
        self.assertIn('<span class="post-comment-mention">@ali ben</span>', html)
        # Hors requête : seules les personnes taguées (comportement d'avant).
        self.assertEqual(str(texte_avec_mentions("@Ali Ben", [{"prenom": "Ali", "nom": "Ben"}])).count("mention"), 1)


class _HorlogeFigee:
    @staticmethod
    def a(instant):
        import datetime

        class D(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

        return D


if __name__ == "__main__":
    unittest.main()

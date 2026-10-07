"""Revue 2 du lot 10 (2026-10-07) : correctifs de textes et d'affichage.

- `date_fr` écrit « 1er » le premier du mois (comme le titre du Daily log) ;
- la carte « Daily log — semaine dernière » de Mon profil n'est plus
  montrée au RH ni à un Client (ses liens menaient à « Accès réservé ») ;
- textes du Daily log : pluriel explicite (plus de « ligne(s) »), messages
  d'échec d'un jour quitté.
"""
import datetime
import unittest

try:
    import test_smoke as smoke
except ImportError:  # lancé depuis la racine du dépôt
    from tests import test_smoke as smoke

from app import utils  # noqa: E402
from app.routes import dailylog as routes  # noqa: E402


class TestDateFr(unittest.TestCase):
    def test_premier_du_mois(self):
        self.assertEqual(utils.date_fr(datetime.date(2026, 10, 1)), "Jeudi 1er octobre 2026")

    def test_autres_jours(self):
        self.assertEqual(utils.date_fr(datetime.date(2026, 10, 2)), "Vendredi 2 octobre 2026")
        self.assertEqual(utils.date_fr(None), "")


class TestCarteDailylogDuProfil(smoke.SmokeBase):
    def _page(self, role):
        return self._get("/utilisateurs/moi", **{"app.auth.get_user_by_id": {**smoke.USER, "role": role}})

    def test_absente_pour_rh_et_client(self):
        for role in ("rh", "client"):
            with self.subTest(role=role):
                resp = self._page(role)
                self.assertEqual(resp.status_code, 200)
                corps = resp.get_data(as_text=True)
                self.assertNotIn("Daily log — semaine dernière", corps)
                self.assertNotIn("/dailylog?date=", corps)

    def test_presente_pour_les_roles_qui_saisissent(self):
        for role in ("admin", "chef_de_projet", "intervenant"):
            with self.subTest(role=role):
                corps = self._page(role).get_data(as_text=True)
                self.assertIn("Daily log — semaine dernière", corps)


class TestTextesDailylog(unittest.TestCase):
    def test_pluriel_explicite(self):
        t = routes.TEXTES_DAILYLOG
        self.assertNotIn("(s)", t["copie_exclues"] + t["copie_exclues_pl"])
        self.assertIn("{x} ligne non reprise", t["copie_exclues"])
        self.assertIn("{x} lignes non reprises", t["copie_exclues_pl"])

    def test_echec_d_un_jour_quitte(self):
        t = routes.TEXTES_DAILYLOG
        for cle in ("non_enregistre_autre_jour", "cause_reseau", "cause_serveur", "brouillon_garde", "revenir"):
            self.assertTrue(t[cle], cle)
        self.assertIn("{x}", t["non_enregistre_autre_jour"])
        self.assertIn("{y}", t["non_enregistre_autre_jour"])


if __name__ == "__main__":
    unittest.main()

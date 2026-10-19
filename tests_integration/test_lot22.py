"""Lot 22 : filtres de « Tous les projets » mémorisés (retour du gérant :
ils revenaient aux valeurs par défaut)."""
from tests_integration.test_lot12 import _Base


class TestFiltresProjetsMemorises(_Base):
    def test_choix_garde_puis_oublie(self):
        termine = self.projet(self.chef, etat="termine", code="T9999X")
        self.login(self.chef)
        page = self.texte(self.client.get("/projets"))
        self.assertNotIn("T9999X", page)                       # défaut : En cours + Bloqué
        r = self.client.get("/projets?filtres_actifs=1&etat=termine&chef_id=%d" % self.chef)
        self.assertIn("T9999X", self.texte(r))
        self.assertIn("kairos_projets_filtres=", r.headers.get("Set-Cookie", ""))
        # Menu, nouvel onglet, F5 sur /projets : le dernier choix revient.
        page = self.texte(self.client.get("/projets"))
        self.assertIn("T9999X", page)
        self.assertRegex(page, r'<option value="termine" selected')
        # Partiel (puces) : mémorisé aussi.
        self.client.get("/projets?filtres_actifs=1&etat=en_cours", headers={"X-Kairos-Partiel": "#projets-resultats",
                                                                           "X-Requested-With": "XMLHttpRequest"})
        self.assertNotIn("T9999X", self.texte(self.client.get("/projets")))
        # « Filtres par défaut » : le choix est oublié.
        self.client.get("/projets?filtres_actifs=1&etat=termine")
        r = self.client.get("/projets?defaut=1")
        self.assertEqual((r.status_code, r.headers["Location"]), (302, "/projets"))
        self.assertIn("kairos_projets_filtres=;", r.headers.get("Set-Cookie", ""))
        self.assertNotIn("T9999X", self.texte(self.client.get("/projets")))
        self.assertTrue(termine)

    def test_cookie_forge_ignore(self):
        self.login(self.chef)
        self.client.set_cookie("kairos_projets_filtres", "filtres_actifs=1&etat=termine&chef_id=abc&x=<script>",
                               path="/projets")
        r = self.client.get("/projets")
        self.assertEqual(r.status_code, 200)
        self.assertRegex(self.texte(r), r'<option value="termine" selected')   # clé inconnue et id invalide ignorés
        self.client.set_cookie("kairos_projets_filtres", "x" * 5000, path="/projets")
        self.assertEqual(self.client.get("/projets").status_code, 200)

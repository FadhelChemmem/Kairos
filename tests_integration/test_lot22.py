"""Lot 22 : filtres de « Tous les projets » mémorisés (retour du gérant :
ils revenaient aux valeurs par défaut). Lot 23 (décision du 20/10) : par
personne, en base — plus par cookie du navigateur."""
from tests_integration.test_lot12 import _Base

PARTIEL = {"X-Kairos-Partiel": "#projets-resultats", "X-Requested-With": "XMLHttpRequest"}


class TestFiltresProjetsMemorises(_Base):
    def test_choix_garde_puis_oublie(self):
        self.projet(self.chef, etat="termine", code="T9999X")
        self.login(self.chef)
        page = self.texte(self.client.get("/projets"))
        self.assertNotIn("T9999X", page)                       # défaut : En cours + Bloqué
        # Choix à l'écran (puces, en partiel) : mémorisé.
        r = self.client.get("/projets?filtres_actifs=1&etat=termine&chef_id=%d" % self.chef, headers=PARTIEL)
        self.assertIn("T9999X", self.texte(r))
        self.assertNotIn("kairos_projets_filtres", r.headers.get("Set-Cookie", ""))
        # Menu, nouvel onglet, F5 sur /projets : le dernier choix revient.
        page = self.texte(self.client.get("/projets"))
        self.assertIn("T9999X", page)
        self.assertRegex(page, r'<option value="termine" selected')
        # Un ancien onglet rechargé (adresse complète, sans geste) n'écrase rien.
        self.client.get("/projets?filtres_actifs=1&etat=en_cours")
        self.assertIn("T9999X", self.texte(self.client.get("/projets")))
        # Sans JavaScript : le bouton « Filtrer » (choix=1) mémorise.
        self.client.get("/projets?filtres_actifs=1&etat=en_cours&choix=1")
        self.assertNotIn("T9999X", self.texte(self.client.get("/projets")))
        # « Filtres par défaut » : le choix est oublié.
        self.client.get("/projets?filtres_actifs=1&etat=termine", headers=PARTIEL)
        r = self.client.get("/projets?defaut=1")
        self.assertEqual((r.status_code, r.headers["Location"]), (302, "/projets"))
        self.assertNotIn("T9999X", self.texte(self.client.get("/projets")))

    def test_par_personne(self):
        self.projet(self.chef, etat="termine", code="T9999X")
        self.login(self.chef)
        self.client.get("/projets?filtres_actifs=1&etat=termine", headers=PARTIEL)
        self.login(self.admin)
        self.assertNotIn("T9999X", self.texte(self.client.get("/projets")))       # pas le choix du chef
        self.login(self.chef)
        self.assertIn("T9999X", self.texte(self.client.get("/projets")))

    def test_valeurs_memorisees_forgees_ignorees(self):
        self.sql("INSERT INTO utilisateur_preference (utilisateur_id, filtres) VALUES (%s, %s::jsonb)",
                 (self.chef, '{"projets": "filtres_actifs=1&etat=termine&chef_id=abc&x=<script>"}'))
        self.login(self.chef)
        r = self.client.get("/projets")
        self.assertEqual(r.status_code, 200)
        self.assertRegex(self.texte(r), r'<option value="termine" selected')   # clé inconnue et id invalide ignorés

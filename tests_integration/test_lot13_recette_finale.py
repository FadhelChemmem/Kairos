"""Lot 13, recette finale (correctifs G) sur un vrai PostgreSQL : rappels
simulés visibles seulement sous date simulée et purgés à la déconnexion
comme à la coupure du mode test (F3) ; double envoi de la confirmation de
clôture (message fondé sur l'effet)."""
import datetime
import re

from werkzeug.datastructures import MultiDict

from tests_integration.test_lot13_correctifs_f1 import _Temps
from tests_integration.test_lot13_projets import _Projets


class TestRappelsSimulesFinDuTest(_Temps):
    def setUp(self):
        super().setUp()
        self.sql("UPDATE utilisateur SET date_embauche = %s WHERE id = %s",
                 (self.auj - datetime.timedelta(days=90), self.inter))

    def simulees(self):
        return self.compter("SELECT count(*) AS n FROM notification WHERE simulee")

    def creer_rappel_simule(self):
        self.login(self.admin)
        self.simuler(self.auj + datetime.timedelta(days=7))
        self.entrer(self.inter, mode="agir")
        self.client.post("/admin/rappel-simule", data={"next": "/accueil"})
        self.assertEqual(self.simulees(), 1)

    def test_invisible_en_agir_comme_au_reel(self):
        self.creer_rappel_simule()
        self.assertEqual(self.client.get("/notifications/compte").get_json()["non_lues"], 1)
        # Rappel laissé en base (ancien comportement) : au réel, rien ne se voit.
        with self.client.session_transaction() as s:
            s.pop("date_simulee", None)
        self.assertEqual(self.client.get("/notifications/compte").get_json()["non_lues"], 0)
        self.assertNotIn("[Simulation]", self.texte(self.client.get("/notifications")))

    def test_purges_a_la_deconnexion(self):
        self.creer_rappel_simule()
        self.assertEqual(self.client.post("/deconnexion").status_code, 302)
        self.assertEqual(self.simulees(), 0)
        # Reconnexion (la déconnexion a révoqué les sessions de l'Admin).
        self.sql("DELETE FROM utilisateur_session WHERE utilisateur_id = %s", (self.admin,))
        self.entrer(self.inter, mode="agir")
        self.assertEqual(self.client.get("/notifications/compte").get_json()["non_lues"], 0)
        self.assertNotIn("[Simulation]", self.texte(self.client.get("/notifications")))

    def test_purges_a_la_coupure_du_mode_test(self):
        self.creer_rappel_simule()
        self.app.config["MODE_TEST"] = False
        try:
            self.assertEqual(self.client.get("/accueil").status_code, 200)
            self.assertEqual(self.simulees(), 0)
        finally:
            self.app.config["MODE_TEST"] = True

    def test_purges_a_la_coupure_avec_date_simulee_seule(self):
        self.login(self.admin)
        self.simuler(self.auj + datetime.timedelta(days=7))
        self.client.post("/admin/rappel-simule", data={"next": "/accueil"})
        n = self.simulees()
        self.app.config["MODE_TEST"] = False
        try:
            self.client.get("/accueil")
            self.assertEqual(self.simulees(), 0, n)
        finally:
            self.app.config["MODE_TEST"] = True


class TestDoubleEnvoiDeLaCloture(_Projets):
    def test_renvoi_sur_un_projet_deja_clos(self):
        self.login(self.chef)
        r = self.informations(self.p1, etat="termine")
        champs = MultiDict([(n, v) for n, v in re.findall(
            r'<input type="hidden" name="([a-z_]+)" value="([^"]*)">', self.texte(r)) if n != "csrf_token"])
        r = self.client.post(f"/projets/{self.p1}/informations", data=champs)
        self.assertIn("Projet clos avec sa tâche ouverte (terminée).", self.flash(r))
        posts = self.compter("SELECT count(*) AS n FROM post WHERE projet_id = %s", (self.p1,))
        # Second envoi identique (double clic, rejeu) : rien n'est clos.
        r = self.client.post(f"/projets/{self.p1}/informations", data=champs)
        self.assertEqual(r.status_code, 302)
        message = self.flash(r)
        self.assertNotIn("Projet clos avec", message)
        self.assertIn("Projet déjà clos", message)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM post WHERE projet_id = %s", (self.p1,)), posts)
        self.assertEqual(self.etat(self.p1), "termine")

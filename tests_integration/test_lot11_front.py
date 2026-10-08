"""Lot 11 (front) sur vraie base : fenêtre de tâche chargée à la demande
(mêmes droits que la fiche projet) et ajout d'intervenant depuis le
sélecteur (POST existant, carte renvoyée par la fiche)."""
from tests_integration.base import BaseIntegration


class TestFenetreTache(BaseIntegration):
    def test_droits_identiques_a_la_fiche(self):
        chef, inter = self.user("chef_de_projet"), self.user("intervenant")
        autre_equipe = self.user("intervenant", equipe="URBS")
        rh = self.user("rh", equipe=None)
        p = self.projet(chef)
        p2 = self.projet(chef)
        t = self.tache(p, chef, intervenants=(inter,))
        t2 = self.tache(p2, chef)

        self.login(inter)
        r = self.client.get(f"/projets/{p}/taches/{t}/fenetre")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["X-Kairos-Fragment"], "tache")
        self.assertIn(f'data-tache-fenetre="{t}"', r.data.decode())
        # Tâche d'un autre projet par l'URL de ce projet : 404.
        self.assertEqual(self.client.get(f"/projets/{p}/taches/{t2}/fenetre").status_code, 404)
        for uid in (autre_equipe, rh):
            with self.subTest(uid=uid):
                self.login(uid)
                self.assertEqual(self.client.get(f"/projets/{p}").status_code, 404)
                self.assertEqual(self.client.get(f"/projets/{p}/taches/{t}/fenetre").status_code, 404)

    def test_fiche_sans_fenetre_pre_rendue_et_taches_closes_repliees(self):
        chef = self.user("chef_de_projet")
        p = self.projet(chef)
        ouverte = self.tache(p, chef)
        close = self.tache(p, chef, etat="termine")
        self.login(chef)
        page = self.client.get(f"/projets/{p}").data.decode()
        self.assertEqual(page.count("<dialog class=\"post-dialog tache-dialog\""), 1)
        avant, closes = page.split('<details class="taches-closes"', 1)
        self.assertIn(f'data-open-tache="{ouverte}"', avant)
        self.assertIn(f'data-open-tache="{close}"', closes)
        self.assertNotIn(f"/taches/{close}/rejoindre", page)


class TestSelecteurIntervenant(BaseIntegration):
    def test_candidats_et_ajout(self):
        chef, inter = self.user("chef_de_projet"), self.user("intervenant")
        nouveau = self.user("intervenant")
        client = self.user("client")
        inactif = self.user("intervenant", actif=False)
        p = self.projet(chef)
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s)", (p, inter))
        self.login(chef)
        page = self.client.get(f"/projets/{p}").data.decode()
        select = page.split('id="ajout-intervenant-choix"', 1)[1].split("</select>", 1)[0]
        self.assertIn(f'value="{nouveau}"', select)
        for uid in (chef, inter, client, inactif):
            self.assertNotIn(f'value="{uid}"', select)
        # Le POST du sélecteur : redirection vers la fiche, dont la carte
        # « Intervenants » contient la personne (lue par projet-intervenants.js).
        r = self.client.post(f"/projets/{p}/intervenants", data={"utilisateur_id": nouveau}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        page = r.data.decode()
        carte = page.split('id="carte-intervenants"', 1)[1]
        self.assertIn("Intervenant ajouté.", page)
        self.assertIn(f"/utilisateurs/{nouveau}/profil", carte)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM projet_intervenant WHERE projet_id=%s AND utilisateur_id=%s",
                                  (p, nouveau))[0]["n"], 1)

"""Décisions du gérant (fin du lot 10) sur vrai PostgreSQL : états de tâche
réservés (route, repository et trigger de la migration 0015) et ce que
voit un Client. Ignorés sans KAIROS_TEST_DATABASE_URL."""
import datetime

from tests_integration.base import BaseIntegration


class TestEtatsReserves(BaseIntegration):
    def _contexte(self, etat="en_cours"):
        chef = self.user("chef_de_projet")
        co_chef = self.user("chef_de_projet")
        admin = self.user("admin", None)
        inter = self.user("intervenant")
        p = self.projet(chef, debut=datetime.date(2026, 1, 5))
        self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s)", (p, co_chef))
        t = self.tache(p, chef, etat=etat, intervenants=(inter,))
        return chef, co_chef, admin, inter, p, t

    def _etat(self, t):
        return self.sql("SELECT etat FROM tache WHERE id=%s", (t,))[0]["etat"]

    def test_intervenant_refuse_dans_les_deux_sens(self):
        chef, _, _, inter, p, t = self._contexte()
        self.login(inter)
        for etat in ("verifie", "arret", "abandonne"):
            self.client.post(f"/projets/{p}/taches/{t}/etat", data={"etat": etat})
            self.assertEqual(self._etat(t), "en_cours")
        self.client.post(f"/projets/{p}/taches/{t}/etat", data={"etat": "bloque"})
        self.assertEqual(self._etat(t), "bloque")
        for reserve in ("verifie", "arret", "abandonne"):
            self.sql("UPDATE tache SET etat=%s WHERE id=%s", (reserve, t))  # sans acteur : libre
            self.client.post(f"/projets/{p}/taches/{t}/etat", data={"etat": "en_cours"})
            self.assertEqual(self._etat(t), reserve)
            self.client.post(f"/projets/{p}/taches/{t}/cloturer", data={"type_code": "envoi"})
            self.assertEqual(self._etat(t), reserve)
        # Aucun post « changement d'état » ni de clôture créé par ces refus.
        self.assertEqual(self.sql("SELECT count(*) AS n FROM post WHERE tache_id=%s AND auteur_id=%s "
                                  "AND evenement IN ('etat_tache', 'cloture_tache')", (t, inter))[0]["n"], 1)

    def test_intervenant_garde_terminee_et_rouvre_une_tache_terminee(self):
        _, _, _, inter, p, t = self._contexte()
        self.login(inter)
        self.client.post(f"/projets/{p}/taches/{t}/cloturer", data={"type_code": "envoi"})
        self.assertEqual(self._etat(t), "termine")
        self.client.post(f"/projets/{p}/taches/{t}/etat", data={"etat": "en_cours"})
        self.assertEqual(self._etat(t), "en_cours")

    def test_chef_co_chef_et_admin_autorises(self):
        chef, co_chef, admin, _, p, t = self._contexte()
        for qui in (chef, co_chef, admin):
            self.login(qui)
            for etat in ("verifie", "en_cours", "arret", "bloque", "abandonne", "en_cours"):
                self.client.post(f"/projets/{p}/taches/{t}/etat", data={"etat": etat})
                self.assertEqual(self._etat(t), etat)
            self.client.post(f"/projets/{p}/taches/{t}/etat", data={"etat": "arret"})
            self.client.post(f"/projets/{p}/taches/{t}/cloturer", data={"type_code": "envoi"})
            self.assertEqual(self._etat(t), "termine")
            self.client.post(f"/projets/{p}/taches/{t}/etat", data={"etat": "verifie"})
            self.assertEqual(self._etat(t), "verifie")
            self.client.post(f"/projets/{p}/taches/{t}/etat", data={"etat": "en_cours"})
            self.assertEqual(self._etat(t), "en_cours")

    def test_repository_sans_peut_gerer_et_trigger_en_base(self):
        from app.repositories import taches
        _, _, _, inter, p, t = self._contexte(etat="verifie")
        with self.assertRaises(taches.EtatReserve):
            taches.set_etat(t, p, "en_cours", inter)
        # Même en se déclarant gestionnaire, l'intervenant est arrêté par le
        # trigger de la migration 0015 (dernier rempart).
        with self.assertRaises(Exception) as ctx:
            taches.set_etat(t, p, "en_cours", inter, peut_gerer=True)
        self.assertTrue(taches.est_refus_etat_reserve(ctx.exception))
        self.assertEqual(self._etat(t), "verifie")
        with self.assertRaises(Exception) as ctx:
            self.sql("SELECT set_config('app.current_user_id', %s, true); "
                     "UPDATE tache SET etat='en_cours' WHERE id=%s", (str(inter), t))
        self.assertTrue(taches.est_refus_etat_reserve(ctx.exception))
        self.assertEqual(self._etat(t), "verifie")

    def test_chef_desactive_refuse_en_base(self):
        from app.repositories import taches
        chef, _, _, _, p, t = self._contexte()
        self.sql("UPDATE utilisateur SET actif=false WHERE id=%s", (chef,))
        with self.assertRaises(Exception) as ctx:
            taches.set_etat(t, p, "verifie", chef, peut_gerer=True)
        self.assertTrue(taches.est_refus_etat_reserve(ctx.exception))

    def test_interface_n_affiche_que_les_etats_autorises(self):
        chef, _, _, inter, p, t = self._contexte()
        self.login(inter)
        # Lot 11 : la fenêtre de la tâche est un fragment chargé à la demande.
        dialogue = self.client.get(f"/projets/{p}/taches/{t}/fenetre").data.decode()
        self.assertIn('<option value="bloque"', dialogue)
        self.assertNotIn('<option value="verifie"', dialogue)
        self.assertNotIn('<option value="abandonne"', dialogue)
        self.login(chef)
        dialogue = self.client.get(f"/projets/{p}/taches/{t}/fenetre").data.decode()
        self.assertIn('<option value="abandonne"', dialogue)


class TestClientVoitHeuresHonorairesPiecesJointes(BaseIntegration):
    def test_client_de_l_equipe(self):
        import io
        import openpyxl
        chef, inter = self.user("chef_de_projet"), self.user("intervenant")
        client = self.user("client")
        p = self.projet(chef, debut=datetime.date(2026, 1, 5))
        self.sql("UPDATE projet SET honoraires = 12500, client = 'IPCO' WHERE id=%s", (p,))
        t = self.tache(p, chef, intervenants=(inter,))
        hier = datetime.date.today() - datetime.timedelta(days=1)
        self.sql("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures) "
                 "VALUES (%s, %s, %s, %s, 3.5)", (inter, hier, p, t))
        chemin = "taches/client-test.pdf"
        import os
        dossier = os.path.join(self.app.config["UPLOAD_DIR"], "taches")
        os.makedirs(dossier, exist_ok=True)
        with open(os.path.join(dossier, "client-test.pdf"), "wb") as f:
            f.write(b"%PDF client")
        pj = self.sql("INSERT INTO tache_piece_jointe (tache_id, nom_fichier, chemin, uploaded_by) "
                      "VALUES (%s, 'note.pdf', %s, %s) RETURNING id", (t, chemin, chef))[0]["id"]

        self.login(client)
        page = self.client.get(f"/projets/{p}").data.decode()
        self.assertIn("Honoraires", page)
        self.assertIn("3\u00a0h\u00a030", page)  # lot 11 : heures et minutes
        # Pièce jointe : dans la fenêtre de la tâche, chargée à la demande (lot 11).
        fenetre = self.client.get(f"/projets/{p}/taches/{t}/fenetre")
        self.assertEqual(fenetre.status_code, 200)
        self.assertIn(f'href="/fichiers/taches/{pj}"', fenetre.data.decode())
        r = self.client.get(f"/fichiers/taches/{pj}")
        self.assertEqual((r.status_code, r.data), (200, b"%PDF client"))
        r.close()
        feuille = openpyxl.load_workbook(io.BytesIO(self.client.get("/projets/export.xlsx").data)).active
        lignes = list(feuille.iter_rows(values_only=True))
        self.assertEqual(lignes[1][lignes[0].index("Honoraires")], 12500)
        self.assertEqual(lignes[1][lignes[0].index("Heures intervenants")], 3.5)
        profil = self.client.get(f"/utilisateurs/{inter}/profil").data.decode()
        self.assertIn('id="dailylog"', profil)
        self.assertIn("3\u00a0h\u00a030", profil)

        # L'intervenant, lui, ne lit toujours pas le Daily log d'un collègue.
        collegue = self.user("intervenant")
        self.login(collegue)
        self.assertNotIn('id="dailylog"', self.client.get(f"/utilisateurs/{inter}/profil").data.decode())


class TestEmailsModeTest(BaseIntegration):
    def test_lien_rh_hors_liste_aucun_jeton_aucun_envoi(self):
        from unittest.mock import patch
        rh = self.user("rh")
        cible = self.user("intervenant", email="w.rekik@midgard.tn")
        autorisee = self.user("intervenant", email="Kairos@MidgardEngineering.com")
        self.app.config.update(SMTP_HOST="smtp.exemple.tn", SMTP_USE_TLS=False,
                               APP_BASE_URL="https://kairos.exemple.tn",
                               MAIL_DESTINATAIRES_AUTORISES="medfadhelchemmem@gmail.com,@midgardengineering.com")
        try:
            self.login(rh)
            with patch("smtplib.SMTP") as smtp:
                self.client.post(f"/utilisateurs/{cible}/envoyer-lien")
                smtp.assert_not_called()
                self.client.post(f"/utilisateurs/{autorisee}/envoyer-lien")
                smtp.assert_called_once()
            jetons = {r["id"]: r["reset_token_hash"] for r in self.sql(
                "SELECT id, reset_token_hash FROM utilisateur WHERE id IN (%s, %s)", (cible, autorisee))}
            self.assertIsNone(jetons[cible])
            self.assertIsNotNone(jetons[autorisee])
        finally:
            self.app.config.update(SMTP_HOST=None, MAIL_DESTINATAIRES_AUTORISES="", APP_BASE_URL="")

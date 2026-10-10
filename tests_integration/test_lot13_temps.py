"""Lot 13 sur un vrai PostgreSQL — audit temps (T-I1–T-I3, T-M1–T-M9) et
décision 5 du gérant : la date simulée sert à VOIR le futur (aucune
écriture datée après la vraie date, app et base), dates de clôture
LEAST(date simulée, vraie date), instant simulé lu au fuseau de chacun,
plusieurs onglets (empreinte du mode), rappels simulés, calendrier."""
import datetime
import re

from tests_integration.test_lot12 import _Base


class _Temps(_Base):
    MODE_TEST = True

    def setUp(self):
        super().setUp()
        self.guyane = self.user("intervenant")
        self.sql("UPDATE utilisateur SET prenom = 'Gia', nom = 'Guyane', fuseau = 'America/Cayenne', date_embauche = %s "
                 "WHERE id = %s", (self.auj - datetime.timedelta(days=90), self.guyane))
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, self.guyane))

    def simuler(self, jour, heure=""):
        r = self.client.post("/admin/date-simulee", data={"date": jour.isoformat(), "heure": heure})
        self.assertEqual(r.status_code, 302)

    def put(self, jour, minutes=60, **entetes):
        return self.client.put(f"/dailylog/api/jour/{jour.isoformat()}", headers=entetes,
                               json={"version": 0, "lignes": [{"projet_id": self.p1, "tache_id": None, "minutes": minutes}]})

    def empreinte(self, page):
        return re.search(r'<meta name="kairos-mode" content="([^"]*)"', self.texte(page)).group(1)


class TestFuturReel(_Temps):
    """T-I1, T-I2 (décision 5)."""

    def test_saisie_refusee_apres_la_vraie_date_meme_sous_date_simulee(self):
        futur = self.auj + datetime.timedelta(days=4)
        self.login(self.admin)
        self.simuler(futur)
        self.entrer(self.inter, mode="agir")
        jour = self.client.get(f"/dailylog/api/jour/{futur.isoformat()}").get_json()
        self.assertTrue(jour["droits"]["futur_reel"])
        self.assertTrue(jour["droits"]["lecture_seule"])
        self.assertFalse(jour["droits"]["saisie_libre"])
        r = self.put(futur)
        self.assertEqual((r.status_code, r.get_json()["erreur"]), (422, "futur_reel"))
        self.assertIn("vraie date du jour", r.get_json()["message"])
        r = self.client.post(f"/dailylog/api/jour/{futur.isoformat()}/absence", json={"version": 0, "absent": True})
        self.assertEqual((r.status_code, r.get_json()["erreur"]), (422, "futur_reel"))
        # Le jour réel reste saisissable sous date simulée.
        self.assertEqual(self.put(self.auj).status_code, 200)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM dailylog_entree WHERE date > %s", (self.auj,)), 0)

    def test_garde_en_base(self):
        futur = self.auj + datetime.timedelta(days=2)
        with self.assertRaises(Exception) as refus:
            with self.db.get_cursor(user_id=self.inter) as cur:
                cur.execute("SET LOCAL kairos.instant_simule = %s", (f"{futur.isoformat()}T12:00:00+01:00",))
                cur.execute("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, 1)",
                            (self.inter, futur, self.p1))
        self.assertIn("vraie date du jour", str(refus.exception))

    def test_dates_de_cloture_jamais_dans_le_futur_reel(self):
        self.login(self.admin)
        self.simuler(self.auj + datetime.timedelta(days=11))
        self.client.post(f"/projets/{self.p1}/taches/{self.t1}/cloturer", data={"type_code": "envoi"})
        self.assertEqual(self.sql("SELECT date_fin FROM tache WHERE id = %s", (self.t1,))[0]["date_fin"], self.auj)
        self.client.post(f"/projets/{self.p2}/informations",
                         data={"nom": "Projet", "etat": "termine", "confirmer_cloture": "1",
                               "taches_a_clore": str(self.t2)})
        projet = self.sql("SELECT etat, date_cloture FROM projet WHERE id = %s", (self.p2,))[0]
        self.assertEqual((projet["etat"], projet["date_cloture"]), ("termine", self.auj))
        self.assertEqual(self.sql("SELECT date_fin FROM tache WHERE id = %s", (self.t2,))[0]["date_fin"], self.auj)
        # Date simulée PASSÉE : la clôture prend cette date.
        passe = self.auj - datetime.timedelta(days=6)
        self.simuler(passe)
        t3 = self.tache(self.p1, self.chef)
        self.client.post(f"/projets/{self.p1}/taches/{t3}/cloturer", data={"type_code": "envoi"})
        self.assertEqual(self.sql("SELECT date_fin FROM tache WHERE id = %s", (t3,))[0]["date_fin"], passe)


class TestOnglets(_Temps):
    """T-I3 : l'onglet envoie l'empreinte du mode qu'il affiche."""

    def test_formulaire_d_un_onglet_reste_sur_un_autre_mode(self):
        self.login(self.admin)
        page = self.client.get("/accueil")
        empreinte = self.empreinte(page)
        self.assertEqual(empreinte, f"u{self.admin}-soi-reel")
        self.assertIn("/static/js/mode-onglets.js", self.texte(page))
        # Autre onglet : date simulée (route de mode : jamais refusée).
        self.client.post("/admin/date-simulee", data={"date": (self.auj + datetime.timedelta(days=5)).isoformat(),
                                                      "_mode": empreinte})
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/cloturer",
                             data={"type_code": "envoi", "_mode": empreinte},
                             headers={"Referer": f"http://localhost/projets/{self.p1}"})
        self.assertEqual((r.status_code, r.headers["Location"]), (303, f"/projets/{self.p1}"))
        self.assertIn("Le mode a changé dans un autre onglet", self.visible(self.client.get(r.headers["Location"])))
        self.assertEqual(self.sql("SELECT etat FROM tache WHERE id = %s", (self.t1,))[0]["etat"], "en_cours")
        # Avec l'empreinte à jour : accepté.
        nouvelle = self.empreinte(self.client.get("/accueil"))
        self.assertRegex(nouvelle, rf"^u{self.admin}-soi-{(self.auj + datetime.timedelta(days=5)).isoformat()}$")
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/cloturer", data={"type_code": "envoi", "_mode": nouvelle})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.sql("SELECT etat FROM tache WHERE id = %s", (self.t1,))[0]["etat"], "termine")

    def test_fetch_d_un_onglet_reste_sur_un_autre_compte(self):
        self.login(self.admin)
        reel = self.empreinte(self.client.get("/dailylog"))
        self.entrer(self.inter, mode="agir")
        r = self.put(self.auj - datetime.timedelta(days=1), **{"X-Kairos-Mode": reel})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.headers.get("X-Kairos-Mode-Change"), "1")
        self.assertEqual(r.get_json()["erreur"], "mode_change")
        self.assertEqual(self.compter("SELECT count(*) AS n FROM dailylog_entree"), 0)
        agi = self.empreinte(self.client.get("/dailylog"))
        self.assertEqual(agi, f"u{self.inter}-agir-reel")
        self.assertEqual(self.put(self.auj - datetime.timedelta(days=1), **{"X-Kairos-Mode": agi}).status_code, 200)
        # Sans empreinte (client hors navigateur, ancien onglet) : pas de contrôle.
        self.assertEqual(self.put(self.auj - datetime.timedelta(days=2)).status_code, 200)

    def test_connexion_jamais_bloquee(self):
        self.login(self.inter)
        r = self.client.post("/deconnexion", data={"_mode": "u999-soi-reel"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/connexion"))


class TestInstantSimule(_Temps):
    """T-M3, T-M4, T-M5 : instant simulé à Tunis, lu au fuseau de chacun."""

    def test_heure_simulee_et_fuseau_de_la_personne(self):
        self.login(self.admin)
        # 2 h du matin à Tunis = 22 h la veille à Cayenne.
        jour = self.auj - datetime.timedelta(days=3)
        self.simuler(jour, "02:00")
        page = self.visible(self.client.get("/accueil"))
        self.assertIn("à 02:00 (Tunis)", page)
        self.entrer(self.guyane, mode="agir")
        jour_guyane = self.client.get(f"/dailylog/api/jour/{(jour - datetime.timedelta(days=1)).isoformat()}").get_json()
        self.assertEqual(jour_guyane["aujourdhui"], (jour - datetime.timedelta(days=1)).isoformat())
        r = self.client.get(f"/dailylog/api/jour/{jour.isoformat()}")
        self.assertEqual((r.status_code, r.get_json()["erreur"]), (422, "date_future"))
        # En base aussi : fn_aujourdhui au fuseau de la personne.
        with self.app.test_request_context("/"):
            from flask import g
            g.date_simulee, g.heure_simulee = jour, datetime.time(2, 0)
            with self.db.get_cursor() as cur:
                cur.execute("SELECT fn_aujourdhui('America/Cayenne') AS g, fn_aujourdhui() AS t")
                ligne = cur.fetchone()
        self.assertEqual((ligne["g"], ligne["t"]), (jour - datetime.timedelta(days=1), jour))
        self.client.post("/admin/revenir")
        self.entrer(self.inter, mode="agir")
        self.assertEqual(self.client.get(f"/dailylog/api/jour/{jour.isoformat()}").get_json()["aujourdhui"],
                         jour.isoformat())

    def test_heure_invalide_et_horodatages_absolus(self):
        self.login(self.admin)
        r = self.client.post("/admin/date-simulee", data={"date": self.auj.isoformat(), "heure": "25:00"},
                             follow_redirects=True)
        self.assertIn("Heure simulée invalide", self.visible(r))
        self.client.post("/posts", data={"projet_id": str(self.p1), "type_code": "information", "contenu": "Horodaté"})
        self.assertIn("à l'instant", self.texte(self.client.get(f"/projets/{self.p1}")))
        self.simuler(self.auj + datetime.timedelta(days=9))
        page = self.texte(self.client.get(f"/projets/{self.p1}"))
        self.assertNotIn("à l'instant", page)
        self.assertRegex(page, r"\d+ \w+\.? à \d+\xa0h\xa0\d\d")
        self.assertIn('title="Horodatage réel\u00a0: ', page)

    def test_aujourdhui_au_fuseau_de_la_personne(self):
        from app import horloge, utils
        with self.app.test_request_context("/"):
            from flask import g
            g.user = {"id": 1, "fuseau": "America/Cayenne"}
            g.date_simulee, g.heure_simulee = datetime.date(2027, 1, 1), datetime.time(1, 30)
            self.assertEqual(horloge.aujourdhui(), datetime.date(2026, 12, 31))
            self.assertEqual(horloge.aujourdhui("Africa/Tunis"), datetime.date(2027, 1, 1))
            self.assertEqual(utils.date_courte(datetime.date(2026, 10, 14)), "14 oct.")
            self.assertEqual(utils.date_courte(datetime.date(2027, 1, 5)), "5 janv. 2027")
            self.assertEqual(self.app.jinja_env.globals["today"](), datetime.date(2026, 12, 31))


class TestRappelsEtCalendrier(_Temps):
    """T-M1, T-M6, T-M7, T-M8, T-M9."""

    def test_rappel_simule(self):
        self.login(self.admin)
        sim = self.auj + datetime.timedelta(days=7)
        self.simuler(sim)
        self.entrer(self.inter, mode="agir")
        self.assertIn("Simuler le rappel du jour", self.visible(self.client.get("/accueil")))
        r = self.client.post("/admin/rappel-simule", data={"next": "/accueil"}, follow_redirects=True)
        self.assertIn("Rappel simulé du", self.visible(r))
        (n,) = self.sql("SELECT message, rappel_jours, simulee FROM notification WHERE utilisateur_id = %s", (self.inter,))
        self.assertTrue(n["simulee"])
        self.assertTrue(n["message"].startswith("[Simulation] "))
        self.assertTrue(any(j > self.auj for j in n["rappel_jours"]))
        # Rejoué : aucun doublon.
        self.client.post("/admin/rappel-simule")
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE utilisateur_id = %s", (self.inter,)), 1)
        # Le vrai rappel ignore le rappel simulé (il peut citer les mêmes jours).
        from app.auth import _verifier_rappel_dailylog
        from app.repositories import dailylog
        personne = dict(self.sql("SELECT id, fuseau, date_embauche AS debut_daily_log FROM utilisateur WHERE id = %s",
                                 (self.inter,))[0])
        _verifier_rappel_dailylog(personne, aujourdhui=dailylog.aujourdhui_pour(personne))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE utilisateur_id = %s AND NOT simulee",
                                      (self.inter,)), 1)
        # « Voir comme » : lecture seule ; un non-Admin : 403.
        self.client.post("/admin/revenir")
        self.entrer(self.inter)
        self.assertEqual(self.client.post("/admin/rappel-simule").status_code, 403)
        self.client.post("/admin/revenir")
        self.login(self.chef)
        self.assertEqual(self.client.post("/admin/rappel-simule").status_code, 403)

    def test_rappel_sorti_de_la_fenetre_marque_lu(self):
        from app.repositories import notifications
        vieux = [self.auj - datetime.timedelta(days=30), self.auj - datetime.timedelta(days=29)]
        recent = [self.auj - datetime.timedelta(days=3)]
        notifications.creer_rappel_dailylog(self.inter, vieux, lambda j: "vieux")
        notifications.creer_rappel_dailylog(self.inter, recent, lambda j: "récent")
        notifications.marquer_rappels_dailylog_lus(self.inter)
        lus = {r["message"]: r["lu"] for r in self.sql("SELECT message, lu FROM notification WHERE utilisateur_id = %s",
                                                       (self.inter,))}
        self.assertEqual(lus, {"vieux": True, "récent": False})

    def test_notification_de_correction_une_fois_par_jour_reel(self):
        self.login(self.admin)
        hier = self.auj - datetime.timedelta(days=1)
        self.simuler(self.auj + datetime.timedelta(days=12))
        for minutes in (60, 90):
            r = self.client.put(f"/dailylog/api/jour/{hier.isoformat()}?utilisateur={self.inter}",
                                json={"version": 0 if minutes == 60 else 1,
                                      "lignes": [{"projet_id": self.p1, "tache_id": None, "minutes": minutes}]})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE utilisateur_id = %s "
                                      "AND message LIKE 'Daily log du %%'", (self.inter,)), 1)

    def test_calendrier_jours_verrouilles(self):
        self.login(self.inter)
        avant = self.auj - datetime.timedelta(days=40)
        mois = self.client.get(f"/dailylog/api/mois/{avant.strftime('%Y-%m')}").get_json()
        etats = mois["jours"]
        ouvres = [k for k, v in etats.items() if v == "verrouille"]
        self.assertTrue(ouvres)
        for k in ouvres:
            d = datetime.date.fromisoformat(k)
            self.assertLess(d.weekday(), 5)
            self.assertLess(d, self.auj - datetime.timedelta(days=14))
        import json
        page = self.texte(self.client.get("/dailylog"))
        textes = json.loads(re.search(r'<script type="application/json" id="dl-textes">(.*?)</script>', page, re.S).group(1))
        self.assertEqual(textes["legende"]["verrouille"], "Non renseigné, verrouillé (au-delà de 14 jours)")

    def test_sortie_du_mode_test_journalise_le_compte_vu(self):
        from app import modes_admin
        self.entrer(self.inter, mode="agir")
        self.app.config["MODE_TEST"] = False
        try:
            self.client.get("/accueil")
        finally:
            self.app.config["MODE_TEST"] = True
        sortie = [e for e in self.journal("mode_agir_comme") if e["action"] == "SORTIE"][-1]
        self.assertEqual(sortie["donnees_apres"]["compte_vu"], "Rim Inter")
        self.assertEqual(sortie["donnees_apres"]["role"], "intervenant")
        from app.validation import DATE_MAX, DATE_MIN
        self.assertEqual((modes_admin.DATE_SIMULEE_MIN, modes_admin.DATE_SIMULEE_MAX), (DATE_MIN, DATE_MAX))
        self.assertEqual((DATE_MIN, DATE_MAX), (datetime.date(2000, 1, 1), datetime.date(2099, 12, 31)))

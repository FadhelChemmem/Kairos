"""Lot 13, correctifs des pages après contre-expertise (verif-ux N2,
verif-temps N4/N5, écarts de spécification) sur un vrai PostgreSQL :
bandeau de la date simulée jugé au fuseau du compte agi, Daily log et
accueil sans invitation à saisir sur un jour du futur réel, « Daily log
de » en fragment, toast après le changement de date simulée, barres des
Deadlines qui ouvrent le panneau sur place."""
import datetime
import json
import re

from tests_integration.test_lot13_temps import _Temps

PARTIEL = {"X-Kairos-Partiel": "#dl9", "X-Requested-With": "XMLHttpRequest"}
TEXTE_FUTUR = ("Date simulée future : les saisies datées (Daily log) sont en lecture seule ; "
               "les autres actions sont réelles")


class TestBandeauDateSimulee(_Temps):
    def test_futur_annonce_sans_promettre_la_lecture_seule(self):
        self.login(self.admin)
        self.simuler(self.auj + datetime.timedelta(days=3))
        page = self.visible(self.client.get("/accueil"))
        self.assertIn(TEXTE_FUTUR, page)
        self.assertNotIn("consultation seulement", page)

    def test_futur_juge_au_fuseau_du_compte_agi(self):
        # 01 h 30 à Tunis le lendemain = 20 h 30 la veille à Cayenne : jour
        # réel, saisissable, pour un compte de Guyane ; futur pour Tunis.
        # Entre 0 h et 5 h à Tunis, Cayenne est encore la veille : le cas
        # ne se construit pas (test sensible à l'heure, vu le 17/10 à 1 h).
        import zoneinfo
        if datetime.datetime.now(zoneinfo.ZoneInfo("Africa/Tunis")).hour < 5:
            self.skipTest("nuit à Tunis : Cayenne est encore la veille")
        self.login(self.admin)
        self.simuler(self.auj + datetime.timedelta(days=1), "01:30")
        self.entrer(self.guyane, mode="agir")
        page = self.visible(self.client.get("/accueil"))
        self.assertNotIn(TEXTE_FUTUR, page)
        self.assertRegex(page, r"\(à Cayenne : \w+ \d+ \w+ \d{4}, \d+ h 30\)")
        self.client.post("/admin/revenir")
        self.entrer(self.inter, mode="agir")
        self.assertIn(TEXTE_FUTUR, self.visible(self.client.get("/accueil")))

    def test_toast_apres_le_changement_de_date(self):
        self.login(self.admin)
        jour = self.auj - datetime.timedelta(days=2)
        r = self.client.post("/admin/date-simulee", data={"date": jour.isoformat(), "heure": "09:15", "next": "/deadlines"})
        self.assertEqual(r.headers["Location"], "/deadlines")
        page = self.texte(self.client.get("/deadlines"))
        self.assertRegex(page, r'<template id="k-toasts-initiaux"><p data-type="succes">Date simulée appliquée\u00a0: '
                               r'\w+ \d+ \w+ \d{4} à 09:15 \(Tunis\)\.</p>')
        self.client.post("/admin/date-simulee/effacer", data={"next": "/deadlines"})
        self.assertIn("Retour à la date réelle.", self.texte(self.client.get("/deadlines")))


class TestDailyLogFuturReel(_Temps):
    def amorce(self, page):
        return json.loads(re.search(r'<script type="application/json" id="dl-amorce">(.*?)</script>', page, re.S).group(1))

    def test_jour_du_futur_reel_sans_invitation(self):
        futur = self.auj + datetime.timedelta(days=4)
        self.login(self.admin)
        self.simuler(futur)
        self.entrer(self.inter, mode="agir")
        page = self.client.get(f"/dailylog?date={futur.isoformat()}").get_data(as_text=True)
        jour = self.amorce(page)["jour"]
        self.assertTrue(jour["droits"]["futur_reel"])
        self.assertEqual(jour["aujourdhui_reel"], self.auj.isoformat())
        textes = json.loads(re.search(r'id="dl-textes">(.*?)</script>', page, re.S).group(1))
        self.assertEqual(textes["aucun_projet_futur"], "Jour à venir\u00a0: consultation seulement.")
        # Accueil : les jours après la vraie date ne sont pas « sans saisie »
        # (arrivée aujourd'hui, journée réelle renseignée).
        self.sql("UPDATE utilisateur SET date_embauche = %s WHERE id = %s", (self.auj, self.inter))
        self.sql("INSERT INTO dailylog_jour (utilisateur_id, date, absent) VALUES (%s, %s, true) "
                 "ON CONFLICT (utilisateur_id, date) DO UPDATE SET absent = true", (self.inter, self.auj))
        accueil = self.visible(self.client.get("/accueil"))
        # Lot 15 : rappel compact dans l'en-tête de l'accueil.
        self.assertNotIn("Remplir mon Daily log", accueil)
        self.assertIn("date simulée future : consultation seule", accueil)
        self.assertNotIn("sans saisie", accueil)


class TestDailyLogDe(_Temps):
    def test_fragment_de_la_page_d_une_autre_personne(self):
        self.login(self.chef)
        page = self.client.get("/dailylog").get_data(as_text=True)
        self.assertIn('data-search-combobox data-search-selection data-search-placeholder="Rechercher une personne…"', page)
        self.assertIn('class="dl-tool k-sans-js">Ouvrir</button>', page)
        r = self.client.get(f"/dailylog?utilisateur={self.inter}&date={self.auj.isoformat()}", headers=PARTIEL)
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertNotIn("<html", html)
        self.assertTrue(re.sub(r"\{#.*?#\}", "", html, flags=re.S).lstrip().startswith('<div class="dl9" id="dl9"'))
        amorce = json.loads(re.search(r'id="dl-amorce">(.*?)</script>', html, re.S).group(1))
        self.assertEqual((amorce["proprietaire"]["id"], amorce["proprietaire"]["soi"]), (self.inter, False))
        self.assertIn("Correction du Daily log&nbsp;: <b>Rim Inter</b>", html)
        self.assertIn('id="dl-textes"', html)
        # Sans l'en-tête : la page complète, inchangée.
        self.assertIn("<html", self.client.get(f"/dailylog?utilisateur={self.inter}").get_data(as_text=True))


class TestDeadlinesPanneau(_Temps):
    def test_barres_ouvrent_le_panneau_sur_place(self):
        self.login(self.chef)
        page = self.texte(self.client.get("/deadlines"))
        self.assertIn('id="dialog-tache"', page)
        self.assertIn('data-rafraichir="#deadlines-contenu"', page)
        self.assertIn("/static/js/tache-dialog.js", page)
        url = f"/projets/{self.p1}/taches/{self.t1}/fenetre"
        self.assertIn(f'data-open-tache="{self.t1}" data-tache-url="{url}"', page)
        self.assertRegex(page, rf'<a href="/projets/{self.p1}\?tache={self.t1}" data-ouvrir-tache')
        r = self.client.get(url)
        self.assertEqual((r.status_code, r.headers.get("X-Kairos-Fragment")), (200, "tache"))
        self.assertIn(f'data-url-fiche="/projets/{self.p1}?tache={self.t1}"', r.get_data(as_text=True))

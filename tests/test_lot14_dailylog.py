"""Lot 14 (A3) — tests unitaires (psycopg2 simulé) : tâches en cours
proposées dans le Daily log (revue produit P0-4) et Daily log de l'équipe
(P1-9). Le SQL est joué sur un vrai PostgreSQL dans
tests_integration/test_lot14_dailylog.py."""
import datetime
import pathlib
import re
import unittest
from unittest.mock import patch

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
    import test_dailylog as tdl
except ImportError:  # python -m unittest tests.test_lot14_dailylog
    from tests import test_smoke as smoke
    from tests import test_dailylog as tdl

from app.repositories import dailylog as dl  # noqa: E402
from app.routes import dailylog as routes  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parent.parent
TUNIS = datetime.timezone(datetime.timedelta(hours=1))
PERSONNE = {"id": 7, "fuseau": "Africa/Tunis", "date_embauche": datetime.date(2026, 10, 1), "created_at": None}


class TestFonctionsPures(unittest.TestCase):
    def test_dix_derniers_jours_ouvres_aujourd_hui_compris(self):
        jours = dl.jours_ouvres_recents(datetime.date(2026, 10, 12), 10)   # lundi
        self.assertEqual(jours[0], datetime.date(2026, 10, 12))
        self.assertEqual(jours[1], datetime.date(2026, 10, 9))
        self.assertEqual(len(jours), 10)
        self.assertTrue(all(j.weekday() < 5 for j in jours))
        self.assertEqual(dl.jours_ouvres_recents(datetime.date(2026, 10, 10), 1), [datetime.date(2026, 10, 9)])

    def test_etat_d_une_case(self):
        a = datetime.datetime(2026, 10, 8, 10, 0, tzinfo=TUNIS)   # jeudi 10 h
        apres_16h = a.replace(hour=17)
        cas = [
            (datetime.date(2026, 10, 6), {"minutes": 90}, a, "rempli"),
            (datetime.date(2026, 10, 6), {"absent": True}, a, "absent"),
            (datetime.date(2026, 10, 6), None, a, "manquant"),
            (datetime.date(2026, 10, 8), None, a, "attente"),
            (datetime.date(2026, 10, 8), None, apres_16h, "manquant"),
            (datetime.date(2026, 10, 9), None, a, "futur"),
            (datetime.date(2026, 10, 4), None, a, "week_end"),
            (datetime.date(2026, 9, 30), None, a, "avant"),
            (datetime.date(2026, 9, 30), {"minutes": 60}, a, "rempli"),   # des heures avant l'embauche restent des heures
        ]
        for date, case, maintenant, attendu in cas:
            with self.subTest(date=date, attendu=attendu):
                self.assertEqual(dl.etat_case(PERSONNE, date, case, maintenant), attendu)
        ancienne = {**PERSONNE, "date_embauche": datetime.date(2025, 1, 1)}
        self.assertEqual(dl.etat_case(ancienne, datetime.date(2026, 9, 1), None, a), "verrouille")
        self.assertEqual(dl.etat_case(ancienne, datetime.date(2026, 9, 24), None, a), "manquant")   # J-14

    def test_titre_de_la_semaine(self):
        self.assertEqual(routes._titre_semaine(datetime.date(2026, 10, 5)), "Semaine du 5 au 9 octobre 2026")
        self.assertEqual(routes._titre_semaine(datetime.date(2026, 9, 28)), "Semaine du 28 septembre au 2 octobre 2026")
        self.assertEqual(routes._titre_semaine(datetime.date(2025, 12, 29)),
                         "Semaine du 29 décembre 2025 au 2 janvier 2026")
        self.assertEqual(routes._titre_semaine(datetime.date(2026, 6, 1)), "Semaine du 1er au 5 juin 2026")


class TestLignesProposees(unittest.TestCase):
    def appel(self, taches, projets):
        with patch("app.db.query_all", side_effect=[taches, projets]):
            return dl.lignes_proposees({"id": 7, "fuseau": "Africa/Tunis"}, datetime.date(2026, 10, 8))

    def test_regroupees_par_projet_projet_seul_d_abord(self):
        taches = [{"projet_id": 2, "code": "B", "nom": "Beta", "tache_id": 20, "tache_titre": "T20"},
                  {"projet_id": 1, "code": "A", "nom": "Été", "tache_id": 10, "tache_titre": "T10"}]
        projets = [{"projet_id": 1, "code": "A", "nom": "Été", "gere": True, "recent": False},
                   {"projet_id": 2, "code": "B", "nom": "Beta", "gere": False, "recent": False},
                   {"projet_id": 3, "code": "C", "nom": "Gamma", "gere": False, "recent": False}]
        sortie = [(l["projet_id"], l["tache_id"]) for l in self.appel(taches, projets)]
        # Beta < Été (sans accents) < Gamma ; B suivi avec une tâche : pas de projet seul.
        self.assertEqual(sortie, [(2, 20), (1, None), (1, 10), (3, None)])

    def test_plus_de_8_projets_geres_seulement_les_recents(self):
        projets = [{"projet_id": i, "code": f"P{i}", "nom": f"P{i:02d}", "gere": True, "recent": i in (4, 6)} for i in range(1, 10)]
        self.assertEqual([l["projet_id"] for l in self.appel([], projets)], [4, 6])
        self.assertEqual(len(self.appel([], projets[:8])), 8)

    def test_plafond(self):
        taches = [{"projet_id": 1, "code": "A", "nom": "A", "tache_id": i, "tache_titre": f"T{i}"} for i in range(30)]
        self.assertEqual(len(self.appel(taches, [])), dl.MAX_PROPOSEES)


class TestApiEtPages(tdl._BaseDailyLog):
    PROPOSEES = [{"projet_id": 1, "code": "P1", "nom": "Projet 1", "tache_id": 5, "tache_titre": "Plans"}]

    def test_journee_vierge_de_son_daily_log_seulement(self):
        # Lot 16 : rien de proposé le week-end ; on prend le dernier jour ouvré.
        jour = self.aujourdhui - datetime.timedelta(days=max(0, self.aujourdhui.weekday() - 4))
        resp = self.appel("get", f"/dailylog/api/jour/{jour}", user=tdl.INTERVENANT,
                          **{"app.repositories.dailylog.lignes_proposees": self.PROPOSEES})
        self.assertEqual(resp.get_json()["proposees"], self.PROPOSEES)
        rempli = {**smoke.DAILYLOG_JOUR_VIDE, "version": 1, "lignes": [
            {"projet_id": 1, "tache_id": None, "code": "P1", "nom": "Projet 1", "tache_titre": None, "minutes": 60, "hors_grille": False}]}
        resp = self.appel("get", f"/dailylog/api/jour/{self.aujourdhui}",
                          **{"app.repositories.dailylog.lignes_proposees": self.PROPOSEES,
                             "app.repositories.dailylog.lire_jour": rempli,
                             "app.repositories.dailylog.projets_info": {1: tdl.projet(1)}})
        self.assertEqual(resp.get_json()["proposees"], [])
        resp = self.appel("get", f"/dailylog/api/jour/{self.aujourdhui}?utilisateur=2", user=tdl.CHEF,
                          **{"app.repositories.dailylog.lignes_proposees": self.PROPOSEES,
                             "app.repositories.utilisateurs.get_utilisateur": tdl.EMPLOYE})
        self.assertEqual(resp.get_json()["proposees"], [])

    def test_textes_et_gabarit(self):
        html = self.appel("get", "/dailylog", user=tdl.INTERVENANT).data.decode()
        for attendu in ('id="dl-propositions"', 'id="dl-catalogue-fini"', "Tapez 2,5 ou 2h30", "Retirer la ligne {x}"):
            self.assertIn(attendu, html)
        self.assertNotIn('id="dl-equipe"', html)   # intervenant : pas de lien d'équipe
        self.assertIn('id="dl-equipe"', self.appel("get", "/dailylog", user=tdl.CHEF).data.decode())

    def test_page_equipe_refusee_a_l_intervenant_rendue_au_chef(self):
        resp = self.appel("get", "/dailylog/equipe", user=tdl.INTERVENANT)
        self.assertEqual(resp.status_code, 302)
        resp = self.appel("get", "/dailylog/equipe", user=tdl.CHEF)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Personne à afficher", resp.data.decode())


class TestGardes(unittest.TestCase):
    def test_pas_de_script_en_ligne_ni_de_couleur_en_dur(self):
        for nom in ("dailylog_equipe.html", "partials/dailylog_equipe.html", "partials/dailylog_dix_jours.html"):
            texte = (RACINE / "app" / "templates" / nom).read_text(encoding="utf-8")
            self.assertNotRegex(texte, r"<script(?![^>]*\bsrc=)(?![^>]*application/json)")
            self.assertNotIn("style=", texte)
        css = (RACINE / "app" / "static" / "css" / "lot14-a3.css").read_text(encoding="utf-8")
        self.assertFalse(re.findall(r"#[0-9a-fA-F]{3,6}\b", css))

    def test_feuille_dans_le_paquet(self):
        from app import paquets
        self.assertIn("css/lot14-a3.css", paquets.PAQUETS["app.css"])


if __name__ == "__main__":
    unittest.main()

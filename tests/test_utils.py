"""Tests unitaires purs (aucune base de données) pour app/utils.py."""
import datetime
import unittest

from app.utils import (
    avatar_color, build_gantt, date_courte, il_y_a, initials, is_lien_valide, is_safe_next, post_type_style, projet_etat_style,
    tache_etat_style,
)


class TestInitials(unittest.TestCase):
    def test_normal_names(self):
        self.assertEqual(initials("Foulen", "Chedly"), "FC")

    def test_lowercase_is_uppercased(self):
        self.assertEqual(initials("omar", "aziz"), "OA")

    def test_missing_names_fall_back(self):
        self.assertEqual(initials("", ""), "?")
        self.assertEqual(initials(None, None), "?")


class TestAvatarColor(unittest.TestCase):
    def test_deterministic(self):
        # Le même id doit toujours donner la même couleur (cohérence
        # visuelle d'une page à l'autre pour la même personne).
        self.assertEqual(avatar_color(7), avatar_color(7))

    def test_no_id_returns_a_color(self):
        self.assertTrue(avatar_color(None).startswith("#"))


class TestEtatStyles(unittest.TestCase):
    def test_known_tache_etat(self):
        self.assertEqual(tache_etat_style("bloque")["label"], "Bloqué")
        # Affichage : état de tâche accordé au féminin (lot 10).
        self.assertEqual(tache_etat_style("bloque")["libelle"], "Bloquée")

    def test_unknown_tache_etat_falls_back_gracefully(self):
        style = tache_etat_style("valeur_inconnue")
        self.assertEqual(style["label"], "valeur_inconnue")

    def test_known_projet_etat(self):
        self.assertEqual(projet_etat_style("en_cours")["label"], "En cours")

    def test_known_post_type(self):
        self.assertEqual(post_type_style("requete")["label"], "Requête")


class TestIlYA(unittest.TestCase):
    def test_none_returns_empty_string(self):
        self.assertEqual(il_y_a(None), "")

    def test_recent_past_is_minutes(self):
        dt = datetime.datetime.now() - datetime.timedelta(minutes=5)
        self.assertIn("min", il_y_a(dt))

    def test_hours_ago(self):
        dt = datetime.datetime.now() - datetime.timedelta(hours=3)
        self.assertIn("h", il_y_a(dt))

    def test_yesterday(self):
        dt = datetime.datetime.now() - datetime.timedelta(days=1, hours=1)
        self.assertEqual(il_y_a(dt), "hier")

    def test_plus_d_une_semaine_date_courte_francaise(self):
        # Lot 10 (audit front §7) : « le 5 oct. », plus « 05/10/2026 ».
        dt = datetime.datetime.now() - datetime.timedelta(days=20)
        self.assertEqual(il_y_a(dt), "le " + date_courte(dt))
        ancien = datetime.datetime(2024, 3, 1, 9, 0)
        self.assertEqual(il_y_a(ancien), "le 1er mars 2024")


class TestDateCourte(unittest.TestCase):
    def test_jour_sans_zero_initial_et_premier(self):
        # Lot 24 (SR-02) : année en cours, pour ne pas dépendre de la date.
        annee = datetime.date.today().year
        self.assertEqual(date_courte(datetime.date(annee, 10, 5)), "5 oct.")
        self.assertEqual(date_courte(datetime.date(2026, 10, 5), False), "5 oct.")
        self.assertEqual(date_courte(datetime.date(2026, 6, 1), True), "1er juin 2026")
        self.assertEqual(date_courte(datetime.date(2026, 9, 23)), "23 sept.")
        self.assertEqual(date_courte(None), "")


class TestBuildGantt(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 16)

    def test_days_window_length_and_first_day(self):
        g = build_gantt([], self.TODAY, window_days=21)
        self.assertEqual(len(g["days"]), 21)
        self.assertEqual(g["days"][0]["date"], self.TODAY)

    def test_month_label_shown_on_first_of_month(self):
        g = build_gantt([], datetime.date(2026, 9, 25), window_days=10)
        oct_1 = next(d for d in g["days"] if d["date"] == datetime.date(2026, 10, 1))
        self.assertIn("oct", oct_1["label"])

    def test_overdue_task_is_red_and_flagged(self):
        taches = [{"titre": "Retard", "date_echeance": self.TODAY - datetime.timedelta(days=3)}]
        g = build_gantt(taches, self.TODAY)
        row = g["rows"][0]
        self.assertEqual(row["span"], 1)
        self.assertEqual(row["couleur"], "#c2401f")
        self.assertIn("retard", row["label_barre"])

    def test_imminent_task_is_red(self):
        taches = [{"titre": "Demain", "date_echeance": self.TODAY + datetime.timedelta(days=1)}]
        row = build_gantt(taches, self.TODAY)["rows"][0]
        self.assertEqual(row["couleur"], "#c2401f")
        self.assertEqual(row["span"], 2)

    def test_this_week_task_is_orange(self):
        taches = [{"titre": "Cette semaine", "date_echeance": self.TODAY + datetime.timedelta(days=5)}]
        row = build_gantt(taches, self.TODAY)["rows"][0]
        self.assertEqual(row["couleur"], "#a16207")
        self.assertEqual(row["niveau"], "semaine")

    def test_later_task_is_green(self):
        taches = [{"titre": "Plus tard", "date_echeance": self.TODAY + datetime.timedelta(days=14)}]
        row = build_gantt(taches, self.TODAY)["rows"][0]
        self.assertEqual(row["couleur"], "#4a7c59")

    def test_span_is_clamped_to_window(self):
        taches = [{"titre": "Loin", "date_echeance": self.TODAY + datetime.timedelta(days=60)}]
        row = build_gantt(taches, self.TODAY, window_days=21)["rows"][0]
        self.assertEqual(row["span"], 21)

    def test_task_without_echeance_is_skipped(self):
        taches = [{"titre": "Sans échéance", "date_echeance": None}]
        g = build_gantt(taches, self.TODAY)
        self.assertEqual(g["rows"], [])


class TestIsSafeNext(unittest.TestCase):
    """PROMPT_CORRECTIONS.md P0 #5 : startswith("/") seul acceptait encore
    des formes que les navigateurs traitent comme des URLs absolues."""

    def test_chemin_interne_simple_est_accepte(self):
        self.assertTrue(is_safe_next("/projets/1"))
        self.assertTrue(is_safe_next("/accueil"))

    def test_chemin_interne_avec_query_string_est_accepte(self):
        self.assertTrue(is_safe_next("/dailylog?date=2026-09-10"))

    def test_vide_ou_absent_est_refuse(self):
        self.assertFalse(is_safe_next(""))
        self.assertFalse(is_safe_next(None))

    def test_url_absolue_est_refusee(self):
        self.assertFalse(is_safe_next("https://evil.tld/phishing"))
        self.assertFalse(is_safe_next("http://evil.tld"))

    def test_protocol_relative_est_refuse(self):
        # "//evil.tld" est traité par la plupart des navigateurs comme une
        # URL absolue (même protocole que la page courante, autre hôte).
        self.assertFalse(is_safe_next("//evil.tld"))
        self.assertFalse(is_safe_next("///evil.tld"))

    def test_backslash_est_refuse(self):
        # "/\evil.tld" : certains navigateurs traitent le antislash comme
        # un slash, ce qui en fait aussi une redirection hors site.
        self.assertFalse(is_safe_next("/\\evil.tld"))
        self.assertFalse(is_safe_next("/\\/evil.tld"))

    def test_chemin_sans_slash_initial_est_refuse(self):
        self.assertFalse(is_safe_next("evil.tld"))
        self.assertFalse(is_safe_next("javascript:alert(1)"))


class TestIsLienValide(unittest.TestCase):
    """PROMPT_CORRECTIONS.md P0 #4 : le champ "lien" du composeur de post
    est rendu dans un <a href="..."> — l'échappement Jinja protège le
    texte affiché, jamais le schéma de l'URL."""

    def test_http_et_https_sont_acceptes(self):
        self.assertTrue(is_lien_valide("http://exemple.tn/plan.pdf"))
        self.assertTrue(is_lien_valide("https://exemple.tn/plan.pdf"))

    def test_partage_reseau_est_accepte(self):
        self.assertTrue(is_lien_valide("file://NAS/Projets/26099X/"))
        self.assertTrue(is_lien_valide("smb://nas.local/projets"))

    def test_chemin_unc_est_accepte(self):
        self.assertTrue(is_lien_valide("\\\\NAS\\Projets\\26099X\\"))

    def test_javascript_est_refuse(self):
        self.assertFalse(is_lien_valide("javascript:alert(document.cookie)"))

    def test_data_uri_est_refusee(self):
        self.assertFalse(is_lien_valide("data:text/html,<script>alert(1)</script>"))

    def test_vide_ou_absent_est_refuse(self):
        self.assertFalse(is_lien_valide(""))
        self.assertFalse(is_lien_valide(None))


if __name__ == "__main__":
    unittest.main()

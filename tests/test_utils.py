"""Tests unitaires purs (aucune base de données) pour app/utils.py."""
import datetime
import unittest

from app.utils import avatar_color, build_gantt, il_y_a, initials, post_type_style, projet_etat_style, tache_etat_style


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
        self.assertEqual(row["couleur"], "#e3512c")
        self.assertIn("retard", row["label_barre"])

    def test_imminent_task_is_red(self):
        taches = [{"titre": "Demain", "date_echeance": self.TODAY + datetime.timedelta(days=1)}]
        row = build_gantt(taches, self.TODAY)["rows"][0]
        self.assertEqual(row["couleur"], "#e3512c")
        self.assertEqual(row["span"], 2)

    def test_this_week_task_is_orange(self):
        taches = [{"titre": "Cette semaine", "date_echeance": self.TODAY + datetime.timedelta(days=5)}]
        row = build_gantt(taches, self.TODAY)["rows"][0]
        self.assertEqual(row["couleur"], "#ea6c1a")

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


if __name__ == "__main__":
    unittest.main()

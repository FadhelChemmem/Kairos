"""Tests du lot 11 (décisions du gérant après la mise en service) : liste
des projets paginée, recherche, dates, heures, code projet proposé, en-têtes,
pages d'erreur, encart Admin, rappel Daily log.

Même principe que tests/test_smoke.py (psycopg2 simulé, repositories
remplacés par des mocks). Le SQL est vérifié sur un vrai PostgreSQL par
tests_integration/test_lot11.py et tests/sql/lot11.sql.
"""
import unittest
from unittest.mock import patch

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
except ImportError:  # python -m unittest tests.test_lot11
    from tests import test_smoke as smoke


class _Base(smoke.SmokeBase):
    def _avec(self, appel, **overrides):
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        try:
            return appel()
        finally:
            for p in reversed(patchers):
                p.stop()


class TestListeDesProjets(_Base):
    def _liste(self, url, total, lignes=1, **autres):
        projets = [dict(smoke.PROJET_LISTE_SANS_HEURES, id=i + 1) for i in range(lignes)]
        with patch("app.repositories.projets.list_projets", return_value=projets) as liste, \
                patch("app.repositories.projets.compter_projets", return_value=total) as compte:
            overrides = {k: v for k, v in autres.items()}
            self._login()
            patchers = [p for p in self._patched(**overrides)
                        if p.attribute not in ("list_projets", "compter_projets")]
            for p in patchers:
                p.start()
            try:
                resp = self.client.get(url, headers={"X-Requested-With": "XMLHttpRequest"})
            finally:
                for p in reversed(patchers):
                    p.stop()
        return resp, liste, compte

    def test_vrai_total_et_pages_de_50(self):
        resp, liste, compte = self._liste("/projets?filtres_actifs=1&etat=termine&page=2", total=653, lignes=50)
        body = resp.get_data(as_text=True)
        self.assertIn("653 projets · 51–100 affichés", body)
        self.assertIn("Page 2 sur 14", body)
        self.assertIn('rel="prev"', body)
        self.assertIn('rel="next"', body)
        self.assertIn("page=1", body)
        self.assertIn("page=3", body)
        self.assertIn("etat=termine", body)  # filtres conservés dans les liens
        kwargs = liste.call_args.kwargs
        self.assertEqual((kwargs["limit"], kwargs["offset"]), (50, 50))
        self.assertEqual(compte.call_args.kwargs["etats"], ["termine"])

    def test_page_hors_bornes_ramenee_a_la_derniere(self):
        resp, liste, _ = self._liste("/projets?filtres_actifs=1&page=99", total=120, lignes=20)
        self.assertIn("Page 3 sur 3", resp.get_data(as_text=True))
        self.assertEqual(liste.call_args.kwargs["offset"], 100)
        resp, liste, _ = self._liste("/projets?filtres_actifs=1&page=abc", total=120, lignes=50)
        self.assertEqual(liste.call_args.kwargs["offset"], 0)

    def test_une_seule_page_sans_navigation(self):
        resp, _, _ = self._liste("/projets", total=1)
        body = resp.get_data(as_text=True)
        self.assertIn(">1 projet<", body)
        self.assertNotIn("Page 1 sur", body)

    def test_recherche_ignore_le_filtre_chef_moi_et_le_dit(self):
        chefs = [{"id": 1, "prenom": "Fadhel", "nom": "Chemmem", "avatar_chemin": None}]
        resp, liste, compte = self._liste("/projets?q=louison", total=1, **{
            "app.repositories.projets.list_chefs_de_projet": chefs})
        self.assertIsNone(liste.call_args.kwargs["chef_ids"])
        self.assertIsNone(compte.call_args.kwargs["chef_ids"])
        self.assertEqual(liste.call_args.kwargs["etats"], ["en_cours", "bloque"])
        self.assertIn("le filtre « Chef de projet : vous » est ignoré", resp.get_data(as_text=True))
        # Sans texte : le filtre par défaut s'applique.
        resp, liste, _ = self._liste("/projets", total=1, **{"app.repositories.projets.list_chefs_de_projet": chefs})
        self.assertEqual(liste.call_args.kwargs["chef_ids"], [1])
        self.assertNotIn("est ignoré", resp.get_data(as_text=True))

    def test_recherche_garde_un_filtre_chef_explicite_vers_un_autre(self):
        _, liste, _ = self._liste("/projets?filtres_actifs=1&chef_id=7&q=tour", total=1)
        self.assertEqual(liste.call_args.kwargs["chef_ids"], [7])

    def test_export_sans_plafond(self):
        with patch("app.repositories.projets.list_projets", return_value=[]) as liste:
            self._login()
            patchers = [p for p in self._patched() if p.attribute != "list_projets"]
            for p in patchers:
                p.start()
            try:
                resp = self.client.get("/projets/export.xlsx?filtres_actifs=1")
            finally:
                for p in reversed(patchers):
                    p.stop()
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(liste.call_args.kwargs["limit"])


if __name__ == "__main__":
    unittest.main()

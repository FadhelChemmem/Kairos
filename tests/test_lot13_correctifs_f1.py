"""Lot 13, tour de corrections après contre-expertise (agent back F1) :
curseur du journal, en-tête Expires des statiques, et autres correctifs
vérifiables sans base (psycopg2 simulé, comme tests/test_smoke.py)."""
import datetime
import email.utils
import unittest

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
except ImportError:  # python -m unittest tests.test_lot13_correctifs_f1
    from tests import test_smoke as smoke

from app.routes import admin as admin_routes  # noqa: E402


class TestCurseurJournal(unittest.TestCase):
    def test_valeurs_hors_bornes_postgresql_ignorees(self):
        for valeur in ("2026-10-09T00:00:00_99999999999999999999",
                       "2026-10-09T00:00:00_-9999",
                       "2026-10-09T00:00:00Z_9223372036854775808",
                       "2026-10-09T00:00:00+16:00_1",
                       "0001-01-01T00:00:00+23:59_1",
                       "1999-12-31T23:00:00+00:00_1",
                       "2100-01-01T00:00:00+00:00_1",
                       "2026-10-09T00:00:00_٣",
                       "x_1", "_", "2026-10-09_"):
            with self.subTest(valeur=valeur):
                self.assertIsNone(admin_routes._lire_curseur(valeur))

    def test_curseur_valide_garde(self):
        instant, ident = admin_routes._lire_curseur("2026-10-05T08:00:00+15:59_401")
        self.assertEqual(ident, 401)
        self.assertEqual(instant.year, 2026)
        self.assertEqual(admin_routes._lire_curseur("2026-10-05T08:00:00_999999999999999999")[1],
                         999999999999999999)


class TestExpiresStatiques(smoke.SmokeBase):
    def test_expires_aligne_sur_max_age(self):
        with self.app.test_request_context():
            from flask import url_for
            url = url_for("static", filename="js/mode-onglets.js")
        resp = self.client.get(url)
        self.assertEqual(resp.headers["Cache-Control"], "public, max-age=31536000, immutable")
        expire = email.utils.parsedate_to_datetime(resp.headers["Expires"])
        restant = expire - datetime.datetime.now(datetime.timezone.utc)
        self.assertGreater(restant, datetime.timedelta(days=364))
        self.assertLess(restant, datetime.timedelta(days=366))


if __name__ == "__main__":
    unittest.main()

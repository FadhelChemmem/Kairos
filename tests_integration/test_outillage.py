"""Outillage des tests d'intégration (recette du lot 14, n° 14) : chaque
classe de tests rend ses connexions à la fin (pool fermé), sinon la suite
complète approche la limite du serveur PostgreSQL (« too many clients »)."""
import unittest

from tests_integration.base import URL, BaseIntegration


def _connexions_ouvertes() -> int:
    import psycopg2

    conn = psycopg2.connect(URL)
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND pid <> pg_backend_pid()")
        return int(cur.fetchone()[0])
    finally:
        conn.close()


class TestPoolFermeEntreClasses(unittest.TestCase):
    def test_tear_down_class_rend_les_connexions(self):
        if not URL:
            raise unittest.SkipTest("KAIROS_TEST_DATABASE_URL non défini")

        class Classe(BaseIntegration):
            pass

        Classe.setUpClass()
        avant = _connexions_ouvertes()
        try:
            # Trois curseurs imbriqués : trois connexions du pool.
            # Mesure PENDANT les trois curseurs (lot 15 : mesurée après leur
            # sortie, elle dépendait du délai de fermeture des connexions
            # rendues au pool au-delà de minconn).
            with Classe.db.get_cursor() as a, Classe.db.get_cursor() as b, Classe.db.get_cursor() as c:
                for cur in (a, b, c):
                    cur.execute("SELECT 1")
                self.assertGreaterEqual(_connexions_ouvertes(), avant + 2)
        finally:
            Classe.tearDownClass()
        self.assertLessEqual(_connexions_ouvertes(), avant)
        self.assertIsNone(Classe.db._pool)

"""Contrôles de structure des migrations (sans base) — audit QA du lot 10.

Le comportement réel des migrations est vérifié sur PostgreSQL par
tests_integration/ et par le job CI « schema » ; ici, seulement les
invariants qui ne demandent pas de base :
- chaque fichier de migrations/ est déclaré dans schema.sql (une base neuve
  ne doit pas rejouer une migration déjà intégrée) ;
- numérotation unique et continue ;
- la migration 0013 est rejouable (aucun CREATE sans garde).
"""
import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
MIGRATIONS = sorted((RACINE / "migrations").glob("*.sql"))


class TestMigrationsDeclarees(unittest.TestCase):
    def test_chaque_migration_est_declaree_dans_schema_sql(self):
        schema = (RACINE / "schema.sql").read_text(encoding="utf-8")
        bloc = schema[schema.index("INSERT INTO schema_migrations"):]
        for f in MIGRATIONS:
            with self.subTest(migration=f.name):
                self.assertIn(f"('{f.stem}')", bloc)

    def test_numerotation_unique_et_continue(self):
        numeros = [int(f.name[:4]) for f in MIGRATIONS]
        self.assertEqual(numeros, list(range(1, len(numeros) + 1)))

    def test_0013_rejouable(self):
        sql = (RACINE / "migrations" / "0013_rattrapage_et_integrite.sql").read_text(encoding="utf-8")
        # Tout CREATE TRIGGER est précédé de son DROP TRIGGER IF EXISTS,
        # tout CREATE INDEX / TABLE / FUNCTION est gardé.
        for nom in re.findall(r"CREATE TRIGGER (\w+)", sql):
            with self.subTest(trigger=nom):
                self.assertIn(f"DROP TRIGGER IF EXISTS {nom} ", sql)
        self.assertNotRegex(sql, r"CREATE (UNIQUE )?INDEX (?!IF NOT EXISTS)")
        self.assertNotRegex(sql, r"CREATE TABLE (?!IF NOT EXISTS)")
        self.assertNotRegex(sql, r"CREATE FUNCTION")


if __name__ == "__main__":
    unittest.main()

"""Tests unitaires purs pour scripts/mysqldump_parser.py —
PROMPT_CORRECTIONS.md P1 #14."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from mysqldump_parser import parse_create_tables, parse_inserts  # noqa: E402

CREATE_TABLE_USERS = (
    "CREATE TABLE `users` (\n"
    "  `id` int(11) NOT NULL,\n"
    "  `email` varchar(255) NOT NULL,\n"
    "  `role` varchar(50) NOT NULL,\n"
    "  PRIMARY KEY (`id`)\n"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n"
)


class TestExtendedInsert(unittest.TestCase):
    """Format par défaut de mysqldump (--extended-insert) : pas de liste de
    colonnes, l'ordre de CREATE TABLE fait foi — comportement déjà correct
    avant P1 #14, vérifié ici en non-régression."""

    def test_parse_extended_insert(self):
        sql = CREATE_TABLE_USERS + "INSERT INTO `users` VALUES (1,'a@b.tn','admin'),(2,'c@d.tn','intervenant');\n"
        tables = parse_create_tables(sql)
        data = parse_inserts(sql, tables)
        self.assertEqual(data["users"], [
            {"id": 1, "email": "a@b.tn", "role": "admin"},
            {"id": 2, "email": "c@d.tn", "role": "intervenant"},
        ])


class TestCompleteInsert(unittest.TestCase):
    """PROMPT_CORRECTIONS.md P1 #14 : mysqldump --complete-insert ajoute la
    liste des colonnes entre le nom de table et VALUES — l'ancienne regex ne
    matchait alors plus AUCUN INSERT, et le script se terminait sans erreur
    avec un résultat entièrement vide."""

    def test_parse_complete_insert_meme_ordre_que_create_table(self):
        sql = CREATE_TABLE_USERS + (
            "INSERT INTO `users` (`id`, `email`, `role`) VALUES "
            "(1,'a@b.tn','admin'),(2,'c@d.tn','intervenant');\n"
        )
        tables = parse_create_tables(sql)
        data = parse_inserts(sql, tables)
        self.assertEqual(data["users"], [
            {"id": 1, "email": "a@b.tn", "role": "admin"},
            {"id": 2, "email": "c@d.tn", "role": "intervenant"},
        ])

    def test_parse_complete_insert_ordre_different_de_create_table(self):
        """Rien ne garantit qu'un --complete-insert respecte l'ordre de
        CREATE TABLE — la liste de colonnes explicite du dump doit primer."""
        sql = CREATE_TABLE_USERS + (
            "INSERT INTO `users` (`email`, `id`, `role`) VALUES "
            "('a@b.tn',1,'admin');\n"
        )
        tables = parse_create_tables(sql)
        data = parse_inserts(sql, tables)
        self.assertEqual(data["users"], [{"id": 1, "email": "a@b.tn", "role": "admin"}])


if __name__ == "__main__":
    unittest.main()


class TestVariantesEtEchecBruyant(unittest.TestCase):
    """Audit n°2 : INSERT IGNORE / REPLACE INTO étaient ignorés en silence,
    et une instruction non reconnue produisait une table vide sans erreur."""

    def test_insert_ignore_et_replace_into(self):
        sql = (
            CREATE_TABLE_USERS
            + "INSERT IGNORE INTO `users` VALUES (1,'a@b.tn','admin');\n"
            + "REPLACE INTO `users` VALUES (2,'c@d.tn','intervenant');\n"
        )
        data = parse_inserts(sql, parse_create_tables(sql))
        self.assertEqual([r["id"] for r in data["users"]], [1, 2])

    def test_echec_bruyant_si_une_insertion_nest_pas_lue(self):
        # Dernière instruction sans retour à la ligne final : non lue par
        # la regex, elle doit faire échouer le parsing au lieu d'être perdue.
        sql = CREATE_TABLE_USERS + "INSERT INTO `users` VALUES (1,'a@b.tn','admin');"
        with self.assertRaises(ValueError):
            parse_inserts(sql, parse_create_tables(sql))

    def test_chaines_avec_caracteres_speciaux(self):
        sql = CREATE_TABLE_USERS + (
            "INSERT INTO `users` VALUES (1,'l\\'a;b),(c','x\\\\y'),(2,NULL,'z');\n"
        )
        data = parse_inserts(sql, parse_create_tables(sql))
        self.assertEqual(data["users"][0]["email"], "l'a;b),(c")
        self.assertEqual(data["users"][0]["role"], "x\\y")
        self.assertIsNone(data["users"][1]["email"])

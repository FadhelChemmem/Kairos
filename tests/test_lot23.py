"""Lot 23, tests unitaires (sans base) : adresses web cliquables dans les
posts et les commentaires."""
import unittest


class TestAvecLiens(unittest.TestCase):
    def test_lien_echappe_et_ponctuation_hors_lien(self):
        from app.utils import avec_liens

        html = str(avec_liens("Plans : https://nas.midgard.tn/p?a=1&b=2. Merci <b>"))
        self.assertIn('<a href="https://nas.midgard.tn/p?a=1&amp;b=2" class="lien-texte" target="_blank" '
                      'rel="noopener noreferrer">https://nas.midgard.tn/p?a=1&amp;b=2</a>. Merci &lt;b&gt;', html)

    def test_parentheses_et_schemas_refuses(self):
        from app.utils import avec_liens

        html = str(avec_liens("(voir https://fr.wikipedia.org/wiki/Béton_(matériau)) javascript:alert(1) "
                              "http:// ftp://x"))
        self.assertIn('href="https://fr.wikipedia.org/wiki/Béton_(matériau)"', html)
        self.assertIn("</a>)", html)
        self.assertEqual(html.count("<a "), 1)
        self.assertNotIn('href="javascript', html)

    def test_injection_dans_l_adresse(self):
        from app.utils import avec_liens

        html = str(avec_liens('https://x.tn/"onmouseover="alert(1)'))
        self.assertNotIn('"onmouseover', html.split("</a>")[0].split(">")[0])

    def test_mentions_hors_des_liens(self):
        from app.utils import texte_avec_mentions

        html = str(texte_avec_mentions("@Rim Inter voir https://x.tn/@Rim Inter",
                                       [{"prenom": "Rim", "nom": "Inter"}]))
        self.assertTrue(html.startswith('<span class="post-comment-mention">@Rim Inter</span>'))
        self.assertIn('href="https://x.tn/@Rim"', html)
        self.assertEqual(html.count("post-comment-mention"), 1)   # jamais dans un lien

    def test_vide(self):
        from app.utils import avec_liens

        self.assertEqual(str(avec_liens(None)), "")


if __name__ == "__main__":
    unittest.main()

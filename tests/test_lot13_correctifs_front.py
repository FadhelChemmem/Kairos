"""Lot 13, correctifs après contre-expertise (verif-a11y-perf.md, verif-ux.md)
— règles CSS et gabarit vérifiés sans navigateur ; le rendu est prouvé par
les scénarios Playwright (tests_e2e/partiel.e2e.js, projet.e2e.js)."""
import pathlib
import re
import unittest

RACINE = pathlib.Path(__file__).resolve().parent.parent
CSS = (RACINE / "app" / "static" / "css" / "app.css").read_text(encoding="utf-8")
BASE = (RACINE / "app" / "templates" / "base.html").read_text(encoding="utf-8")


def regles(selecteur_motif):
    """Corps des règles dont le sélecteur correspond au motif."""
    return [corps for sel, corps in re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S))
            if re.search(selecteur_motif, sel)]


class TestCorrectifsCss(unittest.TestCase):
    def test_r3_bascule_de_theme_sans_transition_sur_tous_les_elements(self):
        self.assertNotRegex(CSS, r"k-theme-transition \*")
        corps = regles(r"k-theme-transition")
        self.assertTrue(corps)
        self.assertTrue(all("!important" not in c for c in corps))

    def test_r1_r4_barre_basse_ne_cache_pas_le_focus(self):
        self.assertIn("scroll-padding-bottom: calc(var(--nav-basse-h) + 12px", CSS)
        bloc = CSS[CSS.index("@media (max-height: 480px) {\n  .topbar, .subbar { position: static; }"):]
        self.assertIn(".k-nav-basse { position: static; }", bloc[:900])

    def test_n2_page_decalee_par_le_panneau(self):
        self.assertRegex(CSS, r"body\.tache-panneau-ouvert:not\(:has\(\.tache-panneau-sortie\)\) main, "
                              r"body\.tache-panneau-ouvert:not\(:has\(\.tache-panneau-sortie\)\) \.bandeau-admin \{ margin-right: 480px; \}")
        self.assertIn("@container taches (max-width: 599px)", CSS)

    def test_n5_tache_close_lisible_sur_ligne_ouverte_ou_survolee(self):
        self.assertIn(".taskrow-ouverte .taskrow-close, .taskrow-cliquable:hover .taskrow-close { color: var(--text-muted); }", CSS)

    def test_n8_coches_decoratives_hors_du_nom_accessible(self):
        for contenu in re.findall(r'content: ("[^"]+")[^;]*;', CSS):
            if contenu in ('" (aperçu)"', '"Test"'):
                continue
            self.assertRegex(CSS, re.escape("content: " + contenu + "; content: " + contenu + ' / "";'))

    def test_toasts_en_popover_et_regions_live_persistantes(self):
        self.assertIn('<div id="k-toasts" class="k-toasts" popover="manual"><div id="k-annonce" class="sr-only" '
                      'role="status" aria-atomic="true"></div><div id="k-alerte" class="sr-only" role="alert" '
                      'aria-atomic="true"></div></div>', BASE)
        corps = " ".join(regles(r"^\s*\.k-toasts\s*$"))
        for decl in ("margin: 0", "border: 0", "background: none", "inset: auto 24px 24px auto"):
            self.assertIn(decl, corps)

    def test_accueil_mobile_colonnes_apres_le_fil_complet(self):
        # CLS sur réseau lent : la page peinte en cours de lecture ne pousse
        # plus « Mes projets » sous le fil qui s'allonge.
        self.assertIn(".page-body-accueil:not(:has(#fil-vide)) > .col { display: none; }", CSS)
        self.assertIn("font-display: optional;", BASE)

    def test_emails_coupes_avec_points_de_suspension(self):
        self.assertIn(".urow .lien-discret.urow-email { display: block; min-width: 0; line-height: 24px; }", CSS)


class TestPolices(unittest.TestCase):
    def test_espace_fine_insecable_dans_les_trois_graisses(self):
        try:
            from fontTools.ttLib import TTFont
            import brotli  # noqa: F401  (décodage woff2)
        except ImportError:
            self.skipTest("fontTools / brotli absents")
        for graisse in (400, 600, 700):
            cmap = TTFont(RACINE / "app" / "static" / "fonts" / f"plus-jakarta-sans-{graisse}.woff2").getBestCmap()
            self.assertIn(0x202F, cmap)
            self.assertEqual(cmap[0x202F], cmap[0x2009])
            for car in "àâçéèêëîïôœùûüÿ’«»…€":
                self.assertIn(ord(car), cmap, car)


if __name__ == "__main__":
    unittest.main()

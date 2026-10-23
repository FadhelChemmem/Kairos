"""Lot 13 — revue visuelle et revue produit (H2) : barre du haut (page
courante, libellés, menu du compte), système visuel (feuille
lot13-visuel.css dans le paquet, sombre neutre, Gantt en jetons),
libellés clairs (« Vu », « Donner suite », « Nouvelle tâche »,
« Prochaine échéance » en rouge si dépassée), états vides de l'accueil.

Même principe que tests/test_smoke.py (psycopg2 simulé, repositories
remplacés par des mocks).
"""
import datetime
import pathlib
import re
import unittest

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
    from test_lot13_front import _Base
except ImportError:  # python -m unittest tests.test_lot13_visuel
    from tests import test_smoke as smoke
    from tests.test_lot13_front import _Base

from app import paquets, utils  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parent.parent
CSS = RACINE / "app" / "static" / "css"


def _ratio(a, b):
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _jetons(css, selecteur):
    bloc = css.split(selecteur + " {", 1)[1].split("}", 1)[0]
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", bloc))


class TestFeuilleVisuelle(unittest.TestCase):
    def test_feuille_dans_le_paquet_apres_les_autres(self):
        # Lot 14 : les feuilles des nouvelles fonctionnalités (lot14-*.css)
        # viennent après ; lot13-visuel.css reste après toutes les autres.
        # Lot 15 : lot15.css (sobriété) en tout dernier.
        # Lot 17 : lot17.css juste après ; lot 25 : lot25.css en tout dernier.
        self.assertEqual(paquets.PAQUETS["app.css"][-3:], ("css/lot15.css", "css/lot17.css", "css/lot25.css"))
        feuilles = [f for f in paquets.PAQUETS["app.css"]
                    if not f.startswith(("css/lot14-", "css/lot15", "css/lot17", "css/lot25"))]
        self.assertEqual(feuilles[-1], "css/lot13-visuel.css")

    def test_regle_k_page_valide(self):
        """P0-1 : la règle .k-page n'est plus annulée par un reste de fusion."""
        css = (CSS / "app.css").read_text(encoding="utf-8")
        self.assertIn(".k-page { padding-top: var(--esp-6); padding-bottom: 60px; }", css)
        self.assertNotRegex(css, r"(?m)^={7}$")

    def test_page_courante_marquee_et_mots_espaces(self):
        css = (CSS / "lot13-visuel.css").read_text(encoding="utf-8")
        self.assertIn(".topbar a.iconbtn[aria-current] {", css)
        self.assertIn("word-spacing: .08em;", (CSS / "app.css").read_text(encoding="utf-8"))

    def test_sombre_neutre_et_contrastes(self):
        """P1-7 : fond vert-noir (plus de kaki), textes ≥ 4,5:1."""
        css = (CSS / "app.css").read_text(encoding="utf-8")
        sombre = _jetons(css, ':root[data-theme="dark"]')
        self.assertEqual(sombre["--bg"], "#111513")
        self.assertEqual(sombre["--surface"], "#191e1b")
        for texte in ("--text", "--text-secondary", "--text-muted", "--text-faint", "--brand-text", "--error-text"):
            for fond in ("--surface", "--bg", "--bg-subtle-1"):
                self.assertGreaterEqual(_ratio(sombre[texte], sombre[fond]), 4.5, f"{texte}/{fond}")

    def test_gantt_couleurs_distinctes_et_lisibles(self):
        """P1-6 : « cette semaine » en ambre, texte blanc ≥ 4,5:1 sur chaque barre."""
        visuel = (CSS / "lot13-visuel.css").read_text(encoding="utf-8")
        jetons = _jetons(visuel, ":root")
        for nom in ("--gantt-urgent", "--gantt-semaine", "--gantt-tard"):
            self.assertGreaterEqual(_ratio("#ffffff", jetons[nom]), 4.5, nom)
        self.assertEqual(jetons["--gantt-semaine"], utils.GANTT_COULEURS["semaine"])
        sombre = _jetons(visuel, ':root[data-theme="dark"]')
        self.assertGreaterEqual(_ratio("#ffffff", sombre["--mode-agir"]), 4.5)


class TestBarreDuHaut(_Base):
    def test_libelles_page_courante_et_menu_du_compte(self):
        html = self._appel("get", "/projets").get_data(as_text=True)
        nav = html.split('<nav class="topbar-actions"', 1)[1].split("</nav>", 1)[0]
        self.assertRegex(nav, r'aria-label="Tous les projets" aria-current="page">.*?<span class="topbar-libelle" aria-hidden="true">Projets</span>')
        self.assertIn('aria-label="Équipe"', nav)
        # Thème et déconnexion dans le menu de l'avatar (popover), plus dans la barre.
        menu = nav.split('id="menu-compte"', 1)[1]
        self.assertIn('popovertarget="menu-compte"', nav)
        self.assertIn('id="theme-toggle"', menu)
        self.assertIn("Se déconnecter", menu)
        self.assertIn("data-aide-raccourcis", menu)
        avant_menu = nav.split('id="menu-compte"', 1)[0]
        self.assertNotIn('id="theme-toggle"', avant_menu)
        self.assertNotIn("/deconnexion", avant_menu.split("topbar-compte", 1)[0])


class TestLibelles(_Base):
    def test_fil_vu_et_donner_suite(self):
        html = self._appel("get", "/accueil").get_data(as_text=True)
        self.assertIn("Donner suite", html)
        self.assertIn("Marquer comme vu, déjà vu par", html)
        self.assertNotIn("Reposter", html)
        self.assertNotIn("Valider ce post", html)
        # Titre de la fenêtre selon l'onglet, bouton « Créer la tâche ».
        self.assertIn('<span class="titre-intent titre-tache">Nouvelle tâche</span>', html)
        self.assertIn(">Créer la tâche</button>", html)

    def test_prochaine_echeance_depassee_en_rouge(self):
        ligne = {**smoke.TestPagesLot6.PROJET_LIGNE, "prochain_rendu": utils._aujourdhui() - datetime.timedelta(days=2)}
        html = self._appel("get", "/projets", **{"app.repositories.projets.list_projets": [ligne]}).get_data(as_text=True)
        self.assertIn(">Prochaine échéance</span>", html)
        self.assertIn(">Heures (interv. · chef)</span>", html)
        self.assertIn("ptable-rendu ptable-rendu-retard", html)
        self.assertIn('<span class="ptable-retard-jours" aria-hidden="true"><span class="sep-point"> · </span>2&nbsp;j de retard</span>', html)
        self.assertIn("8 h · 5 h", html)

    def test_accueil_etats_vides_avec_action(self):
        vides = {"app.repositories.projets.list_mes_projets_recents": [],
                 "app.repositories.taches.list_mes_taches": [],
                 "app.repositories.taches.list_deadlines": [],
                 "app.repositories.taches.list_deadlines_tous": [],
                 "app.repositories.tableaux.taches_de_mes_projets": []}
        html = self._appel("get", "/accueil", **vides).get_data(as_text=True)
        # Lot 15 : l'Admin rattaché à aucun projet n'a plus de cartes vides
        # « Mes projets » / « Tâches de mes projets » (Vue d'ensemble).
        self.assertNotIn("Aucun projet pour l’instant.", html)
        self.assertNotIn("Aucune tâche en cours sur vos projets.", html)
        self.assertIn("Aucune échéance en cours dans le bureau.", html)
        html = self._appel("get", "/accueil", **vides, **{
            "app.auth.get_user_by_id": {**smoke.USER, "role": "intervenant"}}).get_data(as_text=True)
        self.assertIn('<p class="k-vide-texte">Aucun projet pour l’instant.</p>', html)
        self.assertIn("Aucune tâche en cours à votre nom.", html)
        self.assertIn("Aucune échéance sur vos projets.", html)


if __name__ == "__main__":
    unittest.main()

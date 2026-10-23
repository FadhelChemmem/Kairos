"""Tests du lot 13, partie front (audit UX §4) : contrat des mises à jour
partielles (app/partiel.py), pilotes de la page Utilisateurs (filtres et
interrupteur « Actif » en partiel), pastilles en classes thémées
(contrastes calculés), police auto-hébergée, CSP sans script en ligne,
« Voir comme » en lecture seule dans l'interface.

Même principe que tests/test_smoke.py (psycopg2 simulé, repositories
remplacés par des mocks).
"""
import json
import pathlib
import re
import unittest
from unittest.mock import patch
from urllib.parse import unquote

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
except ImportError:  # python -m unittest tests.test_lot13_front
    from tests import test_smoke as smoke

from flask import flash, redirect  # noqa: E402

from app import partiel, utils  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parent.parent
PARTIEL = {"X-Kairos-Partiel": "#utilisateurs-resultats", "X-Requested-With": "XMLHttpRequest"}


def toasts_de(resp):
    entete = resp.headers.get("X-Kairos-Toasts")
    return json.loads(unquote(entete)) if entete else []


class _Base(smoke.SmokeBase):
    def _appel(self, methode, chemin, en_tetes=None, data=None, extra=(), **overrides):
        self._login()
        patchers = self._patched(**overrides) + list(extra)
        for p in patchers:
            p.start()
        try:
            return getattr(self.client, methode)(chemin, headers=en_tetes or {}, data=data)
        finally:
            for p in reversed(patchers):
                p.stop()


class TestContratPartiel(_Base):
    """app/partiel.py : en-têtes, toasts, refus, redirections adaptées."""

    def test_est_partiel(self):
        with self.app.test_request_context("/", headers={"X-Kairos-Partiel": " #cible "}):
            self.assertEqual(partiel.est_partiel(), "#cible")
        with self.app.test_request_context("/"):
            self.assertIsNone(partiel.est_partiel())
        with self.app.test_request_context("/", headers={"X-Kairos-Partiel": ""}):
            self.assertIsNone(partiel.est_partiel())

    def test_repondre_fragment_toasts_et_flash_une_seule_fois(self):
        from jinja2 import ChoiceLoader, DictLoader
        self.app.jinja_loader = ChoiceLoader([DictLoader({"_fragment.html": "<p id=\"x\">{{ n }} comptes</p>"}), self.app.jinja_loader])
        with self.app.test_request_context("/", headers={"X-Kairos-Partiel": "#x"}):
            flash("Enregistré.", "success")
            flash("Attention : rien n’a changé.", "error")
            r = partiel.repondre("_fragment.html", statut=200,
                                 toasts=[partiel.toast("Compte réactivé.", action={"libelle": "Annuler"})], n=3)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.get_data(as_text=True), '<p id="x">3 comptes</p>')
            self.assertEqual(r.headers["X-Kairos-Fragment"], "_fragment.html")
            self.assertEqual(r.headers["Cache-Control"], "no-store")
            self.assertIn("X-Kairos-Partiel", r.headers["Vary"])
            toasts = toasts_de(r)
            self.assertEqual([t["type"] for t in toasts], ["succes", "succes", "erreur"])
            self.assertEqual(toasts[0]["action"], {"libelle": "Annuler"})
            self.assertEqual(toasts[2]["texte"], "Attention : rien n’a changé.")
            # Lus une seule fois (Flask garde la liste en cache dans la requête).
            self.assertEqual(partiel.toasts_flash(), [])
            # En-tête ASCII (encodé en pourcents), accents préservés.
            r.headers["X-Kairos-Toasts"].encode("ascii")

    def test_refuser_json(self):
        with self.app.test_request_context("/", headers={"X-Kairos-Partiel": "#x"}):
            r = partiel.refuser("Seul un Admin peut le faire.", 403)
            self.assertEqual(r.status_code, 403)
            self.assertEqual(r.get_json(), {"erreur": "interdit", "message": "Seul un Admin peut le faire."})
            self.assertEqual(partiel.conflit("Déjà modifié.").status_code, 409)
            self.assertEqual(partiel.refuser("x", 409, erreur="rh").get_json()["erreur"], "rh")

    def test_toast_type_inconnu_devient_info(self):
        self.assertEqual(partiel.toast("x", "bizarre")["type"], "info")
        self.assertNotIn("action", partiel.toast("x"))

    def test_redirection_d_une_route_non_convertie_devient_204(self):
        @self.app.route("/_test_prg", methods=["POST"])
        def _test_prg():
            flash("Fait.", "success")
            return redirect("/accueil")
        resp = self._appel("post", "/_test_prg", {"X-Kairos-Partiel": "#x"})
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.headers["X-Kairos-Redirection"], "/accueil")
        self.assertNotIn("Location", resp.headers)
        # Le message reste en session pour la page d'arrivée.
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("_flashes"), [("success", "Fait.")])
        sans = self._appel("post", "/_test_prg")
        self.assertEqual(sans.status_code, 302)

    def test_session_expiree_401(self):
        resp = self.client.get("/utilisateurs", headers={**PARTIEL, "Referer": "http://localhost/utilisateurs?q=a"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.get_json()["erreur"], "non_connecte")
        self.assertEqual(resp.headers["X-Kairos-Connexion"], "/connexion?next=/utilisateurs?q%3Da")
        # Sans en-tête partiel : redirection habituelle.
        self.assertEqual(self.client.get("/utilisateurs").status_code, 302)

    def test_page_d_erreur_en_json_pour_une_requete_partielle(self):
        resp = self._appel("get", "/projets/999999/inexistant", PARTIEL)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["erreur"], "introuvable")
        self.assertIn("n’existe pas", resp.get_json()["message"])
        html = self._appel("get", "/projets/999999/inexistant")
        self.assertIn("text/html", html.headers["Content-Type"])

    def test_csrf_refuse_en_json_pour_une_requete_partielle(self):
        class AvecCsrf(smoke.TestConfig):
            WTF_CSRF_ENABLED = True
        from app import create_app
        self.app = create_app(AvecCsrf)
        self.client = self.app.test_client()
        resp = self._appel("post", "/utilisateurs/5/toggle-actif", {"X-Kairos-Partiel": "#u-5"}, data={"actif_cible": "0"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["erreur"], "csrf")
        # Session perdue (cookie expiré) : 401, proposition de se reconnecter.
        self.client.delete_cookie("session")
        resp = self.client.post("/utilisateurs/5/toggle-actif", headers={"X-Kairos-Partiel": "#u-5"}, data={"actif_cible": "0"})
        self.assertEqual(resp.status_code, 401)
        self.assertIn("/connexion?next=", resp.headers["X-Kairos-Connexion"])


class TestPiloteUtilisateurs(_Base):
    """Pilotes du socle : filtres automatiques et interrupteur « Actif »."""

    def test_page_complete_filtres_automatiques_et_repli_sans_js(self):
        html = self._appel("get", "/utilisateurs").get_data(as_text=True)
        self.assertIn('data-partiel="#utilisateurs-resultats" data-partiel-auto="input:250 change"', html)
        self.assertIn('id="utilisateurs-resultats"', html)
        self.assertIn('id="filtre-utilisateurs-q"', html)
        # Bouton « Filtrer » gardé pour le repli sans JavaScript.
        self.assertRegex(html, r'<button type="submit" class="btn-secondary k-sans-js"[^>]*>Filtrer</button>')
        self.assertIn('id="u-5"', html)
        self.assertIn('id="actif-5"', html)
        self.assertIn('data-partiel="#u-5" data-optimiste="bascule"', html)
        self.assertIn('<span id="utilisateurs-compte" class="utilisateurs-compte" role="status">2 comptes · 1 actif</span>', html)

    def test_filtres_en_partiel_renvoient_le_tableau_et_le_compteur(self):
        resp = self._appel("get", "/utilisateurs?q=amine&role=intervenant", PARTIEL)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertNotIn("<html", html)
        self.assertNotIn("subbar", html)
        self.assertTrue(html.lstrip().startswith('<div id="utilisateurs-resultats">'))
        self.assertIn('data-partiel-oob>2 résultats sur 2 comptes</span>', html)
        self.assertIn('id="u-1"', html)
        vide = self._appel("get", "/utilisateurs?q=zzz", PARTIEL,
                           **{"app.repositories.utilisateurs.list_tous": []}).get_data(as_text=True)
        self.assertIn("Aucun utilisateur ne correspond à ces filtres.", vide)
        self.assertIn("Effacer les filtres", vide)
        self.assertNotIn('role="columnheader"', vide)

    def test_chef_de_projet_lecture_seule(self):
        chef = {**smoke.USER, "role": "chef_de_projet"}
        html = self._appel("get", "/utilisateurs", PARTIEL, **{"app.auth.get_user_by_id": chef}).get_data(as_text=True)
        self.assertNotIn('role="switch"', html)
        self.assertIn('<span class="pill pill-sm pill-vert">Actif</span>', html)

    def test_interrupteur_partiel_ligne_toast_annuler(self):
        cible = {**smoke.UTILISATEUR_PROFIL, "id": 5, "prenom": "Amine", "nom": "Ben Salah", "role": "intervenant",
                 "actif": False}
        resp = self._appel(
            "post", "/utilisateurs/5/toggle-actif", {"X-Kairos-Partiel": "#u-5", "X-Requested-With": "XMLHttpRequest"},
            data={"q": "am", "equipe_code": "", "role": "", "actif": "", "actif_cible": "0"},
            extra=[patch("app.repositories.utilisateurs.set_actif")],
            **{"app.repositories.utilisateurs.get_utilisateur": cible})
        self.assertEqual(resp.status_code, 200, resp.data[:500])
        html = resp.get_data(as_text=True)
        self.assertTrue(html.lstrip().startswith('<div class="urow inactif" role="row" id="u-5">'))
        self.assertIn('aria-checked="false"', html)
        self.assertIn('name="q" value="am"', html)
        self.assertIn("data-partiel-oob", html)
        toasts = toasts_de(resp)
        self.assertEqual(len(toasts), 1)
        self.assertEqual(toasts[0]["texte"], "Compte désactivé\u00a0: Amine Ben Salah.")
        action = toasts[0]["action"]
        self.assertEqual(action["libelle"], "Annuler")
        self.assertEqual(action["url"], "/utilisateurs/5/toggle-actif")
        self.assertEqual(action["donnees"]["actif_cible"], "1")
        self.assertEqual(action["donnees"]["q"], "am")
        self.assertEqual((action["cible"], action["focus"]), ("#u-5", "#actif-5"))
        # L'annulation ne propose pas d'annuler l'annulation.
        resp = self._appel(
            "post", "/utilisateurs/5/toggle-actif", {"X-Kairos-Partiel": "#u-5"},
            data={"actif_cible": "1", "annulation": "1"},
            extra=[patch("app.repositories.utilisateurs.set_actif")],
            **{"app.repositories.utilisateurs.get_utilisateur": {**cible, "actif": True}})
        self.assertNotIn("action", toasts_de(resp)[0])
        self.assertEqual(toasts_de(resp)[0]["texte"], "Compte réactivé\u00a0: Amine Ben Salah.")

    def test_interrupteur_partiel_refus(self):
        cible = {**smoke.UTILISATEUR_PROFIL, "id": 5, "role": "intervenant", "actif": True}
        cas = [
            (1, {"actif_cible": "0"}, {}, 403),                                  # son propre compte
            (5, {"actif_cible": "x"}, {}, 400),                                  # requête invalide
            (5, {"actif_cible": "0"}, {"app.repositories.utilisateurs.get_utilisateur": None}, 404),
        ]
        for user_id, data, overrides, statut in cas:
            with self.subTest(statut=statut):
                over = {"app.repositories.utilisateurs.get_utilisateur": cible, **overrides}
                resp = self._appel("post", f"/utilisateurs/{user_id}/toggle-actif", {"X-Kairos-Partiel": f"#u-{user_id}"},
                                   data=data, extra=[patch("app.repositories.utilisateurs.set_actif")], **over)
                self.assertEqual(resp.status_code, statut)
                self.assertTrue(resp.get_json()["message"])
                # Message unique, rien ne reste pour la page suivante.
                self.assertEqual(toasts_de(resp), [])
                with self.client.session_transaction() as sess:
                    self.assertFalse(sess.get("_flashes"))

    def test_interrupteur_rh_singleton_409(self):
        cible = {**smoke.UTILISATEUR_PROFIL, "id": 2, "role": "rh", "actif": False}
        resp = self._appel("post", "/utilisateurs/2/toggle-actif", {"X-Kairos-Partiel": "#u-2"}, data={"actif_cible": "1"},
                           extra=[patch("app.repositories.utilisateurs.set_actif",
                                        side_effect=Exception("idx_utilisateur_rh_singleton"))],
                           **{"app.repositories.utilisateurs.get_utilisateur": cible})
        self.assertEqual(resp.status_code, 409)
        self.assertIn("compte RH actif", resp.get_json()["message"])

    def test_interrupteur_sans_js_inchange(self):
        resp = self._appel("post", "/utilisateurs/5/toggle-actif", data={"actif_cible": "0", "q": "am"},
                           extra=[patch("app.repositories.utilisateurs.set_actif")])
        self.assertEqual(resp.status_code, 302)
        self.assertIn("q=am", resp.headers["Location"])


class TestPastillesEtContrastes(unittest.TestCase):
    """Pastilles en classes (utils.py) et jetons --etat-* (app.css)."""

    CLASSES = {"pill-bleu", "pill-rouge", "pill-vert", "pill-violet", "pill-orange", "pill-neutre"}

    @staticmethod
    def _jetons(css, selecteur):
        bloc = re.search(r"^" + re.escape(selecteur) + r" \{(.*?)\n\}", css, re.S | re.M).group(1)
        return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", bloc))

    @staticmethod
    def _ratio(a, b):
        def lum(h):
            c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
            return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
        la, lb = sorted((lum(a), lum(b)), reverse=True)
        return (la + 0.05) / (lb + 0.05)

    def test_utils_renvoie_des_classes(self):
        styles = [utils.tache_etat_style(e) for e in ("en_cours", "bloque", "verifie", "termine", "arret", "abandonne", "?")]
        styles += [utils.projet_etat_style(e) for e in ("en_cours", "bloque", "termine", "abandonne", "?")]
        styles += [utils.post_type_style(e) for e in ("envoi", "reponse", "question", "requete", "information", "?")]
        styles += [utils.role_style(r) for r in ("admin", "chef_de_projet", "intervenant", "rh", "client", "?")]
        styles += [utils.notif_categorie_style(c) for c in ("projet", "rh_info", "?")] + [utils.POST_TACHE_PILL]
        for st in styles:
            self.assertIn(st["classe"], self.CLASSES)
            self.assertNotIn("bg", st)
            self.assertNotIn("fg", st)
        self.assertEqual(utils.tache_etat_style("bloque")["classe"], "pill-rouge")

    def test_plus_de_couleur_de_pastille_en_dur_dans_les_gabarits(self):
        for tpl in (RACINE / "app" / "templates").rglob("*.html"):
            texte = tpl.read_text(encoding="utf-8")
            self.assertNotRegex(texte, r"\.(bg|fg) \}\}", tpl.name)

    def test_contrastes_clair_et_sombre(self):
        css = (RACINE / "app" / "static" / "css" / "app.css").read_text(encoding="utf-8")
        clair = self._jetons(css, ":root")
        sombre = {**clair, **self._jetons(css, ':root[data-theme="dark"]')}
        for nom, jetons in (("clair", clair), ("sombre", sombre)):
            for etat in ("cours", "bloque", "termine", "verifie", "requete", "neutre"):
                ratio = self._ratio(jetons[f"--etat-{etat}-texte"], jetons[f"--etat-{etat}-fond"])
                self.assertGreaterEqual(ratio, 4.5, f"{nom} {etat} : {ratio:.2f}")
            # Textes courants et anneau de focus sur la surface et le fond.
            for texte in ("--text", "--text-secondary", "--text-muted", "--brand-text", "--brand-text-strong", "--error-text"):
                for fond in ("--surface", "--bg"):
                    self.assertGreaterEqual(self._ratio(jetons[texte], jetons[fond]), 4.5, f"{nom} {texte}/{fond}")
            for element in ("--focus-ring", "--control-border"):
                self.assertGreaterEqual(self._ratio(jetons[element], jetons["--surface"]), 3, f"{nom} {element}")
            self.assertGreaterEqual(self._ratio("#ffffff", jetons["--accent-fill"]), 4.5, f"{nom} bouton primaire")
            self.assertGreaterEqual(self._ratio("#ffffff", jetons["--danger-fill"]), 4.5, f"{nom} bouton danger")

    def test_classes_de_pastilles_definies(self):
        css = (RACINE / "app" / "static" / "css" / "app.css").read_text(encoding="utf-8")
        for classe in self.CLASSES:
            self.assertIn("." + classe + " {", css)


class TestPoliceEtCsp(_Base):
    def test_police_auto_hebergee(self):
        html = self._appel("get", "/accueil").get_data(as_text=True)
        self.assertNotIn("fonts.googleapis", html)
        self.assertNotIn("fonts.gstatic", html)
        # Audit a11y-perf R5 : aucun preload (premier rendu retardé en 3G),
        # trois graisses seulement.
        self.assertNotIn('rel="preload"', html)
        for graisse in (400, 600, 700):
            self.assertIn(f"font-weight: {graisse}; font-display: optional;", html)
            self.assertTrue((RACINE / "app" / "static" / "fonts" / f"plus-jakarta-sans-{graisse}.woff2").is_file())
        for graisse in (500, 800):
            self.assertNotIn(f"font-weight: {graisse}; font-display", html)
            self.assertFalse((RACINE / "app" / "static" / "fonts" / f"plus-jakarta-sans-{graisse}.woff2").exists())
        css = (RACINE / "app" / "static" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertNotRegex(css, r"font-weight: ?(500|800)\b")
        self.assertIn("SIL Open Font License", (RACINE / "app" / "static" / "fonts" / "OFL.txt").read_text(encoding="utf-8"))
        police = self.client.get("/static/fonts/plus-jakarta-sans-400.woff2")
        self.assertEqual(police.mimetype, "font/woff2")
        police.close()

    def test_aucun_script_en_ligne_dans_les_gabarits(self):
        """CSP script-src 'self' (sans 'unsafe-inline') : tout script est un
        fichier ; seuls les blocs de données JSON restent dans les pages."""
        for tpl in (RACINE / "app" / "templates").rglob("*.html"):
            texte = tpl.read_text(encoding="utf-8")
            for balise in re.findall(r"<script\b[^>]*>", texte):
                self.assertTrue("src=" in balise or 'type="application/json"' in balise, f"{tpl.name} : {balise}")
            self.assertNotRegex(texte, r"\son[a-z]+=", tpl.name)
            self.assertNotRegex(texte, r'(href|src|action)="javascript:', tpl.name)

    def test_csp_stricte_pour_les_scripts(self):
        csp = self._appel("get", "/accueil").headers["Content-Security-Policy"]
        self.assertIn("script-src 'self';", csp)
        self.assertNotIn("unsafe-eval", csp)


class TestBaseEtLectureSeule(_Base):
    def test_barre_basse_recherche_mobile_et_toasts(self):
        html = self._appel("get", "/accueil").get_data(as_text=True)
        self.assertIn('<nav class="k-nav-basse" aria-label="Navigation rapide">', html)
        self.assertIn('data-recherche-ouvrir aria-expanded="false" aria-controls="recherche-globale"', html)
        self.assertIn('data-url="/recherche/api"', html)
        # Zone en popover + régions live persistantes, vides au chargement (audit a11y R2).
        self.assertIn('<div id="k-toasts" class="k-toasts" popover="manual" role="region" aria-label="Messages"><div id="k-annonce" class="sr-only" role="status" aria-atomic="true"></div><div id="k-alerte" class="sr-only" role="alert" aria-atomic="true"></div></div>', html)
        # Scripts communs en un seul fichier (audit a11y-perf N9).
        self.assertRegex(html, r'<script src="/static/paquets/commun\.js\?v=[0-9a-f]{12}" defer></script>')
        self.assertNotIn("js/kairos-partiel.js", html)
        self.assertRegex(html, r'<link rel="stylesheet" href="/static/paquets/app\.css\?v=[0-9a-f]{12}">')
        self.assertIn('aria-keyshortcuts="Control+K /"', html)
        self.assertIn('data-raccourci-g="a"', html)
        self.assertNotIn("data-lecture-seule", html.split("<head>")[0])

    def test_voir_comme_marque_la_page_en_lecture_seule(self):
        chef = {**smoke.USER, "id": 34, "role": "chef_de_projet", "prenom": "Chef", "nom": "Test"}
        self._login()
        with self.client.session_transaction() as sess:
            sess["mode_admin"] = {"admin": 1, "cible": 34, "mode": "voir"}
        lire = lambda uid: smoke.USER if uid == 1 else chef  # noqa: E731
        resp = self._appel("get", "/accueil", extra=[patch("app.auth.get_user_by_id", side_effect=lire)])
        html = resp.get_data(as_text=True)
        self.assertIn('<html lang="fr" data-lecture-seule>', html)
        self.assertEqual(html.count("data-permis-lecture"), 2)   # déconnexion, « Revenir à mon compte »
        # Écriture refusée en JSON pour une requête partielle (jamais la page « Lecture seule »).
        resp = self._appel("post", "/utilisateurs/5/toggle-actif", {"X-Kairos-Partiel": "#u-5", "X-Requested-With": "XMLHttpRequest"},
                           data={"actif_cible": "0"}, extra=[patch("app.auth.get_user_by_id", side_effect=lire)])
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["erreur"], "lecture_seule")


if __name__ == "__main__":
    unittest.main()

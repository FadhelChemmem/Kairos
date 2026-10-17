"""Tests du lot 13, phase 2 (D) : Deadlines, Notifications, Journal d'audit,
Utilisateurs (fiche, création, profils), en mise à jour partielle — même
contrat que les pilotes (app/partiel.py) : fragment seul, toasts en
en-tête, 422 avec les erreurs reliées aux champs, refus en JSON, repli
sans JavaScript inchangé (POST puis redirection, ou page re-rendue).

Même principe que tests/test_smoke.py (psycopg2 simulé, repositories
remplacés par des mocks).
"""
import datetime
import re
import unittest
from unittest.mock import MagicMock, patch

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
    from test_lot13_front import _Base, toasts_de
except ImportError:  # python -m unittest tests.test_lot13_pages
    from tests import test_smoke as smoke
    from tests.test_lot13_front import _Base, toasts_de

from app.routes import admin as admin_routes  # noqa: E402
from app.routes import deadlines as deadlines_routes  # noqa: E402
from app.routes import notifications as notifications_routes  # noqa: E402


def partiel(cible):
    return {"X-Kairos-Partiel": cible, "X-Requested-With": "XMLHttpRequest"}


def espion(cible, retour=None):
    """Mock d'un repository déjà simulé par défaut (_patched) : passé en
    `extra`, il est démarré après les défauts et l'emporte."""
    m = MagicMock(return_value=retour)
    m.patcher = patch(cible, new=m)
    return m


def fragment(test, resp):
    html = resp.get_data(as_text=True)
    test.assertNotIn("<html", html)
    test.assertNotIn('class="topbar', html)
    return html


class TestDeadlines(_Base):
    TOUS = [{**smoke.DEADLINES[0], "id": 8, "chef_id": 2, "chef_prenom": "Ali", "chef_nom": "Chef"}]

    def test_page_bascule_et_contenu_partiels(self):
        html = self._appel("get", "/deadlines").get_data(as_text=True)
        self.assertIn('id="deadlines-contenu"', html)
        self.assertIn('data-partiel="#deadlines-contenu" data-vue="tous"', html)
        self.assertIn('<span id="deadlines-compte" class="subbar-compte" role="status">', html)
        # Liste par semaine du téléphone, ligne « aujourd'hui ».
        self.assertIn('class="deadlines-semaines"', html)
        self.assertIn("g-daycell g-aujourdhui", html)
        self.assertNotIn("background:#c2401f", html)

    def test_fragment_vue_tous_et_filtres(self):
        resp = self._appel("get", "/deadlines?vue=tous&equipe=URBS", partiel("#deadlines-contenu"), **{
            "app.repositories.taches.list_deadlines_tous": self.TOUS})
        self.assertEqual(resp.status_code, 200)
        html = fragment(self, resp)
        self.assertTrue(html.lstrip().startswith('<div id="deadlines-contenu"'))
        self.assertIn('data-partiel-auto="change"', html)
        self.assertIn('id="deadlines-chef"', html)
        self.assertIn('data-partiel-oob>1 tâche avec échéance — tous les projets</span>', html)

    def test_admin_sans_projet_etat_vide(self):
        html = self._appel("get", "/deadlines?vue=mes", **{"app.repositories.taches.list_deadlines": []}).get_data(as_text=True)
        self.assertIn("Aucune échéance sur vos projets.", html)
        self.assertIn('href="/deadlines?vue=tous" class="btn btn-primaire" data-partiel="#deadlines-contenu"', html)
        self.assertNotIn('class="gantt"', html)

    def test_intervenant_ne_voit_pas_tous_les_projets_en_partiel(self):
        inter = {**smoke.USER, "role": "intervenant"}
        with patch("app.repositories.taches.list_deadlines_tous") as tous:
            resp = self._appel("get", "/deadlines?vue=tous", partiel("#deadlines-contenu"),
                               **{"app.auth.get_user_by_id": inter})
        tous.assert_not_called()
        self.assertNotIn("filtres-deadlines-admin", fragment(self, resp))
        self.assertNotIn("Voir tous les projets", resp.get_data(as_text=True))

    def test_rh_refuse_meme_en_partiel(self):
        rh = {**smoke.USER, "role": "rh"}
        resp = self._appel("get", "/deadlines", partiel("#deadlines-contenu"), **{"app.auth.get_user_by_id": rh})
        self.assertEqual(resp.status_code, 204)
        self.assertIn("X-Kairos-Redirection", resp.headers)

    def test_grouper_par_semaine(self):
        jeudi = datetime.date(2026, 10, 8)
        rows = [{"date_echeance": jeudi + datetime.timedelta(days=d)} for d in (-2, 0, 3, 4, 11, 30)]
        groupes = deadlines_routes.grouper_par_semaine(rows, jeudi)
        self.assertEqual([(g["cle"], len(g["rows"])) for g in groupes],
                         [("retard", 1), ("semaine", 2), ("prochaine", 1), ("plus_tard", 2)])


class TestNotifications(_Base):
    def test_apercu_de_la_cloche(self):
        liste = espion("app.repositories.notifications.list_notifications", smoke.NOTIFICATIONS)
        resp = self._appel("get", "/notifications", partiel("#notifs-apercu"), extra=[liste.patcher])
        html = fragment(self, resp)
        self.assertTrue(html.lstrip().startswith('<div id="notifs-apercu"'))
        self.assertEqual(liste.call_args.kwargs.get("limit"), 10)
        self.assertIn('<data id="notifs-nb" value="2" hidden data-partiel-oob></data>', html)
        self.assertIn('data-optimiste="notifs-toutes-lues"', html)
        self.assertIn("Tout voir", html)

    def test_page_groupee_par_jour(self):
        html = self._appel("get", "/notifications").get_data(as_text=True)
        self.assertIn('id="notifications-liste"', html)
        self.assertIn('class="notif-jour"', html)
        self.assertIn('id="notif-10"', html)
        self.assertIn('data-optimiste="notif-lue"', html)
        # Cloche : aperçu à la demande, badge tenu à jour.
        self.assertIn('aria-controls="notifs-popover"', html)
        self.assertIn('<data id="notifs-nb" value="2" hidden></data>', html)

    def test_marquer_lue_partiel_et_repli(self):
        lu = espion("app.repositories.notifications.marquer_lu")
        resp = self._appel("post", "/notifications/10/lue", partiel("#notif-10"), extra=[lu.patcher],
                           **{"app.repositories.notifications.compter_non_lues": 1})
        lu.assert_called_once_with(10, 1)
        html = fragment(self, resp)
        self.assertTrue(html.lstrip().startswith('<li class="notif-ligne" id="notif-10">'))
        self.assertNotIn("notif-lire-btn", html)
        # Place du bouton gardée (revue d'interaction P1-7 : la ligne ne s'élargit pas).
        self.assertIn('class="notif-lire-vide"', html)
        self.assertIn('value="1" hidden data-partiel-oob', html)
        resp = self._appel("post", "/notifications/10/lue")
        self.assertEqual((resp.status_code, resp.headers["Location"]), (302, "/notifications"))

    def test_marquer_lue_d_un_autre_refuse(self):
        lu = espion("app.repositories.notifications.marquer_lu")
        resp = self._appel("post", "/notifications/99/lue", partiel("#notif-99"), extra=[lu.patcher],
                           **{"app.repositories.notifications.get_notification": None})
        lu.assert_not_called()
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["erreur"], "introuvable")

    def test_tout_marquer_comme_lu_partiel(self):
        resp = self._appel("post", "/notifications/marquer-toutes-lues", partiel("#notifications-liste"),
                           **{"app.repositories.notifications.compter_non_lues": 0})
        html = fragment(self, resp)
        self.assertTrue(html.lstrip().startswith('<div id="notifications-liste"'))
        self.assertIn("marquées comme lues", toasts_de(resp)[0]["texte"])
        self.assertIn('data-partiel-oob>0 non lue</span>', html)
        resp = self._appel("post", "/notifications/marquer-toutes-lues")
        self.assertEqual(resp.status_code, 302)

    def test_compte_json(self):
        resp = self._appel("get", "/notifications/compte")
        self.assertEqual(resp.get_json(), {"non_lues": 2})
        self.assertEqual(resp.headers["Cache-Control"], "no-store")

    def test_grouper_par_jour(self):
        maintenant = datetime.datetime.now(datetime.timezone.utc)
        notifs = [{"created_at": maintenant}, {"created_at": maintenant - datetime.timedelta(days=1)},
                  {"created_at": maintenant - datetime.timedelta(days=5)}]
        with self.app.test_request_context("/"):
            groupes = notifications_routes.grouper_par_jour(notifs)
        self.assertEqual([g["titre"] for g in groupes][:2], ["Aujourd’hui", "Hier"])
        self.assertEqual(len(groupes), 3)


class TestJournal(_Base):
    def _entrees(self, n):
        base = datetime.datetime(2026, 10, 9, 12, 0, tzinfo=datetime.timezone.utc)
        return [{**smoke.AUDIT_ENTREES[0], "id": 500 - i, "created_at": base - datetime.timedelta(hours=i),
                 "donnees_avant": None, "donnees_apres": None, "compte_vu": None,
                 "admin_reel_id": None} for i in range(n)]

    def test_page_tableau_leger(self):
        liste = espion("app.repositories.audit.list_entrees", smoke.AUDIT_ENTREES)
        html = self._appel("get", "/admin/journal", extra=[liste.patcher]).get_data(as_text=True)
        self.assertEqual(liste.call_args.kwargs["limit"], admin_routes.PAR_PAGE + 1)
        self.assertFalse(liste.call_args.kwargs["avec_donnees"])
        self.assertIn('<table class="journal-table" id="journal-table">', html)
        self.assertIn("<caption", html)
        self.assertIn('scope="rowgroup"', html)
        self.assertIn('data-url="/admin/journal/1"', html)
        self.assertNotIn("<pre", html)
        self.assertIn('data-partiel="#journal-resultats" data-partiel-auto="change"', html)

    def test_curseur_et_suite(self):
        entrees = self._entrees(admin_routes.PAR_PAGE + 1)
        html = self._appel("get", "/admin/journal?table=projet", **{
            "app.repositories.audit.list_entrees": entrees}).get_data(as_text=True)
        self.assertEqual(html.count('class="journal-ligne"'), admin_routes.PAR_PAGE)
        suite = re.search(r'<a href="([^"]+)" class="btn" data-partiel="#journal-table" data-partiel-mode="apres"', html)
        self.assertTrue(suite)
        self.assertIn("table=projet", suite.group(1))
        self.assertIn("n=100", suite.group(1))
        liste = espion("app.repositories.audit.list_entrees", entrees[:3])
        resp = self._appel("get", "/admin/journal?table=projet&avant=2026-10-05T08%3A00%3A00%2B00%3A00_401&n=100&jour=2026-10-05",
                           partiel("#journal-table"), extra=[liste.patcher])
        avant = liste.call_args.kwargs["avant"]
        self.assertEqual(avant[1], 401)
        self.assertEqual(avant[0].isoformat(), "2026-10-05T08:00:00+00:00")
        html = fragment(self, resp)
        self.assertTrue(html.lstrip().startswith('<tbody class="journal-jour">'))
        self.assertIn('id="journal-apres-401" tabindex="-1"', html)
        self.assertIn('id="journal-suite" class="journal-suite" data-partiel-oob', html)
        self.assertIn("103 entrées affichées", html)

    def test_curseur_invalide_ignore(self):
        liste = espion("app.repositories.audit.list_entrees", [])
        self._appel("get", "/admin/journal?avant=pas-un-curseur", extra=[liste.patcher])
        self.assertIsNone(liste.call_args.kwargs["avant"])

    def test_filtres_partiels_et_etat_vide(self):
        resp = self._appel("get", "/admin/journal?action=DELETE", partiel("#journal-resultats"),
                           **{"app.repositories.audit.list_entrees": []})
        html = fragment(self, resp)
        self.assertTrue(html.lstrip().startswith('<div id="journal-resultats">'))
        self.assertIn("Aucune entrée pour ces filtres.", html)
        resp = self._appel("get", "/admin/journal?table=xxx", partiel("#journal-resultats"))
        self.assertIn("ignoré", toasts_de(resp)[0]["texte"])

    def test_donnees_a_la_demande(self):
        entree = {**smoke.AUDIT_ENTREES[0], "donnees_avant": {"etat": "en_cours", "nom": "Tour"},
                  "donnees_apres": {"etat": "bloque", "nom": "Tour"}, "compte_vu": None, "admin_reel_id": None}
        with patch("app.repositories.audit.get_entree", return_value=entree):
            resp = self._appel("get", "/admin/journal/1", partiel("#journal-donnees-1"))
            page = self._appel("get", "/admin/journal/1").get_data(as_text=True)
        html = fragment(self, resp)
        self.assertIn("<del>en_cours</del>", html)
        self.assertIn("<ins>bloque</ins>", html)
        self.assertIn("1 champ inchangé", html)
        self.assertIn("<html", page)
        with patch("app.repositories.audit.get_entree", return_value=None):
            self.assertEqual(self._appel("get", "/admin/journal/9", partiel("#x")).status_code, 404)

    def test_donnees_reservees_a_l_admin(self):
        chef = {**smoke.USER, "role": "chef_de_projet"}
        with patch("app.repositories.audit.get_entree") as lire:
            resp = self._appel("get", "/admin/journal/1", **{"app.auth.get_user_by_id": chef})
        self.assertEqual(resp.status_code, 302)
        lire.assert_not_called()

    def test_differences(self):
        d = admin_routes.differences({"donnees_avant": {"a": 1, "b": "x"}, "donnees_apres": {"a": 2, "b": "x"}})
        self.assertEqual(d["lignes"], [{"champ": "a", "avant": "1", "apres": "2", "type": "modifie"}])
        self.assertEqual(d["inchanges"], [{"champ": "b", "valeur": "x"}])
        d = admin_routes.differences({"donnees_avant": None, "donnees_apres": {"a": 1, "vide": None, "liste": []}})
        self.assertEqual([l["champ"] for l in d["lignes"]], ["a"])
        d = admin_routes.differences({"donnees_avant": {"a": "z" * 900}, "donnees_apres": None})
        self.assertTrue(d["lignes"][0]["avant"].endswith("…"))
        self.assertEqual(admin_routes.differences({"donnees_avant": None, "donnees_apres": None})["brut"], None)


class TestUtilisateursFormulaires(_Base):
    AUTRE = smoke.AUTRE_UTILISATEUR
    FICHE = {"prenom": "Wael", "nom": "Testeur", "email": "w.testeur@midgard.tn", "telephone": "", "poste": "Technicien",
             "adresse": "", "date_embauche": "", "equipe_code": "URBS", "role": "intervenant", "fuseau": "Africa/Tunis"}

    def test_fiche_erreur_reliee_au_champ_422(self):
        with patch("app.repositories.utilisateurs.update_utilisateur_complet") as maj:
            resp = self._appel("post", "/utilisateurs/2", partiel("#utilisateur-form"), data={**self.FICHE, "telephone": "abc!!"},
                               **{"app.repositories.utilisateurs.get_utilisateur": self.AUTRE})
        maj.assert_not_called()
        self.assertEqual(resp.status_code, 422)
        html = fragment(self, resp)
        self.assertTrue(html.lstrip().startswith('<form method="post" action="/utilisateurs/2"'))
        self.assertRegex(html, r'id="telephone"[^>]* aria-invalid="true" aria-describedby="err-telephone"')
        self.assertIn('<p class="champ-erreur" id="err-telephone">', html)
        self.assertEqual(toasts_de(resp), [])
        with self.client.session_transaction() as s:
            self.assertFalse(s.get("_flashes"))

    def test_fiche_enregistree_toast_et_titre(self):
        with patch("app.repositories.utilisateurs.update_utilisateur_complet") as maj:
            resp = self._appel("post", "/utilisateurs/2", partiel("#utilisateur-form"), data=self.FICHE,
                               **{"app.repositories.utilisateurs.get_utilisateur": self.AUTRE})
        maj.assert_called_once()
        self.assertEqual(resp.status_code, 200)
        html = fragment(self, resp)
        self.assertIn('<h1 class="page-titre" id="utilisateur-titre" data-partiel-oob>Wael Testeur</h1>', html)
        self.assertEqual(toasts_de(resp)[0], {"type": "succes", "texte": "Fiche mise à jour."})
        # Sans JavaScript : redirection inchangée.
        with patch("app.repositories.utilisateurs.update_utilisateur_complet"):
            resp = self._appel("post", "/utilisateurs/2", data=self.FICHE,
                               **{"app.repositories.utilisateurs.get_utilisateur": self.AUTRE})
        self.assertEqual((resp.status_code, resp.headers["Location"]), (302, "/utilisateurs/2"))

    def test_fiche_admin_protegee_pour_le_rh(self):
        rh = {**smoke.USER, "role": "rh"}
        cible = {**self.AUTRE, "role": "admin"}
        with patch("app.repositories.utilisateurs.update_utilisateur_complet") as maj:
            resp = self._appel("post", "/utilisateurs/2", partiel("#utilisateur-form"), data=self.FICHE,
                               **{"app.auth.get_user_by_id": rh, "app.repositories.utilisateurs.get_utilisateur": cible})
        maj.assert_not_called()
        self.assertEqual(resp.status_code, 403)

    def test_creation_erreurs_puis_navigation(self):
        with patch("app.repositories.utilisateurs.create_utilisateur") as creer:
            resp = self._appel("post", "/utilisateurs/nouveau", partiel("#utilisateur-form"),
                               data={"prenom": "", "nom": "", "email": "", "role": "intervenant", "fuseau": "Africa/Tunis"})
        creer.assert_not_called()
        self.assertEqual(resp.status_code, 422)
        html = fragment(self, resp)
        for champ in ("prenom", "nom", "email", "equipe_code"):
            self.assertIn(f'id="err-{champ}"', html)
        with patch("app.repositories.utilisateurs.create_utilisateur", return_value=50), \
             patch("app.routes.utilisateurs._envoyer_lien_mot_de_passe", return_value=True):
            resp = self._appel("post", "/utilisateurs/nouveau", partiel("#utilisateur-form"),
                               data={"prenom": "Neo", "nom": "Phyte", "email": "neo@x.tn", "role": "intervenant",
                                     "equipe_code": "MIDGARD", "fuseau": "Africa/Tunis", "actif": "on"})
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.headers["X-Kairos-Redirection"], "/utilisateurs")

    def test_creation_sans_js_autofocus_sur_la_premiere_erreur(self):
        with patch("app.repositories.utilisateurs.create_utilisateur", side_effect=Exception("idx_utilisateur_email_lower")):
            resp = self._appel("post", "/utilisateurs/nouveau",
                               data={"prenom": "Neo", "nom": "Phyte", "email": "pris@x.tn", "role": "intervenant",
                                     "equipe_code": "MIDGARD", "fuseau": "Africa/Tunis"})
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertRegex(html, r'id="email"[^>]* aria-invalid="true" aria-describedby="err-email" autofocus')
        self.assertNotRegex(html, r'id="prenom"[^>]*autofocus')
        self.assertIn("Un compte existe déjà avec l’email pris@x.tn.", html)

    def test_mot_de_passe_actuel_faux(self):
        with patch("app.routes.utilisateurs.verify_password", return_value=False), \
             patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.repositories.securite.enregistrer_tentative"), \
             patch("app.repositories.utilisateurs.set_password") as changer:
            resp = self._appel("post", "/utilisateurs/moi/mot-de-passe", partiel("#mot-de-passe"),
                               data={"mot_de_passe_actuel": "x", "nouveau_mot_de_passe": "abcdefghij", "confirmation": "abcdefghij"})
            sans_js = self._appel("post", "/utilisateurs/moi/mot-de-passe",
                                  data={"mot_de_passe_actuel": "x", "nouveau_mot_de_passe": "abcdefghij", "confirmation": "abcdefghij"})
        changer.assert_not_called()
        self.assertEqual(resp.status_code, 422)
        self.assertRegex(fragment(self, resp), r'id="mot_de_passe_actuel"[^>]* aria-invalid="true" aria-describedby="err-mot_de_passe_actuel"')
        self.assertEqual(sans_js.status_code, 200)
        self.assertRegex(sans_js.get_data(as_text=True), r'id="mot_de_passe_actuel"[^>]*autofocus')

    def test_mot_de_passe_change_champs_vides(self):
        with patch("app.routes.utilisateurs.verify_password", return_value=True), \
             patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.repositories.securite.enregistrer_tentative"), \
             patch("app.repositories.utilisateurs.set_password") as changer:
            resp = self._appel("post", "/utilisateurs/moi/mot-de-passe", partiel("#mot-de-passe"),
                               data={"mot_de_passe_actuel": "x", "nouveau_mot_de_passe": "abcdefghij", "confirmation": "abcdefghij"})
        changer.assert_called_once()
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("abcdefghij", fragment(self, resp))
        self.assertEqual(toasts_de(resp)[0]["texte"], "Mot de passe changé.")

    def test_mes_informations(self):
        resp = self._appel("post", "/utilisateurs/moi", partiel("#mes-infos"), data={"telephone": "abc!!"})
        self.assertEqual(resp.status_code, 422)
        self.assertIn('id="err-telephone"', fragment(self, resp))
        maj = espion("app.repositories.utilisateurs.update_profil")
        resp = self._appel("post", "/utilisateurs/moi", partiel("#mes-infos"), data={"telephone": "20 000 000"}, extra=[maj.patcher])
        maj.assert_called_once()
        html = fragment(self, resp)
        self.assertTrue(html.lstrip().startswith('<div class="card" id="mes-infos">'))
        self.assertNotIn('id="topbar-avatar"', html)   # pas de nouvelle photo
        self.assertEqual(toasts_de(resp)[0]["texte"], "Vos informations ont été mises à jour.")

    def test_compte_actif_depuis_la_fiche(self):
        apres = {**self.AUTRE, "actif": False}
        with patch("app.repositories.utilisateurs.set_actif") as basculer:
            resp = self._appel("post", "/utilisateurs/2/toggle-actif", partiel("#utilisateur-actif"),
                               data={"retour": "fiche", "actif_cible": "0"},
                               **{"app.repositories.utilisateurs.get_utilisateur": apres})
            sans_js = self._appel("post", "/utilisateurs/2/toggle-actif", data={"retour": "fiche", "actif_cible": "0"},
                                  **{"app.repositories.utilisateurs.get_utilisateur": apres})
        self.assertEqual(basculer.call_count, 2)
        html = fragment(self, resp)
        self.assertTrue(html.lstrip().startswith('<form method="post" action="/utilisateurs/2/toggle-actif"'))
        self.assertIn('id="fiche-actif" class="toggle toggle-liste" role="switch" aria-checked="false"', html)
        self.assertIn('id="utilisateur-reinit"', html)   # carte de réinitialisation, hors cible
        toast = toasts_de(resp)[0]
        self.assertEqual(toast["texte"], "Compte désactivé\u00a0: Wael Testeur.")
        self.assertEqual((toast["action"]["cible"], toast["action"]["donnees"]["retour"]), ("#utilisateur-actif", "fiche"))
        self.assertEqual((sans_js.status_code, sans_js.headers["Location"]), (302, "/utilisateurs/2"))

    def test_envoyer_lien_en_place(self):
        resp = self._appel("post", "/utilisateurs/2/envoyer-lien", partiel("#utilisateur-reinit"),
                           **{"app.repositories.utilisateurs.get_utilisateur": self.AUTRE})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="utilisateur-reinit-envoyer"', fragment(self, resp))
        self.assertEqual(toasts_de(resp)[0]["type"], "erreur")   # SMTP non configuré en test

    def test_profil_personne_semaine_precedente(self):
        resp = self._appel("get", "/utilisateurs/2/profil?semaines=2", partiel("#profil-activite"),
                           **{"app.repositories.utilisateurs.get_utilisateur": self.AUTRE})
        html = fragment(self, resp)
        self.assertTrue(html.lstrip().startswith('<div class="col-center" id="profil-activite">'))
        self.assertIn("2 dernières semaines", html)
        self.assertIn('data-partiel="#profil-activite"', html)
        self.assertIn('class="lien-cible"', html)


if __name__ == "__main__":
    unittest.main()

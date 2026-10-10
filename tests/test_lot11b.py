"""Lot 11 b — changement du chef de projet, tâche ouverte depuis la
recherche ou une notification, texte du rappel Daily log : routes et
gabarits (psycopg2 simulé, repositories remplacés par des mocks, comme
tests/test_smoke.py). La logique SQL est testée sur vraie base dans
tests_integration/test_lot11b.py.
"""
import html
import re
import unittest
from unittest.mock import patch

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
except ImportError:  # python -m unittest tests.test_lot11b
    from tests import test_smoke as smoke

from app import create_app  # noqa: E402
from app.repositories import projets as projets_repo  # noqa: E402

CHEF = {**smoke.USER, "id": 1, "role": "chef_de_projet", "prenom": "Ali", "nom": "Chef"}
ADMIN = {**smoke.USER, "id": 1, "role": "admin", "prenom": "Fadhel", "nom": "Admin"}
SAMI = {"id": 5, "prenom": "Sami", "nom": "Chérif", "poste": None, "role": "chef_de_projet",
        "equipe_code": "MIDGARD", "avatar_chemin": None, "actif": True}
OMAR = {"id": 3, "prenom": "Omar", "nom": "Aziz", "poste": "Technicien", "role": "intervenant",
        "equipe_code": "MIDGARD", "avatar_chemin": None, "actif": True}
ACTIFS = [{"id": 1, "prenom": "Foulen", "nom": "Chedly", "poste": "Ingénieur", "role": "chef_de_projet",
           "avatar_chemin": None}, SAMI, OMAR]
PROJET_OUVERT = {**smoke.PROJET, "etat": "en_cours", "chef_projet_id": 1}
PROJET_CLOS = {**smoke.PROJET, "etat": "termine", "chef_projet_id": 1}
CHANGEMENT = {"post_id": 77, "nouveau": SAMI, "ancien": {"id": 1, "prenom": "Foulen", "nom": "Chedly"},
              "acteur": CHEF}
DONNEES = {"nom": "Tour Meridian", "etat": "en_cours", "client": "IPCO", "chef_projet_id": "5"}


class _Base(smoke.SmokeBase):
    def requete(self, methode, chemin, data=None, espions=(), **overrides):
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        mocks = {}
        try:
            for cible, valeur in espions:
                pp = patch(cible, **({"side_effect": valeur} if isinstance(valeur, Exception) else {"return_value": valeur}))
                mocks[cible] = pp.start()
                patchers.append(pp)
            resp = getattr(self.client, methode)(chemin, data=data or {}, follow_redirects=methode == "post")
        finally:
            for p in reversed(patchers):
                p.stop()
        return resp, mocks

    @staticmethod
    def texte(resp):
        return html.unescape(resp.get_data(as_text=True))


class TestChangementDeChefRoute(_Base):
    def poster(self, user=CHEF, projet=PROJET_OUVERT, candidat=SAMI, data=None, maj=CHANGEMENT, **overrides):
        return self.requete(
            "post", "/projets/1/informations", data or DONNEES,
            espions=[("app.repositories.projets.update_projet", maj),
                     ("app.repositories.notifications.creer", 201)],
            **{"app.auth.get_user_by_id": user, "app.repositories.projets.get_projet": projet,
               "app.repositories.utilisateurs.get_utilisateur": candidat, **overrides})

    def test_chef_confie_le_projet(self):
        resp, mocks = self.poster()
        maj = mocks["app.repositories.projets.update_projet"]
        self.assertEqual((maj.call_args.kwargs["chef_projet_id"], maj.call_args.kwargs["acteur_admin"]), (5, False))
        notif = mocks["app.repositories.notifications.creer"]
        self.assertEqual(notif.call_args.args[:2], (5, "projet"))
        self.assertEqual(notif.call_args.args[2],
                         "Ali Chef vous a confié le projet «\u00a026099X_Tour Meridian\u00a0»\u00a0: vous en êtes le chef de projet.")
        self.assertEqual(notif.call_args.kwargs["post_id"], 77)
        self.assertIn("projet confié à Sami Chérif (Foulen Chedly devient co-chef)", self.texte(resp))

    def test_meme_chef_ou_champ_absent_pas_de_changement(self):
        for data in ({**DONNEES, "chef_projet_id": "1"}, {k: v for k, v in DONNEES.items() if k != "chef_projet_id"}):
            with self.subTest(data=data):
                resp, mocks = self.poster(data=data, maj=None)
                self.assertIsNone(mocks["app.repositories.projets.update_projet"].call_args.kwargs["chef_projet_id"])
                mocks["app.repositories.notifications.creer"].assert_not_called()
                self.assertIn("Informations du projet mises à jour.", self.texte(resp))

    def test_nouveau_chef_invalide_refuse_sans_rien_enregistrer(self):
        cas = [({**DONNEES, "chef_projet_id": "abc"}, SAMI), ({**DONNEES, "chef_projet_id": "²"}, SAMI),
               ({**DONNEES, "chef_projet_id": "9" * 19}, SAMI), (DONNEES, None), (DONNEES, {**SAMI, "actif": False}),
               (DONNEES, OMAR), (DONNEES, {**SAMI, "role": "rh"}), (DONNEES, {**SAMI, "role": "client"})]
        for data, candidat in cas:
            with self.subTest(candidat=candidat, data=data["chef_projet_id"]):
                resp, mocks = self.poster(data=data, candidat=candidat)
                mocks["app.repositories.projets.update_projet"].assert_not_called()
                self.assertIn(projets_repo.MESSAGE_CHEF_INVALIDE, self.texte(resp))

    def test_projet_clos_refuse_sauf_admin(self):
        resp, mocks = self.poster(projet=PROJET_CLOS, data={**DONNEES, "etat": "en_cours"})
        mocks["app.repositories.projets.update_projet"].assert_not_called()
        self.assertIn(projets_repo.MESSAGE_CHEF_PROJET_CLOS, self.texte(resp))
        resp, mocks = self.poster(user=ADMIN, projet=PROJET_CLOS, data={**DONNEES, "etat": "termine"})
        self.assertTrue(mocks["app.repositories.projets.update_projet"].call_args.kwargs["acteur_admin"])

    def test_sans_droit_de_gestion(self):
        resp, mocks = self.poster(**{"app.repositories.projets.user_can_manage": False})
        mocks["app.repositories.projets.update_projet"].assert_not_called()
        self.assertIn("Seul le chef de projet ou un co-chef peut modifier les informations du projet.", self.texte(resp))

    def test_refus_du_repository_et_du_trigger(self):
        resp, _ = self.poster(maj=projets_repo.ChangementChefRefuse(projets_repo.MESSAGE_CHEF_PROJET_CLOS))
        self.assertIn(projets_repo.MESSAGE_CHEF_PROJET_CLOS, self.texte(resp))
        exc = Exception("Projet 1 : seuls le chef de projet, un co-chef ou un Admin peuvent changer de chef de projet.")
        exc.pgcode = "42501"
        resp, mocks = self.poster(maj=exc)
        self.assertIn("Changement de chef refusé", self.texte(resp))
        mocks["app.repositories.notifications.creer"].assert_not_called()

    def test_notification_en_echec_ne_defait_rien(self):
        self._login()
        patchers = self._patched(**{"app.auth.get_user_by_id": CHEF, "app.repositories.projets.get_projet": PROJET_OUVERT,
                                    "app.repositories.utilisateurs.get_utilisateur": SAMI})
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.projets.update_projet", return_value=CHANGEMENT), \
                 patch("app.repositories.notifications.creer", side_effect=RuntimeError("boom")):
                resp = self.client.post("/projets/1/informations", data=DONNEES, follow_redirects=True)
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("projet confié à Sami Chérif", self.texte(resp))


class TestFenetreInformations(_Base):
    def page(self, user=CHEF, projet=PROJET_OUVERT, chemin="/projets/1", **overrides):
        resp, _ = self.requete("get", chemin, **{"app.auth.get_user_by_id": user, "app.repositories.projets.get_projet": projet,
                                                 "app.repositories.utilisateurs.list_actifs": ACTIFS, **overrides})
        self.assertEqual(resp.status_code, 200)
        return self.texte(resp)

    def test_champ_chef_meme_composant_que_le_selecteur(self):
        page = self.page()
        select = page.split('<select id="dialog-info-chef"', 1)[1].split("</select>", 1)[0]
        self.assertIn('name="chef_projet_id" data-search-combobox data-search-riche', select)
        self.assertIn('aria-describedby="dialog-info-chef-aide"', select)
        self.assertEqual(re.findall(r'<option value="(\d+)"', select), ["1", "5"])  # pas l'intervenant
        self.assertRegex(select, r'<option value="1" selected[^>]*data-sous-titre="Chef actuel · Chef de projet"')
        self.assertIn('data-sous-titre="Chef de projet">Sami Chérif</option>', select)
        self.assertIn("L’ancien chef devient co-chef.", page)
        self.assertNotIn("data-ouvrir-au-chargement", page)

    def test_projet_clos_lecture_seule_sauf_admin(self):
        page = self.page(projet=PROJET_CLOS)
        self.assertNotIn('id="dialog-info-chef"', page)
        self.assertIn("Projet clos\u00a0: rouvrez-le d’abord pour changer de chef.", page)
        self.assertIn('id="dialog-info-chef"', self.page(user=ADMIN, projet=PROJET_CLOS))

    def test_chef_desactive_reste_le_choix_affiche(self):
        projet = {**PROJET_OUVERT, "chef_projet_id": 8, "chef_prenom": "Ancien", "chef_nom": "Compte"}
        page = self.page(user=ADMIN, projet=projet, chemin="/projets/1?informations=chef",
                         **{"app.repositories.utilisateurs.get_utilisateur": {**OMAR, "id": 8, "actif": False}})
        self.assertIn('data-ouvrir-au-chargement="chef"', page)
        select = page.split('<select id="dialog-info-chef"', 1)[1].split("</select>", 1)[0]
        self.assertRegex(select, r'<option value="8" selected[^>]*data-sous-titre="Compte désactivé · chef actuel">Ancien Compte \(désactivé\)</option>')

    def test_post_automatique_rendu(self):
        post = {**smoke.FEED_POST_MANUEL, "evenement": "chef_projet", "type_code": "information",
                "contenu": "Ali Chef a confié le projet à Sami Chérif. Foulen Chedly, chef précédent, devient co-chef."}
        page = self.page(**{"app.repositories.posts.list_feed_projet": [post]})
        self.assertIn("a changé le chef de projet", page)
        self.assertIn("Ali Chef a confié le projet à Sami Chérif.", page)


class TestTacheDepuisRechercheEtNotification(_Base):
    def test_lien_de_recherche(self):
        resp, _ = self.requete("get", "/recherche/api?q=plan", **{
            "app.repositories.taches.search": [{"id": 5, "titre": "Plan", "etat": "en_cours", "projet_id": 1,
                                                "projet_code": "26099X", "projet_nom": "Tour"}]})
        self.assertEqual(resp.get_json()["resultats"][0]["url"], "/projets/1?tache=5")

    def test_fiche_ouvre_la_tache_et_deplie_les_closes(self):
        resp, _ = self.requete("get", "/projets/1?tache=6")  # tâche 6 : terminée
        page = resp.get_data(as_text=True)
        self.assertIn('data-ouvrir-au-chargement="6"', page)
        self.assertIn('id="taches-closes" open', page)
        resp, _ = self.requete("get", "/projets/1?tache=5")  # tâche 5 : bloquée (ouverte)
        page = resp.get_data(as_text=True)
        self.assertIn('data-ouvrir-au-chargement="5"', page)
        self.assertNotIn('id="taches-closes" open', page)
        for inconnue in ("999", "x"):
            resp, _ = self.requete("get", f"/projets/1?tache={inconnue}")
            self.assertNotIn("data-ouvrir-au-chargement", resp.get_data(as_text=True))

    def test_notification_d_une_tache(self):
        notif = {**smoke.NOTIFICATION_UNE, "post_id": None, "post_projet_id": None, "tache_id": 5, "tache_projet_id": 1}
        self._login()
        patchers = self._patched(**{"app.repositories.notifications.get_notification": notif})
        for p in patchers:
            p.start()
        try:
            r = self.client.post("/notifications/10/ouvrir")
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertTrue(r.headers["Location"].endswith("/projets/1?tache=5"), r.headers["Location"])


class _CsrfConfig(smoke.TestConfig):
    WTF_CSRF_ENABLED = True


class TestCsrfInformations(unittest.TestCase):
    _login = smoke.SmokeTestCase._login
    _patched = smoke.SmokeTestCase._patched

    def setUp(self):
        self.app = create_app(_CsrfConfig)
        self.client = self.app.test_client()
        self._login()
        self.patchers = self._patched(**{"app.auth.get_user_by_id": CHEF, "app.repositories.projets.get_projet": PROJET_OUVERT,
                                         "app.repositories.utilisateurs.get_utilisateur": SAMI,
                                         "app.repositories.utilisateurs.list_actifs": ACTIFS})
        for p in self.patchers:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patchers])

    def test_sans_jeton_refuse_avec_jeton_accepte(self):
        with patch("app.repositories.projets.update_projet", return_value=CHANGEMENT) as maj:
            self.client.post("/projets/1/informations", data=DONNEES)
            maj.assert_not_called()
            page = self.client.get("/projets/1").get_data(as_text=True)
            formulaire = page.split('id="dialog-informations-projet"', 1)[1]
            jeton = re.search(r'name="csrf_token" value="([^"]+)"', formulaire).group(1)
            self.client.post("/projets/1/informations", data={**DONNEES, "csrf_token": jeton})
            self.assertEqual(maj.call_args.kwargs["chef_projet_id"], 5)


if __name__ == "__main__":
    unittest.main()

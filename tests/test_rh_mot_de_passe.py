"""Décision du gérant (lot 10) : le RH ne fixe plus lui-même le mot de
passe d'un employé. Il peut seulement envoyer un lien de réinitialisation
(même mécanisme que « mot de passe oublié ») ; l'Admin garde la
possibilité de fixer un mot de passe depuis la fiche.

Corollaire : l'adresse e-mail d'un compte n'est modifiable que par un
Admin — sinon le RH pourrait la remplacer par une adresse qu'il contrôle,
s'y envoyer le lien et prendre la main sur le compte.

Et plus de faux succès : sans SMTP, les messages disent que l'e-mail n'a
pas pu partir (sans révéler, pour « mot de passe oublié », si l'email
correspond à un compte).

Même principe que tests/test_lot10.py (repositories remplacés par des
mocks) : on vérifie que l'action refusée n'est JAMAIS exécutée.
"""
import html
import re
import unittest
from unittest.mock import patch

try:  # python -m unittest discover -s tests
    import test_lot10 as lot10
    import test_smoke as smoke
except ImportError:  # python -m unittest tests.test_rh_mot_de_passe
    from tests import test_lot10 as lot10
    from tests import test_smoke as smoke

from app import create_app  # noqa: E402

RH = lot10.RH
CIBLE = {**smoke.AUTRE_UTILISATEUR, "id": 10}
CIBLE_INACTIVE = {**CIBLE, "actif": False}
ADMIN_CIBLE = lot10.ADMIN_CIBLE
FICHE = {"prenom": "Wael", "nom": "Testeur", "email": CIBLE["email"], "role": "intervenant",
         "equipe_code": "URBS"}

CREER = "app.repositories.utilisateurs.create_utilisateur"
MAJ = "app.repositories.utilisateurs.update_utilisateur_complet"
MDP = "app.repositories.utilisateurs.set_password"
JETON = "app.repositories.utilisateurs.set_reset_token"
ENVOYER = "app.mailer.envoyer"
GET_U = "app.repositories.utilisateurs.get_utilisateur"
QUI = "app.auth.get_user_by_id"
LIEN = "/utilisateurs/10/envoyer-lien"


class _Base(lot10._BaseLot10):
    def _flashes(self):
        with self.client.session_transaction() as sess:
            return [msg for _, msg in sess.pop("_flashes", [])]

    def _smtp(self, hote="smtp.midgard.tn"):
        self.app.config["SMTP_HOST"] = hote


class TestRHNeFixePlusDeMotDePasse(_Base):
    def test_rh_ne_voit_plus_le_champ_mot_de_passe(self):
        resp, _ = self._requete("get", "/utilisateurs/10", **{QUI: RH, GET_U: CIBLE})
        html = resp.data.decode()
        self.assertNotIn('name="nouveau_mot_de_passe"', html)
        self.assertIn("Envoyer un lien de réinitialisation", html)
        self.assertIn(f'action="{LIEN}"', html)

    def test_formulaire_du_lien_en_post_avec_csrf(self):
        resp, _ = self._requete("get", "/utilisateurs/10", **{QUI: RH, GET_U: CIBLE})
        m = re.search(r'<form[^>]*action="%s"[^>]*>(.*?)</form>' % re.escape(LIEN), resp.data.decode(), re.S)
        self.assertIsNotNone(m)
        self.assertIn('method="post"', m.group(0))
        self.assertIn('name="csrf_token"', m.group(1))

    def test_admin_garde_le_champ_mot_de_passe(self):
        resp, _ = self._requete("get", "/utilisateurs/10", **{GET_U: CIBLE})
        self.assertIn('name="nouveau_mot_de_passe"', resp.data.decode())

    def test_rh_mot_de_passe_force_refuse_sur_la_fiche(self):
        resp, m = self._requete("post", "/utilisateurs/10", {**FICHE, "nouveau_mot_de_passe": "x" * 12},
                                espions=[(MAJ, None), (MDP, None)], **{QUI: RH, GET_U: CIBLE})
        self.assertEqual(resp.status_code, 403)
        m[MAJ].assert_not_called()
        m[MDP].assert_not_called()

    def test_rh_mot_de_passe_force_refuse_sur_sa_propre_fiche(self):
        moi = {**CIBLE, "id": 7, "role": "rh"}
        resp, m = self._requete("post", "/utilisateurs/7", {**FICHE, "role": "rh", "nouveau_mot_de_passe": "x" * 12},
                                espions=[(MAJ, None), (MDP, None)], **{QUI: RH, GET_U: moi})
        self.assertEqual(resp.status_code, 403)
        m[MDP].assert_not_called()

    def test_rh_mot_de_passe_force_refuse_a_la_creation(self):
        for champ in ("mot_de_passe", "nouveau_mot_de_passe"):
            with self.subTest(champ=champ):
                resp, m = self._requete("post", "/utilisateurs/nouveau",
                                        {**FICHE, "actif": "on", champ: "x" * 12},
                                        espions=[(CREER, 11), (MDP, None)], **{QUI: RH})
                self.assertEqual(resp.status_code, 403)
                m[CREER].assert_not_called()
                m[MDP].assert_not_called()

    def test_rh_modifie_toujours_le_reste_de_la_fiche(self):
        resp, m = self._requete("post", "/utilisateurs/10", {**FICHE, "nouveau_mot_de_passe": ""},
                                espions=[(MAJ, None), (MDP, None)], **{QUI: RH, GET_U: CIBLE})
        self.assertEqual(resp.status_code, 302)
        m[MAJ].assert_called_once()
        m[MDP].assert_not_called()

    def test_admin_fixe_toujours_un_mot_de_passe(self):
        _, m = self._requete("post", "/utilisateurs/10", {**FICHE, "nouveau_mot_de_passe": "x" * 12},
                             espions=[(MAJ, None), (MDP, None)], **{GET_U: CIBLE})
        m[MAJ].assert_called_once()
        m[MDP].assert_called_once()


class TestEnvoyerLienReinitialisation(_Base):
    def test_rh_envoie_le_lien_a_l_email_enregistre(self):
        self._smtp()
        resp, m = self._requete("post", LIEN, {"email": "rh-perso@x.tn"},
                                espions=[(JETON, None), (ENVOYER, True), (MDP, None)], **{QUI: RH, GET_U: CIBLE})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/utilisateurs/10", resp.headers["Location"])
        m[JETON].assert_called_once()
        self.assertEqual(m[JETON].call_args.args[0], 10)
        m[ENVOYER].assert_called_once()
        self.assertEqual(m[ENVOYER].call_args.args[0], CIBLE["email"])
        self.assertIn("/reinitialiser/", m[ENVOYER].call_args.args[2])
        m[MDP].assert_not_called()  # le mot de passe actuel reste valable
        flashes = self._flashes()
        self.assertTrue(any("envoyé à " + CIBLE["email"] in f for f in flashes), flashes)

    def test_admin_peut_aussi_envoyer_le_lien(self):
        self._smtp()
        _, m = self._requete("post", LIEN, espions=[(JETON, None), (ENVOYER, True)], **{GET_U: CIBLE})
        m[ENVOYER].assert_called_once()

    def test_sans_smtp_pas_de_faux_succes(self):
        self._smtp(None)
        _, m = self._requete("post", LIEN, espions=[(JETON, None)], **{QUI: RH, GET_U: CIBLE})
        flashes = self._flashes()
        self.assertTrue(any("n’a pas pu être envoyé" in f and "SMTP" in f for f in flashes), flashes)
        self.assertFalse(any("envoyé à" in f for f in flashes), flashes)

    def test_smtp_en_panne_pas_de_faux_succes(self):
        self._smtp()
        _, m = self._requete("post", LIEN, espions=[(JETON, None), (ENVOYER, False)], **{QUI: RH, GET_U: CIBLE})
        flashes = self._flashes()
        self.assertTrue(any("n’a pas pu être envoyé" in f for f in flashes), flashes)
        self.assertFalse(any("envoyé à" in f for f in flashes), flashes)

    def test_rh_ne_peut_pas_viser_un_admin(self):
        self._smtp()
        _, m = self._requete("post", "/utilisateurs/9/envoyer-lien", espions=[(JETON, None), (ENVOYER, True)],
                             **{QUI: RH, GET_U: ADMIN_CIBLE})
        m[JETON].assert_not_called()
        m[ENVOYER].assert_not_called()

    def test_compte_desactive_refuse(self):
        self._smtp()
        _, m = self._requete("post", LIEN, espions=[(JETON, None), (ENVOYER, True)],
                             **{QUI: RH, GET_U: CIBLE_INACTIVE})
        m[JETON].assert_not_called()
        m[ENVOYER].assert_not_called()
        self.assertTrue(any("désactivé" in f for f in self._flashes()))

    def test_reserve_admin_et_rh(self):
        self._smtp()
        for role in ("chef_de_projet", "intervenant", "client"):
            with self.subTest(role=role):
                _, m = self._requete("post", LIEN, espions=[(JETON, None), (ENVOYER, True)],
                                     **{QUI: {**smoke.USER, "role": role}, GET_U: CIBLE})
                m[JETON].assert_not_called()
                m[ENVOYER].assert_not_called()

    def test_get_refuse(self):
        resp, _ = self._requete("get", LIEN, **{QUI: RH, GET_U: CIBLE})
        self.assertEqual(resp.status_code, 405)


class TestLienCsrf(unittest.TestCase):
    """Le bouton est un POST protégé par le jeton CSRF global."""

    def test_post_sans_jeton_refuse(self):
        app = create_app(smoke.CsrfTestConfig)
        app.config["SMTP_HOST"] = "smtp.midgard.tn"
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["pw_fingerprint"] = smoke.password_fingerprint(smoke.MOT_DE_PASSE_HASH_PAR_DEFAUT)
        patchers = smoke.SmokeTestCase._patched(None, **{QUI: RH, GET_U: CIBLE})
        for p in patchers:
            p.start()
        try:
            with patch(JETON) as jeton, patch(ENVOYER, return_value=True) as envoyer:
                client.post(LIEN)
        finally:
            for p in reversed(patchers):
                p.stop()
        jeton.assert_not_called()
        envoyer.assert_not_called()


class TestEmailReserveAdmin(_Base):
    """Règle choisie : seul un Admin change l'adresse e-mail d'un compte.
    Le RH ne peut donc pas rediriger le lien vers une adresse à lui."""

    def test_rh_ne_change_pas_l_email(self):
        resp, m = self._requete("post", "/utilisateurs/10", {**FICHE, "email": "rh-perso@x.tn"},
                                espions=[(MAJ, None)], **{QUI: RH, GET_U: CIBLE})
        m[MAJ].assert_not_called()
        html_page = html.unescape(resp.data.decode())
        self.assertIn("Seul un Admin peut changer l’adresse e-mail", html_page)
        # La fiche réaffichée garde l'adresse enregistrée, pas celle saisie.
        self.assertNotIn('value="rh-perso@x.tn"', html_page)

    def test_rh_garde_l_email_a_l_identique_meme_casse_differente(self):
        _, m = self._requete("post", "/utilisateurs/10", {**FICHE, "email": CIBLE["email"].upper()},
                             espions=[(MAJ, None)], **{QUI: RH, GET_U: CIBLE})
        m[MAJ].assert_called_once()
        self.assertEqual(m[MAJ].call_args.kwargs["email"], CIBLE["email"])

    def test_admin_change_l_email(self):
        _, m = self._requete("post", "/utilisateurs/10", {**FICHE, "email": "nouveau@midgard.tn"},
                             espions=[(MAJ, None)], **{GET_U: CIBLE})
        m[MAJ].assert_called_once()
        self.assertEqual(m[MAJ].call_args.kwargs["email"], "nouveau@midgard.tn")

    def test_champ_email_en_lecture_seule_pour_le_rh(self):
        resp, _ = self._requete("get", "/utilisateurs/10", **{QUI: RH, GET_U: CIBLE})
        champ = re.search(r'<input[^>]*id="email"[^>]*>', resp.data.decode()).group(0)
        self.assertIn("readonly", champ)
        resp, _ = self._requete("get", "/utilisateurs/10", **{GET_U: CIBLE})
        champ = re.search(r'<input[^>]*id="email"[^>]*>', resp.data.decode()).group(0)
        self.assertNotIn("readonly", champ)


class TestCreationParLeRH(_Base):
    DATA = {**FICHE, "email": "nouvel@midgard.tn", "actif": "on"}

    def test_compte_cree_sans_mot_de_passe_et_lien_envoye(self):
        self._smtp()
        _, m = self._requete("post", "/utilisateurs/nouveau", self.DATA,
                             espions=[(CREER, 11), (JETON, None), (ENVOYER, True), (MDP, None)], **{QUI: RH})
        m[CREER].assert_called_once()
        self.assertFalse(m[CREER].call_args.kwargs["verifie"])
        m[MDP].assert_not_called()
        self.assertEqual(m[JETON].call_args.args[0], 11)
        self.assertEqual(m[ENVOYER].call_args.args[0], "nouvel@midgard.tn")
        self.assertTrue(any("Un email lui a été envoyé" in f for f in self._flashes()))

    def test_sans_smtp_le_compte_existe_et_le_message_le_dit(self):
        self._smtp(None)
        resp, m = self._requete("post", "/utilisateurs/nouveau", self.DATA,
                                espions=[(CREER, 11), (JETON, None)], **{QUI: RH})
        self.assertEqual(resp.status_code, 302)
        flashes = self._flashes()
        self.assertTrue(any(f.startswith("Compte créé") and "n’a pas pu être envoyé" in f for f in flashes), flashes)
        # Le RH ne peut plus fixer de mot de passe : on ne le lui propose pas.
        self.assertFalse(any("définissez-lui un mot de passe" in f for f in flashes), flashes)
        self.assertTrue(any("Envoyer un lien de réinitialisation" in f for f in flashes), flashes)

    def test_erreur_apres_creation_ne_dit_pas_impossible_de_creer(self):
        """Le compte est créé : une panne lors de la génération du lien ne
        doit pas faire croire qu'il n'existe pas (on le recréerait en
        doublon)."""
        self._smtp()
        self._login()
        patchers = self._patched(**{QUI: RH})
        for p in patchers:
            p.start()
        try:
            with patch(CREER, return_value=11) as creer, \
                 patch(JETON, side_effect=Exception("panne")), \
                 patch(ENVOYER, return_value=True) as envoyer:
                resp = self.client.post("/utilisateurs/nouveau", data=self.DATA)
        finally:
            for p in reversed(patchers):
                p.stop()
        creer.assert_called_once()
        envoyer.assert_not_called()
        self.assertEqual(resp.status_code, 302)
        flashes = self._flashes()
        self.assertFalse(any("Impossible de créer" in f for f in flashes), flashes)
        self.assertTrue(any(f.startswith("Compte créé") and "n’a pas pu être envoyé" in f for f in flashes), flashes)

    def test_admin_se_voit_proposer_les_deux_solutions(self):
        self._smtp(None)
        self._requete("post", "/utilisateurs/nouveau", self.DATA, espions=[(CREER, 11), (JETON, None)])
        self.assertTrue(any("définissez-lui un mot de passe" in f for f in self._flashes()))


class TestMotDePasseOublieSansFauxSucces(_Base):
    """Sans SMTP, « mot de passe oublié » ne prétend plus avoir envoyé un
    lien — et le message reste le même que l'email existe ou non."""

    def _demander(self, utilisateur):
        with patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.repositories.securite.enregistrer_tentative"), \
             patch("app.auth.get_user_by_email", return_value=utilisateur), \
             patch(JETON), patch(ENVOYER, return_value=False):
            self.client.post("/mot-de-passe-oublie", data={"email": "x@midgard.tn"})
        return self._flashes()

    def test_sans_smtp_message_clair_et_identique(self):
        self._smtp(None)
        connu = self._demander({**smoke.USER, "actif": True})
        inconnu = self._demander(None)
        self.assertEqual(connu, inconnu)
        self.assertFalse(any("vient d’être envoyé" in f or "lui est envoyé" in f for f in connu), connu)
        self.assertTrue(any("Impossible d’envoyer le lien" in f and "pas configuré" in f for f in connu), connu)

    def test_avec_smtp_message_generique_identique(self):
        self._smtp()
        connu = self._demander({**smoke.USER, "actif": True})
        inconnu = self._demander(None)
        self.assertEqual(connu, inconnu)
        self.assertTrue(any("un lien de réinitialisation" in f for f in connu), connu)


if __name__ == "__main__":
    unittest.main()

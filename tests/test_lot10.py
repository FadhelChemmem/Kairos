"""Tests du lot 10 (intégration des audits sécurité, données et QA du
2026-10-07) : décisions 1, 2, 3 et 5 du gérant, entrées forgées,
notifications en double, sessions, durcissement, `flask migrer`.

Même principe que tests/test_smoke.py (psycopg2 simulé, repositories
remplacés par des mocks) : on vérifie que l'action protégée n'est JAMAIS
exécutée quand elle doit être refusée. Le SQL lui-même est vérifié sur un
vrai PostgreSQL par tests/sql/ et tests_integration/.
"""
import contextlib
import hashlib
import pathlib
import unittest
from unittest.mock import MagicMock, patch

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
except ImportError:  # python -m unittest tests.test_lot10
    from tests import test_smoke as smoke

from app import create_app, db  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parent.parent


class _FauxCurseur:
    """Curseur minimal pour `flask migrer` : mémorise le SQL exécuté et
    sert le contenu (simulé) de schema_migrations."""

    def __init__(self, journal, deja):
        self.journal, self.deja = journal, deja
        self._lignes = []
        self.connection = MagicMock(notices=[])

    def execute(self, sql, params=None):
        self.journal.append((" ".join(sql.split()), params))
        if sql.startswith("SELECT version, checksum"):
            self._lignes = [{"version": v, "checksum": c} for v, c in self.deja.items()]
        if sql.startswith("INSERT INTO schema_migrations"):
            self.deja[params[0]] = params[1]

    def fetchall(self):
        return self._lignes

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestFlaskMigrer(unittest.TestCase):
    """Audits données (M4) et QA (I5) : verrou, délai de verrouillage,
    empreintes des migrations publiées."""

    def _migrer(self, deja):
        journal = []
        verrou = MagicMock()
        verrou.cursor.side_effect = lambda: _FauxCurseur(journal, deja)
        pool = MagicMock()
        pool.getconn.return_value = verrou

        @contextlib.contextmanager
        def faux_get_cursor(*a, **k):
            yield _FauxCurseur(journal, deja)

        app = create_app(smoke.TestConfig)
        with patch.object(db, "_pool", pool), patch.object(db, "get_cursor", faux_get_cursor):
            res = app.test_cli_runner().invoke(args=["migrer"])
        return res, [sql for sql, _ in journal], pool

    @staticmethod
    def _empreinte(nom):
        return hashlib.sha256((RACINE / "migrations" / f"{nom}.sql").read_bytes()).hexdigest()

    def _toutes(self, sauf=()):
        return {f.stem: self._empreinte(f.stem) for f in sorted((RACINE / "migrations").glob("*.sql"))
                if f.stem not in sauf}

    def test_verrou_pris_puis_rendu(self):
        res, sqls, pool = self._migrer(self._toutes())
        self.assertEqual(res.exit_code, 0, res.output)
        self.assertIn("Rien à faire", res.output)
        self.assertIn("SELECT pg_advisory_lock(hashtext('kairos:flask-migrer'))", sqls)
        self.assertIn("SELECT pg_advisory_unlock(hashtext('kairos:flask-migrer'))", sqls)
        pool.putconn.assert_called_once()

    def test_migration_jouee_avec_lock_timeout_et_empreinte(self):
        deja = self._toutes(sauf=("0013_rattrapage_et_integrite",))
        res, sqls, _ = self._migrer(deja)
        self.assertEqual(res.exit_code, 0, res.output)
        self.assertIn("Application de 0013_rattrapage_et_integrite.sql", res.output)
        self.assertIn("SET LOCAL lock_timeout = '15s'", sqls)
        self.assertEqual(deja["0013_rattrapage_et_integrite"], self._empreinte("0013_rattrapage_et_integrite"))

    def test_migration_modifiee_apres_application_signalee(self):
        deja = self._toutes()
        deja["0011_roles_et_projets_clos"] = "0" * 64
        res, _, _ = self._migrer(deja)
        self.assertEqual(res.exit_code, 0)
        self.assertIn("ATTENTION : 0011_roles_et_projets_clos.sql a été modifiée", res.output)

    def test_empreinte_manquante_enregistree(self):
        deja = self._toutes()
        deja["0001_equipe_urbs_ipco"] = None
        res, sqls, _ = self._migrer(deja)
        self.assertNotIn("ATTENTION", res.output)
        self.assertTrue(any(s.startswith("UPDATE schema_migrations SET checksum") for s in sqls))


RH = {**smoke.USER, "id": 7, "role": "rh", "prenom": "Rym", "nom": "Hadj", "equipe_code": None}
ADMIN = smoke.USER  # id 1, rôle admin
ADMIN_CIBLE = {**smoke.AUTRE_UTILISATEUR, "id": 9, "role": "admin"}
INTERVENANT_CIBLE = {**smoke.AUTRE_UTILISATEUR, "id": 10, "role": "intervenant"}
FICHE = {"prenom": "Ali", "nom": "Ben", "email": "ali@midgard.tn", "role": "intervenant"}


class _BaseLot10(smoke.SmokeBase):
    def _requete(self, methode, chemin, data=None, espions=(), **overrides):
        """Requête avec les mocks par défaut de test_smoke (+ overrides) et
        des espions (cible -> valeur de retour) ; renvoie (réponse, espions)."""
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        mocks = {}
        try:
            for cible, valeur in espions:
                pp = patch(cible, return_value=valeur)
                mocks[cible] = pp.start()
                patchers.append(pp)
            resp = getattr(self.client, methode)(chemin, data=data or {})
        finally:
            for p in reversed(patchers):
                p.stop()
        return resp, mocks


class TestDecision1RHEtAdmin(_BaseLot10):
    """Décision 1 : le RH ne peut ni créer, ni promouvoir, ni modifier (mot
    de passe, email, activation, rôle) un Admin. L'Admin, lui, le peut."""

    CREER = "app.repositories.utilisateurs.create_utilisateur"
    MAJ = "app.repositories.utilisateurs.update_utilisateur_complet"
    MDP = "app.repositories.utilisateurs.set_password"
    ACTIF = "app.repositories.utilisateurs.set_actif"

    def test_rh_ne_cree_pas_d_admin(self):
        _, m = self._requete("post", "/utilisateurs/nouveau", {**FICHE, "role": "admin", "actif": "on"},
                             espions=[(self.CREER, 11)], **{"app.auth.get_user_by_id": RH})
        m[self.CREER].assert_not_called()

    def test_rh_ne_promeut_pas_en_admin(self):
        _, m = self._requete("post", "/utilisateurs/10", {**FICHE, "role": "admin"}, espions=[(self.MAJ, None)],
                             **{"app.auth.get_user_by_id": RH,
                                "app.repositories.utilisateurs.get_utilisateur": INTERVENANT_CIBLE})
        m[self.MAJ].assert_not_called()

    def test_rh_ne_modifie_pas_un_admin(self):
        data = {**FICHE, "role": "admin", "email": "rh-perso@x.tn", "nouveau_mot_de_passe": "x" * 12}
        resp, m = self._requete("post", "/utilisateurs/9", data, espions=[(self.MAJ, None), (self.MDP, None)],
                                **{"app.auth.get_user_by_id": RH,
                                   "app.repositories.utilisateurs.get_utilisateur": ADMIN_CIBLE})
        self.assertEqual(resp.status_code, 302)
        m[self.MAJ].assert_not_called()
        m[self.MDP].assert_not_called()

    def test_rh_ne_retrograde_pas_un_admin(self):
        _, m = self._requete("post", "/utilisateurs/9", {**FICHE, "role": "intervenant"}, espions=[(self.MAJ, None)],
                             **{"app.auth.get_user_by_id": RH,
                                "app.repositories.utilisateurs.get_utilisateur": ADMIN_CIBLE})
        m[self.MAJ].assert_not_called()

    def test_rh_ne_desactive_pas_un_admin(self):
        _, m = self._requete("post", "/utilisateurs/9/toggle-actif", {"actif_cible": "0"},
                             espions=[(self.ACTIF, True)],
                             **{"app.auth.get_user_by_id": RH,
                                "app.repositories.utilisateurs.get_utilisateur": ADMIN_CIBLE})
        m[self.ACTIF].assert_not_called()

    def test_rh_ne_voit_pas_l_option_admin(self):
        resp, _ = self._requete("get", "/utilisateurs/nouveau", **{"app.auth.get_user_by_id": RH})
        self.assertNotIn('value="admin"', resp.data.decode())
        resp, _ = self._requete("get", "/utilisateurs/9", **{
            "app.auth.get_user_by_id": RH, "app.repositories.utilisateurs.get_utilisateur": ADMIN_CIBLE})
        self.assertIn("<fieldset disabled", resp.data.decode())

    def test_rh_garde_la_main_sur_les_autres_comptes(self):
        # Même email : seul un Admin peut le changer (lot 10, lien de
        # réinitialisation — voir tests/test_rh_mot_de_passe.py).
        _, m = self._requete("post", "/utilisateurs/10",
                             {**FICHE, "email": INTERVENANT_CIBLE["email"], "role": "chef_de_projet"},
                             espions=[(self.MAJ, None)],
                             **{"app.auth.get_user_by_id": RH,
                                "app.repositories.utilisateurs.get_utilisateur": INTERVENANT_CIBLE})
        m[self.MAJ].assert_called_once()

    def test_admin_peut_tout_sur_un_admin(self):
        _, m = self._requete("post", "/utilisateurs/nouveau", {**FICHE, "role": "admin"},
                             espions=[(self.CREER, 11)])
        m[self.CREER].assert_called_once()
        _, m = self._requete("post", "/utilisateurs/9", {**FICHE, "role": "admin", "nouveau_mot_de_passe": "x" * 12},
                             espions=[(self.MAJ, None), (self.MDP, None)],
                             **{"app.repositories.utilisateurs.get_utilisateur": ADMIN_CIBLE})
        m[self.MAJ].assert_called_once()
        m[self.MDP].assert_called_once()

    def test_dernier_admin_message_clair(self):
        """Refus du trigger trg_garde_comptes_admin (0013) : message, pas de 500."""
        erreur = Exception("Impossible : ce compte est le dernier Admin actif.")
        self._login()
        patchers = self._patched(**{"app.repositories.utilisateurs.get_utilisateur": ADMIN_CIBLE})
        for p in patchers:
            p.start()
        try:
            with patch(self.MAJ, side_effect=erreur):
                resp = self.client.post("/utilisateurs/9", data={**FICHE, "role": "intervenant"},
                                        follow_redirects=False)
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("dernier Admin actif", resp.data.decode())


class TestDecision2AdminCoChef(unittest.TestCase):
    """Décision 2 : l'Admin a les droits de co-chef sur tous les projets,
    réouverture comprise. Comportement prouvé sur vraie base par
    tests_integration (test_admin_co_chef_de_tous_les_projets) ; ici, la
    clause elle-même."""

    def test_clause_admin_dans_user_can_manage_et_je_gere(self):
        import inspect
        from app.repositories import posts, projets
        self.assertIn("ux.role = 'admin'", inspect.getsource(projets.user_can_manage))
        self.assertIn("ua.role = 'admin'", posts._FEED_SELECT)


class _CurseurEspion:
    def __init__(self, role, rowcount=1):
        self.role, self.rowcount, self.sql = role, rowcount, []

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))

    def fetchone(self):
        return {"role": self.role}


class TestDecision3CoChefAutomatique(_BaseLot10):
    def _ajouter(self, role, rowcount=1):
        cur = _CurseurEspion(role, rowcount)

        @contextlib.contextmanager
        def faux(*a, **k):
            yield cur

        from app.repositories import projets
        with patch.object(db, "get_cursor", faux):
            ajoute = projets.add_intervenant(1, 5, 1)
        return ajoute, cur.sql[-1]

    def test_chef_ajoute_comme_intervenant_devient_co_chef(self):
        ajoute, sql = self._ajouter("chef_de_projet")
        self.assertTrue(ajoute)
        self.assertIn("INSERT INTO projet_co_chef", sql)
        self.assertIn("p.chef_projet_id <>", sql)  # jamais co-chef de son propre projet

    def test_intervenant_reste_intervenant(self):
        ajoute, sql = self._ajouter("intervenant")
        self.assertIn("INSERT INTO projet_intervenant", sql)

    def test_deja_rattache_ni_notifie_ni_ajoute(self):
        ajoute, _ = self._ajouter("intervenant", rowcount=0)
        self.assertFalse(ajoute)

    def test_notification_co_chef(self):
        chef = {**INTERVENANT_CIBLE, "role": "chef_de_projet"}
        _, m = self._requete("post", "/projets/1/intervenants", {"utilisateur_id": "10"},
                             espions=[("app.repositories.projets.add_intervenant", True),
                                      ("app.repositories.notifications.creer", 1)],
                             **{"app.repositories.utilisateurs.get_utilisateur": chef})
        self.assertIn("co-chef", m["app.repositories.notifications.creer"].call_args.args[2])

    def test_second_ajout_pas_de_notification(self):
        _, m = self._requete("post", "/projets/1/intervenants", {"utilisateur_id": "10"},
                             espions=[("app.repositories.projets.add_intervenant", False),
                                      ("app.repositories.notifications.creer", 1)],
                             **{"app.repositories.utilisateurs.get_utilisateur": INTERVENANT_CIBLE})
        m["app.repositories.notifications.creer"].assert_not_called()


class TestDecision5TachesClosesMasquees(unittest.TestCase):
    """Décision 5 : Vérifiée et Arrêt retirées de Mes tâches et des
    Deadlines (prouvé sur vraie base par tests_integration)."""

    def test_seules_les_taches_en_cours(self):
        import inspect
        from app.repositories import projets, taches
        for fn in (taches.list_mes_taches, taches.list_deadlines, taches.list_en_cours_pour_profil):
            with self.subTest(fn=fn.__name__):
                self.assertIn("WHERE t.etat = 'en_cours'", inspect.getsource(fn))
        # Lot 11 : « Prochain rendu » et tri de la liste, même règle (ni Bloquée).
        source = inspect.getsource(projets.list_projets)
        self.assertEqual(source.count("t.etat = 'en_cours'"), 3)
        self.assertNotIn("'verifie', 'arret'", source)



class TestEntreesForgees(_BaseLot10):
    """Audit sécurité I14 / M18, audit données M5 : plus d'erreur 500 sur
    une entrée forgée, et les jokers LIKE sont pris littéralement."""

    def test_ids_entiers_chiffres_ascii_sans_doublon(self):
        from app.validation import ids_entiers
        self.assertEqual(ids_entiers(["1", "²", "٣", "1", "x", "007", "1" * 19, "", None, " 2"]), [1, 7])

    def test_motif_like_litteral(self):
        from app.repositories._like import motif_contient
        self.assertEqual(motif_contient("__"), "%\\_\\_%")
        self.assertEqual(motif_contient(" 50% "), "%50\\%%")
        self.assertEqual(motif_contient("a\\b"), "%a\\\\b%")

    def test_exposant_dans_les_ids_sans_500(self):
        cas = [
            ("get", "/admin/journal?utilisateur_id=%C2%B2", None),
            ("get", "/projets?filtres_actifs=1&chef_id=%C2%B2", None),
            ("post", "/posts", {"projet_id": "1", "type_code": "requete", "contenu": "x", "mentions": "²"}),
            ("post", "/projets/1/taches", {"titre": "T", "type_deadline": "interne", "intervenants": "²"}),
        ]
        for methode, chemin, data in cas:
            with self.subTest(chemin=chemin):
                resp, _ = self._requete(methode, chemin, data, espions=[
                    ("app.repositories.posts.create_post", 1), ("app.repositories.taches.create_tache", 1)])
                self.assertLess(resp.status_code, 500)

    def test_role_hors_enum_ignore(self):
        _, m = self._requete("get", "/utilisateurs?role=foo",
                             espions=[("app.repositories.utilisateurs.list_tous", [])])
        self.assertIsNone(m["app.repositories.utilisateurs.list_tous"].call_args.kwargs["role"])

    def test_email_de_300_caracteres_sans_500(self):
        email = "a" * 290 + "@x.tn"
        with patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.auth.get_user_by_email", return_value=None), \
             patch("app.repositories.securite.enregistrer_tentative") as enregistrer:
            resp = self.client.post("/connexion", data={"email": email, "password": "x"})
            self.assertLess(resp.status_code, 500)
            self.assertTrue(all(len(c.args[1]) <= 255 for c in enregistrer.call_args_list))
            resp = self.client.post("/mot-de-passe-oublie", data={"email": email})
            self.assertLess(resp.status_code, 500)
            self.assertTrue(all(len(c.args[1]) <= 255 for c in enregistrer.call_args_list))

    def test_caractere_nul_refuse_400(self):
        resp, m = self._requete("post", "/posts", {"projet_id": "1", "type_code": "requete", "contenu": "a\x00b"},
                                espions=[("app.repositories.posts.create_post", 1)])
        self.assertEqual(resp.status_code, 400)
        m["app.repositories.posts.create_post"].assert_not_called()
        resp, _ = self._requete("get", "/projets?q=%00")
        self.assertEqual(resp.status_code, 400)

    def test_nom_de_fichier_long_ou_nul(self):
        import tempfile
        from app import storage

        class Fichier:
            def __init__(self, nom):
                self.filename = nom

            def save(self, dst):
                pathlib.Path(dst).write_bytes(b"x")

        with tempfile.TemporaryDirectory() as d, self.app.app_context():
            self.app.config["UPLOAD_DIR"] = d
            nom, chemin = storage.save_upload(Fichier("n" * 300 + ".pdf"), "taches/1")
            self.assertLessEqual(len(nom), 255)
            self.assertTrue(nom.endswith(".pdf") and chemin.endswith(".pdf"))
            nom, _ = storage.save_upload(Fichier("plan\x00.pdf"), "taches/1")
            self.assertEqual(nom, "plan.pdf")



class TestDoublonsEtIdempotence(_BaseLot10):
    """Audit sécurité I3, I12, M1 ; audit données M7, M8."""

    def test_mentions_repetees_une_seule_notification(self):
        from app.repositories import notifications
        with patch.object(notifications, "creer") as creer:
            notifications.creer_pour_plusieurs([5, 5, 6, 5], "projet", "m", exclure_id=6)
        self.assertEqual([c.args[0] for c in creer.call_args_list], [5])

    def test_information_sans_projet_mention_hors_equipe_ou_client_ignoree(self):
        actifs = [
            {"id": 3, "prenom": "A", "nom": "M", "poste": None, "role": "intervenant", "equipe_code": "MIDGARD"},
            {"id": 4, "prenom": "B", "nom": "U", "poste": None, "role": "intervenant", "equipe_code": "URBS"},
            {"id": 5, "prenom": "C", "nom": "C", "poste": None, "role": "client", "equipe_code": "MIDGARD"},
        ]
        intervenant = {**smoke.USER, "role": "intervenant"}
        _, m = self._requete("post", "/posts", {"type_code": "information", "equipes": "MIDGARD",
                                                 "contenu": "x", "mentions": ["3", "4", "5", "3"]},
                             espions=[("app.repositories.posts.create_post", 1)],
                             **{"app.auth.get_user_by_id": intervenant,
                                "app.repositories.utilisateurs.list_actifs": actifs})
        self.assertEqual(m["app.repositories.posts.create_post"].call_args.kwargs["mentionne_ids"], [3])

    def test_activation_idempotente(self):
        for cible, attendu in (("0", False), ("1", True)):
            with self.subTest(cible=cible):
                _, m = self._requete("post", "/utilisateurs/2/toggle-actif", {"actif_cible": cible},
                                     espions=[("app.repositories.utilisateurs.set_actif", True)],
                                     **{"app.repositories.utilisateurs.get_utilisateur": smoke.AUTRE_UTILISATEUR})
                self.assertEqual(m["app.repositories.utilisateurs.set_actif"].call_args.args[:2], (2, attendu))

    def test_activation_sans_etat_voulu_refusee(self):
        _, m = self._requete("post", "/utilisateurs/2/toggle-actif", {},
                             espions=[("app.repositories.utilisateurs.set_actif", True)],
                             **{"app.repositories.utilisateurs.get_utilisateur": smoke.AUTRE_UTILISATEUR})
        m["app.repositories.utilisateurs.set_actif"].assert_not_called()

    def test_activation_compte_inexistant(self):
        resp, m = self._requete("post", "/utilisateurs/99999/toggle-actif", {"actif_cible": "0"},
                                espions=[("app.repositories.utilisateurs.set_actif", False)],
                                **{"app.repositories.utilisateurs.get_utilisateur": None})
        m["app.repositories.utilisateurs.set_actif"].assert_not_called()
        with self.client.session_transaction() as sess:
            self.assertTrue(any("introuvable" in msg for _, msg in sess.get("_flashes", [])))

    def test_set_actif_pose_la_valeur(self):
        from app.repositories import utilisateurs
        with patch.object(db, "execute", return_value=1) as execute:
            self.assertTrue(utilisateurs.set_actif(4, False, 1))
        self.assertIn("SET actif = %s", execute.call_args.args[0])
        self.assertEqual(execute.call_args.args[1], (False, 4))



class TestSessions(_BaseLot10):
    """Audit sécurité I7 (cookie rejouable après déconnexion ou
    réactivation, pas de durée absolue) et I13 (rappel Daily log)."""

    def _accueil(self, utilisateur=None, **session):
        self._login()
        with self.client.session_transaction() as sess:
            sess.update(session)
        return self._requete("get", "/accueil", espions=[("app.auth._verifier_rappel_dailylog", None)],
                             **{"app.auth.get_user_by_id": utilisateur or smoke.USER})

    def test_deconnexion_revoque_toutes_les_sessions(self):
        _, m = self._requete("post", "/deconnexion", espions=[("app.repositories.utilisateurs.revoquer_sessions", None)])
        m["app.repositories.utilisateurs.revoquer_sessions"].assert_called_once_with(1)

    def test_cookie_d_une_generation_revoquee_refuse(self):
        resp, _ = self._accueil({**smoke.USER, "session_gen": 2}, gen=1)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/connexion", resp.headers["Location"])

    def test_session_d_avant_le_correctif_reste_valide(self):
        resp, _ = self._accueil({**smoke.USER, "session_gen": 0})
        self.assertEqual(resp.status_code, 200)

    def test_duree_absolue_depassee(self):
        import time
        trop_vieux = int(time.time()) - 31 * 86400
        resp, _ = self._accueil(iat=trop_vieux)
        self.assertEqual(resp.status_code, 302)
        resp, _ = self._accueil(iat=int(time.time()) - 86400)
        self.assertEqual(resp.status_code, 200)

    def test_connexion_memorise_generation_et_debut(self):
        user_row = {**smoke.USER, "mot_de_passe_hash": "h", "session_gen": 4}
        with patch("app.auth.get_user_by_email", return_value=user_row), \
             patch("app.auth.verify_password", return_value=True), \
             patch("app.repositories.utilisateurs.set_password"), \
             patch("app.auth._verifier_rappel_dailylog"), \
             patch("app.repositories.securite.compter_tentatives_recentes", return_value=0):
            self.client.post("/connexion", data={"email": "a@b.tn", "password": "x"})
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["gen"], 4)
            self.assertIsInstance(sess["iat"], int)

    def test_rappel_daily_log_une_fois_par_jour_sans_reconnexion(self):
        import datetime
        from app.repositories import dailylog
        _, m = self._accueil()
        # Lot 10 (Daily log v9) : la personne entière (fuseau, date d'arrivée).
        self.assertEqual(m["app.auth._verifier_rappel_dailylog"].call_args.args[0]["id"], 1)
        _, m = self._accueil(rappel_le=dailylog.aujourdhui_pour(smoke.USER).isoformat())
        m["app.auth._verifier_rappel_dailylog"].assert_not_called()
        _, m = self._accueil(RH)
        m["app.auth._verifier_rappel_dailylog"].assert_not_called()



class TestDurcissement(unittest.TestCase):
    """Audit sécurité I8, I9, I10 ; audit QA m5, m6."""

    def test_starttls_verifie_le_certificat(self):
        import ssl
        app = create_app(smoke.TestConfig)
        app.config.update(SMTP_HOST="smtp.exemple.tn", SMTP_USE_TLS=True)
        from app import mailer
        with app.app_context(), patch("smtplib.SMTP") as smtp:
            self.assertTrue(mailer.envoyer("a@b.tn", "s", "c"))
        serveur = smtp.return_value.__enter__.return_value
        contexte = serveur.starttls.call_args.kwargs["context"]
        self.assertEqual(contexte.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(contexte.check_hostname)

    def _config(self, proxys, bind):
        class C(smoke.TestConfig):
            TESTING = False
            SECRET_KEY = "k" * 40
            TRUSTED_PROXY_COUNT = proxys
            WEB_BIND = bind
        return C

    def test_proxy_de_confiance_demarre_quel_que_soit_web_bind(self):
        """Décision du gérant (fin du lot 10) : plus de refus de démarrer ;
        les en-têtes ne sont crus que depuis TRUSTED_PROXY_IPS (voir
        tests/test_decisions_gerant.py)."""
        with self.assertLogs("app.proxy", "WARNING"):
            create_app(self._config(1, "0.0.0.0"))
        create_app(self._config(1, "127.0.0.1"))
        create_app(self._config(0, "0.0.0.0"))

    def test_jeton_masque_dans_le_journal_gunicorn(self):
        import importlib.util
        import logging
        spec = importlib.util.spec_from_file_location("gunicorn_conf", RACINE / "gunicorn.conf.py")
        conf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(conf)
        args = {"r": "GET /reinitialiser/AbC-123_x HTTP/1.1", "f": "https://k.tn/reinitialiser/AbC-123_x?a=1",
                "U": "/reinitialiser/AbC-123_x", "s": "200"}
        record = logging.LogRecord("gunicorn.access", logging.INFO, "", 0, '%(r)s %(s)s "%(f)s"', None, None)
        record.args = args
        self.assertTrue(conf.MasqueJetonReset().filter(record))
        ligne = record.getMessage()
        self.assertNotIn("AbC-123_x", ligne)
        self.assertIn("GET /reinitialiser/*** HTTP/1.1 200", ligne)
        self.assertIn("/reinitialiser/***?a=1", ligne)

    def test_dockerfile_charge_gunicorn_conf(self):
        self.assertIn("gunicorn -c gunicorn.conf.py", (RACINE / "Dockerfile").read_text(encoding="utf-8"))

    def test_variables_vides_dans_env_sans_plantage(self):
        import importlib
        import os
        from app import config
        with patch.dict(os.environ, {"SMTP_PORT": "", "MAX_CONTENT_LENGTH": ""}):
            importlib.reload(config)
            self.assertEqual(config.Config.SMTP_PORT, 587)
        importlib.reload(config)

    def test_serveur_de_dev_local_seulement(self):
        self.assertIn('host="127.0.0.1"', (RACINE / "wsgi.py").read_text(encoding="utf-8"))



class TestFichiersIgnores(unittest.TestCase):
    """Audits sécurité I16 / QA I7 : fichiers sensibles hors de git, et
    image Docker construite sur liste blanche."""

    SENSIBLES = (".env", ".env.prod", "kairos_2026-10-01_0300.sql.gz", "dump.sql", "kairos.dump",
                 "export_rh.csv", "identifiants.csv", "migration_2026.sql", "liste.xlsx", "Remarques.docx",
                 "sous/capture.png", "sous/kairos.tar.gz")
    VERSIONNES = ("schema.sql", "migrations/0013_rattrapage_et_integrite.sql", "tests/sql/rattrapage_0013.sql",
                  ".env.example", "app/static/img/kairos-logo.png")

    def _git(self, *args):
        import shutil
        import subprocess
        if not shutil.which("git") or not (RACINE / ".git").exists():
            self.skipTest("dépôt git indisponible")
        return subprocess.run(["git", *args], cwd=RACINE, capture_output=True, text=True)

    def test_gitignore(self):
        for f in self.SENSIBLES:
            with self.subTest(fichier=f):
                self.assertEqual(self._git("check-ignore", "-q", "--no-index", f).returncode, 0)
        for f in self.VERSIONNES:
            with self.subTest(fichier=f):
                self.assertEqual(self._git("check-ignore", "-q", "--no-index", f).returncode, 1)

    def test_dockerignore_liste_blanche(self):
        lignes = [l.strip() for l in (RACINE / ".dockerignore").read_text(encoding="utf-8").splitlines()
                  if l.strip() and not l.startswith("#")]
        self.assertEqual(lignes[0], "*")
        autorises = {l[1:] for l in lignes if l.startswith("!")}
        self.assertEqual(autorises, {"app/", "migrations/", "wsgi.py", "requirements.txt", "gunicorn.conf.py"})



class TestVerrouProjet(unittest.TestCase):
    """Audit données I2 : verrou du projet AVANT tout changement d'état de
    tâche (write skew « projet resté Bloqué »). La concurrence réelle est
    testée sur PostgreSQL (tests_integration)."""

    def test_premiere_instruction_verrouille_le_projet(self):
        from app.repositories import taches

        class Curseur:
            rowcount = 0

            def __init__(self):
                self.sql = []

            def execute(self, sql, params=None):
                self.sql.append(" ".join(sql.split()))

            def fetchone(self):
                return None

        for appel in (lambda: taches.set_etat(5, 1, "termine", 1),
                      lambda: taches.close_tache(5, 1, 1, "information"),
                      lambda: taches.create_tache(1, "T", 1)):
            cur = Curseur()

            @contextlib.contextmanager
            def faux(*a, **k):
                yield cur

            with patch.object(db, "get_cursor", faux):
                try:
                    appel()
                except Exception:
                    pass  # le faux curseur ne renvoie rien : seul l'ordre compte
            with self.subTest(sql=cur.sql[:1]):
                self.assertEqual(cur.sql[0], "SELECT 1 FROM projet WHERE id = %s FOR NO KEY UPDATE")



class TestDailyLogDesCollegues(_BaseLot10):
    """Audit sécurité I5 : un intervenant lisait le Daily log de ses
    collègues sur leur profil."""

    def _profil(self, visiteur, cible=5):
        return self._requete("get", f"/utilisateurs/{cible}/profil",
                             espions=[("app.repositories.dailylog.list_entrees_periode", [])],
                             **{"app.auth.get_user_by_id": visiteur,
                                "app.repositories.utilisateurs.get_utilisateur": {**smoke.AUTRE_UTILISATEUR, "id": 5}})

    def test_intervenant_ne_voit_pas_le_daily_log_d_un_collegue(self):
        resp, m = self._profil({**smoke.USER, "role": "intervenant"})
        self.assertEqual(resp.status_code, 200)
        m["app.repositories.dailylog.list_entrees_periode"].assert_not_called()
        self.assertNotIn('id="dailylog"', resp.data.decode())

    def test_soi_meme_admin_et_chef_le_voient(self):
        for visiteur, cible in (({**smoke.USER, "role": "intervenant"}, 1), (smoke.USER, 5),
                                ({**smoke.USER, "role": "chef_de_projet"}, 5)):
            with self.subTest(role=visiteur["role"], cible=cible):
                resp, _ = self._profil(visiteur, cible)
                self.assertIn('id="dailylog"', resp.data.decode())


if __name__ == "__main__":
    unittest.main()

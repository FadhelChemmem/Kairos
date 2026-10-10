"""Lot 12 — « Voir comme », « Agir comme », date simulée, liens vers les
tâches, vue Admin des Deadlines : logique pure, gabarits et routes
(psycopg2 simulé, repositories remplacés par des mocks, comme
tests/test_smoke.py). Le comportement sur vraie base (lecture seule
réelle, audit, gardes SQL) est dans tests_integration/test_lot12.py.
"""
import contextlib
import datetime
import html
import importlib
import os
import re
import unittest
from unittest.mock import MagicMock, patch

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
except ImportError:  # python -m unittest tests.test_lot12
    from tests import test_smoke as smoke

from flask import g  # noqa: E402

from app import create_app, db, horloge, mailer, modes_admin, utils  # noqa: E402
from app.repositories import dailylog as dl  # noqa: E402

ADMIN = {**smoke.USER, "id": 1, "role": "admin", "prenom": "Fadhel", "nom": "Admin", "fuseau": "Africa/Tunis",
         "session_gen": 0, "avatar_chemin": None}
ADMIN2 = {**ADMIN, "id": 2, "prenom": "Autre", "nom": "Admin"}
INTER = {"id": 3, "email": "rim@x.tn", "prenom": "Rim", "nom": "Inter", "role": "intervenant", "actif": True,
         "poste": "Technicienne", "equipe_code": "MIDGARD", "avatar_chemin": None, "fuseau": "Africa/Tunis",
         "debut_daily_log": datetime.date(2026, 1, 1), "session_gen": 0}
RH = {**INTER, "id": 4, "prenom": "Rania", "nom": "RH", "role": "rh", "equipe_code": None}
INACTIF = {**INTER, "id": 5, "prenom": "Ancien", "nom": "Compte", "actif": False}
COMPTES = {1: ADMIN, 2: ADMIN2, 3: INTER, 4: RH, 5: INACTIF}


class ConfigModeTest(smoke.TestConfig):
    MODE_TEST = True


class _Base(smoke.SmokeBase):
    config = smoke.TestConfig

    def setUp(self):
        smoke.sys.modules["psycopg2.pool"].ThreadedConnectionPool.appels = 0
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    def session(self, **cles):
        with self.client.session_transaction() as s:
            s["user_id"] = 1
            s["pw_fingerprint"] = smoke.password_fingerprint(smoke.MOT_DE_PASSE_HASH_PAR_DEFAUT)
            for cle, valeur in cles.items():
                if valeur is None:
                    s.pop(cle, None)
                else:
                    s[cle] = valeur

    def requete(self, methode, chemin, comptes=None, espions=(), **kw):
        """Requête avec les mocks par défaut, get_user_by_id selon l'id, et
        des espions (cible -> valeur) dont on garde les mocks."""
        comptes = COMPTES if comptes is None else comptes
        patchers = self._patched()
        patchers.append(patch("app.auth.get_user_by_id", side_effect=lambda uid: comptes.get(uid)))
        mocks = {}
        for cible, valeur in espions:
            p = patch(cible, side_effect=valeur) if callable(valeur) or isinstance(valeur, Exception) \
                else patch(cible, return_value=valeur)
            patchers.append(p)
        demarres = [p.start() for p in patchers]
        for (cible, _), m in zip(espions, demarres[-len(espions):] if espions else []):
            mocks[cible] = m
        try:
            resp = getattr(self.client, methode)(chemin, **kw)
        finally:
            for p in reversed(patchers):
                p.stop()
        return resp, mocks

    @staticmethod
    def texte(resp):
        return html.unescape(resp.get_data(as_text=True))

    @staticmethod
    def visible(resp):
        brut = html.unescape(resp.get_data(as_text=True))
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", brut)).replace("\xa0", " ")


# ---------------------------------------------------------------------
# Logique pure
# ---------------------------------------------------------------------
class TestHorloge(unittest.TestCase):
    def setUp(self):
        self.app = create_app(smoke.TestConfig)

    def test_sans_requete_ni_date_simulee_la_vraie_date(self):
        reel = datetime.datetime.now(datetime.timezone.utc).astimezone(horloge.ZoneInfo("Africa/Tunis")).date()
        self.assertIsNone(horloge.date_simulee())
        self.assertEqual(horloge.aujourdhui(), reel)
        with self.app.test_request_context("/"):
            self.assertEqual(horloge.aujourdhui("Africa/Tunis"), reel)

    def test_date_simulee_de_la_requete(self):
        simulee = datetime.date(2026, 10, 15)
        with self.app.test_request_context("/"):
            g.date_simulee = simulee
            self.assertEqual(horloge.aujourdhui(), simulee)
            self.assertEqual(horloge.aujourdhui("America/Cayenne"), simulee)
            maintenant = horloge.maintenant("Africa/Tunis")
            self.assertEqual(maintenant.date(), simulee)
            reel = datetime.datetime.now(datetime.timezone.utc).astimezone(horloge.ZoneInfo("Africa/Tunis"))
            self.assertLess(abs((maintenant.hour * 60 + maintenant.minute) - (reel.hour * 60 + reel.minute)), 2)
            # Le Daily log et tout ce qui passe par aujourdhui_pour suivent.
            self.assertEqual(dl.aujourdhui_pour(INTER), simulee)
            self.assertEqual(dl.aujourdhui_pour({"fuseau": "America/Cayenne"}), simulee)
            # Un `maintenant` injecté (tests) garde la priorité.
            self.assertEqual(dl.aujourdhui_pour(INTER, datetime.datetime(2026, 1, 2, 12, 0)), datetime.date(2026, 1, 2))
            # Valeur posée qui n'est pas une date : ignorée.
            g.date_simulee = "2026-10-15"
            self.assertNotEqual(horloge.aujourdhui(), simulee)

    def test_jours_manques_a_la_date_simulee(self):
        simulee = datetime.date(2026, 10, 15)  # jeudi
        with self.app.test_request_context("/"), \
                patch("app.repositories.dailylog.jours_renseignes", return_value=set()) as remplis:
            g.date_simulee = simulee
            manques = dl.jours_manques_recents({**INTER, "debut_daily_log": datetime.date(2026, 10, 12)})
        self.assertEqual([j for j in manques if j < simulee],
                         [datetime.date(2026, 10, 12), datetime.date(2026, 10, 13), datetime.date(2026, 10, 14)])
        self.assertTrue(remplis.called)

    def test_dates_affichees_et_gabarits(self):
        self.assertEqual(utils.date_longue(datetime.date(2026, 10, 15)), "jeudi 15 octobre 2026")
        self.assertEqual(utils.date_longue(datetime.date(2026, 11, 1)), "dimanche 1er novembre 2026")
        with self.app.test_request_context("/"):
            g.date_simulee = datetime.date(2031, 3, 2)
            self.assertEqual(self.app.jinja_env.globals["today"](), datetime.date(2031, 3, 2))
            # L'année n'est plus écrite pour l'année simulée.
            self.assertEqual(utils.date_courte(datetime.date(2031, 5, 4)), "4 mai")
            self.assertEqual(utils.date_courte(datetime.date(2026, 5, 4)), "4 mai 2026")


class TestReglesDesModes(unittest.TestCase):
    def test_lire_date(self):
        self.assertEqual(modes_admin.lire_date("2026-10-15"), datetime.date(2026, 10, 15))
        self.assertEqual(modes_admin.lire_date("2000-01-01"), datetime.date(2000, 1, 1))
        self.assertEqual(modes_admin.lire_date("2099-12-31"), datetime.date(2099, 12, 31))
        for valeur in (None, "", "abc", "2026-02-31", "1999-12-31", "2100-01-01", "15/10/2026", " 2026-10-15",
                       "2026-10-15 ", "２０２６-10-15", "2026-1-5", 20261015, "2026-10-15T00:00"):
            with self.subTest(valeur=valeur):
                self.assertIsNone(modes_admin.lire_date(valeur))

    def test_cible_autorisee(self):
        self.assertIsNone(modes_admin.cible_autorisee(INTER, ADMIN))
        self.assertIsNone(modes_admin.cible_autorisee(RH, ADMIN))
        self.assertEqual(modes_admin.cible_autorisee(None, ADMIN), "Compte introuvable.")
        self.assertEqual(modes_admin.cible_autorisee(ADMIN2, ADMIN), "Impossible de voir Kairos comme un autre Admin.")
        self.assertEqual(modes_admin.cible_autorisee(ADMIN, ADMIN), "Impossible de voir Kairos comme un autre Admin.")
        self.assertEqual(modes_admin.cible_autorisee(INACTIF, ADMIN), "Le compte de Ancien Compte est désactivé.")
        self.assertEqual(modes_admin.libelle_compte(INTER), "Rim Inter (Intervenant)")

    def test_kairos_mode_test_seulement_si_true(self):
        import app.config as config_module
        try:
            for valeur, attendu in (("true", True), ("TRUE", True), (" true ", True), ("false", False),
                                    ("", False), ("1", False), ("oui", False), ("yes", False)):
                with self.subTest(valeur=valeur), patch.dict(os.environ, {"KAIROS_MODE_TEST": valeur}):
                    self.assertIs(importlib.reload(config_module).Config.MODE_TEST, attendu)
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("KAIROS_MODE_TEST", None)
                self.assertIs(importlib.reload(config_module).Config.MODE_TEST, False)
        finally:
            importlib.reload(config_module)


class _CurseurEspion:
    def __init__(self, erreur=None):
        self.ordres, self.erreur = [], erreur

    def execute(self, sql, params=None):
        self.ordres.append((sql, params))
        if self.erreur is not None and sql.startswith("INSERT"):
            raise self.erreur

    def close(self):
        pass


class TestTransactions(unittest.TestCase):
    """app/db.py : READ ONLY en « Voir comme », Admin réel en « Agir
    comme », date simulée — et rien de tout ça hors requête."""

    def setUp(self):
        self.app = create_app(smoke.TestConfig)

    @contextlib.contextmanager
    def pool(self, curseur):
        conn = MagicMock()
        conn.cursor.return_value = curseur
        conn.closed = 0
        faux = MagicMock()
        faux.getconn.return_value = conn
        with patch.object(db, "_pool", faux):
            yield conn

    def test_hors_requete_rien_n_est_pose(self):
        cur = _CurseurEspion()
        with self.pool(cur):
            with db.get_cursor(user_id=7) as c:
                c.execute("SELECT 1")
        self.assertEqual([o[0] for o in cur.ordres], ["SET LOCAL app.current_user_id = %s", "SELECT 1"])

    def test_voir_comme_transaction_en_lecture_seule_d_abord(self):
        cur = _CurseurEspion()
        with self.app.test_request_context("/"), self.pool(cur):
            g.lecture_seule, g.admin_reel_agit, g.date_simulee = True, None, None
            with db.get_cursor(user_id=3) as c:
                c.execute("SELECT 1")
        self.assertEqual(cur.ordres[0][0], "SET TRANSACTION READ ONLY")
        self.assertEqual(cur.ordres[1], ("SET LOCAL app.current_user_id = %s", ("3",)))

    def test_agir_comme_et_date_simulee(self):
        cur = _CurseurEspion()
        with self.app.test_request_context("/"), self.pool(cur):
            g.lecture_seule, g.admin_reel_agit, g.date_simulee = False, 1, datetime.date(2026, 10, 15)
            with db.get_cursor(user_id=3) as c:
                c.execute("SELECT 1")
        # Lot 13 : l'instant simulé (date simulée à l'heure réelle de Tunis).
        self.assertEqual(cur.ordres[:2], [("SET LOCAL app.current_user_id = %s", ("3",)),
                                          ("SET LOCAL app.admin_reel_id = %s", ("1",))])
        self.assertEqual(cur.ordres[2][0], "SET LOCAL kairos.instant_simule = %s")
        self.assertRegex(cur.ordres[2][1][0], r"^2026-10-15T[0-9]{2}:[0-9]{2}:[0-9]{2}\+01:00$")
        self.assertNotIn("SET TRANSACTION READ ONLY", [o[0] for o in cur.ordres])

    def test_ecriture_refusee_par_la_base_devient_lecture_seule(self):
        erreur = Exception("cannot execute INSERT in a read-only transaction")
        erreur.pgcode = "25006"
        cur = _CurseurEspion(erreur)
        with self.app.test_request_context("/"), self.pool(cur) as conn:
            g.lecture_seule = True
            with self.assertRaises(db.LectureSeule):
                with db.get_cursor() as c:
                    c.execute("INSERT INTO x VALUES (1)")
            conn.rollback.assert_called()
        # Hors « Voir comme », la même erreur remonte telle quelle.
        with self.app.test_request_context("/"), self.pool(_CurseurEspion(erreur)):
            with self.assertRaises(Exception) as ctx:
                with db.get_cursor() as c:
                    c.execute("INSERT INTO x VALUES (1)")
            self.assertIs(ctx.exception, erreur)


class TestEmails(unittest.TestCase):
    def setUp(self):
        self.app = create_app(smoke.TestConfig)
        self.app.config.update(SMTP_HOST="smtp.test", MAIL_DESTINATAIRES_AUTORISES="ok@midgard.tn")

    def test_voir_comme_n_envoie_rien(self):
        with self.app.test_request_context("/"), patch("smtplib.SMTP") as smtp:
            g.mode_admin = "voir"
            self.assertFalse(mailer.envoyer("ok@midgard.tn", "s", "c"))
            mailer.envoyer_en_arriere_plan("ok@midgard.tn", "s", "c")
            smtp.assert_not_called()

    def test_agir_comme_reste_soumis_a_la_liste_autorisee(self):
        with self.app.test_request_context("/"), patch("smtplib.SMTP") as smtp:
            g.mode_admin = "agir"
            self.assertFalse(mailer.envoyer("autre@x.tn", "s", "c"))
            smtp.assert_not_called()
            self.assertTrue(mailer.envoyer("ok@midgard.tn", "s", "c"))
            smtp.assert_called_once()


# ---------------------------------------------------------------------
# Routes et gabarits
# ---------------------------------------------------------------------
class TestVoirCommeRoutes(_Base):
    MODE = {"admin": 1, "cible": 3, "mode": "voir"}

    def test_entrer_journalise_et_redirige(self):
        self.session()
        resp, m = self.requete("post", "/admin/voir-comme", data={"utilisateur_id": "3"},
                               espions=[("app.repositories.audit.journaliser_mode", None)])
        self.assertEqual((resp.status_code, resp.headers["Location"]), (302, "/accueil"))
        appel = m["app.repositories.audit.journaliser_mode"].call_args.args
        self.assertEqual(appel[:4], ("mode_voir_comme", "ENTREE", 1, 3))
        self.assertEqual(appel[4]["compte_vu"], "Rim Inter")
        with self.client.session_transaction() as s:
            self.assertEqual(s["mode_admin"], self.MODE)

    def test_bandeau_menus_et_titre_de_l_onglet(self):
        self.session(mode_admin=self.MODE)
        resp, _ = self.requete("get", "/accueil")
        page = self.texte(resp)
        self.assertIn('<div class="bandeau-admin bandeau-admin-voir" role="region" aria-label="Mode de l’Administrateur" id="bandeau-admin">', page)
        self.assertIn("Vous voyez Kairos comme Rim Inter (Intervenant) — Revenir à mon compte", self.visible(resp))
        self.assertIn('<header class="topbar topbar-mode-voir">', page)
        self.assertIn("<title>[Vu comme Rim Inter] Accueil — Kairos</title>", page)
        self.assertIn('<input type="hidden" name="next" value="/accueil">', page)
        self.assertNotIn('aria-label="Journal d\'audit"', page)
        self.assertNotIn("Date simulée", page)  # pas de mode test

    def test_ecriture_refusee_html_et_json(self):
        self.session(mode_admin=self.MODE)
        resp, m = self.requete("post", "/notifications/marquer-toutes-lues",
                               espions=[("app.repositories.notifications.marquer_toutes_lues", None)])
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Lecture seule", self.texte(resp))
        self.assertIn("Vous voyez Kairos comme Rim Inter\u00a0: lecture seule, rien n’a été modifié.", self.texte(resp))
        m["app.repositories.notifications.marquer_toutes_lues"].assert_not_called()
        for chemin, kw in (("/dailylog/api/jour/2026-10-08", {"json": {"version": 0, "lignes": []}}),
                           ("/posts/9/reagir", {"headers": {"X-Requested-With": "XMLHttpRequest"}}),
                           ("/posts", {"headers": {"Accept": "application/json"}})):
            with self.subTest(chemin=chemin):
                resp, _ = self.requete("put" if "dailylog" in chemin else "post", chemin, **kw)
                self.assertEqual(resp.status_code, 403)
                self.assertEqual(resp.get_json()["erreur"], "lecture_seule")

    def test_aucun_rappel_ni_ecriture_au_chargement(self):
        self.session(mode_admin=self.MODE)
        resp, m = self.requete("get", "/accueil", espions=[
            ("app.repositories.notifications.creer_rappel_dailylog", []),
            ("app.repositories.notifications.marquer_rappels_dailylog_lus", None)])
        self.assertEqual(resp.status_code, 200)
        m["app.repositories.notifications.creer_rappel_dailylog"].assert_not_called()
        m["app.repositories.notifications.marquer_rappels_dailylog_lus"].assert_not_called()
        with self.client.session_transaction() as s:
            self.assertNotIn("rappel_le", s)

    def test_revenir_et_deconnexion_restent_permis(self):
        self.session(mode_admin=self.MODE)
        resp, m = self.requete("post", "/admin/revenir", data={"next": "/projets"},
                               espions=[("app.repositories.audit.journaliser_mode", None)])
        self.assertEqual((resp.status_code, resp.headers["Location"]), (302, "/projets"))
        self.assertEqual(m["app.repositories.audit.journaliser_mode"].call_args.args[:4],
                         ("mode_voir_comme", "SORTIE", 1, 3))
        self.session(mode_admin=self.MODE)
        resp, m = self.requete("post", "/deconnexion", espions=[
            ("app.repositories.audit.journaliser_mode", None),
            ("app.repositories.utilisateurs.revoquer_sessions", None)])
        self.assertEqual(resp.status_code, 302)
        m["app.repositories.utilisateurs.revoquer_sessions"].assert_called_once_with(1)
        self.assertEqual(m["app.repositories.audit.journaliser_mode"].call_args.args[1], "SORTIE")
        with self.client.session_transaction() as s:
            self.assertEqual(dict(s), {})

    def test_cible_refusee_retour_automatique(self):
        for cible in (5, 2, 99):
            with self.subTest(cible=cible):
                self.session(mode_admin={**self.MODE, "cible": cible})
                resp, m = self.requete("get", "/accueil",
                                       espions=[("app.repositories.audit.journaliser_mode", None)])
                self.assertEqual(resp.status_code, 200)
                self.assertNotIn("bandeau-admin", self.texte(resp))
                self.assertIn("Retour à votre compte.", self.texte(resp))
                self.assertEqual(m["app.repositories.audit.journaliser_mode"].call_args.args[1], "SORTIE")

    def test_non_admin_jamais(self):
        comptes = {**COMPTES, 1: {**ADMIN, "role": "chef_de_projet"}}
        self.session(mode_admin=self.MODE, date_simulee={"admin": 1, "date": "2030-01-01"})
        resp, _ = self.requete("get", "/accueil", comptes=comptes)
        self.assertNotIn("bandeau-admin", self.texte(resp))
        with self.client.session_transaction() as s:
            self.assertNotIn("mode_admin", s)
            self.assertNotIn("date_simulee", s)
        resp, _ = self.requete("post", "/admin/voir-comme", comptes=comptes, data={"utilisateur_id": "3"})
        self.assertEqual(resp.status_code, 403)
        resp, _ = self.requete("get", "/admin/voir-comme", comptes=comptes)
        self.assertEqual(resp.status_code, 403)

    def test_pas_d_agir_ni_de_date_sans_mode_test(self):
        self.session()
        for chemin in ("/admin/agir-comme", "/admin/date-simulee", "/admin/date-simulee/effacer"):
            with self.subTest(chemin=chemin):
                resp, _ = self.requete("post", chemin, data={"utilisateur_id": "3", "date": "2030-01-01"})
                self.assertEqual(resp.status_code, 404)
        resp, _ = self.requete("get", "/admin/voir-comme", espions=[
            ("app.repositories.utilisateurs.list_cibles_voir_comme", [INTER, RH])])
        page = self.texte(resp)
        self.assertNotIn("Agir comme", page)
        self.assertNotIn("bandeau-admin", page)
        self.assertIn('data-search-combobox data-search-riche', page)
        self.assertIn('<option value="3"', page)
        self.assertIn('<option value="4"', page)
        self.assertNotIn("mode_test.", " ".join(r.endpoint for r in self.app.url_map.iter_rules()))


class TestModeTestRoutes(_Base):
    config = ConfigModeTest

    def test_routes_enregistrees_et_bandeau_admin(self):
        self.assertIn("mode_test.agir_comme", {r.endpoint for r in self.app.url_map.iter_rules()})
        self.session()
        resp, _ = self.requete("get", "/accueil")
        page = self.texte(resp)
        self.assertIn('class="bandeau-admin bandeau-admin-test" role="region"', page)
        self.assertIn('action="/admin/date-simulee"', page)
        self.assertIn("Voir ou agir comme…", page)

    def test_agir_comme_bandeau_rouge_et_mot_de_passe_refuse(self):
        self.session(mode_admin={"admin": 1, "cible": 3, "mode": "agir"})
        resp, _ = self.requete("get", "/accueil")
        self.assertIn("Vous agissez comme Rim Inter (Intervenant) (mode test) — Revenir à mon compte", self.visible(resp))
        self.assertIn('<header class="topbar topbar-mode-agir">', self.texte(resp))
        resp, m = self.requete("post", "/utilisateurs/moi/mot-de-passe", data={"mot_de_passe_actuel": "x"},
                               espions=[("app.repositories.utilisateurs.set_password", None)])
        self.assertEqual(resp.status_code, 403)
        m["app.repositories.utilisateurs.set_password"].assert_not_called()

    def test_date_simulee_posee_puis_effacee(self):
        self.session()
        resp, m = self.requete("post", "/admin/date-simulee", data={"date": "2026-10-15", "next": "/deadlines"},
                               espions=[("app.repositories.audit.journaliser_mode", None)])
        self.assertEqual((resp.status_code, resp.headers["Location"]), (302, "/deadlines"))
        self.assertEqual(m["app.repositories.audit.journaliser_mode"].call_args.args[:3], ("date_simulee", "ENTREE", 1))
        resp, _ = self.requete("get", "/accueil")
        self.assertIn("Date simulée : jeudi 15 octobre 2026", self.visible(resp))
        self.assertIn("— Revenir à aujourd’hui", self.visible(resp))
        self.assertIn('class="bandeau-admin bandeau-admin-date"', self.texte(resp))
        self.assertIn('value="2026-10-15"', self.texte(resp))
        resp, _ = self.requete("post", "/admin/date-simulee/effacer", data={"next": "//evil.tld"},
                               espions=[("app.repositories.audit.journaliser_mode", None)])
        self.assertEqual(resp.headers["Location"], "/accueil")
        with self.client.session_transaction() as s:
            self.assertNotIn("date_simulee", s)

    def test_date_simulee_sert_aux_echeances(self):
        self.session(date_simulee={"admin": 1, "date": "2026-10-15"})
        taches = [{**smoke.DEADLINES[0], "id": 7, "date_echeance": datetime.date(2026, 10, 12)}]
        resp, _ = self.requete("get", "/deadlines", espions=[("app.repositories.taches.list_deadlines", taches)])
        page = self.texte(resp)
        self.assertIn("en retard de 3 j", page)
        self.assertIn('href="/projets/1?tache=7"', page)
        self.assertIn("ouvrir la tâche", page)


class TestDeadlinesEtLiens(_Base):
    def test_mes_taches_ouvrent_la_fenetre_de_la_tache(self):
        self.session()
        resp, _ = self.requete("get", "/accueil")
        self.assertIn('href="/projets/1?tache=1"', self.texte(resp))

    def test_bascule_admin_et_filtres(self):
        self.session()
        tous = [{**smoke.DEADLINES[0], "id": 8, "chef_id": 2, "chef_prenom": "Ali", "chef_nom": "Chef"}]
        resp, m = self.requete("get", "/deadlines?vue=tous&chef=2&equipe=URBS", espions=[
            ("app.repositories.taches.list_deadlines_tous", tous),
            ("app.repositories.projets.list_chefs_de_projet", smoke.CHEFS_DE_PROJET)])
        page = self.texte(resp)
        self.assertIn('aria-current="page">Tous les projets', page)
        self.assertIn("· Ali Chef", page)
        self.assertIn('href="/projets/1?tache=8"', page)
        self.assertIn("Tâches en cours sans échéance", page)
        appels = m["app.repositories.taches.list_deadlines_tous"].call_args_list
        self.assertEqual(appels[0].args[:2], (2, "URBS"))
        self.assertTrue(appels[1].kwargs["sans_echeance"])
        resp, m = self.requete("get", "/deadlines?vue=tous&chef=²&equipe=<x>", espions=[
            ("app.repositories.taches.list_deadlines_tous", []),
            ("app.repositories.projets.list_chefs_de_projet", [])])
        self.assertEqual(m["app.repositories.taches.list_deadlines_tous"].call_args_list[0].args[:2], (None, None))

    def test_autres_roles_inchanges(self):
        comptes = {**COMPTES, 1: {**ADMIN, "role": "intervenant"}}
        self.session()
        resp, m = self.requete("get", "/deadlines?vue=tous", comptes=comptes, espions=[
            ("app.repositories.taches.list_deadlines_tous", [])])
        page = self.texte(resp)
        m["app.repositories.taches.list_deadlines_tous"].assert_not_called()
        self.assertNotIn("bascule-vue", page)
        self.assertNotIn("Voir Kairos comme", page)



class TestDeploiement(unittest.TestCase):
    def lire(self, nom):
        from pathlib import Path
        return (Path(__file__).resolve().parent.parent / nom).read_text(encoding="utf-8")

    def test_kairos_mode_test_transmis_coupe_par_defaut(self):
        self.assertIn("      KAIROS_MODE_TEST: ${KAIROS_MODE_TEST:-false}\n", self.lire("docker-compose.yml"))
        exemple = self.lire(".env.example")
        self.assertIn("\nKAIROS_MODE_TEST=false\n", exemple)
        self.assertIn("AVANT LA MISE EN SERVICE RÉELLE", exemple)
        readme = self.lire("README.md")
        self.assertIn("### Mode test (« Agir comme », date simulée)", readme)
        self.assertIn("**À couper avant la\nmise en service réelle.**", readme)

    def test_migration_0018_declaree_et_recopiee_dans_schema(self):
        mig = self.lire("migrations/0018_modes_admin_et_date_simulee.sql")
        schema = self.lire("schema.sql")
        self.assertIn("('0018_modes_admin_et_date_simulee')", schema)
        for fonction in ("fn_app_admin_reel_id", "fn_audit_log", "fn_date_simulee", "fn_aujourdhui", "fn_dailylog_garde"):
            with self.subTest(fonction=fonction):
                debut = f"CREATE OR REPLACE FUNCTION {fonction}("
                # Dernière version de la fonction (fn_aujourdhui et
                # fn_dailylog_garde : migration 0019, lot 13).
                from pathlib import Path
                dossier = Path(__file__).resolve().parent.parent / "migrations"
                derniere = [m.read_text(encoding="utf-8") for m in sorted(dossier.glob("*.sql"))
                            if debut in m.read_text(encoding="utf-8")][-1]
                corps_mig = derniere[derniere.index(debut):derniere.index("$$ LANGUAGE", derniere.index(debut))]
                corps_schema = schema[schema.index(debut):schema.index("$$ LANGUAGE", schema.index(debut))]
                self.assertEqual(corps_mig, corps_schema)
        # Rejouable : rien qui échoue à la seconde passe.
        self.assertIn("ADD COLUMN IF NOT EXISTS admin_reel_id", mig)
        self.assertIn("DROP CONSTRAINT IF EXISTS audit_log_action_valide", mig)
        self.assertIn("CREATE INDEX IF NOT EXISTS idx_audit_admin_reel", mig)
        self.assertNotIn("CREATE TABLE ", mig)
        # Migrations 0013 à 0017 jamais modifiées (déjà publiées).
        self.assertIn("v_aujourdhui := (now() AT TIME ZONE COALESCE(v_fuseau, 'Africa/Tunis'))::DATE;",
                      self.lire("migrations/0014_dailylog_v9.sql"))


if __name__ == "__main__":
    unittest.main()

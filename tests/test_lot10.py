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
    ACTIF = "app.repositories.utilisateurs.toggle_actif"

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
        _, m = self._requete("post", "/utilisateurs/10", {**FICHE, "role": "chef_de_projet"},
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
        self.assertEqual(inspect.getsource(projets.list_projets).count("'verifie', 'arret'"), 3)


if __name__ == "__main__":
    unittest.main()

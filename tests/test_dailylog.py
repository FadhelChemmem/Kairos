"""Daily log v9 (lot 10) — tests unitaires (psycopg2 simulé, repositories
remplacés par des mocks), un par règle de la spécification d'intégration
(/tmp/lot10-audit/dailylog-spec.md §7.2) et des décisions du gérant :

- entrées strictes (dates, mois, corps JSON, ids forgés « ² ») → 400, jamais 500 ;
- l'API répond TOUJOURS en JSON (401, 403, 404, 405, CSRF) ;
- chaque code de refus 422, la ligne inchangée qui échappe aux règles,
  « Vider la journée » avec confirmation, 409 ;
- matrice des droits (titulaire J-14 / J-15, chef de ses projets, Admin) au
  fuseau de Tunis et de Cayenne ;
- rappel (lundi → vendredi, date d'arrivée), jours manqués, objectif,
  profils, carte d'accueil, fuseau sur la fiche, reprise Chronos.

Le SQL (triggers 0014, verrou, diff, audit) est vérifié sur un vrai
PostgreSQL : tests/sql/dailylog_v9.sql et tests_integration/test_dailylog.py.
"""
import datetime
import pathlib
import unittest
from unittest.mock import patch

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
except ImportError:  # python -m unittest tests.test_dailylog
    from tests import test_smoke as smoke

from app.repositories import dailylog as dl  # noqa: E402
from app.routes import dailylog as routes  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parent.parent
INTERVENANT = {**smoke.USER, "id": 1, "role": "intervenant"}
CHEF = {**smoke.USER, "id": 1, "role": "chef_de_projet"}
ADMIN = {**smoke.USER, "id": 1, "role": "admin"}
EMPLOYE = {**smoke.AUTRE_UTILISATEUR, "id": 2, "role": "intervenant", "fuseau": "Africa/Tunis"}


def projet(pid=1, **champs):
    base = {"id": pid, "code": f"P{pid}", "nom": f"Projet {pid}", "etat": "en_cours", "date_debut": None,
            "date_cloture": None, "visible": True, "visible_acteur": True, "gere": False}
    base.update(champs)
    return base


class _BaseDailyLog(smoke.SmokeBase):
    def setUp(self):
        super().setUp()
        self.aujourdhui = dl.aujourdhui_pour(smoke.USER)
        self.preparation = None

    def appel(self, methode, url, json=None, user=None, existantes=None, absent_actuel=False,
              version_actuelle=0, espions=(), brut=None, **overrides):
        """Requête connectée ; `enregistrer_jour` est remplacé par un faux qui
        joue VRAIMENT la validation de la route (`preparer`) contre l'état
        « verrouillé » donné (`existantes`, `absent_actuel`)."""
        self._login()
        if user is not None:
            overrides["app.auth.get_user_by_id"] = user
        patchers = self._patched(**overrides)
        test = self

        def faux_enregistrer(user_id, date, version, acteur_id, preparer):
            if version != version_actuelle:
                raise dl.VersionPerimee(version_actuelle)
            test.preparation = preparer(dict(existantes or {}), absent_actuel)
            change = test.preparation != (absent_actuel, dict(existantes or {}))
            return {"version": version_actuelle + (1 if change else 0), "change": change}

        patchers.append(patch("app.repositories.dailylog.enregistrer_jour", side_effect=faux_enregistrer))
        self.mocks = {}
        for cible, valeur in espions:
            patchers.append(patch(cible, return_value=valeur))
        for p in patchers:
            m = p.start()
            self.mocks[getattr(p, "attribute", None)] = m
        try:
            kwargs = {"json": json} if json is not None else {}
            if brut is not None:
                kwargs = {"data": brut, "content_type": "application/json"}
            return getattr(self.client, methode)(url, **kwargs)
        finally:
            for p in reversed(patchers):
                p.stop()

    def put(self, lignes, date=None, version=0, projets=None, taches=None, **kw):
        date = date or self.aujourdhui
        corps = {"version": version, "lignes": lignes}
        corps.update(kw.pop("corps", {}))
        return self.appel("put", f"/dailylog/api/jour/{date.isoformat()}{kw.pop('qs', '')}", json=corps,
                          **{"app.repositories.dailylog.projets_info": projets if projets is not None else {1: projet(1)},
                             "app.repositories.dailylog.taches_projet": taches or {}},
                          **kw)

    def codes(self, resp):
        self.assertEqual(resp.status_code, 422, resp.data[:500])
        return [e["code"] for e in resp.get_json()["erreurs"]]


class TestEntreesStrictes(_BaseDailyLog):
    def test_dates_invalides_400_jamais_500(self):
        for brute in ("2026-1-5", "0001-01-01", "1989-12-31", "²", "2026-02-30", "٢٠٢٦-١٠-٠١", "aujourdhui", "2026-10-07x"):
            with self.subTest(date=brute):
                resp = self.appel("get", f"/dailylog/api/jour/{brute}")
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.get_json()["erreur"], "date_invalide")

    def test_date_future_422_au_fuseau_du_proprietaire(self):
        demain = self.aujourdhui + datetime.timedelta(days=1)
        resp = self.appel("get", f"/dailylog/api/jour/{demain}")
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.get_json()["erreur"], "date_future")
        resp = self.put([{"projet_id": 1, "minutes": 60}], date=demain)
        self.assertEqual(resp.get_json()["erreur"], "date_future")

    def test_mois_invalides(self):
        for brut in ("2026-13", "2026-00", "1989-12", "2026-1", "²²²²-01", "2101-01"):
            with self.subTest(mois=brut):
                resp = self.appel("get", f"/dailylog/api/mois/{brut}")
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.get_json()["erreur"], "mois_invalide")

    def test_corps_forges_400(self):
        mauvais = [
            None, [], "x", {"lignes": []}, {"version": True, "lignes": []}, {"version": 1.0, "lignes": []},
            {"version": "0", "lignes": []}, {"version": -1, "lignes": []}, {"version": 2 ** 40, "lignes": []},
            {"version": 0, "lignes": {}}, {"version": 0, "lignes": [1]},
            {"version": 0, "lignes": [{"projet_id": 1, "minutes": 60}] * 41},
            {"version": 0, "lignes": [{"projet_id": 1, "minutes": 60.0}]},
            {"version": 0, "lignes": [{"projet_id": 1, "minutes": "60"}]},
            {"version": 0, "lignes": [{"projet_id": "1", "minutes": 60}]},
            {"version": 0, "lignes": [{"projet_id": 2 ** 63, "minutes": 60}]},
            {"version": 0, "lignes": [{"projet_id": 0, "minutes": 60}]},
            {"version": 0, "lignes": [{"projet_id": 1, "tache_id": "²", "minutes": 60}]},
            {"version": 0, "lignes": [{"projet_id": 1, "tache_id": True, "minutes": 60}]},
            {"version": 0, "lignes": [{"projet_id": 1}]},
            {"version": 0, "lignes": [], "vider": "oui"},
        ]
        for corps in mauvais:
            with self.subTest(corps=str(corps)[:60]):
                resp = self.appel("put", f"/dailylog/api/jour/{self.aujourdhui}", json=corps)
                self.assertEqual(resp.status_code, 400, resp.data[:300])
                self.assertEqual(resp.get_json()["erreur"], "json_invalide")
        for brut in ("pas du json", "{\"version\": NaN, \"lignes\": []}", "", "[]"):
            with self.subTest(brut=brut):
                resp = self.appel("put", f"/dailylog/api/jour/{self.aujourdhui}", brut=brut)
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.get_json()["erreur"], "json_invalide")

    def test_absence_forgee(self):
        url = f"/dailylog/api/jour/{self.aujourdhui}/absence"
        for corps in ({"version": 0}, {"version": 0, "absent": "true"}, {"version": 0, "absent": 1}):
            with self.subTest(corps=corps):
                self.assertEqual(self.appel("post", url, json=corps).status_code, 400)

    def test_utilisateur_forge(self):
        for brut in ("²", "-1", "abc", "1" * 19, "1e3"):
            with self.subTest(utilisateur=brut):
                resp = self.appel("get", f"/dailylog/api/jour/{self.aujourdhui}?utilisateur={brut}")
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(resp.get_json()["erreur"], "utilisateur_invalide")
        resp = self.appel("get", "/dailylog?utilisateur=²")
        self.assertEqual(resp.status_code, 404)

    def test_recherche_et_taches_forgees(self):
        resp = self.appel("get", "/dailylog/recherche-projets?q=" + "x" * 101)
        self.assertEqual(resp.status_code, 400)
        resp = self.appel("get", "/dailylog/recherche-projets?q=ab&date=²")
        self.assertEqual(resp.status_code, 400)
        for brut in ("", "²", "-3", "1" * 19):
            with self.subTest(projet=brut):
                self.assertEqual(self.appel("get", f"/dailylog/api/taches?projet={brut}").status_code, 400)


class TestApiToujoursEnJson(_BaseDailyLog):
    URLS = [("get", "/dailylog/api/jour/2026-10-01"), ("put", "/dailylog/api/jour/2026-10-01"),
            ("post", "/dailylog/api/jour/2026-10-01/absence"), ("get", "/dailylog/api/mois/2026-10"),
            ("put", "/dailylog/api/objectif"), ("get", "/dailylog/recherche-projets?q=ab"),
            ("get", "/dailylog/api/taches?projet=1")]

    def test_401_sans_session_jamais_302(self):
        for methode, url in self.URLS:
            with self.subTest(url=url, methode=methode):
                resp = getattr(self.client, methode)(url, json={})
                self.assertEqual(resp.status_code, 401)
                self.assertEqual(resp.get_json()["erreur"], "non_connecte")

    def test_403_rh_client_et_compte_inactif(self):
        for user in (smoke.RH, smoke.CLIENT, {**INTERVENANT, "actif": False}):
            for methode, url in self.URLS:
                with self.subTest(role=user["role"], url=url):
                    resp = self.appel(methode, url, json={"version": 0}, user=user)
                    self.assertEqual(resp.status_code, 403)
                    self.assertEqual(resp.get_json()["erreur"], "interdit")

    def test_intervenant_ne_corrige_pas_un_autre(self):
        resp = self.appel("get", f"/dailylog/api/jour/{self.aujourdhui}?utilisateur=2", user=INTERVENANT,
                          **{"app.repositories.utilisateurs.get_utilisateur": EMPLOYE})
        self.assertEqual(resp.status_code, 403)
        resp = self.appel("get", "/dailylog?utilisateur=2", user=INTERVENANT)
        self.assertEqual(resp.status_code, 403)

    def test_personne_inconnue_ou_sans_daily_log(self):
        for personne in (None, {**EMPLOYE, "role": "rh"}, {**EMPLOYE, "role": "client"}):
            with self.subTest(personne=personne and personne["role"]):
                resp = self.appel("get", f"/dailylog/api/jour/{self.aujourdhui}?utilisateur=2", user=CHEF,
                                  **{"app.repositories.utilisateurs.get_utilisateur": personne})
                self.assertEqual(resp.status_code, 404)
                self.assertEqual(resp.get_json()["erreur"], "utilisateur_introuvable")

    def test_404_et_405_en_json_sous_l_api(self):
        resp = self.appel("get", "/dailylog/api/inconnue")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["erreur"], "introuvable")
        resp = self.appel("delete", f"/dailylog/api/jour/{self.aujourdhui}")
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.get_json()["erreur"], "methode_interdite")
        # Ailleurs : pages d'erreur habituelles (HTML).
        resp = self.appel("get", "/page-inconnue")
        self.assertEqual(resp.status_code, 404)
        self.assertIsNone(resp.get_json(silent=True))

    def test_csrf_en_json_avec_la_protection_active(self):
        class ConfigCSRF(smoke.TestConfig):
            WTF_CSRF_ENABLED = True
        app = smoke.create_app(ConfigCSRF)
        client = app.test_client()
        with client.session_transaction() as s:
            s["user_id"] = 1
            s["pw_fingerprint"] = smoke.password_fingerprint(smoke.MOT_DE_PASSE_HASH_PAR_DEFAUT)
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            resp = client.put(f"/dailylog/api/jour/{self.aujourdhui}", json={"version": 0, "lignes": []})
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.get_json()["erreur"], "csrf")
            resp = client.put("/dailylog/api/objectif", json={"objectif_minutes": 480},
                              headers={"X-CSRFToken": "faux"})
            self.assertEqual(resp.get_json()["erreur"], "csrf")
            # Formulaire classique ailleurs : toujours la redirection habituelle.
            resp = client.post("/notifications/marquer-toutes-lues")
            self.assertEqual(resp.status_code, 302)
        finally:
            for p in reversed(patchers):
                p.stop()


class TestReglesDEcriture(_BaseDailyLog):
    def test_ligne_valide_enregistree_en_minutes(self):
        resp = self.put([{"projet_id": 1, "tache_id": None, "minutes": 270}])
        self.assertEqual(resp.status_code, 200, resp.data[:500])
        self.assertTrue(resp.get_json()["enregistre"])
        self.assertEqual(self.preparation, (False, {(1, 0): 270}))

    def test_un_code_par_regle(self):
        hier = self.aujourdhui - datetime.timedelta(days=1)
        cas = [
            ([{"projet_id": 1, "minutes": 0}], {}, "minutes_invalides"),
            ([{"projet_id": 1, "minutes": -30}], {}, "minutes_invalides"),
            ([{"projet_id": 1, "minutes": 630}], {}, "minutes_invalides"),
            ([{"projet_id": 1, "minutes": 135}], {}, "pas_30_min"),
            ([{"projet_id": 1, "minutes": 45}], {}, "pas_30_min"),
            ([{"projet_id": 1, "minutes": 360}, {"projet_id": 2, "minutes": 270}],
             {2: projet(2)}, "max_journee"),
            ([{"projet_id": 1, "minutes": 60}, {"projet_id": 1, "minutes": 30}], {}, "ligne_en_double"),
            ([{"projet_id": 9, "minutes": 60}], {}, "projet_invisible"),
            ([{"projet_id": 3, "minutes": 60}], {3: projet(3, visible=False)}, "projet_invisible"),
            ([{"projet_id": 4, "minutes": 60}], {4: projet(4, etat="termine", date_cloture=hier)}, "projet_clos"),
            ([{"projet_id": 4, "minutes": 60}], {4: projet(4, etat="abandonne", date_cloture=None)}, "projet_clos"),
            ([{"projet_id": 5, "minutes": 60}], {5: projet(5, date_debut=self.aujourdhui + datetime.timedelta(days=3))},
             "projet_pas_commence"),
            ([{"projet_id": 1, "tache_id": 7, "minutes": 60}], {}, "tache_hors_projet"),
        ]
        for lignes, autres, code in cas:
            with self.subTest(code=code, lignes=lignes):
                resp = self.put(lignes, projets={1: projet(1), **autres}, taches={7: 99})
                self.assertIn(code, self.codes(resp))

    def test_plusieurs_erreurs_renvoyees_ensemble(self):
        resp = self.put([{"projet_id": 1, "minutes": 135}, {"projet_id": 9, "minutes": 60},
                         {"projet_id": 1, "tache_id": 7, "minutes": 60}], taches={7: 99})
        self.assertEqual(set(self.codes(resp)), {"pas_30_min", "projet_invisible", "tache_hors_projet"})

    def test_projet_bloque_et_clos_jusqu_a_sa_cloture_incluse(self):
        aujourdhui = self.aujourdhui
        for p in (projet(1, etat="bloque"), projet(1, etat="termine", date_cloture=aujourdhui),
                  projet(1, etat="abandonne", date_cloture=aujourdhui + datetime.timedelta(days=5))):
            with self.subTest(etat=p["etat"]):
                resp = self.put([{"projet_id": 1, "minutes": 60}], projets={1: p})
                self.assertEqual(resp.status_code, 200, resp.data[:300])

    def test_ligne_inchangee_echappe_a_toutes_les_regles(self):
        """Données anciennes (v2 au quart d'heure, Chronos > 10 h, projet clos
        ou invisible depuis) : réenregistrables telles quelles."""
        existantes = {(1, 0): 135, (2, 0): 600}
        resp = self.put([{"projet_id": 1, "minutes": 135}, {"projet_id": 2, "minutes": 600}],
                        projets={1: projet(1, etat="termine", date_cloture=datetime.date(2020, 1, 1)),
                                 2: projet(2, visible=False)},
                        existantes=existantes)
        self.assertEqual(resp.status_code, 200, resp.data[:300])
        self.assertFalse(resp.get_json()["enregistre"])

    def test_ancienne_journee_de_12_h_peut_etre_reduite_pas_augmentee(self):
        existantes = {(1, 0): 420, (2, 0): 300}
        ok = self.put([{"projet_id": 1, "minutes": 390}, {"projet_id": 2, "minutes": 300}],
                      projets={1: projet(1), 2: projet(2)}, existantes=existantes)
        self.assertEqual(ok.status_code, 200, ok.data[:300])
        ko = self.put([{"projet_id": 1, "minutes": 450}, {"projet_id": 2, "minutes": 300}],
                      projets={1: projet(1), 2: projet(2)}, existantes=existantes)
        self.assertIn("max_journee", self.codes(ko))

    def test_vider_une_journee_exige_une_confirmation(self):
        existantes = {(1, 0): 240}
        self.assertIn("journee_vide", self.codes(self.put([], existantes=existantes)))
        resp = self.put([], existantes=existantes, corps={"vider": True})
        self.assertEqual(resp.status_code, 200, resp.data[:300])
        self.assertEqual(self.preparation, (False, {}))
        # Jour jamais rempli : rien à vider, pas d'erreur.
        self.assertEqual(self.put([]).status_code, 200)

    def test_ligne_existante_projet_clos_ou_invisible_reduite_pas_augmentee(self):
        """Revue 1 du lot 10 : une ligne ancienne d'un projet clos depuis ou
        plus visible par la personne se corrige à la BAISSE (elle pouvait
        déjà être supprimée) ; la hausse et l'ajout restent refusés."""
        vieux = self.aujourdhui - datetime.timedelta(days=40)
        projets = {1: projet(1, etat="termine", date_cloture=vieux - datetime.timedelta(days=10)),
                   2: projet(2, visible=False)}
        existantes = {(1, 0): 240, (2, 0): 160}

        def put(lignes, user=ADMIN):
            return self.put(lignes, date=vieux, user=user, projets=projets, existantes=existantes)

        ok = put([{"projet_id": 1, "minutes": 180}, {"projet_id": 2, "minutes": 150}])
        self.assertEqual(ok.status_code, 200, ok.data[:300])
        self.assertEqual(self.preparation, (False, {(1, 0): 180, (2, 0): 150}))
        self.assertIn("projet_clos", self.codes(put([{"projet_id": 1, "minutes": 270}, {"projet_id": 2, "minutes": 160}])))
        self.assertIn("projet_invisible", self.codes(put([{"projet_id": 1, "minutes": 240}, {"projet_id": 2, "minutes": 180}])))
        self.assertIn("projet_clos", self.codes(put([{"projet_id": 1, "tache_id": None, "minutes": 240},
                                                     {"projet_id": 2, "minutes": 160},
                                                     {"projet_id": 1, "tache_id": 7, "minutes": 30}])))
        # Une baisse reste au pas de 30 min, et réservée à qui peut modifier la ligne.
        self.assertIn("pas_30_min", self.codes(put([{"projet_id": 1, "minutes": 225}, {"projet_id": 2, "minutes": 160}])))
        self.assertIn("ligne_non_modifiable", self.codes(
            put([{"projet_id": 1, "minutes": 180}, {"projet_id": 2, "minutes": 160}], user=INTERVENANT)))

    def test_absence_exclusive_et_annulation_qui_rend_les_lignes(self):
        url = f"/dailylog/api/jour/{self.aujourdhui}/absence"
        projets = {"app.repositories.dailylog.projets_info": {1: projet(1)}}
        resp = self.appel("post", url, json={"version": 0, "absent": True, "lignes": [{"projet_id": 1, "minutes": 60}]},
                          **projets)
        self.assertIn("absent_avec_heures", self.codes(resp))
        resp = self.appel("post", url, json={"version": 1, "absent": True}, existantes={(1, 0): 240},
                          version_actuelle=1, **projets)
        self.assertEqual(resp.status_code, 200, resp.data[:300])
        self.assertEqual(self.preparation, (True, {}))
        resp = self.appel("post", url, json={"version": 2, "absent": False, "lignes": [{"projet_id": 1, "minutes": 240}]},
                          absent_actuel=True, version_actuelle=2, **projets)
        self.assertEqual(resp.status_code, 200, resp.data[:300])
        self.assertEqual(self.preparation, (False, {(1, 0): 240}))

    def test_version_perimee_409_avec_l_etat_du_serveur(self):
        resp = self.put([{"projet_id": 1, "minutes": 60}], version=0, version_actuelle=3)
        self.assertEqual(resp.status_code, 409)
        corps = resp.get_json()
        self.assertEqual(corps["erreur"], "version_perimee")
        self.assertIn("jour", corps)
        self.assertEqual(corps["jour"]["date"], self.aujourdhui.isoformat())

    def test_refus_de_la_base_traduits_sans_500(self):
        for pgcode, statut, code in (("23514", 422, "refus_base"), ("23503", 422, "refus_base"), ("42501", 403, "interdit")):
            with self.subTest(pgcode=pgcode):
                erreur = Exception("refus")
                erreur.pgcode = pgcode
                self._login()
                patchers = self._patched(**{"app.repositories.dailylog.projets_info": {1: projet(1)}})
                patchers.append(patch("app.repositories.dailylog.enregistrer_jour", side_effect=erreur))
                for p in patchers:
                    p.start()
                try:
                    resp = self.client.put(f"/dailylog/api/jour/{self.aujourdhui}",
                                           json={"version": 0, "lignes": [{"projet_id": 1, "minutes": 60}]})
                finally:
                    for p in reversed(patchers):
                        p.stop()
                self.assertEqual(resp.status_code, statut)
                self.assertEqual(resp.get_json()["erreur"], code)


class TestDroits(_BaseDailyLog):
    def _droits(self, acteur, proprio, jours_avant):
        aujourdhui = datetime.date(2026, 10, 7)
        return routes.droits_jour(acteur, proprio, aujourdhui - datetime.timedelta(days=jours_avant), aujourdhui)

    def test_matrice(self):
        moi = {"id": 1, "role": "intervenant"}
        chef = {"id": 1, "role": "chef_de_projet"}
        admin = {"id": 1, "role": "admin"}
        autre = {"id": 2, "role": "intervenant"}
        cas = [
            (moi, moi, 14, True, False, False), (moi, moi, 15, False, False, True),
            (chef, chef, 0, True, False, False), (chef, chef, 15, False, True, False),
            (chef, autre, 0, False, True, False), (chef, autre, 90, False, True, False),
            (admin, autre, 400, True, False, False), (admin, admin, 400, True, False, False),
        ]
        for acteur, proprio, jours, libre, ses_projets, lecture in cas:
            with self.subTest(acteur=acteur["role"], soi=acteur is proprio, jours=jours):
                d = self._droits(acteur, proprio, jours)
                self.assertEqual(d["saisie_libre"], libre)
                self.assertEqual(d["absence"], libre)
                self.assertEqual(d["lignes_de_ses_projets"], ses_projets)
                self.assertEqual(d["lecture_seule"], lecture)
                self.assertEqual(d["mode"], "saisie" if acteur is proprio else "correction")

    def test_fenetre_au_fuseau_de_la_personne(self):
        """À 1 h 30 UTC le 8 octobre, Tunis est le 8 et la Guyane encore le 7 :
        J-14 n'est pas le même jour."""
        maintenant = datetime.datetime(2026, 10, 8, 1, 30, tzinfo=datetime.timezone.utc)
        tunis = {"id": 1, "role": "intervenant", "fuseau": "Africa/Tunis"}
        guyane = {"id": 1, "role": "intervenant", "fuseau": "America/Cayenne"}
        a_tunis, a_cayenne = dl.aujourdhui_pour(tunis, maintenant), dl.aujourdhui_pour(guyane, maintenant)
        self.assertEqual((a_tunis, a_cayenne), (datetime.date(2026, 10, 8), datetime.date(2026, 10, 7)))
        j15_tunis = datetime.date(2026, 9, 23)  # J-15 à Tunis, J-14 en Guyane
        self.assertFalse(routes.droits_jour(tunis, tunis, j15_tunis, a_tunis)["saisie_libre"])
        self.assertTrue(routes.droits_jour(guyane, guyane, j15_tunis, a_cayenne)["saisie_libre"])
        self.assertFalse(routes.droits_jour(guyane, guyane, j15_tunis - datetime.timedelta(days=1), a_cayenne)["saisie_libre"])
        self.assertTrue(routes.droits_jour(tunis, tunis, j15_tunis + datetime.timedelta(days=1), a_tunis)["saisie_libre"])

    def test_aujourdhui_pour(self):
        self.assertEqual(dl.aujourdhui_pour({"fuseau": "Africa/Tunis"}, datetime.datetime(2026, 10, 7, 23, 30)),
                         datetime.date(2026, 10, 8))
        self.assertEqual(dl.aujourdhui_pour({"fuseau": "America/Cayenne"}, datetime.datetime(2026, 10, 8, 1, 30)),
                         datetime.date(2026, 10, 7))
        # Fuseau absent ou inconnu : Tunis.
        self.assertEqual(dl.aujourdhui_pour({}, datetime.datetime(2026, 10, 7, 23, 30)), datetime.date(2026, 10, 8))
        self.assertEqual(dl.aujourdhui_pour({"fuseau": "Europe/Paris"}, datetime.datetime(2026, 10, 7, 23, 30)),
                         datetime.date(2026, 10, 8))

    def test_titulaire_au_dela_de_14_jours_ne_modifie_rien(self):
        vieux = self.aujourdhui - datetime.timedelta(days=15)
        resp = self.put([{"projet_id": 1, "minutes": 60}], date=vieux, user=INTERVENANT)
        self.assertIn("ligne_non_modifiable", self.codes(resp))
        resp = self.appel("post", f"/dailylog/api/jour/{vieux}/absence", json={"version": 0, "absent": True},
                          user=INTERVENANT)
        self.assertIn("absence_non_autorisee", self.codes(resp))
        dans_la_fenetre = self.aujourdhui - datetime.timedelta(days=14)
        self.assertEqual(self.put([{"projet_id": 1, "minutes": 60}], date=dans_la_fenetre, user=INTERVENANT).status_code, 200)

    def test_chef_corrige_les_lignes_de_ses_projets_seulement(self):
        vieux = self.aujourdhui - datetime.timedelta(days=40)
        projets = {1: projet(1, gere=True), 2: projet(2, gere=False)}
        qs = "?utilisateur=2"
        emp = {"app.repositories.utilisateurs.get_utilisateur": EMPLOYE}
        # sa ligne : OK, et la ligne d'un autre chef (absente de la requête) est GARDÉE
        resp = self.put([{"projet_id": 1, "minutes": 120}], date=vieux, user=CHEF, projets=projets, qs=qs,
                        existantes={(1, 0): 60, (2, 0): 180}, **emp)
        self.assertEqual(resp.status_code, 200, resp.data[:300])
        self.assertEqual(self.preparation, (False, {(1, 0): 120, (2, 0): 180}))
        # modifier la ligne d'un autre chef : refusé
        resp = self.put([{"projet_id": 1, "minutes": 60}, {"projet_id": 2, "minutes": 210}], date=vieux, user=CHEF,
                        projets=projets, qs=qs, existantes={(1, 0): 60, (2, 0): 180}, **emp)
        self.assertIn("ligne_non_modifiable", self.codes(resp))
        # ajouter une ligne sur un projet qu'il ne gère pas : refusé
        resp = self.put([{"projet_id": 2, "minutes": 60}], date=vieux, user=CHEF, projets=projets, qs=qs, **emp)
        self.assertIn("ligne_non_modifiable", self.codes(resp))
        # l'absence d'un autre : jamais pour un chef
        resp = self.appel("post", f"/dailylog/api/jour/{self.aujourdhui}/absence{qs}",
                          json={"version": 0, "absent": True}, user=CHEF, **emp)
        self.assertIn("absence_non_autorisee", self.codes(resp))
        # la 10 h compte les lignes gardées
        resp = self.put([{"projet_id": 1, "minutes": 450}], date=vieux, user=CHEF, projets=projets, qs=qs,
                        existantes={(2, 0): 180}, **emp)
        self.assertIn("max_journee", self.codes(resp))

    def test_admin_corrige_tout_absence_comprise(self):
        vieux = self.aujourdhui - datetime.timedelta(days=200)
        emp = {"app.repositories.utilisateurs.get_utilisateur": EMPLOYE}
        resp = self.put([{"projet_id": 2, "minutes": 60}], date=vieux, user=ADMIN, qs="?utilisateur=2",
                        projets={2: projet(2)}, existantes={(1, 0): 120}, **emp)
        self.assertEqual(resp.status_code, 200, resp.data[:300])
        self.assertEqual(self.preparation, (False, {(2, 0): 60}))
        resp = self.appel("post", f"/dailylog/api/jour/{vieux}/absence?utilisateur=2", json={"version": 0, "absent": True},
                          user=ADMIN, existantes={(1, 0): 120}, **{**emp, "app.repositories.dailylog.projets_info": {1: projet(1)}})
        self.assertEqual(resp.status_code, 200, resp.data[:300])

    def test_correction_previent_la_personne_une_fois(self):
        vieux = self.aujourdhui - datetime.timedelta(days=30)
        emp = {"app.repositories.utilisateurs.get_utilisateur": EMPLOYE}
        self.put([{"projet_id": 1, "minutes": 60}], date=vieux, user=ADMIN, qs="?utilisateur=2",
                 espions=[("app.repositories.notifications.creer", 1)], **emp)
        creer = self.mocks["creer"]
        creer.assert_called_once()
        self.assertEqual(creer.call_args.args[0], 2)
        self.assertIn(f"Daily log du {vieux:%d/%m/%Y} corrigé par", creer.call_args.args[2])
        self.put([{"projet_id": 1, "minutes": 60}], date=vieux, user=ADMIN, qs="?utilisateur=2",
                 espions=[("app.repositories.notifications.creer", 1)],
                 **{**emp, "app.repositories.notifications.a_deja_la_notification": True})
        self.mocks["creer"].assert_not_called()
        # Saisie pour soi-même : pas de notification.
        self.put([{"projet_id": 1, "minutes": 60}], espions=[("app.repositories.notifications.creer", 1)])
        self.mocks["creer"].assert_not_called()

    def test_ligne_masquee_pour_un_chef_d_une_autre_equipe(self):
        jour = {**smoke.DAILYLOG_JOUR_VIDE, "version": 2, "lignes": [
            {"projet_id": 1, "tache_id": None, "code": "26099X", "nom": "Tour Meridian", "tache_titre": None,
             "minutes": 240, "hors_grille": False},
            {"projet_id": 9, "tache_id": None, "code": "SECRET", "nom": "Projet secret", "tache_titre": None,
             "minutes": 180, "hors_grille": False}]}
        resp = self.appel("get", f"/dailylog/api/jour/{self.aujourdhui}?utilisateur=2", user=CHEF,
                          **{"app.repositories.utilisateurs.get_utilisateur": EMPLOYE,
                             "app.repositories.dailylog.lire_jour": jour,
                             "app.repositories.dailylog.projets_info": {1: projet(1, gere=True),
                                                                        9: projet(9, visible_acteur=False)}})
        corps = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("SECRET", resp.data.decode())
        self.assertNotIn("Projet secret", resp.data.decode())
        self.assertEqual(corps["total_minutes"], 420)
        masquee = [l for l in corps["lignes"] if l["masquee"]]
        self.assertEqual(masquee, [{"masquee": True, "minutes": 180, "modifiable": False, "hors_grille": False}])
        self.assertTrue(next(l for l in corps["lignes"] if not l["masquee"])["modifiable"])


class TestJourEtCopie(_BaseDailyLog):
    def test_format_jour_et_copie_filtree_arrondie_plafonnee(self):
        source = self.aujourdhui - datetime.timedelta(days=3)
        def lire(uid, date):
            if date == source:
                return {**smoke.DAILYLOG_JOUR_VIDE, "version": 1, "lignes": [
                    {"projet_id": 1, "tache_id": None, "code": "A", "nom": "A", "tache_titre": None, "minutes": 135, "hors_grille": True},
                    {"projet_id": 2, "tache_id": None, "code": "B", "nom": "B", "tache_titre": None, "minutes": 20, "hors_grille": True},
                    {"projet_id": 3, "tache_id": None, "code": "C", "nom": "C", "tache_titre": None, "minutes": 240, "hors_grille": False},
                    {"projet_id": 4, "tache_id": None, "code": "D", "nom": "D", "tache_titre": None, "minutes": 420, "hors_grille": False},
                    {"projet_id": 5, "tache_id": None, "code": "E", "nom": "E", "tache_titre": None, "minutes": 60, "hors_grille": False}]}
            return smoke.DAILYLOG_JOUR_VIDE
        projets = {1: projet(1), 2: projet(2), 3: projet(3, etat="termine", date_cloture=source), 4: projet(4), 5: projet(5)}
        self._login()
        patchers = self._patched(**{"app.repositories.dailylog.dernier_jour_rempli": source,
                                    "app.repositories.dailylog.projets_info": projets,
                                    "app.repositories.dailylog.jours_manques_recents": [source - datetime.timedelta(days=1)]})
        patchers.append(patch("app.repositories.dailylog.lire_jour", side_effect=lire))
        for p in patchers:
            p.start()
        try:
            corps = self.client.get(f"/dailylog/api/jour/{self.aujourdhui}").get_json()
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(corps["statut"], "vide")
        self.assertEqual(corps["version"], 0)
        self.assertEqual(corps["manques"], [(source - datetime.timedelta(days=1)).isoformat()])
        copie = corps["copie"]
        self.assertEqual(copie["date"], source.isoformat())
        # 135 → 150 ; 20 → 30 (minimum) ; C clos avant la date → exclu ; D 420 plafonné à 600 - 180 = 420 ; E ne tient plus
        self.assertEqual([(l["projet_id"], l["minutes"]) for l in copie["lignes"]], [(1, 150), (2, 30), (4, 420)])
        self.assertEqual(copie["exclues"], 2)
        self.assertEqual(sum(l["minutes"] for l in copie["lignes"]), 600)

    def test_pas_de_copie_ni_de_manques_en_correction_chef(self):
        resp = self.appel("get", f"/dailylog/api/jour/{self.aujourdhui}?utilisateur=2", user=CHEF,
                          **{"app.repositories.utilisateurs.get_utilisateur": EMPLOYE,
                             "app.repositories.dailylog.dernier_jour_rempli": self.aujourdhui})
        corps = resp.get_json()
        self.assertIsNone(corps["copie"])
        self.assertEqual(corps["manques"], [])
        self.assertEqual(corps["droits"]["mode"], "correction")

    def test_mois(self):
        resp = self.appel("get", f"/dailylog/api/mois/{self.aujourdhui:%Y-%m}",
                          **{"app.repositories.dailylog.etats_mois": {"2026-10-01": "rempli"}})
        self.assertEqual(resp.get_json()["jours"], {"2026-10-01": "rempli"})
        futur = self.aujourdhui.replace(day=1) + datetime.timedelta(days=40)
        resp = self.appel("get", f"/dailylog/api/mois/{futur:%Y-%m}")
        self.assertEqual(resp.get_json()["jours"], {})

    def test_etats_mois_trois_etats(self):
        lignes = [{"date": datetime.date(2026, 9, 11), "etat": "rempli"}, {"date": datetime.date(2026, 9, 14), "etat": "absent"},
                  {"date": datetime.date(2026, 9, 15), "etat": "rempli"}, {"date": datetime.date(2026, 9, 15), "etat": "absent"}]
        with patch("app.db.query_all", return_value=lignes):
            etats = dl.etats_mois({"id": 1}, datetime.date(2026, 9, 1), datetime.date(2026, 9, 30),
                                  manques=[datetime.date(2026, 9, 16), datetime.date(2026, 9, 11), datetime.date(2026, 10, 1)])
        self.assertEqual(etats, {"2026-09-11": "rempli", "2026-09-14": "absent", "2026-09-15": "absent", "2026-09-16": "vide"})


class TestPage(_BaseDailyLog):
    def test_page_amorce_et_textes_en_json(self):
        resp = self.appel("get", "/dailylog")
        self.assertEqual(resp.status_code, 200, resp.data[:1000])
        html = resp.data.decode()
        self.assertIn('<script type="application/json" id="dl-amorce">', html)
        self.assertIn('<script type="application/json" id="dl-textes">', html)
        self.assertIn("/static/js/dailylog.js", html)
        self.assertIn("/static/css/dailylog.css", html)
        self.assertNotIn("<form method=\"post\"", html.split('id="dl9"')[1])
        self.assertIn('role="meter"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertNotIn("fonts.googleapis.com/css2?family=Plus+Jakarta+Sans&", html)

    def test_page_date_future_redirige_vers_aujourdhui(self):
        demain = self.aujourdhui + datetime.timedelta(days=1)
        resp = self.appel("get", f"/dailylog?date={demain}")
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f"date={self.aujourdhui}", resp.headers["Location"])
        resp = self.appel("get", "/dailylog?date=0001-01-01")
        self.assertEqual(resp.status_code, 200)

    def test_nom_piege_n_echappe_pas_de_l_amorce(self):
        piege = "</script><img src=x onerror=alert(1)>"
        catalogue = {"mine": [{"projet_id": 1, "code": "X", "nom": piege, "tache_id": None, "tache_titre": None,
                               "nb_taches": 0, "date_debut": None}], "recentes": []}
        resp = self.appel("get", "/dailylog", **{"app.repositories.dailylog.list_lignes_suggerees": catalogue})
        html = resp.data.decode()
        self.assertNotIn(piege, html)
        self.assertIn("\\u003c/script\\u003e", html)

    def test_endpoint_formulaire_garde_son_nom(self):
        with self.app.test_request_context():
            from flask import url_for
            self.assertEqual(url_for("dailylog.formulaire", date="2026-10-01"), "/dailylog?date=2026-10-01")

    def test_selection_d_un_employe_pour_chef_et_admin(self):
        actifs = [{"id": 2, "prenom": "Wael", "nom": "Rekik", "role": "intervenant"},
                  {"id": 7, "prenom": "Rym", "nom": "Client", "role": "client"}]
        for user, voit in ((CHEF, True), (ADMIN, True), (INTERVENANT, False)):
            with self.subTest(role=user["role"]):
                html = self.appel("get", "/dailylog", user=user,
                                  **{"app.repositories.utilisateurs.list_actifs": actifs}).data.decode()
                self.assertEqual('id="dl-qui-select"' in html, voit)
                if voit:
                    self.assertIn("Wael Rekik", html)
                    self.assertNotIn("Rym Client", html)

    def test_mode_correction_bandeau(self):
        html = self.appel("get", "/dailylog?utilisateur=2", user=CHEF,
                          **{"app.repositories.utilisateurs.get_utilisateur": EMPLOYE}).data.decode()
        self.assertIn("Correction du Daily log de <b>Wael Rekik</b>", html)
        self.assertIn("Seules les lignes de vos projets sont modifiables", html)
        self.assertIn('"mode": "correction"', html)

    def test_ancien_css_daily_log_retire(self):
        css = (RACINE / "app" / "static" / "css" / "app.css").read_text(encoding="utf-8")
        for classe in (".lrow", ".dayseg", ".bar-handle", "#duree-popup", ".hq-row", ".cal-day", ".dailylog-wrap", ".warn-banner"):
            self.assertNotIn(classe, css)
        neuf = (RACINE / "app" / "static" / "css" / "dailylog.css").read_text(encoding="utf-8")
        self.assertNotIn("fonts.googleapis", neuf)
        self.assertNotIn(":root{", neuf.replace(" ", ""))   # pas de jetons recopiés
        js = (RACINE / "app" / "static" / "js" / "dailylog.js").read_text(encoding="utf-8")
        self.assertNotIn("new Date(2026", js)               # « aujourd'hui » vient du serveur
        self.assertIn("keepalive", js)


class TestObjectif(_BaseDailyLog):
    def test_bornes_et_pas(self):
        for minutes, statut in ((240, 200), (600, 200), (270, 200), (210, 422), (630, 422), (275, 422),
                                ("480", 422), (True, 422), (480.0, 422)):
            with self.subTest(minutes=minutes):
                resp = self.appel("put", "/dailylog/api/objectif", json={"objectif_minutes": minutes},
                                  espions=[("app.repositories.dailylog.set_objectif", None)])
                self.assertEqual(resp.status_code, statut)
                if statut == 200:
                    self.assertEqual(resp.get_json(), {"objectif_minutes": minutes})
        self.assertEqual(self.appel("put", "/dailylog/api/objectif", json=[480]).status_code, 400)


class TestJoursManquesEtRappel(unittest.TestCase):
    def test_week_ends_jamais_manques_et_aujourdhui_apres_16h_local(self):
        user = {"id": 1, "fuseau": "Africa/Tunis"}
        lundi = datetime.date(2026, 10, 5)
        with patch("app.repositories.dailylog.jours_renseignes", return_value=set()):
            matin = dl.jours_manques_recents(user, aujourdhui=lundi,
                                             maintenant=datetime.datetime(2026, 10, 5, 8, 0, tzinfo=datetime.timezone.utc))
            soir = dl.jours_manques_recents(user, aujourdhui=lundi,
                                            maintenant=datetime.datetime(2026, 10, 5, 15, 30, tzinfo=datetime.timezone.utc))
        self.assertTrue(all(j.weekday() < 5 for j in matin))
        self.assertNotIn(lundi, matin)
        self.assertIn(lundi, soir)  # 16 h 30 à Tunis
        self.assertEqual(len(matin), 10)

    def test_borne_par_la_date_d_arrivee(self):
        user = {"id": 1, "fuseau": "Africa/Tunis", "debut_daily_log": datetime.date(2026, 10, 1)}
        with patch("app.repositories.dailylog.jours_renseignes", return_value={datetime.date(2026, 10, 2)}) as rens:
            manques = dl.jours_manques_recents(user, aujourdhui=datetime.date(2026, 10, 7),
                                               maintenant=datetime.datetime(2026, 10, 7, 9, 0, tzinfo=datetime.timezone.utc))
        self.assertEqual(manques, [datetime.date(2026, 10, 1), datetime.date(2026, 10, 5), datetime.date(2026, 10, 6)])
        self.assertTrue(all(j >= datetime.date(2026, 10, 1) for j in rens.call_args.args[1]))

    def test_rappel_lundi_pour_le_vendredi(self):
        """Lot 11 b : texte clair, jours oubliés de la fenêtre (week-end et
        aujourd'hui exclus), via creer_rappel_dailylog (dédoublonnage par
        rappel_jours, testé sur vraie base)."""
        from app.auth import _verifier_rappel_dailylog
        user = {"id": 1, "fuseau": "Africa/Tunis", "debut_daily_log": datetime.date(2025, 1, 1)}
        lundi = datetime.date(2026, 10, 5)
        remplis = {lundi - datetime.timedelta(days=i) for i in range(4, 15)}  # tout sauf le vendredi 2
        with patch("app.repositories.dailylog.jours_renseignes", return_value=remplis), \
             patch("app.repositories.notifications.creer_rappel_dailylog", return_value=[]) as rappel, \
             patch("app.repositories.notifications.creer") as creer:
            _verifier_rappel_dailylog(user, aujourdhui=lundi)
        creer.assert_not_called()
        uid, jours, texte = rappel.call_args.args
        self.assertEqual((uid, jours), (1, [datetime.date(2026, 10, 2)]))
        self.assertEqual(texte(jours), "Daily log du vendredi 2 octobre non rempli")
        self.assertNotIn("Rappel DailyLog", texte(jours))

    def test_plusieurs_jours_une_seule_notification(self):
        from app.auth import _verifier_rappel_dailylog
        user = {"id": 1, "fuseau": "Africa/Tunis", "debut_daily_log": datetime.date(2026, 9, 29)}
        jeudi = datetime.date(2026, 10, 1)
        with patch("app.repositories.dailylog.jours_renseignes", return_value=set()), \
             patch("app.repositories.notifications.creer_rappel_dailylog", return_value=[]) as rappel:
            _verifier_rappel_dailylog(user, aujourdhui=jeudi)
        rappel.assert_called_once()
        _, jours, texte = rappel.call_args.args
        self.assertEqual(jours, [datetime.date(2026, 9, 29), datetime.date(2026, 9, 30)])
        self.assertEqual(texte(jours), "2 jours de Daily log non remplis : mardi 29 et mercredi 30 septembre")

    def test_texte_du_rappel(self):
        from app.utils import texte_rappel_daily_log as t
        d = datetime.date
        auj = d(2026, 10, 8)
        self.assertEqual(t([d(2026, 10, 7)], auj), "Daily log du mercredi 7 octobre non rempli")
        self.assertEqual(t([d(2026, 10, 1)], auj), "Daily log du jeudi 1er octobre non rempli")
        self.assertEqual(t([d(2026, 10, 7), d(2026, 10, 5), d(2026, 10, 6)], auj),
                         "3 jours de Daily log non remplis : lundi 5, mardi 6 et mercredi 7 octobre")
        self.assertEqual(t([d(2026, 9, 30), d(2026, 10, 1), d(2026, 10, 2)], auj),
                         "3 jours de Daily log non remplis : mercredi 30 septembre, jeudi 1er et vendredi 2 octobre")
        self.assertEqual(t([d(2026, 12, 31), d(2027, 1, 4)], d(2027, 1, 5)),
                         "2 jours de Daily log non remplis : jeudi 31 décembre 2026 et lundi 4 janvier")
        cinq = [d(2026, 10, j) for j in (1, 2, 5, 6, 7)]
        self.assertEqual(t(cinq, auj), "5 jours de Daily log non remplis : jeudi 1er, vendredi 2, lundi 5, "
                                       "mardi 6 et mercredi 7 octobre")
        dix = [d(2026, 9, j) for j in (24, 25, 28, 29, 30)] + cinq
        self.assertEqual(t(dix, auj), "10 jours de Daily log non remplis, du jeudi 24 septembre au mercredi 7 octobre")
        self.assertEqual(t(dix, d(2027, 1, 4)),
                         "10 jours de Daily log non remplis, du jeudi 24 septembre 2026 au mercredi 7 octobre 2026")

    def test_pas_de_rappel_le_week_end_ni_avant_l_arrivee_ni_jour_rempli(self):
        from app.auth import _verifier_rappel_dailylog
        lundi = datetime.date(2026, 10, 5)
        fenetre = {lundi - datetime.timedelta(days=i) for i in range(1, 15)}
        cas = [
            # arrivée le jour même : rien avant
            ({"id": 1, "debut_daily_log": lundi}, set()),
            # tout rempli (ou absent) : rien
            ({"id": 1, "debut_daily_log": None}, fenetre),
            # seul le week-end est vide : jamais un oubli
            ({"id": 1, "debut_daily_log": None}, {j for j in fenetre if j.weekday() < 5}),
        ]
        for user, remplis in cas:
            with self.subTest(user=user, remplis=len(remplis)):
                with patch("app.repositories.dailylog.jours_renseignes", return_value=remplis), \
                     patch("app.repositories.notifications.creer_rappel_dailylog") as rappel:
                    _verifier_rappel_dailylog(user, aujourdhui=lundi)
                rappel.assert_not_called()
        # samedi et dimanche : le jour visé reste le vendredi
        self.assertEqual(dl.jour_ouvre_precedent(datetime.date(2026, 10, 4)), datetime.date(2026, 10, 2))
        self.assertEqual(dl.jour_ouvre_precedent(datetime.date(2026, 10, 3)), datetime.date(2026, 10, 2))

    def test_recherche_sans_accents_et_jokers_litteraux(self):
        self.assertEqual(dl.sans_accents("Résidence ÉTÉ Œuvre"), "residence ete ouvre")
        self.assertEqual(dl.motif_sans_accents(" 50%_a\\b "), "%50\\%\\_a\\\\b%")


class TestAutresPages(_BaseDailyLog):
    def test_notification_daily_log_ouvre_le_jour(self):
        notif = {"id": 9, "message": "Rappel DailyLog : vous n'avez pas rempli votre journée du 02/10/2026.",
                 "post_projet_id": None, "tache_projet_id": None, "post_id": None}
        resp = self.appel("post", "/notifications/9/ouvrir",
                          **{"app.repositories.notifications.get_notification": notif})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/dailylog?date=2026-10-02"))
        resp = self.appel("post", "/notifications/9/ouvrir",
                          **{"app.repositories.notifications.get_notification": {**notif, "message": "Daily log du 31/02/2026 corrigé par X."}})
        self.assertTrue(resp.headers["Location"].endswith("/notifications"))

    def test_rappel_nouveau_format_ouvre_le_premier_jour_a_remplir(self):
        """Lot 11 b : le lien suit rappel_jours (pas le texte) — premier jour
        encore vide, à défaut le premier cité."""
        d = datetime.date
        notif = {"id": 9, "message": "3 jours de Daily log non remplis : lundi 5, mardi 6 et mercredi 7 octobre",
                 "rappel_jours": [d(2026, 10, 7), d(2026, 10, 5), d(2026, 10, 6)],
                 "post_projet_id": None, "tache_projet_id": None, "post_id": None, "tache_id": None}
        for remplis, attendu in ((set(), "2026-10-05"), ({d(2026, 10, 5)}, "2026-10-06"),
                                 ({d(2026, 10, 5), d(2026, 10, 6), d(2026, 10, 7)}, "2026-10-05")):
            with self.subTest(remplis=remplis):
                resp = self.appel("post", "/notifications/9/ouvrir",
                                  **{"app.repositories.notifications.get_notification": notif,
                                     "app.repositories.dailylog.jours_renseignes": remplis})
                self.assertEqual(resp.status_code, 302)
                self.assertTrue(resp.headers["Location"].endswith(f"/dailylog?date={attendu}"), resp.headers["Location"])

    def test_carte_accueil_sait_si_aujourdhui_est_rempli(self):
        html = self.appel("get", "/accueil", **{"app.repositories.dailylog.jour_renseigne": True}).data.decode()
        self.assertIn("Journée du jour renseignée", html)
        html = self.appel("get", "/accueil", **{"app.repositories.dailylog.jour_renseigne": False}).data.decode()
        self.assertIn("Répartissez vos heures de la journée par projet.", html)
        self.assertIn("Remplir mon Daily log", html)

    def test_profil_absent_et_lien_corriger(self):
        jour = dl.aujourdhui_pour(EMPLOYE)
        for user, lien in ((CHEF, True), (ADMIN, True), ({**INTERVENANT, "id": 1}, False)):
            with self.subTest(role=user["role"]):
                resp = self.appel("get", "/utilisateurs/2/profil", user=user,
                                  **{"app.repositories.utilisateurs.get_utilisateur": EMPLOYE,
                                     "app.repositories.dailylog.jours_absents": {jour}})
                html = resp.data.decode()
                self.assertEqual(f"/dailylog?date={jour}&amp;utilisateur=2" in html, lien)
                if lien:
                    self.assertIn("Absent", html)

    def test_fiche_admin_lien_et_fuseau(self):
        html = self.appel("get", "/utilisateurs/2", user=ADMIN,
                          **{"app.repositories.utilisateurs.get_utilisateur": EMPLOYE}).data.decode()
        self.assertIn('name="fuseau"', html)
        self.assertIn("Guyane (UTC−3)", html)
        self.assertIn("/dailylog?utilisateur=2", html)

    def test_fuseau_modifiable_par_admin_et_rh_et_valide(self):
        # L'email reste celui du compte : depuis le lot 10, seul l'Admin peut
        # changer l'adresse d'un employé (le RH n'envoie qu'un lien).
        base = {"prenom": "Ali", "nom": "Ben", "email": EMPLOYE["email"], "role": "intervenant",
                "equipe_code": "MIDGARD"}
        self._login()
        for user in (ADMIN, smoke.RH):
            for fuseau, accepte in (("America/Cayenne", True), ("Africa/Tunis", True),
                                    ("Europe/Tunis", False), ("Europe/Paris", False)):
                with self.subTest(role=user["role"], fuseau=fuseau):
                    patchers = self._patched(**{"app.auth.get_user_by_id": user,
                                                "app.repositories.utilisateurs.get_utilisateur": EMPLOYE})
                    for p in patchers:
                        p.start()
                    try:
                        with patch("app.repositories.utilisateurs.update_utilisateur_complet") as maj, \
                             patch("app.repositories.utilisateurs.create_utilisateur", return_value=9) as cree, \
                             patch("app.routes.utilisateurs.generer_lien_reset", return_value="/x"), \
                             patch("app.mailer.envoyer", return_value=True):
                            self.client.post("/utilisateurs/2", data={**base, "fuseau": fuseau})
                            self.client.post("/utilisateurs/nouveau",
                                             data={**base, "email": "n@m.tn", "fuseau": fuseau, "actif": "on"})
                    finally:
                        for p in reversed(patchers):
                            p.stop()
                    self.assertEqual(maj.called, accepte)
                    self.assertEqual(cree.called, accepte)
                    if accepte:
                        self.assertEqual(maj.call_args.kwargs["fuseau"], fuseau)
                        self.assertEqual(cree.call_args.kwargs["fuseau"], fuseau)


class TestRepriseChronos(unittest.TestCase):
    def test_set_local_juste_apres_begin(self):
        src = (RACINE / "scripts" / "migrate_from_chronos.py").read_text(encoding="utf-8")
        debut = src.index('w("BEGIN;")')
        suite = src[debut:debut + 600]
        self.assertIn('w("SET LOCAL kairos.reprise_historique = \'on\';")', suite)

    def test_migration_0014_et_schema(self):
        mig = (RACINE / "migrations" / "0014_dailylog_v9.sql").read_text(encoding="utf-8")
        schema = (RACINE / "schema.sql").read_text(encoding="utf-8")
        self.assertIn("('0014_dailylog_v9')", schema)
        for objet in ("fn_dailylog_entree_controle", "fn_dailylog_jour_coherent", "fn_dailylog_garde",
                      "fn_sans_accents", "dailylog_preference", "utilisateur_fuseau_valide", "dailylog_jour_version_valide"):
            with self.subTest(objet=objet):
                self.assertIn(objet, mig)
                self.assertIn(objet, schema)
        # Les fonctions sont recopiées à l'identique (catalogue neuf = migré),
        # dans leur DERNIÈRE version (fn_dailylog_garde : 0018, date simulée).
        migrations = sorted((RACINE / "migrations").glob("*.sql"))
        for fonction in ("fn_dailylog_entree_controle", "fn_dailylog_jour_coherent", "fn_dailylog_garde", "fn_sans_accents"):
            debut = f"CREATE OR REPLACE FUNCTION {fonction}("
            derniere = [m.read_text(encoding="utf-8") for m in migrations if debut in m.read_text(encoding="utf-8")][-1]
            corps_mig = derniere[derniere.index(debut):derniere.index("$$ LANGUAGE", derniere.index(debut))]
            corps_schema = schema[schema.index(debut):schema.index("$$ LANGUAGE", schema.index(debut))]
            self.assertEqual(corps_mig, corps_schema, fonction)
        self.assertIn("kairos.reprise_historique", mig)
        self.assertIn("lock_timeout", mig)


if __name__ == "__main__":
    unittest.main()

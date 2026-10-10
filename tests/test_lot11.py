"""Tests du lot 11 (décisions du gérant après la mise en service) : liste
des projets paginée, recherche, dates, heures, code projet proposé, en-têtes,
pages d'erreur, encart Admin, rappel Daily log.

Même principe que tests/test_smoke.py (psycopg2 simulé, repositories
remplacés par des mocks). Le SQL est vérifié sur un vrai PostgreSQL par
tests_integration/test_lot11.py et tests/sql/lot11.sql.
"""
import unittest
from unittest.mock import patch

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
except ImportError:  # python -m unittest tests.test_lot11
    from tests import test_smoke as smoke


class _Base(smoke.SmokeBase):
    def _avec(self, appel, **overrides):
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        try:
            return appel()
        finally:
            for p in reversed(patchers):
                p.stop()


class TestListeDesProjets(_Base):
    def _liste(self, url, total, lignes=1, **autres):
        projets = [dict(smoke.PROJET_LISTE_SANS_HEURES, id=i + 1) for i in range(lignes)]
        with patch("app.repositories.projets.list_projets", return_value=projets) as liste, \
                patch("app.repositories.projets.compter_projets", return_value=total) as compte:
            overrides = {k: v for k, v in autres.items()}
            self._login()
            patchers = [p for p in self._patched(**overrides)
                        if p.attribute not in ("list_projets", "compter_projets")]
            for p in patchers:
                p.start()
            try:
                resp = self.client.get(url, headers={"X-Requested-With": "XMLHttpRequest"})
            finally:
                for p in reversed(patchers):
                    p.stop()
        return resp, liste, compte

    def test_vrai_total_et_pages_de_50(self):
        resp, liste, compte = self._liste("/projets?filtres_actifs=1&etat=termine&page=2", total=653, lignes=50)
        body = resp.get_data(as_text=True)
        self.assertIn("653 projets · 51–100 affichés", body)
        self.assertIn("Page 2 sur 14", body)
        self.assertIn('rel="prev"', body)
        self.assertIn('rel="next"', body)
        self.assertIn("page=1", body)
        self.assertIn("page=3", body)
        self.assertIn("etat=termine", body)  # filtres conservés dans les liens
        kwargs = liste.call_args.kwargs
        self.assertEqual((kwargs["limit"], kwargs["offset"]), (50, 50))
        self.assertEqual(compte.call_args.kwargs["etats"], ["termine"])

    def test_page_hors_bornes_ramenee_a_la_derniere(self):
        resp, liste, _ = self._liste("/projets?filtres_actifs=1&page=99", total=120, lignes=20)
        self.assertIn("Page 3 sur 3", resp.get_data(as_text=True))
        self.assertEqual(liste.call_args.kwargs["offset"], 100)
        resp, liste, _ = self._liste("/projets?filtres_actifs=1&page=abc", total=120, lignes=50)
        self.assertEqual(liste.call_args.kwargs["offset"], 0)

    def test_une_seule_page_sans_navigation(self):
        resp, _, _ = self._liste("/projets", total=1)
        body = resp.get_data(as_text=True)
        self.assertIn(">1 projet<", body)
        self.assertNotIn("Page 1 sur", body)

    def test_recherche_ignore_le_filtre_chef_moi_et_le_dit(self):
        chefs = [{"id": 1, "prenom": "Fadhel", "nom": "Chemmem", "avatar_chemin": None}]
        resp, liste, compte = self._liste("/projets?q=louison", total=1, **{
            "app.repositories.projets.list_chefs_de_projet": chefs})
        self.assertIsNone(liste.call_args.kwargs["chef_ids"])
        self.assertIsNone(compte.call_args.kwargs["chef_ids"])
        self.assertEqual(liste.call_args.kwargs["etats"], ["en_cours", "bloque"])
        self.assertIn("le filtre «&nbsp;Chef de projet&nbsp;: vous&nbsp;» est ignoré", resp.get_data(as_text=True))
        # Sans texte : le filtre par défaut s'applique.
        resp, liste, _ = self._liste("/projets", total=1, **{"app.repositories.projets.list_chefs_de_projet": chefs})
        self.assertEqual(liste.call_args.kwargs["chef_ids"], [1])
        self.assertNotIn("est ignoré", resp.get_data(as_text=True))

    def test_recherche_garde_un_filtre_chef_explicite_vers_un_autre(self):
        _, liste, _ = self._liste("/projets?filtres_actifs=1&chef_id=7&q=tour", total=1)
        self.assertEqual(liste.call_args.kwargs["chef_ids"], [7])

    def test_export_sans_plafond(self):
        with patch("app.repositories.projets.list_projets", return_value=[]) as liste:
            self._login()
            patchers = [p for p in self._patched() if p.attribute != "list_projets"]
            for p in patchers:
                p.start()
            try:
                resp = self.client.get("/projets/export.xlsx?filtres_actifs=1")
            finally:
                for p in reversed(patchers):
                    p.stop()
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(liste.call_args.kwargs["limit"])


class TestDatesEtHeures(_Base):
    def test_annee_ecrite_hors_de_l_annee_en_cours(self):
        import datetime
        from app.utils import date_courte
        cette_annee = datetime.date.today().year
        self.assertEqual(date_courte(datetime.date(2022, 11, 17)), "17 nov. 2022")
        self.assertEqual(date_courte(datetime.date(cette_annee, 6, 1)), "1er juin")
        self.assertEqual(date_courte(datetime.date(cette_annee, 6, 1), True), f"1er juin {cette_annee}")
        self.assertEqual(date_courte(datetime.date(2022, 6, 1), False), "1er juin")
        self.assertEqual(date_courte(None), "")

    def test_retard_en_jours(self):
        import datetime
        from app.utils import build_gantt, en_retard_de
        auj = datetime.date(2026, 10, 8)
        self.assertEqual(en_retard_de(datetime.date(2026, 10, 1), auj), "en retard de 7 j")
        self.assertEqual(en_retard_de(auj, auj), "")
        self.assertEqual(en_retard_de(None, auj), "")
        g = build_gantt([{"date_echeance": datetime.date(2026, 9, 1)},
                         {"date_echeance": datetime.date(2026, 10, 20)}], auj)
        self.assertEqual(g["rows"][0]["label_barre"], "◀ en retard de 37 j")
        self.assertEqual(g["rows"][0]["retard"], "en retard de 37 j")
        self.assertEqual(g["rows"][1]["label_barre"], "20 oct.")  # plus « 20/10 »

    def test_heures_en_heures_et_minutes(self):
        from decimal import Decimal
        from app.utils import heures, heures_interv_chef
        nb = "\u00a0"
        self.assertEqual(heures(1.75), f"1{nb}h{nb}45")
        self.assertEqual(heures(Decimal("8.00")), f"8{nb}h")
        self.assertEqual(heures(0.5), f"0{nb}h{nb}30")
        self.assertEqual(heures(None), f"0{nb}h")
        self.assertEqual(heures(2.67), f"2{nb}h{nb}40")
        self.assertEqual(heures(0.25), f"0{nb}h{nb}15")
        self.assertEqual(heures_interv_chef(8, 5.5), f"8{nb}h · 5{nb}h{nb}30")

    def test_plus_aucune_heure_decimale_dans_les_gabarits(self):
        import pathlib
        racine = pathlib.Path(__file__).resolve().parent.parent / "app" / "templates"
        for gabarit in racine.rglob("*.html"):
            with self.subTest(gabarit=gabarit.name):
                self.assertNotIn("heures_courtes", gabarit.read_text(encoding="utf-8"))

    def test_deadlines_au_fuseau_de_la_personne(self):
        import datetime
        taches = [dict(smoke.DEADLINES[0], date_echeance=datetime.date(2026, 10, 6))]
        with patch("app.repositories.dailylog.aujourdhui_pour", return_value=datetime.date(2026, 10, 8)) as fuseau:
            resp = self._avec(lambda: self.client.get("/deadlines"),
                              **{"app.repositories.taches.list_deadlines": taches})
        self.assertTrue(fuseau.called)
        self.assertIn("◀ en retard de 2 j", resp.get_data(as_text=True))

    def test_accueil_retard_dans_mes_taches_et_le_bandeau(self):
        import datetime
        tache = dict(smoke.MES_TACHES[0], etat="en_cours", date_echeance=datetime.date(2026, 10, 3))
        echeance = [dict(smoke.DEADLINES[0], date_echeance=datetime.date(2026, 10, 5))]
        with patch("app.repositories.dailylog.aujourdhui_pour", return_value=datetime.date(2026, 10, 8)):
            resp = self._avec(lambda: self.client.get("/accueil"), **{
                "app.repositories.taches.list_mes_taches": [tache],
                "app.repositories.taches.list_deadlines": echeance})
        body = resp.get_data(as_text=True)
        self.assertIn("en retard de 5 j", body)   # Mes tâches
        self.assertIn("· en retard de 3 j", body)  # bandeau des échéances


class TestCodePropose(unittest.TestCase):
    """Numéro d'affaire global à l'année (toutes phases), lettre selon la
    phase, série 9xx jamais proposée, phase liée = même numéro."""

    def propose(self, codes, phase, **kw):
        from app.repositories import projets
        with patch("app.db.query_all", return_value=[{"code": c} for c in codes]) as requete:
            code = projets.propose_code(phase, annee=2026, **kw)
        self.assertEqual(requete.call_args.args[1], ("26%",))  # toutes les phases de l'année
        return code

    def test_numero_global_toutes_phases(self):
        codes = ["26076D", "26077X", "26088X", "26085P", "26922X", "26924X", "25999X", "26C9P", "26077X-2"]
        self.assertEqual(self.propose(codes, "APS"), "26089P")
        self.assertEqual(self.propose(codes, "APD"), "26089P")
        self.assertEqual(self.propose(codes, "DCE"), "26089D")
        self.assertEqual(self.propose(codes, "EXE"), "26089X")
        self.assertEqual(self.propose(codes, "DOE"), "26089E")

    def test_serie_9xx_jamais_proposee(self):
        self.assertEqual(self.propose(["26901X", "26950P"], "EXE"), "26001X")
        self.assertEqual(self.propose(["26899P", "26900X"], "EXE"), "261000X")
        self.assertEqual(self.propose(["26899P", "261003D"], "DCE"), "261004D")

    def test_phase_liee_garde_son_numero(self):
        from app.repositories import projets
        with patch("app.db.query_one", return_value=None), patch("app.db.query_all") as requete:
            self.assertEqual(projets.propose_code("EXE", annee=2026, phase_liee_code="26922D"), "26922X")
        requete.assert_not_called()
        # Même lettre (APS -> APD) : déjà pris, numéro suivant de l'année.
        with patch("app.db.query_one", return_value={"pris": 1}), \
                patch("app.db.query_all", return_value=[{"code": "26012P"}, {"code": "26040X"}]):
            self.assertEqual(projets.propose_code("APD", annee=2026, phase_liee_code="26012P"), "26041P")

    def test_neuf_cents_saisissable_a_la_main(self):
        from app.repositories.projets import code_valide
        self.assertTrue(code_valide("26924X", "EXE"))


class TestRechercheGlobale(_Base):
    def test_projets_taches_et_personnes_inactives_signalees(self):
        resp = self._avec(lambda: self.client.get("/recherche/api?q=resid"), **{
            "app.repositories.projets.search": [{"id": 4, "code": "26001X", "nom": "Résidence Été", "etat": "bloque"}],
            "app.repositories.taches.search": [{"id": 9, "titre": "Coffrage", "etat": "en_cours", "projet_id": 4,
                                                "projet_code": "26001X", "projet_nom": "Résidence Été"}],
            "app.repositories.utilisateurs.search": [
                {"id": 3, "prenom": "Fadhel", "nom": "Chemmem", "poste": "Gérant", "actif": True},
                {"id": 8, "prenom": "Omrane", "nom": "B", "poste": None, "actif": False}],
        })
        r = resp.get_json()["resultats"]
        self.assertEqual([x["label"] for x in r],
                         ["26001X_Résidence Été", "Coffrage", "Fadhel Chemmem", "Omrane B (inactif)"])
        self.assertEqual(r[0]["sous_titre"], "Projet · Bloqué")
        self.assertEqual((r[1]["sous_titre"], r[1]["url"]), ("Tâche en cours · 26001X_Résidence Été", "/projets/4?tache=9"))
        self.assertEqual(r[2]["sous_titre"], "Gérant")
        self.assertEqual((r[3]["sous_titre"], r[3]["url"]), ("compte désactivé", "/utilisateurs/8/profil"))

    def test_sql_sans_accents_partout(self):
        import inspect
        from app.repositories import dailylog, projets, taches, utilisateurs
        for fn in (projets.search, taches.search, utilisateurs.search, utilisateurs.list_tous,
                   dailylog.rechercher_projets):
            with self.subTest(fn=fn.__qualname__):
                self.assertIn("fn_recherche(", inspect.getsource(fn))
        self.assertIn("fn_recherche(p.code || '_' || p.nom) LIKE fn_recherche(%(q)s)", projets._FILTRES_LISTE)

    def test_motif_litteral_et_espaces(self):
        from app.repositories._like import motif_recherche
        self.assertEqual(motif_recherche("  Fadhel   Chem "), "%fadhel chem%")
        self.assertEqual(motif_recherche("50%_a\\b"), "%50\\%\\_a\\\\b%")


class TestEnTetesCache(_Base):
    def test_no_store_sur_tout_ce_qui_est_authentifie(self):
        for url in ("/accueil", "/projets", "/projets/1", "/deadlines", "/notifications",
                    "/recherche/api?q=ab", "/projets/code-propose?phase=EXE", "/projets/export.xlsx",
                    "/page-inexistante"):
            with self.subTest(url=url):
                resp = self._get(url)
                self.assertEqual(resp.headers.get("Cache-Control"), "no-store")

    def test_piece_jointe_et_avatar(self):
        from flask import Response

        def fichier(*args, **kwargs):
            r = Response(b"%PDF", mimetype="application/pdf")
            r.headers["Cache-Control"] = "no-cache"
            r.headers["ETag"] = '"abc"'
            return r
        with patch("app.routes.fichiers.send_from_directory", side_effect=fichier):
            resp = self._get("/fichiers/taches/1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["Cache-Control"], "no-store")
        self.assertNotIn("ETag", resp.headers)
        # Toujours les en-têtes de sécurité habituels.
        self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")

    def test_statiques_et_anonyme_inchanges(self):
        resp = self._get("/static/css/app.css")
        self.assertNotEqual(resp.headers.get("Cache-Control"), "no-store")
        resp.close()
        resp = self.app.test_client().get("/connexion")
        self.assertNotEqual(resp.headers.get("Cache-Control"), "no-store")


class TestPagesErreur(_Base):
    def setUp(self):
        super().setUp()
        from flask import abort

        @self.app.route("/__test/interdit")
        def _interdit():
            abort(403)

        @self.app.route("/__test/plante")
        def _plante():
            raise RuntimeError("secret technique : /app/routes/x.py ligne 12")

    def _verifier(self, resp, code, titre):
        body = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, code)
        self.assertIn("text/html", resp.headers["Content-Type"])
        self.assertIn('<html lang="fr">', body)
        self.assertIn(f"Erreur {code}", body)
        self.assertIn(titre, body)
        self.assertIn("Retour à l’accueil", body)
        self.assertIn('href="/accueil"', body)
        for technique in ("Werkzeug", "Traceback", "Not Found", "The requested URL", "secret technique"):
            self.assertNotIn(technique, body)
        return body

    def test_404_403_405(self):
        self._verifier(self._get("/page-inexistante"), 404, "Page introuvable")
        self._verifier(self._get("/projets/1", **{"app.repositories.projets.user_can_view": False}),
                       404, "Page introuvable")
        self._verifier(self._get("/__test/interdit"), 403, "Accès refusé")
        resp = self._get("/notifications/1/ouvrir")  # POST seulement
        self._verifier(resp, 405, "Action non autorisée")
        self.assertIn("POST", resp.headers["Allow"])

    def test_404_anonyme(self):
        self._verifier(self.client.get("/inexistante"), 404, "Page introuvable")

    def test_500_sans_detail_technique(self):
        self.app.testing = False
        self.app.config["PROPAGATE_EXCEPTIONS"] = False
        with self.assertLogs(self.app.logger, level="ERROR"):
            body = self._verifier(self._get("/__test/plante"), 500, "Erreur du serveur")
        self.assertIn("prévenez l’administrateur", body)

    def test_api_json_inchangee(self):
        resp = self._get("/dailylog/api/inexistante")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["erreur"], "introuvable")


class TestAdminChefDesactive(_Base):
    LIGNES = [{"id": 7, "code": "21114X", "nom": "Siemens", "etat": "bloque", "chef_id": 9,
               "chef_prenom": "Omrane", "chef_nom": "B"}]

    def test_encart_pour_l_admin(self):
        resp = self._avec(lambda: self.client.get("/utilisateurs"),
                          **{"app.repositories.projets.list_ouverts_chef_inactif": self.LIGNES})
        body = resp.get_data(as_text=True)
        self.assertIn("Projets ouverts dont le chef est désactivé (1)", body)
        self.assertIn('href="/projets/7"', body)
        self.assertIn("21114X_Siemens", body)
        self.assertIn("Omrane B (désactivé)", body)

    def test_rien_pour_un_chef_de_projet(self):
        chef = dict(smoke.USER, role="chef_de_projet")
        resp = self._avec(lambda: self.client.get("/utilisateurs"), **{
            "app.auth.get_user_by_id": chef, "app.repositories.projets.list_ouverts_chef_inactif": self.LIGNES})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("dont le chef est désactivé", resp.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()

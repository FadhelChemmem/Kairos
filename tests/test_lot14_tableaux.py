"""Tests du lot 14 (A2) : Vue d'ensemble de l'Admin (revue produit P0-3),
carte « À traiter » du chef de projet et « Tâches de mes projets » (P1-2),
Deadlines sur « Tous les projets » pour l'Admin.

Même principe que tests/test_smoke.py (psycopg2 simulé, repositories
remplacés par des mocks) ; le SQL est vérifié par tests_integration.
"""
import datetime
import json
import unittest

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
    from test_lot13_front import _Base
    from test_lot13_pages import espion, fragment, partiel
except ImportError:  # python -m unittest tests.test_lot14_tableaux
    from tests import test_smoke as smoke
    from tests.test_lot13_front import _Base
    from tests.test_lot13_pages import espion, fragment, partiel

from app.routes import tableaux  # noqa: E402

CHEF = {**smoke.USER, "role": "chef_de_projet"}
INTERV = {**smoke.USER, "role": "intervenant"}
COMPTE = {"projets": 59, "retard": 9, "retard_max": 5, "bloquees": 27, "projets_bloques": 14,
          "sans_intervenant": 6, "sans_echeance": 0, "projets_sans_tache": 37, "dailylog": 25}
RETARD = [{"id": 41, "titre": "Plans de coffrage", "etat": "en_cours", "date_echeance": datetime.date(2026, 10, 1),
           "type_deadline": "rendu_client", "updated_at": None, "projet_id": 7, "projet_code": "26089X",
           "projet_nom": "Résidence", "chef_id": 2, "chef_prenom": "Ali", "chef_nom": "Chef", "intervenants": "Rim B."}]
MANQUANTS = [{"id": 5, "prenom": "Rim", "nom": "Inter", "poste": None, "role": "intervenant", "avatar_chemin": None}]
BLOQUEES = [{**RETARD[0], "etat": "bloque", "bloque_motif": "Attente des plans <archi>",
             "bloque_le": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3),
             "bloque_par_prenom": "Rim", "bloque_par_nom": "Inter"}]
PAR_CHEF = [{"id": 2, "prenom": "Ali", "nom": "Chef", "avatar_chemin": None, "actif": True,
             "projets": 4, "retard": 2, "bloquees": 1, "heures": 12.5}]


class TestVueEnsemble(_Base):
    def test_accueil_admin_tuiles_gantt_du_bureau_et_par_chef(self):
        compteurs = espion("app.repositories.tableaux.compteurs", COMPTE)
        liste = espion("app.repositories.tableaux.liste", [])
        tous = espion("app.repositories.taches.list_deadlines_tous", smoke.DEADLINES)
        html = self._appel("get", "/accueil", extra=[compteurs.patcher, liste.patcher, tous.patcher], **{
            "app.repositories.tableaux.par_chef": PAR_CHEF}).get_data(as_text=True)
        self.assertIn('id="vue-ensemble"', html)
        for cle in ("retard", "bloquees", "projets_sans_tache", "dailylog"):
            self.assertIn(f'id="tuile-{cle}"', html)
        self.assertNotIn('id="tuile-sans_intervenant"', html)
        self.assertIn('href="/accueil?voir=retard"', html)
        self.assertIn('aria-expanded="false" aria-controls="ve-detail"', html)
        self.assertIn('<span class="ve-tuile-nombre">9</span>', html)
        self.assertIn("Échéances du bureau", html)  # lot 15 : ligne repliée
        self.assertIn("Par chef de projet", html)
        self.assertIn('href="/deadlines?vue=tous&amp;chef=2"', html)
        self.assertIn("12 h 30", html)
        # Tout le bureau, aucune liste dépliée sans ?voir.
        self.assertTrue(compteurs.call_args.args[1])
        liste.assert_not_called()
        tous.assert_called_once()
        self.assertNotIn('id="a-traiter"', html)

    def test_tuile_depliee_en_fragment(self):
        liste = espion("app.repositories.tableaux.liste", RETARD)
        resp = self._appel("get", "/accueil?voir=retard&taches=miennes", partiel("#vue-ensemble"),
                           extra=[liste.patcher], **{"app.repositories.tableaux.compteurs": COMPTE})
        self.assertEqual(resp.status_code, 200)
        html = fragment(self, resp)
        self.assertTrue(html.lstrip().startswith('<section id="vue-ensemble"'))
        self.assertEqual(liste.call_args.args[:3], ("retard", smoke.USER["id"], True))
        self.assertIn('id="tuile-retard" class="ve-tuile tb-t-retard"', html)
        self.assertIn('aria-expanded="true"', html)
        # La tuile ouverte se replie (lien sans ?voir), le mode des tâches est gardé.
        self.assertIn('href="/accueil?taches=miennes" id="tuile-retard"', html)
        self.assertIn('id="ve-detail-titre"', html)
        self.assertIn('href="/projets/7?tache=41"', html)
        self.assertIn("Ali Chef", html)
        # Retard compté depuis l'échéance de la fixture (date du jour réelle).
        self.assertIn(f"+{(datetime.date.today() - RETARD[0]['date_echeance']).days}&nbsp;j", html)

    def test_voir_inconnu_ignore(self):
        liste = espion("app.repositories.tableaux.liste", RETARD)
        html = self._appel("get", "/accueil?voir=sans_echeance", extra=[liste.patcher]).get_data(as_text=True)
        liste.assert_not_called()  # pas une tuile de l'Admin
        self.assertNotIn('id="ve-detail-titre"', html)

    def test_dailylog_masque_pour_admin_sans_heures(self):
        html = self._appel("get", "/accueil", **{"app.repositories.tableaux.saisit_des_heures": False}).get_data(as_text=True)
        self.assertNotIn('class="acc-dl', html)
        html = self._appel("get", "/accueil", **{"app.repositories.tableaux.saisit_des_heures": True}).get_data(as_text=True)
        self.assertIn('class="acc-dl', html)

    def test_vue_ensemble_refusee_hors_admin(self):
        for user in (CHEF, INTERV):
            compteurs = espion("app.repositories.tableaux.compteurs", COMPTE)
            resp = self._appel("get", "/accueil?voir=retard", partiel("#vue-ensemble"), extra=[compteurs.patcher],
                               **{"app.auth.get_user_by_id": user})
            self.assertEqual(resp.status_code, 403)
            self.assertIn("message", json.loads(resp.get_data(as_text=True)))
            compteurs.assert_not_called()


class TestATraiter(_Base):
    def test_chef_carte_lignes_non_nulles(self):
        compte = {**COMPTE, "projets": 3, "bloquees": 0, "sans_echeance": 1}
        compteurs = espion("app.repositories.tableaux.compteurs", compte)
        html = self._appel("get", "/accueil", extra=[compteurs.patcher],
                           **{"app.auth.get_user_by_id": CHEF,
                              "app.repositories.dailylog.manquants_du_jour": MANQUANTS}).get_data(as_text=True)
        self.assertFalse(compteurs.call_args.args[1])  # ses projets seulement
        self.assertIn('id="a-traiter"', html)
        self.assertIn("Vos 3 projets ouverts", html)
        self.assertIn('id="at-retard"', html)
        self.assertIn('id="at-sans_echeance"', html)
        self.assertNotIn('id="at-bloquees"', html)  # 0 : masquée
        self.assertIn("votre équipe", html)
        self.assertIn('<span class="at-nombre">1</span>', html)
        self.assertNotIn('id="vue-ensemble"', html)
        self.assertNotIn("Toutes les échéances du bureau", html)

    def test_rien_a_traiter(self):
        zero = {k: 0 for k in COMPTE} | {"projets": 2}
        html = self._appel("get", "/accueil", **{"app.auth.get_user_by_id": CHEF,
                                                 "app.repositories.tableaux.compteurs": zero}).get_data(as_text=True)
        self.assertIn("Rien à traiter.", html)
        self.assertNotIn('class="at-lignes"', html)

    def test_fragment_ligne_depliee(self):
        liste = espion("app.repositories.tableaux.liste", RETARD)
        resp = self._appel("get", "/accueil?voir=retard", partiel("#a-traiter"), extra=[liste.patcher],
                           **{"app.auth.get_user_by_id": CHEF, "app.repositories.tableaux.compteurs": COMPTE})
        html = fragment(self, resp)
        self.assertTrue(html.lstrip().startswith('<section id="a-traiter"'))
        self.assertEqual(liste.call_args.args[:3], ("retard", smoke.USER["id"], False))
        self.assertIn('id="at-detail-fermer"', html)
        self.assertIn('data-focus-apres="#at-retard"', html)
        self.assertNotIn("Ali Chef", html)  # ses propres projets : le chef n'est pas répété

    def test_intervenant_sans_carte_sauf_co_chef(self):
        html = self._appel("get", "/accueil", **{"app.auth.get_user_by_id": INTERV}).get_data(as_text=True)
        self.assertNotIn('id="a-traiter"', html)
        self.assertNotIn("data-tdp-bascule", html)
        self.assertIn(">Mes tâches</h2>", html)
        resp = self._appel("get", "/accueil", partiel("#a-traiter"), **{"app.auth.get_user_by_id": INTERV})
        self.assertEqual(resp.status_code, 403)
        resp = self._appel("get", "/accueil", partiel("#accueil-taches"), **{"app.auth.get_user_by_id": INTERV})
        self.assertEqual(resp.status_code, 403)
        html = self._appel("get", "/accueil", **{"app.auth.get_user_by_id": INTERV,
                                                 "app.repositories.tableaux.gere_des_projets": True}).get_data(as_text=True)
        self.assertIn('id="a-traiter"', html)
        self.assertIn("data-tdp-bascule", html)

    def test_rh_et_client_sans_tableaux(self):
        for role in ("rh", "client"):
            compteurs = espion("app.repositories.tableaux.compteurs", COMPTE)
            html = self._appel("get", "/accueil?voir=retard", extra=[compteurs.patcher],
                               **{"app.auth.get_user_by_id": {**smoke.USER, "role": role}}).get_data(as_text=True)
            compteurs.assert_not_called()
            self.assertNotIn('id="a-traiter"', html)
            self.assertNotIn('id="vue-ensemble"', html)


class TestRecetteTableaux(_Base):
    """Recette du lot 14 : n° 7 (accords), n° 8 (pas de lien « Daily log »
    pour qui n'y a pas droit), n° 10 (liste des tâches bloquées : motif,
    durée, auteur)."""

    def test_accords(self):
        for projets, attendu in ((1, "Votre projet ouvert"), (2, "Vos 2 projets ouverts"),
                                 (0, "Aucun projet ouvert à gérer")):
            with self.subTest(projets=projets):
                html = self._appel("get", "/accueil", **{"app.auth.get_user_by_id": CHEF,
                                                         "app.repositories.tableaux.compteurs": {**COMPTE, "projets": projets}}
                                   ).get_data(as_text=True)
                self.assertIn(f'<p class="at-portee">{attendu}</p>', html)
                self.assertNotIn("Vos 1 ", html)
        zero = {**COMPTE, "projets": 1, "projets_bloques": 1, "bloquees": 1}
        html = self._appel("get", "/accueil", **{"app.repositories.tableaux.compteurs": zero,
                                                 "app.repositories.dailylog.manquants_du_jour": []}).get_data(as_text=True)
        self.assertIn("Tout le bureau · 1 projet ouvert", html)
        self.assertIn("sur 1 projet ouvert", html)
        self.assertNotIn("sur 1 projets", html)
        self.assertIn('<span class="ve-tuile-unite"> personne</span>', html)
        html = self._appel("get", "/accueil", **{"app.repositories.tableaux.compteurs": {**COMPTE, "projets": 0}}
                           ).get_data(as_text=True)
        self.assertIn("Tout le bureau · aucun projet ouvert", html)

    def test_intervenant_co_chef_sans_ligne_daily_log(self):
        manquants = espion("app.repositories.dailylog.manquants_du_jour", MANQUANTS)
        html = self._appel("get", "/accueil?voir=dailylog", extra=[manquants.patcher],
                           **{"app.auth.get_user_by_id": INTERV,
                              "app.repositories.tableaux.gere_des_projets": True}).get_data(as_text=True)
        self.assertIn('id="a-traiter"', html)
        self.assertNotIn('id="at-dailylog"', html)
        self.assertNotIn("utilisateur=5", html)
        manquants.assert_not_called()
        resp = self._appel("get", "/accueil?voir=dailylog", partiel("#a-traiter"),
                           **{"app.auth.get_user_by_id": INTERV, "app.repositories.tableaux.gere_des_projets": True,
                              "app.repositories.dailylog.manquants_du_jour": MANQUANTS})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("utilisateur=5", resp.get_data(as_text=True))
        # Le chef de projet garde la ligne, et le lien vers l'équipe.
        resp = self._appel("get", "/accueil?voir=dailylog", partiel("#a-traiter"),
                           **{"app.auth.get_user_by_id": CHEF, "app.repositories.dailylog.manquants_du_jour": MANQUANTS})
        html = resp.get_data(as_text=True)
        self.assertIn('id="at-dailylog"', html)
        self.assertIn("utilisateur=5", html)
        self.assertIn('href="/dailylog/equipe"', html)

    def test_liste_des_bloquees_motif_duree_auteur(self):
        liste = espion("app.repositories.tableaux.liste", BLOQUEES)
        for user, cible in ((smoke.USER, "#vue-ensemble"), (CHEF, "#a-traiter")):
            with self.subTest(cible=cible):
                resp = self._appel("get", "/accueil?voir=bloquees", partiel(cible), extra=[liste.patcher],
                                   **{"app.auth.get_user_by_id": user, "app.repositories.tableaux.compteurs": COMPTE})
                html = resp.get_data(as_text=True)
                self.assertIn("« Attente des plans &lt;archi&gt; »", html.replace("&nbsp;", " "))
                self.assertIn('<span class="tb-ligne-depuis">Depuis 3&nbsp;j</span>', html.replace("\u00a0", "&nbsp;"))
                self.assertIn("par Rim Inter", html)
                self.assertIn("le blocage le plus ancien d’abord", html)
                self.assertNotIn("la dernière modifiée d’abord", html)


class TestTachesDeMesProjets(_Base):
    LIGNES = [{**smoke.MES_TACHES[0], "id": 1, "etat": "en_cours", "projet_code": "26099X", "mienne": False},
              {**smoke.MES_TACHES[0], "id": 2, "etat": "en_cours", "titre": "Ma tâche", "projet_code": "26099X", "mienne": True}]

    def test_bascule_et_mode_toutes(self):
        html = self._appel("get", "/accueil", **{"app.auth.get_user_by_id": CHEF,
                                                 "app.repositories.tableaux.taches_de_mes_projets": self.LIGNES}).get_data(as_text=True)
        self.assertIn(">Tâches de mes projets</h2>", html)
        self.assertIn('id="tdp-toutes" data-partiel="#accueil-taches"', html)
        self.assertIn('data-tableau-valeur="" aria-current="page">Toutes</a>', html)
        self.assertIn('href="/projets/1?tache=1"', html)
        self.assertIn('<span class="tdp-a-vous">À vous</span>', html)

    def test_fragment_les_miennes(self):
        resp = self._appel("get", "/accueil?taches=miennes", partiel("#accueil-taches"), **{
            "app.auth.get_user_by_id": CHEF, "app.repositories.tableaux.taches_de_mes_projets": self.LIGNES})
        html = fragment(self, resp)
        self.assertTrue(html.lstrip().startswith('<div id="accueil-taches"'))
        self.assertIn('data-mode="miennes"', html)
        self.assertIn('href="/projets/1?tache=2"', html)
        self.assertNotIn('href="/projets/1?tache=1"', html)

    def test_miennes_vide_propose_toutes(self):
        resp = self._appel("get", "/accueil?taches=miennes", partiel("#accueil-taches"), **{
            "app.auth.get_user_by_id": CHEF, "app.repositories.tableaux.taches_de_mes_projets": self.LIGNES[:1]})
        html = fragment(self, resp)
        self.assertIn("Aucune tâche en cours à votre nom.", html)
        self.assertIn(">Voir toutes les tâches</a>", html)

    def test_pastilles_de_mes_projets(self):
        # Lot 15 (sobriété) : une seule pastille par projet — « Bloqué »,
        # sinon le nombre de tâches en retard ; plus de prochaine échéance.
        projets = [{"id": 1, "code": "26099X", "nom": "Tour", "phase": "EXE", "etat": "bloque", "mon_role": "chef_de_projet"},
                   {"id": 2, "code": "26100X", "nom": "Pont", "phase": "APS", "etat": "en_cours", "mon_role": "co_chef"}]
        html = self._appel("get", "/accueil", **{
            "app.auth.get_user_by_id": CHEF, "app.repositories.projets.list_mes_projets_recents": projets,
            "app.repositories.tableaux.pastilles_projets": {1: {"retard": 2, "prochaine": datetime.date(2026, 10, 14)},
                                                            2: {"retard": 3, "prochaine": None}},
        }).get_data(as_text=True)
        self.assertIn('<span class="pill pill-sm pill-rouge">3 en retard</span>', html)
        self.assertIn('<span class="pill pill-sm pill-rouge">Bloqué</span>', html)
        self.assertNotIn("2 en retard", html)
        self.assertNotIn("Prochaine échéance", html)
        self.assertIn('<span class="acc-phase">APS</span>', html)


class TestDeadlinesAdmin(_Base):
    def test_admin_arrive_sur_tous_les_projets(self):
        tous = espion("app.repositories.taches.list_deadlines_tous", [])
        mes = espion("app.repositories.taches.list_deadlines", [])
        html = self._appel("get", "/deadlines", extra=[tous.patcher, mes.patcher]).get_data(as_text=True)
        self.assertTrue(tous.called)
        mes.assert_not_called()
        self.assertIn('href="/deadlines?vue=tous" data-partiel="#deadlines-contenu" data-vue="tous" aria-current="page"', html)
        self.assertIn('href="/deadlines?vue=mes" data-partiel="#deadlines-contenu" data-vue=""', html)
        tous = espion("app.repositories.taches.list_deadlines_tous", [])
        self._appel("get", "/deadlines?vue=mes", extra=[tous.patcher])
        tous.assert_not_called()

    def test_chef_inchange(self):
        tous = espion("app.repositories.taches.list_deadlines_tous", [])
        self._appel("get", "/deadlines", extra=[tous.patcher], **{"app.auth.get_user_by_id": CHEF})
        tous.assert_not_called()


class TestAides(unittest.TestCase):
    def test_jour_du_daily_log(self):
        lundi, samedi = datetime.date(2026, 10, 12), datetime.date(2026, 10, 10)
        self.assertEqual(tableaux.jour_dailylog(lundi), datetime.date(2026, 10, 9))
        self.assertEqual(tableaux.libelle_jour(datetime.date(2026, 10, 9), lundi), "vendredi")
        self.assertEqual(tableaux.libelle_jour(tableaux.jour_dailylog(samedi), samedi), "hier")


if __name__ == "__main__":
    unittest.main()

"""Lot 14 (A2) sur un vrai PostgreSQL : compteurs et listes de la Vue
d'ensemble (Admin) et de la carte « À traiter » (chef, co-chef), tableau
« Par chef de projet », « Tâches de mes projets », pastilles de « Mes
projets », Deadlines sur « Tous les projets » ; droits : périmètre tiré du
compte, cibles partielles refusées hors rôle, aucun paramètre ne donne les
projets d'un autre."""
import datetime

from app.repositories import dailylog as dl
from app.repositories import tableaux as tb
from tests_integration.test_lot12 import _Base


class _Tableaux(_Base):
    def setUp(self):
        super().setUp()
        self.jour = dl.jour_ouvre_precedent(self.auj)
        self.chef2 = self.user("chef_de_projet")
        self.inter2 = self.user("intervenant")
        self.cochef = self.user("chef_de_projet")
        self.sql("UPDATE utilisateur SET date_embauche = %s", (self.auj - datetime.timedelta(days=90),))
        self.sql("UPDATE utilisateur SET prenom = 'Zoé', nom = 'Second' WHERE id = %s", (self.chef2,))
        self.p3 = self.projet(self.chef2)
        self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p3, self.cochef))
        self.t3 = self.tache(self.p3, self.chef2, intervenants=[self.inter2], echeance=self.auj - datetime.timedelta(days=4))
        self.sql("UPDATE tache SET titre = 'Tâche du second chef' WHERE id = %s", (self.t3,))
        self.t4 = self.tache(self.p1, self.chef, etat="bloque")
        self.p4 = self.projet(self.chef)
        self.tache(self.p4, self.chef, etat="termine")
        self.p5 = self.projet(self.chef, etat="termine")
        self.tache(self.p5, self.chef, echeance=self.auj - datetime.timedelta(days=30))
        # inter a rempli son Daily log du dernier jour ouvré.
        self.sql("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, 3)",
                 (self.inter, self.jour, self.p1))

    def compte(self, uid, tous):
        c = tb.compteurs(uid, tous, self.auj, self.jour)
        c["dailylog"] = len(self.manquants(None if tous else uid))
        return c

    def manquants(self, gere_par):
        """Daily log manquants du dernier jour ouvré : même périmètre que la
        page « Daily log de l'équipe » (recette du lot 14, n° 9)."""
        with self.app.app_context():
            return dl.manquants_du_jour(gere_par, self.jour)


class TestCompteurs(_Tableaux):
    def test_tout_le_bureau(self):
        c = self.compte(self.admin, True)
        self.assertEqual(c["projets"], 4)          # p1 p2 p3 p4 (p5 terminé)
        self.assertEqual(c["retard"], 1)            # t3 (la tâche du projet terminé ne compte pas)
        self.assertEqual(c["retard_max"], 4)
        self.assertEqual(c["bloquees"], 1)          # t4
        self.assertEqual(c["projets_bloques"], 1)
        self.assertEqual(c["sans_intervenant"], 2)  # t2, t4
        self.assertEqual(c["projets_sans_tache"], 1)  # p4
        # chef, chef2, cochef, inter2 (inter a rempli ; les Admin ne saisissent pas ; pas le RH).
        self.assertEqual(c["dailylog"], 4)
        noms = {r["id"] for r in self.manquants(None)}
        self.assertEqual(noms, {self.chef, self.chef2, self.cochef, self.inter2})

    def test_absence_et_arrivee_recente_ne_manquent_pas(self):
        self.sql("INSERT INTO dailylog_jour (utilisateur_id, date, absent) VALUES (%s, %s, true)", (self.inter2, self.jour))
        self.sql("UPDATE utilisateur SET date_embauche = %s WHERE id = %s", (self.auj, self.chef2))
        self.sql("UPDATE utilisateur SET actif = false WHERE id = %s", (self.cochef,))
        self.assertEqual(self.compte(self.admin, True)["dailylog"], 1)  # chef seul

    def test_admin_qui_saisit_compte(self):
        self.assertFalse(tb.saisit_des_heures(self.admin2))
        self.sql("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, 1)",
                 (self.admin2, self.jour - datetime.timedelta(days=7), self.p1))
        self.assertTrue(tb.saisit_des_heures(self.admin2))
        self.assertEqual(self.compte(self.admin, True)["dailylog"], 5)

    def test_perimetre_du_chef(self):
        c = self.compte(self.chef, False)
        self.assertEqual((c["projets"], c["retard"], c["bloquees"], c["projets_sans_tache"]), (3, 0, 1, 1))
        self.assertEqual(c["sans_intervenant"], 2)
        # Son équipe (page « Daily log de l'équipe ») : lui-même et inter, qui a rempli.
        self.assertEqual(c["dailylog"], 1)
        self.assertEqual([r["id"] for r in self.manquants(self.chef)], [self.chef])
        self.assertEqual([r["id"] for r in tb.liste("projets_sans_tache", self.chef, False, self.auj, self.jour)], [self.p4])
        self.assertEqual(tb.liste("retard", self.chef, False, self.auj, self.jour), [])

    def test_perimetre_du_co_chef(self):
        c = self.compte(self.cochef, False)
        # p3, t3 ; Daily log : lui, chef2 (titulaire de p3) et inter2.
        self.assertEqual((c["projets"], c["retard"], c["dailylog"]), (1, 1, 3))
        lignes = tb.liste("retard", self.cochef, False, self.auj, self.jour)
        self.assertEqual([(r["id"], r["intervenants"]) for r in lignes], [(self.t3, "P intervenant")])
        self.assertTrue(tb.gere_des_projets(self.cochef))
        self.assertFalse(tb.gere_des_projets(self.inter))

    def test_sans_echeance_et_cle_inconnue(self):
        self.sql("UPDATE tache SET date_echeance = NULL WHERE id = %s", (self.t1,))
        self.assertEqual([r["id"] for r in tb.liste("sans_echeance", self.chef, False, self.auj, self.jour)], [self.t1])
        self.assertEqual(tb.liste("x; DROP TABLE tache", self.chef, False, self.auj, self.jour), [])


class TestParChefEtCartes(_Tableaux):
    def test_par_chef(self):
        lundi = self.auj - datetime.timedelta(days=self.auj.weekday())
        self.sql("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, 2.5)",
                 (self.inter2, self.auj, self.p3))
        lignes = {r["id"]: r for r in tb.par_chef(self.auj, lundi)}
        self.assertEqual(set(lignes), {self.chef, self.chef2})
        self.assertEqual((lignes[self.chef]["projets"], lignes[self.chef]["retard"], lignes[self.chef]["bloquees"]), (3, 0, 1))
        self.assertEqual((lignes[self.chef2]["projets"], lignes[self.chef2]["retard"]), (1, 1))
        self.assertEqual(float(lignes[self.chef2]["heures"]), 2.5)
        attendu = 3.0 if self.jour >= lundi else 0.0
        self.assertEqual(float(lignes[self.chef]["heures"]), attendu)

    def test_taches_de_mes_projets_et_pastilles(self):
        lignes = tb.taches_de_mes_projets(self.chef)
        self.assertEqual({r["id"] for r in lignes}, {self.t1, self.t2})  # en cours, projets ouverts
        self.assertFalse(any(r["mienne"] for r in lignes))
        miennes = tb.taches_de_mes_projets(self.inter)
        self.assertEqual([(r["id"], r["mienne"]) for r in miennes], [(self.t1, True)])
        p = tb.pastilles_projets([self.p1, self.p3], self.auj)
        self.assertEqual(p[self.p3]["retard"], 1)
        self.assertEqual(p[self.p1], {"retard": 0, "prochaine": self.auj + datetime.timedelta(days=5)})


class TestPagesEtDroits(_Tableaux):
    def test_accueil_admin(self):
        self.login(self.admin)
        page = self.texte(self.client.get("/accueil"))
        self.assertIn('id="vue-ensemble"', page)
        self.assertIn("Par chef de projet", page)
        self.assertIn("Zoé Second", page)
        r = self.client.get("/accueil?voir=retard", headers={"X-Kairos-Partiel": "#vue-ensemble"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Tâche du second chef", self.texte(r))
        self.assertNotIn("<html", self.texte(r))

    def test_chef_ne_voit_que_ses_projets(self):
        self.login(self.chef)
        page = self.texte(self.client.get("/accueil?voir=retard"))
        self.assertIn('id="a-traiter"', page)
        self.assertNotIn("Tâche du second chef", page)
        self.assertNotIn('id="vue-ensemble"', page)
        # Cible forgée : refusée, rien du bureau.
        r = self.client.get("/accueil?voir=retard", headers={"X-Kairos-Partiel": "#vue-ensemble"})
        self.assertEqual(r.status_code, 403)
        self.assertNotIn("Tâche du second chef", self.texte(r))
        r = self.client.get("/accueil?voir=bloquees", headers={"X-Kairos-Partiel": "#a-traiter"})
        self.assertEqual(r.status_code, 200)
        self.assertIn(f'href="/projets/{self.p1}?tache={self.t4}"', self.texte(r))

    def test_co_chef_voit_le_retard_de_son_projet(self):
        self.login(self.cochef)
        r = self.client.get("/accueil?voir=retard", headers={"X-Kairos-Partiel": "#a-traiter"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Tâche du second chef", self.texte(r))

    def test_intervenant_et_rh_refuses(self):
        for uid in (self.inter, self.inter2):
            self.login(uid)
            for cible in ("#vue-ensemble", "#a-traiter", "#accueil-taches"):
                r = self.client.get("/accueil?voir=retard", headers={"X-Kairos-Partiel": cible})
                self.assertEqual(r.status_code, 403, (uid, cible))
        # inter2 intervient sur la tâche (« Mes tâches ») ; inter, non.
        self.login(self.inter)
        self.assertNotIn("Tâche du second chef", self.texte(self.client.get("/accueil?voir=retard")))
        self.login(self.rh)
        r = self.client.get("/accueil?voir=retard", headers={"X-Kairos-Partiel": "#vue-ensemble"})
        self.assertNotEqual(r.status_code, 200)

    def test_deadlines_admin_sur_tous_les_projets(self):
        self.login(self.admin)
        self.assertIn("Tâche du second chef", self.texte(self.client.get("/deadlines")))
        self.assertNotIn("Tâche du second chef", self.texte(self.client.get("/deadlines?vue=mes")))
        self.login(self.chef)
        self.assertNotIn("Tâche du second chef", self.texte(self.client.get("/deadlines?vue=tous")))


class TestRecetteDailyLogEquipe(_Tableaux):
    """Recette du lot 14 : n° 9 (« Daily log manquants » de « À traiter »
    = colonne du jour de la page « Daily log de l'équipe »), n° 8 (liens
    cohérents avec les droits), n° 11 (pas de rappel pour l'Admin qui ne
    saisit pas d'heures)."""

    def nombre_carte(self, html, cle):
        import re
        m = re.search(rf'id="{cle}"[^>]*>.*?<span class="(?:at|ve-tuile)-nombre">(\d+)', html, re.S)
        return int(m.group(1)) if m else 0

    def colonne_equipe(self):
        """Nombre de « manquants » au pied de la colonne du jour, page
        « Daily log de l'équipe » de la personne connectée."""
        import re
        lundi = self.jour - datetime.timedelta(days=self.jour.weekday())
        html = self.texte(self.client.get(f"/dailylog/equipe?semaine={lundi.isoformat()}"))
        pied = html.split("<tfoot>")[1].split("</tfoot>")[0]
        cellules = re.findall(r'<td class="dlq-pied"[^>]*>(.*?)</td>', pied, re.S)
        m = re.search(r'dlq-ico-pied" aria-hidden="true">!</span>(\d+)', cellules[self.jour.weekday()])
        return int(m.group(1)) if m else 0

    def test_chef_et_co_chef_meme_compte_que_l_equipe(self):
        # chef2 devient aussi co-chef de p1 : il est dans l'équipe du chef.
        self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, self.chef2))
        attendus = {self.chef: 2, self.cochef: 3, self.chef2: 4}  # avant : 0, 1, 2 (intervenants seulement)
        for qui, attendu in attendus.items():
            with self.subTest(qui=qui):
                self.login(qui)
                accueil = self.texte(self.client.get("/accueil"))
                self.assertEqual((self.nombre_carte(accueil, "at-dailylog"), self.colonne_equipe()), (attendu, attendu))

    def test_admin_tuile_egale_l_equipe(self):
        self.login(self.admin)
        accueil = self.texte(self.client.get("/accueil"))
        self.assertEqual(self.nombre_carte(accueil, "tuile-dailylog"), 4)
        html = self.texte(self.client.get("/accueil?voir=dailylog", headers={"X-Kairos-Partiel": "#vue-ensemble"}))
        self.assertIn('href="/dailylog/equipe"', html)

    def test_intervenant_co_chef_sans_ligne_ni_lien_interdit(self):
        self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p3, self.inter))
        self.login(self.inter)
        accueil = self.texte(self.client.get("/accueil?voir=dailylog"))
        self.assertIn('id="a-traiter"', accueil)
        self.assertNotIn('id="at-dailylog"', accueil)
        self.assertNotIn("/dailylog?utilisateur=", accueil.replace("&amp;", "&"))
        self.assertNotIn("utilisateur=", accueil.split('id="a-traiter"')[1].split("</section>")[0])

    def test_pas_de_rappel_pour_l_admin_sans_heures(self):
        rappels = lambda uid: self.compter(  # noqa: E731
            "SELECT count(*) AS n FROM notification WHERE utilisateur_id = %s AND message LIKE '%%Daily log%%'", (uid,))
        _login = self.login

        def login(uid):  # le rappel est vérifié une fois par jour et par session
            _login(uid)
            with self.client.session_transaction() as session:
                session.pop("rappel_le", None)
        self.login = login
        self.login(self.admin)
        self.client.get("/accueil")
        self.assertEqual(rappels(self.admin), 0)
        # Ni à la connexion (formulaire).
        from werkzeug.security import generate_password_hash
        self.sql("UPDATE utilisateur SET email = 'admin-rappel@t.tn', mot_de_passe_hash = %s WHERE id = %s",
                 (generate_password_hash("Mot-de-passe-2026!"), self.admin))
        client = self.app.test_client()
        r = client.post("/connexion", data={"email": "admin-rappel@t.tn", "password": "Mot-de-passe-2026!"})
        self.assertEqual(r.status_code, 302)
        client.get("/accueil")
        self.assertEqual(rappels(self.admin), 0)
        # Un Admin qui saisit des heures garde son rappel.
        self.sql("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, 1)",
                 (self.admin2, self.jour - datetime.timedelta(days=20), self.p1))
        self.login(self.admin2)
        self.client.get("/accueil")
        self.assertGreaterEqual(rappels(self.admin2), 1)
        # Le chef aussi (inchangé).
        self.login(self.chef)
        self.client.get("/accueil")
        self.assertGreaterEqual(rappels(self.chef), 1)

"""Lot 14 (A3) sur un VRAI PostgreSQL : tâches en cours proposées dans le
Daily log (revue produit P0-4) et Daily log de l'équipe (P1-9), droits
compris (requêtes forgées, « Voir comme »)."""
import datetime
import re

from tests_integration.base import BaseIntegration

PARTIEL = {"X-Kairos-Partiel": "#dlq", "X-Requested-With": "XMLHttpRequest"}


class _Base(BaseIntegration):
    def setUp(self):
        super().setUp()
        from app.repositories import dailylog
        self.dl = dailylog
        self.admin = self.user("admin")
        self.chef = self.user("chef_de_projet")
        self.cochef = self.user("chef_de_projet")
        self.moi = self.user("intervenant")
        self.autre = self.user("intervenant")       # hors des projets du chef
        self.rh = self.user("rh", equipe=None)
        self.sql("UPDATE utilisateur SET created_at = now() - interval '400 days'")
        self.auj = self.dl.aujourdhui_pour({"fuseau": "Africa/Tunis"})
        self.pa = self.projet(self.chef, code="26001A")
        self.pb = self.projet(self.chef, code="26002B")
        self.pc = self.projet(self.cochef, code="26003C")
        self.sql("UPDATE projet SET nom = 'Projet ' || code")
        self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s)", (self.pa, self.cochef))
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s), (%s, %s)",
                 (self.pa, self.moi, self.pb, self.moi))
        self.t1 = self.tache(self.pa, self.chef, intervenants=(self.moi,))
        self.t2 = self.tache(self.pa, self.chef, etat="bloque", intervenants=(self.moi,))
        self.t3 = self.tache(self.pa, self.chef, etat="termine", intervenants=(self.moi,))
        self.t4 = self.tache(self.pc, self.cochef, intervenants=(self.autre,))
        self.sql("UPDATE tache SET created_at = now() - interval '30 days'")

    def jour(self, uid, date):
        self.login(uid)
        r = self.client.get(f"/dailylog/api/jour/{date.isoformat()}")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()

    def ouvre_precedent(self, n=1):
        d = self.auj
        while n:
            d -= datetime.timedelta(days=1)
            if d.weekday() < 5:
                n -= 1
        return d


class TestPropositions(_Base):
    def test_taches_en_cours_puis_projets_suivis_sans_tache(self):
        j = self.jour(self.moi, self.auj)
        cles = [(l["projet_id"], l["tache_id"]) for l in j["proposees"]]
        # Projet A : ses deux tâches ouvertes (Bloquée comprise), pas la terminée,
        # pas de « projet seul » (elle y a des tâches) ; projet B : projet seul.
        self.assertCountEqual(cles, [(self.pa, self.t1), (self.pa, self.t2), (self.pb, None)])
        self.assertEqual(cles[0][0], self.pa)              # regroupées par projet (nom)
        self.assertEqual(j["lignes"], [])
        self.assertEqual(self.sql("SELECT count(*) AS n FROM dailylog_entree")[0]["n"], 0)  # jamais stockées

    def test_chef_et_co_chef_projet_seul_pour_leurs_projets(self):
        j = self.jour(self.chef, self.auj)
        self.assertCountEqual([(l["projet_id"], l["tache_id"]) for l in j["proposees"]],
                              [(self.pa, None), (self.pb, None)])
        j = self.jour(self.cochef, self.auj)
        self.assertCountEqual([(l["projet_id"], l["tache_id"]) for l in j["proposees"]],
                              [(self.pa, None), (self.pc, None)])

    def test_plus_de_8_projets_geres_seulement_les_recents(self):
        autres = [self.projet(self.chef) for _ in range(8)]
        hier = self.ouvre_precedent()
        with self.db.get_cursor() as cur:
            cur.execute("SET LOCAL kairos.reprise_historique = 'on'")
            cur.execute("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, 2)",
                        (self.chef, hier, autres[3]))
        j = self.jour(self.chef, self.auj)
        self.assertEqual([(l["projet_id"], l["tache_id"]) for l in j["proposees"]], [(autres[3], None)])

    def test_rien_hors_journee_vierge_ni_en_correction_ni_hors_fenetre(self):
        hier = self.ouvre_precedent()
        self.login(self.moi)
        r = self.client.put(f"/dailylog/api/jour/{hier.isoformat()}",
                            json={"version": 0, "lignes": [{"projet_id": self.pa, "tache_id": self.t1, "minutes": 60}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["proposees"], [])                    # journée remplie
        r = self.client.post(f"/dailylog/api/jour/{self.auj.isoformat()}/absence", json={"version": 0, "absent": True})
        self.assertEqual(r.get_json()["proposees"], [])                    # jour absent
        loin = self.auj - datetime.timedelta(days=20)
        self.assertEqual(self.jour(self.moi, loin)["proposees"], [])       # au-delà de 14 jours
        self.login(self.chef)
        r = self.client.get(f"/dailylog/api/jour/{self.ouvre_precedent(2).isoformat()}?utilisateur={self.moi}")
        self.assertEqual(r.get_json()["proposees"], [])                    # correction par le chef

    def test_tache_ou_projet_pas_encore_commence(self):
        avant = self.auj - datetime.timedelta(days=3)
        self.sql("UPDATE tache SET created_at = now() WHERE id = %s", (self.t1,))      # créée après : proposée quand même
        self.sql("UPDATE tache SET date_debut = %s WHERE id = %s", (self.auj, self.t2))
        self.sql("UPDATE projet SET date_debut = %s WHERE id = %s", (self.auj, self.pb))
        cles = [(l["projet_id"], l["tache_id"]) for l in self.jour(self.moi, avant)["proposees"]]
        self.assertEqual(cles, [(self.pa, self.t1)])

    def test_projet_clos_jamais_propose(self):
        self.sql("UPDATE projet SET etat = 'termine', date_cloture = %s WHERE id = %s",
                 (self.auj - datetime.timedelta(days=1), self.pb))
        self.sql("UPDATE projet SET etat = 'abandonne', date_cloture = %s WHERE id = %s",
                 (self.auj - datetime.timedelta(days=1), self.pa))
        self.assertEqual(self.jour(self.moi, self.auj)["proposees"], [])

    def test_lignes_proposees_acceptees_a_l_enregistrement(self):
        j = self.jour(self.moi, self.auj)
        lignes = [{"projet_id": l["projet_id"], "tache_id": l["tache_id"], "minutes": 120} for l in j["proposees"]]
        r = self.client.put(f"/dailylog/api/jour/{self.auj.isoformat()}", json={"version": 0, "lignes": lignes})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(self.sql("SELECT sum(heures) AS h FROM dailylog_entree WHERE utilisateur_id = %s",
                                  (self.moi,))[0]["h"], 6)


class TestEquipe(_Base):
    def page(self, uid, qs="", **kw):
        self.login(uid)
        return self.client.get("/dailylog/equipe" + qs, **kw)

    def test_droits_seuls_admin_et_chef(self):
        for uid in (self.moi, self.rh):
            r = self.page(uid)
            self.assertEqual(r.status_code, 302)
            self.assertNotIn("/dailylog/equipe", r.headers["Location"])
        client_ipco = self.user("client", equipe="IPCO")
        self.assertEqual(self.page(client_ipco).status_code, 302)
        r = self.page(self.moi, headers=PARTIEL)                         # requête partielle forgée
        self.assertNotEqual(r.status_code, 200)
        self.assertNotIn(b"dlq-table", r.data)
        r = self.app.test_client().get("/dailylog/equipe")                # sans session
        self.assertEqual(r.status_code, 302)
        self.assertIn("/connexion", r.headers["Location"])

    def test_chef_voit_les_personnes_de_ses_projets_seulement(self):
        html = self.page(self.chef).get_data(as_text=True)
        ids = {int(x) for x in re.findall(r'/utilisateurs/(\d+)"', html)}
        self.assertEqual(ids, {self.chef, self.cochef, self.moi})        # pas « autre » (projet C, géré par le co-chef)
        self.assertNotIn(f"utilisateur={self.autre}", html)

    def test_admin_voit_tout_le_bureau_sauf_rh_client_inactifs(self):
        inactif = self.user("intervenant", actif=False)
        html = self.page(self.admin).get_data(as_text=True)
        ids = {int(x) for x in re.findall(r'/utilisateurs/(\d+)"', html)}
        self.assertEqual(ids, {self.chef, self.cochef, self.moi, self.autre})
        self.assertNotIn(inactif, ids)

    def test_cases_rempli_absent_manquant_et_liens(self):
        lundi = self.auj - datetime.timedelta(days=self.auj.weekday() + 7)   # semaine dernière, entière
        with self.db.get_cursor() as cur:
            cur.execute("SET LOCAL kairos.reprise_historique = 'on'")
            cur.execute("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, 7.5)",
                        (self.moi, lundi, self.pa))
            cur.execute("INSERT INTO dailylog_jour (utilisateur_id, date, absent) VALUES (%s, %s, true)",
                        (self.moi, lundi + datetime.timedelta(days=1)))
            cur.execute("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, 3)",
                        (self.moi, lundi + datetime.timedelta(days=5), self.pa))
        html = self.page(self.chef, f"?semaine={(lundi + datetime.timedelta(days=2)).isoformat()}").get_data(as_text=True)
        self.assertIn(f'href="/dailylog?date={lundi.isoformat()}&amp;utilisateur={self.moi}"', html)
        ligne = html[html.index(f"/utilisateurs/{self.moi}\""):]
        ligne = ligne[:ligne.index("</tr>")]
        self.assertIn("dlq-rempli", ligne)
        self.assertIn("7 h 30", ligne)
        self.assertIn("dlq-absent", ligne)
        self.assertEqual(ligne.count("dlq-manquant"), 3)
        self.assertIn("10 h 30", ligne)                          # total, samedi compris
        self.assertIn("le week-end", ligne)
        # Sa propre ligne : lien vers son Daily log, sans ?utilisateur=.
        self.assertIn(f'href="/dailylog?date={lundi.isoformat()}"', html)

    def test_semaine_future_ramenee_a_la_semaine_courante_et_parametre_invalide(self):
        loin = (self.auj + datetime.timedelta(days=60)).isoformat()
        for qs in (f"?semaine={loin}", "?semaine=n%27importe", "?semaine=2026-02-31", "?semaine=" + "9" * 30):
            r = self.page(self.chef, qs)
            self.assertEqual(r.status_code, 200, qs)
            html = r.get_data(as_text=True)
            self.assertIn('id="dlq-suiv" aria-disabled="true"', html, qs)

    def test_navigation_partielle_rend_le_fragment(self):
        r = self.page(self.admin, "?semaine=2026-09-02", headers=PARTIEL)
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertTrue(html.lstrip().startswith('<section class="dlq" id="dlq"'), html[:200])
        self.assertNotIn("<html", html)
        self.assertIn("Semaine du 31 août au 4 septembre 2026", html)
        self.assertIn("?semaine=2026-08-24", html)
        self.assertIn("?semaine=2026-09-07", html)

    def test_post_refuse_et_voir_comme_garde_les_droits_de_la_personne(self):
        self.login(self.chef)
        r = self.client.post("/dailylog/equipe")
        self.assertEqual(r.status_code, 405)
        self.login(self.admin)
        with self.client.session_transaction() as s:
            s["mode_admin"] = {"admin": self.admin, "cible": self.moi, "mode": "voir"}
        r = self.client.get("/dailylog/equipe")
        self.assertEqual(r.status_code, 302)                               # intervenant : pas de page d'équipe
        with self.client.session_transaction() as s:
            s["mode_admin"] = {"admin": self.admin, "cible": self.chef, "mode": "voir"}
        html = self.client.get("/dailylog/equipe").get_data(as_text=True)
        ids = {int(x) for x in re.findall(r'/utilisateurs/(\d+)"', html)}
        self.assertEqual(ids, {self.chef, self.cochef, self.moi})

    def test_lien_depuis_le_daily_log_pour_admin_et_chef_seulement(self):
        self.login(self.chef)
        self.assertIn('id="dl-equipe"', self.client.get("/dailylog").get_data(as_text=True))
        self.login(self.moi)
        self.assertNotIn('id="dl-equipe"', self.client.get("/dailylog").get_data(as_text=True))


class TestFiche(_Base):
    def test_dix_derniers_jours_ouvres_chef_et_admin(self):
        hier = self.ouvre_precedent()
        with self.db.get_cursor() as cur:
            cur.execute("SET LOCAL kairos.reprise_historique = 'on'")
            cur.execute("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, 4)",
                        (self.moi, hier, self.pa))
        for uid in (self.chef, self.admin):
            self.login(uid)
            html = self.client.get(f"/utilisateurs/{self.moi}").get_data(as_text=True)
            self.assertIn("Daily log — 10 derniers jours ouvrés", html)
            self.assertEqual(html.count('class="dl-semaine-jour'), 10)
            self.assertIn(f'/dailylog?date={hier.isoformat()}&amp;utilisateur={self.moi}', html)
            self.assertIn("Non renseigné", html)
            self.assertIn('href="/dailylog/equipe"', html)

    def test_rien_pour_le_rh_ni_sur_la_fiche_d_un_rh(self):
        self.login(self.rh)
        self.assertNotIn("Daily log — 10 derniers", self.client.get(f"/utilisateurs/{self.moi}").get_data(as_text=True))
        self.login(self.chef)
        html = self.client.get(f"/utilisateurs/{self.rh}").get_data(as_text=True)
        self.assertNotIn("Daily log — 10 derniers", html)
        self.assertIn("nom et téléphone uniquement", html)

    def test_chef_ne_voit_que_les_lignes_de_ses_projets_mais_l_etat_reel(self):
        hier = self.ouvre_precedent()
        with self.db.get_cursor() as cur:
            cur.execute("SET LOCAL kairos.reprise_historique = 'on'")
            self.sql("UPDATE projet SET equipe_code = 'URBS' WHERE id = %s", (self.pc,))
            cur.execute("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, 4)",
                        (self.autre, hier, self.pc))
        self.login(self.chef)
        html = self.client.get(f"/utilisateurs/{self.autre}").get_data(as_text=True)
        self.assertNotIn("Projet 26003C", html)
        bloc = html[html.index(f"/dailylog?date={hier.isoformat()}") - 600:html.index(f"/dailylog?date={hier.isoformat()}")]
        self.assertNotIn("Non renseigné", bloc)                            # rempli, même si rien n'est détaillé

    def test_preference_dans_mes_informations(self):
        self.login(self.moi)
        html = self.client.get("/utilisateurs/moi").get_data(as_text=True)
        self.assertIn(f'data-pref-dl-proposer="{self.moi}" checked', html)
        self.assertIn("dailylog-preferences.js", html)
        self.login(self.rh)
        self.assertNotIn("data-pref-dl-proposer", self.client.get("/utilisateurs/moi").get_data(as_text=True))

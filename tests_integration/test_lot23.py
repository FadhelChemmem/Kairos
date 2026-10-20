"""Lot 23 sur un vrai PostgreSQL : test Chrome des lots 21 et 22, avec les
décisions du gérant du 20/10 (filtres mémorisés par personne, notification
ouverte sur « Tout » avec le post signalé, Admin : tous les chefs par
défaut)."""
import datetime

from tests_integration.test_lot20 import _Lot20, partiel

PARTIEL = {"X-Kairos-Partiel": "#x", "X-Requested-With": "XMLHttpRequest"}


class TestFiltresMemorisesParPersonne(_Lot20):
    MODE_TEST = True

    def test_equipe(self):
        self.login(self.admin)
        self.client.get("/utilisateurs?q=&equipe_code=URBS&role=&actif=", headers=PARTIEL)
        # Page ouverte par le menu : redirigée vers l'adresse du choix (Retour fiable).
        r = self.client.get("/utilisateurs")
        self.assertEqual((r.status_code, r.headers["Location"]),
                         (302, "/utilisateurs?filtres_actifs=1&equipe_code=URBS"))
        self.assertRegex(self.texte(self.client.get(r.headers["Location"])), r'<option value="URBS" selected')
        # Retour du navigateur vers l'adresse sans filtre (partiel) : tout le monde.
        self.assertNotRegex(self.texte(self.client.get("/utilisateurs", headers=PARTIEL)), r'URBS" selected')
        self.client.get("/utilisateurs?defaut=1", headers=PARTIEL)
        r = self.client.get("/utilisateurs")
        self.assertEqual(r.status_code, 200)
        self.assertNotRegex(self.texte(r), r'<option value="URBS" selected')

    def test_journal(self):
        self.login(self.admin)
        self.client.get("/admin/journal?table=&action=INSERT&utilisateur_id=&date_debut=&date_fin=",
                        headers=PARTIEL)
        self.assertRegex(self.texte(self.client.get("/admin/journal", follow_redirects=True)),
                         r'<option value="INSERT" selected')
        self.client.get("/admin/journal?defaut=1", headers=PARTIEL)
        self.assertNotRegex(self.texte(self.client.get("/admin/journal", follow_redirects=True)),
                            r'<option value="INSERT" selected')

    def test_voir_comme_et_agir_comme_n_ecrivent_rien(self):
        """Lot 24 (décision du 20/10) : ni en « Voir comme » ni en « Agir
        comme » — l'Admin lit les filtres de la personne sans les changer."""
        self.sql("INSERT INTO utilisateur_preference (utilisateur_id, filtres) VALUES (%s, %s)",
                 (self.chef, '{"projets": "filtres_actifs=1&etat=bloque"}'))
        self.entrer(self.chef, mode="voir")
        r = self.client.get("/projets?filtres_actifs=1&etat=termine", headers=PARTIEL)
        self.assertEqual(r.status_code, 200)
        self.client.post("/admin/revenir")
        self.entrer(self.chef, mode="agir")
        self.assertIn('href="/projets/export.xlsx?filtres_actifs=1&etat=bloque"', self.texte(self.client.get("/projets")))
        self.client.get("/projets?filtres_actifs=1&etat=termine", headers=PARTIEL)
        self.client.get("/projets?defaut=1")
        self.assertEqual(self.sql("SELECT filtres->>'projets' AS f FROM utilisateur_preference "
                                  "WHERE utilisateur_id = %s", (self.chef,))[0]["f"], "filtres_actifs=1&etat=bloque")
        self.assertEqual(self.compter("SELECT count(*) AS n FROM utilisateur_preference WHERE utilisateur_id <> %s",
                                      (self.chef,)), 0)

    def test_admin_tous_les_chefs_par_defaut_et_export_aux_filtres_effectifs(self):
        self.login(self.admin)
        page = self.texte(self.client.get("/projets"))
        self.assertNotRegex(page, r'name="chef_id"[^>]*>\s*<option[^>]*selected')
        self.client.get("/projets?filtres_actifs=1&etat=termine&lot_egal=CM", headers=PARTIEL)
        page = self.texte(self.client.get("/projets"))
        self.assertIn('href="/projets/export.xlsx?filtres_actifs=1&etat=termine&lot_egal=CM"', page)

    def test_afficher_tous_les_projets_page_entiere_memorisee(self):
        self.login(self.chef)
        self.client.get("/projets?filtres_actifs=1&etat=abandonne", headers=PARTIEL)
        page = self.texte(self.client.get("/projets"))
        self.assertIn('href="/projets?filtres_actifs=1&choix=1" class="btn"', page)
        self.client.get("/projets?filtres_actifs=1&choix=1")
        page = self.texte(self.client.get("/projets"))
        self.assertNotRegex(page, r'<option value="abandonne" selected')


class TestMentionEnModifiantUnPost(_Lot20):
    def test_tag_dans_le_texte_modifie(self):
        post = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', "
                        "'Relevé') RETURNING id", (self.p1, self.chef))[0]["id"]
        urbs = self.user("intervenant", equipe="URBS")
        self.sql("UPDATE utilisateur SET prenom = 'Uri', nom = 'Urbs' WHERE id = %s", (urbs,))
        self.login(self.chef)
        r = self.client.post(f"/posts/{post}/modifier", data={"contenu": "Relevé pour @Rim Inter et @Uri Urbs"},
                             headers=partiel(f"#post-{post}"))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual([x["utilisateur_id"] for x in self.sql("SELECT utilisateur_id FROM post_mention "
                                                               "WHERE post_id = %s", (post,))], [self.inter])
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE utilisateur_id = %s "
                                      "AND message LIKE '%%mentionné dans un post%%'", (self.inter,)), 1)
        self.client.post(f"/posts/{post}/modifier", data={"contenu": "Relevé corrigé pour @Rim Inter"},
                         headers=partiel(f"#post-{post}"))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE utilisateur_id = %s",
                                      (self.inter,)), 1)                                  # pas deux fois
        page = self.texte(self.client.get(f"/projets/{self.p1}"))
        self.assertIn(f'id="post-{post}-texte" name="contenu" maxlength="10000" rows="3" required data-mention-input',
                      page)


class TestDailyLogLectureSeule(_Lot20):
    def test_lignes_d_un_projet_quitte_en_lecture_seule(self):
        hier = self.auj - datetime.timedelta(days=1)
        t = self.tache(self.p2, self.chef, intervenants=[self.inter])
        with self.db.get_cursor(user_id=self.inter) as cur:
            cur.execute("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, 2)",
                        (self.inter, hier, self.p2))
            cur.execute("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures) "
                        "VALUES (%s, %s, %s, %s, 1)", (self.inter, hier, self.p2, t))
        # Sa tâche est close aujourd'hui : plus d'action sur ce projet d'une
        # autre équipe, sauf ses heures sur cette tâche jusqu'à sa date de fin.
        self.sql("UPDATE tache SET etat = 'termine', date_fin = %s WHERE id = %s", (self.auj, t))
        self.login(self.inter)
        lignes = {(l["projet_id"], l["tache_id"]): l["modifiable"]
                  for l in self.client.get(f"/dailylog/api/jour/{hier.isoformat()}").get_json()["lignes"]}
        self.assertEqual(lignes, {(self.p2, None): False, (self.p2, t): True})


class TestPanneauEtFil(_Lot20):
    def test_donner_suite_absent_sur_projet_clos(self):
        post = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', "
                        "'Info') RETURNING id", (self.p1, self.chef))[0]["id"]
        self.login(self.chef)
        self.assertIn(f'data-parent-post-id="{post}"', self.texte(self.client.get(f"/projets/{self.p1}?fil=tout")))
        self.sql("UPDATE projet SET etat = 'termine' WHERE id = %s", (self.p1,))
        self.assertNotIn(f'data-parent-post-id="{post}"', self.texte(self.client.get(f"/projets/{self.p1}?fil=tout")))
        self.assertNotIn(f'data-parent-post-id="{post}"', self.texte(self.client.get("/accueil?fil=tout")))

    def test_personnes_qui_voient_un_projet(self):
        urbs = self.user("intervenant", equipe="URBS")
        self.login(self.chef)
        ids = self.client.get(f"/projets/{self.p1}/voient").get_json()["ids"]
        self.assertIn(self.inter, ids)
        self.assertNotIn(urbs, ids)
        self.login(urbs)
        self.assertEqual(self.client.get(f"/projets/{self.p1}/voient").status_code, 404)

    def test_lots_et_client_de_la_phase_liee(self):
        self.sql("UPDATE projet SET client = 'Cité Nord' WHERE id = %s", (self.p1,))
        self.sql("INSERT INTO projet_lot (projet_id, lot_code) VALUES (%s, 'CM'), (%s, 'GO')", (self.p1, self.p1))
        self.login(self.chef)
        d = self.client.get(f"/projets/code-propose?phase=APD&phase_liee_id={self.p1}").get_json()
        self.assertEqual((d["client"], d["lots"]), ("Cité Nord", ["CM", "GO"]))

    def test_lien_cliquable_dans_un_post(self):
        self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', "
                 "'Plans sur https://nas.midgard.tn/a?b=1&c=2.')", (self.p1, self.chef))
        self.login(self.inter)
        page = self.client.get(f"/projets/{self.p1}?fil=tout").get_data(as_text=True)
        self.assertIn('<a href="https://nas.midgard.tn/a?b=1&amp;c=2" class="lien-texte" target="_blank" '
                      'rel="noopener noreferrer">', page)

    def test_notification_ouvre_tout_jusqu_au_post(self):
        self.login(self.chef)
        self.client.post("/posts", data={"projet_id": str(self.p1), "type_code": "information", "contenu": "Info"})
        post = self.sql("SELECT max(id) AS id FROM post")[0]["id"]
        self.client.post(f"/posts/{post}/commenter", data={"contenu": "@Rim Inter regarde"})
        n = self.sql("SELECT id FROM notification WHERE utilisateur_id = %s ORDER BY id DESC LIMIT 1",
                     (self.inter,))[0]["id"]
        self.login(self.inter)
        self.client.set_cookie("kairos_fil_projet", "activite")
        r = self.client.post(f"/notifications/{n}/ouvrir")
        self.assertEqual(r.headers["Location"], f"/projets/{self.p1}?fil=tout&jusqua={post}#post-{post}")
        page = self.texte(self.client.get(r.headers["Location"]))
        self.assertIn(f'id="post-{post}"', page)
        self.assertIn('data-fil-categorie="tout"', page)


class TestDailyLogEtAccueil(_Lot20):
    def test_tache_bloquee_ce_jour_non_proposee(self):
        self.sql("UPDATE tache SET created_at = now() - interval '30 days' WHERE id = %s", (self.t1,))
        self.sql("UPDATE projet SET created_at = now() - interval '30 days'")
        self.sql("UPDATE utilisateur SET created_at = now() - interval '400 days'")
        self.sql("UPDATE tache SET etat = 'bloque', bloque_le = now() - interval '2 days', bloque_motif = 'x' "
                 "WHERE id = %s", (self.t1,))
        self.login(self.inter)
        jour = self.auj
        while jour.weekday() >= 5:
            jour -= datetime.timedelta(days=1)
        taches = [l["tache_id"] for l in
                  self.client.get(f"/dailylog/api/jour/{jour.isoformat()}").get_json()["proposees"]]
        self.assertNotIn(self.t1, taches)
        # Avant son blocage, elle était en cours ce jour-là : proposée.
        avant = self.auj - datetime.timedelta(days=5)
        while avant.weekday() >= 5:
            avant -= datetime.timedelta(days=1)
        self.sql("UPDATE tache SET bloque_le = %s::date + 1 WHERE id = %s", (avant, self.t1))
        taches = [l["tache_id"] for l in
                  self.client.get(f"/dailylog/api/jour/{avant.isoformat()}").get_json()["proposees"]]
        self.assertIn(self.t1, taches)

    def test_carte_daily_log_en_rouge_si_rien_aujourd_hui(self):
        self.login(self.inter)
        page = self.texte(self.client.get("/accueil"))
        rouge = 'class="acc-dl acc-dl-a-remplir"' in page
        self.assertEqual(rouge, self.auj.weekday() < 5 and "acc-dl-alerte" not in page)
        if self.auj.weekday() < 5:
            with self.db.get_cursor(user_id=self.inter) as cur:
                cur.execute("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, 1)",
                            (self.inter, self.auj, self.p1))
            self.assertNotIn("acc-dl-a-remplir", self.texte(self.client.get("/accueil")))

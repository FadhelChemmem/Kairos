"""Lot 24 sur un vrai PostgreSQL : contre-expertise des lots 21 à 23 et
demandes du gérant du 20/10 (lecture gardée par ceux qui ont vraiment
participé, dates de la tâche, blocages passés dans le Daily log, onglet du
fil par personne, notifications Windows)."""
import datetime
import json
import os
from unittest import mock

from tests_integration.test_lot20 import _Lot20, partiel, toasts

PARTIEL = {"X-Kairos-Partiel": "#x", "X-Requested-With": "XMLHttpRequest"}


def voit(test, projet_id, user_id):
    return test.compter("SELECT count(*) AS n FROM v_projet_visibilite WHERE projet_id = %s AND utilisateur_id = %s",
                        (projet_id, user_id)) == 1


class TestParticipationReelle(_Lot20):
    """Décision du gérant (Q1, Q3, MX-02) : lecture gardée seulement par qui
    a participé — y compris après un changement d'équipe."""

    def test_retire_sans_rien_faire_perd_la_lecture(self):
        x = self.user("intervenant", equipe="URBS")
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, x))
        self.login(self.chef)
        self.client.post(f"/projets/{self.p1}/intervenants/{x}/retirer")
        self.assertFalse(voit(self, self.p1, x))
        self.login(x)
        self.assertEqual(self.client.get(f"/projets/{self.p1}").status_code, 404)

    def test_ancien_co_chef_garde_la_lecture(self):
        x = self.user("chef_de_projet", equipe="URBS")
        self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, x))
        self.sql("DELETE FROM projet_co_chef WHERE projet_id = %s AND utilisateur_id = %s", (self.p1, x))
        self.assertTrue(voit(self, self.p1, x))

    def test_changement_d_equipe_apres_avoir_participe(self):
        mig = self.user("intervenant")              # MIDGARD, voit p1 par son équipe
        sans = self.user("intervenant")
        self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', 'x')",
                 (self.p1, mig))
        self.sql("UPDATE utilisateur SET equipe_code = 'URBS' WHERE id IN (%s, %s)", (mig, sans))
        self.assertTrue(voit(self, self.p1, mig))
        self.assertFalse(voit(self, self.p1, sans))
        self.login(mig)
        self.assertEqual(self.client.get(f"/projets/{self.p1}").status_code, 200)
        r = self.client.post("/posts", data={"projet_id": str(self.p1), "type_code": "information", "contenu": "y"})
        self.assertIn(r.status_code, (302, 403, 404, 409))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM post WHERE auteur_id = %s", (mig,)), 1)

    def test_reprise_0027(self):
        """La migration retire les anciens membres sans participation et
        reprend les anciens chefs remplacés hors de l'appli (MD-3)."""
        x = self.user("intervenant", equipe="URBS")
        ancien_chef = self.user("chef_de_projet", equipe="URBS")
        self.sql("INSERT INTO projet_ancien_membre (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, x))
        self.sql("SELECT set_config('app.current_user_id', %s, false)", (str(self.admin),))
        self.sql("UPDATE projet SET chef_projet_id = %s WHERE id = %s", (ancien_chef, self.p1))
        self.sql("UPDATE projet SET chef_projet_id = %s WHERE id = %s", (self.chef, self.p1))
        self.sql("DELETE FROM projet_ancien_membre WHERE utilisateur_id = %s", (ancien_chef,))
        self.rejouer_migrations_suivantes("0026_lot23_filtres_memorises")
        self.assertFalse(voit(self, self.p1, x))
        self.assertTrue(voit(self, self.p1, ancien_chef))


class TestTacheRouverteEtDateDeFin(_Lot20):
    def test_chef_intervenant_redevient_co_chef(self):
        """MX-01 : à la réouverture d'une ancienne tâche, un chef de projet
        qui en est intervenant redevient co-chef aussitôt."""
        x = self.user("chef_de_projet", equipe="URBS")
        t = self.tache(self.p1, self.chef, etat="termine", intervenants=[x])
        self.sql("DELETE FROM projet_co_chef WHERE projet_id = %s AND utilisateur_id = %s", (self.p1, x))
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p1}/taches/{t}/etat", data={"etat": "en_cours"}, headers=partiel("#x"))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet_co_chef WHERE projet_id = %s AND "
                                      "utilisateur_id = %s", (self.p1, x)), 1)

    def test_tache_close_a_toujours_une_date_de_fin(self):
        """NB7 / SB-02 / HD-09 : même chargée par un script sans date."""
        t = self.sql("INSERT INTO tache (projet_id, titre, created_by, etat, created_at, updated_at, date_fin) "
                     "VALUES (%s, 'Reprise', %s, 'abandonne', now() - interval '30 days', "
                     "now() - interval '20 days', NULL) RETURNING id, date_fin", (self.p1, self.chef))[0]
        self.assertEqual(t["date_fin"], self.auj - datetime.timedelta(days=20))


class TestLectureSeuleAuServeur(_Lot20):
    def setUp(self):
        super().setUp()
        self.x = self.user("intervenant", equipe="URBS")
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, self.x))
        self.jour = self.auj - datetime.timedelta(days=2)
        self.sql("INSERT INTO dailylog_entree (utilisateur_id, projet_id, date, heures) VALUES (%s, %s, %s, 2)",
                 (self.x, self.p1, self.jour))
        self.sql("INSERT INTO dailylog_jour (utilisateur_id, date, version) VALUES (%s, %s, 1)", (self.x, self.jour))
        self.login(self.chef)
        self.client.post(f"/projets/{self.p1}/intervenants/{self.x}/retirer")
        self.login(self.x)

    def test_ni_baisse_ni_suppression(self):
        """HD-01 : la règle de l'écran vaut au serveur."""
        url = f"/dailylog/api/jour/{self.jour.isoformat()}"
        self.assertFalse(self.client.get(url).get_json()["lignes"][0]["modifiable"])
        r = self.client.put(url, json={"version": 1, "lignes": [{"projet_id": self.p1, "minutes": 60}]})
        self.assertEqual(r.status_code, 422, r.get_data(as_text=True)[:300])
        p2 = self.projet(self.chef, equipe="URBS")
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s)", (p2, self.x))
        r = self.client.put(url, json={"version": 1, "lignes": [{"projet_id": p2, "minutes": 60}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        lignes = self.sql("SELECT projet_id, heures FROM dailylog_entree WHERE utilisateur_id = %s ORDER BY projet_id",
                          (self.x,))
        self.assertEqual([(l["projet_id"], float(l["heures"])) for l in lignes], [(self.p1, 2.0), (p2, 1.0)])

    def test_api_taches_d_un_projet_en_lecture(self):
        """MX-04 : comme la recherche de projets."""
        r = self.client.get(f"/dailylog/api/taches?projet={self.p1}")
        self.assertEqual(r.status_code, 404)

    def test_notification_sans_code_de_projet_invisible(self):
        """MX-03 : ni extrait ni code du projet qu'on ne voit plus."""
        self.sql("DELETE FROM dailylog_entree WHERE utilisateur_id = %s", (self.x,))
        self.sql("DELETE FROM projet_ancien_membre WHERE utilisateur_id = %s", (self.x,))
        self.sql("INSERT INTO notification (utilisateur_id, categorie, message, projet_id) "
                 "VALUES (%s, 'projet', 'Secret : « code 1234 »', %s)", (self.x, self.p1))
        code = self.sql("SELECT code FROM projet WHERE id = %s", (self.p1,))[0]["code"]
        page = self.texte(self.client.get("/notifications"))
        self.assertNotIn(code, page)
        self.assertNotIn("1234", page)


class TestEpingle(_Lot20):
    def setUp(self):
        super().setUp()
        self.info = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES "
                             "(%s, %s, 'information', 'Consigne') RETURNING id", (self.p1, self.chef))[0]["id"]
        self.login(self.chef)
        self.client.post(f"/posts/{self.info}/epingler", headers=partiel("#fil-epingle"))

    def test_annuler_la_suppression_vide_l_encadre(self):
        """EC-01 : le post revient sans épingle, dans la liste, jamais deux fois."""
        r = self.client.post(f"/posts/{self.info}/supprimer", headers={**partiel(f"#post-{self.info}"),
                                                                       "Referer": f"/projets/{self.p1}?fil=tout"})
        self.assertEqual(r.status_code, 200)
        action = toasts(r)[0]["action"]
        r = self.client.post(action["url"], data=action["donnees"],
                             headers={**partiel(action["cible"]), "Referer": f"/projets/{self.p1}?fil=tout"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        html = r.get_data(as_text=True)
        encadre = html[html.index('id="fil-epingle"'):html.index('id="fil-posts"')]
        self.assertIn("data-partiel-oob", encadre)
        self.assertNotIn(f'id="post-{self.info}"', encadre)
        self.assertIn(f'id="fil-item-{self.info}"', html[html.index('id="fil-posts"'):])

    def test_categorie_changee_avec_l_encadre_a_jour(self):
        """EC-02 et EC-03 : l'encadré suit la liste ; jamais le même post deux fois."""
        self.sql("UPDATE post SET epingle_le = NULL WHERE id = %s", (self.info,))
        r = self.client.get(f"/projets/{self.p1}?fil=tout", headers=partiel("#fil-posts"))
        html = r.get_data(as_text=True)
        self.assertIn('id="fil-epingle"', html)
        self.assertEqual(html.count(f'id="post-{self.info}"'), 1)
        from app.repositories import posts as posts_repo
        self.sql("UPDATE post SET epingle_le = now() WHERE id = %s", (self.info,))
        ids = [p["id"] for p in posts_repo.list_feed_projet(self.p1, self.chef, exclure=self.info)]
        self.assertNotIn(self.info, ids)

    def test_gestes_sans_effet_et_post_supprime(self):
        """EC-04, EC-06 : messages justes."""
        r = self.client.post(f"/posts/{self.info}/desepingler", headers=partiel("#fil-epingle"))
        self.assertEqual(toasts(r)[0]["texte"], "Post désépinglé.")
        r = self.client.post(f"/posts/{self.info}/desepingler", headers=partiel("#fil-epingle"))
        self.assertEqual(toasts(r)[0], {"type": "info", "texte": "Ce post n’était plus épinglé."})
        self.sql("UPDATE post SET supprime_le = now() WHERE id = %s", (self.info,))
        from app.repositories import posts as posts_repo
        with self.assertRaises(posts_repo.EpinglageRefuse):
            posts_repo.epingler(self.info, self.p1, self.chef)
        r = self.client.post(f"/posts/{self.info}/supprimer", headers=partiel(f"#post-{self.info}"))
        self.assertIn(r.status_code, (200, 404))

    def test_suppression_par_un_co_chef_sur_projet_clos(self):
        """EC-05 : sous le verrou du projet, un projet clos refuse."""
        from app.repositories import posts as posts_repo
        from app.repositories import taches as taches_repo
        self.sql("UPDATE projet SET etat = 'termine', date_cloture = current_date WHERE id = %s", (self.p1,))
        with self.assertRaises(taches_repo.ProjetClos):
            posts_repo.supprimer_post(self.info, self.chef, projet_ouvert_requis=True)
        self.assertIsNotNone(posts_repo.supprimer_post(self.info, self.admin))


class TestFiltresLot24(_Lot20):
    def prefs(self, uid):
        lignes = self.sql("SELECT filtres FROM utilisateur_preference WHERE utilisateur_id = %s", (uid,))
        return lignes[0]["filtres"] if lignes else {}

    def test_equipe_tous_oublie_le_choix(self):
        """FI-01 : toutes les listes sur « Tous » est un choix."""
        self.login(self.admin)
        self.client.get("/utilisateurs?filtres_actifs=1&role=client", headers=PARTIEL)
        self.assertEqual(self.prefs(self.admin)["equipe"], "filtres_actifs=1&role=client")
        self.client.get("/utilisateurs?filtres_actifs=1&q=&equipe_code=&role=&actif=", headers=PARTIEL)
        self.assertNotIn("equipe", self.prefs(self.admin))
        self.assertEqual(self.client.get("/utilisateurs").status_code, 200)

    def test_retour_du_navigateur_n_ecrit_rien(self):
        """Q13/Q14, FI-09 : Retour / Avancer ne sont pas des gestes."""
        self.login(self.admin)
        self.client.get("/utilisateurs?filtres_actifs=1&role=rh", headers=PARTIEL)
        rejoue = {**PARTIEL, "X-Kairos-Historique": "1"}
        self.client.get("/utilisateurs?filtres_actifs=1&role=client", headers=rejoue)
        self.client.get("/utilisateurs?defaut=1", headers=rejoue)
        self.assertEqual(self.prefs(self.admin)["equipe"], "filtres_actifs=1&role=rh")

    def test_valeurs_hors_liste_et_trop_longues(self):
        """FI-06, FI-07."""
        self.login(self.admin)
        self.client.get("/utilisateurs?filtres_actifs=1&equipe_code=ZZZ", headers=PARTIEL)
        self.assertNotIn("equipe_code=ZZZ", self.prefs(self.admin).get("equipe", ""))
        self.sql("INSERT INTO utilisateur_preference (utilisateur_id, filtres) VALUES (%s, %s) "
                 "ON CONFLICT (utilisateur_id) DO UPDATE SET filtres = EXCLUDED.filtres",
                 (self.admin, json.dumps({"equipe": "equipe_code=" + "A" * 5000, "journal": "table=%00"})))
        self.assertEqual(self.client.get("/utilisateurs").status_code, 200)
        r = self.client.get("/admin/journal")
        self.assertTrue(r.status_code == 200 or "%00" not in r.headers.get("Location", ""))
        with self.assertRaises(Exception):
            self.sql("UPDATE utilisateur_preference SET filtres = '[]' WHERE utilisateur_id = %s", (self.admin,))

    def test_journal_page_suivante_sans_redirection(self):
        """FI-05."""
        self.login(self.admin)
        self.client.get("/admin/journal?filtres_actifs=1&table=projet", headers=PARTIEL)
        r = self.client.get("/admin/journal?avant=2026-10-20T09:24:58.641549%2B01:00_43&n=100&jour=2026-10-20")
        self.assertEqual(r.status_code, 200)

    def test_pas_d_ecriture_sans_changement_et_export(self):
        """FI-08, FI-09."""
        self.login(self.chef)
        self.client.get("/projets?filtres_actifs=1&etat=termine", headers=PARTIEL)
        avant = self.sql("SELECT updated_at FROM utilisateur_preference WHERE utilisateur_id = %s",
                         (self.chef,))[0]["updated_at"]
        self.client.get("/projets?filtres_actifs=1&etat=termine&q=P", headers=PARTIEL)
        self.client.get("/projets/export.xlsx?defaut=1")
        apres = self.sql("SELECT updated_at FROM utilisateur_preference WHERE utilisateur_id = %s",
                         (self.chef,))[0]["updated_at"]
        self.assertEqual(avant, apres)
        self.assertEqual(self.prefs(self.chef)["projets"], "filtres_actifs=1&etat=termine")

    def test_chef_memorise_sans_projet_et_lot_inconnu(self):
        """FI-10, Q7."""
        bob = self.user("chef_de_projet")
        self.sql("UPDATE utilisateur SET prenom = 'Bob', nom = 'Chefsansprojet' WHERE id = %s", (bob,))
        self.login(self.admin)
        page = self.texte(self.client.get(f"/projets?filtres_actifs=1&etat=en_cours&chef_id={bob}&lot_contient=SB"))
        self.assertIn(f'<option value="{bob}" selected', page)
        self.assertNotIn("lot_contient=SB", page)


class TestOngletDuFilParPersonne(_Lot20):
    def test_onglet_retenu_par_personne(self):
        """Décision du gérant (Q3) : retenu en base, pas dans le navigateur."""
        self.login(self.inter)
        self.client.get("/accueil?fil=activite", headers=partiel("#fil-posts"))
        self.assertEqual(self.sql("SELECT filtres->>'fil_accueil' AS f FROM utilisateur_preference "
                                  "WHERE utilisateur_id = %s", (self.inter,))[0]["f"], "activite")
        page = self.texte(self.client.get("/accueil"))
        self.assertRegex(page, r'data-fil="activite"[^>]*aria-current="(page|true)"|aria-current="(page|true)"[^>]*data-fil="activite"')
        # Voir comme : l'onglet de la personne, rien d'écrit.
        self.entrer(self.inter, mode="voir")
        self.client.get("/accueil?fil=tout", headers=partiel("#fil-posts"))
        self.assertEqual(self.sql("SELECT filtres->>'fil_accueil' AS f FROM utilisateur_preference "
                                  "WHERE utilisateur_id = %s", (self.inter,))[0]["f"], "activite")


class TestBlocagesPassesDansLeDailyLog(_Lot20):
    def test_jours_bloques_non_proposes_puis_proposes(self):
        """Décision du gérant (B2) : un jour où la tâche était bloquée, elle
        n'est pas proposée — même débloquée depuis ; débloquée dans la
        journée, elle l'est."""
        from app.repositories import dailylog as dl
        self.sql("UPDATE tache SET created_at = now() - interval '30 days' WHERE id = %s", (self.t1,))
        self.sql("UPDATE projet SET created_at = now() - interval '30 days' WHERE id = %s", (self.p1,))
        j = lambda n: self.auj - datetime.timedelta(days=n)  # noqa: E731
        for evenement, jours in (("blocage_tache", 6), ("deblocage_tache", 3)):
            self.sql("INSERT INTO post (projet_id, tache_id, auteur_id, type_code, contenu, evenement, created_at) "
                     "VALUES (%s, %s, %s, 'information', 'x', %s, %s::date + time '10:00')",
                     (self.p1, self.t1, self.chef, evenement, j(jours)))
        user = self.sql("SELECT * FROM utilisateur WHERE id = %s", (self.inter,))[0]

        def propose(n):
            return any(l["tache_id"] == self.t1 for l in dl.lignes_proposees(user, j(n)))

        self.assertTrue(propose(7))
        self.assertFalse(propose(6))
        self.assertFalse(propose(4))
        self.assertTrue(propose(3))
        self.assertTrue(propose(1))
        # Toujours sélectionnable à la main.
        self.login(self.inter)
        r = self.client.get(f"/dailylog/api/taches?projet={self.p1}&date={j(4).isoformat()}")
        self.assertIn(self.t1, [t["tache_id"] for t in r.get_json()["taches"]])


class TestDatesDeLaTache(_Lot20):
    def test_debut_fin_et_blocage_dans_le_panneau(self):
        self.sql("UPDATE tache SET created_at = %s::date + time '09:00' WHERE id = %s",
                 (self.auj - datetime.timedelta(days=12), self.t1))
        self.login(self.inter)
        url = f"/projets/{self.p1}/taches/{self.t1}/fenetre"
        page = self.visible(self.client.get(url))
        from app.utils import date_courte
        debut = date_courte(self.auj - datetime.timedelta(days=12))
        self.assertIn(f"Début : {debut}", page)
        self.sql("UPDATE tache SET etat = 'bloque', bloque_le = %s::date + time '08:00' WHERE id = %s",
                 (self.auj - datetime.timedelta(days=2), self.t1))
        self.assertIn(f"Bloquée depuis le {date_courte(self.auj - datetime.timedelta(days=2))}",
                      self.visible(self.client.get(url)))
        self.sql("UPDATE tache SET etat = 'termine', date_fin = %s WHERE id = %s", (self.auj, self.t1))
        self.assertIn(f"Fin : {date_courte(self.auj)} (terminée)", self.visible(self.client.get(url)))


class TestModeTestLot24(_Lot20):
    MODE_TEST = True

    def test_date_sans_heure_ancree_au_moment_pose(self):
        """HD-04 : la date posée sans heure retient l'instant réel du geste."""
        self.login(self.admin)
        self.client.post("/admin/date-simulee", data={"date": (self.auj - datetime.timedelta(days=3)).isoformat()})
        with self.client.session_transaction() as s:
            self.assertIsInstance(s["date_simulee"].get("pose_le"), float)

    def test_jamais_date_avant_la_creation(self):
        """HD-06 : blocage et commentaire sous une date simulée passée."""
        self.login(self.admin)
        self.entrer(self.chef, mode="agir")
        self.client.post("/admin/date-simulee", data={"date": (self.auj - datetime.timedelta(days=5)).isoformat(),
                                                      "heure": "10:00"})
        self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Visa"},
                         headers=partiel("#x"))
        t = self.sql("SELECT created_at, bloque_le FROM tache WHERE id = %s", (self.t1,))[0]
        self.assertGreaterEqual(t["bloque_le"], t["created_at"])

    def test_deux_annuler_croises_ne_laissent_aucun_post(self):
        """R17 : l'état du projet revient, son fil aussi."""
        t2 = self.tache(self.p1, self.chef, intervenants=[self.inter])
        self.login(self.inter)
        ra = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "M1"},
                              headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.login(self.chef)
        rb = self.client.post(f"/projets/{self.p1}/taches/{t2}/etat", data={"etat": "bloque", "motif": "M2"},
                              headers=partiel(f"#tache-fenetre-{t2}"))
        self.login(self.inter)
        self.assertEqual(self.annuler(ra).status_code, 200)
        self.login(self.chef)
        self.assertEqual(self.annuler(rb).status_code, 200)
        self.assertEqual(self.etat_projet(self.p1), "en_cours")
        self.assertEqual(self.compter("SELECT count(*) AS n FROM post WHERE projet_id = %s AND evenement = 'etat_projet'",
                                      (self.p1,)), 0)

    def test_fenetre_informations_sans_etat_affiche(self):
        """SB-01 : état affiché vide ou invalide, un passage clos → ouvert est refusé."""
        self.sql("UPDATE projet SET etat = 'termine', date_cloture = current_date WHERE id = %s", (self.p1,))
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p1}/informations", data={"nom": "Renommé", "etat": "en_cours", "etat_initial": "xx"},
                             headers=partiel("#informations-form"))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.etat_projet(self.p1), "termine")


class TestMentionRetiree(_Lot20):
    def test_mention_effacee_du_texte(self):
        """Q10 : un « @Prénom Nom » effacé du texte retire la mention ; une
        personne taguée par les puces, hors du texte, reste."""
        autre = self.user("intervenant")
        self.sql("UPDATE utilisateur SET prenom = 'Sami', nom = 'Puce' WHERE id = %s", (autre,))
        post = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', "
                        "'Bonjour @Rim Inter') RETURNING id", (self.p1, self.chef))[0]["id"]
        self.sql("INSERT INTO post_mention (post_id, utilisateur_id) VALUES (%s, %s), (%s, %s)",
                 (post, self.inter, post, autre))
        self.login(self.chef)
        r = self.client.post(f"/posts/{post}/modifier", data={"contenu": "Bonjour à tous"}, headers=partiel(f"#post-{post}"))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual([l["utilisateur_id"] for l in self.sql("SELECT utilisateur_id FROM post_mention WHERE post_id = %s",
                                                                 (post,))], [autre])


class TestCarteDailyLog(_Lot20):
    MODE_TEST = True

    def test_week_end_et_avant_l_arrivee(self):
        """HD-11 (A1), HD-12."""
        samedi = self.auj - datetime.timedelta(days=(self.auj.weekday() - 5) % 7 or 7)
        self.entrer(self.inter, mode="agir")
        self.client.post("/admin/date-simulee", data={"date": samedi.isoformat(), "heure": "10:00"})
        page = self.texte(self.client.get("/accueil"))
        self.assertNotIn("acc-dl-a-remplir", page)
        self.assertNotIn("à remplir aujourd’hui", page)
        lundi = samedi - datetime.timedelta(days=5)
        self.sql("UPDATE utilisateur SET date_embauche = %s WHERE id = %s", (lundi + datetime.timedelta(days=1), self.inter))
        self.client.post("/admin/date-simulee", data={"date": lundi.isoformat(), "heure": "10:00"})
        page = self.texte(self.client.get("/accueil"))
        self.assertNotIn("acc-dl-a-remplir", page)


class TestNotificationsWindows(_Lot20):
    MODE_TEST = True

    def setUp(self):
        super().setUp()
        from app import push
        self.push = push
        cles = push.generer_cles()
        self.env = mock.patch.dict(os.environ, {"VAPID_PRIVATE_KEY": cles["VAPID_PRIVATE_KEY"],
                                                "VAPID_PUBLIC_KEY": cles["VAPID_PUBLIC_KEY"]})
        self.env.start()
        self.app.config["PUSH_DELAI"] = 0
        push._derniers_essais.clear()
        self.envois = []
        self.envoyer = mock.patch("app.push.envoyer", side_effect=lambda a, m, **k: self.envois.append((a, m)) or 201)
        self.envoyer.start()

    def tearDown(self):
        self.envoyer.stop()
        self.env.stop()
        super().tearDown()

    def cle_navigateur(self):
        """Clé publique P-256 valide (lot 25, PU-03 : un point hors courbe est
        refusé)."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        point = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return self.push.b64url(point)

    def abonner(self, uid, endpoint="https://fcm.googleapis.com/fcm/send/abc", cle=None, auth=b"a" * 16):
        self.login(uid)
        return self.client.post("/push/abonnement", json={"endpoint": endpoint,
                                                          "keys": {"p256dh": cle or self.cle_navigateur(),
                                                                   "auth": self.push.b64url(auth)}})

    def test_manifeste_et_service_worker(self):
        m = self.client.get("/manifest.webmanifest")
        self.assertEqual(m.status_code, 200)
        d = json.loads(m.get_data(as_text=True))
        self.assertEqual((d["name"], d["display"], d["start_url"]), ("Kairos", "standalone", "/accueil"))
        self.assertEqual({i["sizes"] for i in d["icons"]}, {"192x192", "512x512"})
        sw = self.client.get("/sw.js")
        self.assertEqual(sw.headers["Service-Worker-Allowed"], "/")
        self.assertNotIn("immutable", sw.headers.get("Cache-Control", ""))
        self.assertIn("worker-src 'self'", sw.headers["Content-Security-Policy"])

    def test_abonnement_valide_ou_refuse(self):
        self.assertEqual(self.abonner(self.inter).status_code, 200)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM push_abonnement WHERE utilisateur_id = %s",
                                      (self.inter,)), 1)
        self.assertEqual(self.abonner(self.inter, "http://pirate.example/x").status_code, 400)
        self.login(self.inter)
        r = self.client.post("/push/abonnement", json={"endpoint": "https://fcm.googleapis.com/x",
                                                       "keys": {"p256dh": "court", "auth": "x"}})
        self.assertEqual(r.status_code, 400)
        # Agir comme : le navigateur de l'Admin ne s'abonne jamais pour un autre.
        self.entrer(self.inter, mode="agir")
        cle = self.cle_navigateur()
        r = self.client.post("/push/abonnement", json={"endpoint": "https://fcm.googleapis.com/fcm/send/admin",
                                                       "keys": {"p256dh": cle, "auth": self.push.b64url(b"a" * 16)}})
        self.assertEqual(r.status_code, 403)

    def test_notification_poussee_sauf_en_mode_test(self):
        from app.repositories import notifications as notifications_repo
        self.abonner(self.inter)
        with self.app.test_request_context("/"):
            from flask import g
            g.user = None
            notifications_repo.creer(self.inter, "projet", "Ali vous a mentionné dans un post.", projet_id=self.p1)
        self.assertEqual(len(self.envois), 1)
        abonnement, message = self.envois[0]
        self.assertEqual(abonnement["endpoint"], "https://fcm.googleapis.com/fcm/send/abc")
        self.assertTrue(message["url"].startswith("/notifications?ouvrir="))
        # Catégorie écartée par la personne : rien.
        self.sql("INSERT INTO utilisateur_preference (utilisateur_id, push_categories) VALUES (%s, ARRAY['rh_info']) "
                 "ON CONFLICT (utilisateur_id) DO UPDATE SET push_categories = EXCLUDED.push_categories", (self.inter,))
        with self.app.test_request_context("/"):
            notifications_repo.creer(self.inter, "projet", "Autre", projet_id=self.p1)
        self.assertEqual(len(self.envois), 1)
        # Action faite en « Agir comme » : rien.
        self.sql("UPDATE utilisateur_preference SET push_categories = NULL WHERE utilisateur_id = %s", (self.inter,))
        self.entrer(self.chef, mode="agir")
        self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "x"},
                         headers=partiel("#x"))
        self.assertEqual(len(self.envois), 1)

    def test_essai_categories_et_ouverture(self):
        self.abonner(self.inter)
        r = self.client.post("/push/essai")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.envois), 1)
        r = self.client.post("/push/categories", data={"categories": ["rh_info"]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.sql("SELECT push_categories FROM utilisateur_preference WHERE utilisateur_id = %s",
                                  (self.inter,))[0]["push_categories"], ["rh_info"])
        n = self.sql("INSERT INTO notification (utilisateur_id, categorie, message) VALUES (%s, 'rh_info', 'x') "
                     "RETURNING id", (self.inter,))[0]["id"]
        page = self.texte(self.client.get(f"/notifications?ouvrir={n}"))
        self.assertIn(f'action="/notifications/{n}/ouvrir"', page)
        self.assertIn("data-auto-envoi", page)
        autre = self.sql("INSERT INTO notification (utilisateur_id, categorie, message) VALUES (%s, 'rh_info', 'x') "
                         "RETURNING id", (self.chef,))[0]["id"]
        self.assertNotIn("data-auto-envoi", self.texte(self.client.get(f"/notifications?ouvrir={autre}")))
        r = self.client.post("/push/desabonnement", json={"endpoint": "https://fcm.googleapis.com/fcm/send/abc"})
        self.assertEqual(self.compter("SELECT count(*) AS n FROM push_abonnement"), 0)


class TestCorrectifsEprouves(_Lot20):
    """Contre-expertise SR-R01 à SR-R08 : correctifs des lots 21 à 23 que
    les mutants laissaient sans test."""
    MODE_TEST = True

    def test_horodatages_en_date_simulee_passee(self):
        """H5 (updated_at), H11 (modifie_le), H14 (« Aujourd’hui »)."""
        jour = self.auj - datetime.timedelta(days=6)
        self.sql("UPDATE tache SET created_at = now() - interval '30 days' WHERE id = %s", (self.t1,))
        post = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu, created_at) VALUES "
                        "(%s, %s, 'information', 'Ancien', now() - interval '30 days') RETURNING id",
                        (self.p1, self.chef))[0]["id"]
        self.entrer(self.chef, mode="agir")
        self.client.post("/admin/date-simulee", data={"date": jour.isoformat(), "heure": "10:00"})
        self.client.post(f"/projets/{self.p1}/taches/{self.t1}/titre", data={"titre": "Renommée"}, headers=partiel("#x"))
        self.client.post(f"/posts/{post}/modifier", data={"contenu": "Corrigé"}, headers=partiel(f"#post-{post}"))
        jour_de = lambda v: v.astimezone(datetime.timezone(datetime.timedelta(hours=1))).date()  # noqa: E731
        self.assertEqual(jour_de(self.sql("SELECT updated_at FROM tache WHERE id = %s", (self.t1,))[0]["updated_at"]), jour)
        self.assertEqual(jour_de(self.sql("SELECT modifie_le FROM post WHERE id = %s", (post,))[0]["modifie_le"]), jour)
        self.sql("INSERT INTO notification (utilisateur_id, categorie, message, created_at) "
                 "VALUES (%s, 'projet', 'Du jour simulé', %s::date + time '09:00')", (self.chef, jour))
        page = self.visible(self.client.get("/notifications"))
        self.assertLess(page.index("Aujourd’hui"), page.index("Du jour simulé"))

    def test_fil_vu_jamais_dans_le_futur_reel(self):
        """H9."""
        from app.repositories import posts as posts_repo
        futur = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3)
        posts_repo.marquer_fil_vu(self.chef, ["echanges"], instant=futur)
        vu = self.sql("SELECT vu_le FROM utilisateur_fil_vu WHERE utilisateur_id = %s", (self.chef,))[0]["vu_le"]
        self.assertLessEqual(vu, datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=5))

    def test_rejoindre_un_projet_clos(self):
        """V3 : add_co_chef sous le verrou du projet."""
        from app.repositories import projets as projets_repo
        from app.repositories import taches as taches_repo
        sami = self.user("chef_de_projet")
        self.sql("UPDATE projet SET etat = 'termine', date_cloture = current_date WHERE id = %s", (self.p1,))
        with self.assertRaises(taches_repo.ProjetClos):
            projets_repo.add_co_chef(self.p1, sami, sami)

    def test_me_concernant_par_l_adresse_seulement(self):
        """F6 (GET : jamais le Referer), F8 (page suivante gardée)."""
        self.login(self.inter)
        for i in range(35):
            self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', %s)",
                     (self.p1, self.inter, f"Mien {i}"))
        self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', "
                 "'Du chef seul')", (self.p1, self.chef))
        page = self.texte(self.client.get(f"/projets/{self.p1}?fil=tout",
                                          headers={"Referer": f"http://localhost/projets/{self.p1}?moi=1"}))
        self.assertIn("Du chef seul", page)
        page = self.texte(self.client.get(f"/projets/{self.p1}?fil=tout&moi=1"))
        self.assertNotIn("Du chef seul", page)
        self.assertRegex(page, r'href="[^"]*moi=1[^"]*"[^>]*class="[^"]*fil-plus|class="[^"]*fil-plus[^"]*"[^>]*href="[^"]*moi=1')

    def test_journal_redirige_vers_le_choix(self):
        """M9 : la redirection elle-même (302 et adresse)."""
        self.login(self.admin)
        self.client.get("/admin/journal?filtres_actifs=1&action=INSERT", headers=PARTIEL)
        r = self.client.get("/admin/journal?date_debut=2026-10-01")
        self.assertEqual(r.status_code, 302)
        self.assertIn("action=INSERT", r.headers["Location"])
        self.assertIn("date_debut=2026-10-01", r.headers["Location"])

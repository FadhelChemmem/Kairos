"""Lot 20 sur un vrai PostgreSQL : corrections du test Chrome et de la revue
Claude Code du 19/10/2026, avec les décisions du gérant (retiré en lecture
seule, date simulée partout, plus de pièce jointe sur une tâche, numéro
d'affaire APS → APD, verrou de 14 jours pour le chef aussi)."""
import datetime
import json
from urllib.parse import unquote

from tests_integration.test_lot12 import _Base


def partiel(cible):
    return {"X-Kairos-Partiel": cible, "X-Requested-With": "XMLHttpRequest"}


def toasts(r):
    return json.loads(unquote(r.headers.get("X-Kairos-Toasts", "%5B%5D")))


class _Lot20(_Base):
    def compter_lignes(self):
        return {t: self.compter(f"SELECT count(*) AS n FROM {t}")
                for t in ("post", "post_commentaire", "post_reaction", "tache_intervenant", "projet_intervenant",
                          "projet_co_chef", "dailylog_entree", "tache_piece_jointe")}

    def etat_tache(self, tid):
        return self.sql("SELECT etat FROM tache WHERE id = %s", (tid,))[0]["etat"]

    def etat_projet(self, pid):
        return self.sql("SELECT etat FROM projet WHERE id = %s", (pid,))[0]["etat"]

    def annuler(self, r):
        action = toasts(r)[0]["action"]
        return self.client.post(action["url"], data=action["donnees"], headers=partiel(action["cible"]))


class TestRetireEnLectureSeule(_Lot20):
    """Revue n° 2 (décision du gérant) : la personne retirée garde la
    lecture, n'agit plus (ni « Rejoindre »), mais peut reprendre ses
    anciens écrits."""

    def setUp(self):
        super().setUp()
        self.autre = self.user("chef_de_projet", equipe="URBS")
        self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, self.autre))
        self.sql("INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (%s, %s)", (self.t1, self.autre))
        self.close = self.tache(self.p1, self.chef, etat="termine", intervenants=[self.autre])
        self.post = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', "
                             "'Du chef') RETURNING id", (self.p1, self.chef))[0]["id"]
        self.sien = self.sql("INSERT INTO post_commentaire (post_id, auteur_id, contenu) VALUES (%s, %s, 'Avant') "
                             "RETURNING id", (self.post, self.autre))[0]["id"]
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p1}/intervenants/{self.autre}/retirer")
        self.assertIn(r.status_code, (200, 302))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet_co_chef WHERE utilisateur_id = %s",
                                      (self.autre,)), 0)

    def test_lecture_gardee(self):
        self.login(self.autre)
        r = self.client.get(f"/projets/{self.p1}")
        self.assertEqual(r.status_code, 200)
        page = self.texte(r)
        self.assertNotIn(f'action="/projets/{self.p1}/rejoindre"', page)

    def test_aucune_action(self):
        self.login(self.autre)
        avant = self.compter_lignes()
        cas = [
            ("/posts", {"projet_id": str(self.p1), "type_code": "information", "contenu": "Encore là"}),
            (f"/posts/{self.post}/commenter", {"contenu": "Un mot"}),
            (f"/posts/{self.post}/reagir", {"reaction_code": "pouce"}),
            (f"/projets/{self.p1}/taches/{self.close}/etat", {"etat": "en_cours"}),
            (f"/projets/{self.p1}/taches/{self.t1}/etat", {"etat": "bloque", "motif": "x"}),
            (f"/projets/{self.p1}/taches/{self.close}/titre", {"titre": "Renommée"}),
            (f"/projets/{self.p1}/rejoindre", {}),
            (f"/projets/{self.p1}/taches/{self.t1}/rejoindre", {}),
            (f"/projets/{self.p1}/taches", {"titre": "Nouvelle"}),
        ]
        for url, data in cas:
            with self.subTest(url=url):
                r = self.client.post(url, data=data, headers=partiel("#x"))
                self.assertIn(r.status_code, (403, 404, 409, 422), r.get_data(as_text=True)[:300])
        self.assertEqual(self.compter_lignes(), avant)
        self.assertEqual(self.etat_tache(self.close), "termine")
        self.assertEqual(self.etat_tache(self.t1), "en_cours")
        # Daily log : pas d'heures sur ce projet.
        r = self.client.put(f"/dailylog/api/jour/{self.auj.isoformat()}",
                            json={"version": 0, "lignes": [{"projet_id": self.p1, "tache_id": None, "minutes": 60}]})
        self.assertGreaterEqual(r.status_code, 400)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM dailylog_entree"), 0)

    def test_ses_anciens_commentaires_restent_modifiables(self):
        self.login(self.autre)
        r = self.client.post(f"/posts/commentaires/{self.sien}/modifier", data={"contenu": "Corrigé"},
                             headers=partiel("#x"))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.sql("SELECT contenu FROM post_commentaire WHERE id = %s", (self.sien,))[0]["contenu"],
                         "Corrigé")

    def test_rajoute_par_le_chef_il_agit_de_nouveau(self):
        self.login(self.chef)
        self.client.post(f"/projets/{self.p1}/intervenants", data={"utilisateur_id": str(self.autre)})
        self.login(self.autre)
        r = self.client.post("/posts", data={"projet_id": str(self.p1), "type_code": "information", "contenu": "Retour"},
                             headers=partiel("#x"))
        self.assertLess(r.status_code, 400, r.get_data(as_text=True)[:300])


class TestAnnulerExact(_Lot20):
    """Revue n° 3, 12b, N2, N3 : « Annuler » rend exactement l'état d'avant,
    et jamais par-dessus le geste d'une autre personne."""

    def test_cloture_d_une_tache_bloquee_puis_annuler(self):
        self.login(self.inter)
        self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Visa BC"},
                         headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(self.etat_projet(self.p1), "bloque")
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/cloturer", data={"type_code": "envoi"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(self.etat_tache(self.t1), "termine")
        r = self.annuler(r)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        ligne = self.sql("SELECT etat, bloque_motif, date_fin FROM tache WHERE id = %s", (self.t1,))[0]
        self.assertEqual((ligne["etat"], ligne["bloque_motif"], ligne["date_fin"]), ("bloque", "Visa BC", None))
        self.assertEqual(self.etat_projet(self.p1), "bloque")

    def test_annuler_un_blocage_efface_le_motif(self):
        self.login(self.inter)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Plans"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.annuler(r)
        ligne = self.sql("SELECT etat, bloque_motif, bloque_le, bloque_par FROM tache WHERE id = %s", (self.t1,))[0]
        self.assertEqual(dict(ligne), {"etat": "en_cours", "bloque_motif": None, "bloque_le": None, "bloque_par": None})

    def test_reouverture_d_une_tache_abandonnee_puis_annuler_garde_la_date_de_fin(self):
        fin = self.auj - datetime.timedelta(days=3)
        self.sql("UPDATE tache SET etat = 'abandonne', date_fin = %s WHERE id = %s", (fin, self.t1))
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "en_cours"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(self.etat_tache(self.t1), "en_cours")
        self.annuler(r)
        ligne = self.sql("SELECT etat, date_fin FROM tache WHERE id = %s", (self.t1,))[0]
        self.assertEqual((ligne["etat"], ligne["date_fin"]), ("abandonne", fin))

    def test_annuler_refuse_apres_le_geste_d_une_autre_personne(self):
        self.login(self.inter)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Plans"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.login(self.chef)
        self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "en_cours"},
                         headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Du chef"},
                         headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.login(self.inter)
        self.annuler(r)
        ligne = self.sql("SELECT etat, bloque_motif FROM tache WHERE id = %s", (self.t1,))[0]
        self.assertEqual((ligne["etat"], ligne["bloque_motif"]), ("bloque", "Du chef"))


class TestProjetClos(_Lot20):
    """Revue n° 12a : sous le verrou du projet, une écriture de tâche
    relit l'état du projet."""

    def test_verrou_refuse_un_projet_clos(self):
        from app.repositories import taches

        self.sql("UPDATE projet SET etat = 'termine' WHERE id = %s", (self.p1,))
        with self.assertRaises(taches.ProjetClos):
            with self.db.get_cursor() as cur:
                taches._verrouiller_projet(cur, self.p1)

    def test_route_repond_409_et_n_ecrit_rien(self):
        from unittest.mock import patch

        self.login(self.chef)
        self.sql("UPDATE projet SET etat = 'termine' WHERE id = %s", (self.p1,))
        avant = self.compter("SELECT count(*) AS n FROM tache")
        # Le contrôle d'avant (projet ouvert) est passé : clôture « pendant » la requête.
        with patch("app.routes.projets._refus_si_clos", return_value=None):
            r = self.client.post(f"/projets/{self.p1}/taches", data={"titre": "Tardive"}, headers=partiel("#x"))
        self.assertIn(r.status_code, (403, 409), r.get_data(as_text=True)[:400])
        self.assertEqual(self.compter("SELECT count(*) AS n FROM tache"), avant)


class TestDateSimuleePartout(_Lot20):
    """Revue 5d, test Chrome KB1/KB2 (décision : tout suit la date simulée,
    sauf le journal d'audit)."""
    MODE_TEST = True

    def test_blocage_en_date_passee_bloque_le_projet_et_date_les_posts(self):
        jour = self.auj - datetime.timedelta(days=3)
        # Lot 24 (HD-06) : la tâche existait ce jour-là (un blocage n'est
        # jamais daté avant la création de sa tâche).
        self.sql("UPDATE tache SET created_at = now() - interval '30 days' WHERE id = %s", (self.t1,))
        self.login(self.admin)
        self.client.post("/admin/date-simulee", data={"date": jour.isoformat(), "heure": "07:00"})
        self.entrer(self.inter, mode="agir")
        self.client.post("/admin/date-simulee", data={"date": jour.isoformat(), "heure": "07:00"})
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Plans"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.etat_projet(self.p1), "bloque")
        dates = self.sql("SELECT (created_at AT TIME ZONE 'Africa/Tunis')::date AS d FROM post "
                         "WHERE evenement = 'blocage_tache'")
        self.assertEqual([x["d"] for x in dates], [jour])
        bloque_le = self.sql("SELECT (bloque_le AT TIME ZONE 'Africa/Tunis')::date AS d FROM tache WHERE id = %s",
                             (self.t1,))[0]["d"]
        self.assertEqual(bloque_le, jour)


class TestDailyLogLot20(_Lot20):
    """Chef et verrou de 14 jours (décision), heures sur une tâche close
    (N4), garde en base sur UPDATE (n° 14)."""

    def put(self, jour, lignes):
        return self.client.put(f"/dailylog/api/jour/{jour.isoformat()}", json={"version": 0, "lignes": lignes})

    def test_le_chef_ne_corrige_pas_ses_propres_jours_au_dela_de_14_jours(self):
        self.login(self.chef)
        r = self.put(self.auj - datetime.timedelta(days=20), [{"projet_id": self.p1, "tache_id": None, "minutes": 60}])
        self.assertGreaterEqual(r.status_code, 400)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM dailylog_entree"), 0)

    def test_pas_d_heures_sur_une_tache_apres_sa_cloture(self):
        fin = self.auj - datetime.timedelta(days=2)
        self.sql("UPDATE tache SET etat = 'termine', date_fin = %s WHERE id = %s", (fin, self.t1))
        self.login(self.inter)
        r = self.put(self.auj - datetime.timedelta(days=1), [{"projet_id": self.p1, "tache_id": self.t1, "minutes": 60}])
        self.assertGreaterEqual(r.status_code, 400)
        r = self.put(self.auj - datetime.timedelta(days=3), [{"projet_id": self.p1, "tache_id": self.t1, "minutes": 60}])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.compter("SELECT count(*) AS n FROM dailylog_entree"), 1)

    def test_garde_en_base_sur_la_ligne_d_origine(self):
        vieux = self.auj - datetime.timedelta(days=30)
        with self.db.get_cursor(user_id=self.admin) as cur:
            cur.execute("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, 3) "
                        "RETURNING id", (self.inter, vieux, self.p1))
            ligne = cur.fetchone()["id"]
        with self.assertRaises(Exception):
            with self.db.get_cursor(user_id=self.inter) as cur:
                cur.execute("UPDATE dailylog_entree SET date = %s WHERE id = %s",
                            (self.auj - datetime.timedelta(days=1), ligne))
        self.assertEqual(self.sql("SELECT date FROM dailylog_entree WHERE id = %s", (ligne,))[0]["date"], vieux)


class TestAccueilEtFil(_Lot20):
    def test_sante(self):
        r = self.client.get("/sante")
        self.assertEqual((r.status_code, r.get_data(as_text=True)), (200, "ok\n"))

    def test_categorie_memorisee_lue_par_le_serveur(self):
        """Revue n° 12d : la page s'ouvre sur la catégorie mémorisée ; seule
        celle-ci devient vue."""
        self.login(self.inter)
        self.client.set_cookie("kairos_fil_accueil", "activite")
        r = self.client.get("/accueil")
        self.assertRegex(self.texte(r), r'id="fil-filtre-accueil-activite" data-fil="activite"[^>]* aria-current="page"')
        vus = {x["categorie"] for x in self.sql("SELECT categorie FROM utilisateur_fil_vu WHERE utilisateur_id = %s",
                                                 (self.inter,))}
        self.assertEqual(vus, {"activite"})

    def test_vu_jusqu_au_dernier_post_affiche_et_jamais_en_arriere(self):
        """Revue n° 12c : un post validé après la lecture reste « nouveau »."""
        from app.repositories import posts

        ancien = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu, created_at) VALUES "
                          "(%s, %s, 'information', 'Ancien', now() - interval '1 hour') RETURNING created_at",
                          (self.p1, self.chef))[0]["created_at"]
        self.login(self.inter)
        self.client.get("/accueil?fil=echanges")
        self.assertEqual(posts.fil_vu(self.inter)["echanges"], ancien)
        # Post « en retard » (transaction commencée avant la lecture) : encore nouveau.
        self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu, created_at) VALUES "
                 "(%s, %s, 'information', 'Retardé', now() - interval '30 minutes')", (self.p1, self.chef))
        self.assertEqual(posts.compter_non_vus(self.inter, posts.fil_vu(self.inter))["echanges"], 1)
        posts.marquer_fil_vu(self.inter, ("echanges",), ancien - datetime.timedelta(days=1))
        self.assertEqual(posts.fil_vu(self.inter)["echanges"], ancien)

    def test_client_deadlines_depliees_meme_avec_une_autre_preference(self):
        """Revue n° 13."""
        client = self.user("client")
        self.sql("INSERT INTO utilisateur_preference (utilisateur_id, dailylog_proposer) VALUES (%s, true)", (client,))
        self.login(client)
        r = self.client.post("/preferences", data={"cle": "dailylog_proposer", "valeur": "1"})
        self.assertEqual(r.status_code, 400)
        page = self.texte(self.client.get("/accueil"))
        self.assertRegex(page, r'<details class="acc-deadlines[^"]*"[^>]*\bopen\b')

    def test_lien_aller_a_mes_taches_seulement_avec_la_carte(self):
        """Revue n° 16a."""
        client = self.user("client")
        self.login(client)
        self.assertNotIn("acc-lien-taches", self.texte(self.client.get("/accueil")))
        self.login(self.inter)
        self.assertIn("acc-lien-taches", self.texte(self.client.get("/accueil")))


class TestProjetEtPosts(_Lot20):
    def test_ajout_d_intervenant_dans_l_activite(self):
        """Test Chrome N6."""
        nouveau = self.user("intervenant")
        self.login(self.chef)
        self.client.post(f"/projets/{self.p1}/intervenants", data={"utilisateur_id": str(nouveau)})
        contenus = [x["contenu"] for x in self.sql("SELECT contenu FROM post WHERE evenement = 'intervenant_projet'")]
        self.assertEqual(len(contenus), 1)
        self.assertIn("au projet comme intervenant", contenus[0])
        # Déjà rattaché : rien de plus.
        self.client.post(f"/projets/{self.p1}/intervenants", data={"utilisateur_id": str(nouveau)})
        self.assertEqual(self.compter("SELECT count(*) AS n FROM post WHERE evenement = 'intervenant_projet'"), 1)

    def test_requete_montre_sa_suite(self):
        """Test Chrome FP3."""
        requete = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES "
                           "(%s, %s, 'requete', 'Pouvez-vous ?') RETURNING id", (self.p1, self.inter))[0]["id"]
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p1}/taches", data={"titre": "Réponse à la requête",
                                                                "parent_post_id": str(requete)})
        self.assertLess(r.status_code, 400)
        page = self.texte(self.client.get(f"/projets/{self.p1}?fil=echanges"))
        self.assertIn("Suite", page)
        self.assertIn("Réponse à la requête", page.split(f'id="post-{requete}"')[1].split('class="post-actions')[0])

    def test_phase_liee_invisible_non_affichee(self):
        """Revue n° 9b."""
        self.sql("UPDATE projet SET phase_liee_id = %s WHERE id = %s", (self.p2, self.p1))
        self.sql("UPDATE projet SET nom = 'Projet URBS secret' WHERE id = %s", (self.p2,))
        self.login(self.inter)
        self.assertNotIn("Projet URBS secret", self.texte(self.client.get(f"/projets/{self.p1}")))

    def test_mentions_plafonnees(self):
        """Revue n° 11 : une liste d'identifiants est bornée."""
        from app import validation

        self.assertEqual(len(validation.ids_entiers([str(i) for i in range(1, 5000)])), validation.MAX_IDS)

    def test_notification_d_un_commentaire_supprime_masque_l_extrait(self):
        """Revue n° 9c."""
        from app.repositories import notifications

        post = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', "
                        "'Post') RETURNING id", (self.p1, self.chef))[0]["id"]
        self.login(self.chef)
        self.client.post(f"/posts/{post}/commenter", data={"contenu": "Secret pour @Rim Inter"}, headers=partiel("#x"))
        cid = self.sql("SELECT id FROM post_commentaire")[0]["id"]
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE commentaire_id = %s", (cid,)), 1)
        self.client.post(f"/posts/commentaires/{cid}/supprimer", headers=partiel("#x"))
        messages = [n["message"] for n in notifications.list_notifications(self.inter)]
        self.assertTrue(messages)
        self.assertFalse(any("Secret" in m for m in messages), messages)


class TestDeadlinesClient(_Lot20):
    """Revue n° 17g : vue Deadlines du client (lot 19)."""

    def test_projet_clos_exclu_retards_anciens_en_dernier_et_limite(self):
        from app.repositories import taches

        client = self.user("client")
        clos = self.projet(self.chef, etat="termine")
        self.tache(clos, self.chef, echeance=self.auj + datetime.timedelta(days=1))
        tres_ancienne = self.tache(self.p1, self.chef, echeance=self.auj - datetime.timedelta(days=100))
        retard = self.tache(self.p1, self.chef, echeance=self.auj - datetime.timedelta(days=10))
        lignes = taches.list_deadlines_equipe(client)
        ids = [x["id"] for x in lignes]
        self.assertNotIn(clos, [x["projet_id"] for x in lignes])
        self.assertEqual(ids[0], retard)
        self.assertEqual(ids[-1], tres_ancienne)
        self.assertEqual(len(taches.list_deadlines_equipe(client, limit=2)), 2)


class TestPoolApresRedemarrage(_Lot20):
    """Nouveau bug N5 : une connexion morte du pool n'est plus prêtée."""

    def test_connexions_coupees_puis_requetes(self):
        from app import db

        self.login(self.inter)
        self.assertEqual(self.client.get("/accueil").status_code, 200)
        self.sql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                 "WHERE datname = current_database() AND pid <> pg_backend_pid() AND usename = current_user "
                 "AND application_name = ''")
        ancien = db.SEUIL_PING
        db.SEUIL_PING = 0
        try:
            for _ in range(4):
                self.assertEqual(self.client.get("/accueil").status_code, 200)
        finally:
            db.SEUIL_PING = ancien

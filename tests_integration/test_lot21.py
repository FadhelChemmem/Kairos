"""Lot 21 sur un vrai PostgreSQL : test Chrome du 19/10 (lot 20) et
contre-expertise Claude Code, avec les décisions du gérant du 19/10 :
toute personne qui a participé à un projet garde la lecture (et peut
reprendre ses anciens écrits, pièces jointes et mentions comprises) ; une
tâche close rouverte rend ses droits à ses intervenants ; un membre de
l'équipe du projet retiré peut le rejoindre de nouveau."""
import datetime
import io
import json
import re
from pathlib import Path
from unittest.mock import patch

from tests_integration.base import URL, fermer_pool
from tests_integration.test_lot20 import _Lot20, partiel, toasts

RACINE = Path(__file__).resolve().parent.parent


class _AncienParticipant(_Lot20):
    def setUp(self):
        super().setUp()
        self.urbs = self.user("intervenant", equipe="URBS")
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, self.urbs))
        self.sien = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, "
                             "'information', 'Mon relevé') RETURNING id", (self.p1, self.urbs))[0]["id"]

    def retirer(self, uid):
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p1}/intervenants/{uid}/retirer")
        self.assertIn(r.status_code, (200, 302))

    def rejouer_0025(self):
        with self.db.get_cursor() as cur:
            cur.execute((RACINE / "migrations" / "0025_lot21_participants_horloge_et_gardes.sql")
                        .read_text(encoding="utf-8"))


class TestAncienParticipant(_AncienParticipant):
    """Test Chrome (nouveau bug) et contre-expertise R1 : retiré d'un projet
    d'une autre équipe SANS tâche close, il gardait la fiche en 404."""

    def test_lecture_gardee_sans_tache_close(self):
        self.retirer(self.urbs)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet_ancien_membre WHERE projet_id = %s "
                                      "AND utilisateur_id = %s", (self.p1, self.urbs)), 1)
        self.login(self.urbs)
        r = self.client.get(f"/projets/{self.p1}")
        self.assertEqual(r.status_code, 200)
        page = self.texte(r)
        # Lecture seule : ni « Commenter » ni « Donner suite » sur les posts.
        self.assertNotIn(f'data-commenter="{self.sien}"', page)
        self.assertNotIn(f'data-parent-post-id="{self.sien}"', page)
        avant = self.compter("SELECT count(*) AS n FROM post")
        r = self.client.post("/posts", data={"projet_id": str(self.p1), "type_code": "information",
                                             "contenu": "Encore là"}, headers=partiel("#x"))
        self.assertIn(r.status_code, (403, 409))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM post"), avant)

    def test_ses_anciens_posts_modifiables_avec_mention(self):
        self.retirer(self.urbs)
        self.login(self.urbs)
        r = self.client.post(f"/posts/{self.sien}/modifier",
                             data={"contenu": "Relevé corrigé @Rim Inter", "mentions": [str(self.inter)]},
                             headers=partiel("#x"))
        self.assertLess(r.status_code, 400, r.get_data(as_text=True)[:300])
        self.assertEqual(self.sql("SELECT contenu FROM post WHERE id = %s", (self.sien,))[0]["contenu"],
                         "Relevé corrigé @Rim Inter")
        # Lot 25 (revue R-05) : la mention est bien enregistrée et prévient Rim.
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE utilisateur_id = %s "
                                      "AND post_id = %s AND message LIKE %s", (self.inter, self.sien, "%mentionn%")), 1)

    def test_rajout_propose_depuis_la_fiche(self):
        self.retirer(self.urbs)
        self.login(self.chef)
        page = self.texte(self.client.get(f"/projets/{self.p1}"))
        self.assertRegex(page, rf'<option value="{self.urbs}"')
        self.client.post(f"/projets/{self.p1}/intervenants", data={"utilisateur_id": str(self.urbs)})
        self.login(self.urbs)
        r = self.client.post("/posts", data={"projet_id": str(self.p1), "type_code": "information",
                                             "contenu": "De retour"}, headers=partiel("#x"))
        self.assertLess(r.status_code, 400, r.get_data(as_text=True)[:300])

    def test_tache_close_rouverte_rend_les_droits(self):
        close = self.tache(self.p1, self.chef, etat="termine", intervenants=[self.urbs])
        self.retirer(self.urbs)
        self.login(self.urbs)
        self.assertGreaterEqual(self.client.post(f"/projets/{self.p1}/taches/{close}/titre", data={"titre": "X"},
                                                 headers=partiel("#x")).status_code, 400)
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p1}/taches/{close}/etat", data={"etat": "en_cours"},
                             headers=partiel(f"#tache-fenetre-{close}"))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.login(self.urbs)
        r = self.client.post("/posts", data={"projet_id": str(self.p1), "type_code": "information",
                                             "contenu": "Elle revient"}, headers=partiel("#x"))
        self.assertLess(r.status_code, 400, r.get_data(as_text=True)[:300])

    def test_membre_de_l_equipe_retire_peut_rejoindre(self):
        self.retirer(self.inter)
        self.login(self.inter)
        self.assertEqual(self.client.get(f"/projets/{self.p1}").status_code, 200)
        self.client.post(f"/projets/{self.p1}/rejoindre")
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet_intervenant WHERE projet_id = %s "
                                      "AND utilisateur_id = %s", (self.p1, self.inter)), 1)

    def test_ancien_chef_garde_la_lecture(self):
        autre_chef = self.user("chef_de_projet", equipe="URBS")
        self.sql("UPDATE projet SET chef_projet_id = %s WHERE id = %s", (autre_chef, self.p1))
        self.sql("UPDATE projet SET chef_projet_id = %s WHERE id = %s", (self.chef, self.p1))
        self.login(autre_chef)
        self.assertEqual(self.client.get(f"/projets/{self.p1}").status_code, 200)

    def test_client_et_rh_jamais_anciens_membres(self):
        client = self.user("client", equipe="URBS")
        self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', 'c')",
                 (self.p1, client))
        self.rejouer_0025()
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet_ancien_membre WHERE utilisateur_id = %s",
                                      (client,)), 0)
        self.login(client)
        self.assertEqual(self.client.get(f"/projets/{self.p1}").status_code, 404)


class TestMigration0025(_AncienParticipant):
    """Reprise : participants d'avant le lot (posts, heures, retraits tracés),
    updated_at réécrits par 0024 rendus, date de fin des tâches closes."""

    def test_reprise_des_participants(self):
        autre = self.user("intervenant", equipe="VD")
        self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', 'v')",
                 (self.p1, autre))
        retire = self.user("intervenant", equipe="VD")
        self.sql("INSERT INTO audit_log (table_cible, action, donnees_avant) VALUES ('projet_intervenant', 'DELETE', "
                 "%s::jsonb)", (json.dumps({"projet_id": self.p1, "utilisateur_id": retire}),))
        self.sql("DELETE FROM projet_ancien_membre")
        self.rejouer_0025()
        ids = {x["utilisateur_id"] for x in self.sql("SELECT utilisateur_id FROM projet_ancien_membre "
                                                      "WHERE projet_id = %s", (self.p1,))}
        self.assertTrue({autre, retire, self.urbs, self.inter} <= ids)
        self.rejouer_0025()   # rejouable
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet_ancien_membre WHERE projet_id = %s",
                                      (self.p1,)), len(ids))

    def test_updated_at_rendus_et_date_de_fin(self):
        applique = self.sql("SELECT applied_at FROM schema_migrations "
                            "WHERE version = '0024_lot20_droits_dates_et_garde'")[0]["applied_at"]
        vrai = datetime.datetime(2026, 3, 4, 10, 0, tzinfo=datetime.timezone.utc)
        close = self.tache(self.p1, self.chef, etat="abandonne")
        self.sql("ALTER TABLE tache DISABLE TRIGGER trg_tache_updated_at")
        try:
            self.sql("UPDATE tache SET updated_at = %s, date_fin = NULL WHERE id IN (%s, %s)",
                     (applique, self.t1, close))
        finally:
            self.sql("ALTER TABLE tache ENABLE TRIGGER trg_tache_updated_at")
        self.sql("INSERT INTO audit_log (table_cible, ligne_id, action, donnees_avant, created_at) "
                 "VALUES ('tache', %s, 'UPDATE', %s::jsonb, %s)",
                 (self.t1, json.dumps({"updated_at": vrai.isoformat()}), applique))
        self.rejouer_0025()
        lignes = {x["id"]: x for x in self.sql("SELECT id, updated_at, date_fin FROM tache WHERE id IN (%s, %s)",
                                                (self.t1, close))}
        self.assertEqual(lignes[self.t1]["updated_at"], vrai)
        self.assertIsNone(lignes[self.t1]["date_fin"])           # tâche ouverte : pas de date de fin
        self.assertIsNotNone(lignes[close]["date_fin"])


class TestDateDeFinEtDailyLog(_Lot20):
    """Test Chrome V11 / V20 et contre-expertise R9 (B-01)."""

    def put(self, jour, lignes):
        return self.client.put(f"/dailylog/api/jour/{jour.isoformat()}", json={"version": 0, "lignes": lignes})

    def test_abandon_pose_la_date_de_fin(self):
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "abandonne"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.sql("SELECT date_fin FROM tache WHERE id = %s", (self.t1,))[0]["date_fin"], self.auj)
        self.assertIn("Abandonnée", self.texte(r))
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "en_cours"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertIsNone(self.sql("SELECT date_fin FROM tache WHERE id = %s", (self.t1,))[0]["date_fin"])

    def test_garde_en_base_tache_close(self):
        fin = self.auj - datetime.timedelta(days=3)
        self.sql("UPDATE tache SET etat = 'termine', date_fin = %s WHERE id = %s", (fin, self.t1))
        import psycopg2

        with self.assertRaises(psycopg2.Error) as ctx:
            with self.db.get_cursor(user_id=self.inter) as cur:
                cur.execute("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures) "
                            "VALUES (%s, %s, %s, %s, 2)", (self.inter, self.auj - datetime.timedelta(days=1),
                                                            self.p1, self.t1))
        self.assertIn("dailylog_tache_close", str(ctx.exception.diag.constraint_name or ctx.exception))
        with self.db.get_cursor(user_id=self.inter) as cur:   # jusqu'à la date de fin : accepté
            cur.execute("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures) "
                        "VALUES (%s, %s, %s, %s, 2)", (self.inter, fin, self.p1, self.t1))

    def test_route_repond_tache_close(self):
        self.sql("UPDATE tache SET etat = 'termine', date_fin = %s WHERE id = %s",
                 (self.auj - datetime.timedelta(days=2), self.t1))
        self.login(self.inter)
        r = self.put(self.auj - datetime.timedelta(days=1), [{"projet_id": self.p1, "tache_id": self.t1, "minutes": 60}])
        self.assertEqual(r.status_code, 422)
        self.assertIn("tache_close", [e["code"] for e in r.get_json()["erreurs"]])

    def test_autre_equipe_garde_ses_heures_jusqu_a_la_fin_de_sa_tache(self):
        t = self.tache(self.p2, self.chef, intervenants=[self.inter])
        self.sql("UPDATE tache SET etat = 'termine', date_fin = %s WHERE id = %s", (self.auj, t))
        self.login(self.inter)
        r = self.put(self.auj, [{"projet_id": self.p2, "tache_id": t, "minutes": 120}])
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.compter("SELECT count(*) AS n FROM dailylog_entree WHERE utilisateur_id = %s",
                                      (self.inter,)), 1)
        # Le projet, sans tâche : refusé (lecture seule).
        r = self.put(self.auj - datetime.timedelta(days=1), [{"projet_id": self.p2, "tache_id": None, "minutes": 60}])
        self.assertEqual(r.status_code, 422)

    def test_le_chef_et_ses_propres_jours_anciens(self):
        self.login(self.chef)
        r = self.put(self.auj - datetime.timedelta(days=20), [{"projet_id": self.p1, "tache_id": None, "minutes": 60}])
        self.assertIn(r.status_code, (403, 422))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM dailylog_entree"), 0)
        etat = self.client.get(f"/dailylog/api/jour/{(self.auj - datetime.timedelta(days=20)).isoformat()}").get_json()
        self.assertTrue(etat["droits"]["lecture_seule"])
        self.assertFalse(etat["droits"]["lignes_de_ses_projets"])

    def test_copie_d_un_jour_sans_ligne_reprenable(self):
        hier = self.auj - datetime.timedelta(days=1)
        with self.db.get_cursor(user_id=self.inter) as cur:
            cur.execute("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures) "
                        "VALUES (%s, %s, %s, %s, 2)", (self.inter, hier, self.p1, self.t1))
        self.sql("UPDATE tache SET etat = 'termine', date_fin = %s WHERE id = %s", (hier, self.t1))
        self.login(self.inter)
        copie = self.client.get(f"/dailylog/api/jour/{self.auj.isoformat()}").get_json()["copie"]
        self.assertEqual((copie["date"], copie["lignes"], copie["exclues"]), (hier.isoformat(), [], 1))


class TestBlocageEtVerrous(_Lot20):
    def test_bloquer_une_tache_deja_bloquee_est_refuse(self):
        self.login(self.inter)
        self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Plans"},
                         headers=partiel(f"#tache-fenetre-{self.t1}"))
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Autre"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        # Lot 23 (test Chrome W11) : panneau rafraîchi (blocage en cours), refus en toast.
        self.assertEqual(r.status_code, 200)
        self.assertEqual([(t["type"], t["texte"][:30]) for t in toasts(r)],
                         [("erreur", "Cette tâche est déjà bloquée\u00a0(")])
        self.assertIn("Plans", self.texte(r))
        self.assertEqual(self.sql("SELECT bloque_motif FROM tache WHERE id = %s", (self.t1,))[0]["bloque_motif"],
                         "Plans")
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Autre"})
        self.assertEqual(r.status_code, 302)                     # sans JavaScript : retour au panneau

    def test_motif_garde_ses_retours_a_la_ligne(self):
        self.login(self.inter)
        self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat",
                         data={"etat": "bloque", "motif": "Ligne 1\r\nLigne 2"},
                         headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(self.sql("SELECT bloque_motif FROM tache WHERE id = %s", (self.t1,))[0]["bloque_motif"],
                         "Ligne 1\nLigne 2")

    def test_projet_clos_sous_verrou_pour_posts_commentaires_et_equipe(self):
        from app.repositories import posts, projets, taches

        post = posts.create_post(self.p1, self.chef, "information", "Avant")
        autre = self.user("intervenant")
        self.sql("UPDATE projet SET etat = 'termine' WHERE id = %s", (self.p1,))
        for appel in (lambda: posts.create_post(self.p1, self.chef, "information", "Après"),
                      lambda: posts.add_comment(post, self.chef, "Mot"),
                      lambda: projets.add_intervenant(self.p1, autre, self.chef),
                      lambda: projets.retirer_intervenant(self.p1, self.inter, self.chef)):
            with self.assertRaises(taches.ProjetClos):
                appel()
        self.assertEqual(self.compter("SELECT count(*) AS n FROM post WHERE contenu = 'Après'"), 0)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet_intervenant WHERE projet_id = %s",
                                      (self.p1,)), 1)

    def test_route_post_409_si_le_projet_se_ferme_pendant_la_requete(self):
        self.login(self.chef)
        self.sql("UPDATE projet SET etat = 'termine' WHERE id = %s", (self.p1,))
        # Lot 24 (revue SR-R06) : seul le contrôle de la route est contourné
        # (l'ancien patch visait une fonction qui n'existe pas).
        with patch("app.routes.posts._refus_si_clos", return_value=None):
            post = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, "
                            "'information', 'x') RETURNING id", (self.p1, self.chef))[0]["id"]
            r = self.client.post(f"/posts/{post}/commenter", data={"contenu": "Tard"}, headers=partiel("#x"))
        self.assertEqual(r.status_code, 409, r.get_data(as_text=True)[:300])
        self.assertEqual(self.compter("SELECT count(*) AS n FROM post_commentaire"), 0)

    def test_etat_du_projet_change_dans_un_autre_onglet(self):
        # Fenêtre ouverte sur un projet en cours, clos entre-temps ailleurs.
        self.sql("UPDATE projet SET etat = 'termine' WHERE id = %s", (self.p1,))
        self.login(self.admin)
        r = self.client.post(f"/projets/{self.p1}/informations",
                             data={"nom": "Renommé", "etat": "en_cours", "etat_initial": "en_cours"},
                             headers=partiel("#informations-form"))
        self.assertEqual(r.status_code, 409, r.get_data(as_text=True)[:300])
        ligne = self.sql("SELECT etat, nom FROM projet WHERE id = %s", (self.p1,))[0]
        self.assertEqual((ligne["etat"], ligne["nom"]), ("termine", "Projet"))

    def test_cloturer_une_tache_d_un_autre_projet_404(self):
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p2}/taches/{self.t1}/cloturer", data={"type_code": "envoi"},
                             headers=partiel("#x"))
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.etat_tache(self.t1), "en_cours")


class TestHorloge(_Lot20):
    """Contre-expertise R10 / R11 / R22 (B-02, B-03)."""
    MODE_TEST = True

    def test_instant_simule_avance_et_debloque_le_projet(self):
        jour = self.auj - datetime.timedelta(days=2)
        # Lot 24 (HD-06) : la tâche existait ce jour-là (un blocage n'est
        # jamais daté avant la création de sa tâche).
        self.sql("UPDATE tache SET created_at = now() - interval '30 days' WHERE id = %s", (self.t1,))
        self.login(self.admin)
        self.entrer(self.chef, mode="agir")
        self.client.post("/admin/date-simulee", data={"date": jour.isoformat(), "heure": "09:00"})
        self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Plans"},
                         headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(self.etat_projet(self.p1), "bloque")
        r = self.client.post(f"/projets/{self.p1}/taches", data={"titre": "Après le blocage"}, headers=partiel("#x"))
        self.assertLess(r.status_code, 400, r.get_data(as_text=True)[:300])
        self.assertEqual(self.etat_projet(self.p1), "en_cours")
        lignes = self.sql("SELECT created_at, bloque_le FROM tache WHERE projet_id = %s ORDER BY id", (self.p1,))
        self.assertGreater(lignes[-1]["created_at"], lignes[0]["bloque_le"])
        self.assertEqual((lignes[0]["bloque_le"].astimezone(datetime.timezone(datetime.timedelta(hours=1)))).date(),
                         jour)

    def test_jamais_d_ecriture_dans_le_futur_reel(self):
        futur = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=5)).isoformat()
        with self.db.get_cursor() as cur:
            cur.execute("SELECT set_config('kairos.instant_simule', %s, true)", (futur,))
            cur.execute("SELECT fn_maintenant() <= clock_timestamp() AS ok, fn_aujourdhui() AS j")
            ligne = cur.fetchone()
        self.assertTrue(ligne["ok"])
        self.assertEqual(ligne["j"], self.auj + datetime.timedelta(days=5))

    def test_commentaire_modifie_sous_futur_simule(self):
        post = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', "
                        "'Post') RETURNING id", (self.p1, self.chef))[0]["id"]
        self.login(self.admin)
        self.entrer(self.chef, mode="agir")
        self.client.post("/admin/date-simulee",
                         data={"date": (self.auj + datetime.timedelta(days=3)).isoformat(), "heure": "09:00"})
        self.client.post(f"/posts/{post}/commenter", data={"contenu": "Code porte 4321 pour @Rim Inter"},
                         headers=partiel("#x"))
        self.client.post("/admin/revenir")
        self.login(self.chef)
        c = self.sql("SELECT id FROM post_commentaire WHERE post_id = %s", (post,))[0]["id"]
        self.client.post(f"/posts/commentaires/{c}/modifier", data={"contenu": "Corrigé pour @Rim Inter"}, headers=partiel("#x"))
        from app.repositories import notifications

        messages = [n["message"] for n in notifications.list_notifications(self.inter)]
        self.assertTrue(messages)
        self.assertTrue(all("4321" not in m for m in messages), messages)

    def test_il_y_a_d_un_instant_futur_est_absolu(self):
        from app.utils import il_y_a

        with self.app.test_request_context("/"):
            texte = il_y_a(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3))
        self.assertNotIn("il y a", texte)
        self.assertNotIn("instant", texte)


class TestFilEtFiche(_Lot20):
    def test_parent_d_une_autre_equipe_masque(self):
        parent = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', "
                          "'Secret URBS') RETURNING id", (self.p2, self.chef))[0]["id"]
        self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu, parent_post_id) VALUES (%s, %s, "
                 "'information', 'Suite MIDGARD', %s)", (self.p1, self.chef, parent))
        self.login(self.inter)
        page = self.texte(self.client.get(f"/projets/{self.p1}"))
        self.assertIn("Suite MIDGARD", page)
        self.assertIn("Post d’une autre équipe.", page)
        self.assertNotIn("Secret URBS", page)

    def test_mentions_limitees_a_ceux_qui_voient_le_projet(self):
        urbs = self.user("intervenant", equipe="URBS")
        self.login(self.chef)
        page = self.texte(self.client.get(f"/projets/{self.p1}"))
        bloc = re.search(r'<script type="application/json" id="kairos-personnes">(.*?)</script>', page, re.S)
        ids = {p["id"] for p in json.loads(bloc.group(1))}
        self.assertIn(self.inter, ids)
        self.assertNotIn(urbs, ids)

    def test_mentions_plafonnees_par_la_route(self):
        self.login(self.chef)
        r = self.client.post("/posts", data={"projet_id": str(self.p1), "type_code": "information",
                                             "contenu": "Beaucoup", "mentions": [str(self.inter)] * 5000},
                             headers=partiel("#x"))
        self.assertLess(r.status_code, 400, r.get_data(as_text=True)[:300])
        self.assertEqual(self.compter("SELECT count(*) AS n FROM post_mention"), 1)
        # Lot 24 (revue R-07) : des ids TOUS différents au-delà du plafond —
        # la route n'en lit pas plus que MAX_IDS (rien n'est écrit pour eux).
        from app import validation
        ids = [str(i) for i in range(10 ** 6, 10 ** 6 + validation.MAX_IDS + 50)] + [str(self.inter)]
        r = self.client.post("/posts", data={"projet_id": str(self.p1), "type_code": "information",
                                             "contenu": "Plafond", "mentions": ids}, headers=partiel("#x"))
        self.assertLess(r.status_code, 400, r.get_data(as_text=True)[:300])
        dernier = self.sql("SELECT max(id) AS id FROM post")[0]["id"]
        self.assertEqual(self.compter("SELECT count(*) AS n FROM post_mention WHERE post_id = %s", (dernier,)), 0)

    def test_code_propose_donne_le_client_de_la_phase_liee(self):
        self.sql("UPDATE projet SET client = 'Cité Nord', phase = 'APS' WHERE id = %s", (self.p1,))
        self.login(self.chef)
        r = self.client.get(f"/projets/code-propose?phase=APD&phase_liee_id={self.p1}")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(r.get_json()["client"], "Cité Nord")


class TestCorrectifsLot20Eprouves(_Lot20):
    """Contre-expertise R12 / R-01 / R-04 : chaque correctif du lot 20 a un
    test qui échoue s'il disparaît."""

    def setUp(self):
        super().setUp()
        configure = patch("app.mailer.est_configure", return_value=True)
        configure.start()
        self.addCleanup(configure.stop)

    def demander_lien(self, email, ip="10.0.0.1"):
        return self.client.post("/mot-de-passe-oublie", data={"email": email}, environ_base={"REMOTE_ADDR": ip})

    def jeton(self, uid):
        return self.sql("SELECT reset_token_hash AS h, reset_token_expires_at AS e FROM utilisateur WHERE id = %s",
                        (uid,))[0]

    def test_un_seul_lien_par_quart_d_heure(self):
        email = self.sql("SELECT email FROM utilisateur WHERE id = %s", (self.inter,))[0]["email"]
        with patch("app.mailer.envoyer_en_arriere_plan") as envoi:
            self.demander_lien(email)
            premier = self.jeton(self.inter)
            self.demander_lien(email)
            self.assertEqual(self.jeton(self.inter)["h"], premier["h"])
            self.assertEqual(envoi.call_count, 1)
            # Lien émis il y a 20 minutes : un nouveau part.
            self.sql("UPDATE utilisateur SET reset_token_expires_at = now() + interval '40 minutes' WHERE id = %s",
                     (self.inter,))
            self.demander_lien(email)
            self.assertNotEqual(self.jeton(self.inter)["h"], premier["h"])
            self.assertEqual(envoi.call_count, 2)

    def test_limite_par_adresse_ip(self):
        from app import auth

        with patch("app.mailer.envoyer_en_arriere_plan") as envoi:
            for i in range(auth.MAX_DEMANDES_RESET_IP):
                self.demander_lien(f"inconnu{i}@t.tn", ip="10.9.9.9")
            email = self.sql("SELECT email FROM utilisateur WHERE id = %s", (self.chef,))[0]["email"]
            self.demander_lien(email, ip="10.9.9.9")
            self.assertIsNone(self.jeton(self.chef)["h"])
            self.demander_lien(email, ip="10.9.9.10")
            self.assertIsNotNone(self.jeton(self.chef)["h"])
        self.assertEqual(envoi.call_count, 1)

    def test_jeton_efface_au_changement_d_email(self):
        from app.repositories import utilisateurs

        self.sql("UPDATE utilisateur SET reset_token_hash = 'h', reset_token_expires_at = now() + interval '1 hour' "
                 "WHERE id = %s", (self.inter,))
        u = utilisateurs.get_utilisateur(self.inter)
        champs = dict(prenom=u["prenom"], nom=u["nom"], telephone=None, poste=None, adresse=None,
                      date_embauche=u["date_embauche"], equipe_code=u["equipe_code"], role=u["role"],
                      champs_perso={}, current_user_id=self.admin)
        utilisateurs.update_utilisateur_complet(self.inter, email=u["email"].upper(), **champs)
        self.assertEqual(self.jeton(self.inter)["h"], "h")      # même adresse (casse) : gardé
        utilisateurs.update_utilisateur_complet(self.inter, email="nouvelle@t.tn", **champs)
        self.assertIsNone(self.jeton(self.inter)["h"])

    def test_ancienne_photo_effacee(self):
        from tests.test_lot21 import JPEG, PNG

        dossier = Path(self.app.config["UPLOAD_DIR"])
        self.login(self.inter)
        self.client.post("/utilisateurs/moi", data={"avatar": (io.BytesIO(PNG), "a.png")},
                         content_type="multipart/form-data")
        premier = self.sql("SELECT avatar_chemin FROM utilisateur WHERE id = %s", (self.inter,))[0]["avatar_chemin"]
        self.assertTrue(premier and (dossier / premier).exists())
        self.client.post("/utilisateurs/moi", data={"avatar": (io.BytesIO(JPEG), "b.jpg")},
                         content_type="multipart/form-data")
        second = self.sql("SELECT avatar_chemin FROM utilisateur WHERE id = %s", (self.inter,))[0]["avatar_chemin"]
        self.assertNotEqual(premier, second)
        self.assertFalse((dossier / premier).exists())
        self.assertTrue((dossier / second).exists())
        # Fausse image : refusée, la photo reste.
        self.client.post("/utilisateurs/moi", data={"avatar": (io.BytesIO(b"GIF89a<html>;"), "c.gif")},
                         content_type="multipart/form-data")
        self.assertEqual(self.sql("SELECT avatar_chemin FROM utilisateur WHERE id = %s", (self.inter,))[0]
                         ["avatar_chemin"], second)

    def test_extrait_modifie_depuis_masque(self):
        post = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', "
                        "'Post') RETURNING id", (self.p1, self.chef))[0]["id"]
        self.login(self.chef)
        self.client.post(f"/posts/{post}/commenter", data={"contenu": "Code 4321 pour @Rim Inter"},
                         headers=partiel("#x"))
        from app.repositories import notifications

        (avant,) = [n["message"] for n in notifications.list_notifications(self.inter)]
        self.assertIn("4321", avant)
        c = self.sql("SELECT id FROM post_commentaire WHERE post_id = %s", (post,))[0]["id"]
        self.client.post(f"/posts/commentaires/{c}/modifier", data={"contenu": "Corrigé"}, headers=partiel("#x"))
        (apres,) = [n["message"] for n in notifications.list_notifications(self.inter)]
        self.assertNotIn("4321", apres)
        self.assertTrue(apres.endswith("(modifié depuis)."), apres)

    def test_reponse_a_une_information_d_une_equipe_disparue(self):
        ancien = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (NULL, %s, "
                          "'information', 'Ancien') RETURNING id", (self.chef,))[0]["id"]
        self.sql("ALTER TABLE post_equipe DISABLE TRIGGER USER")
        try:
            self.sql("INSERT INTO post_equipe (post_id, equipe_code) SELECT %s, code FROM equipe "
                     "WHERE code = 'IPCO'", (ancien,))
        finally:
            self.sql("ALTER TABLE post_equipe ENABLE TRIGGER USER")
        self.login(self.chef)
        r = self.client.post("/posts", data={"type_code": "information", "contenu": "Réponse",
                                             "parent_post_id": str(ancien)}, headers=partiel("#x"))
        self.assertLess(r.status_code, 400, r.get_data(as_text=True)[:300])
        reponse = self.sql("SELECT id FROM post WHERE contenu = 'Réponse'")[0]["id"]
        equipes = [x["equipe_code"] for x in self.sql("SELECT equipe_code FROM post_equipe WHERE post_id = %s",
                                                       (reponse,))]
        self.assertEqual(equipes, ["MIDGARD"])

    def test_connexions_reellement_coupees(self):
        import psycopg2

        from app import db

        self.login(self.inter)
        self.assertEqual(self.client.get("/accueil").status_code, 200)
        tueur = psycopg2.connect(URL, application_name="kairos-test-tueur")
        try:
            tueur.autocommit = True
            with tueur.cursor() as cur:
                cur.execute("SELECT count(*) FROM (SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                            "AND usename = current_user) x")
                tuees = cur.fetchone()[0]
        finally:
            tueur.close()
        self.assertGreaterEqual(tuees, 1)
        ancien = db.SEUIL_PING
        db.SEUIL_PING = 0
        try:
            with self.assertLogs("app.db", level="WARNING"):
                for _ in range(4):
                    self.assertEqual(self.client.get("/accueil").status_code, 200)
        finally:
            db.SEUIL_PING = ancien
            fermer_pool()
            db.init_pool(URL)


class TestPostEpingle(_Lot20):
    """Demande du gérant (19/10) : une Information épinglée en tête du fil
    du projet — une seule, par le chef, un co-chef ou l'Admin."""

    def info(self, texte, auteur=None, projet=None, type_code="information"):
        return self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, %s, %s) "
                        "RETURNING id", (projet or self.p1, auteur or self.inter, type_code, texte))[0]["id"]

    def epingles(self):
        return [x["id"] for x in self.sql("SELECT id FROM post WHERE epingle_le IS NOT NULL ORDER BY id")]

    def test_un_seul_post_epingle_en_tete_et_pas_repete(self):
        a, b = self.info("Accès chantier : code 12"), self.info("Réunion lundi")
        self.login(self.chef)
        page = self.texte(self.client.get(f"/projets/{self.p1}"))
        self.assertIn(f'action="/posts/{a}/epingler"', page)
        r = self.client.post(f"/posts/{a}/epingler", headers=partiel("#fil-epingle"))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertIn('id="fil-epingle"', self.texte(r))
        self.assertEqual(self.epingles(), [a])
        self.client.post(f"/posts/{b}/epingler", headers=partiel("#fil-epingle"))
        self.assertEqual(self.epingles(), [b])
        self.login(self.inter)
        page = self.texte(self.client.get(f"/projets/{self.p1}?fil=activite"))
        zone = page.split('id="fil-epingle"')[1].split('id="fil-posts"')[0]
        self.assertIn("Épinglé", zone)
        self.assertIn("Réunion lundi", zone)
        self.assertEqual(page.count(f'id="post-{b}"'), 1)
        # Lot 24 (revue SR-R04) : sur « Tout », où une Information est dans la
        # liste, le post épinglé n'y est pas répété.
        self.assertEqual(self.texte(self.client.get(f"/projets/{self.p1}?fil=tout")).count(f'id="post-{b}"'), 1)
        self.assertNotIn(f'action="/posts/{b}/desepingler"', page)      # l'intervenant n'épingle pas
        # Lot 24 (mutant E3) : désépingler est réservé à qui gère le projet.
        self.assertEqual(self.client.post(f"/posts/{b}/desepingler", headers=partiel("#fil-epingle")).status_code, 403)
        self.assertEqual(self.epingles(), [b])
        # Sur l'accueil : la mention « Épinglé » sur la carte.
        accueil = self.texte(self.client.get("/accueil"))
        self.assertIn("pill-epingle", accueil)

    def test_droits_et_types(self):
        a = self.info("Info")
        self.login(self.inter)
        self.assertEqual(self.client.post(f"/posts/{a}/epingler").status_code, 403)
        requete = self.info("Objet\n\nTexte", type_code="requete")
        self.login(self.chef)
        r = self.client.post(f"/posts/{requete}/epingler", headers=partiel("#fil-epingle"))
        self.assertEqual(r.status_code, 422)
        self.sql("UPDATE projet SET etat = 'termine' WHERE id = %s", (self.p1,))
        self.assertEqual(self.client.post(f"/posts/{a}/epingler", headers=partiel("#fil-epingle")).status_code, 409)
        self.assertEqual(self.epingles(), [])
        import psycopg2

        with self.assertRaises(psycopg2.Error):     # garde en base : jamais deux par projet
            self.sql("UPDATE post SET epingle_le = now() WHERE id IN (%s, %s)", (a, self.info("Autre")))

    def test_desepingler_et_suppression(self):
        a = self.info("Info")
        self.login(self.chef)
        self.client.post(f"/posts/{a}/epingler")
        r = self.client.post(f"/posts/{a}/desepingler")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.epingles(), [])
        self.client.post(f"/posts/{a}/epingler")
        self.client.post(f"/posts/{a}/supprimer", headers=partiel(f"#post-{a}"))
        self.assertEqual(self.epingles(), [])
        page = self.texte(self.client.get(f"/projets/{self.p1}"))
        self.assertNotIn('class="fil-epingle"', page)


class TestFilMeConcernant(_Lot20):
    """Demande du gérant (19/10) : sur la fiche projet, une bascule pour ne
    voir que ce qui me concerne — mes posts, ceux où je suis tagué (post ou
    commentaire) et les suites données à mes posts."""

    def post(self, auteur, texte, parent=None):
        return self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu, parent_post_id) VALUES "
                        "(%s, %s, 'information', %s, %s) RETURNING id", (self.p1, auteur, texte, parent))[0]["id"]

    def test_bascule(self):
        autre = self.user("intervenant")
        mien = self.post(self.inter, "Mon post")
        tague = self.post(self.chef, "Pour Rim")
        self.sql("INSERT INTO post_mention (post_id, utilisateur_id) VALUES (%s, %s)", (tague, self.inter))
        commente = self.post(self.chef, "Commenté pour Rim")
        c = self.sql("INSERT INTO post_commentaire (post_id, auteur_id, contenu) VALUES (%s, %s, 'Vu @Rim') "
                     "RETURNING id", (commente, autre))[0]["id"]
        self.sql("INSERT INTO post_commentaire_mention (commentaire_id, utilisateur_id) VALUES (%s, %s)",
                 (c, self.inter))
        suite = self.post(self.chef, "Suite donnée", parent=mien)
        etranger = self.post(self.chef, "Rien à voir")
        supprime = self.post(self.chef, "Mention retirée")
        c2 = self.sql("INSERT INTO post_commentaire (post_id, auteur_id, contenu, supprime_le) VALUES "
                      "(%s, %s, 'x', now()) RETURNING id", (supprime, autre))[0]["id"]
        self.sql("INSERT INTO post_commentaire_mention (commentaire_id, utilisateur_id) VALUES (%s, %s)",
                 (c2, self.inter))
        self.login(self.inter)
        tout = self.texte(self.client.get(f"/projets/{self.p1}?fil=tout"))
        for pid in (mien, tague, commente, suite, etranger, supprime):
            self.assertIn(f'id="post-{pid}"', tout)
        self.assertIn('role="switch"', tout)
        self.assertIn('aria-checked="false"', tout)
        r = self.client.get(f"/projets/{self.p1}?fil=tout&moi=1", headers=partiel("#fil-posts"))
        moi = self.texte(r)
        self.assertIn('data-fil-moi="1"', moi)
        for pid in (mien, tague, commente, suite):
            self.assertIn(f'id="post-{pid}"', moi)
        for pid in (etranger, supprime):
            self.assertNotIn(f'id="post-{pid}"', moi)
        page = self.texte(self.client.get(f"/projets/{self.p1}?fil=tout&moi=1"))
        self.assertIn('aria-checked="true"', page)

    def test_rien_ne_me_concerne(self):
        self.post(self.chef, "Rien à voir")
        self.login(self.inter)
        page = self.texte(self.client.get(f"/projets/{self.p1}?fil=tout&moi=1"))
        self.assertIn("Rien ne vous concerne ici", page)
        self.assertNotIn("Rien à voir", page)

    def test_action_en_partiel_garde_la_bascule(self):
        self.post(self.chef, "Rien à voir")
        self.login(self.inter)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Plans"},
                             headers={**partiel(f"#tache-fenetre-{self.t1}"),
                                      "Referer": f"http://localhost/projets/{self.p1}?fil=tout&moi=1"})
        self.assertEqual(r.status_code, 200)
        from app import fil as film

        with self.app.test_request_context("/x", method="POST",
                                           headers={"Referer": f"http://localhost/projets/{self.p1}?moi=1"}):
            self.assertTrue(film.moi_demande())

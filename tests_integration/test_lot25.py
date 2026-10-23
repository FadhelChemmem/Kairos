"""Lot 25, tests d'intégration (vraie base) : vérification complète du
23/10/2026 après le lot 24 et décisions du gérant du 23/10."""
import datetime
import json
import os
from unittest import mock

from tests_integration.test_lot20 import _Lot20, partiel, toasts  # noqa: F401


class _Push(_Lot20):
    MODE_TEST = True

    def setUp(self):
        super().setUp()
        from app import push
        self.push = push
        cles = push.generer_cles()
        self.cles = cles
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

    def login(self, user_id):
        """Connexion qui suit la génération de sessions du compte (après une
        déconnexion, l'ancienne génération ne vaut plus)."""
        super().login(user_id)
        ligne = self.sql("SELECT generation FROM utilisateur_session WHERE utilisateur_id = %s", (user_id,))
        with self.client.session_transaction() as s:
            s["gen"] = ligne[0]["generation"] if ligne else 0

    def cle_navigateur(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        point = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return self.push.b64url(point)

    def abonner(self, uid, endpoint="https://fcm.googleapis.com/fcm/send/abc", cle=None, auth=b"a" * 16, login=True):
        if login:
            self.login(uid)
        return self.client.post("/push/abonnement", json={"endpoint": endpoint,
                                                          "keys": {"p256dh": cle or self.cle_navigateur(),
                                                                   "auth": self.push.b64url(auth)}})

    def nb_abonnements(self, uid=None):
        if uid is None:
            return self.compter("SELECT count(*) AS n FROM push_abonnement")
        return self.compter("SELECT count(*) AS n FROM push_abonnement WHERE utilisateur_id = %s", (uid,))


class TestPushLot25(_Push):
    def test_adresse_interne_refusee(self):
        """PU-01 : SSRF."""
        for endpoint in ("https://127.0.0.1/x", "https://localhost/x", "https://169.254.169.254/latest",
                         "https://kairos-db/x", "https://10.0.0.5/x"):
            with self.subTest(endpoint=endpoint):
                r = self.abonner(self.inter, endpoint)
                self.assertEqual(r.status_code, 400)
        self.assertEqual(self.nb_abonnements(), 0)

    def test_corps_json_qui_n_est_pas_un_objet(self):
        """PU-07 : jamais de 500."""
        self.login(self.inter)
        for url in ("/push/etat", "/push/abonnement", "/push/desabonnement"):
            for corps in ('"texte"', "5", "[1]", "true"):
                with self.subTest(url=url, corps=corps):
                    r = self.client.post(url, data=corps, content_type="application/json")
                    self.assertIn(r.status_code, (200, 400))

    def test_session_expiree_repond_en_json(self):
        """PU-09 : 401 JSON, jamais une redirection prise pour un succès."""
        for url in ("/push/abonnement", "/push/essai", "/push/etat", "/push/desabonnement"):
            r = self.client.post(url, json={})
            self.assertEqual(r.status_code, 401, url)
            self.assertEqual(r.get_json()["erreur"], "non_connecte")
        self.assertEqual(self.client.get("/push/cle").status_code, 401)

    def test_appropriation_refusee_et_meme_navigateur_repris(self):
        """PU-04 : un endpoint connu avec d'autres clés n'est pas repris ; le
        même navigateur (mêmes clés) passe au nouveau compte."""
        cle = self.cle_navigateur()
        self.assertEqual(self.abonner(self.inter, cle=cle).status_code, 200)
        self.assertEqual(self.abonner(self.chef, auth=b"b" * 16).status_code, 400)
        self.assertEqual(self.nb_abonnements(self.inter), 1)
        self.assertEqual(self.abonner(self.chef, cle=cle).status_code, 200)
        self.assertEqual((self.nb_abonnements(self.inter), self.nb_abonnements(self.chef)), (0, 1))

    def test_au_plus_dix_appareils(self):
        """PU-11."""
        self.login(self.inter)
        for i in range(12):
            self.abonner(self.inter, f"https://fcm.googleapis.com/fcm/send/{i}", login=False)
            self.sql("UPDATE push_abonnement SET vu_le = now() - make_interval(secs => %s) WHERE endpoint = %s",
                     (100 - i, f"https://fcm.googleapis.com/fcm/send/{i}"))
        self.assertEqual(self.nb_abonnements(self.inter), 10)
        restants = {r["endpoint"] for r in self.sql("SELECT endpoint FROM push_abonnement")}
        self.assertNotIn("https://fcm.googleapis.com/fcm/send/0", restants)
        self.assertIn("https://fcm.googleapis.com/fcm/send/11", restants)

    def test_deconnexion_et_mot_de_passe_retirent_les_appareils(self):
        """Décision du gérant du 23/10 (PU-05)."""
        self.assertEqual(self.abonner(self.inter).status_code, 200)
        self.client.post("/deconnexion")
        self.assertEqual(self.nb_abonnements(self.inter), 0)
        self.assertEqual(self.abonner(self.inter).status_code, 200)
        self.sql("UPDATE utilisateur SET mot_de_passe_hash = 'autre' WHERE id = %s", (self.inter,))
        self.assertEqual(self.nb_abonnements(self.inter), 0)
        self.abonner(self.chef)
        self.sql("UPDATE utilisateur SET actif = false WHERE id = %s", (self.chef,))
        self.assertEqual(self.nb_abonnements(self.chef), 0)
        # Une autre mise à jour du compte ne touche à rien.
        self.sql("UPDATE utilisateur SET mot_de_passe_hash = 'h' WHERE id = %s", (self.inter,))
        self.abonner(self.inter)
        self.sql("UPDATE utilisateur SET telephone = '0102' WHERE id = %s", (self.inter,))
        self.assertEqual(self.nb_abonnements(self.inter), 1)

    def test_cle_serveur_changee(self):
        """PU-12 : après un changement de clés, « Activer » est de nouveau proposé."""
        self.abonner(self.inter)
        etat = lambda: self.client.post("/push/etat", json={"endpoint": "https://fcm.googleapis.com/fcm/send/abc"}).get_json()  # noqa: E731
        self.assertTrue(etat()["abonne"])
        nouvelles = self.push.generer_cles()
        with mock.patch.dict(os.environ, {"VAPID_PRIVATE_KEY": nouvelles["VAPID_PRIVATE_KEY"],
                                          "VAPID_PUBLIC_KEY": nouvelles["VAPID_PUBLIC_KEY"]}):
            self.assertFalse(etat()["abonne"])
            self.client.post("/push/essai")
            self.assertEqual(self.envois, [])

    def test_attente_reservee_une_seule_fois(self):
        """PU-10 : notification marquée en attente, poussée une fois."""
        from app.repositories import notifications as notifications_repo
        from app.repositories import push as push_repo
        self.abonner(self.inter)
        self.app.config["PUSH_DELAI"] = 30
        with self.app.test_request_context("/"), mock.patch.object(self.push, "_lancer"), \
             mock.patch.object(self.push, "_file") as file:
            from flask import g
            g.user = None
            notifications_repo.creer(self.inter, "projet", "Ali vous a mentionné.", projet_id=self.p1)
        self.assertEqual(file.put.call_count, 1)
        en_attente = push_repo.en_attente_recentes(30)
        self.assertEqual(len(en_attente), 1)
        nid = en_attente[0]["id"]
        self.assertGreater(float(en_attente[0]["reste"]), 20)
        self.assertEqual(self.push.traiter([nid]), 1)
        self.assertEqual(self.push.traiter([nid]), 0)
        self.assertEqual(push_repo.en_attente_recentes(30), [])

    def test_essai_limite_et_appareil_retire(self):
        """PU-14, U4."""
        self.abonner(self.inter)
        self.assertEqual(self.client.post("/push/essai").status_code, 200)
        self.assertEqual(self.client.post("/push/essai").status_code, 429)
        self.assertEqual(len(self.envois), 1)
        page = self.texte(self.client.get("/utilisateurs/moi"))
        self.assertIn("Appareils qui reçoivent vos notifications", page)
        aid = self.sql("SELECT id FROM push_abonnement WHERE utilisateur_id = %s", (self.inter,))[0]["id"]
        # Un autre compte ne retire rien.
        self.login(self.chef)
        self.client.post(f"/push/appareils/{aid}/retirer")
        self.assertEqual(self.nb_abonnements(self.inter), 1)
        self.login(self.inter)
        r = self.client.post(f"/push/appareils/{aid}/retirer")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.nb_abonnements(self.inter), 0)

    def test_titre_parlant(self):
        """Décision du gérant (22/10) : titre = projet et tâche, ou Daily log."""
        from app.repositories import notifications as notifications_repo
        self.abonner(self.inter)
        with self.app.test_request_context("/"):
            from flask import g
            g.user = None
            notifications_repo.creer(self.inter, "projet", "Ali a bloqué la tâche.", projet_id=self.p1,
                                     tache_id=self.t1)
        titre = self.envois[-1][1]["titre"]
        code, tache = self.sql("SELECT p.code, t.titre FROM tache t JOIN projet p ON p.id = t.projet_id "
                               "WHERE t.id = %s", (self.t1,))[0].values()
        self.assertEqual(titre, f"{code} · {tache}")


class TestSuiviAB(_Lot20):
    """Annexes A et B du rapport du 23/10."""
    MODE_TEST = True

    def test_reprise_chronos_bloquee_puis_debloquee(self):
        """SB-05 : bloquée par la reprise (sans post), levée dans l'appli :
        pas proposée les jours où elle était bloquée."""
        from app.repositories import dailylog as dl
        j = lambda n: self.auj - datetime.timedelta(days=n)  # noqa: E731
        self.sql("UPDATE tache SET created_at = now() - interval '40 days' WHERE id = %s", (self.t1,))
        self.sql("UPDATE projet SET created_at = now() - interval '40 days' WHERE id = %s", (self.p1,))
        self.sql("ALTER TABLE tache DISABLE TRIGGER USER")
        try:
            self.sql("UPDATE tache SET etat = 'en_cours', bloque_le = %s::date + time '09:00', bloque_motif = 'Chronos' "
                     "WHERE id = %s", (j(9), self.t1))
        finally:
            self.sql("ALTER TABLE tache ENABLE TRIGGER USER")
        self.sql("INSERT INTO post (projet_id, tache_id, auteur_id, type_code, contenu, evenement, created_at) "
                 "VALUES (%s, %s, %s, 'information', 'x', 'deblocage_tache', %s::date + time '10:00')",
                 (self.p1, self.t1, self.chef, j(6)))
        user = self.sql("SELECT * FROM utilisateur WHERE id = %s", (self.inter,))[0]
        propose = lambda n: any(l["tache_id"] == self.t1 for l in dl.lignes_proposees(user, j(n)))  # noqa: E731
        self.assertTrue(propose(10))
        self.assertFalse(propose(8))
        self.assertFalse(propose(7))
        self.assertTrue(propose(6))

    def test_mode_test_jamais_avant_et_ordre_des_gestes(self):
        """SB-03, SA-L25-05 : réaction, réponse, post automatique et nouvelle
        tâche jamais datés avant ce qu'ils suivent ; la tâche créée après le
        blocage débloque le projet."""
        post = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', "
                        "'Créé réel') RETURNING id, created_at", (self.p1, self.chef))[0]
        reelle = self.tache(self.p1, self.chef, intervenants=[self.inter])
        cree = self.sql("SELECT created_at FROM tache WHERE id = %s", (reelle,))[0]["created_at"]
        self.entrer(self.chef, mode="agir")
        self.client.post("/admin/date-simulee", data={"date": (self.auj - datetime.timedelta(days=5)).isoformat(),
                                                      "heure": "10:00"})
        self.client.post(f"/posts/{post['id']}/reagir", data={"reaction_code": "pouce"})
        reaction = self.sql("SELECT created_at FROM post_reaction WHERE post_id = %s", (post["id"],))
        if reaction:
            self.assertGreaterEqual(reaction[0]["created_at"], post["created_at"])
        self.client.post("/posts", data={"projet_id": str(self.p1), "type_code": "information",
                                         "contenu": "Réponse", "parent_post_id": str(post["id"])})
        reponse = self.sql("SELECT created_at FROM post WHERE parent_post_id = %s", (post["id"],))
        self.assertTrue(reponse)
        self.assertGreaterEqual(reponse[0]["created_at"], post["created_at"])
        self.client.post(f"/projets/{self.p1}/taches/{reelle}/etat", data={"etat": "bloque", "motif": "Plans"},
                         headers=partiel("#x"))
        auto = self.sql("SELECT created_at FROM post WHERE tache_id = %s AND evenement = 'blocage_tache'", (reelle,))
        self.assertTrue(auto)
        self.assertGreaterEqual(auto[0]["created_at"], cree)
        self.assertEqual(self.etat_projet(self.p1), "bloque")
        self.client.post(f"/projets/{self.p1}/taches", data={"titre": "Créée après"}, headers=partiel("#x"))
        self.assertEqual(self.etat_projet(self.p1), "en_cours")

    def test_filtrer_sans_js_puis_f5(self):
        """SB-07 : « Filtrer » sans JS → 303 vers l'adresse sans `choix`."""
        self.login(self.chef)
        r = self.client.get("/projets?filtres_actifs=1&etat=termine&choix=1")
        self.assertEqual(r.status_code, 303)
        self.assertNotIn("choix", r.headers["Location"])
        self.assertIn("etat=termine", r.headers["Location"])
        self.assertEqual(self.client.get(r.headers["Location"]).status_code, 200)

    def test_chef_inconnu_ignore_et_pas_d_enumeration(self):
        """SB-09 et annexe C : un `chef_id` qui n'est chef d'aucun projet ne
        filtre rien et ne montre ni nom ni photo."""
        cachee = self.user("intervenant")
        self.sql("UPDATE utilisateur SET nom = 'Personne Cachée' WHERE id = %s", (cachee,))
        self.login(self.chef)
        page = self.texte(self.client.get(f"/projets?filtres_actifs=1&chef_id={cachee}&chef_id=999999"))
        self.assertNotIn("Personne Cachée", page)
        self.assertNotIn('value="999999"', page)

    def test_annuler_garde_la_version_du_geste(self):
        """Mutant M8 : la version du jeton est celle du geste (lue dans sa
        transaction), pas relue après coup."""
        from app.repositories import taches
        self.login(self.inter)
        with mock.patch.object(taches, "version", return_value="relue-apres-coup"):
            r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat",
                                 data={"etat": "bloque", "motif": "Plans"}, headers=partiel("#x"))
        self.assertEqual(self.etat_tache(self.t1), "bloque")
        r = self.annuler(r)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.etat_tache(self.t1), "en_cours")

    def test_reponse_aux_seules_equipes_actives(self):
        """Mutant M20 : une réponse à une Information d'équipe ne part pas
        vers une équipe qui n'existe plus."""
        self.sql("INSERT INTO equipe (code, libelle) VALUES ('IPCO', 'IPCO') ON CONFLICT DO NOTHING")
        parent = self.sql("INSERT INTO post (auteur_id, type_code, contenu) VALUES (%s, 'information', 'Équipes') "
                          "RETURNING id", (self.chef,))[0]["id"]
        self.sql("INSERT INTO post_equipe (post_id, equipe_code) VALUES (%s, 'IPCO'), (%s, 'MIDGARD')",
                 (parent, parent))
        self.login(self.chef)
        self.client.post("/posts", data={"type_code": "information", "contenu": "Réponse",
                                         "parent_post_id": str(parent)})
        reponse = self.sql("SELECT id FROM post WHERE parent_post_id = %s", (parent,))[0]["id"]
        self.assertEqual([r["equipe_code"] for r in self.sql(
            "SELECT equipe_code FROM post_equipe WHERE post_id = %s ORDER BY 1", (reponse,))], ["MIDGARD"])


class TestProjetsLot25(_Lot20):
    """Annexe C du rapport du 23/10."""

    def informations(self, projet_id, **champs):
        return self.client.post(f"/projets/{projet_id}/informations", data=champs, headers=partiel("#informations-form"))

    def lots(self, projet_id):
        return [r["lot_code"] for r in self.sql("SELECT lot_code FROM projet_lot WHERE projet_id = %s ORDER BY 1",
                                                (projet_id,))]

    def test_phase_liee_invisible_conservee(self):
        """PR-01 : renommer ne vide plus une phase liée que l'éditeur ne voit pas."""
        autre = self.projet(self.user("chef_de_projet", equipe="URBS"), equipe="URBS")
        self.sql("UPDATE projet SET phase_liee_id = %s WHERE id = %s", (autre, self.p1))
        self.login(self.chef)
        page = self.texte(self.client.get(f"/projets/{self.p1}/informations"))
        self.assertIn("Liée à un projet que vous ne voyez pas", page)
        r = self.informations(self.p1, nom="Renommé", etat="en_cours", lots="GO", lots_envoyes="1", phase_liee_id="")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        ligne = self.sql("SELECT nom, phase_liee_id FROM projet WHERE id = %s", (self.p1,))[0]
        self.assertEqual((ligne["nom"], ligne["phase_liee_id"]), ("Renommé", autre))

    def test_champs_absents_inchanges_et_doublons(self):
        """PR-07, PR-08, PR-09."""
        self.sql("INSERT INTO projet_lot (projet_id, lot_code) VALUES (%s, 'GO'), (%s, 'CM') ON CONFLICT DO NOTHING",
                 (self.p1, self.p1))
        self.sql("UPDATE projet SET client = 'Client A', honoraires = 1200, date_debut = current_date - 40 "
                 "WHERE id = %s", (self.p1,))
        self.login(self.chef)
        r = self.informations(self.p1, nom="Sans lots", etat="en_cours")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        ligne = self.sql("SELECT client, honoraires, date_debut FROM projet WHERE id = %s", (self.p1,))[0]
        self.assertEqual((ligne["client"], float(ligne["honoraires"])), ("Client A", 1200.0))
        self.assertIsNotNone(ligne["date_debut"])
        self.assertEqual(self.lots(self.p1), ["CM", "GO"])
        r = self.client.post(f"/projets/{self.p1}/informations",
                             data={"nom": "Doublon", "etat": "en_cours", "lots": ["CM", "CM"], "lots_envoyes": "1"},
                             headers=partiel("#informations-form"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.lots(self.p1), ["CM"])
        r = self.informations(self.p1, nom="Soi", etat="en_cours", lots="CM", lots_envoyes="1",
                              phase_liee_id=str(self.p1))
        self.assertEqual(r.status_code, 422)

    def test_creation_controles(self):
        """PR-03, PR-05, PR-06."""
        self.login(self.chef)
        base = {"nom": "Nouveau", "phase": "EXE", "lots_envoyes": "1"}
        r = self.client.post("/projets/nouveau", data={**base, "code": "26901X", "lots": ["CM", "CM"]},
                             headers=partiel("#projet-dialog-form"))
        self.assertIn(r.status_code, (200, 204, 302), r.get_data(as_text=True)[:300])
        pid = self.sql("SELECT id FROM projet WHERE code = '26901X'")[0]["id"]
        self.assertEqual(self.lots(pid), ["CM"])
        r = self.client.post("/projets/nouveau", data={**base, "code": "26902X", "lots": "CM",
                                                       "honoraires": "9999999999,995"},
                             headers=partiel("#projet-dialog-form"))
        self.assertEqual(r.status_code, 422)
        self.assertIn("Honoraires", r.get_data(as_text=True))
        r = self.client.post("/projets/nouveau", data={**base, "code": "26903X", "lots": "CM", "chef_projet_id": "abc"},
                             headers=partiel("#projet-dialog-form"))
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet WHERE code IN ('26902X', '26903X')"), 0)

    def test_retour_aux_projets_et_phase_suivante(self):
        """Demande du gérant (23/10) et U7."""
        suite = self.projet(self.chef)
        self.sql("UPDATE projet SET phase_liee_id = %s, code = '26777D' WHERE id = %s", (self.p1, suite))
        self.login(self.chef)
        page = self.texte(self.client.get(f"/projets/{self.p1}"))
        self.assertIn("Retour aux projets", page)
        self.assertIn("Phase suivante", page)
        self.assertIn("26777D", page)


class TestTachesLot25(_Lot20):
    """Annexe D du rapport du 23/10."""

    def test_annuler_un_retrait_d_intervenant(self):
        """TA-01 : ni second post ni seconde notification."""
        self.login(self.chef)
        avant_posts = self.compter("SELECT count(*) AS n FROM post WHERE evenement = 'intervenant_tache'")
        avant_notifs = self.compter("SELECT count(*) AS n FROM notification WHERE utilisateur_id = %s", (self.inter,))
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/intervenants/{self.inter}/retirer",
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM tache_intervenant WHERE tache_id = %s AND "
                                      "utilisateur_id = %s", (self.t1, self.inter)), 0)
        r = self.annuler(r)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.compter("SELECT count(*) AS n FROM tache_intervenant WHERE tache_id = %s AND "
                                      "utilisateur_id = %s", (self.t1, self.inter)), 1)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM post WHERE evenement = 'intervenant_tache'"),
                         avant_posts)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE utilisateur_id = %s",
                                      (self.inter,)), avant_notifs)

    def test_rejoindre_co_chef_signale_et_croise(self):
        """TA-03, TA-11."""
        chef2 = self.user("chef_de_projet")
        self.login(chef2)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/rejoindre", headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("co-chef", json.dumps(toasts(r), ensure_ascii=False))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE utilisateur_id = %s "
                                      "AND message LIKE %s", (self.chef, "%co-chef%")), 1)
        autre_projet = self.projet(self.chef)
        autre_tache = self.tache(autre_projet, self.chef)
        r = self.client.post(f"/projets/{self.p1}/taches/{autre_tache}/rejoindre", headers=partiel("#x"))
        self.assertEqual(r.status_code, 404)

    def test_titre_invisible_refuse(self):
        """TA-04."""
        self.login(self.chef)
        for titre in ("​", "​​", "﻿  "):
            r = self.client.post(f"/projets/{self.p1}/taches", data={"titre": titre}, headers=partiel("#x"))
            self.assertEqual(r.status_code, 422, repr(titre))
        r = self.client.post(f"/projets/{self.p1}/taches", data={"titre": "Ligne1\nLigne2"}, headers=partiel("#x"))
        self.assertLess(r.status_code, 400)
        self.assertEqual(self.sql("SELECT titre FROM tache ORDER BY id DESC LIMIT 1")[0]["titre"], "Ligne1 Ligne2")

    def test_meme_etat_rien_ecrit(self):
        """TA-05."""
        self.login(self.inter)
        version = self.sql("SELECT updated_at FROM tache WHERE id = %s", (self.t1,))[0]["updated_at"]
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "en_cours"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("déjà", json.dumps(toasts(r), ensure_ascii=False))
        self.assertEqual(self.sql("SELECT updated_at FROM tache WHERE id = %s", (self.t1,))[0]["updated_at"], version)

    def test_annuler_reouverture_retire_le_co_chef(self):
        """TA-06."""
        chef2 = self.user("chef_de_projet")
        close = self.tache(self.p1, self.chef, etat="abandonne", intervenants=[chef2])
        self.sql("DELETE FROM projet_co_chef WHERE projet_id = %s AND utilisateur_id = %s", (self.p1, chef2))
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p1}/taches/{close}/etat", data={"etat": "en_cours"},
                             headers=partiel(f"#tache-fenetre-{close}"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet_co_chef WHERE projet_id = %s AND "
                                      "utilisateur_id = %s", (self.p1, chef2)), 1)
        r = self.annuler(r)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.etat_tache(close), "abandonne")
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet_co_chef WHERE projet_id = %s AND "
                                      "utilisateur_id = %s", (self.p1, chef2)), 0)

    def test_date_de_fin_par_script(self):
        """TA-09 : clôture par UPDATE = date du jour."""
        self.sql("ALTER TABLE tache DISABLE TRIGGER trg_tache_updated_at")
        try:
            self.sql("UPDATE tache SET updated_at = now() - interval '300 days' WHERE id = %s", (self.t1,))
        finally:
            self.sql("ALTER TABLE tache ENABLE TRIGGER trg_tache_updated_at")
        self.sql("UPDATE tache SET etat = 'termine' WHERE id = %s", (self.t1,))
        fin = self.sql("SELECT date_fin, (now() AT TIME ZONE 'Africa/Tunis')::date AS auj FROM tache WHERE id = %s",
                       (self.t1,))[0]
        self.assertEqual(fin["date_fin"], fin["auj"])

    def test_annuler_un_blocage_retire_la_carte_du_fil(self):
        """TA-02 : la réponse de « Annuler » rend le fil sans le post retiré."""
        self.login(self.inter)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Fantome"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        post = self.sql("SELECT id FROM post WHERE evenement = 'blocage_tache' AND tache_id = %s", (self.t1,))[0]["id"]
        r = self.annuler(r)
        html = r.get_data(as_text=True)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM post WHERE id = %s", (post,)), 0)
        self.assertIn('id="fil-posts"', html)
        self.assertNotIn(f'id="post-{post}"', html)


class TestFilLot25(_Lot20):
    """Annexe E du rapport du 23/10 (fil, posts, notifications)."""

    def setUp(self):
        super().setUp()
        self.sql("UPDATE utilisateur SET prenom = 'Ali', nom = 'Chef' WHERE id = %s", (self.chef,))
        self.sami = self.user("intervenant", equipe="URBS")
        self.sql("UPDATE utilisateur SET prenom = 'Sami', nom = 'Trabelsi' WHERE id = %s", (self.sami,))

    def nb_notifs(self, uid):
        return self.compter("SELECT count(*) AS n FROM notification WHERE utilisateur_id = %s", (uid,))

    def test_mention_ecrite_dans_un_nouveau_post(self):
        """FL-02 : même règle à la création qu'en modification ; U7 : jamais soi-même."""
        self.login(self.chef)
        avant = self.nb_notifs(self.inter)
        self.client.post("/posts", data={"projet_id": str(self.p1), "type_code": "information",
                                         "contenu": "Bonjour @Rim Inter, voir plan.", "mentions": [str(self.chef)]})
        p = self.sql("SELECT id FROM post WHERE contenu LIKE 'Bonjour @Rim%%'")[0]["id"]
        mentions = [r["utilisateur_id"] for r in self.sql("SELECT utilisateur_id FROM post_mention WHERE post_id = %s",
                                                          (p,))]
        self.assertEqual(mentions, [self.inter])
        self.assertEqual(self.nb_notifs(self.inter), avant + 1)
        self.client.post(f"/posts/{p}/modifier", data={"contenu": "Bonjour @Rim Inter : voir plan."})
        self.assertEqual(self.nb_notifs(self.inter), avant + 1)

    def test_mention_ecartee_signalee(self):
        """U5 : une personne qui ne voit pas le post n'est pas taguée, et on le dit."""
        post = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', "
                        "'Plan') RETURNING id", (self.p1, self.chef))[0]["id"]
        self.login(self.chef)
        r = self.client.post(f"/posts/{post}/commenter", data={"contenu": "Vu avec @Sami Trabelsi"},
                             headers=partiel(f"#post-{post}-commentaires"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any("Sami Trabelsi ne voit pas ce post" in t["texte"] for t in toasts(r)), toasts(r))
        self.assertEqual(self.nb_notifs(self.sami), 0)

    def test_notifications_au_dela_de_50(self):
        """FL-04 : « Afficher plus » rend les plus anciennes atteignables."""
        self.sql("INSERT INTO notification (utilisateur_id, categorie, message, created_at) "
                 "SELECT %s, 'projet', 'Notif '||g, now() - g * interval '1 minute' FROM generate_series(1, 70) g",
                 (self.inter,))
        self.login(self.inter)
        html = self.client.get("/notifications").get_data(as_text=True)
        self.assertEqual(html.count('class="notif-ligne'), 50)
        self.assertIn('href="/notifications?n=100"', html)
        html = self.client.get("/notifications?n=100", headers=partiel("#notifications-liste")).get_data(as_text=True)
        self.assertEqual(html.count('class="notif-ligne'), self.nb_notifs(self.inter))
        self.assertNotIn("Afficher plus", html)
        self.assertIn("data-partiel-titre", html)

    def test_pieces_d_un_commentaire_bornees(self):
        """FL-05 : au plus 10 pièces actives sur un commentaire."""
        import io
        post = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', "
                        "'Plan') RETURNING id", (self.p1, self.chef))[0]["id"]
        c = self.sql("INSERT INTO post_commentaire (post_id, auteur_id, contenu) VALUES (%s, %s, 'Pièces') "
                     "RETURNING id", (post, self.inter))[0]["id"]
        self.sql("INSERT INTO post_commentaire_piece_jointe (commentaire_id, nom_fichier, chemin, uploaded_by) "
                 "SELECT %s, 'f'||g||'.pdf', 'x/f'||g, %s FROM generate_series(1, 10) g", (c, self.inter))
        self.login(self.inter)
        r = self.client.post(f"/posts/commentaires/{c}/modifier",
                             data={"contenu": "Pièces", "fichier": (io.BytesIO(b"%PDF-1.4\n%%EOF\n"), "g.pdf")},
                             content_type="multipart/form-data", headers=partiel(f"#post-{post}-commentaires"))
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM post_commentaire_piece_jointe WHERE "
                                      "commentaire_id = %s AND retire_le IS NULL", (c,)), 10)

    def test_notification_d_un_post_supprime_et_d_un_commentaire(self):
        """U2 : message et fiche sans recherche ; U3 : le commentaire est visé."""
        post = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', "
                        "'Plan') RETURNING id", (self.p1, self.chef))[0]["id"]
        c = self.sql("INSERT INTO post_commentaire (post_id, auteur_id, contenu) VALUES (%s, %s, 'Vu') RETURNING id",
                     (post, self.chef))[0]["id"]
        n1 = self.sql("INSERT INTO notification (utilisateur_id, categorie, message, post_id, commentaire_id) "
                      "VALUES (%s, 'projet', 'm', %s, %s) RETURNING id", (self.inter, post, c))[0]["id"]
        n2 = self.sql("INSERT INTO notification (utilisateur_id, categorie, message, post_id) "
                      "VALUES (%s, 'projet', 'm', %s) RETURNING id", (self.inter, post))[0]["id"]
        self.login(self.inter)
        r = self.client.post(f"/notifications/{n1}/ouvrir")
        self.assertIn(f"commentaire={c}", r.headers["Location"])
        self.assertIn(f"jusqua={post}", r.headers["Location"])
        self.sql("UPDATE post SET supprime_le = now() WHERE id = %s", (post,))
        r = self.client.post(f"/notifications/{n2}/ouvrir")
        self.assertTrue(r.headers["Location"].endswith(f"/projets/{self.p1}"), r.headers["Location"])
        with self.client.session_transaction() as s:
            self.assertIn("Ce post a été supprimé.", [m for _, m in s.get("_flashes", [])])

    def test_categorie_absente_de_la_premiere_page(self):
        """FL-03 : une rafale d'évènements automatiques ne fait plus perdre un échange."""
        from app.repositories import posts as posts_repo

        self.login(self.inter)
        self.client.get("/accueil?fil=tout")
        self.sql("UPDATE utilisateur_fil_vu SET vu_le = now() - interval '1 hour' WHERE utilisateur_id = %s",
                 (self.inter,))
        info = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu, created_at) VALUES "
                        "(%s, %s, 'information', 'INFO IMPORTANTE', clock_timestamp() - interval '1 minute') "
                        "RETURNING created_at", (self.p1, self.chef))[0]["created_at"]
        self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu, evenement, tache_id, created_at) "
                 "SELECT %s, %s, 'information', 'Échéance '||g, 'echeance_tache', %s, "
                 "clock_timestamp() - interval '30 s' + g * interval '1 ms' FROM generate_series(1, 25) g",
                 (self.p1, self.chef, self.t1))
        self.client.get("/accueil?fil=tout")
        with self.app.app_context():
            vus = posts_repo.fil_vu(self.inter)
        self.assertLess(vus["echanges"], info)
        html = self.client.get("/accueil?fil=echanges").get_data(as_text=True)
        self.assertIn("INFO IMPORTANTE", html)


class TestDailyLogLot25(_Lot20):
    """Annexe F du rapport du 23/10 (Daily log, horloge)."""

    def setUp(self):
        super().setUp()
        self.sql("UPDATE tache SET created_at = now() - interval '30 days' WHERE id = %s", (self.t1,))
        self.sql("UPDATE projet SET created_at = now() - interval '30 days' WHERE id = %s", (self.p1,))
        self.u = self.sql("SELECT * FROM utilisateur WHERE id = %s", (self.inter,))[0]

    def j(self, n):
        return self.auj - datetime.timedelta(days=n)

    def propose_tache(self, n):
        from app.repositories import dailylog as dl
        return any(l["tache_id"] == self.t1 for l in dl.lignes_proposees(self.u, self.j(n)))

    def test_reouverte_apres_cloture_du_projet(self):
        """DL-01 : la réouverture (« etat_tache ») lève le blocage d'avant."""
        self.sql("INSERT INTO post (projet_id, tache_id, auteur_id, type_code, contenu, evenement, created_at) "
                 "VALUES (%s, %s, %s, 'information', 'x', 'blocage_tache', %s::date + time '10:00'), "
                 "(%s, %s, %s, 'information', 'Abandonnée → En cours', 'etat_tache', %s::date + time '10:00')",
                 (self.p1, self.t1, self.chef, self.j(6), self.p1, self.t1, self.chef, self.j(3)))
        self.assertFalse(self.propose_tache(5))
        self.assertTrue(self.propose_tache(3))
        self.assertTrue(self.propose_tache(1))

    def test_rouverte_par_script_sans_date_de_fin(self):
        """DL-05 : rouverte en SQL, la date de fin s'efface."""
        self.sql("UPDATE tache SET etat = 'termine' WHERE id = %s", (self.t1,))
        self.assertIsNotNone(self.sql("SELECT date_fin FROM tache WHERE id = %s", (self.t1,))[0]["date_fin"])
        self.sql("UPDATE tache SET etat = 'en_cours' WHERE id = %s", (self.t1,))
        self.assertIsNone(self.sql("SELECT date_fin FROM tache WHERE id = %s", (self.t1,))[0]["date_fin"])

    def test_projet_suivi_seulement_par_des_heures_plus_tardives(self):
        """DL-08 : des heures saisies après le jour affiché ne le font pas proposer."""
        from app.repositories import dailylog as dl
        p3 = self.projet(self.chef, debut=self.j(20))
        self.sql("INSERT INTO dailylog_entree (utilisateur_id, projet_id, date, heures) VALUES (%s, %s, %s, 2)",
                 (self.inter, p3, self.j(1)))
        self.assertNotIn(p3, [l["projet_id"] for l in dl.lignes_proposees(self.u, self.j(3))])
        self.assertIn(p3, [l["projet_id"] for l in dl.lignes_proposees(self.u, self.j(1))])

    def test_absent_avec_une_ligne_figee(self):
        """DL-06, DL-07 : la cause est dite (projet quitté, pas « 14 jours »)."""
        x = self.user("intervenant", equipe="URBS")
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, x))
        jour = self.j(1)
        self.sql("INSERT INTO dailylog_entree (utilisateur_id, projet_id, date, heures) VALUES (%s, %s, %s, 2)",
                 (x, self.p1, jour))
        self.sql("INSERT INTO dailylog_jour (utilisateur_id, date, version) VALUES (%s, %s, 1)", (x, jour))
        self.login(self.chef)
        self.client.post(f"/projets/{self.p1}/intervenants/{x}/retirer")
        self.login(x)
        url = f"/dailylog/api/jour/{jour.isoformat()}"
        ligne = self.client.get(url).get_json()["lignes"][0]
        self.assertTrue(ligne["figee"])
        self.assertFalse(ligne["modifiable"])
        r = self.client.post(url + "/absence", json={"version": 1, "absent": True})
        self.assertEqual(r.status_code, 422, r.get_data(as_text=True)[:300])
        self.assertIn("absence_ligne_figee", r.get_data(as_text=True))
        self.assertNotIn("ligne_non_modifiable", r.get_data(as_text=True))


class TestComptesLot25(_Lot20):
    """Annexe G du rapport du 23/10 (comptes, administration)."""

    def jeton(self, uid):
        return self.sql("SELECT reset_token_hash AS h FROM utilisateur WHERE id = %s", (uid,))[0]["h"]

    def test_lien_non_parti_garde_le_precedent(self):
        """UT-02 : SMTP en panne — le lien déjà reçu reste valable."""
        from unittest.mock import patch

        self.sql("UPDATE utilisateur SET reset_token_hash = 'h0', reset_token_expires_at = now() + interval '1 hour' "
                 "WHERE id = %s", (self.inter,))
        self.login(self.rh)
        with patch("app.mailer.est_configure", return_value=True), \
             patch("app.mailer.destinataire_autorise", return_value=True), \
             patch("app.mailer.envoyer", return_value=False):
            self.client.post(f"/utilisateurs/{self.inter}/envoyer-lien")
        self.assertEqual(self.jeton(self.inter), "h0")
        # « Mot de passe oublié » en panne : plus de lien « récent » fantôme.
        self.sql("UPDATE utilisateur SET reset_token_hash = NULL, reset_token_expires_at = NULL WHERE id = %s",
                 (self.inter,))
        email = self.sql("SELECT email FROM utilisateur WHERE id = %s", (self.inter,))[0]["email"]
        with patch("app.mailer.envoyer", return_value=False):
            self.client.post("/mot-de-passe-oublie", data={"email": email})
        self.assertIsNone(self.jeton(self.inter))

    def test_auteurs_du_journal(self):
        """UT-01 : même liste qu'avant, par le parcours des index."""
        from app.repositories import audit as audit_repo

        self.sql("INSERT INTO audit_log (table_cible, ligne_id, action, utilisateur_id, admin_reel_id) "
                 "VALUES ('tache', 1, 'UPDATE', %s, NULL), ('tache', 2, 'UPDATE', %s, %s)",
                 (self.inter, self.chef, self.admin2))
        attendus = {r["id"] for r in self.sql(
            "SELECT u.id FROM utilisateur u WHERE EXISTS (SELECT 1 FROM audit_log a WHERE a.utilisateur_id = u.id) "
            "OR EXISTS (SELECT 1 FROM audit_log a WHERE a.admin_reel_id = u.id)")}
        with self.app.app_context():
            obtenus = {u["id"] for u in audit_repo.list_auteurs()}
        self.assertEqual(obtenus, attendus)
        self.assertTrue({self.inter, self.chef, self.admin2} <= obtenus)

    def test_f5_sur_effacer_les_filtres(self):
        """UT-04 : sans JavaScript, « defaut=1 » sert une fois (303 vers l'adresse nue)."""
        self.login(self.admin)
        r = self.client.get("/utilisateurs?defaut=1")
        self.assertEqual(r.status_code, 303)
        self.assertTrue(r.headers["Location"].endswith("/utilisateurs"), r.headers["Location"])

    def test_photo_d_un_compte_desactive_pour_un_client(self):
        """UT-05 : comme son profil, la photo d'un compte désactivé n'existe pas pour un Client."""
        client = self.user("client")
        parti = self.user("intervenant", actif=False)
        self.sql("UPDATE utilisateur SET avatar_chemin = 'avatars/x.png' WHERE id = %s", (parti,))
        self.login(client)
        self.assertEqual(self.client.get(f"/fichiers/avatars/{parti}").status_code, 404)

    def test_compte_desactive_le_dit(self):
        """U3 : « Ce compte a été désactivé. », pas « session expirée »."""
        self.login(self.inter)
        self.sql("UPDATE utilisateur SET actif = false WHERE id = %s", (self.inter,))
        self.client.get("/accueil")
        with self.client.session_transaction() as s:
            messages = [m for _, m in s.get("_flashes", [])]
        self.assertIn("Ce compte a été désactivé.", messages)

    def test_journal_dates_inversees(self):
        """U5 : « Au » avant « Du » est dit."""
        self.login(self.admin)
        page = self.client.get("/admin/journal?filtres_actifs=1&date_debut=2026-10-20&date_fin=2026-10-10")
        self.assertIn("est avant la date", page.get_data(as_text=True))


class TestMatriceLot25(_Lot20):
    """Annexe I du rapport du 23/10 (matrice routes × profils)."""

    def test_retrait_independant_de_l_ordre(self):
        """MX-05 : affecté à une tâche ouverte sans rien y faire, puis retiré du
        projet : pas de lecture gardée, quel que soit l'ordre des retraits."""
        x = self.user("intervenant", equipe="URBS")
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, x))
        self.sql("INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (%s, %s)", (self.t1, x))
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p1}/intervenants/{x}/retirer", headers=partiel("#x"))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet_ancien_membre WHERE utilisateur_id = %s",
                                      (x,)), 0)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM v_projet_visibilite WHERE projet_id = %s AND "
                                      "utilisateur_id = %s", (self.p1, x)), 0)


class TestBaseLot25(_Lot20):
    """Annexe J du rapport du 23/10 (base, déploiement)."""

    def test_voyants_comme_la_vue(self):
        """BD-04 : la requête dédiée donne exactement la vue."""
        from app.repositories import projets as projets_repo

        ancien = self.user("intervenant", equipe="URBS")
        self.user("client")
        inactif = self.user("intervenant", equipe="URBS")
        self.sql("INSERT INTO projet_ancien_membre (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, ancien))
        self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p2, self.inter))
        self.sql("INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (%s, %s)", (self.t1, inactif))
        self.sql("UPDATE utilisateur SET actif = false WHERE id = %s", (inactif,))
        for p in (self.p1, self.p2):
            vue = {r["utilisateur_id"] for r in self.sql(
                "SELECT utilisateur_id FROM v_projet_visibilite WHERE projet_id = %s", (p,))}
            with self.app.app_context():
                self.assertEqual(projets_repo.ids_utilisateurs_voyant(p), vue)

    def test_chef_inactif_pas_co_chef(self):
        """Observation : un chef désactivé affecté à une tâche ne devient pas co-chef."""
        chef2 = self.user("chef_de_projet", actif=False)
        self.sql("INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (%s, %s)", (self.t1, chef2))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet_co_chef WHERE utilisateur_id = %s",
                                      (chef2,)), 0)


class TestMutantsPushLot25(_Push):
    """Revue sécurité du 23/10, mutants survivants (W02, W03, W05, W10, W16, W17, S12)."""

    def test_desabonnement_et_etat_par_compte(self):
        """W16, W17 : l'adresse d'autrui n'est ni retirée ni dite « abonnée »."""
        self.abonner(self.chef, "https://fcm.googleapis.com/fcm/send/chef")
        self.login(self.inter)
        r = self.client.post("/push/etat", json={"endpoint": "https://fcm.googleapis.com/fcm/send/chef"})
        self.assertFalse(r.get_json()["abonne"])
        self.client.post("/push/desabonnement", json={"endpoint": "https://fcm.googleapis.com/fcm/send/chef"})
        self.assertEqual(self.nb_abonnements(self.chef), 1)

    def test_pour_push_ecarte_lue_simulee_et_compte_inactif(self):
        """W02, W03, W05."""
        from app.repositories import notifications as notifications_repo

        x = self.user("intervenant")
        ids = [self.sql("INSERT INTO notification (utilisateur_id, categorie, message, lu, simulee) "
                        "VALUES (%s, 'projet', 'm', %s, %s) RETURNING id", (u, lu, sim))[0]["id"]
               for u, lu, sim in ((self.inter, True, False), (self.inter, False, True), (x, False, False),
                                  (self.inter, False, False))]
        self.sql("UPDATE utilisateur SET actif = false WHERE id = %s", (x,))
        with self.app.app_context():
            self.assertEqual([n["id"] for n in notifications_repo.pour_push(ids)], [ids[3]])

    def test_categories_en_agir_comme(self):
        """W10 : refusé (403 en partiel)."""
        self.login(self.admin)
        self.client.post("/admin/agir-comme", data={"utilisateur_id": str(self.inter)})
        r = self.client.post("/push/categories", data={"categories": ["projet"]}, headers=partiel("#x"))
        self.assertEqual(r.status_code, 403)
        lignes = self.sql("SELECT push_categories FROM utilisateur_preference WHERE utilisateur_id = %s",
                          (self.inter,))
        self.assertTrue(not lignes or lignes[0]["push_categories"] is None, lignes)

    def test_adresse_http_refusee_par_la_base(self):
        """S12 : défense en profondeur — la base refuse un abonnement http://."""
        import psycopg2

        with self.assertRaises(psycopg2.Error):
            self.sql("INSERT INTO push_abonnement (utilisateur_id, endpoint, cle_p256dh, cle_auth) "
                     "VALUES (%s, 'http://fcm.googleapis.com/x', 'a', 'b')", (self.inter,))


class TestMutantsLot25(_Lot20):
    """Revue sécurité du 23/10, mutants survivants (S05, S06, P33, P51)."""

    def retirer(self, x):
        self.login(self.chef)
        self.client.post(f"/projets/{self.p1}/intervenants/{x}/retirer", headers=partiel("#x"))
        return self.compter("SELECT count(*) AS n FROM projet_ancien_membre WHERE projet_id = %s AND "
                            "utilisateur_id = %s", (self.p1, x))

    def test_participation_par_tache_close_ou_heures(self):
        """S05 (intervenant d'une tâche close), S06 (heures seules) : la lecture reste."""
        x = self.user("intervenant", equipe="URBS")
        y = self.user("intervenant", equipe="URBS")
        close = self.tache(self.p1, self.chef, etat="termine")
        for u in (x, y):
            self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, u))
        self.sql("INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (%s, %s)", (close, x))
        self.sql("INSERT INTO dailylog_entree (utilisateur_id, projet_id, date, heures) VALUES (%s, %s, %s, 1)",
                 (y, self.p1, self.auj))
        self.assertEqual(self.retirer(x), 1)
        self.assertEqual(self.retirer(y), 1)

    def test_retour_sur_defaut_ne_fait_pas_oublier(self):
        """P33 : `?defaut=1` rejoué par Retour (X-Kairos-Historique) garde le choix."""
        self.login(self.chef)
        self.client.get("/projets?filtres_actifs=1&etat=termine", headers=partiel("#projets-resultats"))
        avant = self.sql("SELECT filtres->>'projets' AS f FROM utilisateur_preference WHERE utilisateur_id = %s",
                         (self.chef,))[0]["f"]
        self.assertTrue(avant)
        h = dict(partiel("#projets-resultats"), **{"X-Kairos-Historique": "1"})
        self.client.get("/projets?defaut=1", headers=h)
        self.assertEqual(self.sql("SELECT filtres->>'projets' AS f FROM utilisateur_preference "
                                  "WHERE utilisateur_id = %s", (self.chef,))[0]["f"], avant)

    def test_mention_mise_en_forme_dans_le_corps_du_post(self):
        """P51 : « @Rim Inter » tagué est mis en forme dans le corps du post."""
        self.login(self.chef)
        self.client.post("/posts", data={"projet_id": str(self.p1), "type_code": "information",
                                         "contenu": "Voir avec @Rim Inter demain"})
        page = self.client.get(f"/projets/{self.p1}").get_data(as_text=True)
        self.assertIn('<span class="post-comment-mention">@Rim Inter</span>', page)


class TestMutantsModeTestLot25(_Lot20):
    """Revue sécurité du 23/10, mutants survivants P10 à P13 (GREATEST)."""
    MODE_TEST = True

    def test_epingle_commentaire_et_modifications_jamais_avant_la_creation(self):
        post = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', "
                        "'Plan') RETURNING id", (self.p1, self.chef))[0]["id"]
        self.login(self.admin)
        r = self.client.post("/admin/agir-comme", data={"utilisateur_id": str(self.chef)})
        self.assertEqual(r.status_code, 302)
        self.client.post("/admin/date-simulee", data={"date": (self.auj - datetime.timedelta(days=5)).isoformat(),
                                                      "heure": "10:00"})
        self.client.post(f"/posts/{post}/commenter", data={"contenu": "Vu"}, headers=partiel("#x"))
        self.client.post(f"/posts/{post}/epingler", headers=partiel("#x"))
        c = self.sql("SELECT id, created_at FROM post_commentaire WHERE post_id = %s", (post,))[0]
        self.client.post(f"/posts/commentaires/{c['id']}/modifier", data={"contenu": "Vu, merci"},
                         headers=partiel("#x"))
        self.client.post(f"/posts/{post}/modifier", data={"contenu": "Plan v2"}, headers=partiel("#x"))
        p = self.sql("SELECT created_at, epingle_le, modifie_le FROM post WHERE id = %s", (post,))[0]
        c = self.sql("SELECT created_at, modifie_le FROM post_commentaire WHERE id = %s", (c["id"],))[0]
        self.assertGreaterEqual(c["created_at"], p["created_at"])        # P11
        self.assertIsNotNone(p["epingle_le"])
        self.assertGreaterEqual(p["epingle_le"], p["created_at"])        # P10
        self.assertGreaterEqual(c["modifie_le"], c["created_at"])        # P12
        self.assertGreaterEqual(p["modifie_le"], p["created_at"])        # P13

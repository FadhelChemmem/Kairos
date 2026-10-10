"""Lot 11 b sur vraie base (PostgreSQL, routes, triggers) :
1. changement du chef de projet depuis la fenêtre « Informations » (droits,
   projet clos, nouveau chef, co-chefs, post, notification, audit, verrou,
   dernier rempart en base de la migration 0017) ;
2. recherche globale et notifications d'une tâche : la fiche ouvre la
   fenêtre de la tâche (?tache=<id>) ;
3. rappel Daily log : texte clair, jours regroupés, dédoublonnage et
   marquage « lu » par notification.rappel_jours (ancien et nouveau format).
"""
import datetime
import html
import pathlib
import re
import threading
import time

from tests_integration.base import BaseIntegration

RACINE = pathlib.Path(__file__).resolve().parent.parent
MIGRATION_0017 = RACINE / "migrations" / "0017_chef_projet_et_rappels_dailylog.sql"


def _texte(r):
    return html.unescape(r.get_data(as_text=True))


class _BaseChef(BaseIntegration):
    def setUp(self):
        super().setUp()
        self.admin = self.user("admin")
        self.chef = self.user("chef_de_projet")       # titulaire
        self.cochef = self.user("chef_de_projet")     # co-chef
        self.autre = self.user("chef_de_projet")      # futur chef (intervenant du projet)
        self.inter = self.user("intervenant")
        for uid, prenom, nom in ((self.admin, "Fadhel", "Admin"), (self.chef, "Ali", "Chef"),
                                 (self.cochef, "Rim", "Cochef"), (self.autre, "Sami", "Chérif"),
                                 (self.inter, "Omar", "Inter")):
            self.sql("UPDATE utilisateur SET prenom = %s, nom = %s WHERE id = %s", (prenom, nom, uid))
        self.p = self.projet(self.chef, code="26101X")
        self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s), (%s, %s)",
                 (self.p, self.cochef, self.p, self.autre))
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s), (%s, %s)",
                 (self.p, self.inter, self.p, self.autre))

    def infos(self, chef_id, etat="en_cours", projet=None, **extra):
        data = {"nom": "Projet", "etat": etat, "client": "IPCO"}
        if chef_id is not None:
            data["chef_projet_id"] = str(chef_id)
        data.update(extra)
        return self.client.post(f"/projets/{projet or self.p}/informations", data=data, follow_redirects=True)

    def chef_de(self, projet=None):
        return self.sql("SELECT chef_projet_id FROM projet WHERE id = %s", (projet or self.p,))[0]["chef_projet_id"]

    def co_chefs(self, projet=None):
        return {r["utilisateur_id"] for r in self.sql(
            "SELECT utilisateur_id FROM projet_co_chef WHERE projet_id = %s", (projet or self.p,))}

    def intervenants(self, projet=None):
        return {r["utilisateur_id"] for r in self.sql(
            "SELECT utilisateur_id FROM projet_intervenant WHERE projet_id = %s", (projet or self.p,))}


class TestChangementDeChef(_BaseChef):
    def test_le_chef_confie_le_projet(self):
        self.login(self.chef)
        r = self.infos(self.autre)
        self.assertEqual(r.status_code, 200)
        self.assertIn("projet confié à Sami Chérif (Ali Chef devient co-chef)", _texte(r))
        self.assertEqual(self.chef_de(), self.autre)
        # Ancien titulaire co-chef ; nouveau ni co-chef ni intervenant ; équipe inchangée.
        self.assertEqual(self.co_chefs(), {self.cochef, self.chef})
        self.assertEqual(self.intervenants(), {self.inter})
        self.assertEqual(self.sql("SELECT equipe_code FROM projet WHERE id = %s", (self.p,))[0]["equipe_code"], "MIDGARD")
        # Post automatique dans le fil.
        (post,) = self.sql("SELECT id, auteur_id, contenu, type_code FROM post WHERE projet_id = %s "
                           "AND evenement = 'chef_projet'", (self.p,))
        self.assertEqual((post["auteur_id"], post["type_code"]), (self.chef, "information"))
        self.assertEqual(post["contenu"], "Ali Chef a confié le projet à Sami Chérif. Ali Chef, chef précédent, devient co-chef.")
        # Lot 14 : un post automatique est dans la vue « Activité » du fil.
        fiche = _texte(self.client.get(f"/projets/{self.p}?fil=activite"))
        self.assertIn("a changé le chef de projet", fiche)
        self.assertIn("Ali Chef a confié le projet à Sami Chérif.", fiche)
        # Notification au nouveau chef, reliée au post (ouvre la fiche).
        (n,) = self.sql("SELECT id, message, post_id, categorie FROM notification WHERE utilisateur_id = %s", (self.autre,))
        self.assertEqual((n["post_id"], n["categorie"]), (post["id"], "projet"))
        self.assertEqual(n["message"], "Ali Chef vous a confié le projet «\u00a026101X_Projet\u00a0»\u00a0: vous en êtes le chef de projet.")
        self.login(self.autre)
        o = self.client.post(f"/notifications/{n['id']}/ouvrir")
        # Lot 13 (audit rôles M8) : sur le post, dans la fiche.
        self.assertTrue(o.headers["Location"].endswith(f"/projets/{self.p}#post-{post['id']}"), o.headers["Location"])
        # Journal d'audit : la ligne du changement, avec son auteur.
        lignes = self.sql("""SELECT utilisateur_id, donnees_avant->>'chef_projet_id' AS avant,
                                    donnees_apres->>'chef_projet_id' AS apres
                             FROM audit_log WHERE table_cible = 'projet' AND ligne_id = %s AND action = 'UPDATE'
                               AND donnees_avant->>'chef_projet_id' <> donnees_apres->>'chef_projet_id'""", (self.p,))
        self.assertEqual([(x["utilisateur_id"], x["avant"], x["apres"]) for x in lignes],
                         [(self.chef, str(self.chef), str(self.autre))])
        self.assertEqual(self.sql("SELECT count(*) AS n FROM audit_log WHERE table_cible = 'projet_co_chef' "
                                  "AND action = 'INSERT' AND utilisateur_id = %s", (self.chef,))[0]["n"], 1)

    def test_un_co_chef_peut_changer_de_chef_et_se_designer(self):
        self.login(self.cochef)
        self.infos(self.cochef)
        self.assertEqual(self.chef_de(), self.cochef)
        self.assertEqual(self.co_chefs(), {self.chef, self.autre})
        # Pas de notification à soi-même.
        self.assertEqual(self.sql("SELECT count(*) AS n FROM notification")[0]["n"], 0)

    def test_meme_chef_ou_champ_absent_rien_ne_change(self):
        self.login(self.chef)
        for chef in (self.chef, None):
            with self.subTest(chef=chef):
                r = self.infos(chef)
                self.assertIn("Informations du projet mises à jour.", _texte(r))
        self.assertEqual(self.chef_de(), self.chef)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM post WHERE evenement = 'chef_projet'")[0]["n"], 0)

    def test_refus_droits_et_nouveau_chef_invalide(self):
        rh, client = self.user("rh", equipe=None), self.user("client")
        inactif = self.user("chef_de_projet", actif=False)
        self.login(self.inter)
        r = self.infos(self.autre)
        self.assertIn("Seul le chef de projet ou un co-chef peut modifier les informations du projet.", _texte(r))
        self.login(self.chef)
        for candidat in (self.inter, rh, client, inactif, 999999, "abc"):
            with self.subTest(candidat=candidat):
                r = self.infos(candidat, nom="Renommé")
                self.assertIn("Nouveau chef de projet invalide", _texte(r))
        self.assertEqual(self.chef_de(), self.chef)
        # Rien d'autre n'a été enregistré (refus avant toute écriture).
        self.assertEqual(self.sql("SELECT nom FROM projet WHERE id = %s", (self.p,))[0]["nom"], "Projet")
        self.assertEqual(self.co_chefs(), {self.cochef, self.autre})

    def test_projet_clos_rouvrir_d_abord_sauf_admin(self):
        self.sql("UPDATE projet SET etat = 'termine' WHERE id = %s", (self.p,))
        self.login(self.chef)
        page = _texte(self.client.get(f"/projets/{self.p}"))
        self.assertNotIn('id="dialog-info-chef"', page)
        self.assertIn("Projet clos\u00a0: rouvrez-le d’abord pour changer de chef.", page)
        # Requête forgée, même en rouvrant dans le même envoi : refusée, rien n'est enregistré.
        r = self.infos(self.autre, etat="en_cours")
        self.assertIn("Ce projet est clos : rouvrez-le d'abord", _texte(r))
        self.assertEqual((self.chef_de(), self.sql("SELECT etat FROM projet WHERE id = %s", (self.p,))[0]["etat"]),
                         (self.chef, "termine"))
        # Rouvert d'abord, puis changé : accepté.
        self.infos(None, etat="en_cours")
        self.infos(self.autre, etat="en_cours")
        self.assertEqual(self.chef_de(), self.autre)

    def test_admin_reaffecte_un_projet_clos_dont_le_chef_est_desactive(self):
        self.sql("UPDATE projet SET etat = 'abandonne' WHERE id = %s", (self.p,))
        self.sql("UPDATE utilisateur SET actif = false WHERE id = %s", (self.chef,))
        self.login(self.admin)
        page = _texte(self.client.get(f"/projets/{self.p}?informations=chef"))
        self.assertIn('data-ouvrir-au-chargement="chef"', page)
        select = page.split('id="dialog-info-chef"', 1)[1].split("</select>", 1)[0]
        # Chef actuel (désactivé) présent et choisi ; candidats : chefs de projet et Admin actifs.
        self.assertRegex(select, rf'<option value="{self.chef}" selected[^>]*data-sous-titre="Compte désactivé · chef actuel">Ali Chef \(désactivé\)</option>')
        valeurs = {int(v) for v in re.findall(r'<option value="(\d+)"', select)}
        self.assertEqual(valeurs, {self.chef, self.admin, self.cochef, self.autre})
        r = self.infos(self.autre, etat="abandonne")
        self.assertIn("projet confié à Sami Chérif", _texte(r))
        self.assertEqual(self.chef_de(), self.autre)
        self.assertIn(self.chef, self.co_chefs())

    def test_encart_admin_renvoie_vers_la_fenetre_informations(self):
        self.sql("UPDATE utilisateur SET actif = false WHERE id = %s", (self.chef,))
        self.login(self.admin)
        page = _texte(self.client.get("/utilisateurs"))
        self.assertIn(f'href="/projets/{self.p}?informations=chef"', page)
        self.assertIn("Changer le chef", page)
        # Le paramètre n'ouvre rien pour qui ne gère pas le projet.
        self.login(self.inter)
        self.assertNotIn("data-ouvrir-au-chargement=\"chef\"", _texte(self.client.get(f"/projets/{self.p}?informations=chef")))

    def test_verrou_le_projet_clos_pendant_la_modification_est_vu(self):
        """Verrou du projet : une clôture en cours (autre transaction) fait
        attendre le changement de chef, qui relit ensuite l'état et refuse."""
        from app.repositories import projets
        resultat = {}

        def changer():
            try:
                projets.update_projet(self.p, nom="Projet", etat="termine", lots=[], current_user_id=self.chef,
                                      chef_projet_id=self.autre, acteur_admin=False)
                resultat["ok"] = True
            except Exception as exc:  # noqa: BLE001
                resultat["exc"] = exc

        with self.db.get_cursor(user_id=self.chef) as cur:
            cur.execute("SELECT 1 FROM projet WHERE id = %s FOR UPDATE", (self.p,))
            cur.execute("UPDATE projet SET etat = 'termine' WHERE id = %s", (self.p,))
            fil = threading.Thread(target=changer)
            fil.start()
            time.sleep(0.6)
            self.assertTrue(fil.is_alive(), "le changement de chef n'a pas attendu le verrou")
        fil.join(10)
        self.assertIsInstance(resultat.get("exc"), projets.ChangementChefRefuse)
        self.assertEqual(self.chef_de(), self.chef)

    def test_dernier_rempart_en_base(self):
        from app.repositories import projets
        inactif = self.user("chef_de_projet", actif=False)

        def maj(acteur, nouveau, reprise=False):
            with self.db.get_cursor(user_id=acteur) as cur:
                if reprise:
                    cur.execute("SET LOCAL kairos.reprise_historique = 'on'")
                cur.execute("UPDATE projet SET chef_projet_id = %s WHERE id = %s", (nouveau, self.p))

        for acteur, nouveau, motif in ((self.inter, self.autre, "seuls le chef de projet"),
                                       (self.chef, inactif, "doit avoir un compte actif"),
                                       (self.chef, self.inter, "doit avoir un compte actif")):
            with self.subTest(acteur=acteur, nouveau=nouveau):
                with self.assertRaises(Exception) as ctx:
                    maj(acteur, nouveau)
                self.assertIn(motif, str(ctx.exception))
                self.assertTrue(projets.est_refus_changement_chef(ctx.exception))
        self.sql("UPDATE projet SET etat = 'termine' WHERE id = %s", (self.p,))
        with self.assertRaises(Exception) as ctx:
            maj(self.chef, self.autre)
        self.assertIn("clos : rouvrez-le", str(ctx.exception))
        maj(self.admin, self.autre)                      # Admin : projet clos réaffecté
        self.assertEqual(self.chef_de(), self.autre)
        maj(None, inactif)                               # sans utilisateur applicatif (script)
        maj(self.inter, self.chef, reprise=True)         # reprise Chronos
        self.assertEqual(self.chef_de(), self.chef)
        # Une autre colonne ne déclenche rien, même avec un chef désactivé.
        self.sql("UPDATE utilisateur SET actif = false WHERE id = %s", (self.chef,))
        with self.db.get_cursor(user_id=self.inter) as cur:
            cur.execute("UPDATE projet SET nom = 'Renommé' WHERE id = %s", (self.p,))


class TestTacheOuverteDepuisRechercheEtNotification(BaseIntegration):
    def setUp(self):
        super().setUp()
        self.chef, self.inter = self.user("chef_de_projet"), self.user("intervenant")
        self.p = self.projet(self.chef)
        self.ouverte = self.tache(self.p, self.chef)
        self.close = self.tache(self.p, self.chef, etat="termine")

    def test_fiche_avec_tache_ouverte_ou_close(self):
        self.login(self.chef)
        page = _texte(self.client.get(f"/projets/{self.p}?tache={self.ouverte}"))
        self.assertIn(f'data-ouvrir-au-chargement="{self.ouverte}"', page)
        self.assertNotIn('id="taches-closes" open', page)
        page = _texte(self.client.get(f"/projets/{self.p}?tache={self.close}"))
        self.assertIn(f'data-ouvrir-au-chargement="{self.close}"', page)
        self.assertIn('id="taches-closes" open', page)
        # Tâche d'un autre projet, ou id invalide : la fiche, sans fenêtre.
        autre = self.tache(self.projet(self.chef), self.chef)
        for valeur in (autre, "abc", 0):
            with self.subTest(valeur=valeur):
                r = self.client.get(f"/projets/{self.p}?tache={valeur}")
                self.assertEqual(r.status_code, 200)
                self.assertNotIn("data-ouvrir-au-chargement=", _texte(r))

    def test_sans_droit_404_comme_avant(self):
        etranger = self.user("intervenant", equipe="URBS")
        self.login(etranger)
        self.assertEqual(self.client.get(f"/projets/{self.p}?tache={self.ouverte}").status_code, 404)
        self.assertEqual(self.client.get(f"/projets/{self.p}/taches/{self.ouverte}/fenetre").status_code, 404)

    def test_notification_d_affectation_ouvre_la_tache(self):
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p}/taches", data={"titre": "Note de calcul", "type_deadline": "interne",
                                                                "intervenants": [str(self.inter)]})
        self.assertEqual(r.status_code, 302)
        (n,) = self.sql("SELECT id, tache_id FROM notification WHERE utilisateur_id = %s", (self.inter,))
        self.assertIsNotNone(n["tache_id"])
        self.login(self.inter)
        o = self.client.post(f"/notifications/{n['id']}/ouvrir")
        self.assertTrue(o.headers["Location"].endswith(f"/projets/{self.p}?tache={n['tache_id']}"), o.headers["Location"])
        page = _texte(self.client.get(o.headers["Location"]))
        self.assertIn(f'data-ouvrir-au-chargement="{n["tache_id"]}"', page)


class TestRappelDailyLogLot11b(BaseIntegration):
    JEUDI = datetime.date(2026, 10, 8)

    def setUp(self):
        super().setUp()
        self.chef = self.user("chef_de_projet")
        self.moi = self.user("intervenant")
        self.p = self.projet(self.chef, code="26070X")
        # Arrivée le lundi 5 : fenêtre = lun. 5, mar. 6, mer. 7.
        self.u = {"id": self.moi, "fuseau": "Africa/Tunis", "debut_daily_log": datetime.date(2026, 10, 5)}

    def verifier(self, aujourdhui=None):
        from app.auth import _verifier_rappel_dailylog
        with self.app.app_context():
            _verifier_rappel_dailylog(self.u, aujourdhui=aujourdhui or self.JEUDI)

    def rappels(self):
        return self.sql("SELECT id, message, rappel_jours, lu, categorie FROM notification "
                        "WHERE utilisateur_id = %s ORDER BY id", (self.moi,))

    def remplir(self, jour, heures=8):
        with self.db.get_cursor() as cur:
            cur.execute("SET LOCAL kairos.reprise_historique = 'on'")
            cur.execute("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, %s)",
                        (self.moi, jour, self.p, heures))

    def test_une_notification_regroupe_les_jours_puis_pas_de_doublon(self):
        self.verifier()
        (n,) = self.rappels()
        self.assertEqual(n["message"], "3 jours de Daily log non remplis\u00a0: lundi 5, mardi 6 et mercredi 7 octobre")
        self.assertEqual(n["rappel_jours"], [datetime.date(2026, 10, d) for d in (5, 6, 7)])
        self.assertEqual(n["categorie"], "rh_info")
        self.verifier()
        self.assertEqual(len(self.rappels()), 1)
        # Le lendemain : seul le nouveau jour oublié, au singulier.
        self.verifier(datetime.date(2026, 10, 9))
        n2 = self.rappels()[-1]
        self.assertEqual((n2["message"], n2["rappel_jours"]),
                         ("Daily log du jeudi 8 octobre non rempli", [datetime.date(2026, 10, 8)]))

    def test_ancien_format_reconnu_apres_migration(self):
        self.sql("INSERT INTO notification (utilisateur_id, categorie, message) VALUES (%s, 'rh_info', %s)",
                 (self.moi, "Rappel DailyLog : vous n'avez pas rempli votre journée du 07/10/2026."))
        # Un texte qui commence pareil sans être un rappel du Daily log n'est pas touché.
        self.sql("INSERT INTO notification (utilisateur_id, categorie, message) VALUES (%s, 'projet', %s)",
                 (self.moi, "Rappel DailyLog : réunion du 06/10/2026."))
        for _ in range(2):  # 0017 rejouable
            with self.db.get_cursor() as cur:
                cur.execute(MIGRATION_0017.read_text(encoding="utf-8"))
            self.rejouer_migrations_suivantes("0017_chef_projet_et_rappels_dailylog")
        anciens = self.rappels()
        self.assertEqual([a["rappel_jours"] for a in anciens], [[datetime.date(2026, 10, 7)], None])
        self.verifier()
        nouveau = self.rappels()[-1]
        self.assertEqual(nouveau["rappel_jours"], [datetime.date(2026, 10, 5), datetime.date(2026, 10, 6)])
        self.assertEqual(nouveau["message"], "2 jours de Daily log non remplis\u00a0: lundi 5 et mardi 6 octobre")
        # Marquage « lu » : l'ancien dès son jour rempli, le groupé quand TOUS ses jours le sont.
        from app.repositories import notifications
        self.remplir(datetime.date(2026, 10, 7))
        self.remplir(datetime.date(2026, 10, 5))
        with self.app.app_context():
            notifications.marquer_rappels_dailylog_lus(self.moi)
        lus = [r["lu"] for r in self.rappels()]
        self.assertEqual(lus, [True, False, False])
        self.sql("INSERT INTO dailylog_jour (utilisateur_id, date, absent) VALUES (%s, %s, true)",
                 (self.moi, datetime.date(2026, 10, 6)))
        with self.app.app_context():
            notifications.marquer_rappels_dailylog_lus(self.moi)
        self.assertEqual([r["lu"] for r in self.rappels()], [True, False, True])

    def test_lien_premier_jour_a_remplir(self):
        self.verifier()
        (n,) = self.rappels()
        self.remplir(datetime.date(2026, 10, 5))
        self.login(self.moi)
        o = self.client.post(f"/notifications/{n['id']}/ouvrir")
        self.assertTrue(o.headers["Location"].endswith("/dailylog?date=2026-10-06"), o.headers["Location"])

    def test_saisie_par_la_route_marque_le_rappel_lu(self):
        """Lot 11 : marqué lu dans la transaction d'enregistrement du jour —
        aussi pour le nouveau format (date relative : la route refuse un
        jour hors de la fenêtre libre)."""
        from app.repositories import dailylog, notifications
        veille = dailylog.aujourdhui_pour(self.u) - datetime.timedelta(days=1)
        self.sql("UPDATE utilisateur SET created_at = now() - interval '400 days' WHERE id = %s", (self.moi,))
        with self.app.app_context():
            notifications.creer_rappel_dailylog(self.moi, [veille], lambda j: "Daily log d'hier non rempli")
        self.login(self.moi)
        r = self.client.put(f"/dailylog/api/jour/{veille.isoformat()}",
                            json={"version": 0, "lignes": [{"projet_id": self.p, "tache_id": None, "minutes": 120}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        rappel = [x for x in self.rappels() if x["rappel_jours"] == [veille]]
        self.assertEqual([x["lu"] for x in rappel], [True])

    def test_deux_sessions_en_meme_temps_un_seul_rappel(self):
        from app.repositories import notifications
        erreurs = []

        def envoyer():
            try:
                with self.app.app_context():
                    notifications.creer_rappel_dailylog(self.moi, [datetime.date(2026, 10, 7)], lambda j: "Daily log")
            except Exception as exc:  # noqa: BLE001
                erreurs.append(exc)

        with self.db.get_cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('kairos.rappel_dailylog'), %s::int)", (self.moi,))
            fils = [threading.Thread(target=envoyer) for _ in range(2)]
            for f in fils:
                f.start()
            time.sleep(0.4)
        for f in fils:
            f.join(10)
        self.assertEqual(erreurs, [])
        self.assertEqual(len(self.rappels()), 1)

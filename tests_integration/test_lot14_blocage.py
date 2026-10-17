"""Lot 14, sur un vrai PostgreSQL : tâche bloquée avec raison (revue produit
P0-1) et message de clôture (P0-2) — motif obligatoire, gardé sur la tâche,
porté par le post automatique et la notification au chef et aux co-chefs ;
« Annuler » cohérent (post et notification de l'aller retirés) ; sections
« Bloquées (n) » de l'accueil et des Deadlines ; droits (requêtes forgées,
« Voir comme », CSRF) ; migration 0020 rejouable."""
import datetime
from pathlib import Path

from tests_integration.test_lot13_partiel import oob, partiel, toasts
from tests_integration.test_lot13_projets import _Projets

MOTIF = "Attente des plans archi indice B"


class _Blocage(_Projets):
    def url_etat(self, tache=None, projet=None):
        return f"/projets/{projet or self.p1}/taches/{tache or self.t1}/etat"

    def bloquer(self, motif=MOTIF, cible=None, **donnees):
        cible = cible or f"#tache-fenetre-{self.t1}"
        return self.client.post(self.url_etat(), data={"etat": "bloque", "motif": motif, **donnees},
                                headers=partiel(cible))

    def tache_bloc(self, tache=None):
        return self.sql("SELECT etat, bloque_motif, bloque_le, bloque_par FROM tache WHERE id = %s",
                        (tache or self.t1,))[0]


class TestBlocageAvecMotif(_Blocage):
    def test_motif_obligatoire_et_trop_long(self):
        self.login(self.inter)
        for motif in ("", "   \n  "):
            with self.subTest(motif=motif):
                r = self.bloquer(motif)
                self.assertEqual(r.status_code, 422)
                self.assertEqual(r.get_json()["champs"], {"motif": "Indiquez ce qui bloque la tâche."})
        r = self.bloquer("x" * 501)
        self.assertEqual(r.status_code, 422)
        self.assertIn("500 caractères au plus", r.get_json()["champs"]["motif"])
        # Sans JavaScript : retour à la fiche (tâche rouverte), message.
        r = self.client.post(self.url_etat(), data={"etat": "bloque"})
        self.assertEqual(r.status_code, 302)
        self.assertIn(f"tache={self.t1}", r.headers["Location"])
        self.assertIn("Indiquez ce qui bloque la tâche.", self.flash(r))
        self.assertEqual(self.tache_bloc()["etat"], "en_cours")
        self.assertEqual(self.posts(self.p1, "blocage_tache"), [])
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE tache_id IS NOT NULL"), 0)

    def test_blocage_motif_post_notification_et_affichage(self):
        self.login(self.inter)
        r = self.bloquer(f"  {MOTIF}  ")
        self.assertEqual(r.status_code, 200)
        bloc = self.tache_bloc()
        self.assertEqual((bloc["etat"], bloc["bloque_motif"], bloc["bloque_par"]), ("bloque", MOTIF, self.inter))
        self.assertIsNotNone(bloc["bloque_le"])
        self.assertEqual(self.etat(self.p1), "bloque")
        # Post « a signalé un blocage », le motif en contenu.
        self.assertEqual(self.posts(self.p1, "blocage_tache"), [{"auteur_id": self.inter, "contenu": MOTIF,
                                                                  "tache_id": self.t1}])
        self.assertEqual(self.posts(self.p1, "etat_tache"), [])
        # Notification au chef et au co-chef (jamais à l'acteur), vers la tâche.
        attendu = f"Rim Inter a bloqué « T » ({self.code()}) : {MOTIF}."
        for uid in (self.chef, self.cochef):
            n = self.notifs(uid)
            self.assertEqual([(x["message"], x["tache_id"]) for x in n], [(attendu, self.t1)])
        self.assertEqual([n for n in self.notifs(self.inter) if n["tache_id"]], [])
        # Toast : les personnes prévenues ; « Annuler » rend l'état d'avant.
        t = toasts(r)[0]
        self.assertEqual(t["texte"], "Blocage signalé à Cheffe Titulaire et P chef_de_projet.")
        self.assertEqual(set(t["action"]["donnees"]), {"etat", "annulation", "jeton"})
        self.assertEqual((t["action"]["donnees"]["etat"], t["action"]["donnees"]["annulation"]), ("en_cours", "1"))
        # Panneau : motif sous les états ; ligne : infobulle et texte lu.
        html = self.texte(r)
        self.assertIn(f'id="tache-{self.t1}-blocage-detail"', html)
        self.assertIn(f"« {MOTIF} »", html)
        self.assertIn(" · bloquée depuis aujourd’hui, par Rim Inter", html)
        self.assertIn(f"tache-ligne-{self.t1}", oob(html))
        ligne = html.split(f'id="tache-ligne-{self.t1}"')[1].split('class="taskrow-heures"')[0]
        self.assertIn(f'title="Bloquée depuis aujourd’hui : « {MOTIF} »"', ligne)
        self.assertIn(f'id="tache-ligne-{self.t1}-blocage">, Bloquée', ligne)
        # Fil de la fiche : « a signalé un blocage » avec le motif.
        fiche = self.visible(self.client.get(f"/projets/{self.p1}"))
        self.assertIn("Rim Inter a signalé un blocage", fiche)
        self.assertIn(f"« {MOTIF} »", fiche)

    def test_annuler_le_blocage_retire_post_et_notifications(self):
        self.login(self.inter)
        action = toasts(self.bloquer())[0]["action"]
        r = self.client.post(action["url"], data=action["donnees"], headers=partiel(action["cible"]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual((self.tache_bloc()["etat"], self.etat(self.p1)), ("en_cours", "en_cours"))
        self.assertEqual(self.posts(self.p1, "blocage_tache") + self.posts(self.p1, "deblocage_tache"), [])
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE tache_id IS NOT NULL"), 0)
        # Une notification déjà lue reste (le chef a vu le blocage).
        action = toasts(self.bloquer())[0]["action"]
        self.sql("UPDATE notification SET lu = true WHERE utilisateur_id = %s", (self.chef,))
        self.client.post(action["url"], data=action["donnees"], headers=partiel(action["cible"]))
        self.assertEqual(len(self.notifs(self.chef)), 1)
        self.assertEqual(self.notifs(self.cochef), [])

    def test_lever_le_blocage_puis_annuler_rend_le_meme_blocage(self):
        self.login(self.inter)
        self.bloquer()
        self.sql("UPDATE tache SET bloque_le = now() - interval '3 days' WHERE id = %s", (self.t1,))
        avant = self.tache_bloc()
        self.login(self.chef)
        r = self.client.post(self.url_etat(), data={"etat": "en_cours"}, headers=partiel(f"#tache-fenetre-{self.t1}"))
        t = toasts(r)[0]
        self.assertEqual(t["texte"], "Blocage levé\u00a0: Rim Inter prévenu.")  # lot 16
        self.assertEqual((t["action"]["donnees"]["etat"], t["action"]["donnees"]["annulation"]), ("bloque", "1"))
        self.assertEqual([p["contenu"] for p in self.posts(self.p1, "deblocage_tache")], ["Bloqué → En cours"])
        fiche = self.visible(self.client.get(f"/projets/{self.p1}?fil=tout"))
        self.assertIn("Cheffe Titulaire a levé le blocage", fiche)
        # Le motif reste gardé (historique), sans être affiché hors blocage.
        self.assertEqual(self.tache_bloc()["bloque_motif"], MOTIF)
        self.assertNotIn(f'id="tache-{self.t1}-blocage-detail"',
                         self.texte(self.client.get(f"/projets/{self.p1}/taches/{self.t1}/fenetre")))
        # « Annuler » : même motif, même début, même auteur ; post de levée retiré.
        r = self.client.post(t["action"]["url"], data=t["action"]["donnees"], headers=partiel(t["action"]["cible"]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.tache_bloc(), avant)
        self.assertEqual(self.posts(self.p1, "deblocage_tache"), [])
        self.assertIn("bloquée depuis 3 j, par Rim Inter", self.texte(r))
        # Aucune nouvelle notification par l'annulation.
        self.assertEqual(len(self.notifs(self.chef)), 1)

    def test_nouveau_blocage_nouvelle_date_et_chef_qui_bloque(self):
        self.login(self.chef)
        r = self.bloquer("Visa du contrôleur technique")
        # Le chef bloque : le co-chef est prévenu, pas le chef lui-même.
        self.assertEqual(toasts(r)[0]["texte"], "Blocage signalé à P chef_de_projet.")
        self.assertEqual(self.notifs(self.chef), [])
        self.assertEqual(len(self.notifs(self.cochef)), 1)
        self.assertEqual(self.tache_bloc()["bloque_par"], self.chef)

    def test_projet_sans_autre_gestionnaire(self):
        self.sql("DELETE FROM projet_co_chef")
        self.login(self.chef)
        self.assertEqual(toasts(self.bloquer())[0]["texte"], "Blocage signalé.")
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE tache_id IS NOT NULL"), 0)

    def code(self):
        return self.sql("SELECT code FROM projet WHERE id = %s", (self.p1,))[0]["code"]


class TestClotureAvecMessage(_Blocage):
    def cloturer(self, **donnees):
        return self.client.post(f"/projets/{self.p1}/taches/{self.t1}/cloturer", data=donnees,
                                headers=partiel(f"#tache-fenetre-{self.t1}"))

    def test_message_publie_et_chef_previenu(self):
        self.login(self.inter)
        r = self.cloturer(type_code="envoi", contenu="  Dossier EXE indice B envoyé au BET  ")
        self.assertEqual(r.status_code, 200)
        post = self.sql("SELECT type_code, contenu FROM post WHERE evenement = 'cloture_tache'")[0]
        self.assertEqual((post["type_code"], post["contenu"]), ("envoi", "Dossier EXE indice B envoyé au BET"))
        code = self.sql("SELECT code FROM projet WHERE id = %s", (self.p1,))[0]["code"]
        attendu = f"Rim Inter a terminé « T » ({code}) — Envoi : Dossier EXE indice B envoyé au BET."
        for uid in (self.chef, self.cochef):
            self.assertEqual([(n["message"], n["tache_id"]) for n in self.notifs(uid)], [(attendu, self.t1)])
        self.assertEqual(toasts(r)[0]["texte"],
                         "Tâche terminée : post publié, Cheffe Titulaire et P chef_de_projet prévenus.")
        fiche = self.visible(self.client.get(f"/projets/{self.p1}"))
        self.assertIn("Rim Inter a terminé une tâche", fiche)
        self.assertIn("Dossier EXE indice B envoyé au BET", fiche)

    def test_sans_message_texte_automatique_et_annuler(self):
        self.login(self.inter)
        r = self.cloturer(type_code="reponse", contenu="   ")
        post = self.sql("SELECT type_code, contenu FROM post WHERE evenement = 'cloture_tache'")[0]
        self.assertEqual((post["type_code"], post["contenu"]), ("reponse", "Tâche terminée."))
        code = self.sql("SELECT code FROM projet WHERE id = %s", (self.p1,))[0]["code"]
        self.assertEqual(self.notifs(self.chef)[0]["message"], f"Rim Inter a terminé « T » ({code}) — Réponse.")
        # « Annuler » : tâche rouverte, post de clôture et notifications retirés.
        action = toasts(r)[0]["action"]
        self.client.post(action["url"], data=action["donnees"], headers=partiel(action["cible"]))
        self.assertEqual(self.tache_bloc()["etat"], "en_cours")
        self.assertEqual(self.compter("SELECT count(*) AS n FROM post WHERE evenement IN ('cloture_tache', 'etat_tache')"), 0)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE tache_id IS NOT NULL"), 0)

    def test_annuler_garde_un_message_commente(self):
        self.login(self.inter)
        r = self.cloturer(type_code="envoi", contenu="Plans envoyés")
        pid = self.sql("SELECT id FROM post WHERE evenement = 'cloture_tache'")[0]["id"]
        self.sql("INSERT INTO post_commentaire (post_id, auteur_id, contenu) VALUES (%s, %s, 'Merci')", (pid, self.chef))
        action = toasts(r)[0]["action"]
        self.client.post(action["url"], data=action["donnees"], headers=partiel(action["cible"]))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM post WHERE evenement = 'cloture_tache'"), 1)
        self.assertEqual([p["contenu"] for p in self.posts(self.p1, "etat_tache")], ["Terminé → En cours"])

    def test_chef_ou_co_chef_qui_termine_ne_notifie_pas(self):
        for qui in (self.chef, self.cochef):
            with self.subTest(qui=qui):
                self.sql("UPDATE tache SET etat = 'en_cours' WHERE id = %s", (self.t1,))
                self.login(qui)
                r = self.cloturer(type_code="envoi")
                self.assertEqual(toasts(r)[0]["texte"], "Tâche terminée : post publié dans le fil.")
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE tache_id IS NOT NULL"), 0)

    def test_panneau_propose_le_message(self):
        self.login(self.inter)
        html = self.texte(self.client.get(f"/projets/{self.p1}/taches/{self.t1}/fenetre"))
        bloc = html.split('class="tache-cloture"')[1].split("</form>")[0]
        self.assertIn("Terminer la tâche", bloc)
        self.assertIn(f'<textarea name="contenu" id="cloture-message-{self.t1}"', bloc)
        self.assertIn('placeholder="Ex. Dossier EXE indice B envoyé au BET"', bloc)
        self.assertIn("Type de post", bloc)
        self.assertIn("Terminer et publier", bloc)
        # Question du blocage : cachée, motif obligatoire, exemple.
        question = html.split(f'id="tache-{self.t1}-blocage"')[1].split("</form>")[0]
        self.assertIn("hidden", question.split(">")[0])
        self.assertIn("Qu’est-ce qui bloque ?", question)
        self.assertIn('placeholder="Ex. attente des plans archi indice B"', question)
        self.assertRegex(question, r'<textarea[^>]+name="motif"[^>]+required')
        self.assertIn(f'data-blocage-ouvrir="tache-{self.t1}-blocage"', html)


class TestDroitsDuBlocage(_Blocage):
    def test_requetes_forgees_refusees(self):
        autre = self.user("intervenant")
        client = self.user("client", "IPCO")
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, autre))
        cas = [
            (autre, self.url_etat(), 403),                       # voit le projet, pas intervenant de la tâche
            (client, self.url_etat(), 404),                      # client d'une autre équipe
            (self.rh, self.url_etat(), 404),                     # RH : aucun projet
            (self.chef, self.url_etat(self.t2, self.p1), 404),   # tâche d'un autre projet
        ]
        for qui, url, statut in cas:
            with self.subTest(qui=qui, url=url):
                self.login(qui)
                r = self.client.post(url, data={"etat": "bloque", "motif": MOTIF}, headers=partiel("#x"))
                self.assertEqual(r.status_code, statut, r.get_data(as_text=True)[:200])
                r = self.client.post(url.replace("/etat", "/cloturer"), data={"type_code": "envoi", "contenu": "x"},
                                     headers=partiel("#x"))
                self.assertIn(r.status_code, (403, 404, 409))
        self.assertEqual(self.sql("SELECT etat, bloque_motif FROM tache WHERE id IN (%s, %s) ORDER BY id",
                                  (self.t1, self.t2)), [{"etat": "en_cours", "bloque_motif": None}] * 2)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE tache_id IS NOT NULL"), 0)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM post"), 0)

    def test_projet_clos_refuse(self):
        self.sql("UPDATE projet SET etat = 'termine' WHERE id = %s", (self.p1,))
        self.login(self.chef)
        self.assertEqual(self.bloquer().status_code, 409)
        self.assertEqual(self.tache_bloc()["etat"], "en_cours")

    def test_voir_comme_lecture_seule(self):
        self.entrer(self.inter)
        r = self.client.post(self.url_etat(), data={"etat": "bloque", "motif": MOTIF})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.tache_bloc()["etat"], "en_cours")
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE tache_id IS NOT NULL"), 0)


class TestCsrfDuBlocage(_Blocage):
    CSRF = True

    def test_sans_jeton_rien_n_est_fait(self):
        self.login(self.inter)
        r = self.client.post(self.url_etat(), data={"etat": "bloque", "motif": MOTIF}, headers=partiel("#x"))
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/cloturer", data={"type_code": "envoi"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.tache_bloc()["etat"], "en_cours")
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE tache_id IS NOT NULL"), 0)


class TestSectionsBloquees(_Blocage):
    def setUp(self):
        super().setUp()
        self.login(self.inter)
        self.bloquer()
        self.sql("UPDATE tache SET bloque_le = now() - interval '4 days' WHERE id = %s", (self.t1,))
        # Tâche bloquée sur un projet d'une autre équipe, sans motif (ancienne).
        self.t3 = self.tache(self.p2, self.chef, etat="bloque")

    def test_accueil_chef_intervenant_et_admin(self):
        for qui in (self.inter, self.chef, self.cochef):
            with self.subTest(qui=qui):
                self.login(qui)
                page = self.texte(self.client.get("/accueil"))
                section = page.split('id="taches-bloquees"')[1].split("</details>")[0]
                self.assertIn("Bloquées <span class=\"taches-bloquees-nb\">(", section)
                self.assertIn(f"« {MOTIF} »", section)
                self.assertIn("Depuis 4 j", section)
                self.assertIn("par Rim Inter", section)
                self.assertIn(f"/projets/{self.p1}?tache={self.t1}", section)
                self.assertEqual(page.count('id="taches-bloquees"'), 1)
        # Le chef voit aussi celle de son projet URBS ; l'intervenant non.
        self.login(self.chef)
        self.assertIn("(2)", self.texte(self.client.get("/accueil")).split('id="taches-bloquees"')[1].split("</h2>")[0])
        self.login(self.inter)
        self.assertIn("(1)", self.texte(self.client.get("/accueil")).split('id="taches-bloquees"')[1].split("</h2>")[0])
        # Admin : tout le bureau, avec le chef de projet ; motif absent signalé.
        self.login(self.admin)
        section = self.texte(self.client.get("/accueil")).split('id="taches-bloquees"')[1].split("</details>")[0]
        self.assertIn("(2)", section)
        self.assertIn("Motif non renseigné", section)
        # Personne d'autre : pas de section.
        self.login(self.user("intervenant"))
        self.assertNotIn('id="taches-bloquees"', self.texte(self.client.get("/accueil")))

    def test_deadlines_mes_projets_et_tous(self):
        self.login(self.inter)
        page = self.texte(self.client.get("/deadlines"))
        section = page.split('id="deadlines-bloquees"')[1].split("</details>")[0]
        self.assertIn(f'data-open-tache="{self.t1}"', section)
        self.assertIn(f'data-tache-url="/projets/{self.p1}/taches/{self.t1}/fenetre"', section)
        self.assertNotIn(f'data-open-tache="{self.t3}"', section)
        # Sous le Gantt : après la frise et la liste du téléphone.
        self.assertLess(page.index("gantt-aide-defilement"), page.index('id="deadlines-bloquees"'))
        # Admin, « Tous les projets », filtre par équipe (en partiel aussi).
        self.login(self.admin)
        r = self.client.get("/deadlines?vue=tous&equipe=URBS", headers=partiel("#deadlines-contenu"))
        section = self.texte(r).split('id="deadlines-bloquees"')[1].split("</details>")[0]
        self.assertIn(f'data-open-tache="{self.t3}"', section)
        self.assertNotIn(f'data-open-tache="{self.t1}"', section)
        self.assertIn(" · Cheffe Titulaire", section)

    def test_projet_clos_et_tache_debloquee_sortent(self):
        self.sql("UPDATE projet SET etat = 'abandonne' WHERE id = %s", (self.p2,))
        self.login(self.inter)
        self.client.post(self.url_etat(), data={"etat": "en_cours"})
        self.login(self.chef)
        self.assertNotIn('id="taches-bloquees"', self.texte(self.client.get("/accueil")))


class TestMigration0020(_Blocage):
    def test_rejouable_et_reprise_des_taches_deja_bloquees(self):
        fichier = Path(__file__).resolve().parent.parent / "migrations" / "0020_lot14_blocage_et_cloture.sql"
        t = self.tache(self.p1, self.chef, etat="bloque")
        self.sql("UPDATE tache SET bloque_le = NULL WHERE id = %s", (t,))
        self.sql("INSERT INTO post (projet_id, tache_id, auteur_id, type_code, contenu, evenement, created_at) "
                 "VALUES (%s, %s, %s, 'information', 'En cours → Bloqué', 'etat_tache', now() - interval '6 days')",
                 (self.p1, t, self.chef))
        for _ in range(2):
            with self.db.get_cursor() as cur:
                cur.execute(fichier.read_text(encoding="utf-8"))
        jours = self.sql("SELECT (now() - bloque_le) AS d FROM tache WHERE id = %s", (t,))[0]["d"]
        self.assertEqual(jours.days, 6)
        self.assertIsNone(self.sql("SELECT bloque_motif FROM tache WHERE id = %s", (t,))[0]["bloque_motif"])
        with self.assertRaises(Exception):
            self.sql("UPDATE tache SET bloque_motif = %s WHERE id = %s", ("x" * 501, t))
        with self.assertRaises(Exception):
            self.sql("INSERT INTO post (projet_id, auteur_id, type_code, evenement) "
                     "VALUES (%s, %s, 'information', 'inconnu')", (self.p1, self.chef))

    def test_aujourdhui_simule_jamais_negatif(self):
        from app.utils import jours_blocage
        with self.app.test_request_context():
            self.assertEqual(jours_blocage(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=2)), 0)
            self.assertIsNone(jours_blocage(None))


class TestRecetteBlocage(_Blocage):
    """Recette du lot 14 : n° 2 et 3 (motif contourné ou invisible), n° 4
    (« Annuler » ne retire que les notifications de son geste), n° 5
    (« Annuler » périmé), n° 12 (aide « qui est prévenu »)."""

    def nb_notifs(self, uid=None):
        return len([n for n in self.notifs(uid or self.chef) if n["tache_id"]])

    def test_annulation_forgee_exige_le_motif_et_previent(self):
        self.login(self.chef)
        for donnees in ({"etat": "bloque", "annulation": "1"},
                        {"etat": "bloque", "annulation": "1", "jeton": ""},
                        {"etat": "bloque", "annulation": "1", "motif": "   "}):
            with self.subTest(donnees=donnees):
                r = self.client.post(self.url_etat(), data=donnees, headers=partiel(f"#tache-fenetre-{self.t1}"))
                self.assertEqual(r.status_code, 422)
                self.assertEqual(r.get_json()["champs"], {"motif": "Indiquez ce qui bloque la tâche."})
        self.assertEqual(self.tache_bloc()["etat"], "en_cours")
        self.assertEqual(self.posts(self.p1, "blocage_tache"), [])
        # Jeton forgé ou d'un autre : 409, rien n'est fait.
        r = self.client.post(self.url_etat(), data={"etat": "bloque", "annulation": "1", "jeton": "faux.jeton"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.tache_bloc()["etat"], "en_cours")
        # Avec un motif, « annulation » forgée n'empêche pas la notification
        # (le co-chef est toujours prévenu).
        r = self.client.post(self.url_etat(), data={"etat": "bloque", "annulation": "1", "motif": MOTIF},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.tache_bloc()["bloque_motif"], MOTIF)
        self.assertEqual(self.nb_notifs(self.cochef), 1)
        self.assertEqual(len(self.posts(self.p1, "blocage_tache")), 1)

    def test_jeton_d_une_autre_personne_refuse(self):
        self.login(self.inter)
        action = toasts(self.bloquer())[0]["action"]
        self.login(self.chef)
        r = self.client.post(action["url"], data=action["donnees"], headers=partiel(action["cible"]))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.tache_bloc()["etat"], "bloque")
        self.assertEqual(self.nb_notifs(self.cochef), 1)

    def test_motif_invisible_refuse(self):
        self.login(self.inter)
        for motif in ("\u00a0\u200b", "\ufeff\u2060", "\u200b\u200c\u200d", "\x07\x1b\x7f", "\u00a0\u202f\u3000\n\t"):
            with self.subTest(motif=repr(motif)):
                r = self.bloquer(motif)
                self.assertEqual(r.status_code, 422)
                self.assertEqual(r.get_json()["champs"], {"motif": "Indiquez ce qui bloque la tâche."})
        self.assertEqual(self.tache_bloc()["etat"], "en_cours")
        self.assertEqual(self.nb_notifs(), 0)
        # Caractères invisibles retirés d'un motif réel.
        self.assertEqual(self.bloquer("\u200bAttente\u00a0des\u200b plans\x07").status_code, 200)
        self.assertEqual(self.tache_bloc()["bloque_motif"], "Attente des plans")

    def test_annuler_ne_retire_que_les_notifications_de_son_geste(self):
        self.login(self.inter)
        self.bloquer("Premier blocage réel")
        self.client.post(self.url_etat(), data={"etat": "en_cours"}, headers=partiel(f"#tache-fenetre-{self.t1}"))
        action = toasts(self.bloquer("Second blocage"))[0]["action"]
        self.assertEqual(self.nb_notifs(), 2)
        r = self.client.post(action["url"], data=action["donnees"], headers=partiel(action["cible"]))
        self.assertEqual(r.status_code, 200)
        restantes = [n["message"] for n in self.notifs(self.chef) if n["tache_id"]]
        self.assertEqual(len(restantes), 1)
        self.assertIn("Premier blocage réel", restantes[0])
        self.assertEqual(len([n for n in self.notifs(self.cochef) if n["tache_id"]]), 1)

    def test_annuler_la_cloture_garde_le_blocage_d_avant(self):
        self.login(self.inter)
        self.bloquer()
        self.client.post(self.url_etat(), data={"etat": "en_cours"}, headers=partiel(f"#tache-fenetre-{self.t1}"))
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/cloturer", data={"type_code": "envoi"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(self.nb_notifs(), 2)
        action = toasts(r)[0]["action"]
        self.client.post(action["url"], data=action["donnees"], headers=partiel(action["cible"]))
        restantes = [n["message"] for n in self.notifs(self.chef) if n["tache_id"]]
        self.assertEqual(len(restantes), 1)
        self.assertIn("a bloqué", restantes[0])

    def test_annuler_perime_apres_le_geste_d_un_autre(self):
        self.login(self.inter)
        action = toasts(self.bloquer())[0]["action"]
        self.login(self.chef)
        self.client.post(self.url_etat(), data={"etat": "en_cours"}, headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.client.post(self.url_etat(), data={"etat": "bloque", "motif": "Blocage du chef"},
                         headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.login(self.inter)
        r = self.client.post(action["url"], data=action["donnees"], headers=partiel(action["cible"]))
        self.assertEqual(r.status_code, 409)
        self.assertIn("La tâche a changé entre-temps", r.get_json()["message"])
        bloc = self.tache_bloc()
        self.assertEqual((bloc["etat"], bloc["bloque_motif"], bloc["bloque_par"]), ("bloque", "Blocage du chef", self.chef))
        # Même chose pour l'« Annuler » d'une levée : le chef a re-bloqué
        # entre-temps, l'intervenant ne remet pas son ancien motif.
        r = self.client.post(self.url_etat(), data={"etat": "en_cours"}, headers=partiel(f"#tache-fenetre-{self.t1}"))
        action = toasts(r)[0]["action"]
        self.login(self.chef)
        self.client.post(self.url_etat(), data={"etat": "bloque", "motif": "Autre motif"},
                         headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.login(self.inter)
        r = self.client.post(action["url"], data=action["donnees"], headers=partiel(action["cible"]))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.tache_bloc()["bloque_motif"], "Autre motif")
        # Sans JavaScript (requête classique) : message, retour à la tâche.
        r = self.client.post(action["url"], data=action["donnees"])
        self.assertEqual(r.status_code, 302)
        self.assertIn("La tâche a changé entre-temps", self.flash(r))

    def aide(self, qui):
        self.login(qui)
        html = self.texte(self.client.get(f"/projets/{self.p1}/taches/{self.t1}/fenetre"))
        return html.split(f'id="tache-{self.t1}-blocage-aide" class="tache-blocage-aide">')[1].split("</p>")[0]

    def test_aide_dit_qui_est_prevenu(self):
        self.assertEqual(self.aide(self.inter), "Le chef de projet et le co-chef sont prévenus.")
        self.assertEqual(self.aide(self.chef), "Le co-chef est prévenu.")
        self.assertEqual(self.aide(self.cochef), "Le chef de projet est prévenu.")
        autre = self.user("chef_de_projet")
        self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, autre))
        self.assertEqual(self.aide(self.chef), "Les co-chefs sont prévenus.")
        self.assertEqual(self.aide(self.inter), "Le chef de projet et les co-chefs sont prévenus.")
        self.sql("DELETE FROM projet_co_chef")
        self.assertEqual(self.aide(self.chef), "Le motif s’affiche sur la tâche et dans le fil du projet.")

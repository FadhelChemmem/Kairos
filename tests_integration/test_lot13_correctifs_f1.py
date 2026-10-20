"""Lot 13, tour de corrections après contre-expertise (agent back F1), sur
un vrai PostgreSQL : curseur du journal (sécurité N1), CSRF avant
l'empreinte de mode (O6), notification d'un projet devenu invisible
(rôles N1), personnes proposées par projet dans « Nouveau post » (I7),
équipe obligatoire dans la fiche (M4), toast de clôture (N2), colonnes du
chef (N3), refus « Voir comme » en JSON (partiel), rappels simulés (temps
N1), « Simuler le rappel » depuis un onglet périmé (N3), création de projet
sous date simulée (N6), « Annuler » sans second post (UX N9), candidats
« Phase liée » à la demande (a11y-perf M11)."""
import datetime
import re

from tests_integration.test_lot12 import _Base
from tests_integration.test_lot13_partiel import toasts
from tests_integration.test_lot13_projets import _Projets


def partiel(cible, xhr=True):
    entetes = {"X-Kairos-Partiel": cible}
    if xhr:
        entetes["X-Requested-With"] = "XMLHttpRequest"
    return entetes


class TestCurseurDuJournal(_Base):
    def test_curseur_hors_bornes_ignore(self):
        self.login(self.admin)
        for curseur in ("2026-10-09T00:00:00_99999999999999999999", "2026-10-09T00:00:00_-9999",
                        "2026-10-09T00:00:00Z_9223372036854775808", "2026-10-09T00:00:00%2B16:00_1",
                        "0001-01-01T00:00:00%2B23:59_1"):
            for entetes in ({}, partiel("#journal-resultats")):
                with self.subTest(curseur=curseur, partiel=bool(entetes)):
                    r = self.client.get(f"/admin/journal?avant={curseur}", headers=entetes)
                    self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])


class TestCsrfAvantEmpreinte(_Base):
    CSRF = True
    MODE_TEST = True

    def test_requete_intersite_ne_pose_aucun_message_de_mode(self):
        self.login(self.inter)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Attente des plans", "_mode": "faux"})
        self.assertEqual(r.status_code, 302)
        with self.client.session_transaction() as s:
            messages = [m for _, m in s.get("_flashes", [])]
        self.assertFalse(any("Le mode a changé" in m for m in messages), messages)
        self.assertTrue(any("formulaire n'est plus valide" in m for m in messages), messages)
        self.assertEqual(self.sql("SELECT etat FROM tache WHERE id = %s", (self.t1,))[0]["etat"], "en_cours")


class TestVoirCommeRefusPartiel(_Base):
    def test_refus_en_json_sans_x_requested_with(self):
        self.entrer(self.inter)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Attente des plans"},
                             headers=partiel(f"#tache-fenetre-{self.t1}", xhr=False))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["erreur"], "lecture_seule")


class TestRoles(_Projets):
    def test_notification_d_un_projet_devenu_invisible(self):
        autre = self.user("intervenant", equipe="URBS")
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, autre))
        # Lot 24 : seul celui qui a participé garde la lecture (ici, un post).
        self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', 'x')",
                 (self.p1, autre))
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p1}/intervenants/{autre}/retirer")
        self.assertEqual(r.status_code, 302)
        (notif,) = self.notifs(autre)
        self.assertEqual(notif["projet_id"], self.p1)
        self.login(autre)
        # Lot 21 (décision du 19/10) : un ancien participant garde la lecture.
        r = self.client.post(f"/notifications/{notif['id']}/ouvrir")
        self.assertEqual((r.status_code, r.headers["Location"]), (302, f"/projets/{self.p1}"))
        # Sans trace de participation : plus d'accès, renvoi aux notifications.
        self.sql("DELETE FROM projet_ancien_membre WHERE projet_id = %s AND utilisateur_id = %s", (self.p1, autre))
        r = self.client.post(f"/notifications/{notif['id']}/ouvrir")
        self.assertEqual((r.status_code, r.headers["Location"]), (302, "/notifications"))
        self.assertIn("Vous n’avez plus accès à ce projet.", self.flash(r))
        # Projet toujours visible : la fiche, comme avant.
        self.sql("INSERT INTO notification (utilisateur_id, categorie, message, projet_id) VALUES (%s, 'projet', 'x', %s)",
                 (self.inter, self.p1))
        nid = self.notifs(self.inter)[-1]["id"]
        self.login(self.inter)
        r = self.client.post(f"/notifications/{nid}/ouvrir")
        self.assertEqual(r.headers["Location"], f"/projets/{self.p1}")

    def test_nouveau_post_de_l_accueil_personnes_par_projet(self):
        urbs = self.user("intervenant", equipe="URBS")
        self.login(self.chef)
        page = self.texte(self.client.get("/accueil"))
        options = dict(re.findall(r'<option value="(\d+)" data-gere="1" data-voient="([^"]*)"', page))
        voient = {int(i) for i in options[str(self.p1)].split()}
        self.assertIn(self.inter, voient)
        self.assertIn(self.chef, voient)
        self.assertNotIn(urbs, voient)
        # Projet URBS du chef : les URBS le voient, pas l'intervenant MIDGARD.
        voient_p2 = {int(i) for i in options[str(self.p2)].split()}
        self.assertIn(urbs, voient_p2)
        self.assertNotIn(self.inter, voient_p2)

    def test_fiche_equipe_obligatoire(self):
        self.login(self.rh)
        r = self.client.post(f"/utilisateurs/{self.inter}", data={
            "prenom": "Rim", "nom": "Inter", "email": self.sql("SELECT email FROM utilisateur WHERE id = %s",
                                                               (self.inter,))[0]["email"],
            "role": "intervenant", "equipe_code": "", "fuseau": "Africa/Tunis"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Choisissez l’équipe de ce compte", self.visible(r))
        self.assertEqual(self.sql("SELECT equipe_code FROM utilisateur WHERE id = %s", (self.inter,))[0]["equipe_code"],
                         "MIDGARD")

    def test_toast_de_cloture_au_singulier(self):
        self.login(self.chef)
        r = self.informations(self.p1, etat="abandonne")
        from werkzeug.datastructures import MultiDict
        champs = re.findall(r'<input type="hidden" name="([a-z_]+)" value="([^"]*)">', self.texte(r))
        r = self.client.post(f"/projets/{self.p1}/informations",
                             data=MultiDict([(n, v) for n, v in champs if n != "csrf_token"]))
        self.assertIn("Projet clos avec sa tâche ouverte (abandonnée).", self.flash(r))

    def test_colonnes_masquees_pour_un_chef(self):
        self.login(self.chef)
        page = self.texte(self.client.get("/utilisateurs"))
        entete = page.split('class="uhead"')[1].split("</div>")[0]
        self.assertNotIn("E-mail", entete)
        self.assertNotIn("Embauche", entete)
        self.assertNotIn("urow-date", page)
        self.assertNotIn("non communiqué", page)
        self.login(self.admin)
        entete = self.texte(self.client.get("/utilisateurs")).split('class="uhead"')[1].split("</div>")[0]
        self.assertIn("E-mail", entete)


class TestAnnulerSansSecondPost(_Projets):
    def annuler(self, r):
        """« Annuler » du toast de la réponse `r` (avec son jeton)."""
        action = toasts(r)[0]["action"]
        return self.client.post(action["url"], data=action["donnees"], headers=partiel(action["cible"]))

    def compter_posts(self, evenement):
        return self.compter("SELECT count(*) AS n FROM post WHERE projet_id = %s AND evenement = %s",
                            (self.p1, evenement))

    def test_annuler_retire_le_post_de_l_aller(self):
        self.login(self.inter)
        url = f"/projets/{self.p1}/taches/{self.t1}/etat"
        r = self.client.post(url, data={"etat": "bloque", "motif": "Attente des plans"}, headers=partiel(f"#tache-fenetre-{self.t1}"))
        # Lot 14 (P0-1) : le blocage est un post « a signalé un blocage ».
        self.assertEqual((self.compter_posts("blocage_tache"), self.compter_posts("etat_projet")), (1, 1))
        r = self.annuler(r)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((self.compter_posts("blocage_tache"), self.compter_posts("deblocage_tache"),
                          self.compter_posts("etat_projet")), (0, 0, 0))
        self.assertEqual((self.etat_tache(self.t1), self.etat(self.p1)), ("en_cours", "en_cours"))
        # Audit gardé : la suppression des deux posts est journalisée.
        self.assertEqual(self.compter("SELECT count(*) AS n FROM audit_log WHERE table_cible = 'post' "
                                      "AND action = 'DELETE'"), 2)
        # Annulation de la clôture (sans message) : le post de clôture part.
        self.annuler(self.client.post(f"/projets/{self.p1}/taches/{self.t1}/cloturer", data={"type_code": "envoi"},
                                      headers=partiel(f"#tache-fenetre-{self.t1}")))
        self.assertEqual((self.compter_posts("cloture_tache"), self.compter_posts("etat_tache")), (0, 0))

    def test_post_ancien_ou_commente_garde(self):
        self.login(self.inter)
        url = f"/projets/{self.p1}/taches/{self.t1}/etat"
        r = self.client.post(url, data={"etat": "bloque", "motif": "Attente des plans"}, headers=partiel("#x"))
        self.sql("UPDATE post SET created_at = created_at - interval '5 minutes' WHERE evenement = 'blocage_tache'")
        self.annuler(r)
        blocages = lambda: (self.compter_posts("blocage_tache"), self.compter_posts("deblocage_tache"))  # noqa: E731
        self.assertEqual(blocages(), (1, 1))
        # Sans « Annuler » : un post par changement, comme avant.
        self.client.post(url, data={"etat": "bloque", "motif": "Attente des plans"})
        self.client.post(url, data={"etat": "en_cours"})
        self.assertEqual(blocages(), (2, 2))
        # Commenté entre-temps : gardé.
        r = self.client.post(url, data={"etat": "bloque", "motif": "Attente des plans"}, headers=partiel("#x"))
        dernier = self.sql("SELECT max(id) AS id FROM post WHERE evenement = 'blocage_tache'")[0]["id"]
        self.sql("INSERT INTO post_commentaire (post_id, auteur_id, contenu) VALUES (%s, %s, 'vu')", (dernier, self.chef))
        self.annuler(r)
        self.assertEqual(blocages(), (3, 3))


class TestPhaseLieeALaDemande(_Projets):
    def test_route_json_memes_droits(self):
        self.login(self.chef)
        r = self.client.get("/projets/phase-liee/candidats?q=")
        ids = [x["id"] for x in r.get_json()["resultats"]]
        self.assertEqual(sorted(ids), sorted([self.p1, self.p2]))
        r = self.client.get(f"/projets/phase-liee/candidats?exclure={self.p1}")
        self.assertNotIn(self.p1, [x["id"] for x in r.get_json()["resultats"]])
        self.assertTrue(all(re.fullmatch(r".+_.+", x["libelle"]) for x in r.get_json()["resultats"]))
        # Intervenant : seulement pour un projet qu'il gère (co-chef).
        self.login(self.inter)
        self.assertEqual(self.client.get("/projets/phase-liee/candidats").status_code, 403)
        self.assertEqual(self.client.get(f"/projets/phase-liee/candidats?exclure={self.p1}").status_code, 403)
        self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, self.inter))
        self.assertEqual(self.client.get(f"/projets/phase-liee/candidats?exclure={self.p1}").status_code, 200)
        self.login(self.rh)
        self.assertEqual(self.client.get("/projets/phase-liee/candidats").status_code, 403)

    def test_page_de_creation_sans_les_200_options(self):
        self.login(self.chef)
        page = self.texte(self.client.get("/projets/nouveau"))
        bloc = page.split('name="phase_liee_id"')[1].split("</select>")[0]
        self.assertEqual(re.findall(r'<option value="(\d*)"', bloc), [""])
        self.assertIn('data-search-url="/projets/phase-liee/candidats"', bloc)


class _Temps(_Base):
    MODE_TEST = True

    def simuler(self, jour):
        self.assertEqual(self.client.post("/admin/date-simulee", data={"date": jour.isoformat()}).status_code, 302)

    def empreinte(self, page):
        return re.search(r'<meta name="kairos-mode" content="([^"]*)"', self.texte(page)).group(1)


class TestRappelsSimules(_Temps):
    def setUp(self):
        super().setUp()
        self.sql("UPDATE utilisateur SET date_embauche = %s WHERE id = %s", (self.auj - datetime.timedelta(days=90),
                                                                              self.inter))

    def creer_rappel_simule(self):
        self.login(self.admin)
        self.simuler(self.auj + datetime.timedelta(days=7))
        self.entrer(self.inter, mode="agir")
        self.client.post("/admin/rappel-simule", data={"next": "/accueil"})
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE simulee"), 1)

    def test_invisible_pour_la_vraie_personne_et_purge(self):
        self.creer_rappel_simule()
        # Pendant le test (Agir comme) : visible.
        self.assertEqual(self.client.get("/notifications/compte").get_json()["non_lues"], 1)
        self.assertIn("[Simulation]", self.texte(self.client.get("/notifications")))
        # « Voir comme » la personne : invisible.
        self.client.post("/admin/revenir")
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE simulee"), 0)

    def test_jamais_dans_la_cloche_de_la_personne(self):
        self.creer_rappel_simule()
        self.login(self.inter)
        self.assertEqual(self.client.get("/notifications/compte").get_json()["non_lues"], 0)
        self.assertNotIn("[Simulation]", self.texte(self.client.get("/notifications")))
        self.assertNotIn("[Simulation]", self.texte(self.client.get("/notifications", headers=partiel("#notifs-apercu"))))
        self.entrer(self.inter)
        self.assertEqual(self.client.get("/notifications/compte").get_json()["non_lues"], 0)

    def test_revenir_a_aujourdhui_purge_aussi(self):
        self.creer_rappel_simule()
        self.client.post("/admin/date-simulee/effacer")
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE simulee"), 0)

    def test_onglet_perime_refuse(self):
        self.login(self.admin)
        self.entrer(self.inter, mode="agir")
        perimee = self.empreinte(self.client.get("/accueil"))
        self.client.post("/admin/revenir")
        self.entrer(self.chef, mode="agir")
        self.simuler(self.auj + datetime.timedelta(days=7))
        r = self.client.post("/admin/rappel-simule", data={"_mode": perimee, "next": "/accueil"})
        self.assertEqual(r.status_code, 303)
        r = self.client.post("/admin/rappel-simule", headers={"X-Kairos-Mode": perimee})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification"), 0)
        # Changer de date depuis un onglet périmé reste permis (choix explicite).
        r = self.client.post("/admin/date-simulee", data={"date": self.auj.isoformat(), "_mode": perimee})
        self.assertEqual(r.status_code, 302)


class TestCreationSousDateSimulee(_Temps):
    def test_code_et_date_de_debut_suivent_la_vraie_date(self):
        self.login(self.admin)
        futur = datetime.date(self.auj.year + 1, 1, 4)
        self.simuler(futur)
        self.entrer(self.chef, mode="agir")
        page = self.texte(self.client.get("/projets/nouveau"))
        code = re.search(r'id="code"[^>]*value="([^"]+)"', page) or re.search(r'value="([^"]+)"[^>]*id="code"', page)
        self.assertTrue(code.group(1).startswith(f"{self.auj.year % 100:02d}"), code.group(1))
        self.assertIn(f'name="date_debut" value="{self.auj.isoformat()}"', page)
        r = self.client.get("/projets/code-propose?phase=EXE")
        self.assertTrue(r.get_json()["code"].startswith(f"{self.auj.year % 100:02d}"))

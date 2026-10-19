"""Lot 13 sur un vrai PostgreSQL — audit des rôles (I1–I9, M1–M15) et
décisions du gérant 1 à 4 et 6 : état du projet recalculé d'après ses
tâches, clôture d'un projet avec confirmation, chef de projet à la
création, intervenants et échéance d'une tâche existante, retrait d'un
intervenant du projet, notifications reliées au projet ou au post, droits
divers."""
import datetime
import re

from tests_integration.test_lot12 import _Base


class _Projets(_Base):
    def setUp(self):
        super().setUp()
        self.cochef = self.user("chef_de_projet")
        self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, self.cochef))
        self.sql("UPDATE utilisateur SET prenom = 'Cheffe', nom = 'Titulaire' WHERE id = %s", (self.chef,))
        self.sql("INSERT INTO projet_lot (projet_id, lot_code) VALUES (%s, 'GO')", (self.p1,))

    def etat(self, projet_id):
        return self.sql("SELECT etat FROM projet WHERE id = %s", (projet_id,))[0]["etat"]

    def etat_tache(self, tache_id):
        return self.sql("SELECT etat FROM tache WHERE id = %s", (tache_id,))[0]["etat"]

    def posts(self, projet_id, evenement):
        return self.sql("SELECT auteur_id, contenu, tache_id FROM post WHERE projet_id = %s AND evenement = %s ORDER BY id",
                        (projet_id, evenement))

    def notifs(self, uid):
        return self.sql("SELECT id, message, post_id, tache_id, projet_id FROM notification WHERE utilisateur_id = %s "
                        "ORDER BY id", (uid,))

    def flash(self, r):
        return self.visible(self.client.get(r.headers["Location"])) if r.status_code in (302, 303) else self.visible(r)

    def informations(self, projet_id, **champs):
        donnees = {"nom": "Projet", "etat": "en_cours", "client": "IPCO", "lots": "GO", "lots_envoyes": "1"}
        donnees.update(champs)
        return self.client.post(f"/projets/{projet_id}/informations", data=donnees)


class TestEtatDuProjet(_Projets):
    """I2, I9 (décision 1) : Bloqué ⇔ une tâche bloquée, projet ouvert."""

    def test_reste_bloque_tant_qu_une_tache_l_est(self):
        t_bloquee = self.tache(self.p1, self.chef, intervenants=[self.inter])
        self.login(self.inter)
        self.client.post(f"/projets/{self.p1}/taches/{t_bloquee}/etat", data={"etat": "bloque", "motif": "Attente des plans"})
        self.assertEqual(self.etat(self.p1), "bloque")
        # Une autre tâche, plus ancienne, bloquée puis remise En cours : le projet reste Bloqué
        # (elle n'a pas été créée après le blocage).
        self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Attente des plans"})
        self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "en_cours"})
        self.assertEqual(self.etat(self.p1), "bloque")
        # Dernière tâche bloquée close : le projet se débloque, post « Bloqué → En cours ».
        self.login(self.chef)
        self.client.post(f"/projets/{self.p1}/taches/{t_bloquee}/cloturer", data={"type_code": "envoi"})
        self.assertEqual(self.etat(self.p1), "en_cours")
        self.assertEqual(self.posts(self.p1, "etat_projet")[-1]["contenu"], "Bloqué → En cours")

    def test_informations_ne_proposent_plus_bloque(self):
        self.login(self.chef)
        page = self.texte(self.client.get(f"/projets/{self.p1}"))
        bloc = page.split('id="dialog-info-etat"')[1].split("</select>")[0]
        self.assertNotIn('value="bloque"', bloc)
        self.assertEqual(re.findall(r'value="(\w+)"', bloc), ["en_cours", "termine", "abandonne"])
        # « Bloqué » forgé sans tâche bloquée : le projet reste En cours.
        self.informations(self.p1, etat="bloque")
        self.assertEqual(self.etat(self.p1), "en_cours")
        self.assertEqual(self.posts(self.p1, "etat_projet"), [])
        # « En cours » demandé avec une tâche bloquée : il reste Bloqué.
        self.sql("UPDATE tache SET etat = 'bloque' WHERE id = %s", (self.t1,))
        self.sql("UPDATE projet SET etat = 'bloque' WHERE id = %s", (self.p1,))
        self.informations(self.p1, etat="en_cours", nom="Renommé")
        self.assertEqual(self.etat(self.p1), "bloque")
        self.assertEqual(self.sql("SELECT nom FROM projet WHERE id = %s", (self.p1,))[0]["nom"], "Renommé")
        page = self.texte(self.client.get(f"/projets/{self.p1}"))
        self.assertIn('value="en_cours" selected>En cours (bloqué\u00a0: une tâche est bloquée)', page)


class TestClotureDuProjet(_Projets):
    """I3 (décision 2) : clore un projet qui a des tâches ouvertes."""

    def setUp(self):
        super().setUp()
        self.t_bloquee = self.tache(self.p1, self.chef, etat="bloque")
        self.t_close = self.tache(self.p1, self.chef, etat="termine")
        self.sql("UPDATE projet SET etat = 'bloque' WHERE id = %s", (self.p1,))
        self.login(self.chef)

    def test_confirmation_puis_cloture_des_taches_dans_la_meme_transaction(self):
        r = self.informations(self.p1, etat="termine")
        self.assertEqual(r.status_code, 200)
        page = self.texte(r)
        self.assertIn(f'id="projet-{self.p1}-cloture-confirmation"', page)
        self.assertIn("Clore le projet et ses 2 tâches", page)
        self.assertEqual(sorted(int(x) for x in re.findall(r'name="taches_a_clore" value="(\d+)"', page)),
                         sorted([self.t1, self.t_bloquee]))
        self.assertIn('name="confirmer_cloture" value="1"', page)
        # Rien n'a changé avant la confirmation.
        self.assertEqual((self.etat(self.p1), self.etat_tache(self.t1)), ("bloque", "en_cours"))
        # Confirmation : le formulaire renvoyé tel quel.
        from werkzeug.datastructures import MultiDict
        champs = re.findall(r'<input type="hidden" name="([a-z_]+)" value="([^"]*)">', page)
        r = self.client.post(f"/projets/{self.p1}/informations",
                             data=MultiDict([(n, v) for n, v in champs if n != "csrf_token"]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.etat(self.p1), "termine")
        self.assertEqual([self.etat_tache(t) for t in (self.t1, self.t_bloquee, self.t_close)],
                         ["termine", "termine", "termine"])
        self.assertEqual(self.sql("SELECT date_fin FROM tache WHERE id = %s", (self.t1,))[0]["date_fin"], self.auj)
        post = self.posts(self.p1, "etat_projet")[-1]
        self.assertTrue(post["contenu"].startswith("Bloqué → Terminé — 2 tâches ouvertes terminées avec le projet"))
        self.assertIn("Clos avec ses 2 tâches", self.flash(r).replace("Projet clos", "Clos"))
        # Réouverture : recalcul (plus aucune tâche bloquée → En cours).
        self.informations(self.p1, etat="en_cours")
        self.assertEqual(self.etat(self.p1), "en_cours")

    def test_abandon_et_liste_changee(self):
        r = self.informations(self.p1, etat="abandonne")
        self.assertIn("Clore le projet et ses 2 tâches", self.texte(r))
        # Une tâche créée entre-temps : la confirmation est redemandée.
        nouvelle = self.tache(self.p1, self.chef)
        r = self.informations(self.p1, etat="abandonne", confirmer_cloture="1",
                              taches_a_clore=[str(self.t1), str(self.t_bloquee)])
        self.assertEqual(r.status_code, 200)
        self.assertIn("La liste des tâches ouvertes a changé", self.texte(r))
        self.assertEqual(self.etat(self.p1), "bloque")
        r = self.informations(self.p1, etat="abandonne", confirmer_cloture="1",
                              taches_a_clore=[str(self.t1), str(self.t_bloquee), str(nouvelle)])
        self.assertEqual(r.status_code, 302)
        self.assertEqual([self.etat_tache(t) for t in (self.t1, self.t_bloquee, nouvelle, self.t_close)],
                         ["abandonne", "abandonne", "abandonne", "termine"])
        self.assertEqual(self.etat(self.p1), "abandonne")

    def test_fragment_ajax_et_sans_tache_ouverte_pas_de_confirmation(self):
        r = self.client.post(f"/projets/{self.p1}/informations",
                             data={"nom": "Projet", "etat": "termine", "lots": "GO"},
                             headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_data(as_text=True).lstrip().startswith("{#") is False)
        self.assertNotIn("<html", r.get_data(as_text=True))
        self.assertIn(f'id="projet-{self.p1}-cloture-confirmation"', r.get_data(as_text=True))
        # Projet sans tâche ouverte : clos directement.
        p = self.projet(self.chef)
        r = self.informations(p, etat="termine")
        self.assertEqual((r.status_code, self.etat(p)), (302, "termine"))

    def test_intervenant_ne_peut_pas_clore(self):
        self.login(self.inter)
        r = self.informations(self.p1, etat="termine", confirmer_cloture="1",
                              taches_a_clore=[str(self.t1), str(self.t_bloquee)])
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.etat(self.p1), "bloque")


class TestCreationDeProjet(_Projets):
    """I4, I5, M5, M12, M14 (décision 3)."""

    def donnees(self, **autres):
        d = {"nom": "Neuf", "code": "26501X", "phase": "EXE", "lots": "GO", "date_debut": "2026-10-01"}
        d.update(autres)
        return d

    def test_chef_de_projet_ou_admin_seulement(self):
        self.login(self.chef)
        page = self.texte(self.client.get("/projets"))
        bloc = page.split('id="dialog-projet-chef"')[1].split("</select>")[0]
        self.assertIn("data-search-combobox", page.split('id="dialog-projet-chef"')[1].split(">")[0])
        ids = {int(x) for x in re.findall(r'<option value="(\d+)"', bloc)}
        self.assertIn(self.chef, ids)
        self.assertIn(self.admin, ids)
        self.assertNotIn(self.inter, ids)
        r = self.client.post("/projets/nouveau", data=self.donnees(chef_projet_id=str(self.inter)))
        self.assertEqual(r.status_code, 200)
        self.assertIn("Nouveau chef de projet invalide", self.visible(r))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet WHERE code = '26501X'"), 0)
        inactif = self.user("chef_de_projet", actif=False)
        self.client.post("/projets/nouveau", data=self.donnees(chef_projet_id=str(inactif)))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet WHERE code = '26501X'"), 0)

    def test_au_moins_un_lot(self):
        self.login(self.chef)
        r = self.client.post("/projets/nouveau", data={k: v for k, v in self.donnees().items() if k != "lots"})
        self.assertIn("Choisissez au moins un lot", self.visible(r))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet WHERE code = '26501X'"), 0)
        # Informations : on ne vide plus les lots d'un projet.
        r = self.client.post(f"/projets/{self.p1}/informations",
                             data={"nom": "Projet", "etat": "en_cours", "lots_envoyes": "1"})
        self.assertIn("Gardez au moins un lot", self.flash(r))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet_lot WHERE projet_id = %s", (self.p1,)), 1)

    def test_createur_d_une_autre_equipe_devient_co_chef(self):
        chef_urbs = self.user("chef_de_projet", "URBS")
        self.login(self.chef)
        r = self.client.post("/projets/nouveau", data=self.donnees(chef_projet_id=str(chef_urbs)))
        (p,) = self.sql("SELECT id, equipe_code FROM projet WHERE code = '26501X'")
        self.assertEqual(p["equipe_code"], "URBS")
        self.assertTrue(r.headers["Location"].endswith(f"/projets/{p['id']}"))
        self.assertIn("vous en êtes co-chef", self.flash(r))
        self.assertEqual(self.client.get(f"/projets/{p['id']}").status_code, 200)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet_co_chef WHERE projet_id = %s AND utilisateur_id = %s",
                                      (p["id"], self.chef)), 1)

    def test_equipe_du_createur_puis_midgard(self):
        sans = self.user("chef_de_projet", equipe=None)
        self.login(self.chef)
        self.client.post("/projets/nouveau", data=self.donnees(chef_projet_id=str(sans)))
        self.assertEqual(self.sql("SELECT equipe_code FROM projet WHERE code = '26501X'")[0]["equipe_code"], "MIDGARD")
        admin_sans = self.user("admin", equipe=None)
        self.login(admin_sans)
        self.client.post("/projets/nouveau", data=self.donnees(code="26502X", chef_projet_id=str(sans)))
        self.assertEqual(self.sql("SELECT equipe_code FROM projet WHERE code = '26502X'")[0]["equipe_code"], "MIDGARD")

    def test_code_propose_reserve_aux_createurs(self):
        for uid, attendu in ((self.inter, 403), (self.rh, 403), (self.chef, 200), (self.admin, 200)):
            with self.subTest(uid=uid):
                self.login(uid)
                self.assertEqual(self.client.get("/projets/code-propose?phase=EXE").status_code, attendu)
        client = self.user("client", "VD")
        self.login(client)
        self.assertEqual(self.client.get("/projets/code-propose?phase=EXE").status_code, 403)


class TestTacheExistante(_Projets):
    """I6, I7, M9, M10 (décision 4) : intervenants et échéance d'une tâche
    existante, retrait d'un intervenant du projet."""

    def setUp(self):
        super().setUp()
        self.inter2 = self.user("intervenant")
        self.sql("UPDATE utilisateur SET prenom = 'Omar', nom = 'Deux' WHERE id = %s", (self.inter2,))
        self.urbs = self.user("intervenant", "URBS")
        self.client_ipco = self.user("client", "VD")

    def test_ajouter_et_retirer_un_intervenant(self):
        self.login(self.cochef)
        fenetre = self.texte(self.client.get(f"/projets/{self.p1}/taches/{self.t1}/fenetre"))
        self.assertIn(f'id="tache-{self.t1}-intervenants"', fenetre)
        self.assertIn(f'id="tache-{self.t1}-echeance"', fenetre)
        bloc = fenetre.split(f'id="tache-{self.t1}-ajout-intervenant"')[1].split("</select>")[0]
        ids = {int(x) for x in re.findall(r'<option value="(\d+)"', bloc)}
        self.assertIn(self.inter2, ids)
        self.assertNotIn(self.urbs, ids)          # ne voit pas le projet
        self.assertNotIn(self.client_ipco, ids)
        self.assertNotIn(self.inter, ids)         # déjà affecté
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/intervenants",
                             data={"utilisateur_id": [str(self.inter2), str(self.urbs)]})
        self.assertTrue(r.headers["Location"].endswith(f"/projets/{self.p1}?tache={self.t1}"))
        message = self.flash(r)
        self.assertIn("1 intervenant ajouté à la tâche", message)
        self.assertIn("n’a pas accès à ce projet", message)
        self.assertEqual({x["utilisateur_id"] for x in self.sql(
            "SELECT utilisateur_id FROM tache_intervenant WHERE tache_id = %s", (self.t1,))}, {self.inter, self.inter2})
        (n,) = self.notifs(self.inter2)
        self.assertEqual(n["tache_id"], self.t1)
        self.assertIn("Nouvelle tâche pour vous\u00a0: «\u00a0", n["message"])
        self.assertIn("a ajouté Omar Deux", self.posts(self.p1, "intervenant_tache")[-1]["contenu"])
        self.assertEqual(self.compter("SELECT count(*) AS n FROM audit_log WHERE table_cible = 'tache_intervenant' "
                                      "AND action = 'INSERT' AND utilisateur_id = %s", (self.cochef,)), 1)
        # Retrait.
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/intervenants/{self.inter}/retirer")
        self.assertIn("retiré de la tâche", self.flash(r))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM tache_intervenant WHERE tache_id = %s AND utilisateur_id = %s",
                                      (self.t1, self.inter)), 0)
        self.assertIn("vous a retiré de la tâche", self.notifs(self.inter)[-1]["message"])
        self.assertIn("a retiré Rim Inter", self.posts(self.p1, "intervenant_tache")[-1]["contenu"])

    def test_droits_et_taches_closes(self):
        # Intervenant de la tâche : refusé (ni ajout, ni retrait, ni échéance).
        self.login(self.inter)
        avant = self.compter("SELECT count(*) AS n FROM tache_intervenant")
        for url, donnees in ((f"/projets/{self.p1}/taches/{self.t1}/intervenants", {"utilisateur_id": str(self.inter2)}),
                             (f"/projets/{self.p1}/taches/{self.t1}/intervenants/{self.inter}/retirer", {}),
                             (f"/projets/{self.p1}/taches/{self.t1}/echeance", {"date_echeance": "", "type_deadline": "interne"}),
                             (f"/projets/{self.p1}/intervenants/{self.inter}/retirer", {})):
            with self.subTest(url=url):
                r = self.client.post(url, data=donnees)
                self.assertEqual(r.status_code, 302)
                self.assertIn("Seul le chef de projet, un co-chef ou un Admin", self.flash(r))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM tache_intervenant"), avant)
        # Projet invisible : 404.
        self.login(self.urbs)
        self.assertEqual(self.client.post(f"/projets/{self.p1}/taches/{self.t1}/intervenants",
                                          data={"utilisateur_id": str(self.urbs)}).status_code, 404)
        # Tâche d'un autre projet : introuvable.
        self.login(self.chef)
        t_autre = self.tache(self.p2, self.chef)
        r = self.client.post(f"/projets/{self.p1}/taches/{t_autre}/intervenants", data={"utilisateur_id": str(self.inter2)})
        self.assertIn("Tâche introuvable", self.flash(r))
        # Tâche close : refus.
        t_close = self.tache(self.p1, self.chef, etat="termine")
        r = self.client.post(f"/projets/{self.p1}/taches/{t_close}/intervenants", data={"utilisateur_id": str(self.inter2)})
        self.assertIn("Cette tâche est close", self.flash(r))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM tache_intervenant WHERE tache_id = %s", (t_close,)), 0)
        # « Voir comme » : lecture seule.
        self.entrer(self.chef)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/intervenants", data={"utilisateur_id": str(self.inter2)})
        self.assertEqual(r.status_code, 403)

    def test_echeance_et_type(self):
        self.login(self.chef)
        nouvelle = self.auj + datetime.timedelta(days=30)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/echeance",
                             data={"date_echeance": nouvelle.isoformat(), "type_deadline": "interne"})
        self.assertIn("Échéance mise à jour", self.flash(r))
        t = self.sql("SELECT date_echeance, type_deadline FROM tache WHERE id = %s", (self.t1,))[0]
        self.assertEqual((t["date_echeance"], t["type_deadline"]), (nouvelle, "interne"))
        post = self.posts(self.p1, "echeance_tache")[-1]
        self.assertTrue(post["contenu"].startswith("Échéance : "))
        self.assertIn("(rendu client) → ", post["contenu"])
        self.assertIn("Échéance de la tâche", self.notifs(self.inter)[-1]["message"])
        # Sans échéance.
        self.client.post(f"/projets/{self.p1}/taches/{self.t1}/echeance", data={"date_echeance": "", "type_deadline": "interne"})
        self.assertIsNone(self.sql("SELECT date_echeance FROM tache WHERE id = %s", (self.t1,))[0]["date_echeance"])
        # Avant le début du projet : refusé.
        self.sql("UPDATE projet SET date_debut = %s WHERE id = %s", (self.auj, self.p1))
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/echeance",
                             data={"date_echeance": (self.auj - datetime.timedelta(days=3)).isoformat(),
                                   "type_deadline": "interne"})
        self.assertIn("antérieure à la date de début du projet", self.flash(r))
        for invalide in ({"date_echeance": "demain", "type_deadline": "interne"},
                         {"date_echeance": "", "type_deadline": "urgent"}):
            r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/echeance", data=invalide)
            self.assertIn("invalide", self.flash(r))

    def test_retirer_du_projet(self):
        t_close = self.tache(self.p1, self.chef, etat="termine", intervenants=[self.inter])
        self.login(self.chef)
        page = self.texte(self.client.get(f"/projets/{self.p1}"))
        self.assertIn(f"/projets/{self.p1}/intervenants/{self.inter}/retirer", page)
        self.assertNotIn(f"/projets/{self.p1}/intervenants/{self.chef}/retirer", page)
        r = self.client.post(f"/projets/{self.p1}/intervenants/{self.chef}/retirer")
        self.assertIn("Le chef de projet titulaire ne se retire pas", self.flash(r))
        r = self.client.post(f"/projets/{self.p1}/intervenants/{self.inter}/retirer")
        self.assertIn("retiré du projet et de 1 tâche en cours", self.flash(r))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet_intervenant WHERE projet_id = %s AND utilisateur_id = %s",
                                      (self.p1, self.inter)), 0)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM tache_intervenant WHERE tache_id = %s", (self.t1,)), 0)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM tache_intervenant WHERE tache_id = %s", (t_close,)), 1)
        self.assertIn("vous a retiré du projet", self.notifs(self.inter)[-1]["message"])
        self.assertEqual(self.notifs(self.inter)[-1]["projet_id"], self.p1)
        self.assertIn("a retiré Rim Inter du projet", self.posts(self.p1, "intervenant_projet")[-1]["contenu"])
        # Co-chef retiré : il perd la gestion.
        self.client.post(f"/projets/{self.p1}/intervenants/{self.cochef}/retirer")
        self.assertEqual(self.compter("SELECT count(*) AS n FROM projet_co_chef WHERE projet_id = %s", (self.p1,)), 0)
        # Plus rien à retirer.
        r = self.client.post(f"/projets/{self.p1}/intervenants/{self.inter}/retirer")
        self.assertIn("n'est pas rattachée au projet", self.flash(r))

    def test_creation_de_tache_personne_ecartee_et_co_chef_signale(self):
        self.login(self.chef)
        page = self.texte(self.client.get(f"/projets/{self.p1}"))
        bloc = page.split('id="dialog-intervenants-tache"')[1].split("</select>")[0]
        ids = {int(x) for x in re.findall(r'<option value="(\d+)"', bloc)}
        self.assertNotIn(self.urbs, ids)
        self.assertNotIn(self.client_ipco, ids)
        autre_chef = self.user("chef_de_projet")
        self.sql("UPDATE utilisateur SET prenom = 'Sami', nom = 'Chef' WHERE id = %s", (autre_chef,))
        # Créée par le co-chef : le chef titulaire est prévenu du nouveau co-chef.
        self.login(self.cochef)
        r = self.client.post(f"/projets/{self.p1}/taches",
                             data={"titre": "Note de calcul", "type_deadline": "interne",
                                   "intervenants": [str(self.inter2), str(self.urbs), str(self.client_ipco), str(autre_chef)]})
        message = self.flash(r)
        self.assertIn("Tâche créée.", message)
        self.assertIn("n’ont pas accès à ce projet", message)
        self.assertIn("Sami Chef devient co-chef du projet", message)
        (t,) = self.sql("SELECT id FROM tache WHERE titre = 'Note de calcul'")
        self.assertEqual({x["utilisateur_id"] for x in self.sql(
            "SELECT utilisateur_id FROM tache_intervenant WHERE tache_id = %s", (t["id"],))}, {self.inter2, autre_chef})
        code = self.sql("SELECT code FROM projet WHERE id = %s", (self.p1,))[0]["code"]
        self.assertIn(f"«\u00a0Note de calcul\u00a0» ({code})", self.notifs(self.inter2)[-1]["message"])
        messages = [n["message"] for n in self.notifs(autre_chef)]
        self.assertTrue(any("vous en êtes maintenant co-chef" in m for m in messages), messages)
        self.assertTrue(any("Sami Chef est maintenant co-chef de votre projet" in n["message"]
                            for n in self.notifs(self.chef)))


class TestNotificationsEtDroits(_Projets):
    """I1, I8, M1, M2, M3, M4, M7, M8, M11, M13, M15."""

    def test_mes_projets_par_les_taches(self):
        p3 = self.projet(self.chef)
        self.tache(p3, self.chef, intervenants=[self.inter])
        p_abandonne = self.projet(self.chef, etat="abandonne")
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s)", (p_abandonne, self.inter))
        from app.repositories import projets
        self.assertIn(p3, {p["id"] for p in projets.list_mes_projets(self.inter)})
        recents = {p["id"] for p in projets.list_mes_projets_recents(self.inter, limit=50)}
        self.assertIn(p3, recents)
        self.assertNotIn(p_abandonne, recents)
        self.login(self.inter)
        code = self.sql("SELECT code FROM projet WHERE id = %s", (p3,))[0]["code"]
        self.assertIn(code, self.visible(self.client.get("/accueil")))

    def test_notifications_reliees_au_projet_et_au_post(self):
        autre = self.user("intervenant")
        self.login(self.chef)
        self.client.post(f"/projets/{self.p1}/intervenants", data={"utilisateur_id": str(autre)})
        (n,) = self.notifs(autre)
        self.assertEqual(n["projet_id"], self.p1)
        self.login(autre)
        r = self.client.post(f"/notifications/{n['id']}/ouvrir")
        self.assertTrue(r.headers["Location"].endswith(f"/projets/{self.p1}"), r.headers["Location"])
        # Rejoindre comme co-chef : le titulaire est notifié, avec le lien.
        chef2 = self.user("chef_de_projet")
        self.login(chef2)
        self.client.post(f"/projets/{self.p1}/rejoindre")
        n = self.notifs(self.chef)[-1]
        self.assertEqual(n["projet_id"], self.p1)
        # Mention sur un post : la fiche, ancrée sur le post.
        self.login(self.chef)
        self.client.post("/posts", data={"projet_id": str(self.p1), "type_code": "information", "contenu": "Bonjour"})
        post_id = self.sql("SELECT max(id) AS id FROM post WHERE projet_id = %s", (self.p1,))[0]["id"]
        self.client.post(f"/posts/{post_id}/commenter", data={"contenu": "@Rim Inter regarde"})
        n = self.notifs(self.inter)[-1]
        self.login(self.inter)
        r = self.client.post(f"/notifications/{n['id']}/ouvrir")
        self.assertTrue(r.headers["Location"].endswith(f"/projets/{self.p1}#post-{post_id}"), r.headers["Location"])

    def test_reponse_previent_l_auteur_du_commentaire(self):
        self.login(self.chef)
        self.client.post("/posts", data={"projet_id": str(self.p1), "type_code": "information", "contenu": "Info"})
        post_id = self.sql("SELECT max(id) AS id FROM post WHERE projet_id = %s", (self.p1,))[0]["id"]
        self.login(self.inter)
        self.client.post(f"/posts/{post_id}/commenter", data={"contenu": "Question"})
        self.assertIn("a commenté votre post", self.notifs(self.chef)[-1]["message"])
        com = self.sql("SELECT id FROM post_commentaire WHERE post_id = %s", (post_id,))[0]["id"]
        self.login(self.cochef)
        avant = len(self.notifs(self.inter))
        self.client.post(f"/posts/{post_id}/commenter", data={"contenu": "Réponse", "parent_commentaire_id": str(com)})
        self.assertEqual(len(self.notifs(self.inter)), avant + 1)
        self.assertIn("a répondu à votre commentaire", self.notifs(self.inter)[-1]["message"])
        # Pas de notification à soi-même.
        self.login(self.inter)
        avant = len(self.notifs(self.inter))
        self.client.post(f"/posts/{post_id}/commenter", data={"contenu": "Moi", "parent_commentaire_id": str(com)})
        self.assertEqual(len(self.notifs(self.inter)), avant)

    def test_admin_ne_rejoint_pas_et_liste_des_utilisateurs_pour_un_chef(self):
        self.login(self.admin)
        self.assertNotIn("Rejoindre ce projet", self.visible(self.client.get(f"/projets/{self.p1}")))
        self.sql("UPDATE utilisateur SET email = 'rim.inter@exemple.test', date_embauche = '2021-03-04' WHERE id = %s",
                 (self.inter,))
        self.assertIn("rim.inter@exemple.test", self.texte(self.client.get("/utilisateurs")))
        self.login(self.chef)
        page = self.texte(self.client.get("/utilisateurs"))
        self.assertIn("Rim Inter", page)
        self.assertNotIn("rim.inter@exemple.test", page)
        self.assertNotIn("4 mars 2021", page)

    def test_client_profil_et_information_d_equipe(self):
        client = self.user("client", "VD")
        self.sql("UPDATE utilisateur SET equipe_code = 'VD' WHERE id = %s", (self.inter,))
        self.sql("INSERT INTO dailylog_jour (utilisateur_id, date, absent, version) VALUES (%s, %s, true, 1)",
                 (self.inter, self.auj - datetime.timedelta(days=1)))
        self.login(client)
        page = self.visible(self.client.get(f"/utilisateurs/{self.inter}/profil"))
        self.assertNotIn("Absent", page)
        inactif = self.user("intervenant", "VD", actif=False)
        # Lot 20 (revue N6) : même réponse qu'un identifiant inexistant.
        self.assertEqual(self.client.get(f"/utilisateurs/{inactif}/profil").status_code, 302)
        self.assertEqual(self.client.get("/utilisateurs/999999/profil").status_code, 302)
        # Information « toutes les équipes » : jamais chez le client.
        self.login(self.admin)
        self.client.post("/posts", data={"type_code": "information", "contenu": "Info RH interne",
                                         "equipes": ["MIDGARD", "URBS", "VD"]})
        self.login(client)
        self.assertNotIn("Info RH interne", self.visible(self.client.get("/accueil")))
        self.login(self.inter)
        self.assertIn("Info RH interne", self.visible(self.client.get("/accueil")))

    def test_equipe_obligatoire_pour_un_compte_interne(self):
        self.login(self.admin)
        donnees = {"prenom": "Neo", "nom": "Phyte", "email": "neo@exemple.test", "role": "intervenant",
                   "fuseau": "Africa/Tunis"}
        r = self.client.post("/utilisateurs/nouveau", data=donnees)
        self.assertIn("Choisissez l’équipe de ce compte", self.visible(r))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM utilisateur WHERE email = 'neo@exemple.test'"), 0)
        self.client.post("/utilisateurs/nouveau", data={**donnees, "equipe_code": "MIDGARD"})
        self.assertEqual(self.compter("SELECT count(*) AS n FROM utilisateur WHERE email = 'neo@exemple.test'"), 1)

    def test_journal_filtre_invalide_signale(self):
        self.login(self.admin)
        page = self.visible(self.client.get("/admin/journal?table=xxx&date_debut=pas-une-date"))
        self.assertIn("Filtres invalides ignorés : table, dates.", page)
        self.assertNotIn("ignoré", self.visible(self.client.get("/admin/journal?table=projet")))


class TestCsrfDesNouvellesRoutes(_Projets):
    """Jeton CSRF exigé sur les routes du lot 13 (sans lui : rien n'est fait)."""
    CSRF = True
    MODE_TEST = True

    def test_sans_jeton_rien_n_est_fait(self):
        self.login(self.chef)
        avant = self.compter("SELECT count(*) AS n FROM tache_intervenant")
        for url, donnees in ((f"/projets/{self.p1}/taches/{self.t1}/intervenants", {"utilisateur_id": str(self.cochef)}),
                             (f"/projets/{self.p1}/taches/{self.t1}/intervenants/{self.inter}/retirer", {}),
                             (f"/projets/{self.p1}/taches/{self.t1}/echeance", {"date_echeance": "", "type_deadline": "interne"}),
                             (f"/projets/{self.p1}/intervenants/{self.inter}/retirer", {}),
                             (f"/projets/{self.p1}/informations", {"nom": "X", "etat": "termine"})):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data=donnees).status_code, 302)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM tache_intervenant"), avant)
        self.assertEqual(self.sql("SELECT date_echeance FROM tache WHERE id = %s", (self.t1,))[0]["date_echeance"],
                         self.auj + datetime.timedelta(days=5))
        self.assertEqual(self.etat(self.p1), "en_cours")
        self.login(self.admin)
        self.assertEqual(self.client.post("/admin/rappel-simule").status_code, 302)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification"), 0)

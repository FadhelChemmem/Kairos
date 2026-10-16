"""Lot 15 sur un vrai PostgreSQL : posts modifiables et supprimables
(« Annuler »), pièces jointes retirées puis purgées après 30 jours, tâche
citée par une Requête, réglages du compte, poste en lecture seule, page
unique d'une personne, accueil en deux colonnes et fiche projet sans
doublon de bouton."""
import datetime
import io
import json
import os
import re
from urllib.parse import unquote

from tests_integration.base import BaseIntegration


def partiel(cible):
    return {"X-Kairos-Partiel": cible, "X-Requested-With": "XMLHttpRequest"}


def toasts(r):
    return json.loads(unquote(r.headers.get("X-Kairos-Toasts", "%5B%5D")))


class _Base(BaseIntegration):
    def setUp(self):
        super().setUp()
        self.admin = self.user("admin")
        self.chef = self.user("chef_de_projet")
        self.inter = self.user("intervenant")
        self.autre = self.user("intervenant")
        self.p = self.projet(self.chef)
        self.sql("INSERT INTO projet_lot (projet_id, lot_code) VALUES (%s, 'GO')", (self.p,))
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s), (%s, %s)",
                 (self.p, self.inter, self.p, self.autre))
        self.t = self.tache(self.p, self.chef, intervenants=(self.inter,))

    def publier(self, auteur, contenu="Bonjour", type_code="information", **donnees):
        self.login(auteur)
        r = self.client.post("/posts", data={"projet_id": self.p, "type_code": type_code, "contenu": contenu,
                                             "next": "/accueil", **donnees})
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:500])
        return self.sql("SELECT max(id) AS id FROM post")[0]["id"]


class TestPostsModifierSupprimer(_Base):
    def test_auteur_modifie_son_post_en_partiel(self):
        pid = self.publier(self.inter, "Avant")
        r = self.client.post(f"/posts/{pid}/modifier", data={"contenu": "Après", "lien": "https://exemple.test/doc",
                                                             "show_projet": "1", "next": "/accueil"},
                             headers=partiel(f"#post-{pid}"))
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertTrue(html.lstrip().startswith(f'<div class="card post-card" id="post-{pid}"'))
        self.assertIn("Après", html)
        self.assertIn("modifié", html)
        self.assertEqual(toasts(r)[0]["texte"], "Post modifié.")
        ligne = self.sql("SELECT contenu, lien, modifie_le FROM post WHERE id = %s", (pid,))[0]
        self.assertEqual((ligne["contenu"], ligne["lien"]), ("Après", "https://exemple.test/doc"))
        self.assertIsNotNone(ligne["modifie_le"])

    def test_requete_objet_et_description(self):
        pid = self.publier(self.inter, "Objet A", type_code="requete", objet="Objet A")
        self.client.post(f"/posts/{pid}/modifier", data={"objet": "Objet B", "contenu": "Détail"})
        self.assertEqual(self.sql("SELECT contenu FROM post WHERE id = %s", (pid,))[0]["contenu"], "Objet B\n\nDétail")
        r = self.client.post(f"/posts/{pid}/modifier", data={"objet": "", "contenu": "x"}, headers=partiel(f"#post-{pid}"))
        self.assertEqual((r.status_code, list(r.get_json()["champs"])), (422, ["objet"]))

    def test_seul_l_auteur_modifie(self):
        pid = self.publier(self.inter, "Avant")
        for uid in (self.autre, self.chef, self.admin):
            self.login(uid)
            r = self.client.post(f"/posts/{pid}/modifier", data={"contenu": "Pirate"})
            self.assertEqual(r.status_code, 403, uid)
        self.assertEqual(self.sql("SELECT contenu FROM post WHERE id = %s", (pid,))[0]["contenu"], "Avant")

    def test_post_automatique_ni_modifiable_ni_supprimable(self):
        auto = self.sql("INSERT INTO post (projet_id, tache_id, auteur_id, type_code, contenu, evenement) "
                        "VALUES (%s, %s, %s, 'information', 'T', 'creation_tache') RETURNING id",
                        (self.p, self.t, self.chef))[0]["id"]
        self.login(self.chef)
        self.assertEqual(self.client.post(f"/posts/{auto}/modifier", data={"contenu": "x"}).status_code, 403)
        self.login(self.admin)
        self.assertEqual(self.client.post(f"/posts/{auto}/supprimer").status_code, 403)

    def test_suppression_logique_annuler_et_droits(self):
        pid = self.publier(self.inter, "À supprimer")
        # Un intervenant ne supprime pas le post d'un autre.
        self.login(self.autre)
        self.assertEqual(self.client.post(f"/posts/{pid}/supprimer").status_code, 403)
        # Le chef du projet le peut ; la carte devient « Post supprimé. ».
        self.login(self.chef)
        r = self.client.post(f"/posts/{pid}/supprimer", headers=partiel(f"#post-{pid}"))
        self.assertEqual(r.status_code, 200)
        self.assertIn(f'<div class="post-supprime" id="post-{pid}"', r.get_data(as_text=True))
        t = toasts(r)[0]
        self.assertEqual((t["texte"], t["action"]["libelle"]), ("Post supprimé.", "Annuler"))
        self.assertEqual(self.sql("SELECT supprime_par FROM post WHERE id = %s", (pid,))[0]["supprime_par"], self.chef)
        # Plus dans le fil, plus d'action possible dessus.
        self.assertNotIn("À supprimer", self.client.get(f"/projets/{self.p}?fil=tout").get_data(as_text=True))
        self.login(self.inter)
        self.assertNotIn("À supprimer", self.client.get("/accueil?fil=tout").get_data(as_text=True))
        self.assertEqual(self.client.post(f"/posts/{pid}/commenter", data={"contenu": "x"}).status_code, 404)
        # « Annuler » : seulement avec le jeton de la personne qui a supprimé.
        r = self.client.post(t["action"]["url"], data=t["action"]["donnees"], headers=partiel(f"#post-{pid}"))
        self.assertEqual(r.status_code, 409)
        self.login(self.chef)
        r = self.client.post(t["action"]["url"], data={"jeton": "faux"}, headers=partiel(f"#post-{pid}"))
        self.assertEqual(r.status_code, 409)
        r = self.client.post(t["action"]["url"], data=t["action"]["donnees"], headers=partiel(f"#post-{pid}"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("À supprimer", r.get_data(as_text=True))
        self.assertIsNone(self.sql("SELECT supprime_le FROM post WHERE id = %s", (pid,))[0]["supprime_le"])

    def test_auteur_et_admin_suppriment_projet_clos_admin_seul(self):
        pid = self.publier(self.inter, "Mon post")
        self.sql("UPDATE projet SET etat = 'termine', date_cloture = CURRENT_DATE WHERE id = %s", (self.p,))
        self.login(self.inter)
        self.assertEqual(self.client.post(f"/posts/{pid}/supprimer").status_code, 403)
        self.login(self.admin)
        self.assertEqual(self.client.post(f"/posts/{pid}/supprimer").status_code, 302)

    def test_menu_selon_les_droits(self):
        pid = self.publier(self.inter, "Menu")
        self.login(self.inter)
        html = self.client.get("/accueil?fil=tout").get_data(as_text=True)
        carte = html[html.index(f'id="post-{pid}"'):]
        self.assertIn(f'data-post-modifier="{pid}"', carte[:6000])
        self.assertIn(f'action="/posts/{pid}/supprimer"', carte[:6000])
        self.login(self.autre)
        html = self.client.get("/accueil?fil=tout").get_data(as_text=True)
        self.assertNotIn(f'action="/posts/{pid}/supprimer"', html)
        self.assertNotIn(f'data-post-modifier="{pid}"', html)
        self.login(self.chef)
        html = self.client.get(f"/projets/{self.p}?fil=tout").get_data(as_text=True)
        self.assertIn(f'action="/posts/{pid}/supprimer"', html)
        self.assertNotIn(f'data-post-modifier="{pid}"', html)


class TestRevueAnnuler(_Base):
    """Revue du lot 15 : jeton « Annuler » lié à l'action et à CETTE
    suppression, parent supprimé refusé, projet clos."""

    def supprimer(self, uid, pid):
        self.login(uid)
        r = self.client.post(f"/posts/{pid}/supprimer", data={"show_projet": "1", "next": "/accueil"},
                             headers=partiel(f"#post-{pid}"))
        self.assertEqual(r.status_code, 200)
        return toasts(r)[0]["action"]

    def test_annuler_garde_l_affichage_de_la_carte(self):
        pid = self.publier(self.inter, "Carte")
        action = self.supprimer(self.inter, pid)
        self.assertEqual((action["donnees"]["show_projet"], action["donnees"]["next"]), ("1", "/accueil"))

    def test_jeton_d_une_autre_action_refuse(self):
        self.login(self.inter)
        r = self.client.post("/posts", data={"projet_id": self.p, "type_code": "information", "contenu": "PJ",
                                             "fichier": (io.BytesIO(b"%PDF"), "a.pdf"), "next": "/accueil"},
                             content_type="multipart/form-data")
        pid = self.sql("SELECT max(id) AS id FROM post")[0]["id"]
        pj = self.sql("SELECT id FROM post_piece_jointe WHERE post_id = %s", (pid,))[0]["id"]
        r = self.client.post(f"/posts/{pid}/modifier", data={"contenu": "PJ", "retirer_pj": str(pj)},
                             headers=partiel(f"#post-{pid}"))
        jeton_pj = toasts(r)[0]["action"]["donnees"]
        self.client.post(f"/posts/{pid}/supprimer")
        r = self.client.post(f"/posts/{pid}/restaurer", data=jeton_pj, headers=partiel(f"#post-{pid}"))
        self.assertEqual(r.status_code, 409)
        self.assertIsNotNone(self.sql("SELECT supprime_le FROM post WHERE id = %s", (pid,))[0]["supprime_le"])

    def test_annuler_seulement_cette_suppression(self):
        pid = self.publier(self.inter, "Deux fois")
        action = self.supprimer(self.chef, pid)
        self.assertEqual(self.client.post(action["url"], data=action["donnees"]).status_code, 302)
        self.supprimer(self.admin, pid)
        # Le jeton du chef (encore valide) ne lève pas la suppression de l'Admin.
        self.login(self.chef)
        r = self.client.post(action["url"], data=action["donnees"], headers=partiel(f"#post-{pid}"))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.sql("SELECT supprime_par FROM post WHERE id = %s", (pid,))[0]["supprime_par"], self.admin)

    def test_annuler_refuse_si_projet_clos(self):
        pid = self.publier(self.inter, "Clos")
        action = self.supprimer(self.inter, pid)
        self.sql("UPDATE projet SET etat = 'termine', date_cloture = CURRENT_DATE WHERE id = %s", (self.p,))
        r = self.client.post(action["url"], data=action["donnees"], headers=partiel(f"#post-{pid}"))
        self.assertEqual(r.status_code, 409)

    def test_commentaire_annuler_et_reponse_a_un_supprime(self):
        pid = self.publier(self.inter, "Fil")
        self.client.post(f"/posts/{pid}/commenter", data={"contenu": "Question"})
        cid = self.sql("SELECT id FROM post_commentaire WHERE post_id = %s", (pid,))[0]["id"]
        cible = partiel(f"#post-{pid}-commentaires")
        r = self.client.post(f"/posts/commentaires/{cid}/supprimer", headers=cible)
        action = toasts(r)[0]["action"]
        self.login(self.autre)
        r = self.client.post(f"/posts/{pid}/commenter", data={"contenu": "Réponse", "parent_commentaire_id": cid},
                             headers=cible)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM post_commentaire WHERE post_id = %s", (pid,))[0]["n"], 1)
        self.login(self.inter)
        r = self.client.post(action["url"], data=action["donnees"], headers=cible)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Question", r.get_data(as_text=True))

    def test_rebond_sur_un_post_supprime_refuse(self):
        pid = self.publier(self.inter, "Parent")
        self.client.post(f"/posts/{pid}/supprimer")
        self.login(self.chef)
        r = self.client.post("/posts", data={"projet_id": self.p, "type_code": "information", "contenu": "Rebond",
                                             "parent_post_id": pid}, headers=partiel("#fil-liste"))
        self.assertEqual(r.status_code, 404)
        r = self.client.post(f"/projets/{self.p}/taches", data={"titre": "Rebond", "parent_post_id": pid,
                                                                "date_echeance": datetime.date.today().isoformat(),
                                                                "type_deadline": "interne"})
        self.assertEqual(r.status_code, 404)

    def test_rebond_sur_une_requete_qui_cite_une_tache(self):
        pid = self.publier(self.inter, "", type_code="requete", objet="Plans à jour ?", tache_id=str(self.t))
        self.publier(self.chef, "Oui", parent_post_id=str(pid))
        html = self.client.get(f"/projets/{self.p}?fil=tout").get_data(as_text=True)
        bloc = html[html.index('class="post-parent-corps"'):][:800]
        self.assertIn("Plans à jour ?", bloc)

    def test_purge_des_pieces_des_commentaires_d_un_post_supprime(self):
        from app import storage

        pid = self.publier(self.inter, "Avec commentaire")
        self.client.post(f"/posts/{pid}/commenter", data={"contenu": "PJ", "fichier": (io.BytesIO(b"x"), "c.txt")},
                         content_type="multipart/form-data")
        self.client.post(f"/posts/{pid}/supprimer")
        self.sql("UPDATE post SET supprime_le = now() - interval '31 days' WHERE id = %s", (pid,))
        with self.app.app_context():
            self.assertEqual(storage.purger_pieces_retirees(), 1)


class TestPiecesJointes(_Base):
    def setUp(self):
        super().setUp()
        self.login(self.inter)
        r = self.client.post("/posts", data={"projet_id": self.p, "type_code": "information", "contenu": "Avec PJ",
                                             "fichier": (io.BytesIO(b"%PDF-1.4"), "plan.pdf"), "next": "/accueil"},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        self.post = self.sql("SELECT max(id) AS id FROM post")[0]["id"]
        self.pj = self.sql("SELECT id, chemin FROM post_piece_jointe WHERE post_id = %s", (self.post,))[0]

    def chemin_disque(self, chemin):
        return os.path.join(self.app.config["UPLOAD_DIR"], chemin)

    def test_retirer_ajouter_annuler(self):
        r = self.client.post(f"/posts/{self.post}/modifier",
                             data={"contenu": "Avec PJ", "retirer_pj": str(self.pj["id"]),
                                   "fichier": (io.BytesIO(b"PNG"), "photo.png")},
                             content_type="multipart/form-data", headers=partiel(f"#post-{self.post}"))
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertNotIn("plan.pdf", html)
        self.assertIn("photo.png", html)
        t = toasts(r)[0]
        self.assertIn("1 fichier retiré", t["texte"])
        # Retirée : plus téléchargeable, fichier encore sur le disque.
        self.assertEqual(self.client.get(f"/fichiers/posts/{self.pj['id']}").status_code, 404)
        self.assertTrue(os.path.exists(self.chemin_disque(self.pj["chemin"])))
        r = self.client.post(t["action"]["url"], data=t["action"]["donnees"], headers=partiel(f"#post-{self.post}"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("plan.pdf", r.get_data(as_text=True))

    def test_purge_apres_30_jours(self):
        from app import storage

        self.client.post(f"/posts/{self.post}/modifier", data={"contenu": "Avec PJ", "retirer_pj": str(self.pj["id"])})
        with self.app.app_context():
            self.assertEqual(storage.purger_pieces_retirees(), 0)     # retirée aujourd'hui : gardée
            self.sql("UPDATE post_piece_jointe SET retire_le = now() - interval '31 days' WHERE id = %s", (self.pj["id"],))
            self.assertEqual(storage.purger_pieces_retirees(), 1)
        self.assertFalse(os.path.exists(self.chemin_disque(self.pj["chemin"])))
        self.assertEqual(self.sql("SELECT count(*) AS n FROM post_piece_jointe WHERE id = %s", (self.pj["id"],))[0]["n"], 0)

    def test_purge_des_fichiers_d_un_post_supprime(self):
        from app import storage

        self.client.post(f"/posts/{self.post}/supprimer")
        with self.app.app_context():
            self.assertEqual(storage.purger_pieces_retirees(), 0)
            self.sql("UPDATE post SET supprime_le = now() - interval '31 days' WHERE id = %s", (self.post,))
            self.assertEqual(storage.purger_pieces_retirees(), 1)
        self.assertFalse(os.path.exists(self.chemin_disque(self.pj["chemin"])))

    def test_piece_jointe_d_un_commentaire(self):
        r = self.client.post(f"/posts/{self.post}/commenter",
                             data={"contenu": "Voir pièce", "fichier": (io.BytesIO(b"x"), "note.txt")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 302)
        cid = self.sql("SELECT id FROM post_commentaire WHERE post_id = %s", (self.post,))[0]["id"]
        cpj = self.sql("SELECT id FROM post_commentaire_piece_jointe WHERE commentaire_id = %s", (cid,))[0]["id"]
        cible = partiel(f"#post-{self.post}-commentaires")
        r = self.client.post(f"/posts/commentaires/{cid}/modifier",
                             data={"contenu": "Voir pièce", "retirer_pj": str(cpj),
                                   "fichier": (io.BytesIO(b"y"), "nouvelle.txt")},
                             content_type="multipart/form-data", headers=cible)
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertNotIn("note.txt", html)
        self.assertIn("nouvelle.txt", html)
        t = toasts(r)[0]
        self.assertEqual(t["action"]["libelle"], "Annuler")
        r = self.client.post(t["action"]["url"], data=t["action"]["donnees"], headers=cible)
        self.assertIn("note.txt", r.get_data(as_text=True))
        # Un autre ne retire pas la pièce d'un commentaire qui n'est pas le sien.
        self.login(self.autre)
        r = self.client.post(f"/posts/commentaires/{cid}/modifier", data={"contenu": "x", "retirer_pj": str(cpj)})
        self.assertEqual(r.status_code, 403)


class TestRequeteTacheCitee(_Base):
    def test_tache_du_projet_citee_et_affichee(self):
        self.login(self.inter)
        r = self.client.get(f"/projets/{self.p}/taches-choix")
        self.assertEqual(r.get_json()["taches"][0]["id"], self.t)
        pid = self.publier(self.inter, "", type_code="requete", objet="Plans à jour ?", tache_id=str(self.t))
        self.assertEqual(self.sql("SELECT tache_id FROM post WHERE id = %s", (pid,))[0]["tache_id"], self.t)
        html = self.client.get(f"/projets/{self.p}?fil=tout").get_data(as_text=True)
        self.assertIn(f'href="/projets/{self.p}?tache={self.t}" class="post-tache-citee"', html)

    def test_tache_d_un_autre_projet_refusee(self):
        autre_projet = self.projet(self.chef)
        t2 = self.tache(autre_projet, self.chef)
        self.login(self.inter)
        r = self.client.post("/posts", data={"projet_id": self.p, "type_code": "requete", "objet": "x",
                                             "tache_id": str(t2)}, headers=partiel("#fil-liste"))
        self.assertEqual((r.status_code, list(r.get_json()["champs"])), (422, ["tache_id"]))
        # Projet d'une autre équipe : invisible, ses tâches aussi.
        urbs = self.projet(self.user("chef_de_projet", equipe="URBS"), equipe="URBS")
        self.assertEqual(self.client.get(f"/projets/{urbs}/taches-choix").status_code, 404)


class TestPreferencesEtPoste(_Base):
    def test_deadlines_repliees_par_defaut_puis_gardees(self):
        self.login(self.inter)
        html = self.client.get("/accueil").get_data(as_text=True)
        self.assertRegex(html, r'<details class="acc-deadlines" id="acc-deadlines" data-preference="accueil_deadlines" data-preference-url="/preferences" data-preference-etat="0">')
        self.assertEqual(self.client.post("/preferences", data={"cle": "accueil_deadlines", "valeur": "1"}).status_code, 204)
        self.assertIn('data-preference-url="/preferences" data-preference-etat="1" open>', self.client.get("/accueil").get_data(as_text=True))
        self.assertEqual(self.client.post("/preferences", data={"cle": "mot_de_passe", "valeur": "1"}).status_code, 400)

    def test_proposer_mes_taches_dans_l_amorce(self):
        self.login(self.inter)
        amorce = lambda: json.loads(re.search(r'id="dl-amorce">(.*?)</script>',  # noqa: E731
                                              self.client.get("/dailylog").get_data(as_text=True), re.S).group(1))
        self.assertTrue(amorce()["proposer"])
        self.client.post("/preferences", data={"cle": "dailylog_proposer", "valeur": "0"})
        self.assertFalse(amorce()["proposer"])

    def test_poste_en_lecture_seule_pour_la_personne(self):
        self.sql("UPDATE utilisateur SET poste = 'Projeteur' WHERE id = %s", (self.inter,))
        self.login(self.inter)
        html = self.client.get("/utilisateurs/moi").get_data(as_text=True)
        self.assertNotIn('name="poste"', html)
        self.assertIn("Projeteur", html)
        self.client.post("/utilisateurs/moi", data={"telephone": "", "poste": "Directeur", "adresse": "Tunis"})
        ligne = self.sql("SELECT poste, adresse FROM utilisateur WHERE id = %s", (self.inter,))[0]
        self.assertEqual((ligne["poste"], ligne["adresse"]), ("Projeteur", "Tunis"))


class TestPageDeLaPersonne(_Base):
    def test_taches_et_projets_en_cours(self):
        hier = datetime.date.today() - datetime.timedelta(days=3)
        en_retard = self.tache(self.p, self.chef, echeance=hier, intervenants=(self.inter,))
        bloquee = self.tache(self.p, self.chef, intervenants=(self.inter,))
        self.sql("UPDATE tache SET etat = 'bloque', bloque_motif = 'Attente', bloque_le = now() WHERE id = %s", (bloquee,))
        self.login(self.chef)
        html = self.client.get(f"/utilisateurs/{self.inter}/profil").get_data(as_text=True)
        self.assertIn("Tâches en cours", html)
        self.assertIn("Projets en cours", html)
        self.assertIn(f'href="/projets/{self.p}?tache={en_retard}"', html)
        self.assertIn(f'href="/projets/{self.p}?tache={bloquee}"', html)
        # Retard d'abord, puis bloquée, puis à venir.
        self.assertLess(html.index(f"tache={en_retard}\""), html.index(f"tache={bloquee}\""))
        self.assertLess(html.index(f"tache={bloquee}\""), html.index(f"tache={self.t}\""))
        self.assertIn("en retard", html)
        self.assertIn(f'href="/projets/{self.p}" class="acc-projet"', html)

    def test_projets_d_une_autre_equipe_caches(self):
        urbs = self.user("chef_de_projet", equipe="URBS")
        p_urbs = self.projet(urbs, equipe="URBS")
        self.tache(p_urbs, urbs, intervenants=(self.inter,))
        self.login(self.autre)
        html = self.client.get(f"/utilisateurs/{self.inter}/profil").get_data(as_text=True)
        self.assertNotIn(f'href="/projets/{p_urbs}"', html)

    def test_admin_et_rh_lien_vers_la_fiche(self):
        for uid, attendu in ((self.admin, "Modifier la fiche"), (self.chef, None)):
            self.login(uid)
            html = self.client.get(f"/utilisateurs/{self.inter}/profil").get_data(as_text=True)
            if attendu:
                self.assertIn(attendu, html)
            else:
                self.assertNotIn("Modifier la fiche", html)


class TestPagesSobres(_Base):
    def test_accueil_deux_colonnes_un_seul_nouveau_post(self):
        self.login(self.chef)
        html = self.client.get("/accueil").get_data(as_text=True)
        self.assertIn('class="acc-grille"', html)
        self.assertIn('class="acc-fil"', html)
        self.assertIn('class="acc-cote"', html)
        self.assertEqual(html.count("+ Nouveau post"), 1)
        # « À traiter » (chef) dans la colonne de droite, après « Mes projets ».
        self.assertLess(html.index('class="acc-cote"'), html.index('id="a-traiter"'))
        self.assertLess(html.index('id="acc-projets-titre"'), html.index('id="a-traiter"'))

    def test_fiche_projet_sans_doublon(self):
        self.login(self.chef)
        html = self.client.get(f"/projets/{self.p}").get_data(as_text=True)
        self.assertNotIn('id="nouvelle-tache"', html)
        self.assertEqual(html.count("+ Nouveau post"), 1)
        self.assertIn('class="page-body page-body-fiche"', html)
        self.assertIn('class="col fiche-cote"', html)


class TestMigration0021(BaseIntegration):
    def test_rejouable(self):
        from pathlib import Path

        sql = (Path(__file__).resolve().parent.parent / "migrations" / "0021_lot15_posts_et_preferences.sql").read_text(
            encoding="utf-8")
        with self.db.get_cursor() as cur:
            cur.execute(sql)
            cur.execute(sql)
        colonnes = {r["column_name"] for r in self.sql(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'post'")}
        self.assertTrue({"modifie_le", "supprime_le", "supprime_par"} <= colonnes)

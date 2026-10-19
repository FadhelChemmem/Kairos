"""Lot 13, phase 2 C, sur un vrai PostgreSQL : réponses partielles de la
fiche projet (panneau de tâche, Informations, intervenants, « + Tâche »),
du fil (commentaires, réaction, publication) et de « Tous les projets » —
mêmes droits que les routes classiques, repli sans JavaScript inchangé."""
import datetime
import io
import json
import re
from urllib.parse import unquote

from tests_integration.test_lot12 import _Base


def partiel(cible):
    return {"X-Kairos-Partiel": cible, "X-Requested-With": "XMLHttpRequest"}


def toasts(r):
    return json.loads(unquote(r.headers.get("X-Kairos-Toasts", "%5B%5D")))


def oob(html):
    """Ids des éléments hors cible d'un fragment."""
    return re.findall(r'id="([^"]+)"[^>]*data-partiel-oob', html)


class _Partiel(_Base):
    def setUp(self):
        super().setUp()
        self.sql("INSERT INTO projet_lot (projet_id, lot_code) VALUES (%s, 'GO')", (self.p1,))

    def etat(self, table, id_):
        return self.sql(f"SELECT etat FROM {table} WHERE id = %s", (id_,))[0]["etat"]


class TestPanneauDeTache(_Partiel):
    def test_etat_en_partiel_panneau_ligne_projet_et_fil(self):
        self.login(self.inter)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Attente des plans"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertNotIn("<html", html)
        self.assertTrue(html.lstrip().startswith(f'<div class="tache-fenetre" id="tache-fenetre-{self.t1}"'))
        ids = oob(html)
        for attendu in (f"tache-ligne-{self.t1}", "taches-compteur", "topbar-projet", "projet-entete",
                        "carte-informations", "carte-intervenants"):
            self.assertIn(attendu, ids)
        self.assertIn('id="fil-posts" data-partiel-oob="avant"', html)
        self.assertEqual(self.etat("projet", self.p1), "bloque")
        t = toasts(r)[0]
        # Lot 14 (P0-1) : le chef de projet est prévenu, et nommé.
        self.assertRegex(t["texte"], r"^Blocage signalé à .+\.$")
        self.assertEqual({k: v for k, v in t["action"]["donnees"].items() if k != "jeton"},
                         {"etat": "en_cours", "annulation": "1"})
        self.assertEqual(t["action"]["cible"], f"#tache-ligne-{self.t1}")
        # « Annuler » rejoué sur la ligne : la ligne est la racine, sans
        # nouveau « Annuler » ; le panneau suit hors cible.
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data=t["action"]["donnees"],
                             headers=partiel(f"#tache-ligne-{self.t1}"))
        html = r.get_data(as_text=True)
        self.assertTrue(html.lstrip().startswith('<div class="taskrow'))
        self.assertIn(f"tache-fenetre-{self.t1}", oob(html))
        self.assertNotIn("action", toasts(r)[0])
        self.assertEqual(self.etat("projet", self.p1), "en_cours")

    def test_cloture_deplace_la_ligne_et_repli_sans_js(self):
        self.login(self.inter)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/cloturer", data={"type_code": "envoi"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("carte-taches", oob(r.get_data(as_text=True)))
        self.assertEqual(toasts(r)[0]["action"]["donnees"]["etat"], "en_cours")
        # Sans JavaScript : redirection et message, comme avant.
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "en_cours"})
        self.assertEqual(r.status_code, 302)

    def test_refus_en_json_memes_droits(self):
        autre = self.user("intervenant")
        self.login(autre)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Attente des plans"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["erreur"], "interdit")
        self.assertEqual(self.etat("tache", self.t1), "en_cours")
        # Projet d'une autre équipe : 404 (JSON pour une requête partielle).
        r = self.client.post(f"/projets/{self.p2}/taches/{self.t2}/etat", data={"etat": "bloque", "motif": "Attente des plans"},
                             headers=partiel(f"#tache-fenetre-{self.t2}"))
        self.assertEqual(r.status_code, 404)
        # Intervenant : Vérifiée réservée au chef.
        self.login(self.inter)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "verifie"},
                             headers=partiel(f"#tache-fenetre-{self.t1}"))
        self.assertEqual(r.status_code, 403)

    def test_titre_echeance_et_erreurs_reliees_aux_champs(self):
        self.login(self.chef)
        cible = partiel(f"#tache-fenetre-{self.t1}")
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/titre", data={"titre": "  "}, headers=cible)
        self.assertEqual(r.status_code, 422)
        self.assertIn("titre", r.get_json()["champs"])
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/titre", data={"titre": "Nouveau titre"}, headers=cible)
        self.assertIn('class="tache-enregistre"', r.get_data(as_text=True))
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/echeance",
                             data={"date_echeance": "1990-01-01", "type_deadline": "interne"}, headers=cible)
        self.assertEqual(r.status_code, 422)
        self.assertIn("date_echeance", r.get_json()["champs"])
        demain = (datetime.date.today() + datetime.timedelta(days=20)).isoformat()
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/echeance",
                             data={"date_echeance": demain, "type_deadline": "interne"}, headers=cible)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(str(self.sql("SELECT date_echeance FROM tache WHERE id = %s", (self.t1,))[0]["date_echeance"]), demain)

    def test_intervenants_rejoindre_et_piece_jointe(self):
        voisin = self.user("intervenant")
        self.login(self.chef)
        cible = partiel(f"#tache-fenetre-{self.t1}")
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/intervenants", data={"utilisateur_id": voisin},
                             headers=cible)
        self.assertEqual(r.status_code, 200)
        self.assertIn(f'id="tache-{self.t1}-intervenant-{voisin}"', r.get_data(as_text=True))
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/intervenants/{voisin}/retirer", headers=cible)
        self.assertEqual(toasts(r)[0]["action"]["donnees"]["utilisateur_id"], str(voisin))
        # Rejoindre depuis la ligne : la ligne est la racine.
        self.login(voisin)
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/rejoindre", headers=partiel(f"#tache-ligne-{self.t1}"))
        html = r.get_data(as_text=True)
        self.assertTrue(html.lstrip().startswith('<div class="taskrow'))
        self.assertNotIn("task-join-btn", html.split("</div>")[0] + html.split('role="cell" class="taskrow-etat"')[0])
        # Pièce jointe : plus jamais sur une tâche (lot 20, décision du gérant).
        r = self.client.post(f"/fichiers/taches/{self.t1}/upload", headers=cible,
                             data={"fichier": (io.BytesIO(b"x" * 10), "plan.pdf")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 410)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM tache_piece_jointe")[0]["n"], 0)
        # Client : refusé aussi (404 s'il ne voit pas le projet, 410 sinon).
        client = self.user("client")
        self.login(client)
        r = self.client.post(f"/fichiers/taches/{self.t1}/upload", headers=cible,
                             data={"fichier": (io.BytesIO(b"x"), "a.pdf")}, content_type="multipart/form-data")
        self.assertIn(r.status_code, (404, 410))


class TestFicheProjet(_Partiel):
    def test_creation_de_tache_sur_la_fiche_et_a_l_accueil(self):
        self.login(self.chef)
        # Lot 14 : fil affiché sur « Tout » (adresse de la page, Referer).
        tout = {"Referer": f"http://localhost/projets/{self.p1}?fil=tout"}
        r = self.client.post(f"/projets/{self.p1}/taches", data={"titre": "Tâche partielle", "type_deadline": "interne"},
                             headers={**partiel("#fil-posts"), **tout})
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertTrue(html.lstrip().startswith('<div class="fil-item"'))
        self.assertIn("carte-taches", oob(html))
        self.assertIn("k-surligne", html)
        r = self.client.post(f"/projets/{self.p1}/taches", data={"titre": "", "type_deadline": "interne"},
                             headers=partiel("#fil-posts"))
        self.assertEqual(r.status_code, 422)
        self.assertEqual(list(r.get_json()["champs"]), ["titre"])
        r = self.client.post(f"/projets/{self.p1}/taches", data={"titre": "Depuis l'accueil", "type_deadline": "interne"},
                             headers={**partiel("#fil-liste"), "Referer": "http://localhost/accueil?fil=activite"})
        self.assertTrue(r.get_data(as_text=True).lstrip().startswith('<div class="fil-item"'))
        self.assertNotIn("carte-taches", oob(r.get_data(as_text=True)))

    def test_informations_confirmation_dans_la_fenetre_et_succes(self):
        self.login(self.chef)
        donnees = {"nom": "Projet", "etat": "termine", "client": "IPCO", "lots": "GO", "lots_envoyes": "1"}
        r = self.client.post(f"/projets/{self.p1}/informations", data=donnees, headers=partiel("#informations-form"))
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn('id="informations-form"', html)
        self.assertIn('data-partiel="#informations-form"', html)
        self.assertEqual(self.etat("projet", self.p1), "en_cours")
        donnees.update(confirmer_cloture="1", taches_a_clore=str(self.t1))
        r = self.client.post(f"/projets/{self.p1}/informations", data=donnees, headers=partiel("#informations-form"))
        html = r.get_data(as_text=True)
        self.assertIn("data-enregistre", html)
        for attendu in ("projet-entete", "carte-taches", "carte-intervenants", "fil-posts", "fil-nouveau-post"):
            self.assertIn(attendu, oob(html))
        self.assertEqual(self.etat("projet", self.p1), "termine")
        r = self.client.post(f"/projets/{self.p1}/informations", data={**donnees, "honoraires": "abc", "etat": "en_cours"},
                             headers=partiel("#informations-form"))
        self.assertEqual((r.status_code, list(r.get_json()["champs"])), (422, ["honoraires"]))
        # Formulaire seul (retour de la confirmation) : réservé à qui gère.
        self.assertEqual(self.client.get(f"/projets/{self.p1}/informations").status_code, 200)
        self.login(self.inter)
        self.assertEqual(self.client.get(f"/projets/{self.p1}/informations").status_code, 403)
        r = self.client.post(f"/projets/{self.p1}/informations", data=donnees, headers=partiel("#informations-form"))
        self.assertEqual(r.status_code, 403)

    def test_carte_intervenants(self):
        voisin = self.user("intervenant")
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p1}/intervenants", data={"utilisateur_id": voisin},
                             headers=partiel("#carte-intervenants"))
        self.assertTrue(r.get_data(as_text=True).lstrip().startswith('<div class="card" id="carte-intervenants"'))
        self.assertEqual(toasts(r)[0]["texte"], "Intervenant ajouté.")
        r = self.client.post(f"/projets/{self.p1}/intervenants/{voisin}/retirer", headers=partiel("#carte-intervenants"))
        self.assertIn("carte-taches", oob(r.get_data(as_text=True)))
        # Rejoindre (intervenant de l'équipe) : la carte ; un chef de projet
        # qui rejoint comme co-chef : vraie navigation (droits de gestion).
        self.login(voisin)
        r = self.client.post(f"/projets/{self.p1}/rejoindre", headers=partiel("#carte-intervenants"))
        self.assertEqual(r.status_code, 200)
        chef2 = self.user("chef_de_projet")
        self.login(chef2)
        r = self.client.post(f"/projets/{self.p1}/rejoindre", headers=partiel("#carte-intervenants"))
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r.headers["X-Kairos-Redirection"], f"/projets/{self.p1}")


class TestFil(_Partiel):
    def setUp(self):
        super().setUp()
        self.post = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', 'Bonjour') "
                             "RETURNING id", (self.p1, self.chef))[0]["id"]

    def test_commentaire_reponse_modification_suppression(self):
        self.login(self.inter)
        cible = partiel(f"#post-{self.post}-commentaires")
        r = self.client.post(f"/posts/{self.post}/commenter", data={"contenu": "Un avis", "next": "/accueil#post-1"},
                             headers=cible)
        html = r.get_data(as_text=True)
        self.assertTrue(html.lstrip().startswith(f'<div class="post-commentaires" id="post-{self.post}-commentaires"'))
        self.assertIn(f"post-{self.post}-compteur", oob(html))
        self.assertIn("data-partiel-titre", html)
        self.assertIn('name="next" value="/accueil#post-', html)
        cid = self.sql("SELECT id FROM post_commentaire WHERE post_id = %s", (self.post,))[0]["id"]
        r = self.client.post(f"/posts/{self.post}/commenter", data={"contenu": "  "}, headers=cible)
        self.assertEqual((r.status_code, list(r.get_json()["champs"])), (422, ["contenu"]))
        r = self.client.post(f"/posts/commentaires/{cid}/modifier", data={"contenu": "Avis modifié"}, headers=cible)
        self.assertIn(f'id="commentaire-{cid}-modifier" data-modifier="{cid}" data-partiel-titre', r.get_data(as_text=True))
        # Lot 15 : l'auteur supprime son commentaire (logique), « Annuler »
        # (jeton signé du toast) le rétablit ; l'Admin le peut aussi.
        r = self.client.post(f"/posts/commentaires/{cid}/supprimer", headers=cible)
        self.assertEqual(r.status_code, 200)
        t = toasts(r)[0]
        self.assertEqual((t["texte"], t["action"]["libelle"]), ("Commentaire supprimé.", "Annuler"))
        self.assertNotIn("Avis modifié", r.get_data(as_text=True))
        self.assertIsNotNone(self.sql("SELECT supprime_le FROM post_commentaire WHERE id = %s", (cid,))[0]["supprime_le"])
        r = self.client.post(t["action"]["url"], data=t["action"]["donnees"], headers=cible)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Avis modifié", r.get_data(as_text=True))
        self.assertIsNone(self.sql("SELECT supprime_le FROM post_commentaire WHERE id = %s", (cid,))[0]["supprime_le"])
        self.login(self.admin)
        r = self.client.post(t["action"]["url"], data=t["action"]["donnees"], headers=cible)
        self.assertEqual(r.status_code, 409)                               # jeton d'une autre personne
        r = self.client.post(f"/posts/commentaires/{cid}/supprimer", headers=cible)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(toasts(r)[0]["texte"], "Commentaire supprimé.")

    def test_reaction_json_et_projet_clos(self):
        self.login(self.inter)
        r = self.client.post(f"/posts/{self.post}/reagir", data={"reaction_code": "pouce"}, headers=partiel(f"#post-{self.post}"))
        self.assertEqual(r.get_json(), {"nb": 1, "ma_reaction": True, "reacteurs": "Rim Inter"})
        r = self.client.post(f"/posts/{self.post}/reagir/supprimer", headers=partiel(f"#post-{self.post}"))
        self.assertEqual(r.get_json()["nb"], 0)
        # Sans JavaScript : retour à la page.
        self.assertEqual(self.client.post(f"/posts/{self.post}/reagir", data={"reaction_code": "pouce"}).status_code, 302)
        self.sql("UPDATE projet SET etat = 'termine' WHERE id = %s", (self.p1,))
        r = self.client.post(f"/posts/{self.post}/reagir/supprimer", headers=partiel(f"#post-{self.post}"))
        self.assertEqual(r.status_code, 409)

    def test_publication_en_tete_du_fil(self):
        self.login(self.inter)
        r = self.client.post("/posts", data={"projet_id": self.p1, "type_code": "requete", "objet": "Plans ?"},
                             headers=partiel("#fil-liste"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_data(as_text=True).lstrip().startswith('<div class="fil-item"'))
        self.assertEqual(toasts(r)[0]["texte"], "Requête publiée.")
        # Page sans ce fil (profil) : toasts seuls.
        r = self.client.post("/posts", data={"projet_id": self.p1, "type_code": "information", "contenu": "Info"},
                             headers=partiel("#dialog-nouveau-post"))
        self.assertEqual(r.status_code, 204)
        r = self.client.post("/posts", data={"projet_id": self.p1, "type_code": "requete", "objet": ""},
                             headers=partiel("#fil-liste"))
        self.assertEqual((r.status_code, list(r.get_json()["champs"])), (422, ["objet"]))


class TestTousLesProjets(_Partiel):
    def test_resultats_statut_et_export_hors_cible(self):
        self.login(self.chef)
        r = self.client.get("/projets?filtres_actifs=1&etat=en_cours&q=projet", headers=partiel("#projets-resultats"))
        html = r.get_data(as_text=True)
        self.assertTrue(html.lstrip().startswith('<div id="projets-resultats"'))
        self.assertIn('role="table" aria-label="Projets"', html)
        self.assertEqual(sorted(oob(html)), ["export-excel", "projets-statut"])
        self.assertIn('href="/projets/export.xlsx?filtres_actifs=1&amp;etat=en_cours&amp;q=projet"', html)

    def test_creation_erreur_reliee_au_champ(self):
        self.login(self.chef)
        code = self.sql("SELECT code FROM projet WHERE id = %s", (self.p1,))[0]["code"]
        donnees = {"nom": "Doublon", "code": code, "phase": "EXE", "lots": "GO", "client": "IPCO"}
        r = self.client.post("/projets/nouveau", data=donnees, headers=partiel("#dialog-nouveau-projet"))
        self.assertEqual(r.status_code, 422)
        self.assertEqual(list(r.get_json()["champs"]), ["code"])
        # Page complète (sans JavaScript) : message sous le champ, aria-invalid.
        page = self.texte(self.client.post("/projets/nouveau", data=donnees))
        self.assertIn('aria-invalid="true" data-k-invalide="err-code" aria-describedby="err-code" autofocus', page)
        self.assertIn('<p class="champ-erreur" id="err-code" data-k-erreur>', page)
        # Succès en partiel : vraie navigation vers la fiche.
        r = self.client.post("/projets/nouveau", data={**donnees, "code": "26777X"}, headers=partiel("#dialog-nouveau-projet"))
        self.assertEqual(r.status_code, 204)
        self.assertRegex(r.headers["X-Kairos-Redirection"], r"^/projets/\d+$")

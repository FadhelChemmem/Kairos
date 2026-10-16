"""Lot 14, sur un vrai PostgreSQL : fil filtrable (revue produit P1-3) —
catégories Tout · Échanges · Activité calculées en SQL, pagination
« Afficher plus » par curseur, regroupements, et mêmes droits que les
pages (requêtes forgées refusées, Voir comme en lecture seule)."""
import datetime
import re

from tests_integration.test_lot12 import _Base


def partiel(cible, referer=None):
    h = {"X-Kairos-Partiel": cible, "X-Requested-With": "XMLHttpRequest"}
    if referer:
        h["Referer"] = "http://localhost" + referer
    return h


def ids_posts(html):
    return [int(x) for x in re.findall(r'id="post-(\d+)"', html)]


class _Fil(_Base):
    def setUp(self):
        super().setUp()
        self.t0 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)

    def post(self, evenement=None, contenu="Texte", minutes=0, auteur=None, projet=None, tache=None,
             type_code="information"):
        return self.sql(
            "INSERT INTO post (projet_id, tache_id, auteur_id, type_code, contenu, evenement, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (projet or self.p1, tache, auteur or self.chef, type_code, contenu, evenement,
             self.t0 - datetime.timedelta(minutes=minutes)))[0]["id"]

    def jeu(self):
        return {
            "info": self.post(None, "Question au BET", 0, auteur=self.inter, type_code="question"),
            "etat": self.post("etat_tache", "En cours → Bloqué", 5, tache=self.t1),
            "creation": self.post("creation_tache", "Note", 10, tache=self.t1),
            "cloture_msg": self.post("cloture_tache", "Envoyé au client", 15, tache=self.t1, type_code="envoi"),
            "cloture_vide": self.post("cloture_tache", None, 20, tache=self.t1, type_code="envoi"),
            "repost": self.post("repost", "Suite donnée", 25),
        }


class TestFilFiltrable(_Fil):
    def test_categories_en_sql(self):
        from app.repositories import posts as posts_repo
        j = self.jeu()
        with self.app.app_context():
            par = {c: [p["id"] for p in posts_repo.list_feed_projet(self.p1, self.chef, categorie=c)]
                   for c in ("tout", "echanges", "activite")}
        self.assertEqual(par["echanges"], [j["info"], j["cloture_msg"], j["repost"]])
        self.assertEqual(par["activite"], [j["etat"], j["creation"], j["cloture_vide"]])
        self.assertEqual(sorted(par["tout"]), sorted(j.values()))

    def test_fiche_fragment_regroupe_et_page_suivante(self):
        ids = [self.post("creation_tache", f"T{i}", minutes=i, tache=self.t1) for i in range(40)]
        self.login(self.chef)
        r = self.client.get(f"/projets/{self.p1}?fil=activite", headers=partiel("#fil-posts"))
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertTrue(html.lstrip().startswith('<div id="fil-posts" class="fil-liste" data-fil-categorie="activite"'))
        # 30 posts de la première page, en un regroupement (même projet, même
        # personne, moins d'une heure : 0 à 29 minutes).
        self.assertEqual(ids_posts(html), ids[:30])
        self.assertEqual(html.count('class="fil-item'), 1)
        self.assertIn("a créé une tâche", html)  # 30 créations de la même tâche
        suite = re.search(r'href="([^"]+)" id="fil-suite-lien"', html).group(1).replace("&amp;", "&")
        r = self.client.get(suite, headers=partiel("#fil-posts"))
        html = r.get_data(as_text=True)
        self.assertEqual(ids_posts(html), ids[30:])
        # Dernière page : plus de lien, une mention qui reçoit le focus.
        self.assertNotIn('fil-plus', html)
        self.assertIn('<p id="fil-suite-lien" class="fil-fin" tabindex="-1">Début du fil atteint', html)
        self.assertIn('id="fil-suite" class="fil-suite" data-partiel-oob', html)
        # Sans JavaScript : la page suivante s'ouvre en entier.
        r = self.client.get(suite)
        self.assertEqual(r.status_code, 200)
        self.assertIn("<html", r.get_data(as_text=True))

    def test_meme_horodatage_curseur_sans_perte(self):
        ids = [self.post(None, f"P{i}", minutes=0) for i in range(25)]
        self.login(self.chef)
        r = self.client.get("/accueil?fil=echanges", headers=partiel("#fil-liste"))
        html = r.get_data(as_text=True)
        vus = ids_posts(html)
        suite = re.search(r'href="([^"]+)" id="fil-suite-lien"', html).group(1).replace("&amp;", "&")
        vus += ids_posts(self.client.get(suite, headers=partiel("#fil-liste")).get_data(as_text=True))
        self.assertEqual(sorted(vus), sorted(ids))
        self.assertEqual(len(vus), len(set(vus)))

    def test_droits_requetes_forgees(self):
        self.jeu()
        urbs = self.user("intervenant", equipe="URBS")
        self.login(urbs)
        # Projet invisible : 404 (JSON en partiel), comme la page.
        r = self.client.get(f"/projets/{self.p1}?fil=tout", headers=partiel("#fil-posts"))
        self.assertEqual(r.status_code, 404)
        r = self.client.get(f"/projets/{self.p1}?fil=tout&avant=2099-01-01T00:00:00_1", headers=partiel("#fil-posts"))
        self.assertEqual(r.status_code, 404)
        # Profil du chef : aucun post d'un projet qu'on ne voit pas.
        r = self.client.get(f"/utilisateurs/{self.chef}/profil?fil=tout", headers=partiel("#profil-posts"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ids_posts(r.get_data(as_text=True)), [])
        r = self.client.get("/accueil?fil=tout", headers=partiel("#fil-liste"))
        self.assertEqual(ids_posts(r.get_data(as_text=True)), [])
        # Valeurs forgées : catégorie inconnue = défaut, curseur illisible ignoré.
        self.login(self.chef)
        r = self.client.get("/accueil?fil=tout%27%20OR%201=1--&avant=x", headers=partiel("#fil-liste"))
        self.assertEqual(r.status_code, 200)
        self.assertIn('data-fil-categorie="echanges"', r.get_data(as_text=True))

    def test_client_et_rh(self):
        info = self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (NULL, %s, 'information', "
                        "'Réunion interne') RETURNING id", (self.admin,))[0]["id"]
        self.sql("INSERT INTO post_equipe (post_id, equipe_code) VALUES (%s, 'MIDGARD')", (info,))
        client = self.user("client")
        self.login(client)
        r = self.client.get("/accueil?fil=tout", headers=partiel("#fil-liste"))
        self.assertNotIn(f'id="post-{info}"', r.get_data(as_text=True))
        self.login(self.rh)
        r = self.client.get("/accueil?fil=echanges", headers=partiel("#fil-liste"))
        self.assertIn(f'id="post-{info}"', r.get_data(as_text=True))

    def test_publication_et_creation_selon_la_categorie_affichee(self):
        self.login(self.inter)
        donnees = {"projet_id": self.p1, "type_code": "information", "contenu": "Bonjour"}
        r = self.client.post("/posts", data=donnees, headers=partiel("#fil-liste", "/accueil?fil=activite"))
        self.assertEqual(r.status_code, 204)
        r = self.client.post("/posts", data=donnees, headers=partiel("#fil-liste", "/accueil"))
        self.assertTrue(r.get_data(as_text=True).lstrip().startswith('<div class="fil-item"'))
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p1}/taches", data={"titre": "Nouvelle", "type_deadline": "interne"},
                             headers=partiel("#fil-posts", f"/projets/{self.p1}"))
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(html.lstrip().startswith('<div class="fil-item"'))
        self.assertIn('id="carte-taches"', html)

    def test_commentaire_garde_le_champ_ouvert(self):
        pid = self.post(None, "Question", 0)
        self.login(self.inter)
        r = self.client.post(f"/posts/{pid}/commenter", data={"contenu": "Réponse"},
                             headers=partiel(f"#post-{pid}-commentaires"))
        html = r.get_data(as_text=True)
        self.assertIn(f'<div class="post-commenter" id="post-{pid}-composer">', html)
        cid = self.sql("SELECT id FROM post_commentaire WHERE post_id = %s", (pid,))[0]["id"]
        r = self.client.post(f"/posts/{pid}/commenter", data={"contenu": "Sous-réponse", "parent_commentaire_id": cid},
                             headers=partiel(f"#post-{pid}-commentaires"))
        self.assertIn(f'<div class="post-commenter" id="post-{pid}-composer" data-replie>', r.get_data(as_text=True))


class TestVoirComme(_Base):
    MODE_TEST = True

    def test_lecture_seule_le_fil_se_filtre(self):
        self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu, evenement) VALUES "
                 "(%s, %s, 'information', 'Auto', 'etat_projet')", (self.p1, self.chef))
        self.entrer(self.chef)
        r = self.client.get(f"/projets/{self.p1}?fil=activite", headers=partiel("#fil-posts"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("a changé l’état du projet", r.get_data(as_text=True))
        # Écriture refusée (lecture seule), même forgée.
        r = self.client.post("/posts", data={"projet_id": self.p1, "type_code": "information", "contenu": "x"},
                             headers=partiel("#fil-posts", f"/projets/{self.p1}?fil=tout"))
        self.assertEqual(r.status_code, 403)


class TestRecetteFil(_Fil):
    """Recette du lot 14 : n° 6 (catégorie d'une page complète jamais
    reprise du Referer) et n° 13 (lien vers un post ancien)."""

    def categorie(self, r, liste="fil-posts"):
        return re.search(rf'id="{liste}" class="fil-liste" data-fil-categorie="(\w+)"', r.get_data(as_text=True)).group(1)

    def test_page_complete_ignore_le_referer(self):
        self.jeu()
        self.login(self.chef)
        referer = {"Referer": f"http://localhost/projets/{self.p1}?fil=activite"}
        self.assertEqual(self.categorie(self.client.get("/accueil", headers=referer), "fil-liste"), "echanges")
        self.assertEqual(self.categorie(self.client.get(f"/projets/{self.p1}", headers=referer)), "echanges")
        # Une action en partiel garde la catégorie de la page d'où elle part.
        r = self.client.get(f"/projets/{self.p1}", headers=partiel("#fil-posts", f"/projets/{self.p1}?fil=activite"))
        self.assertEqual(self.categorie(r), "activite")
        # L'adresse prime toujours.
        self.assertEqual(self.categorie(self.client.get("/accueil?fil=tout", headers=referer), "fil-liste"), "tout")

    def test_jusqua_un_post_ancien(self):
        ids = [self.post(None, f"Info {i}", minutes=i * 70) for i in range(45)]
        self.login(self.chef)
        page = self.client.get(f"/projets/{self.p1}?fil=tout").get_data(as_text=True)
        self.assertNotIn(f'id="post-{ids[40]}"', page)
        for adresse, cible in ((f"/projets/{self.p1}?fil=tout&jusqua={ids[40]}", "#fil-posts"),
                               (f"/accueil?fil=tout&jusqua={ids[40]}", "#fil-liste")):
            with self.subTest(adresse=adresse):
                for entetes in ({}, partiel(cible)):
                    html = self.client.get(adresse, headers=entetes).get_data(as_text=True)
                    self.assertIn(f'id="post-{ids[40]}"', html)
                    self.assertNotIn(f'id="post-{ids[41]}"', html)
                    # La suite repart après lui, sans doublon.
                    suite = re.search(r'href="([^"]+)" id="fil-suite-lien"', html).group(1).replace("&amp;", "&")
                    html2 = self.client.get(suite, headers=partiel(cible)).get_data(as_text=True)
                    self.assertEqual(ids_posts(html2)[:1], [ids[41]])
        # Post d'un projet invisible, inexistant ou valeur forgée : page normale.
        autre = self.projet(self.user("chef_de_projet"), equipe="URBS")
        cache = self.post(None, "Caché", minutes=1, projet=autre)
        for valeur in (cache, 999999, "x", "1" * 30):
            with self.subTest(valeur=valeur):
                html = self.client.get(f"/projets/{self.p1}?fil=tout&jusqua={valeur}").get_data(as_text=True)
                self.assertEqual(len(ids_posts(html)), 30)

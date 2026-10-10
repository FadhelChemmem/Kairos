"""Lot 14 — fil filtrable (revue produit P1-3) : catégories Tout · Échanges ·
Activité (SQL et adresse), regroupement des évènements automatiques,
« Afficher plus », « Commenter » replié. Même principe que
tests/test_smoke.py (psycopg2 simulé, repositories remplacés par des mocks).
"""
import datetime
import unittest
from unittest.mock import MagicMock, patch

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
    from test_lot13_front import _Base
except ImportError:  # python -m unittest tests.test_lot14_fil
    from tests import test_smoke as smoke
    from tests.test_lot13_front import _Base

from app import fil  # noqa: E402

T0 = datetime.datetime(2026, 10, 9, 15, 0, tzinfo=datetime.timezone.utc)


def auto(i, evenement="creation_tache", minutes=0, projet=1, auteur=2, tache=None, titre=None):
    return {**smoke.FEED_POST_MANUEL, "id": i, "evenement": evenement, "est_activite": True,
            "est_creation_tache": evenement == "creation_tache", "created_at": T0 - datetime.timedelta(minutes=minutes),
            "projet_id": projet, "auteur_id": auteur, "tache_id": tache if tache is not None else 100 + i,
            "tache_titre": titre or f"Tâche {i}", "contenu": "En cours → Bloqué"}


def ecrit(i, minutes=0, projet=1, auteur=2):
    return {**smoke.FEED_POST_MANUEL, "id": i, "evenement": None, "est_activite": False,
            "created_at": T0 - datetime.timedelta(minutes=minutes), "projet_id": projet, "auteur_id": auteur}


def espion(cible, **kw):
    m = MagicMock(**kw)
    m.patcher = patch(cible, new=m)
    return m


def partiel(cible):
    return {"X-Kairos-Partiel": cible, "X-Requested-With": "XMLHttpRequest"}


class TestResume(unittest.TestCase):
    def test_un_seul_type(self):
        self.assertEqual(fil.resume([auto(1), auto(2), auto(3)]), "a créé 3 tâches")
        self.assertEqual(fil.resume([auto(1, "etat_tache"), auto(2, "etat_tache")]), "a changé l’état de 2 tâches")

    def test_types_melanges_dans_l_ordre_d_arrivee(self):
        posts = [auto(3, "etat_tache", 0), auto(2, minutes=5), auto(1, minutes=10)]
        self.assertEqual(fil.resume(posts), "a créé 2 tâches et changé l’état d’une tâche")
        posts.append(auto(4, "creation_projet", 20))
        self.assertEqual(fil.resume(posts), "a créé le projet, créé 2 tâches et changé l’état d’une tâche")

    def test_meme_tache_comptee_une_fois(self):
        posts = [auto(i, "etat_tache", i, tache=7) for i in range(1, 4)]
        self.assertEqual(fil.resume(posts), "a changé l’état d’une tâche")

    def test_evenement_inconnu(self):
        self.assertEqual(fil.resume([auto(1, "affectation"), auto(2, "affectation")]), "a fait 2 modifications")


class TestRegrouper(unittest.TestCase):
    def test_meme_projet_meme_personne_dans_l_heure(self):
        entrees = fil.regrouper([auto(3, minutes=0), auto(2, minutes=20), auto(1, minutes=59)])
        self.assertEqual(len(entrees), 1)
        self.assertEqual([p["id"] for p in entrees[0]["groupe"]], [3, 2, 1])
        self.assertEqual(entrees[0]["phrase"], "a créé 3 tâches")
        self.assertEqual(entrees[0]["tete"]["id"], 3)
        self.assertEqual(entrees[0]["objets"], ["Tâche 3", "Tâche 2", "Tâche 1"])

    def test_au_dela_d_une_heure_autre_groupe(self):
        entrees = fil.regrouper([auto(3, minutes=0), auto(2, minutes=30), auto(1, minutes=61)])
        self.assertEqual([len(e.get("groupe", [e.get("post")])) for e in entrees], [2, 1])
        self.assertIn("post", entrees[1])

    def test_autre_projet_ou_autre_personne_separes(self):
        entrees = fil.regrouper([auto(3), auto(2, projet=2), auto(1, auteur=9)])
        self.assertEqual([e["post"]["id"] for e in entrees], [3, 2, 1])

    def test_echanges_jamais_regroupes_et_ordre_garde(self):
        posts = [auto(5, minutes=0), ecrit(4, minutes=5), auto(3, minutes=10), ecrit(2, minutes=15), auto(1, minutes=20)]
        entrees = fil.regrouper(posts)
        self.assertEqual(len(entrees), 3)
        self.assertEqual([p["id"] for p in entrees[0]["groupe"]], [5, 3, 1])
        self.assertEqual([entrees[1]["post"]["id"], entrees[2]["post"]["id"]], [4, 2])

    def test_objets_limites(self):
        entrees = fil.regrouper([auto(i, minutes=i) for i in range(1, 6)])
        self.assertEqual(entrees[0]["objets"], ["Tâche 1", "Tâche 2", "Tâche 3"])
        self.assertEqual(entrees[0]["objets_reste"], 2)


class TestCategorieEtCurseur(_Base):
    def test_categorie_adresse_referer_defaut(self):
        with self.app.test_request_context("/accueil?fil=activite"):
            self.assertEqual(fil.categorie_demandee(), "activite")
        with self.app.test_request_context("/accueil?fil=nimporte"):
            self.assertEqual(fil.categorie_demandee(), "echanges")
        with self.app.test_request_context("/projets/1/taches/2/etat", method="POST",
                                           headers={"Referer": "http://localhost/projets/1?fil=tout"}):
            self.assertEqual(fil.categorie_demandee(), "tout")
        with self.app.test_request_context("/posts", method="POST",
                                           headers={"Referer": "http://ailleurs.example/accueil?fil=tout"}):
            self.assertEqual(fil.categorie_demandee(), "echanges")
        with self.app.test_request_context("/accueil"):
            self.assertEqual(fil.categorie_demandee(), fil.CATEGORIE_DEFAUT)
        self.assertEqual(fil.CATEGORIE_DEFAUT, "echanges")

    def test_curseur(self):
        post = auto(42)
        with self.app.test_request_context("/accueil", query_string={"avant": fil.curseur_de(post)}):
            self.assertEqual(fil.curseur_demande(), (post["created_at"], 42))
        with self.app.test_request_context("/accueil?avant=pas-un-curseur"):
            self.assertIsNone(fil.curseur_demande())
        posts, suite = fil.page([auto(i) for i in range(4)], 3)
        self.assertEqual((len(posts), suite), (3, fil.curseur_de(posts[-1])))
        self.assertEqual(fil.page([auto(1)], 3)[1], None)


class TestSql(unittest.TestCase):
    def _sql(self, appel):
        with patch("app.db.get_cursor") as mock_cur:
            cur = mock_cur.return_value.__enter__.return_value
            cur.fetchall.return_value = []
            appel()
        return cur.execute.call_args.args

    def test_filtre_categorie_et_curseur_dans_la_page_d_ids(self):
        from app.repositories import posts as posts_repo
        sql, params = self._sql(lambda: posts_repo.list_feed_mes_projets(1, limit=21, categorie="echanges",
                                                                         avant=(T0, 9)))
        page = sql.split("WITH page AS (", 1)[1].split(")\n", 1)[0]
        self.assertIn("NOT (p.evenement IS NOT NULL AND p.evenement NOT IN ('repost', 'blocage_tache')", sql)
        self.assertIn("(p.created_at, p.id) < (%(avant_date)s::timestamptz, %(avant_id)s::bigint)", sql)
        self.assertIn("WHERE p.id = ANY (ARRAY(SELECT id FROM page))", sql)
        self.assertNotIn("json_agg", page)
        self.assertEqual((params["limit"], params["avant_date"], params["avant_id"]), (21, T0, 9))
        sql, _ = self._sql(lambda: posts_repo.list_feed_projet(1, 1, categorie="activite"))
        self.assertIn("AND (p.evenement IS NOT NULL AND p.evenement NOT IN ('repost', 'blocage_tache')", sql)
        sql, _ = self._sql(lambda: posts_repo.list_feed_auteur(3, 1, categorie="tout"))
        self.assertIn("AND TRUE", sql)

    def test_cloture_avec_message_est_un_echange(self):
        from app.repositories import posts as posts_repo
        self.assertIn("COALESCE(btrim(p.contenu), '') NOT IN ('', 'Tâche terminée.')",
                      posts_repo._EST_ACTIVITE)


class TestPages(_Base):
    def test_accueil_controle_segmente_et_commenter_replie(self):
        html = self._appel("get", "/accueil", **{"app.repositories.posts.list_feed_mes_projets": [ecrit(1)]}).get_data(
            as_text=True)
        self.assertIn('data-fil-filtres="accueil" data-fil-cible="#fil-liste"', html)
        self.assertIn('href="/accueil?fil=echanges" id="fil-filtre-accueil-echanges" data-fil="echanges" '
                      'data-partiel="#fil-liste" aria-current="page"', html)
        self.assertIn('id="fil-liste" class="fil-liste" data-fil-categorie="echanges"', html)
        self.assertIn('id="post-1-commenter" data-commenter="1" aria-expanded="false" aria-controls="post-1-composer"',
                      html)
        self.assertIn('<div class="post-commenter" id="post-1-composer" data-replie>', html)
        self.assertIn('id="commentaire-post-1"', html)
        self.assertIn("js/filtre-fil.js", html)
        self.assertNotIn('class="fil-plus', html)

    def test_accueil_regroupe_et_afficher_plus(self):
        posts = [auto(i, minutes=i) for i in range(21)]
        feed = espion("app.repositories.posts.list_feed_mes_projets", return_value=posts)
        html = self._appel("get", "/accueil?fil=activite", extra=[feed.patcher]).get_data(as_text=True)
        self.assertEqual(feed.call_args.kwargs["categorie"], "activite")
        self.assertEqual(feed.call_args.kwargs["limit"], 21)
        self.assertIn('id="fil-groupe-0"', html)
        self.assertIn("a créé 20 tâches sur", html)
        self.assertIn("Détail des 20 événements", html)
        self.assertIn('class="btn btn-pleine-largeur fil-plus" data-partiel="#fil-liste" data-partiel-mode="apres"', html)
        self.assertIn("avant=", html)

    def test_accueil_fragment_categorie(self):
        resp = self._appel("get", "/accueil?fil=tout", partiel("#fil-liste"),
                           **{"app.repositories.posts.list_feed_mes_projets": [ecrit(1), auto(2)]})
        html = resp.get_data(as_text=True)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("<html", html)
        self.assertTrue(html.lstrip().startswith('<div id="fil-liste" class="fil-liste" data-fil-categorie="tout"'))
        self.assertIn('<div id="fil-suite" class="fil-suite" data-partiel-oob>', html)
        self.assertIn('data-categorie="activite"', html)
        self.assertNotIn("Tâches de mes projets", html)

    def test_accueil_fragment_page_suivante(self):
        resp = self._appel("get", "/accueil?fil=echanges&avant=2026-10-09T15:00:00%2B00:00_9", partiel("#fil-liste"),
                           **{"app.repositories.posts.list_feed_mes_projets": [ecrit(8)]})
        html = resp.get_data(as_text=True)
        self.assertTrue(html.lstrip().startswith('<div class="fil-item" id="fil-item-8"'))
        self.assertIn('<div id="fil-suite" class="fil-suite" data-partiel-oob>', html)

    def test_etat_vide_echanges_propose_l_activite(self):
        html = self._appel("get", "/accueil", **{"app.repositories.posts.list_feed_mes_projets": []}).get_data(
            as_text=True)
        self.assertIn("Aucun échange pour l’instant", html)
        self.assertIn('href="/accueil?fil=activite" class="btn-fantome btn-petit" data-partiel="#fil-liste"', html)

    def test_fiche_fragment_et_page(self):
        feed = espion("app.repositories.posts.list_feed_projet", return_value=[ecrit(1)])
        resp = self._appel("get", "/projets/1?fil=activite", partiel("#fil-posts"), extra=[feed.patcher])
        html = resp.get_data(as_text=True)
        self.assertEqual(feed.call_args.kwargs["categorie"], "activite")
        self.assertEqual(feed.call_args.kwargs["limit"], 31)
        self.assertTrue(html.lstrip().startswith('<div id="fil-posts" class="fil-liste" data-fil-categorie="activite"'))
        self.assertNotIn("carte-taches", html)
        page = self._appel("get", "/projets/1", **{"app.repositories.posts.list_feed_projet": [ecrit(1)]}).get_data(
            as_text=True)
        self.assertIn('data-fil-filtres="projet" data-fil-cible="#fil-posts"', page)
        self.assertIn('href="/projets/1?fil=activite"', page)

    def test_profil_fragment(self):
        extra = {"app.repositories.utilisateurs.get_utilisateur": {**smoke.UTILISATEUR_PROFIL, "id": 3}}
        feed = espion("app.repositories.posts.list_feed_auteur", side_effect=[[auto(1), auto(2, minutes=3)], []])
        resp = self._appel("get", "/utilisateurs/3/profil?fil=activite", partiel("#profil-posts"),
                           extra=[feed.patcher], **extra)
        html = resp.get_data(as_text=True)
        self.assertEqual(feed.call_args_list[0].kwargs["categorie"], "activite")
        self.assertTrue(html.lstrip().startswith('<div id="profil-posts"'))
        self.assertIn("a créé 2 tâches", html)
        self.assertNotIn("Daily log", html)

    def test_projet_clos_compteur_sans_bouton(self):
        post = {**ecrit(1), "projet_etat": "termine"}
        html = self._appel("get", "/accueil", **{"app.repositories.posts.list_feed_mes_projets": [post]}).get_data(
            as_text=True)
        self.assertNotIn('data-commenter="1"', html)
        self.assertIn('id="post-1-compteur"', html)


class TestTypographieEtPaquet(unittest.TestCase):
    def test_feuille_lot14_dans_le_paquet(self):
        from app import paquets
        self.assertIn("css/lot14-a4.css", paquets.PAQUETS["app.css"])


if __name__ == "__main__":
    unittest.main()

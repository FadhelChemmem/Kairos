"""Lot 17 sur un vrai PostgreSQL (demandes du gérant du 17/10/2026) :
panneau de tâche à trois états (En cours · Bloquée · Terminée) avec
« Abandonner » en petit ; clôture avec date de fin choisie (hier, avant-hier,
jamais dans le futur ni avant la création) ; posts pas encore vus du fil
(pastille des onglets, repère « Nouveau », migration 0022) ; fil de
l'Admin sur tous les projets ouverts ; plusieurs pièces jointes par post ;
champ Lien masqué ; plus de bascule « Les miennes | Toutes »."""
import datetime
import io
import json
from urllib.parse import unquote

from tests_integration.base import BaseIntegration
from tests_integration.test_lot12 import _Base as _BaseModes


def partiel(cible):
    return {"X-Kairos-Partiel": cible, "X-Requested-With": "XMLHttpRequest"}


def toasts(r):
    return json.loads(unquote(r.headers.get("X-Kairos-Toasts", "%5B%5D")))


class _Base(BaseIntegration):
    def setUp(self):
        super().setUp()
        self.chef = self.user("chef_de_projet")
        self.inter = self.user("intervenant")
        self.autre = self.user("intervenant")
        self.p = self.projet(self.chef)
        self.sql("INSERT INTO projet_lot (projet_id, lot_code) VALUES (%s, 'GO')", (self.p,))
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s), (%s, %s)",
                 (self.p, self.inter, self.p, self.autre))
        self.t = self.tache(self.p, self.chef, intervenants=(self.inter,))

    def texte(self, r):
        import html
        return html.unescape(r.get_data(as_text=True))

    def fenetre(self):
        return self.texte(self.client.get(f"/projets/{self.p}/taches/{self.t}/fenetre"))

    def cloturer(self, **data):
        return self.client.post(f"/projets/{self.p}/taches/{self.t}/cloturer",
                                data={"type_code": "envoi", **data}, headers=partiel(f"#tache-fenetre-{self.t}"))

    def tache_lue(self):
        return self.sql("SELECT etat, date_fin FROM tache WHERE id = %s", (self.t,))[0]

    def aujourdhui(self):
        return self.sql("SELECT fn_date_ecriture('Africa/Tunis') AS d")[0]["d"]


class TestPanneauTroisEtats(_Base):
    def test_chef_trois_etats_et_abandonner_en_petit(self):
        self.login(self.chef)
        html = self.fenetre()
        zone = html.split(f'id="tache-{self.t}-etats"')[1].split("</form>")[0]
        for etat in ("en_cours", "bloque"):
            self.assertIn(f'name="etat" value="{etat}"', zone)
        self.assertIn(f'id="tache-{self.t}-etat-termine"', zone)
        for etat in ("verifie", "arret", "abandonne"):
            self.assertNotIn(f'value="{etat}"', zone)
        self.assertIn('class="tache-etats-autres"', html)
        self.assertIn(f'form="tache-{self.t}-etats" name="etat" value="abandonne"', html)
        # Pièces jointes de tâche : plus d'envoi ; « + M'ajouter » dans Intervenants.
        self.assertNotIn('enctype="multipart/form-data"', html)

    def test_intervenant_sans_abandonner(self):
        self.login(self.inter)
        html = self.fenetre()
        self.assertNotIn('value="abandonne"', html)
        self.assertIn(f'id="tache-{self.t}-etat-termine"', html)

    def test_abandonner_par_le_lien(self):
        self.login(self.chef)
        r = self.client.post(f"/projets/{self.p}/taches/{self.t}/etat", data={"etat": "abandonne"},
                             headers=partiel(f"#tache-fenetre-{self.t}"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.tache_lue()["etat"], "abandonne")
        html = self.texte(r)
        self.assertIn(f'id="tache-{self.t}-cloture-detail"', html)
        self.assertIn(">Reprendre</button>", html)
        self.assertNotIn('class="tache-etats-autres"', html)

    def test_terminee_encadre_date_auteur_et_rouvrir(self):
        self.login(self.inter)
        r = self.cloturer(contenu="Dossier EXE envoyé")
        self.assertEqual(r.status_code, 200)
        html = self.texte(r)
        self.assertIn(f'id="tache-{self.t}-cloture-detail"', html)
        self.assertRegex(html, r"<b>Terminée le [^<]+</b> par ")
        self.assertIn(f'id="tache-{self.t}-rouvrir"', html)


class TestDateDeFin(_Base):
    def test_par_defaut_aujourd_hui_et_bornes_du_champ(self):
        self.login(self.inter)
        html = self.fenetre()
        champ = html.split(f'id="cloture-date-{self.t}"')[1].split(">")[0]
        auj = self.aujourdhui().isoformat()
        self.assertIn(f'value="{auj}"', champ)
        self.assertIn(f'max="{auj}"', champ)
        self.assertIn("min=", champ)
        self.cloturer()
        self.assertEqual(self.tache_lue(), {"etat": "termine", "date_fin": self.aujourdhui()})

    def test_hier_accepte(self):
        self.sql("UPDATE tache SET created_at = now() - interval '5 days' WHERE id = %s", (self.t,))
        hier = self.aujourdhui() - datetime.timedelta(days=2)
        self.login(self.inter)
        r = self.cloturer(date_fin=hier.isoformat())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.tache_lue(), {"etat": "termine", "date_fin": hier})

    def test_futur_refuse(self):
        self.login(self.inter)
        demain = self.aujourdhui() + datetime.timedelta(days=1)
        r = self.cloturer(date_fin=demain.isoformat())
        self.assertEqual(r.status_code, 422)
        self.assertEqual(list(r.get_json()["champs"]), ["date_fin"])
        self.assertEqual(self.tache_lue()["etat"], "en_cours")

    def test_avant_la_creation_refusee(self):
        self.login(self.inter)
        r = self.cloturer(date_fin=(self.aujourdhui() - datetime.timedelta(days=30)).isoformat())
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.tache_lue()["etat"], "en_cours")

    def test_date_illisible_refusee(self):
        self.login(self.inter)
        r = self.cloturer(date_fin="17/10/2026")
        self.assertEqual(r.status_code, 422)


class TestPostsNonVus(_BaseModes):
    MODE_TEST = True     # « Agir comme » n'existe qu'en mode test

    def publier(self, auteur, texte, type_code="information"):
        self.login(auteur)
        r = self.client.post("/posts", data={"projet_id": self.p1, "type_code": type_code, "contenu": texte,
                                             "next": "/accueil"})
        self.assertEqual(r.status_code, 302)
        return self.sql("SELECT max(id) AS id FROM post")[0]["id"]

    def accueil(self, qui, fil=None):
        self.login(qui)
        return self.texte(self.client.get("/accueil" + (f"?fil={fil}" if fil else "")))

    def vieillir(self):
        self.sql("UPDATE utilisateur_fil_vu SET vu_le = vu_le - interval '1 minute'")

    def test_premiere_visite_rien_de_nouveau_puis_repere(self):
        self.publier(self.inter, "Ancien")
        page = self.accueil(self.chef)
        self.assertNotIn("fil-nouveau", page)
        self.vieillir()
        pid = self.publier(self.inter, "Plans indice C")
        mon_post = self.publier(self.chef, "Le mien")
        page = self.accueil(self.chef)
        self.assertIn(f'class="fil-item fil-nouveau" id="fil-item-{pid}"', page)
        self.assertNotIn(f'fil-nouveau" id="fil-item-{mon_post}"', page)
        # Vu : plus de repère à la visite suivante.
        self.assertNotIn("fil-nouveau", self.accueil(self.chef))

    def test_pastille_sur_l_autre_onglet(self):
        self.accueil(self.chef, "tout")          # les deux catégories vues
        self.vieillir()
        self.login(self.inter)
        self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Plans"})
        self.sql("UPDATE tache SET etat = 'en_cours' WHERE id = %s", (self.t1,))
        self.publier(self.inter, "Info")
        # Une activité automatique (création de tâche) pour l'onglet Activité.
        self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu, evenement) "
                 "VALUES (%s, %s, 'information', 'Tâche créée', 'creation_tache')", (self.p1, self.inter))
        page = self.accueil(self.chef, "echanges")
        # Activité : création de tâche + passage du projet en « Bloqué ».
        self.assertIn('>Activité<span class="fil-non-vus" data-fil-non-vus><span aria-hidden="true">2</span>'
                      '<span class="sr-only">, 2 nouveaux</span>', page)
        # Échanges affichés : pas de pastille sur leur propre onglet.
        self.assertEqual(page.count("data-fil-non-vus"), 1)
        page = self.accueil(self.chef, "activite")
        self.assertNotIn("data-fil-non-vus", page)

    def test_voir_comme_et_agir_comme_ne_consomment_pas(self):
        for mode in ("voir", "agir"):
            with self.subTest(mode=mode):
                self.sql("DELETE FROM utilisateur_fil_vu")
                self.entrer(self.inter, mode)
                self.client.get("/accueil")
                self.assertEqual(self.sql("SELECT count(*) AS n FROM utilisateur_fil_vu WHERE utilisateur_id = %s",
                                          (self.inter,))[0]["n"], 0)
                self.client.post("/admin/revenir", data={"next": "/accueil"})


class TestFilAdmin(_Base):
    def test_echanges_de_tous_les_projets_ouverts(self):
        admin = self.user("admin")
        ferme = self.projet(self.chef, etat="termine")
        for projet, texte in ((self.p, "Ouvert"), (ferme, "Fermé")):
            self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, 'information', %s)",
                     (projet, self.chef, texte))
        self.login(admin)
        page = self.texte(self.client.get("/accueil"))
        self.assertIn(">Ouvert<", page.replace("\n", "").replace("  ", ""))
        self.assertNotIn(">Fermé<", page.replace("\n", "").replace("  ", ""))
        # Un intervenant d'un autre projet : rien de ce projet.
        self.login(self.user("intervenant"))
        self.assertNotIn("Ouvert", self.texte(self.client.get("/accueil")))


class TestPiecesJointesMultiples(_Base):
    def poster(self, fichiers):
        self.login(self.inter)
        return self.client.post("/posts", data={"projet_id": self.p, "type_code": "information", "contenu": "PJ",
                                                "fichier": fichiers, "next": "/accueil"},
                                content_type="multipart/form-data", headers=partiel("#fil-liste"))

    def test_plusieurs_fichiers(self):
        r = self.poster([(io.BytesIO(b"PNG"), "Capture 2026-10-17 09h12.png"), (io.BytesIO(b"%PDF"), "plan.pdf")])
        self.assertIn(r.status_code, (200, 302))
        pid = self.sql("SELECT max(id) AS id FROM post")[0]["id"]
        noms = [x["nom_fichier"] for x in self.sql(
            "SELECT nom_fichier FROM post_piece_jointe WHERE post_id = %s ORDER BY id", (pid,))]
        self.assertEqual(noms, ["Capture 2026-10-17 09h12.png", "plan.pdf"])

    def test_plus_de_dix_refuse(self):
        r = self.poster([(io.BytesIO(b"x"), f"n{i}.txt") for i in range(11)])
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM post")[0]["n"], 0)

    def test_extension_refusee(self):
        r = self.poster([(io.BytesIO(b"MZ"), "outil.exe")])
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM post")[0]["n"], 0)


class TestPagesSimplifiees(_Base):
    def test_lien_masque_et_bascule_absente(self):
        self.login(self.chef)
        page = self.texte(self.client.get("/accueil"))
        self.assertNotIn("data-tdp-bascule", page)
        self.assertNotIn(">Les miennes</a>", page)
        self.assertIn("data-search-selection", page)
        self.assertIn("data-pj-zone", page)
        import re
        for champ in ("information", "requete"):
            ligne = re.search(r'<div[^>]*>\s*<label for="dialog-lien-' + champ + '"', page)
            self.assertIsNotNone(ligne, champ)
            self.assertIn("hidden", ligne.group(0).split(">")[0])

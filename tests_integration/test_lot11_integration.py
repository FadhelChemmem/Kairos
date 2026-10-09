"""Intégration du lot 11 (back + front) sur vraie base : refus serveur de
« Rejoindre » une tâche close, photos du sélecteur d'intervenant,
fenêtre de tâche (une seule tâche lue, dates et heures du back), et
recherche faite dans la page identique à fn_recherche()."""
import json
import pathlib
import shutil
import subprocess
import unittest

from tests_integration.base import BaseIntegration

RACINE = pathlib.Path(__file__).resolve().parent.parent


class TestRejoindreTacheClose(BaseIntegration):
    def test_refus_sur_chaque_etat_clos(self):
        chef, inter = self.user("chef_de_projet"), self.user("intervenant")
        p = self.projet(chef)
        self.login(inter)
        for etat in ("termine", "verifie", "arret", "abandonne"):
            with self.subTest(etat=etat):
                t = self.tache(p, chef, etat=etat)
                r = self.client.post(f"/projets/{p}/taches/{t}/rejoindre", follow_redirects=True)
                self.assertEqual(r.status_code, 200)
                self.assertIn("Cette tâche est close : on ne peut plus la rejoindre.", r.data.decode())
                n = self.sql("SELECT count(*) AS n FROM tache_intervenant WHERE tache_id = %s", (t,))[0]["n"]
                self.assertEqual(n, 0)

    def test_tache_ouverte_toujours_rejointe(self):
        chef, inter = self.user("chef_de_projet"), self.user("intervenant")
        p = self.projet(chef)
        for etat in ("en_cours", "bloque"):
            with self.subTest(etat=etat):
                t = self.tache(p, chef, etat=etat)
                self.login(inter)
                r = self.client.post(f"/projets/{p}/taches/{t}/rejoindre", follow_redirects=True)
                self.assertIn("Vous avez rejoint la tâche.", r.data.decode())
                self.assertEqual(self.sql("SELECT count(*) AS n FROM tache_intervenant WHERE tache_id = %s AND "
                                          "utilisateur_id = %s", (t, inter))[0]["n"], 1)

    def test_tache_d_un_autre_projet(self):
        chef, inter = self.user("chef_de_projet"), self.user("intervenant")
        p, p2 = self.projet(chef), self.projet(chef)
        t2 = self.tache(p2, chef)
        self.login(inter)
        r = self.client.post(f"/projets/{p}/taches/{t2}/rejoindre", follow_redirects=True)
        self.assertIn("Tâche introuvable sur ce projet.", r.data.decode())
        self.assertEqual(self.sql("SELECT count(*) AS n FROM tache_intervenant")[0]["n"], 0)


class TestSelecteurPhotos(BaseIntegration):
    def test_list_actifs_renvoie_avatar_chemin_et_selecteur_affiche_la_photo(self):
        from app.repositories import utilisateurs
        from app.utils import avatar_version

        chef, nouveau = self.user("chef_de_projet"), self.user("intervenant")
        self.sql("UPDATE utilisateur SET avatar_chemin = 'avatars/x/photo.png' WHERE id = %s", (nouveau,))
        with self.app.app_context():
            ligne = next(u for u in utilisateurs.list_actifs() if u["id"] == nouveau)
        self.assertEqual(ligne["avatar_chemin"], "avatars/x/photo.png")
        p = self.projet(chef)
        self.login(chef)
        page = self.client.get(f"/projets/{p}").data.decode()
        select = page.split('id="ajout-intervenant-choix"', 1)[1].split("</select>", 1)[0]
        self.assertIn(f'data-photo="/fichiers/avatars/{nouveau}?v={avatar_version("avatars/x/photo.png")}"', select)


class TestFenetreTache(BaseIntegration):
    def test_une_seule_tache_lue_dates_et_heures(self):
        import datetime

        from app.repositories import taches

        chef, inter = self.user("chef_de_projet"), self.user("intervenant")
        p = self.projet(chef)
        echeance = datetime.date(datetime.date.today().year - 1, 11, 17)
        t = self.tache(p, chef, intervenants=(inter,), echeance=echeance)
        self.tache(p, chef)
        for uid, heures in ((inter, 1.5), (chef, 0.5)):
            self.sql("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures) "
                     "VALUES (%s, current_date - 1, %s, %s, %s)", (uid, p, t, heures))
        with self.app.app_context():
            self.assertEqual([x["id"] for x in taches.list_taches_projet(p, tache_id=t)], [t])
            self.assertEqual(len(taches.list_taches_projet(p)), 2)
        self.login(chef)
        html = self.client.get(f"/projets/{p}/taches/{t}/fenetre").data.decode()
        # Lot 13 : le chef modifie l'échéance dans un champ date (année comprise).
        self.assertIn(f'value="{echeance.isoformat()}"', html)
        self.assertIn("1\u00a0h\u00a030 intervenants / 0\u00a0h\u00a030 chef de projet", html)


class TestRechercheNavigateurCommeServeur(BaseIntegration):
    """texte-recherche.js (sélecteur d'intervenant, puces de la fenêtre
    « Nouvelle tâche », Daily log) doit normaliser exactement comme
    fn_recherche() (migration 0016)."""

    ECHANTILLONS = [
        "Hélène Chérif", "ÉCOLE Ça", "Œuvre Æther", "Straße Łódź Ørsted", "l’équipe « x »",
        "R+2 – voile — B", "Naïve façade", "Ðavid Þór", "Ŀuc ĸ", "Gros Œuvre — 2ᵉ étage", "Ñandú Ågård",
    ]

    def test_meme_normalisation(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node indisponible")
        script = ("const kt = require(process.argv[1]); const e = JSON.parse(process.argv[2]);"
                  "process.stdout.write(JSON.stringify(e.map(kt.sansAccents)));")
        sortie = subprocess.run([node, "-e", script, str(RACINE / "app/static/js/texte-recherche.js"),
                                 json.dumps(self.ECHANTILLONS)], capture_output=True, text=True, check=True).stdout
        navigateur = json.loads(sortie)
        serveur = [self.sql("SELECT fn_recherche(%s) AS r", (e,))[0]["r"] for e in self.ECHANTILLONS]
        for e, n, s in zip(self.ECHANTILLONS, navigateur, serveur):
            with self.subTest(texte=e):
                self.assertEqual(n, s)


class TestRechercheClient(BaseIntegration):
    def test_client_sans_comptes_desactives(self):
        inactif = self.user("intervenant", actif=False)
        self.sql("UPDATE utilisateur SET prenom = 'Omrane', nom = 'Zéphyr' WHERE id = %s", (inactif,))
        for role, trouve in (("client", False), ("chef_de_projet", True)):
            with self.subTest(role=role):
                self.login(self.user(role))
                r = self.client.get("/recherche/api", query_string={"q": "zephyr"}).get_json()["resultats"]
                self.assertEqual(any(x["label"] == "Omrane Zéphyr (inactif)" for x in r), trouve)

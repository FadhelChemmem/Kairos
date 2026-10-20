"""Lot 16 sur un vrai PostgreSQL : scénario « cas réels » du 17/10/2026 et
revue des experts — une Requête prévient le chef, les co-chefs et les
intervenants de la tâche citée ; une tâche close ne se cite pas ; la levée
d'un blocage prévient qui l'avait signalé ; « Annuler » ne ressuscite pas
une réponse orpheline ; l'extrait d'un post supprimé quitte les
notifications ; mentions limitées aux personnes qui voient le projet ;
Daily log ouvert sur le dernier jour ouvré le week-end ; heure du blocage
simulée en mode test."""
import datetime
import json
import re
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
        self.cochef = self.user("chef_de_projet")
        self.inter = self.user("intervenant")
        self.autre = self.user("intervenant")
        self.urbs = self.user("intervenant", equipe="URBS")
        self.p = self.projet(self.chef)
        self.sql("INSERT INTO projet_lot (projet_id, lot_code) VALUES (%s, 'GO')", (self.p,))
        self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p, self.cochef))
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s), (%s, %s)",
                 (self.p, self.inter, self.p, self.autre))
        self.t = self.tache(self.p, self.chef, intervenants=(self.inter,))

    def notifs(self, uid):
        return [r["message"] for r in self.sql(
            "SELECT message FROM notification WHERE utilisateur_id = %s ORDER BY id", (uid,))]


class TestRequeteNotifiee(_Base):
    def test_chef_co_chef_et_intervenants_de_la_tache(self):
        self.login(self.autre)
        r = self.client.post("/posts", data={"projet_id": self.p, "type_code": "requete", "objet": "Rapport de sol ?",
                                             "contenu": "Contrainte admissible", "tache_id": str(self.t),
                                             "next": "/accueil"})
        self.assertEqual(r.status_code, 302)
        for uid in (self.chef, self.cochef, self.inter):
            messages = self.notifs(uid)
            self.assertEqual(len(messages), 1, uid)
            self.assertIn("a publié une requête sur", messages[0])
            self.assertIn("Rapport de sol ?", messages[0])
        self.assertEqual(self.notifs(self.autre), [])

    def test_personne_deja_mentionnee_et_information(self):
        self.login(self.inter)
        self.client.post("/posts", data={"projet_id": self.p, "type_code": "requete", "objet": "Visa ?",
                                         "mentions": str(self.chef), "next": "/accueil"})
        self.assertEqual(len(self.notifs(self.chef)), 1)          # la mention seule
        self.assertIn("mentionné", self.notifs(self.chef)[0])
        self.assertEqual(len(self.notifs(self.cochef)), 1)
        self.client.post("/posts", data={"projet_id": self.p, "type_code": "information", "contenu": "Info",
                                         "next": "/accueil"})
        self.assertEqual(len(self.notifs(self.cochef)), 1)        # une Information ne notifie pas

    def test_tache_close_refusee(self):
        self.sql("UPDATE tache SET etat = 'termine', date_fin = CURRENT_DATE WHERE id = %s", (self.t,))
        self.login(self.inter)
        r = self.client.post("/posts", data={"projet_id": self.p, "type_code": "requete", "objet": "x",
                                             "tache_id": str(self.t)}, headers=partiel("#fil-liste"))
        self.assertEqual((r.status_code, list(r.get_json()["champs"])), (422, ["tache_id"]))


class TestLeveeDeBlocage(_Base):
    def url(self):
        return f"/projets/{self.p}/taches/{self.t}/etat"

    def test_previent_qui_a_bloque_et_les_intervenants(self):
        self.sql("INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (%s, %s)", (self.t, self.autre))
        self.login(self.inter)
        self.client.post(self.url(), data={"etat": "bloque", "motif": "Plans archi"}, headers=partiel("#x"))
        self.login(self.chef)
        r = self.client.post(self.url(), data={"etat": "en_cours"}, headers=partiel(f"#tache-fenetre-{self.t}"))
        self.assertEqual(r.status_code, 200)
        t = toasts(r)[0]
        self.assertTrue(t["texte"].startswith("Blocage levé"), t["texte"])
        for uid in (self.inter, self.autre):
            self.assertTrue(any("a levé le blocage" in m for m in self.notifs(uid)), uid)
        self.assertFalse(any("a levé le blocage" in m for m in self.notifs(self.chef)))
        # « Annuler » : la tâche redevient bloquée, les notifications de la levée disparaissent.
        self.client.post(t["action"]["url"], data=t["action"]["donnees"], headers=partiel(f"#tache-fenetre-{self.t}"))
        self.assertEqual(self.sql("SELECT etat FROM tache WHERE id = %s", (self.t,))[0]["etat"], "bloque")
        self.assertFalse(any("a levé le blocage" in m for m in self.notifs(self.inter)))

    def test_levee_dans_les_echanges(self):
        self.login(self.inter)
        self.client.post(self.url(), data={"etat": "bloque", "motif": "Plans archi"})
        self.client.post(self.url(), data={"etat": "en_cours"})
        html = self.client.get(f"/projets/{self.p}?fil=echanges").get_data(as_text=True)
        self.assertIn("a levé le blocage", html)


class TestCommentairesEtNotifications(_Base):
    def test_annuler_une_reponse_dont_le_parent_a_ete_supprime(self):
        self.login(self.inter)
        r = self.client.post("/posts", data={"projet_id": self.p, "type_code": "information", "contenu": "Fil",
                                             "next": "/accueil"})
        pid = self.sql("SELECT max(id) AS id FROM post")[0]["id"]
        self.client.post(f"/posts/{pid}/commenter", data={"contenu": "Question"})
        parent = self.sql("SELECT id FROM post_commentaire WHERE post_id = %s", (pid,))[0]["id"]
        self.login(self.autre)
        self.client.post(f"/posts/{pid}/commenter", data={"contenu": "Réponse", "parent_commentaire_id": parent})
        reponse = self.sql("SELECT id FROM post_commentaire WHERE parent_commentaire_id = %s", (parent,))[0]["id"]
        cible = partiel(f"#post-{pid}-commentaires")
        r = self.client.post(f"/posts/commentaires/{reponse}/supprimer", headers=cible)
        action = toasts(r)[0]["action"]
        self.login(self.chef)
        self.client.post(f"/posts/commentaires/{parent}/supprimer", headers=cible)
        self.login(self.autre)
        r = self.client.post(action["url"], data=action["donnees"], headers=cible)
        self.assertEqual(r.status_code, 409)
        self.assertIsNotNone(self.sql("SELECT supprime_le FROM post_commentaire WHERE id = %s", (reponse,))[0]["supprime_le"])

    def test_extrait_d_un_post_supprime_retire_des_notifications(self):
        self.login(self.inter)
        self.client.post("/posts", data={"projet_id": self.p, "type_code": "information", "contenu": "Code porte 4321",
                                         "mentions": str(self.chef), "next": "/accueil"})
        pid = self.sql("SELECT max(id) AS id FROM post")[0]["id"]
        self.login(self.chef)
        self.assertIn("Code porte 4321", self.client.get("/notifications").get_data(as_text=True))
        self.login(self.inter)
        self.client.post(f"/posts/{pid}/supprimer")
        self.login(self.chef)
        html = self.client.get("/notifications").get_data(as_text=True)
        self.assertNotIn("4321", html)
        self.assertIn("(post supprimé).", html)

    def test_mentions_limitees_aux_personnes_qui_voient_le_projet(self):
        self.login(self.inter)
        html = self.client.get(f"/projets/{self.p}").get_data(as_text=True)
        bloc = html[html.index('id="dialog-mentions-requete"'):]
        bloc = bloc[:bloc.index("</select>")]
        self.assertIn(f'value="{self.chef}"', bloc)
        self.assertNotIn(f'value="{self.urbs}"', bloc)


class TestModeTestLot16(_BaseModes):
    MODE_TEST = True

    def samedi(self):
        d = self.auj - datetime.timedelta(days=7)
        while d.weekday() != 5:
            d -= datetime.timedelta(days=1)
        return d

    def amorce(self, chemin="/dailylog"):
        html = self.client.get(chemin).get_data(as_text=True)
        return json.loads(re.search(r'id="dl-amorce">(.*?)</script>', html, re.S).group(1))

    def test_daily_log_le_week_end_ouvre_le_vendredi(self):
        samedi = self.samedi()
        self.entrer(self.inter, mode="agir")
        self.client.post("/admin/date-simulee", data={"date": samedi.isoformat()})
        a = self.amorce()
        self.assertEqual(a["jour"]["date"], (samedi - datetime.timedelta(days=1)).isoformat())
        # Le samedi reste ouvert à la demande, sans tâches proposées.
        a = self.amorce(f"/dailylog?date={samedi.isoformat()}")
        self.assertEqual((a["jour"]["date"], a["jour"]["proposees"]), (samedi.isoformat(), []))

    def test_blocage_date_simulee(self):
        jour = self.auj - datetime.timedelta(days=20)
        # Lot 24 (HD-06) : la tâche existait ce jour-là (un blocage n'est
        # jamais daté avant la création de sa tâche).
        self.sql("UPDATE tache SET created_at = now() - interval '30 days' WHERE id = %s", (self.t1,))
        self.entrer(self.inter, mode="agir")
        self.client.post("/admin/date-simulee", data={"date": jour.isoformat(), "heure": "10:00"})
        self.client.post(f"/projets/{self.p1}/taches/{self.t1}/etat", data={"etat": "bloque", "motif": "Attente"})
        bloque_le = self.sql("SELECT (bloque_le AT TIME ZONE 'Africa/Tunis')::date AS d FROM tache WHERE id = %s",
                             (self.t1,))[0]["d"]
        self.assertEqual(bloque_le, jour)

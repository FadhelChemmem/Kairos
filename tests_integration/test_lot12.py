"""Lot 12 sur un vrai PostgreSQL : « Voir comme » (lecture seule, aucun
effet de bord, sécurité), « Agir comme » et date simulée (KAIROS_MODE_TEST),
journal d'audit (Admin réel), liens vers les tâches, vue Admin des
Deadlines, migration 0018 rejouable."""
import datetime
import os
import tempfile
from pathlib import Path

from tests_integration.base import URL, BaseIntegration

RACINE = Path(__file__).resolve().parent.parent
MIGRATION_0018 = RACINE / "migrations" / "0018_modes_admin_et_date_simulee.sql"


class _Base(BaseIntegration):
    MODE_TEST = False
    CSRF = False

    @classmethod
    def setUpClass(cls):
        if not URL:
            import unittest
            raise unittest.SkipTest("KAIROS_TEST_DATABASE_URL non défini")
        os.environ.setdefault("SECRET_KEY", "x" * 40)
        from app import create_app, db
        from app.config import Config

        class ConfigIT(Config):
            TESTING = True
            SECRET_KEY = "x" * 40
            DATABASE_URL = URL
            WTF_CSRF_ENABLED = cls.CSRF
            UPLOAD_DIR = tempfile.mkdtemp(prefix="kairos-it-")
            MODE_TEST = cls.MODE_TEST

        db._pool = None
        cls.app = create_app(ConfigIT)
        cls.db = db

    def setUp(self):
        super().setUp()
        self.auj = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=1))).date()
        self.admin = self.user("admin")
        self.admin2 = self.user("admin")
        self.inter = self.user("intervenant")
        self.chef = self.user("chef_de_projet")
        self.rh = self.user("rh", equipe=None)
        self.sql("UPDATE utilisateur SET prenom = 'Rim', nom = 'Inter', date_embauche = %s WHERE id = %s",
                 (self.auj - datetime.timedelta(days=60), self.inter))
        self.p1 = self.projet(self.chef)
        self.p2 = self.projet(self.chef, equipe="URBS")
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p1, self.inter))
        self.t1 = self.tache(self.p1, self.chef, intervenants=[self.inter], echeance=self.auj + datetime.timedelta(days=5))
        self.t2 = self.tache(self.p2, self.chef, echeance=self.auj + datetime.timedelta(days=9))

    # --- outils ----------------------------------------------------------
    def compter(self, requete, params=()):
        return self.sql(requete, params)[0]["n"]

    def journal(self, table):
        return self.sql("SELECT action, utilisateur_id, ligne_id, admin_reel_id, donnees_apres FROM audit_log "
                        "WHERE table_cible = %s ORDER BY id", (table,))

    def entrer(self, cible, mode="voir"):
        self.login(self.admin)
        url = "/admin/voir-comme" if mode == "voir" else "/admin/agir-comme"
        r = self.client.post(url, data={"utilisateur_id": str(cible)})
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True))
        return r

    def texte(self, r):
        import html
        return html.unescape(r.get_data(as_text=True))

    def visible(self, r):
        """Texte de la page sans balises, espaces regroupés."""
        import re
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", self.texte(r))).replace("\xa0", " ")


class TestVoirComme(_Base):
    def test_admin_voit_kairos_comme_l_intervenant(self):
        self.entrer(self.inter)
        r = self.client.get("/accueil")
        page = self.texte(r)
        self.assertEqual(r.status_code, 200)
        self.assertIn('class="bandeau-admin bandeau-admin-voir" role="region"', page)
        self.assertIn("Vous voyez Kairos comme Rim Inter (Intervenant) — Revenir à mon compte", self.visible(r))
        self.assertIn("Revenir à mon compte", page)
        # Menus de l'intervenant : ni Utilisateurs ni Journal d'audit.
        self.assertNotIn('aria-label="Journal d’audit"', page)
        self.assertNotIn('aria-label="Utilisateurs"', page)
        self.assertIn('aria-label="Daily log"', page)
        # Mes tâches : sa tâche, lien vers la fenêtre de la tâche (lot 12).
        self.assertIn(f'href="/projets/{self.p1}?tache={self.t1}"', page)
        # Projets visibles : les siens, pas ceux d'une autre équipe.
        self.assertEqual(self.client.get(f"/projets/{self.p1}").status_code, 200)
        self.assertEqual(self.client.get(f"/projets/{self.p2}").status_code, 404)
        # Pages de l'Admin refusées, comme pour lui.
        r = self.client.get("/admin/journal")
        self.assertEqual(r.status_code, 302)
        # Deadlines et Daily log : les siens.
        self.assertIn(f"/projets/{self.p1}?tache={self.t1}", self.texte(self.client.get("/deadlines")))
        self.assertIn('"soi": true', self.texte(self.client.get("/dailylog")))
        (entree,) = self.journal("mode_voir_comme")
        self.assertEqual((entree["action"], entree["utilisateur_id"], entree["ligne_id"], entree["admin_reel_id"]),
                         ("ENTREE", self.admin, self.inter, self.admin))
        self.assertEqual(entree["donnees_apres"]["compte_vu"], "Rim Inter")

    def test_lecture_seule_toute_ecriture_refusee(self):
        self.entrer(self.inter)
        avant = {t: self.compter(f"SELECT count(*) AS n FROM {t}") for t in
                 ("post", "dailylog_entree", "dailylog_jour", "notification", "tache_intervenant", "dailylog_preference")}
        cas = [
            ("post", "/posts", {"data": {"projet_id": str(self.p1), "type_code": "information", "contenu": "x"}}),
            ("post", f"/projets/{self.p1}/taches/{self.t1}/etat", {"data": {"etat": "bloque"}}),
            ("post", "/notifications/marquer-toutes-lues", {}),
            ("post", f"/projets/{self.p2}/rejoindre", {}),
            ("post", "/utilisateurs/moi", {"data": {"telephone": "123"}}),
        ]
        for methode, url, kw in cas:
            with self.subTest(url=url):
                r = getattr(self.client, methode)(url, **kw)
                self.assertEqual(r.status_code, 403)
                self.assertIn("lecture seule", self.texte(r))
                self.assertIn("Vous voyez Kairos comme Rim Inter", self.texte(r))
        # API JSON du Daily log : 403 en JSON (enregistrement, autosave
        # keepalive, absence, objectif).
        jour = self.auj.isoformat()
        for methode, url, corps in (
            ("put", f"/dailylog/api/jour/{jour}", {"version": 0, "lignes": [{"projet_id": self.p1, "tache_id": None, "minutes": 60}]}),
            ("post", f"/dailylog/api/jour/{jour}/absence", {"version": 0, "absent": True}),
            ("put", "/dailylog/api/objectif", {"objectif_minutes": 420}),
        ):
            with self.subTest(url=url):
                r = getattr(self.client, methode)(url, json=corps)
                self.assertEqual(r.status_code, 403)
                self.assertEqual(r.get_json()["erreur"], "lecture_seule")
                self.assertIn("lecture seule", r.get_json()["message"])
        # Une réaction en AJAX (X-Requested-With) : JSON aussi.
        r = self.client.post("/posts/1/reagir", headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertEqual((r.status_code, r.get_json()["erreur"]), (403, "lecture_seule"))
        apres = {t: self.compter(f"SELECT count(*) AS n FROM {t}") for t in avant}
        self.assertEqual(avant, apres)
        self.assertEqual(self.sql("SELECT etat FROM tache WHERE id = %s", (self.t1,))[0]["etat"], "en_cours")

    def test_aucun_effet_de_bord_en_lecture(self):
        # Jours oubliés (rappel attendu à sa propre connexion) et notification non lue.
        self.sql("INSERT INTO notification (utilisateur_id, categorie, message) VALUES (%s, 'projet', 'À lire')",
                 (self.inter,))
        self.sql("ALTER TABLE utilisateur DISABLE TRIGGER trg_utilisateur_updated_at;"
                 "UPDATE utilisateur SET updated_at = '2024-05-01 10:00+01';"
                 "ALTER TABLE utilisateur ENABLE TRIGGER trg_utilisateur_updated_at")
        self.entrer(self.inter)
        audit_avant = self.compter("SELECT count(*) AS n FROM audit_log")
        notifs_avant = self.sql("SELECT id, lu FROM notification ORDER BY id")
        for url in ("/accueil", "/dailylog", f"/dailylog?date={(self.auj - datetime.timedelta(days=3)).isoformat()}",
                    f"/dailylog/api/jour/{self.auj.isoformat()}", f"/dailylog/api/mois/{self.auj.strftime('%Y-%m')}",
                    "/notifications", "/deadlines", "/projets", f"/projets/{self.p1}", f"/projets/{self.p1}?tache={self.t1}",
                    f"/projets/{self.p1}/taches/{self.t1}/fenetre", "/utilisateurs/moi",
                    f"/utilisateurs/{self.chef}/profil", "/recherche/api?q=Pro", f"/fichiers/avatars/{self.inter}"):
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertIn(r.status_code, (200, 404), url)
        self.assertEqual(self.sql("SELECT id, lu FROM notification ORDER BY id"), notifs_avant)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE rappel_jours IS NOT NULL"), 0)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM audit_log"), audit_avant)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM utilisateur WHERE updated_at <> '2024-05-01 10:00+01'"), 0)
        # Ouvrir une notification (POST) : refusé, elle reste non lue.
        notif = notifs_avant[0]["id"]
        self.assertEqual(self.client.post(f"/notifications/{notif}/ouvrir").status_code, 403)
        self.assertFalse(self.sql("SELECT lu FROM notification WHERE id = %s", (notif,))[0]["lu"])

    def test_dernier_rempart_transaction_en_lecture_seule(self):
        from flask import g

        from app import db
        with self.app.test_request_context("/accueil"):
            g.lecture_seule = True
            with self.assertRaises(db.LectureSeule):
                db.execute("INSERT INTO notification (utilisateur_id, categorie, message) VALUES (%s, 'projet', 'x')",
                           (self.inter,))
            self.assertEqual(db.query_one("SELECT 1 AS un")["un"], 1)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification"), 0)

    def test_revenir_a_mon_compte(self):
        self.entrer(self.inter)
        r = self.client.post("/admin/revenir", data={"next": f"/projets/{self.p1}"})
        self.assertEqual((r.status_code, r.headers["Location"]), (302, f"/projets/{self.p1}"))
        page = self.texte(self.client.get("/accueil"))
        self.assertNotIn("bandeau-admin", page)
        self.assertIn('aria-label="Journal d’audit"', page)
        self.assertEqual([e["action"] for e in self.journal("mode_voir_comme")], ["ENTREE", "SORTIE"])
        # Adresse de retour extérieure : ignorée.
        self.entrer(self.inter)
        r = self.client.post("/admin/revenir", data={"next": "//evil.tld/x"})
        self.assertEqual(r.headers["Location"], "/admin/voir-comme")

    def test_jamais_un_admin_ni_un_compte_inactif(self):
        inactif = self.user("intervenant", actif=False)
        self.login(self.admin)
        for cible, message in ((self.admin2, "Impossible de voir Kairos comme un autre Admin."),
                               (self.admin, "Impossible de voir Kairos comme un autre Admin."),
                               (inactif, "est désactivé"), (999999, "Compte introuvable."),
                               ("abc", "Compte introuvable."), ("", "Choisissez un compte"),
                               ("9" * 30, "Compte introuvable.")):
            with self.subTest(cible=cible):
                r = self.client.post("/admin/voir-comme", data={"utilisateur_id": str(cible)}, follow_redirects=True)
                self.assertIn(message, self.texte(r))
                with self.client.session_transaction() as s:
                    self.assertNotIn("mode_admin", s)
        self.assertEqual(self.journal("mode_voir_comme"), [])
        # La liste ne propose que les comptes actifs non admin (RH compris).
        page = self.texte(self.client.get("/admin/voir-comme"))
        for uid in (self.inter, self.chef, self.rh):
            self.assertIn(f'<option value="{uid}"', page)
        for uid in (self.admin, self.admin2, inactif):
            self.assertNotIn(f'<option value="{uid}"', page)
        self.assertNotIn("Agir comme", page)

    def test_un_non_admin_ne_peut_rien_activer(self):
        for role_id in (self.chef, self.inter, self.rh):
            with self.subTest(role=role_id):
                self.login(role_id)
                self.assertEqual(self.client.post("/admin/voir-comme", data={"utilisateur_id": str(self.inter)}).status_code, 403)
                self.assertIn(self.client.get("/admin/voir-comme").status_code, (403,))
                # Session forgée (clé posée à la main, même liée à son id ou à celui d'un Admin).
                for admin_id in (role_id, self.admin):
                    with self.client.session_transaction() as s:
                        s["mode_admin"] = {"admin": admin_id, "cible": self.inter, "mode": "voir"}
                        s["date_simulee"] = {"admin": admin_id, "date": "2030-01-01"}
                    page = self.texte(self.client.get("/accueil"))
                    self.assertNotIn("bandeau-admin", page)
                    with self.client.session_transaction() as s:
                        self.assertNotIn("mode_admin", s)
                        self.assertNotIn("date_simulee", s)
        # Clé liée à un AUTRE Admin dans la session de l'Admin : ignorée.
        self.login(self.admin)
        with self.client.session_transaction() as s:
            s["mode_admin"] = {"admin": self.admin2, "cible": self.inter, "mode": "voir"}
        self.assertNotIn("bandeau-admin", self.texte(self.client.get("/accueil")))
        # Formes invalides : ignorées sans erreur.
        for forme in ({"admin": self.admin, "cible": str(self.inter), "mode": "voir"},
                      {"admin": self.admin, "cible": True, "mode": "voir"},
                      {"admin": self.admin, "cible": self.inter, "mode": "tout"}, "voir", [1, 2]):
            with self.subTest(forme=forme):
                with self.client.session_transaction() as s:
                    s["mode_admin"] = forme
                r = self.client.get("/accueil")
                self.assertEqual(r.status_code, 200)
                self.assertNotIn("bandeau-admin", self.texte(r))

    def test_compte_desactive_pendant_la_session_retour_automatique(self):
        self.entrer(self.inter)
        self.sql("UPDATE utilisateur SET actif = false WHERE id = %s", (self.inter,))
        r = self.client.get("/accueil")
        page = self.texte(r)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("bandeau-admin", page)
        self.assertIn("Le compte de Rim Inter est désactivé. Retour à votre compte.", page)
        self.assertIn('aria-label="Journal d’audit"', page)
        sortie = self.journal("mode_voir_comme")[-1]
        self.assertEqual((sortie["action"], sortie["donnees_apres"]["raison"]), ("SORTIE", "compte_refuse"))
        # Compte devenu Admin pendant la session : même chose.
        self.sql("UPDATE utilisateur SET actif = true WHERE id = %s", (self.inter,))
        self.entrer(self.inter)
        self.sql("UPDATE utilisateur SET role = 'admin' WHERE id = %s", (self.inter,))
        self.assertNotIn("bandeau-admin", self.texte(self.client.get("/accueil")))

    def test_admin_desactive_ou_deconnecte_perd_le_mode(self):
        self.entrer(self.inter)
        r = self.client.post("/deconnexion")
        self.assertEqual((r.status_code, r.headers["Location"]), (302, "/connexion"))
        with self.client.session_transaction() as s:
            self.assertNotIn("mode_admin", s)
            self.assertNotIn("user_id", s)
        self.assertEqual([e["action"] for e in self.journal("mode_voir_comme")], ["ENTREE", "SORTIE"])
        self.assertEqual(self.journal("mode_voir_comme")[-1]["donnees_apres"]["raison"], "deconnexion")
        # Admin désactivé par un autre Admin : sa session (et le mode) tombe.
        self.sql("DELETE FROM utilisateur_session")
        self.entrer(self.inter)
        self.sql("SET LOCAL app.current_user_id = %s; UPDATE utilisateur SET actif = false WHERE id = %s",
                 (str(self.admin2), self.admin))
        r = self.client.get("/accueil")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/connexion", r.headers["Location"])
        with self.client.session_transaction() as s:
            self.assertNotIn("mode_admin", s)

    def test_rien_du_mode_test_sans_kairos_mode_test(self):
        self.login(self.admin)
        self.assertEqual(self.client.post("/admin/agir-comme", data={"utilisateur_id": str(self.inter)}).status_code, 404)
        self.assertEqual(self.client.post("/admin/date-simulee", data={"date": "2030-01-01"}).status_code, 404)
        self.assertEqual(self.client.post("/admin/date-simulee/effacer").status_code, 404)
        page = self.texte(self.client.get("/accueil"))
        self.assertNotIn("bandeau-admin", page)
        self.assertNotIn("Date simulée", page)
        # Session d'un ancien mode test (agir, date) : retour au compte, vraie date.
        with self.client.session_transaction() as s:
            s["mode_admin"] = {"admin": self.admin, "cible": self.inter, "mode": "agir"}
            s["date_simulee"] = {"admin": self.admin, "date": "2030-01-01"}
        page = self.texte(self.client.get("/accueil"))
        self.assertNotIn("bandeau-admin", page)
        self.assertIn("Le mode test a été coupé", page)
        with self.client.session_transaction() as s:
            self.assertNotIn("mode_admin", s)
            self.assertNotIn("date_simulee", s)

    def test_vue_admin_des_deadlines(self):
        chef2 = self.user("chef_de_projet", equipe="URBS")
        p3 = self.projet(chef2, equipe="URBS")
        t3 = self.tache(p3, chef2, echeance=self.auj + datetime.timedelta(days=2))
        sans = self.sql("INSERT INTO tache (projet_id, titre, created_by, etat) VALUES (%s, 'Sans date', %s, 'en_cours') "
                        "RETURNING id", (p3, chef2))[0]["id"]
        self.tache(p3, chef2, etat="bloque")
        self.login(self.admin)
        page = self.texte(self.client.get("/deadlines"))
        self.assertIn("0 tâche avec échéance", page)
        self.assertIn('aria-current="page">Mes projets', page)
        page = self.texte(self.client.get("/deadlines?vue=tous"))
        self.assertIn("3 tâches avec échéance — tous les projets", page)
        for p, t in ((self.p1, self.t1), (self.p2, self.t2), (p3, t3), (p3, sans)):
            self.assertIn(f"/projets/{p}?tache={t}", page)
        self.assertIn("Tâches en cours sans échéance", page)
        page = self.texte(self.client.get(f"/deadlines?vue=tous&chef={chef2}"))
        self.assertIn("1 tâche avec échéance", page)
        page = self.texte(self.client.get("/deadlines?vue=tous&equipe=URBS"))
        self.assertIn("2 tâches avec échéance", page)
        page = self.texte(self.client.get("/deadlines?vue=tous&equipe=XXX&chef=abc"))
        self.assertIn("3 tâches avec échéance", page)
        # Les autres rôles : inchangés (paramètre ignoré, pas de bascule).
        self.login(self.inter)
        page = self.texte(self.client.get("/deadlines?vue=tous"))
        self.assertIn("1 tâche avec échéance", page)
        self.assertNotIn("Tous les projets</a>", page)
        self.assertIn(f"/projets/{self.p1}?tache={self.t1}", page)
        self.assertNotIn(f"tache={self.t2}", page)

    def test_lien_tache_ouvre_la_fenetre(self):
        self.login(self.inter)
        page = self.texte(self.client.get(f"/projets/{self.p1}?tache={self.t1}"))
        self.assertIn(f'data-ouvrir-au-chargement="{self.t1}"', page)


class TestCsrfDesModes(_Base):
    CSRF = True

    def test_routes_protegees_par_csrf(self):
        self.login(self.admin)
        r = self.client.post("/admin/voir-comme", data={"utilisateur_id": str(self.inter)})
        self.assertEqual(r.status_code, 302)
        with self.client.session_transaction() as s:
            self.assertNotIn("mode_admin", s)
            s["mode_admin"] = {"admin": self.admin, "cible": self.inter, "mode": "voir"}
        self.client.post("/admin/revenir")
        with self.client.session_transaction() as s:
            self.assertIn("mode_admin", s)


class TestModeTest(_Base):
    MODE_TEST = True

    def test_agir_comme_ecrit_au_nom_du_compte_et_trace_l_admin(self):
        self.entrer(self.inter, mode="agir")
        r = self.client.get("/accueil")
        self.assertIn('class="bandeau-admin bandeau-admin-agir" role="region"', self.texte(r))
        self.assertIn("Vous agissez comme Rim Inter (Intervenant) (mode test) — Revenir à mon compte", self.visible(r))
        r = self.client.post("/posts", data={"projet_id": str(self.p1), "type_code": "information",
                                             "contenu": "Post au nom de Rim", "next": "/accueil"})
        self.assertEqual(r.status_code, 302)
        post = self.sql("SELECT id, auteur_id FROM post WHERE contenu = 'Post au nom de Rim'")[0]
        self.assertEqual(post["auteur_id"], self.inter)
        audit = self.sql("SELECT utilisateur_id, admin_reel_id FROM audit_log WHERE table_cible = 'post' "
                         "AND ligne_id = %s AND action = 'INSERT'", (post["id"],))[0]
        self.assertEqual((audit["utilisateur_id"], audit["admin_reel_id"]), (self.inter, self.admin))
        jour = (self.auj - datetime.timedelta(days=1)).isoformat()
        r = self.client.put(f"/dailylog/api/jour/{jour}",
                            json={"version": 0, "lignes": [{"projet_id": self.p1, "tache_id": None, "minutes": 90}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        ligne = self.sql("SELECT utilisateur_id, updated_by, created_at::date AS cree FROM dailylog_entree")[0]
        self.assertEqual((ligne["utilisateur_id"], ligne["updated_by"]), (self.inter, self.inter))
        self.assertEqual(self.compter("SELECT count(*) AS n FROM audit_log WHERE table_cible LIKE 'dailylog%%' "
                                      "AND utilisateur_id = %s AND admin_reel_id = %s", (self.inter, self.admin)), 2)
        # Mot de passe du compte : jamais en « Agir comme ».
        r = self.client.post("/utilisateurs/moi/mot-de-passe", data={"mot_de_passe_actuel": "h"})
        self.assertEqual(r.status_code, 403)
        # Journal d'audit (retour à l'Admin) : « Rim Inter (par l'Admin …) ».
        self.client.post("/admin/revenir")
        page = self.texte(self.client.get("/admin/journal?table=post"))
        self.assertIn("Rim Inter", page)
        self.assertIn("(par l’Admin P admin)", page)
        self.assertEqual([e["action"] for e in self.journal("mode_agir_comme")], ["ENTREE", "SORTIE"])
        # Filtre « Auteur » = l'Admin : ses actions « comme » Rim comprises.
        page = self.texte(self.client.get(f"/admin/journal?table=post&utilisateur_id={self.admin}"))
        self.assertIn("(par l’Admin P admin)", page)

    def test_page_propose_agir_comme_et_date(self):
        self.login(self.admin)
        page = self.texte(self.client.get("/admin/voir-comme"))
        self.assertIn('formaction="/admin/agir-comme"', page)
        self.assertIn('class="bandeau-admin bandeau-admin-test" role="region"', page)
        self.assertIn('name="date"', page)
        # Un non-Admin : ni bandeau, ni route.
        self.login(self.inter)
        self.assertNotIn("bandeau-admin", self.texte(self.client.get("/accueil")))
        self.assertEqual(self.client.post("/admin/agir-comme", data={"utilisateur_id": str(self.chef)}).status_code, 403)
        self.assertEqual(self.client.post("/admin/date-simulee", data={"date": "2030-01-01"}).status_code, 403)

    def test_date_simulee_daily_log_et_echeances(self):
        self.login(self.admin)
        j3 = self.auj + datetime.timedelta(days=3)
        # Sans date simulée : J+3 refusé (jour futur).
        self.assertEqual(self.client.get(f"/dailylog?date={j3.isoformat()}").status_code, 302)
        r = self.client.post("/admin/date-simulee", data={"date": j3.isoformat(), "next": "/accueil"})
        self.assertEqual((r.status_code, r.headers["Location"]), (302, "/accueil"))
        from app.utils import date_longue
        accueil = self.visible(self.client.get("/accueil"))
        self.assertIn(f"Date simulée : {date_longue(j3)}", accueil)
        self.assertIn("— Revenir à aujourd’hui", accueil)
        self.assertEqual(self.client.get(f"/dailylog?date={j3.isoformat()}").status_code, 200)
        # Lot 13 (décision 5) : J+3 se consulte, mais ne s'écrit pas.
        r = self.client.put(f"/dailylog/api/jour/{j3.isoformat()}",
                            json={"version": 0, "lignes": [{"projet_id": self.p1, "tache_id": None, "minutes": 60}]})
        self.assertEqual((r.status_code, r.get_json()["erreur"]), (422, "futur_reel"))
        r = self.client.put(f"/dailylog/api/jour/{self.auj.isoformat()}",
                            json={"version": 0, "lignes": [{"projet_id": self.p1, "tache_id": None, "minutes": 60}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["aujourdhui"], j3.isoformat())
        # Horodatage réel, date simulée seulement pour la logique métier.
        self.assertEqual(self.sql("SELECT (created_at AT TIME ZONE 'Africa/Tunis')::date AS d FROM dailylog_entree")[0]["d"], self.auj)
        # Autre session (l'intervenant) : la vraie date.
        autre = self.app.test_client()
        with autre.session_transaction() as s:
            from app.auth import password_fingerprint
            s["user_id"] = self.inter
            s["pw_fingerprint"] = password_fingerprint("h")
        self.assertEqual(autre.get(f"/dailylog?date={j3.isoformat()}").status_code, 302)
        r = autre.put(f"/dailylog/api/jour/{j3.isoformat()}",
                      json={"version": 0, "lignes": [{"projet_id": self.p1, "tache_id": None, "minutes": 60}]})
        self.assertEqual((r.status_code, r.get_json()["erreur"]), (422, "date_future"))
        rappels = self.compter("SELECT count(*) AS n FROM notification WHERE rappel_jours IS NOT NULL")
        # Échéances : la tâche à J+5, vue avec la date simulée à J+10 → en retard de 5 j.
        self.client.post("/admin/date-simulee", data={"date": (self.auj + datetime.timedelta(days=10)).isoformat()})
        self.entrer(self.inter, mode="agir")
        self.assertIn("en retard de 5 j", self.texte(self.client.get("/deadlines")))
        self.assertIn("en retard de 5 j", self.texte(self.client.get("/accueil")))
        # Fenêtre de 14 jours décalée, pour l'intervenant agi.
        sim = self.auj + datetime.timedelta(days=10)
        for delta, attendu in ((14, 200), (15, 422), (10, 200), (0, 422)):
            jour = (sim - datetime.timedelta(days=delta)).isoformat()
            with self.subTest(jour=jour):
                r = self.client.put(f"/dailylog/api/jour/{jour}",
                                    json={"version": 0, "lignes": [{"projet_id": self.p1, "tache_id": None, "minutes": 30}]})
                self.assertEqual(r.status_code, attendu, r.get_data(as_text=True))
        # Pas de rappel Daily log créé pendant les modes.
        self.assertEqual(self.compter("SELECT count(*) AS n FROM notification WHERE rappel_jours IS NOT NULL"), rappels)
        # Revenir à aujourd'hui.
        self.client.post("/admin/revenir")
        self.client.post("/admin/date-simulee/effacer")
        self.assertEqual(self.client.get(f"/dailylog?date={j3.isoformat()}").status_code, 302)
        actions = [(e["action"], e["donnees_apres"].get("date")) for e in self.journal("date_simulee")]
        self.assertEqual(actions[0], ("ENTREE", j3.isoformat()))
        self.assertEqual(actions[-1][0], "SORTIE")

    def test_date_simulee_invalide_ou_hors_bornes(self):
        self.login(self.admin)
        for valeur in ("", "abc", "2026-02-31", "1999-12-31", "2100-01-01", "15/10/2026", "２０２６-10-15"):
            with self.subTest(valeur=valeur):
                r = self.client.post("/admin/date-simulee", data={"date": valeur}, follow_redirects=True)
                self.assertIn("Date simulée invalide", self.texte(r))
                with self.client.session_transaction() as s:
                    self.assertNotIn("date_simulee", s)

    def test_date_simulee_en_voir_comme_et_cloture_de_tache(self):
        self.login(self.admin)
        sim = self.auj + datetime.timedelta(days=20)
        self.client.post("/admin/date-simulee", data={"date": sim.isoformat()})
        # Voir comme + date simulée : le changement de date reste permis.
        self.entrer(self.inter)
        r = self.client.post("/admin/date-simulee", data={"date": (sim + datetime.timedelta(days=1)).isoformat()})
        self.assertEqual(r.status_code, 302)
        self.client.post("/admin/revenir")
        # Clôture d'une tâche par l'Admin sous date simulée FUTURE : jamais
        # après la vraie date (lot 13, fn_date_ecriture).
        r = self.client.post(f"/projets/{self.p1}/taches/{self.t1}/cloturer", data={"type_code": "envoi"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.sql("SELECT date_fin FROM tache WHERE id = %s", (self.t1,))[0]["date_fin"], self.auj)


class TestMigration0018(_Base):
    def test_rejouable_sans_rien_perdre(self):
        self.sql("SET LOCAL app.admin_reel_id = %s; SET LOCAL app.current_user_id = %s;"
                 "INSERT INTO notification (utilisateur_id, categorie, message) VALUES (%s, 'projet', 'x');"
                 "UPDATE projet SET nom = 'Renommé' WHERE id = %s",
                 (str(self.admin), str(self.chef), self.chef, self.p1))
        avant = self.sql("SELECT id, admin_reel_id FROM audit_log ORDER BY id")
        self.assertIn(self.admin, [a["admin_reel_id"] for a in avant])
        for _ in range(2):
            with self.db.get_cursor() as cur:
                cur.execute(MIGRATION_0018.read_text(encoding="utf-8"))
            self.rejouer_migrations_suivantes("0018_modes_admin_et_date_simulee")
        self.assertEqual(self.sql("SELECT id, admin_reel_id FROM audit_log ORDER BY id"), avant)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM pg_constraint WHERE conname = 'audit_log_action_valide'"), 1)
        self.assertEqual(self.compter("SELECT count(*) AS n FROM pg_constraint WHERE conrelid = 'audit_log'::regclass "
                                      "AND contype = 'f' AND conname LIKE '%%admin_reel%%'"), 1)

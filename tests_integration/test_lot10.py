"""Lot 10 sur vrai PostgreSQL : décisions 1 et 3 par les routes, réouverture
par l'Admin (décision 2), révocation des sessions, dernier Admin, verrou du
projet en concurrence, jokers LIKE. Ignorés sans KAIROS_TEST_DATABASE_URL."""
import datetime
import threading

from tests_integration.base import BaseIntegration

MOT_DE_PASSE = "un-mot-de-passe-solide"


class TestDecisionsParLesRoutes(BaseIntegration):
    def test_rh_ne_peut_ni_modifier_ni_desactiver_un_admin(self):
        rh, admin = self.user("rh"), self.user("admin", None)
        self.login(rh)
        self.client.post(f"/utilisateurs/{admin}", data={
            "prenom": "A", "nom": "B", "email": "a@t.tn", "role": "intervenant",
            "nouveau_mot_de_passe": "x" * 12})
        self.client.post(f"/utilisateurs/{admin}/toggle-actif", data={"actif_cible": "0"})
        u = self.sql("SELECT role, actif, mot_de_passe_hash, email FROM utilisateur WHERE id=%s", (admin,))[0]
        self.assertEqual((u["role"], u["actif"], u["mot_de_passe_hash"]), ("admin", True, "h"))
        self.assertNotEqual(u["email"], "a@t.tn")
        intermediaire = self.user("intervenant")
        self.client.post(f"/utilisateurs/{intermediaire}", data={
            "prenom": "I", "nom": "J", "email": "i@t.tn", "role": "admin"})
        self.assertEqual(self.sql("SELECT role FROM utilisateur WHERE id=%s", (intermediaire,))[0]["role"],
                         "intervenant")

    def test_admin_rouvre_le_projet_clos_d_un_autre_chef(self):
        admin, chef = self.user("admin", None), self.user("chef_de_projet")
        p = self.projet(chef, etat="termine", debut=datetime.date(2026, 1, 5))
        self.login(admin)
        self.client.post(f"/projets/{p}/informations", data={"nom": "Projet", "etat": "en_cours"})
        self.assertEqual(self.sql("SELECT etat FROM projet WHERE id=%s", (p,))[0]["etat"], "en_cours")

    def test_chef_intervenant_d_une_tache_devient_co_chef(self):
        from app.repositories import projets
        chef, autre_chef = self.user("chef_de_projet"), self.user("chef_de_projet")
        p = self.projet(chef)
        self.login(chef)
        self.client.post(f"/projets/{p}/taches", data={
            "titre": "Calcul", "type_deadline": "interne", "intervenants": [str(autre_chef)]})
        self.assertTrue(projets.user_can_manage(p, autre_chef))
        self.assertFalse(self.sql("SELECT 1 FROM projet_co_chef WHERE projet_id=%s AND utilisateur_id=%s",
                                  (p, chef)))  # jamais co-chef de son propre projet

    def test_ajout_repete_d_un_intervenant_une_seule_notification(self):
        chef, inter = self.user("chef_de_projet"), self.user("intervenant")
        p = self.projet(chef)
        self.login(chef)
        for _ in range(3):
            self.client.post(f"/projets/{p}/intervenants", data={"utilisateur_id": inter})
        self.assertEqual(self.sql("SELECT count(*) AS n FROM notification WHERE utilisateur_id=%s",
                                  (inter,))[0]["n"], 1)


class TestSessions(BaseIntegration):
    def _connecter(self, email):
        r = self.client.post("/connexion", data={"email": email, "password": MOT_DE_PASSE})
        self.assertEqual(r.status_code, 302, r.data[:300])
        return self.client.get_cookie("session").value

    def _rejouer(self, cookie):
        client = self.app.test_client()
        client.set_cookie("session", cookie)
        return client.get("/accueil")

    def _compte(self, role="chef_de_projet"):
        from app.auth import hash_password
        email = f"{role}-{datetime.datetime.now().timestamp()}@t.tn"
        uid = self.sql("INSERT INTO utilisateur (email, mot_de_passe_hash, prenom, nom, role, equipe_code) "
                       "VALUES (%s, %s, 'P', 'N', %s, 'MIDGARD') RETURNING id",
                       (email, hash_password(MOT_DE_PASSE), role))[0]["id"]
        return uid, email

    def test_cookie_copie_refuse_apres_deconnexion(self):
        _, email = self._compte()
        cookie = self._connecter(email)
        self.assertEqual(self._rejouer(cookie).status_code, 200)
        self.client.post("/deconnexion")
        r = self._rejouer(cookie)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/connexion", r.headers["Location"])

    def test_cookie_copie_refuse_apres_desactivation_puis_reactivation(self):
        from app.repositories import utilisateurs
        uid, email = self._compte("intervenant")
        cookie = self._connecter(email)
        admin = self.user("admin", None)
        utilisateurs.set_actif(uid, False, admin)
        utilisateurs.set_actif(uid, True, admin)
        self.assertEqual(self._rejouer(cookie).status_code, 302)

    def test_dernier_admin_jamais_desactive(self):
        from app.repositories import utilisateurs
        seul_admin = self.user("admin", None)
        with self.assertRaises(Exception) as ctx:
            utilisateurs.set_actif(seul_admin, False, seul_admin)
        self.assertIn("dernier Admin actif", str(ctx.exception))


class TestConcurrence(BaseIntegration):
    def test_deux_clotures_simultanees_debloquent_le_projet(self):
        """Audit données I2 : deux tâches bloquées clôturées en même temps ;
        une 3e session tient le projet pour aligner les deux transactions."""
        from app.repositories import taches
        chef = self.user("chef_de_projet")
        p = self.projet(chef)
        t1, t2 = self.tache(p, chef), self.tache(p, chef)
        taches.set_etat(t1, p, "bloque", chef, motif="Attente des plans")
        taches.set_etat(t2, p, "bloque", chef, motif="Attente des plans")
        self.assertEqual(self.sql("SELECT etat FROM projet WHERE id=%s", (p,))[0]["etat"], "bloque")

        erreurs = []

        def cloturer(t):
            try:
                taches.close_tache(t, p, chef, "information")
            except Exception as exc:  # pragma: no cover - affiché par l'assertion
                erreurs.append(exc)

        with self.db.get_cursor() as verrou:
            verrou.execute("SELECT 1 FROM projet WHERE id = %s FOR UPDATE", (p,))
            fils = [threading.Thread(target=cloturer, args=(t,)) for t in (t1, t2)]
            for f in fils:
                f.start()
            for f in fils:
                f.join(0.5)  # les deux attendent le verrou (ou ont déjà lu, sans le correctif)
        for f in fils:
            f.join(10)
        self.assertEqual(erreurs, [])
        self.assertEqual(self.sql("SELECT count(*) AS n FROM tache WHERE projet_id=%s AND etat='bloque'",
                                  (p,))[0]["n"], 0)
        self.assertEqual(self.sql("SELECT etat FROM projet WHERE id=%s", (p,))[0]["etat"], "en_cours")


class TestRecherche(BaseIntegration):
    def test_jokers_like_litteraux(self):
        from app.repositories import projets, utilisateurs
        chef = self.user("chef_de_projet")
        self.projet(chef)
        self.assertTrue(utilisateurs.search("chef"))
        self.assertEqual(utilisateurs.search("__"), [])
        self.assertEqual(utilisateurs.search("%"), [])
        self.assertEqual(projets.search(chef, "%"), [])

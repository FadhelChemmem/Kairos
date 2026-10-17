"""Lot 18 sur un vrai PostgreSQL : corrections de la revue d'experts du
17/10/2026 (sécurité, droits et visibilité, robustesse, métier) et matrice
de droits par rôle sur les cinq phases d'une affaire (APS → DOE)."""
import datetime
import io
import json
from urllib.parse import unquote

from tests_integration.base import BaseIntegration

PHASES = ("APS", "APD", "DCE", "EXE", "DOE")


def partiel(cible):
    return {"X-Kairos-Partiel": cible, "X-Requested-With": "XMLHttpRequest"}


class _Base(BaseIntegration):
    def setUp(self):
        super().setUp()
        self.chef = self.user("chef_de_projet")
        self.inter = self.user("intervenant")
        self.admin = self.user("admin")
        self.p = self.projet(self.chef)
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s)", (self.p, self.inter))
        self.t = self.tache(self.p, self.chef, intervenants=(self.inter,))

    def post_projet(self, auteur, contenu="Un post", type_code="information"):
        return self.sql("INSERT INTO post (projet_id, auteur_id, type_code, contenu) VALUES (%s, %s, %s, %s) RETURNING id",
                        (self.p, auteur, type_code, contenu))[0]["id"]


class TestPiecesJointesEtSaisies(_Base):
    def commenter(self, post_id, fichier=None, **data):
        donnees = {"contenu": "Un commentaire", **data}
        if fichier:
            donnees["fichier"] = fichier
        return self.client.post(f"/posts/{post_id}/commenter", data=donnees, headers=partiel("#x"),
                               content_type="multipart/form-data")

    def test_commentaire_refuse_une_extension_hors_liste_blanche(self):
        self.login(self.inter)
        post = self.post_projet(self.chef)
        for nom in ("facture.exe", "x.html", "a.php", "sans_extension"):
            with self.subTest(nom=nom):
                r = self.commenter(post, (io.BytesIO(b"contenu"), nom))
                self.assertEqual(r.status_code, 422)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM post_commentaire")[0]["n"], 0)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM post_commentaire_piece_jointe")[0]["n"], 0)

    def test_commentaire_accepte_un_pdf_et_refuse_un_fichier_vide(self):
        self.login(self.inter)
        post = self.post_projet(self.chef)
        self.assertEqual(self.commenter(post, (io.BytesIO(b"%PDF-1.4"), "plan.pdf")).status_code, 200)
        self.assertEqual(self.commenter(post, (io.BytesIO(b""), "vide.pdf")).status_code, 422)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM post_commentaire_piece_jointe")[0]["n"], 1)

    def test_modifier_commentaire_refuse_une_extension_interdite(self):
        self.login(self.inter)
        post = self.post_projet(self.chef)
        self.commenter(post)
        cid = self.sql("SELECT id FROM post_commentaire")[0]["id"]
        r = self.client.post(f"/posts/commentaires/{cid}/modifier",
                             data={"contenu": "Modifié", "fichier": (io.BytesIO(b"x"), "x.bat")},
                             headers=partiel("#x"), content_type="multipart/form-data")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.sql("SELECT contenu FROM post_commentaire")[0]["contenu"], "Un commentaire")

    def test_envoi_sur_une_tache_refuse_une_extension_interdite(self):
        self.login(self.chef)
        r = self.client.post(f"/fichiers/taches/{self.t}/upload",
                             data={"fichier": (io.BytesIO(b"x"), "virus.exe")}, headers=partiel("#x"),
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM tache_piece_jointe")[0]["n"], 0)

    def test_post_invisible_refuse(self):
        self.login(self.inter)
        for texte in ("​​", "  ‍", "﻿"):
            with self.subTest(texte=repr(texte)):
                r = self.client.post("/posts", data={"projet_id": self.p, "type_code": "information", "contenu": texte},
                                     headers=partiel("#x"))
                self.assertEqual(r.status_code, 422)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM post")[0]["n"], 0)

    def test_lien_avec_saut_de_ligne_neutralise(self):
        self.login(self.inter)
        self.client.post("/posts", data={"projet_id": self.p, "type_code": "information", "contenu": "Plans",
                                         "lien": "http://a\nb"}, headers=partiel("#x"))
        ligne = self.sql("SELECT lien FROM post")[0]
        self.assertIsNone(ligne["lien"])

    def test_edition_limite_cumulative_de_dix_pieces(self):
        self.login(self.inter)
        pieces = [(io.BytesIO(b"%PDF-1.4"), f"p{i}.pdf") for i in range(10)]
        r = self.client.post("/posts", data={"projet_id": self.p, "type_code": "information", "contenu": "Dossier",
                                             "fichier": pieces}, headers=partiel("#x"), content_type="multipart/form-data")
        self.assertIn(r.status_code, (200, 201, 204))
        pid = self.sql("SELECT id FROM post")[0]["id"]
        r = self.client.post(f"/posts/{pid}/modifier", data={"contenu": "Dossier", "fichier": (io.BytesIO(b"%PDF-1.4"), "de-trop.pdf")},
                             headers=partiel("#x"), content_type="multipart/form-data")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM post_piece_jointe WHERE retire_le IS NULL")[0]["n"], 10)


class TestRobustesse(_Base):
    def test_curseur_avant_forge_ne_donne_pas_500(self):
        self.login(self.chef)
        self.post_projet(self.chef)
        for valeur in ("2026-10-17_99999999999999999999999", "0001-01-01T00:00:00+23:59_1", "2026-10-17T10:00:00_-5",
                       "2026-10-17T10:00:00_0", "abc"):
            for url in ("/accueil", f"/projets/{self.p}"):
                with self.subTest(avant=valeur, url=url):
                    r = self.client.get(url, query_string={"avant": valeur})
                    self.assertEqual(r.status_code, 200)

    def test_identifiants_a_zero_ou_enormes_ignores(self):
        self.login(self.chef)
        post = self.post_projet(self.chef)
        r = self.client.post("/posts", data={"projet_id": self.p, "type_code": "requete", "objet": "Question",
                                             "contenu": "Texte", "tache_id": "0", "parent_post_id": "0"}, headers=partiel("#x"))
        self.assertIn(r.status_code, (200, 204))
        r = self.client.post("/posts", data={"projet_id": self.p, "type_code": "information", "contenu": "Texte",
                                             "parent_post_id": "99999999999999999999999"}, headers=partiel("#x"))
        self.assertLess(r.status_code, 500)
        for champ in ("parent_commentaire_id", "mentionne_user_id"):
            with self.subTest(champ=champ):
                r = self.client.post(f"/posts/{post}/commenter", data={"contenu": "Réponse", champ: "0"}, headers=partiel("#x"))
                self.assertIn(r.status_code, (200, 204))

    def test_redirection_apres_connexion_refuse_les_caracteres_de_controle(self):
        from app.utils import is_safe_next

        self.assertTrue(is_safe_next("/projets/3?tache=2"))
        for url in ("/\r\nSet-Cookie:x=1", "/a\nb", "/a\tb", "/a\\b", "//evil.com", "/\\evil.com", "https://evil.com", "/\x7f"):
            with self.subTest(url=repr(url)):
                self.assertFalse(is_safe_next(url))

    def test_set_etat_rend_letat_reellement_remplace(self):
        from app.repositories import taches

        self.sql("UPDATE tache SET etat = 'bloque', bloque_motif = 'Plans', bloque_par = %s, bloque_le = now() WHERE id = %s",
                 (self.chef, self.t))
        remplace = {}
        self.assertTrue(taches.set_etat(self.t, self.p, "en_cours", self.chef, peut_gerer=True, remplace=remplace))
        self.assertEqual(remplace["etat"], "bloque")
        self.assertEqual(remplace["bloque_motif"], "Plans")
        self.assertEqual(remplace["bloque_par"], self.chef)
        self.assertEqual(remplace["titre"], "T")

    def test_double_blocage_une_seule_notification(self):
        """Deux « Bloquer » l'un après l'autre : le second ne voit plus la
        tâche « en cours » (l'état avant est lu sous verrou)."""
        self.login(self.inter)
        url = f"/projets/{self.p}/taches/{self.t}/etat"
        for _ in range(2):
            self.client.post(url, data={"etat": "bloque", "motif": "Plans"}, headers=partiel(f"#tache-fenetre-{self.t}"))
        self.assertEqual(self.sql("SELECT count(*) AS n FROM notification WHERE utilisateur_id = %s", (self.chef,))[0]["n"], 1)

    def test_marquage_vu_a_linstant_releve_avant_la_lecture(self):
        from app.repositories import posts

        uid = self.inter
        avant = self.sql("SELECT now() - interval '1 hour' AS t")[0]["t"]
        posts.marquer_fil_vu(uid, ("echanges",), avant)
        self.assertEqual(posts.fil_vu(uid)["echanges"], avant)
        posts.marquer_fil_vu(uid, ("echanges",))
        self.assertGreater(posts.fil_vu(uid)["echanges"], avant)


class TestVisibiliteEtDroits(_Base):
    def test_tache_creee_par_moi_disparait_si_je_ne_vois_plus_le_projet(self):
        from app.repositories import tableaux, taches

        ex_chef = self.user("chef_de_projet", equipe="URBS")
        self.sql("UPDATE tache SET created_by = %s WHERE id = %s", (ex_chef, self.t))
        self.sql("UPDATE tache SET created_by = %s WHERE id = %s", (ex_chef, self.t))
        # Chef d'une autre équipe, créateur de la tâche, jamais rattaché : il ne voit pas le projet.
        self.assertEqual([t["id"] for t in tableaux.taches_de_mes_projets(ex_chef)], [])
        self.assertEqual([t["id"] for t in taches.list_mes_taches(ex_chef)], [])
        self.assertEqual([t["id"] for t in taches.list_bloquees(ex_chef)], [])
        self.sql("UPDATE tache SET etat = 'bloque', bloque_motif = 'x', bloque_le = now(), bloque_par = %s WHERE id = %s",
                 (self.chef, self.t))
        self.assertEqual([t["id"] for t in taches.list_bloquees(ex_chef)], [])
        # Le chef du projet, lui, la voit toujours.
        self.assertEqual([t["id"] for t in taches.list_bloquees(self.chef)], [self.t])

    def test_notification_sans_extrait_quand_laccès_est_perdu(self):
        from app.repositories import notifications

        autre = self.user("intervenant", equipe="URBS")
        self.sql("INSERT INTO notification (utilisateur_id, categorie, message, projet_id) VALUES (%s, 'projet', %s, %s), (%s, 'projet', %s, %s)",
                 (autre, "SECRET-CLIENT-ALPHA marge 12%", self.p, self.inter, "Visible pour moi", self.p))
        perdu = notifications.list_notifications(autre)
        self.assertEqual(len(perdu), 1)
        self.assertNotIn("SECRET", perdu[0]["message"])
        self.assertIn("plus accès", perdu[0]["message"])
        garde = notifications.list_notifications(self.inter)
        self.assertEqual(garde[0]["message"], "Visible pour moi")

    def test_tache_sans_intervenant_actif_est_signalee(self):
        from app.repositories import tableaux

        depart = self.user("intervenant", actif=True)
        t2 = self.tache(self.p, self.chef, intervenants=(depart,))
        base = tableaux.compteurs(self.chef, False, datetime.date.today(), datetime.date.today())["sans_intervenant"]
        self.sql("UPDATE utilisateur SET actif = false WHERE id = %s", (depart,))
        apres = tableaux.compteurs(self.chef, False, datetime.date.today(), datetime.date.today())["sans_intervenant"]
        self.assertEqual(apres, base + 1, t2)

    def test_admin_ne_peut_pas_rejoindre_un_projet(self):
        self.login(self.admin)
        r = self.client.post(f"/projets/{self.p}/rejoindre", headers=partiel("#x"))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM projet_intervenant WHERE utilisateur_id = %s", (self.admin,))[0]["n"], 0)

    def test_mot_de_passe_actuel_limite_les_essais(self):
        from app.auth import hash_password

        self.sql("UPDATE utilisateur SET mot_de_passe_hash = %s WHERE id = %s", (hash_password("Vrai-mot-de-passe-1"), self.inter))
        from app.auth import password_fingerprint

        with self.client.session_transaction() as s:
            s["user_id"] = self.inter
            s["pw_fingerprint"] = password_fingerprint(hash_password("Vrai-mot-de-passe-1"))
        # pw_fingerprint dépend du hash exact : on relit celui de la base.
        h = self.sql("SELECT mot_de_passe_hash AS h FROM utilisateur WHERE id = %s", (self.inter,))[0]["h"]
        with self.client.session_transaction() as s:
            s["pw_fingerprint"] = password_fingerprint(h)
        donnees = {"mot_de_passe_actuel": "faux", "nouveau_mot_de_passe": "Nouveau-mot-de-passe-2", "confirmation": "Nouveau-mot-de-passe-2"}
        for _ in range(5):
            r = self.client.post("/utilisateurs/moi/mot-de-passe", data=donnees, headers=partiel("#mot-de-passe"))
            self.assertEqual(r.status_code, 422)
        donnees["mot_de_passe_actuel"] = "Vrai-mot-de-passe-1"
        r = self.client.post("/utilisateurs/moi/mot-de-passe", data=donnees, headers=partiel("#mot-de-passe"))
        self.assertEqual(r.status_code, 422)
        self.assertIn("Trop de tentatives", unquote(r.get_data(as_text=True)))
        self.assertEqual(self.sql("SELECT mot_de_passe_hash AS h FROM utilisateur WHERE id = %s", (self.inter,))[0]["h"], h)


class TestMatriceDesRoles(BaseIntegration):
    """Matrice de droits sur les cinq phases d'une affaire de MIDGARD plus un
    projet d'une autre équipe. Fige le comportement actuel, y compris le
    périmètre du client (toute son équipe : décision du gérant à prendre)."""

    def setUp(self):
        super().setUp()
        self.admin = self.user("admin")
        self.rh = self.user("rh")
        self.chef = self.user("chef_de_projet")
        self.cochef = self.user("chef_de_projet")
        self.inter_r = self.user("intervenant")      # rattaché à toutes les phases
        self.inter_t = self.user("intervenant")      # sur une tâche seulement
        self.inter_m = self.user("intervenant")      # même équipe, non rattaché
        self.inter_u = self.user("intervenant", equipe="URBS")
        self.client_m = self.user("client")
        self.client_u = self.user("client", equipe="URBS")
        self.desactive = self.user("intervenant", actif=False)
        self.projets = {}
        precedent = None
        for i, phase in enumerate(PHASES):
            pid = self.sql(
                "INSERT INTO projet (code, nom, phase, chef_projet_id, equipe_code, etat, phase_liee_id) "
                "VALUES (%s, %s, %s, %s, 'MIDGARD', 'en_cours', %s) RETURNING id",
                (f"26{i + 1:03d}X", f"Affaire {phase}", phase, self.chef, precedent))[0]["id"]
            self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s)", (pid, self.cochef))
            self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s, %s)", (pid, self.inter_r))
            tid = self.tache(pid, self.chef, intervenants=(self.inter_t,))
            self.projets[phase] = (pid, tid)
            precedent = pid
        self.autre_chef = self.user("chef_de_projet", equipe="URBS")
        self.autre_projet = self.projet(self.autre_chef, equipe="URBS", code="26900X")

    def statut(self, qui, url, methode="get", **kw):
        self.client = self.app.test_client()
        self.login(qui)
        return getattr(self.client, methode)(url, **kw).status_code

    def test_lecture_de_la_fiche_projet_par_role_et_par_phase(self):
        attendu = {
            "admin": 200, "chef": 200, "cochef": 200, "inter_r": 200, "inter_t": 200, "inter_m": 200,
            "client_m": 200,   # périmètre actuel du client : toute son équipe
            "rh": 404, "inter_u": 404, "client_u": 404,
        }
        for phase, (pid, _) in self.projets.items():
            for role, code in attendu.items():
                with self.subTest(phase=phase, role=role):
                    self.assertEqual(self.statut(getattr(self, role), f"/projets/{pid}"), code)
        for role in ("chef", "cochef", "inter_r", "inter_m", "client_m", "rh"):
            with self.subTest(autre_equipe=role):
                self.assertEqual(self.statut(getattr(self, role), f"/projets/{self.autre_projet}"), 404)
        self.assertEqual(self.statut(self.admin, f"/projets/{self.autre_projet}"), 200)
        self.assertEqual(self.statut(self.desactive, f"/projets/{self.projets['EXE'][0]}"), 302)

    def test_ecriture_creer_une_tache_par_role(self):
        pid, _ = self.projets["EXE"]
        permis = {"admin": True, "chef": True, "cochef": True, "inter_r": False, "inter_t": False, "inter_m": False,
                  "client_m": False, "rh": False, "inter_u": False, "client_u": False}
        for role, ok in permis.items():
            with self.subTest(role=role):
                avant = self.sql("SELECT count(*) AS n FROM tache WHERE projet_id = %s", (pid,))[0]["n"]
                self.statut(getattr(self, role), f"/projets/{pid}/taches", "post",
                            data={"titre": f"Tâche de {role}", "type_deadline": "interne"}, headers=partiel("#x"))
                apres = self.sql("SELECT count(*) AS n FROM tache WHERE projet_id = %s", (pid,))[0]["n"]
                self.assertEqual(apres - avant, 1 if ok else 0)

    def test_etats_reserves_a_la_gestion(self):
        for phase, (pid, tid) in self.projets.items():
            for role, ok in (("inter_t", False), ("chef", True), ("cochef", True), ("admin", True)):
                with self.subTest(phase=phase, role=role):
                    self.sql("UPDATE tache SET etat = 'en_cours' WHERE id = %s", (tid,))
                    self.statut(getattr(self, role), f"/projets/{pid}/taches/{tid}/etat", "post",
                                data={"etat": "abandonne"}, headers=partiel("#x"))
                    etat = self.sql("SELECT etat FROM tache WHERE id = %s", (tid,))[0]["etat"]
                    self.assertEqual(etat == "abandonne", ok)

    def test_un_client_ne_cree_ni_tache_ni_projet_et_ne_voit_pas_le_daily_log(self):
        pid, tid = self.projets["APS"]
        self.assertIn(self.statut(self.client_m, "/projets/nouveau"), (302, 403))
        for url in ("/dailylog", "/dailylog/equipe", "/utilisateurs", "/deadlines"):
            with self.subTest(url=url):
                self.assertIn(self.statut(self.client_m, url), (302, 403, 404))
        self.assertEqual(self.statut(self.client_m, f"/projets/{pid}/taches/{tid}/etat", "post",
                                     data={"etat": "bloque", "motif": "x"}, headers=partiel("#x")), 403)
        self.assertEqual(self.sql("SELECT etat FROM tache WHERE id = %s", (tid,))[0]["etat"], "en_cours")

    def test_rh_sans_aucun_projet_ni_daily_log(self):
        pid, _ = self.projets["EXE"]
        for url in (f"/projets/{pid}", "/dailylog/equipe", "/deadlines"):
            with self.subTest(url=url):
                self.assertIn(self.statut(self.rh, url), (302, 403, 404))
        self.assertEqual(self.statut(self.rh, "/utilisateurs"), 200)

    def test_cycle_de_vie_dune_affaire_sur_cinq_phases(self):
        """Clôturer APS puis passer à APD : les tâches closes disparaissent des
        listes ouvertes, la phase suivante reste visible par toute l'équipe."""
        aps, taps = self.projets["APS"]
        apd, tapd = self.projets["APD"]
        self.login(self.chef)
        r = self.client.post(f"/projets/{aps}/taches/{taps}/cloturer", data={"type_code": "envoi"}, headers=partiel("#x"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.sql("SELECT etat FROM tache WHERE id = %s", (taps,))[0]["etat"], "termine")
        self.assertEqual(self.sql("SELECT etat FROM tache WHERE id = %s", (tapd,))[0]["etat"], "en_cours")
        self.assertEqual(self.sql("SELECT phase_liee_id FROM projet WHERE id = %s", (apd,))[0]["phase_liee_id"], aps)
        for role in ("inter_r", "inter_t", "client_m"):
            with self.subTest(role=role):
                self.assertEqual(self.statut(getattr(self, role), f"/projets/{apd}"), 200)

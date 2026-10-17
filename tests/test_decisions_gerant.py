"""Décisions du gérant intégrées à la fin du lot 10 :

- décision 2 : le Client VOIT les heures, les honoraires, les pièces
  jointes et le Daily log (en lecture, sur le profil) des projets qu'il
  peut voir — tests qui figent la décision ;
- décision 3 : Vérifiée, Arrêtée et Abandonnée sont réservées au chef de
  projet titulaire, aux co-chefs et à l'Admin, dans les deux sens ;
- décision 5 : X-Forwarded-* crus seulement depuis TRUSTED_PROXY_IPS ;
- décision 6 : MAIL_DESTINATAIRES_AUTORISES (mode test des e-mails).

Même principe que tests/test_smoke.py (psycopg2 simulé, repositories
remplacés par des mocks). Le trigger de la migration 0015 est vérifié sur
un vrai PostgreSQL par tests/sql/etats_taches_reserves.sql et
tests_integration/test_decisions_gerant.py.
"""
import datetime
import io
import pathlib
import unittest
from unittest.mock import MagicMock, patch

try:  # python -m unittest discover -s tests
    import test_smoke as smoke
except ImportError:  # python -m unittest tests.test_decisions_gerant
    from tests import test_smoke as smoke

RACINE = pathlib.Path(__file__).resolve().parent.parent

CLIENT = {**smoke.USER, "id": 1, "role": "client"}
INTERVENANT = {**smoke.USER, "id": 1, "role": "intervenant"}
CHEF = {**smoke.USER, "id": 1, "role": "chef_de_projet"}


class _Base(smoke.SmokeBase):
    def _requete(self, methode, chemin, data=None, espions=(), suivre=False, **overrides):
        """Requête avec les mocks par défaut de test_smoke (+ overrides) et
        des espions (cible -> valeur de retour ou exception) ; renvoie
        (réponse, espions)."""
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        mocks = {}
        try:
            for cible, valeur in espions:
                if isinstance(valeur, Exception):
                    pp = patch(cible, side_effect=valeur)
                else:
                    pp = patch(cible, return_value=valeur)
                mocks[cible] = pp.start()
                patchers.append(pp)
            resp = getattr(self.client, methode)(chemin, data=data or {}, follow_redirects=suivre)
        finally:
            for p in reversed(patchers):
                p.stop()
        return resp, mocks

    def _flashes(self):
        with self.client.session_transaction() as sess:
            return [message for _, message in sess.get("_flashes", [])]


# ---------------------------------------------------------------------------
# Décision 2 : ce que voit un Client
# ---------------------------------------------------------------------------
class TestDecision2ClientVoitHeuresHonorairesPiecesJointes(_Base):
    def test_fiche_projet_heures_honoraires_et_pieces_jointes(self):
        resp, _ = self._requete("get", "/projets/1", **{
            "app.auth.get_user_by_id": CLIENT,
            "app.repositories.projets.user_can_manage": False,
            "app.repositories.projets.get_projet": {**smoke.PROJET, "honoraires": 12500, "client": "IPCO"},
        })
        self.assertEqual(resp.status_code, 200)
        page = resp.data.decode()
        self.assertIn("Honoraires", page)
        self.assertIn("12", page)  # montant affiché (format français)
        self.assertNotIn("Honoraires</span><span style=\"font-weight:600;\">—", page)
        self.assertIn("Heures intervenants", page)
        self.assertIn("Heures chef de projet", page)
        self.assertIn("302", page)  # heures intervenants du projet
        # Pièce jointe d'une tâche : dans sa fenêtre, chargée à la demande (lot 11).
        resp, _ = self._requete("get", "/projets/1/taches/5/fenetre", **{
            "app.auth.get_user_by_id": CLIENT,
            "app.repositories.projets.user_can_manage": False,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('href="/fichiers/taches/1"', resp.data.decode())

    def test_telechargement_piece_jointe_tache_et_post(self):
        for chemin_fichier, url in ((smoke.PIECE_JOINTE_TACHE["chemin"], "/fichiers/taches/1"),
                                    (smoke.PIECE_JOINTE_POST["chemin"], "/fichiers/posts/1")):
            with self.subTest(url=url):
                chemin = pathlib.Path(self.app.config["UPLOAD_DIR"]) / chemin_fichier
                chemin.parent.mkdir(parents=True, exist_ok=True)
                chemin.write_bytes(b"%PDF-1.4 client")
                self.addCleanup(chemin.unlink)
                resp, _ = self._requete("get", url, **{"app.auth.get_user_by_id": CLIENT})
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.data, b"%PDF-1.4 client")
                resp.close()

    def test_export_excel_avec_heures_et_honoraires(self):
        import openpyxl
        ligne = {
            "id": 1, "code": "26099X", "nom": "Tour Meridian", "phase": "EXE", "etat": "en_cours",
            "date_debut": datetime.date(2026, 1, 5), "client": "IPCO", "honoraires": 12500,
            "chef_prenom": "Foulen", "chef_nom": "Chedly", "lots": "CM · GO",
            "heures_chef": 5.0, "heures_intervenant": 8.0,
            "prochain_rendu": None, "prochain_rendu_titre": None,
            "prochaine_deadline": None, "prochaine_deadline_titre": None,
        }
        resp, _ = self._requete("get", "/projets/export.xlsx", **{
            "app.auth.get_user_by_id": CLIENT,
            "app.repositories.projets.list_projets": [ligne],
        })
        self.assertEqual(resp.status_code, 200)
        lignes = list(openpyxl.load_workbook(io.BytesIO(resp.data)).active.iter_rows(values_only=True))
        entetes = lignes[0]
        self.assertEqual(lignes[1][entetes.index("Honoraires")], 12500)
        self.assertEqual(lignes[1][entetes.index("Heures intervenants")], 8.0)
        self.assertEqual(lignes[1][entetes.index("Heures chef de projet")], 5.0)

    def _profil(self, visiteur):
        return self._requete(
            "get", "/utilisateurs/5/profil",
            espions=[("app.repositories.dailylog.list_entrees_periode", [])],
            **{"app.auth.get_user_by_id": visiteur,
               "app.repositories.utilisateurs.get_utilisateur": {**smoke.AUTRE_UTILISATEUR, "id": 5}})

    def test_profil_d_une_personne_daily_log_en_lecture(self):
        resp, m = self._profil(CLIENT)
        self.assertEqual(resp.status_code, 200)
        m["app.repositories.dailylog.list_entrees_periode"].assert_called()
        page = resp.data.decode()
        self.assertIn('id="dailylog"', page)
        self.assertNotIn(">Corriger</a>", page)  # lecture seule

    def test_intervenant_toujours_sans_le_daily_log_de_ses_collegues(self):
        resp, m = self._profil(INTERVENANT)
        self.assertEqual(resp.status_code, 200)
        m["app.repositories.dailylog.list_entrees_periode"].assert_not_called()
        self.assertNotIn('id="dailylog"', resp.data.decode())

    def test_la_regle_du_profil_nomme_le_client(self):
        """Garde-fou de relecture : la décision est écrite dans le code."""
        from app.routes import utilisateurs
        import inspect
        source = inspect.getsource(utilisateurs.profil_personne)
        self.assertIn('("admin", "chef_de_projet", "client")', source)


# ---------------------------------------------------------------------------
# Décision 3 : états de tâche réservés au chef, aux co-chefs et à l'Admin
# ---------------------------------------------------------------------------
class TestDecision3EtatsReserves(_Base):
    INTERVENANT_DE_LA_TACHE = {
        "app.auth.get_user_by_id": INTERVENANT,
        "app.repositories.projets.user_can_manage": False,
        "app.repositories.taches.user_est_intervenant": True,
    }

    def test_intervenant_ne_passe_pas_en_etat_reserve(self):
        for etat in ("verifie", "arret", "abandonne"):
            with self.subTest(etat=etat):
                resp, m = self._requete("post", "/projets/1/taches/5/etat", {"etat": etat},
                                        espions=[("app.repositories.taches.set_etat", True)],
                                        **self.INTERVENANT_DE_LA_TACHE)
                self.assertEqual(resp.status_code, 302)
                m["app.repositories.taches.set_etat"].assert_not_called()
                self.assertTrue(any("Seuls le chef de projet, un co-chef ou un Admin" in f
                                    for f in self._flashes()))

    def test_intervenant_garde_en_cours_et_bloquee(self):
        for etat in ("en_cours", "bloque"):
            with self.subTest(etat=etat):
                # Lot 14 (P0-1) : « Bloquée » avec son motif.
                donnees = {"etat": etat, **({"motif": "Attente des plans"} if etat == "bloque" else {})}
                _, m = self._requete("post", "/projets/1/taches/5/etat", donnees,
                                     espions=[("app.repositories.taches.set_etat", True)],
                                     **self.INTERVENANT_DE_LA_TACHE)
                attendu = {"motif": "Attente des plans"} if etat == "bloque" else {}
                m["app.repositories.taches.set_etat"].assert_called_once_with(5, 1, etat, 1, peut_gerer=False, annulation=False,
                                                                             **attendu)

    def test_intervenant_ne_rouvre_pas_une_tache_reservee(self):
        """La tâche est Vérifiée (lu sous verrou par set_etat) : refus propre."""
        from app.repositories.taches import EtatReserve
        resp, _ = self._requete("post", "/projets/1/taches/5/etat", {"etat": "en_cours"},
                                espions=[("app.repositories.taches.set_etat", EtatReserve("x"))],
                                **self.INTERVENANT_DE_LA_TACHE)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(any("Seuls le chef de projet" in f for f in self._flashes()))

    def test_intervenant_ne_cloture_pas_une_tache_arretee(self):
        from app.repositories.taches import EtatReserve
        resp, m = self._requete("post", "/projets/1/taches/5/cloturer", {"type_code": "envoi"},
                                espions=[("app.repositories.taches.close_tache", EtatReserve("x"))],
                                **self.INTERVENANT_DE_LA_TACHE)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(m["app.repositories.taches.close_tache"].call_args.kwargs, {"peut_gerer": False})
        self.assertTrue(any("Seuls le chef de projet" in f for f in self._flashes()))

    def test_refus_du_trigger_en_base_message_clair(self):
        """Dernier rempart (migration 0015) : erreur Postgres reconnue par
        le nom de sa contrainte, jamais une erreur 500."""
        erreur = Exception("refus")
        erreur.diag = MagicMock(constraint_name="tache_etat_reserve")
        resp, _ = self._requete("post", "/projets/1/taches/5/etat", {"etat": "bloque", "motif": "Plans"},
                                espions=[("app.repositories.taches.set_etat", erreur)],
                                **self.INTERVENANT_DE_LA_TACHE)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(any("Seuls le chef de projet" in f for f in self._flashes()))

    def test_chef_co_chef_admin_passent_partout(self):
        for role in ("chef_de_projet", "admin"):
            for etat in ("verifie", "arret", "abandonne", "en_cours"):
                with self.subTest(role=role, etat=etat):
                    _, m = self._requete("post", "/projets/1/taches/5/etat", {"etat": etat},
                                         espions=[("app.repositories.taches.set_etat", True)],
                                         **{"app.auth.get_user_by_id": {**smoke.USER, "role": role},
                                            "app.repositories.projets.user_can_manage": True})
                    m["app.repositories.taches.set_etat"].assert_called_once_with(5, 1, etat, 1, peut_gerer=True, annulation=False)
        _, m = self._requete("post", "/projets/1/taches/5/cloturer", {"type_code": "envoi"},
                             espions=[("app.repositories.taches.close_tache", 100)])
        self.assertEqual(m["app.repositories.taches.close_tache"].call_args.kwargs, {"peut_gerer": True})

    # --- repository : contrôle sur l'état lu sous verrou ---
    def _curseur(self, fetchone):
        p = patch("app.db.get_cursor")
        m = p.start()
        self.addCleanup(p.stop)
        cur = m.return_value.__enter__.return_value
        cur.fetchone.side_effect = fetchone
        return cur

    def _updates(self, cur):
        return [c for c in cur.execute.call_args_list if c.args[0].lstrip().startswith(("UPDATE tache", "WITH avant"))]

    def test_repository_refuse_sans_rien_ecrire(self):
        from app.repositories import taches
        for avant, apres in (("verifie", "en_cours"), ("arret", "bloque"), ("abandonne", "en_cours"),
                             ("en_cours", "verifie"), ("bloque", "arret")):
            with self.subTest(avant=avant, apres=apres):
                cur = self._curseur([{"etat": avant}])
                with self.assertRaises(taches.EtatReserve):
                    taches.set_etat(5, 1, apres, 1)
                self.assertEqual(self._updates(cur), [])

    def test_repository_autorise_le_gestionnaire_et_les_etats_libres(self):
        from app.repositories import taches
        cur = self._curseur([{"etat": "verifie"}, None])
        self.assertTrue(taches.set_etat(5, 1, "en_cours", 1, peut_gerer=True))
        self.assertEqual(len(self._updates(cur)), 1)
        cur = self._curseur([{"etat": "bloque"}, None, None])
        self.assertTrue(taches.set_etat(5, 1, "en_cours", 1))
        self.assertEqual(len(self._updates(cur)), 1)

    def test_cloture_refusee_sur_tache_arretee_pour_un_intervenant(self):
        from app.repositories import taches
        cur = self._curseur([None, {"etat": "arret"}])
        with self.assertRaises(taches.EtatReserve):
            taches.close_tache(5, 1, 1, "envoi")
        update = self._updates(cur)[0]
        self.assertEqual(update.args[1][4:], (False, ["arret", "abandonne"]))
        # Déjà terminée : simple « rien à clôturer », pas un refus d'état réservé.
        self._curseur([None, {"etat": "termine"}])
        self.assertIsNone(taches.close_tache(5, 1, 1, "envoi"))

    # --- interface : seuls les états autorisés sont proposés ---
    def _page(self, utilisateur, gere, etat_tache):
        # Lot 11 : le contenu de la fenêtre de tâche est un fragment chargé
        # à la demande (taches_fenetre.fenetre).
        tache = {**smoke.TACHES_PROJET[0], "etat": etat_tache}
        resp, _ = self._requete("get", "/projets/1/taches/5/fenetre", **{
            "app.auth.get_user_by_id": utilisateur,
            "app.repositories.projets.user_can_manage": gere,
            "app.repositories.taches.list_taches_projet": [tache],
        })
        self.assertEqual(resp.status_code, 200)
        return resp.data.decode()

    # Lot 13 (phase 2) : liste de choix sans « Appliquer » — un bouton par
    # état proposé (name="etat" value="…").
    @staticmethod
    def _choix(etat):
        return f'name="etat" value="{etat}"'

    def test_intervenant_ne_voit_que_en_cours_et_bloquee(self):
        dialogue = self._page(INTERVENANT, False, "bloque")
        self.assertIn(self._choix("en_cours"), dialogue)
        self.assertIn(self._choix("bloque"), dialogue)
        for etat in ("verifie", "arret", "abandonne"):
            self.assertNotIn(self._choix(etat), dialogue)
        self.assertIn("Terminer et publier", dialogue)

    def test_intervenant_sur_tache_terminee_peut_rouvrir_mais_pas_verifier(self):
        dialogue = self._page(INTERVENANT, False, "termine")
        self.assertIn(">Rouvrir</button>", dialogue)
        self.assertNotIn(self._choix("verifie"), dialogue)

    def test_intervenant_sur_tache_reservee_aucune_action_d_etat(self):
        for etat in ("verifie", "arret", "abandonne"):
            with self.subTest(etat=etat):
                dialogue = self._page(INTERVENANT, False, etat)
                self.assertNotIn("/taches/5/etat", dialogue)
                self.assertNotIn("/taches/5/cloturer", dialogue)
                self.assertIn("seuls le chef de projet, un co-chef ou un admin", dialogue.lower())

    def test_chef_voit_tous_les_etats(self):
        dialogue = self._page(CHEF, True, "bloque")
        for etat in ("en_cours", "bloque", "verifie", "arret", "abandonne"):
            self.assertIn(self._choix(etat), dialogue)
        self.assertRegex(self._page(CHEF, True, "termine"), self._choix("verifie") + r'[^>]*>Vérifiée</button>')
        self.assertIn(">Rouvrir</button>", self._page(CHEF, True, "verifie"))
        self.assertIn("Terminer et publier", self._page(CHEF, True, "arret"))


class TestDecisions1Et4Inchangees(_Base):
    """Décisions 1 et 4 : rien à changer, seulement vérifié."""

    def test_chef_qui_rejoint_devient_co_chef_sans_validation(self):
        _, m = self._requete("post", "/projets/1/rejoindre",
                             espions=[("app.repositories.projets.add_co_chef", None), ("app.repositories.notifications.creer", None),
                                      ("app.repositories.projets.add_intervenant", True)],
                             **{"app.auth.get_user_by_id": {**CHEF, "id": 1},
                                "app.repositories.projets.get_projet": {**smoke.PROJET, "chef_projet_id": 9}})
        m["app.repositories.projets.add_co_chef"].assert_called_once_with(1, 1, 1)
        m["app.repositories.projets.add_intervenant"].assert_not_called()

    def test_liste_utilisateurs_visible_pour_le_chef(self):
        resp, _ = self._requete("get", "/utilisateurs", **{"app.auth.get_user_by_id": CHEF})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('href="/utilisateurs"', resp.data.decode())


# ---------------------------------------------------------------------------
# Décision 5 : X-Forwarded-* crus seulement depuis TRUSTED_PROXY_IPS
# ---------------------------------------------------------------------------
class TestDecision5ProxyDeConfiance(unittest.TestCase):
    def _app(self, proxys=1, ips="", bind="0.0.0.0", hote=""):
        from flask import request
        from app import create_app

        class C(smoke.TestConfig):
            TRUSTED_PROXY_COUNT = proxys
            TRUSTED_PROXY_IPS = ips
            WEB_BIND = bind
            HOST_IP = hote
        app = create_app(C)

        @app.route("/_vu")
        def _vu():
            return f"{request.remote_addr}|{request.scheme}|{request.headers.get('X-Forwarded-For', '-')}"
        return app

    def _vu(self, app, adresse, xff="203.0.113.9", proto="https"):
        resp = app.test_client().get("/_vu", environ_base={"REMOTE_ADDR": adresse},
                                     headers={"X-Forwarded-For": xff, "X-Forwarded-Proto": proto})
        return resp.data.decode()

    def test_en_tete_accepte_depuis_une_ip_de_confiance(self):
        app = self._app(ips="172.16.0.0/12")
        self.assertEqual(self._vu(app, "172.18.0.5"), "203.0.113.9|https|203.0.113.9")

    def test_en_tete_ignore_depuis_le_lan_avec_avertissement_une_fois(self):
        app = self._app(ips="172.16.0.0/12")
        with self.assertLogs("app.proxy", "WARNING") as journal:
            self.assertEqual(self._vu(app, "192.168.100.50"), "192.168.100.50|http|-")
            self.assertEqual(self._vu(app, "192.168.100.50", xff="198.51.100.7"), "192.168.100.50|http|-")
            self._vu(app, "192.168.100.51")
        self.assertEqual(len(journal.records), 2)  # une fois par adresse
        self.assertIn("192.168.100.50", journal.output[0])
        self.assertIn("TRUSTED_PROXY_IPS", journal.output[0])

    def test_sans_en_tete_aucun_avertissement(self):
        app = self._app(ips="172.16.0.0/12")
        with patch("app.proxy.logger") as journal:
            resp = app.test_client().get("/_vu", environ_base={"REMOTE_ADDR": "192.168.100.50"})
        self.assertEqual(resp.data.decode(), "192.168.100.50|http|-")
        journal.warning.assert_not_called()

    def test_cidr_ip_seule_et_espaces(self):
        app = self._app(ips=" 192.0.2.17 , 10.0.0.0/8,")
        self.assertTrue(self._vu(app, "10.200.3.4").startswith("203.0.113.9|"))
        self.assertTrue(self._vu(app, "192.0.2.17").startswith("203.0.113.9|"))
        with self.assertLogs("app.proxy", "WARNING"):
            self.assertTrue(self._vu(app, "192.168.100.18").startswith("192.168.100.18|"))
            self.assertTrue(self._vu(app, "172.18.0.5").startswith("172.18.0.5|"))  # pas dans la liste

    def test_liste_vide_defaut_sur_avec_avertissement_au_demarrage(self):
        with self.assertLogs("app.proxy", "WARNING") as journal:
            app = self._app(ips="", bind="0.0.0.0")
        self.assertIn("TRUSTED_PROXY_IPS vide", journal.output[0])
        self.assertIn("172.16.0.0/12", journal.output[0])
        for adresse in ("172.17.0.1", "172.31.255.254", "127.0.0.1"):
            with self.subTest(adresse=adresse):
                self.assertTrue(self._vu(app, adresse).startswith("203.0.113.9|"))
        with self.assertLogs("app.proxy", "WARNING"):
            for adresse in ("192.168.100.50", "192.0.2.17", "172.32.0.1", "10.0.0.5"):
                self.assertTrue(self._vu(app, adresse).startswith(adresse + "|"))

    def test_liste_vide_avec_ip_de_l_hote(self):
        with self.assertLogs("app.proxy", "WARNING") as journal:
            app = self._app(ips="", hote="192.0.2.17")
        self.assertIn("192.0.2.17", journal.output[0])
        self.assertTrue(self._vu(app, "192.0.2.17").startswith("203.0.113.9|"))
        with self.assertLogs("app.proxy", "WARNING"):
            self.assertTrue(self._vu(app, "192.168.100.50").startswith("192.168.100.50|"))

    def test_web_bind_local_meme_defaut_sans_avertissement(self):
        with patch("app.proxy.logger") as journal:
            app = self._app(ips="", bind="127.0.0.1")
        journal.warning.assert_not_called()
        self.assertTrue(self._vu(app, "172.17.0.1").startswith("203.0.113.9|"))

    def test_entree_invalide_ignoree_et_signalee(self):
        with self.assertLogs("app.proxy", "ERROR") as journal:
            app = self._app(ips="npm.local, 172.16.0.0/12")
        self.assertIn("npm.local", journal.output[0])
        self.assertTrue(self._vu(app, "172.20.0.3").startswith("203.0.113.9|"))

    def test_ipv4_vue_en_ipv6(self):
        from app.proxy import ProxyDeConfiance, analyser_reseaux
        reseaux, _ = analyser_reseaux("172.16.0.0/12")
        mw = ProxyDeConfiance(lambda e, s: [], 1, reseaux)
        self.assertTrue(mw.est_de_confiance("::ffff:172.18.0.2"))
        self.assertFalse(mw.est_de_confiance("::ffff:192.168.100.50"))
        self.assertFalse(mw.est_de_confiance("pas-une-ip"))

    def test_sans_proxy_en_tetes_jamais_crus(self):
        app = self._app(proxys=0, ips="172.16.0.0/12")
        self.assertTrue(self._vu(app, "172.18.0.5").startswith("172.18.0.5|http|"))

    def _connexion(self, app, adresse):
        client = app.test_client()
        with patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
                patch("app.repositories.securite.enregistrer_tentative") as enregistrer, \
                patch("app.auth.get_user_by_email", return_value=None):
            client.post("/connexion", data={"email": "x@t.tn", "password": "faux"},
                        environ_base={"REMOTE_ADDR": adresse},
                        headers={"X-Forwarded-For": "203.0.113.9"})
        return [c.args for c in enregistrer.call_args_list]

    def test_limiteur_ip_reelle_si_confiance_ip_tcp_sinon(self):
        app = self._app(ips="172.16.0.0/12")
        self.assertIn(("connexion_ip", "203.0.113.9"), self._connexion(app, "172.18.0.5"))
        with self.assertLogs("app.proxy", "WARNING"):
            appels = self._connexion(app, "192.168.100.50")
        self.assertIn(("connexion_ip", "192.168.100.50"), appels)
        self.assertIn(("connexion", "x@t.tn|192.168.100.50"), appels)

    def test_docker_compose_et_env_example(self):
        compose = (RACINE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("TRUSTED_PROXY_IPS: ${TRUSTED_PROXY_IPS:-}", compose)
        self.assertIn("HOST_IP: ${HOST_IP:-}", compose)
        exemple = (RACINE / ".env.example").read_text(encoding="utf-8")
        self.assertIn("\nTRUSTED_PROXY_IPS=", exemple)


# ---------------------------------------------------------------------------
# Décision 6 : mode test des e-mails (MAIL_DESTINATAIRES_AUTORISES)
# ---------------------------------------------------------------------------
LISTE_TEST = "Gerant@exemple.tn, @midgardengineering.com"
CIBLE_HORS_LISTE = {**smoke.AUTRE_UTILISATEUR, "id": 10, "email": "w.testeur@midgard.tn"}
CIBLE_DANS_LISTE = {**CIBLE_HORS_LISTE, "email": "Kairos@MidgardEngineering.com"}
RH = {**smoke.USER, "id": 7, "role": "rh"}


class TestDecision6MailerModeTest(unittest.TestCase):
    def setUp(self):
        from app import create_app
        self.app = create_app(smoke.TestConfig)
        self.app.config.update(SMTP_HOST="smtp.exemple.tn", SMTP_USE_TLS=False)

    def _envoyer(self, liste, destinataire, corps="Lien secret : /reinitialiser/JETON123"):
        from app import mailer
        self.app.config["MAIL_DESTINATAIRES_AUTORISES"] = liste
        with self.app.app_context(), patch("smtplib.SMTP") as smtp:
            ok = mailer.envoyer(destinataire, "Kairos — sujet", corps)
        return ok, smtp

    def test_liste_vide_ou_absente_comportement_normal(self):
        for liste in ("", "  ", None):
            with self.subTest(liste=liste):
                ok, smtp = self._envoyer(liste, "n.importe@qui.tn")
                self.assertTrue(ok)
                smtp.assert_called_once()

    def test_adresse_et_domaine_autorises_casse_ignoree(self):
        for adresse in ("gerant@EXEMPLE.tn", " Gerant@exemple.tn ",
                        "kairos@midgardengineering.com", "Autre@MIDGARDENGINEERING.COM"):
            with self.subTest(adresse=adresse):
                ok, smtp = self._envoyer(LISTE_TEST, adresse)
                self.assertTrue(ok)
                smtp.assert_called_once()

    def test_hors_liste_rien_ne_part_journal_sans_contenu_adresse_masquee(self):
        for adresse in ("w.testeur@midgard.tn", "gerant@exemple.tn.pirate.tn",
                        "x@sous.midgardengineering.com", "gerant@exemple.t", "pas-une-adresse"):
            with self.subTest(adresse=adresse):
                with self.assertLogs("app.mailer", "WARNING") as journal:
                    ok, smtp = self._envoyer(LISTE_TEST, adresse)
                self.assertFalse(ok)
                smtp.assert_not_called()
                ligne = "\n".join(journal.output)
                self.assertIn("NON envoyé", ligne)
                self.assertNotIn("JETON123", ligne)
                self.assertNotIn(adresse, ligne)

    def test_masquage(self):
        from app.mailer import masquer
        self.assertEqual(masquer("w.testeur@midgard.tn"), "w.***@midgard.tn")
        self.assertEqual(masquer("a@b.tn"), "a***@b.tn")

    def test_liste_sans_entree_valide_rien_n_est_autorise(self):
        with self.assertLogs("app.mailer", "ERROR"):
            ok, smtp = self._envoyer("gmail.com, @", "a@gmail.com")
        self.assertFalse(ok)
        smtp.assert_not_called()

    def test_arriere_plan_filtre_aussi(self):
        from app import mailer
        self.app.config["MAIL_DESTINATAIRES_AUTORISES"] = LISTE_TEST
        with self.app.app_context(), patch("smtplib.SMTP") as smtp, self.assertLogs("app.mailer", "WARNING"):
            mailer.envoyer_en_arriere_plan("w.testeur@midgard.tn", "s", "c")
        smtp.assert_not_called()

    def test_avertissement_au_demarrage(self):
        from app import create_app

        class C(smoke.TestConfig):
            MAIL_DESTINATAIRES_AUTORISES = LISTE_TEST
        with self.assertLogs("app.mailer", "WARNING") as journal:
            create_app(C)
        self.assertIn("gerant@exemple.tn", journal.output[0])
        self.assertIn("@midgardengineering.com", journal.output[0])

    def test_seul_mailer_envoie(self):
        """Tous les chemins d'envoi passent par mailer.envoyer (contrôle
        unique) : aucun autre fichier n'utilise smtplib."""
        fichiers = [f for f in (RACINE / "app").rglob("*.py") if "smtplib" in f.read_text(encoding="utf-8")]
        fichiers += [f for f in (RACINE / "scripts").rglob("*.py") if "smtplib" in f.read_text(encoding="utf-8")]
        self.assertEqual([f.relative_to(RACINE).as_posix() for f in fichiers], ["app/mailer.py"])

    def test_docker_compose_et_env_example(self):
        self.assertIn("MAIL_DESTINATAIRES_AUTORISES: ${MAIL_DESTINATAIRES_AUTORISES:-}",
                      (RACINE / "docker-compose.yml").read_text(encoding="utf-8"))
        self.assertIn("\nMAIL_DESTINATAIRES_AUTORISES=\n", (RACINE / ".env.example").read_text(encoding="utf-8"))


class TestDecision6Interface(_Base):
    LIEN = "/utilisateurs/10/envoyer-lien"
    JETON = "app.repositories.utilisateurs.set_reset_token"
    SMTP = "smtplib.SMTP"

    def setUp(self):
        super().setUp()
        self.app.config.update(SMTP_HOST="smtp.exemple.tn", SMTP_USE_TLS=False,
                               MAIL_DESTINATAIRES_AUTORISES=LISTE_TEST,
                               APP_BASE_URL="https://kairos.exemple.tn")

    def test_rh_lien_hors_liste_pas_de_faux_succes_ni_jeton(self):
        with self.assertLogs("app", "WARNING"):
            resp, m = self._requete("post", self.LIEN, espions=[(self.JETON, None), (self.SMTP, None)],
                                    **{"app.auth.get_user_by_id": RH,
                                       "app.repositories.utilisateurs.get_utilisateur": CIBLE_HORS_LISTE})
        self.assertEqual(resp.status_code, 302)
        m[self.JETON].assert_not_called()
        m[self.SMTP].assert_not_called()
        flashes = self._flashes()
        self.assertTrue(any("n’a pas pu être envoyé" in f and "mode test" in f
                            and "MAIL_DESTINATAIRES_AUTORISES" in f for f in flashes), flashes)
        self.assertFalse(any("Lien de réinitialisation envoyé" in f for f in flashes), flashes)

    def test_rh_lien_dans_la_liste_part(self):
        resp, m = self._requete("post", self.LIEN, espions=[(self.JETON, None), (self.SMTP, MagicMock())],
                                **{"app.auth.get_user_by_id": RH,
                                   "app.repositories.utilisateurs.get_utilisateur": CIBLE_DANS_LISTE})
        m[self.JETON].assert_called_once()
        m[self.SMTP].assert_called_once()
        self.assertTrue(any("Lien de réinitialisation envoyé" in f for f in self._flashes()))

    def test_creation_hors_liste_compte_cree_message_mode_test(self):
        data = {"prenom": "N", "nom": "Ouveau", "email": "nouveau@midgard.tn", "role": "intervenant",
                "equipe_code": "URBS", "actif": "on"}
        with self.assertLogs("app", "WARNING"):
            _, m = self._requete("post", "/utilisateurs/nouveau", data,
                                 espions=[("app.repositories.utilisateurs.create_utilisateur", 11),
                                          (self.JETON, None), (self.SMTP, None)],
                                 **{"app.auth.get_user_by_id": RH})
        m["app.repositories.utilisateurs.create_utilisateur"].assert_called_once()
        m[self.JETON].assert_not_called()
        m[self.SMTP].assert_not_called()
        flashes = self._flashes()
        self.assertTrue(any(f.startswith("Compte créé") and "mode test" in f for f in flashes), flashes)

    def _oublie(self, email, utilisateur):
        self._login()
        with self.client.session_transaction() as sess:
            sess.clear()
        with patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
                patch("app.repositories.securite.enregistrer_tentative"), \
                patch("app.auth.get_user_by_email", return_value=utilisateur) as chercher, \
                patch(self.JETON), patch(self.SMTP) as smtp:
            resp = self.client.post("/mot-de-passe-oublie", data={"email": email})
        return resp, self._flashes(), chercher, smtp

    def test_mot_de_passe_oublie_hors_liste_message_honnete_identique(self):
        _, connu, chercher, smtp = self._oublie("w.testeur@midgard.tn", {**smoke.USER, "email": "w.testeur@midgard.tn"})
        _, inconnu, _, _ = self._oublie("w.testeur@midgard.tn", None)
        self.assertEqual(connu, inconnu)  # ne révèle pas si le compte existe
        chercher.assert_not_called()      # la base n'est même pas consultée
        smtp.assert_not_called()
        self.assertTrue(any("phase de test" in f and "aucun lien" in f for f in connu), connu)
        self.assertFalse(any("va lui être envoyé" in f for f in connu), connu)

    def test_mot_de_passe_oublie_dans_la_liste_comportement_normal(self):
        _, connu, _, smtp = self._oublie("gerant@exemple.tn",
                                         {**smoke.USER, "id": 1, "email": "gerant@exemple.tn"})
        _, inconnu, _, _ = self._oublie("gerant@exemple.tn", None)
        self.assertEqual(connu, inconnu)
        self.assertTrue(any("un lien de réinitialisation va lui être envoyé" in f for f in connu), connu)


if __name__ == "__main__":
    unittest.main()

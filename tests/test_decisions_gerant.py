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
        self.assertIn('href="/fichiers/taches/1"', page)  # pièce jointe d'une tâche

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
                _, m = self._requete("post", "/projets/1/taches/5/etat", {"etat": etat},
                                     espions=[("app.repositories.taches.set_etat", True)],
                                     **self.INTERVENANT_DE_LA_TACHE)
                m["app.repositories.taches.set_etat"].assert_called_once_with(5, 1, etat, 1, peut_gerer=False)

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
        resp, _ = self._requete("post", "/projets/1/taches/5/etat", {"etat": "bloque"},
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
                    m["app.repositories.taches.set_etat"].assert_called_once_with(5, 1, etat, 1, peut_gerer=True)
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
        self.assertEqual(update.args[1][3:], (False, ["arret", "abandonne"]))
        # Déjà terminée : simple « rien à clôturer », pas un refus d'état réservé.
        self._curseur([None, {"etat": "termine"}])
        self.assertIsNone(taches.close_tache(5, 1, 1, "envoi"))

    # --- interface : seuls les états autorisés sont proposés ---
    def _page(self, utilisateur, gere, etat_tache):
        tache = {**smoke.TACHES_PROJET[0], "etat": etat_tache}
        resp, _ = self._requete("get", "/projets/1", **{
            "app.auth.get_user_by_id": utilisateur,
            "app.repositories.projets.user_can_manage": gere,
            "app.repositories.taches.list_taches_projet": [tache],
        })
        self.assertEqual(resp.status_code, 200)
        page = resp.data.decode()
        debut = page.index('id="dialog-tache-5"')
        return page[debut:page.index("</dialog>", debut)]

    def test_intervenant_ne_voit_que_en_cours_et_bloquee(self):
        dialogue = self._page(INTERVENANT, False, "bloque")
        self.assertIn('<option value="en_cours"', dialogue)
        self.assertIn('<option value="bloque"', dialogue)
        for etat in ("verifie", "arret", "abandonne"):
            self.assertNotIn(f'<option value="{etat}"', dialogue)
        self.assertIn("Marquer comme terminée", dialogue)

    def test_intervenant_sur_tache_terminee_peut_rouvrir_mais_pas_verifier(self):
        dialogue = self._page(INTERVENANT, False, "termine")
        self.assertIn("Rouvrir (en cours)", dialogue)
        self.assertNotIn('<option value="verifie"', dialogue)

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
            self.assertIn(f'<option value="{etat}"', dialogue)
        self.assertIn('<option value="verifie">Vérifiée</option>', self._page(CHEF, True, "termine"))
        self.assertIn("Rouvrir (en cours)", self._page(CHEF, True, "verifie"))
        self.assertIn("Marquer comme terminée", self._page(CHEF, True, "arret"))


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


if __name__ == "__main__":
    unittest.main()

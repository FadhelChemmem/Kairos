"""Lot 11 sur vrai PostgreSQL (décisions du gérant après la mise en
service). Ignorés sans KAIROS_TEST_DATABASE_URL."""
import datetime
from pathlib import Path

from tests_integration.base import BaseIntegration

RACINE = Path(__file__).resolve().parent.parent
MIGRATION_0016 = RACINE / "migrations" / "0016_equipe_projets_et_recherche.sql"
MIGRATION_0017 = RACINE / "migrations" / "0017_chef_projet_et_rappels_dailylog.sql"


class TestEquipeDesProjets(BaseIntegration):
    """Migration 0016 : projet sans équipe -> équipe du chef, à défaut
    MIDGARD ; visibilité qui en découle (v_projet_visibilite)."""

    def migrer(self):
        with self.db.get_cursor() as cur:
            cur.execute(MIGRATION_0016.read_text(encoding="utf-8"))
        self.rejouer_migrations_suivantes("0016_equipe_projets_et_recherche")

    def test_equipe_du_chef_sinon_midgard_rejouable_sans_toucher_updated_at(self):
        chef_midgard = self.user("chef_de_projet", "MIDGARD")
        chef_urbs = self.user("chef_de_projet", "URBS")
        chef_sans = self.user("chef_de_projet", None)
        p_midgard = self.projet(chef_midgard, equipe=None)
        p_urbs = self.projet(chef_urbs, equipe=None)
        p_sans = self.projet(chef_sans, equipe=None)
        p_garde = self.projet(chef_urbs, equipe="VD")  # équipe déjà choisie : intacte
        self.sql("ALTER TABLE projet DISABLE TRIGGER trg_projet_updated_at;"
                 "UPDATE projet SET updated_at = '2024-05-01 10:00+01';"
                 "ALTER TABLE projet ENABLE TRIGGER trg_projet_updated_at")
        audit_avant = self.sql("SELECT count(*) AS n FROM audit_log WHERE table_cible = 'projet'")[0]["n"]

        self.migrer()
        equipes = {r["id"]: r["equipe_code"] for r in self.sql("SELECT id, equipe_code FROM projet")}
        self.assertEqual(equipes, {p_midgard: "MIDGARD", p_urbs: "URBS", p_sans: "MIDGARD", p_garde: "VD"})
        self.assertEqual(self.sql("SELECT count(*) AS n FROM projet WHERE updated_at <> '2024-05-01 10:00+01'")[0]["n"], 0)
        # Une ligne d'audit par projet modifié ; le trigger updated_at est rétabli.
        self.assertEqual(self.sql("SELECT count(*) AS n FROM audit_log WHERE table_cible = 'projet'")[0]["n"],
                         audit_avant + 3)
        self.assertEqual(self.sql("""SELECT tgenabled FROM pg_trigger
                                     WHERE tgname = 'trg_projet_updated_at'""")[0]["tgenabled"], "O")
        # Rejouée : rien ne change.
        self.migrer()
        self.assertEqual({r["id"]: r["equipe_code"] for r in self.sql("SELECT id, equipe_code FROM projet")}, equipes)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM audit_log WHERE table_cible = 'projet'")[0]["n"],
                         audit_avant + 3)

    def test_un_chef_et_un_intervenant_midgard_voient_les_projets_midgard(self):
        from app.repositories import projets
        chef_a = self.user("chef_de_projet", "MIDGARD")
        chef_b = self.user("chef_de_projet", "MIDGARD")
        inter = self.user("intervenant", "MIDGARD")
        urbs = self.user("intervenant", "URBS")
        repris = [self.projet(chef_b, equipe=None) for _ in range(3)]
        self.assertFalse(any(projets.user_can_view(p, chef_a) for p in repris))  # avant : invisibles
        self.migrer()
        for uid in (chef_a, inter):
            self.assertEqual(projets.list_ids_visibles(uid), set(repris))
            self.assertEqual(projets.compter_projets(user_id=uid), 3)
        self.assertEqual(projets.list_ids_visibles(urbs), set())

    def test_creation_garde_l_equipe_du_chef(self):
        chef = self.user("chef_de_projet", "URBS")
        self.login(chef)
        self.client.post("/projets/nouveau", data={"nom": "Neuf", "code": "26001X", "phase": "EXE",
                                                    "chef_projet_id": chef, "date_debut": "2026-10-01",
                                                    "lots": "GO"})
        self.assertEqual(self.sql("SELECT equipe_code FROM projet WHERE code = '26001X'")[0]["equipe_code"], "URBS")


class TestListeDesProjets(BaseIntegration):
    def test_pagination_et_vrai_total(self):
        from app.repositories import projets
        chef = self.user("chef_de_projet")
        for i in range(120):
            self.projet(chef, code=f"26{i:03d}X")
        self.assertEqual(projets.compter_projets(user_id=chef), 120)
        pages = [projets.list_projets(user_id=chef, limit=50, offset=o) for o in (0, 50, 100)]
        self.assertEqual([len(p) for p in pages], [50, 50, 20])
        ids = [p["id"] for page in pages for p in page]
        self.assertEqual(len(set(ids)), 120)  # ordre stable, aucune ligne en double ni perdue
        self.assertEqual(len(projets.list_projets(user_id=chef, limit=None)), 120)
        self.login(chef)
        body = self.client.get("/projets?page=3").get_data(as_text=True)
        self.assertIn("120 projets · 101–120 affichés", body)
        self.assertIn("Page 3 sur 3", body)

    def test_prochain_rendu_sur_les_seules_taches_en_cours(self):
        from app.repositories import projets
        chef = self.user("chef_de_projet")
        p_bloque = self.projet(chef, code="26001X", etat="bloque")
        p_ok = self.projet(chef, code="26002X")
        self.tache(p_bloque, chef, etat="bloque", echeance=datetime.date(2022, 11, 17))
        self.tache(p_bloque, chef, etat="verifie", echeance=datetime.date(2023, 1, 5))
        self.tache(p_ok, chef, echeance=datetime.date(2026, 11, 2))
        lignes = projets.list_projets(user_id=chef)
        self.assertEqual([l["code"] for l in lignes], ["26002X", "26001X"])
        self.assertEqual(lignes[0]["prochain_rendu"], datetime.date(2026, 11, 2))
        self.assertIsNone(lignes[1]["prochain_rendu"])
        self.assertIsNone(lignes[1]["prochaine_echeance"])

    def test_recherche_dans_tous_les_projets_visibles(self):
        moi, autre = self.user("chef_de_projet"), self.user("chef_de_projet")
        self.projet(moi, code="26010X")
        louison = self.projet(autre, code="24102X")
        self.sql("UPDATE projet SET nom = 'Villa Louison' WHERE id = %s", (louison,))
        self.login(moi)
        ajax = {"X-Requested-With": "XMLHttpRequest"}  # le tableau seul
        body = self.client.get("/projets", headers=ajax).get_data(as_text=True)
        self.assertNotIn("Villa Louison", body)  # défaut : mes projets
        body = self.client.get("/projets?filtres_actifs=1&etat=en_cours&etat=bloque"
                               f"&chef_id={moi}&q=louison", headers=ajax).get_data(as_text=True)
        self.assertIn("24102X_Villa Louison", body)
        self.assertIn("est ignoré", body)


class TestCodePropose(BaseIntegration):
    def test_numero_d_affaire_global_hors_serie_9xx(self):
        from app.repositories import projets
        chef = self.user("chef_de_projet")
        for code in ("26076D", "26077X", "26088X", "26085P", "26922X", "26924X", "25120X"):
            self.projet(chef, code=code)
        self.assertEqual(projets.propose_code("APS", annee=2026), "26089P")
        self.assertEqual(projets.propose_code("DCE", annee=2026), "26089D")
        self.assertEqual(projets.propose_code("EXE", annee=2025), "25121X")
        self.assertEqual(projets.propose_code("EXE", annee=2026, phase_liee_code="26076D"), "26076X")
        self.assertEqual(projets.propose_code("DCE", annee=2026, phase_liee_code="26076D"), "26089D")  # pris
        self.login(chef)
        self.assertEqual(self.client.get("/projets/code-propose?phase=DOE").get_json()["code"],
                         f"{datetime.date.today().year % 100:02d}001E" if datetime.date.today().year != 2026 else "26089E")


class TestRechercheSansAccents(BaseIntegration):
    def setUp(self):
        super().setUp()
        self.chef = self.user("chef_de_projet")
        self.sql("UPDATE utilisateur SET prenom = 'Fadhel', nom = 'Chemmem' WHERE id = %s", (self.chef,))
        self.inactif = self.user("chef_de_projet", actif=False)
        self.sql("UPDATE utilisateur SET prenom = 'Omrane', nom = 'Ben Salah' WHERE id = %s", (self.inactif,))
        self.residence = self.projet(self.chef, code="26001X", debut=datetime.date(2026, 1, 5))
        self.sql("UPDATE projet SET nom = 'Résidence Été' WHERE id = %s", (self.residence,))
        self.coffrage = self.tache(self.residence, self.chef)
        self.sql("UPDATE tache SET titre = 'Plans de coffrage — Bâtiment B' WHERE id = %s", (self.coffrage,))
        # Projet d'une autre équipe : ni lui ni ses tâches ne sortent.
        urbs = self.user("chef_de_projet", "URBS")
        cache = self.projet(urbs, equipe="URBS", code="26002X")
        self.sql("UPDATE projet SET nom = 'Résidence cachée' WHERE id = %s", (cache,))
        t = self.tache(cache, urbs)
        self.sql("UPDATE tache SET titre = 'Coffrage caché' WHERE id = %s", (t,))

    def api(self, q):
        self.login(self.chef)
        return self.client.get("/recherche/api", query_string={"q": q}).get_json()["resultats"]

    def test_projets_sans_accents(self):
        from app.repositories import projets
        for q in ("residence", "RÉSIDENCE", "ete", "26001x_res"):
            with self.subTest(q=q):
                self.assertEqual([p["id"] for p in projets.search(self.chef, q)], [self.residence])
        labels = [r["label"] for r in self.api("residence")]
        self.assertEqual(labels, ["26001X_Résidence Été"])
        self.assertEqual(projets.compter_projets(user_id=self.chef, q="résidénce"), 1)

    def test_personnes_nom_complet_et_inactifs(self):
        from app.repositories import utilisateurs
        for q in ("fadhel chem", "Chemmem Fadhel", "chémmem", "  fadhel   chemmem "):
            with self.subTest(q=q):
                self.assertEqual([u["id"] for u in utilisateurs.search(q)], [self.chef])
        trouves = self.api("omrane")
        self.assertEqual(len(trouves), 1)
        self.assertEqual(trouves[0]["label"], "Omrane Ben Salah (inactif)")
        self.assertIn("compte désactivé", trouves[0]["sous_titre"])
        self.assertEqual([u["id"] for u in utilisateurs.list_tous(q="ben salah omrane")], [self.inactif])

    def test_taches_avec_lien_vers_le_projet(self):
        trouves = self.api("batiment b")
        self.assertEqual(len(trouves), 1)
        self.assertEqual(trouves[0]["label"], "Plans de coffrage — Bâtiment B")
        # Lot 11 b : le lien ouvre la fenêtre de la tâche sur la fiche.
        (tid,) = [r["id"] for r in self.sql("SELECT id FROM tache WHERE titre LIKE 'Plans de coffrage%%'")]
        self.assertEqual(trouves[0]["url"], f"/projets/{self.residence}?tache={tid}")
        self.assertIn("26001X_Résidence Été", trouves[0]["sous_titre"])
        self.assertEqual([r["label"] for r in self.api("coffrage")], ["Plans de coffrage — Bâtiment B"])

    def test_jokers_litteraux(self):
        self.assertEqual(self.api("%_"), [])

    def test_liste_des_projets_et_daily_log(self):
        from app.repositories import dailylog
        self.login(self.chef)
        body = self.client.get("/projets?filtres_actifs=1&q=residence",
                               headers={"X-Requested-With": "XMLHttpRequest"}).get_data(as_text=True)
        self.assertIn("26001X_Résidence Été", body)
        self.assertNotIn("cachée", body)
        trouves = dailylog.rechercher_projets("RESIDENCE ete", self.chef, datetime.date(2026, 10, 1))
        self.assertEqual([p["projet_id"] for p in trouves], [self.residence])
        self.assertEqual(dailylog.rechercher_projets("oeuvre", self.chef, datetime.date(2026, 10, 1)), [])
        self.sql("UPDATE projet SET nom = 'Gros Œuvre' WHERE id = %s", (self.residence,))
        trouves = dailylog.rechercher_projets("oeuvre", self.chef, datetime.date(2026, 10, 1))
        self.assertEqual([p["projet_id"] for p in trouves], [self.residence])


class TestEnTetesEtPagesErreur(BaseIntegration):
    def test_no_store_et_pages_d_erreur(self):
        chef = self.user("chef_de_projet")
        p = self.projet(chef)
        self.login(chef)
        for url in ("/accueil", f"/projets/{p}", "/projets/export.xlsx", "/dailylog/api/mois/2026-10"):
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.headers["Cache-Control"], "no-store")
        r = self.client.get("/projets/999999")
        self.assertEqual(r.status_code, 404)
        self.assertIn("Page introuvable", r.get_data(as_text=True))
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        r = self.client.get("/dailylog/api/jour/2026-13-40")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["erreur"], "date_invalide")


class TestAdminChefDesactive(BaseIntegration):
    def test_projets_ouverts_dont_le_chef_est_desactive(self):
        from app.repositories import projets
        admin, parti, present = self.user("admin"), self.user("chef_de_projet"), self.user("chef_de_projet")
        ouvert = self.projet(parti, code="21114X", etat="bloque")
        self.projet(parti, code="21115X", etat="termine")
        self.projet(present, code="21116X")
        self.sql("UPDATE utilisateur SET actif = false WHERE id = %s", (parti,))
        self.assertEqual([p["id"] for p in projets.list_ouverts_chef_inactif()], [ouvert])
        self.login(admin)
        body = self.client.get("/utilisateurs").get_data(as_text=True)
        self.assertIn("Projets ouverts dont le chef est désactivé (1)", body)
        self.assertIn(f'href="/projets/{ouvert}"', body)


class TestRappelDailyLogMarqueLu(BaseIntegration):
    """Lot 11 : le rappel d'un jour est marqué lu dès que ce jour est rempli
    ou marqué absent (Daily log v9, routes JSON et triggers réels)."""

    def setUp(self):
        super().setUp()
        from app.repositories import dailylog
        self.dl = dailylog
        self.chef = self.user("chef_de_projet")
        self.moi = self.user("intervenant")
        self.p = self.projet(self.chef, code="26069D")
        self.sql("UPDATE utilisateur SET created_at = now() - interval '400 days'")
        self.auj = dailylog.aujourdhui_pour({"fuseau": "Africa/Tunis"})
        self.j1 = self.auj - datetime.timedelta(days=1)
        self.j2 = self.auj - datetime.timedelta(days=2)
        for j in (self.j1, self.j2):
            self.rappel(j)
        # Rappels de l'ancien format envoyés AVANT le lot 11 b : la migration
        # 0017 (rejouée ici) leur donne leur jour (rappel_jours).
        with self.db.get_cursor() as cur:
            cur.execute(MIGRATION_0017.read_text(encoding="utf-8"))
        self.rejouer_migrations_suivantes("0017_chef_projet_et_rappels_dailylog")

    def rappel(self, jour):
        self.sql("INSERT INTO notification (utilisateur_id, categorie, message) VALUES (%s, 'rh_info', %s)",
                 (self.moi, f"Rappel DailyLog : vous n'avez pas rempli votre journée du {jour.strftime('%d/%m/%Y')}."))

    def lus(self):
        # Les rappels de l'ancien format seulement (la première page du jour
        # peut en envoyer un nouveau, pour les autres jours oubliés).
        return {r["message"][-11:-1]: r["lu"] for r in self.sql(
            "SELECT message, lu FROM notification WHERE utilisateur_id = %s AND message LIKE 'Rappel%%'",
            (self.moi,))}

    def test_jour_rempli_puis_jour_absent(self):
        self.login(self.moi)
        r = self.client.put(f"/dailylog/api/jour/{self.j1.isoformat()}",
                            json={"version": 0, "lignes": [{"projet_id": self.p, "tache_id": None, "minutes": 120}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(self.lus(), {self.j1.strftime("%d/%m/%Y"): True, self.j2.strftime("%d/%m/%Y"): False})
        r = self.client.post(f"/dailylog/api/jour/{self.j2.isoformat()}/absence", json={"version": 0, "absent": True})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(set(self.lus().values()), {True})

    def test_correction_par_le_chef(self):
        self.login(self.chef)
        r = self.client.put(f"/dailylog/api/jour/{self.j1.isoformat()}?utilisateur={self.moi}",
                            json={"version": 0, "lignes": [{"projet_id": self.p, "tache_id": None, "minutes": 60}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(self.lus()[self.j1.strftime("%d/%m/%Y")])

    def test_rappel_quotidien_nettoie_les_anciens(self):
        from app.repositories import notifications
        with self.db.get_cursor() as cur:  # jour rempli hors de l'appli (reprise, script)
            cur.execute("SET LOCAL kairos.reprise_historique = 'on'")
            cur.execute("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, 8)",
                        (self.moi, self.j2, self.p))
        self.sql("INSERT INTO notification (utilisateur_id, categorie, message) VALUES (%s, 'rh_info', 'Autre message 01/01/2026')",
                 (self.moi,))
        notifications.marquer_rappels_dailylog_lus(self.moi)
        lus = self.lus()
        self.assertTrue(lus[self.j2.strftime("%d/%m/%Y")])
        self.assertFalse(lus[self.j1.strftime("%d/%m/%Y")])
        self.assertEqual(self.sql("SELECT lu FROM notification WHERE message LIKE 'Autre%%'")[0]["lu"], False)
        # Par la session : une fois par jour, à la première page.
        self.sql("INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, heures) VALUES (%s, %s, %s, 2)",
                 (self.moi, self.j1, self.p))
        self.login(self.moi)
        self.assertEqual(self.client.get("/accueil").status_code, 200)
        self.assertTrue(self.lus()[self.j1.strftime("%d/%m/%Y")])

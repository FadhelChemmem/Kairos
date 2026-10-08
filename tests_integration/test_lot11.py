"""Lot 11 sur vrai PostgreSQL (décisions du gérant après la mise en
service). Ignorés sans KAIROS_TEST_DATABASE_URL."""
import datetime
from pathlib import Path

from tests_integration.base import BaseIntegration

RACINE = Path(__file__).resolve().parent.parent
MIGRATION_0016 = RACINE / "migrations" / "0016_equipe_projets_et_recherche.sql"


class TestEquipeDesProjets(BaseIntegration):
    """Migration 0016 : projet sans équipe -> équipe du chef, à défaut
    MIDGARD ; visibilité qui en découle (v_projet_visibilite)."""

    def migrer(self):
        with self.db.get_cursor() as cur:
            cur.execute(MIGRATION_0016.read_text(encoding="utf-8"))

    def test_equipe_du_chef_sinon_midgard_rejouable_sans_toucher_updated_at(self):
        chef_midgard = self.user("chef_de_projet", "MIDGARD")
        chef_urbs = self.user("chef_de_projet", "URBS")
        chef_sans = self.user("chef_de_projet", None)
        p_midgard = self.projet(chef_midgard, equipe=None)
        p_urbs = self.projet(chef_urbs, equipe=None)
        p_sans = self.projet(chef_sans, equipe=None)
        p_garde = self.projet(chef_urbs, equipe="IPCO")  # équipe déjà choisie : intacte
        self.sql("ALTER TABLE projet DISABLE TRIGGER trg_projet_updated_at;"
                 "UPDATE projet SET updated_at = '2024-05-01 10:00+01';"
                 "ALTER TABLE projet ENABLE TRIGGER trg_projet_updated_at")
        audit_avant = self.sql("SELECT count(*) AS n FROM audit_log WHERE table_cible = 'projet'")[0]["n"]

        self.migrer()
        equipes = {r["id"]: r["equipe_code"] for r in self.sql("SELECT id, equipe_code FROM projet")}
        self.assertEqual(equipes, {p_midgard: "MIDGARD", p_urbs: "URBS", p_sans: "MIDGARD", p_garde: "IPCO"})
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
                                                    "chef_projet_id": chef, "date_debut": "2026-10-01"})
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
        self.assertEqual(trouves[0]["url"], f"/projets/{self.residence}")
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

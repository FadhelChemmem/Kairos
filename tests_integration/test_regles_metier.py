import datetime
import pathlib
import subprocess
import unittest

from tests_integration.base import URL, BaseIntegration


class TestPermissions(BaseIntegration):
    def test_admin_co_chef_de_tous_les_projets(self):
        from app.repositories import projets
        admin, chef = self.user("admin", equipe=None), self.user("chef_de_projet")
        p = self.projet(chef)
        self.assertTrue(projets.user_can_view(p, admin))
        self.assertTrue(projets.user_can_manage(p, admin))   # décision attendue

    def test_client_et_rh_ne_gerent_jamais_meme_anciens_rattachements(self):
        from app.repositories import projets
        chef = self.user("chef_de_projet")
        client = self.user("intervenant")
        p = self.projet(chef)
        self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s)", (p, client))
        self.sql("ALTER TABLE utilisateur DISABLE TRIGGER USER")
        self.sql("UPDATE utilisateur SET role = 'client' WHERE id = %s", (client,))
        self.sql("ALTER TABLE utilisateur ENABLE TRIGGER USER")
        self.assertFalse(projets.user_can_manage(p, client))

    def test_co_chef_d_un_autre_ne_donne_aucun_droit(self):
        from app.repositories import projets
        chef, co_chef, tiers = self.user("chef_de_projet"), self.user("chef_de_projet"), self.user("intervenant")
        p = self.projet(chef)
        self.sql("INSERT INTO projet_co_chef (projet_id, utilisateur_id) VALUES (%s, %s)", (p, co_chef))
        self.assertTrue(projets.user_can_manage(p, co_chef))
        self.assertFalse(projets.user_can_manage(p, tiers))

    def test_matrice_visibilite_par_role(self):
        from app.repositories import projets
        chef_m, chef_u = self.user("chef_de_projet"), self.user("chef_de_projet", "URBS")
        pm, pu = self.projet(chef_m), self.projet(chef_u, "URBS")
        attendu = {self.user("admin", None): {pm, pu}, self.user("rh"): set(),
                   self.user("client"): {pm}, chef_m: {pm}, chef_u: {pu}}
        for uid, ids in attendu.items():
            with self.subTest(uid=uid):
                self.assertEqual(projets.list_ids_visibles(uid), ids)
                self.assertEqual({p for p in (pm, pu) if projets.user_can_view(p, uid)}, ids)

    def test_rh_ne_peut_pas_creer_un_admin(self):
        rh = self.user("rh")
        self.login(rh)
        self.client.post("/utilisateurs/nouveau", data={
            "prenom": "X", "nom": "Y", "email": "pirate@t.tn", "role": "admin", "actif": "on"})
        self.assertEqual(self.sql("SELECT count(*) AS n FROM utilisateur WHERE role='admin'")[0]["n"], 0)

    def test_chef_ajoute_comme_intervenant_devient_co_chef(self):
        chef, autre_chef = self.user("chef_de_projet"), self.user("chef_de_projet")
        p = self.projet(chef)
        self.login(chef)
        self.client.post(f"/projets/{p}/intervenants", data={"utilisateur_id": autre_chef})
        from app.repositories import projets
        self.assertTrue(projets.user_can_manage(p, autre_chef))


class TestTachesCloses(BaseIntegration):
    def test_mes_taches_et_deadlines_excluent_verifie_et_arret(self):
        from app.repositories import taches
        chef = self.user("chef_de_projet")
        p = self.projet(chef)
        ouvertes = {self.tache(p, chef, etat="en_cours", intervenants=[chef])}
        for etat in ("verifie", "arret", "termine", "abandonne", "bloque"):
            self.tache(p, chef, etat=etat, intervenants=[chef])
        self.assertEqual({t["id"] for t in taches.list_mes_taches(chef)}, ouvertes)
        self.assertEqual({t["id"] for t in taches.list_deadlines(chef)}, ouvertes)

    def test_deadlines_limitees_a_mes_projets_et_avec_echeance(self):
        from app.repositories import taches
        moi, autre = self.user("intervenant"), self.user("chef_de_projet")
        p_autre = self.projet(autre)
        self.tache(p_autre, autre)                                  # pas impliqué
        p_moi = self.projet(autre)
        self.sql("INSERT INTO projet_intervenant (projet_id, utilisateur_id) VALUES (%s,%s)", (p_moi, moi))
        sans = self.sql("INSERT INTO tache (projet_id, titre, created_by) VALUES (%s,'S',%s) RETURNING id",
                        (p_moi, autre))[0]["id"]
        avec = self.tache(p_moi, autre)
        self.assertEqual([t["id"] for t in taches.list_deadlines(moi)], [avec])
        self.assertNotIn(sans, [t["id"] for t in taches.list_deadlines(moi)])


class TestDailyLogRepository(BaseIntegration):
    """enregistrer_jour (lot 10) : une journée n'efface jamais les autres
    jours ni les autres personnes ; l'absence retire les heures du jour."""

    def _ecrire(self, uid, date, lignes, absent=False):
        from app.repositories import dailylog
        version = dailylog.lire_jour(uid, date)["version"]
        return dailylog.enregistrer_jour(uid, date, version, uid,
                                         lambda existantes, absent_actuel: (absent, dict(lignes)))

    def test_journee_absente_efface_les_heures(self):
        u = self.user("intervenant"); p = self.projet(self.user("chef_de_projet"))
        j = datetime.date.today()
        self._ecrire(u, j, {(p, 0): 480})
        self._ecrire(u, j, {}, absent=True)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM dailylog_entree WHERE utilisateur_id=%s", (u,))[0]["n"], 0)

    def test_n_efface_jamais_les_autres_jours_ni_les_autres_personnes(self):
        u, v = self.user("intervenant"), self.user("intervenant")
        p = self.projet(self.user("chef_de_projet"))
        hier = datetime.date.today() - datetime.timedelta(days=1)
        auj = datetime.date.today()
        self._ecrire(u, hier, {(p, 0): 480})
        self._ecrire(u, auj, {(p, 0): 480})
        self._ecrire(v, auj, {(p, 0): 480})
        self._ecrire(u, auj, {}, absent=True)
        restantes = self.sql("SELECT utilisateur_id, date FROM dailylog_entree ORDER BY 1, 2")
        self.assertEqual([(r["utilisateur_id"], r["date"]) for r in restantes], [(u, hier), (v, auj)])


class TestDailyLogRegles(BaseIntegration):
    """Règles du Daily log (lot 10) par l'API : fenêtre de 14 jours
    (décision 4), 10 h par jour, pas de 30 min, dates absurdes. Ces tests
    étaient « échec attendu » avant la réécriture du Daily log."""

    def _put(self, jours_avant=0, minutes=(480,)):
        u = self.user("intervenant"); p = self.projet(self.user("chef_de_projet"))
        self.sql("UPDATE utilisateur SET created_at = now() - interval '60 days'")
        self.login(u)
        from app.repositories import dailylog
        date = dailylog.aujourdhui_pour({"fuseau": "Africa/Tunis"}) - datetime.timedelta(days=jours_avant)
        lignes = [{"projet_id": p, "minutes": m} for m in minutes]
        if len(lignes) > 1:
            lignes = [{"projet_id": self.projet(self.user("chef_de_projet")), "minutes": m} for m in minutes]
        self.client.put(f"/dailylog/api/jour/{date.isoformat()}", json={"version": 0, "lignes": lignes})
        return self.sql("SELECT coalesce(sum(heures),0) AS h FROM dailylog_entree WHERE utilisateur_id=%s", (u,))[0]["h"]

    def test_fenetre_de_14_jours(self):
        self.assertEqual(float(self._put(jours_avant=14)), 8.0)
        self.assertEqual(float(self._put(jours_avant=15)), 0.0)

    def test_maximum_10_heures_par_jour(self):
        self.assertEqual(float(self._put(minutes=(600,))), 10.0)
        self.assertEqual(float(self._put(minutes=(630,))), 0.0)
        self.assertEqual(float(self._put(minutes=(360, 270))), 0.0)

    def test_pas_de_30_minutes(self):
        self.assertEqual(float(self._put(minutes=(450,))), 7.5)
        self.assertEqual(float(self._put(minutes=(435,))), 0.0)

    def test_date_absurde_refusee_sans_500(self):
        u = self.user("intervenant"); self.login(u)
        for date in ("0001-01-01", "1989-12-31", "²", "2026-02-30"):
            r = self.client.put(f"/dailylog/api/jour/{date}", json={"version": 0, "lignes": []})
            self.assertEqual(r.status_code, 400, date)
        self.assertEqual(self.sql("SELECT count(*) AS n FROM dailylog_jour WHERE date < '2000-01-01'")[0]["n"], 0)


class TestMigrations(BaseIntegration):
    RACINE = pathlib.Path(__file__).resolve().parent.parent

    def test_flask_migrer_rejouable(self):
        runner = self.app.test_cli_runner()
        for _ in range(2):
            res = runner.invoke(args=["migrer"])
            self.assertEqual(res.exit_code, 0, res.output)
        self.assertIn("Rien à faire", res.output)

    def test_montee_de_version_depuis_le_schema_d_origine(self):
        """Base « comme en prod avant les migrations » : flask migrer joue tout, dans l'ordre,
        puis ne rejoue rien."""
        import os, sys
        base = "kairos_it_montee"
        psql = ["psql", URL.rsplit("/", 1)[0] + "/postgres", "-v", "ON_ERROR_STOP=1", "-q"]
        subprocess.run(psql + ["-c", f"DROP DATABASE IF EXISTS {base}"], check=True, capture_output=True)
        subprocess.run(psql + ["-c", f"CREATE DATABASE {base}"], check=True, capture_output=True)
        racine_commit = subprocess.run(["git", "rev-list", "--max-parents=0", "HEAD"], cwd=self.RACINE,
                                       capture_output=True, text=True).stdout.split()
        if not racine_commit:
            self.skipTest("historique git indisponible")
        origine = subprocess.run(["git", "show", f"{racine_commit[-1]}:schema.sql"], cwd=self.RACINE,
                                 capture_output=True, text=True, check=True).stdout
        subprocess.run(["psql", URL.rsplit("/", 1)[0] + "/" + base, "-v", "ON_ERROR_STOP=1", "-q"],
                       input=origine, text=True, check=True, capture_output=True)
        env = dict(os.environ, DATABASE_URL=URL.rsplit("/", 1)[0] + "/" + base, FLASK_APP="wsgi.py",
                   SECRET_KEY="x" * 40, UPLOAD_DIR=self.app.config["UPLOAD_DIR"])
        cmd = [sys.executable, "-m", "flask", "migrer"]
        r1 = subprocess.run(cmd, cwd=self.RACINE, env=env, capture_output=True, text=True)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        jouees = [l.split()[2].rstrip(".") for l in r1.stdout.splitlines() if l.startswith("Application de")]
        attendues = sorted(f.name for f in (self.RACINE / "migrations").glob("*.sql"))
        self.assertEqual(jouees, attendues)
        r2 = subprocess.run(cmd, cwd=self.RACINE, env=env, capture_output=True, text=True)
        self.assertIn("Rien à faire", r2.stdout)

    def test_schema_sql_declare_toutes_les_migrations(self):
        fichiers = sorted(f.stem for f in (self.RACINE / "migrations").glob("*.sql"))
        en_base = [r["version"] for r in self.sql("SELECT version FROM schema_migrations ORDER BY 1")]
        self.assertEqual(en_base, fichiers)

    def test_migrations_publiees_jamais_modifiees(self):
        """Une migration déjà sur origin/master ne change plus (sinon les bases en prod ne la
        rejouent jamais) — voir 0011/0012 modifiées le 2026-09-29."""
        diff = subprocess.run(["git", "diff", "--name-status", "--diff-filter=MDR", "origin/master", "--",
                               "migrations/"], cwd=self.RACINE, capture_output=True, text=True)
        if diff.returncode != 0:
            self.skipTest("origin/master indisponible")
        self.assertEqual(diff.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()

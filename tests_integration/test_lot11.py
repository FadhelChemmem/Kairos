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
        self.assertEqual(projets.list_ids_visibles(urbs), set())

    def test_creation_garde_l_equipe_du_chef(self):
        chef = self.user("chef_de_projet", "URBS")
        self.login(chef)
        self.client.post("/projets/nouveau", data={"nom": "Neuf", "code": "26001X", "phase": "EXE",
                                                    "chef_projet_id": chef, "date_debut": "2026-10-01"})
        self.assertEqual(self.sql("SELECT equipe_code FROM projet WHERE code = '26001X'")[0]["equipe_code"], "URBS")

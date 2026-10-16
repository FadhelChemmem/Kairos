"""Socle des tests d'intégration : VRAI PostgreSQL, VRAI psycopg2.

Lancés à part (jamais dans le même processus que tests/test_smoke.py, qui
installe un faux psycopg2 dans sys.modules) :

    KAIROS_TEST_DATABASE_URL=postgresql://kairos:kairos@127.0.0.1:5432/kairos_it \
    python -m unittest discover -s tests_integration -t .

La base doit déjà contenir schema.sql + migrations (voir la CI). Chaque test
part de tables métier vides (TRUNCATE ... RESTART IDENTITY CASCADE ; les
tables de référence equipe/lot/post_type/reaction_type sont conservées).
"""
import datetime
import os
import tempfile
import unittest

URL = os.environ.get("KAIROS_TEST_DATABASE_URL")

TABLES_METIER = (
    "notification, post_commentaire_mention, post_commentaire_piece_jointe, post_commentaire, "
    "post_reaction, post_equipe, post_mention, post_piece_jointe, post, dailylog_preference, dailylog_jour, "
    "dailylog_entree, tache_piece_jointe, tache_intervenant, tache, projet_intervenant, "
    "projet_co_chef, projet_lot, projet, tentative_securite, audit_log, utilisateur_session, utilisateur_preference, utilisateur"
)


def fermer_pool() -> None:
    """Ferme les connexions du pool de l'appli (recette lot 14, n° 14) :
    chaque classe de tests crée sa propre appli et son pool ; sans cette
    fermeture, les connexions des classes précédentes restaient ouvertes
    jusqu'à la fin du processus (pic de 99 connexions pour 100 permises :
    « too many clients » dès qu'une autre base du serveur travaillait)."""
    from app import db

    if db._pool is not None:
        db._pool.closeall()
    db._pool = None


class BaseIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not URL:
            raise unittest.SkipTest("KAIROS_TEST_DATABASE_URL non défini")
        os.environ.setdefault("SECRET_KEY", "x" * 40)
        from app import create_app, db
        from app.config import Config

        class ConfigIT(Config):
            TESTING = True
            SECRET_KEY = "x" * 40
            DATABASE_URL = URL
            WTF_CSRF_ENABLED = False
            UPLOAD_DIR = tempfile.mkdtemp(prefix="kairos-it-")

        fermer_pool()
        cls.app = create_app(ConfigIT)
        cls.db = db

    @classmethod
    def tearDownClass(cls):
        fermer_pool()
        super().tearDownClass()

    def setUp(self):
        with self.db.get_cursor() as cur:
            cur.execute(f"TRUNCATE {TABLES_METIER} RESTART IDENTITY CASCADE")
        self.client = self.app.test_client()

    # --- fabriques -------------------------------------------------------
    def sql(self, requete, params=()):
        with self.db.get_cursor() as cur:
            cur.execute(requete, params)
            try:
                return cur.fetchall()
            except Exception:
                return None

    def user(self, role, equipe="MIDGARD", actif=True, email=None):
        email = email or f"{role}-{equipe}-{os.urandom(3).hex()}@t.tn"
        return self.sql(
            "INSERT INTO utilisateur (email, mot_de_passe_hash, prenom, nom, role, equipe_code, actif) "
            "VALUES (%s, 'h', 'P', %s, %s, %s, %s) RETURNING id",
            (email, role, role, equipe, actif))[0]["id"]

    def projet(self, chef_id, equipe="MIDGARD", etat="en_cours", code=None, debut=None):
        code = code or f"T{os.urandom(2).hex().upper()}X"
        return self.sql(
            "INSERT INTO projet (code, nom, phase, chef_projet_id, equipe_code, etat, date_debut) "
            "VALUES (%s, 'Projet', 'EXE', %s, %s, %s, %s) RETURNING id",
            (code, chef_id, equipe, etat, debut))[0]["id"]

    def tache(self, projet_id, auteur_id, etat="en_cours", echeance=None, intervenants=()):
        echeance = echeance or datetime.date.today() + datetime.timedelta(days=7)
        tid = self.sql(
            "INSERT INTO tache (projet_id, titre, created_by, etat, date_echeance) "
            "VALUES (%s, 'T', %s, %s, %s) RETURNING id", (projet_id, auteur_id, etat, echeance))[0]["id"]
        for uid in intervenants:
            self.sql("INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (%s, %s)", (tid, uid))
        return tid

    def rejouer_migrations_suivantes(self, version: str) -> None:
        """Après le rejeu d'une ANCIENNE migration (test de rejouabilité),
        rejoue toutes les suivantes : sinon la base partagée par la suite
        garde l'ancienne version d'une fonction ou d'une contrainte redéfinie
        depuis (ex. 0018 rejouée après 0019 : fn_aujourdhui sans instant
        simulé), et les tests qui suivent tournent sur un schéma périmé."""
        from pathlib import Path

        for fichier in sorted((Path(__file__).resolve().parent.parent / "migrations").glob("*.sql")):
            if fichier.stem > version:
                with self.db.get_cursor() as cur:
                    cur.execute(fichier.read_text(encoding="utf-8"))

    def login(self, user_id):
        from app.auth import password_fingerprint
        with self.client.session_transaction() as s:
            s["user_id"] = user_id
            s["pw_fingerprint"] = password_fingerprint("h")

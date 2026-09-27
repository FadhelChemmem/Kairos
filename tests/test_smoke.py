"""Tests de fumée — vérifient que l'application se construit, que les
routes existent, et surtout que les templates Jinja2 s'affichent sans
erreur avec des données réalistes.

Pourquoi ces tests plutôt que des tests d'intégration classiques :
psycopg2 n'est pas installable dans cet environnement de développement
(voir le message envoyé à Fadhel sur la limite réseau du bac à sable).
On simule donc le module psycopg2 (jamais réellement appelé — toutes les
fonctions de repository qui l'utilisent sont remplacées par des fixtures)
et on exécute la vraie pile Flask + Jinja2 + routes + url_for pour
attraper les erreurs qu'une relecture ne verrait pas forcément
(variable manquante dans un template, endpoint url_for mal nommé, etc.).
La logique SQL elle-même a été validée séparément, en vrai, sur un
PostgreSQL local (voir schema.sql et les notes de conception).
"""
import datetime
import io
import sys
import types
import unittest
from unittest.mock import patch


def _install_fake_psycopg2():
    """Un stub minimal, juste assez pour que `import psycopg2`,
    `import psycopg2.extras` et `from psycopg2.pool import
    ThreadedConnectionPool` réussissent sans le vrai paquet installé."""
    if "psycopg2" in sys.modules:
        return

    psycopg2 = types.ModuleType("psycopg2")

    extras = types.ModuleType("psycopg2.extras")

    class RealDictCursor:
        pass

    extras.RealDictCursor = RealDictCursor

    pool_mod = types.ModuleType("psycopg2.pool")

    class ThreadedConnectionPool:
        def __init__(self, *args, **kwargs):
            pass

        def getconn(self):
            raise RuntimeError("Ne devrait jamais être appelé dans les tests de fumée (DB mockée)")

        def putconn(self, conn):
            pass

        def closeall(self):
            pass

    pool_mod.ThreadedConnectionPool = ThreadedConnectionPool

    psycopg2.extras = extras
    psycopg2.pool = pool_mod

    sys.modules["psycopg2"] = psycopg2
    sys.modules["psycopg2.extras"] = extras
    sys.modules["psycopg2.pool"] = pool_mod


_install_fake_psycopg2()

from app import create_app  # noqa: E402
from app.auth import password_fingerprint  # noqa: E402
from app.config import Config  # noqa: E402

# Hash de mot de passe "actuel" par défaut pour tous les tests connectés via
# _login() ci-dessous — PROMPT_CORRECTIONS.md P2 #17 : load_logged_in_user()
# compare désormais, à chaque requête, l'empreinte mémorisée en session à
# celle du hash renvoyé par get_mot_de_passe_hash() ; les deux doivent
# rester cohérentes pour qu'une session ouverte via _login() reste valide.
MOT_DE_PASSE_HASH_PAR_DEFAUT = "hash-bidon"


class TestConfig(Config):
    DATABASE_URL = "postgresql://fake/fake"  # jamais utilisé, get_cursor n'est pas appelé
    SECRET_KEY = "test-secret"
    TESTING = True


# --- Fixtures : formes de lignes telles que les repositories les renvoient ---

USER = {
    "id": 1, "email": "fadhel@midgard.tn", "nom": "Chedly", "prenom": "Foulen",
    "role": "admin", "actif": True, "poste": "Ingénieur", "equipe_code": "MIDGARD",
}

MES_PROJETS = [
    {"id": 1, "code": "26099X", "nom": "Tour Meridian", "phase": "EXE", "etat": "bloque", "mon_role": "chef_de_projet"},
    {"id": 2, "code": "25014X", "nom": "Résidence Les Oliviers", "phase": "EXE", "etat": "en_cours", "mon_role": "intervenant"},
]

DEADLINES = [
    {"id": 1, "titre": "Note de calcul EXE", "etat": "en_cours", "date_echeance": datetime.date(2026, 9, 18),
     "type_deadline": "rendu_client", "projet_id": 1, "projet_code": "26099X", "projet_nom": "Tour Meridian"},
]

MES_TACHES = [
    {"id": 1, "titre": "Plan ferraillage voile R+2", "etat": "bloque", "date_echeance": datetime.date(2026, 9, 20),
     "projet_id": 1, "projet_nom": "Tour Meridian"},
]

FEED_POST_MANUEL = {
    "id": 1, "type_code": "envoi", "contenu": "Envoi du dossier EXE lot GO.", "created_at": datetime.datetime(2026, 9, 15, 10, 0),
    "tache_id": None, "parent_post_id": None, "projet_id": 1, "projet_code": "26099X", "projet_nom": "Tour Meridian",
    "auteur_id": 2, "auteur_prenom": "Foulen", "auteur_nom": "Ben Foulen",
    "tache_titre": None, "tache_etat": None, "est_creation_tache": False, "est_cloture_tache": False,
    "nb_reactions": 12, "nb_commentaires": 2, "ma_reaction": None, "pieces_jointes": [],
    "reacteurs": [], "commentaires": [],
    "parent_contenu": None, "parent_type_code": None, "parent_auteur_prenom": None,
    "parent_auteur_nom": None, "parent_tache_titre": None,
}

FEED_POST_CREATION_TACHE = {
    **FEED_POST_MANUEL, "id": 2, "contenu": "Reprise ferraillage voile R+2", "tache_id": 5,
    "tache_titre": "Reprise ferraillage voile R+2", "tache_etat": "en_cours", "est_creation_tache": True,
    "nb_reactions": 4, "nb_commentaires": 0,
}

FEED_POST_REBOND = {
    **FEED_POST_MANUEL, "id": 3, "type_code": "requete", "contenu": "Blocage sur la reprise du voile R+2.",
    "parent_post_id": 2, "parent_contenu": None, "parent_type_code": None,
    "parent_auteur_prenom": "Foulen", "parent_auteur_nom": "Chedly", "parent_tache_titre": "Plan ferraillage voile R+2",
}

# Bug corrigé (2026-09-27, retour Fadhel) : un post de clôture de tâche
# affichait toujours la pastille "Terminé" (état de la tâche), jamais le
# tag (Envoi/Réponse/Question/Requête) réellement choisi par l'utilisateur
# à la clôture — voir partials/post_card.html et taches.close_tache. Ici le
# tag choisi est "question", volontairement différent de "termine", pour
# que le test échoue si le gabarit retombe sur l'ancien comportement.
FEED_POST_CLOTURE_TACHE = {
    **FEED_POST_MANUEL, "id": 4, "type_code": "question", "contenu": "Point bloquant résolu ?",
    "tache_id": 5, "tache_titre": "Plan ferraillage voile R+2", "tache_etat": "termine",
    "est_cloture_tache": True,
}

FEED = [FEED_POST_MANUEL, FEED_POST_CREATION_TACHE, FEED_POST_REBOND]

PROJET = {
    "id": 1, "code": "26099X", "nom": "Tour Meridian", "phase": "EXE", "etat": "bloque",
    "date_debut": datetime.date(2025, 2, 3), "date_fin": None, "honoraires": None,
    "chef_projet_id": 1, "phase_liee_id": None, "chef_prenom": "Foulen", "chef_nom": "Chedly",
    "phase_liee_code": None, "phase_liee_nom": None, "heures_cumulees": 482.0,
}

# Projet fraîchement créé, sans aucune ligne DailyLog : v_projet_heures ne
# renvoie donc aucune ligne pour lui, et le LEFT JOIN donne heures_cumulees
# = None (pas 0). Fixture dédiée pour attraper un bug réel remonté par
# Fadhel (2026-09-19) : `None|default(0)|round(1)` plante (le filtre Jinja
# `default` ne remplace que les valeurs Undefined, pas None) — la création
# d'un projet plantait donc systématiquement en 500 dès la redirection vers
# sa page, et "Tous les projets" plantait de la même façon pour tout projet
# sans heures. Corrigé en `default(0, true)` (le `true` force le
# remplacement des valeurs falsy, dont None) dans projet_detail.html et
# projets_liste.html.
PROJET_SANS_HEURES = {
    "id": 2, "code": "26001X", "nom": "Projet de test", "phase": "EXE", "etat": "en_cours",
    "date_debut": datetime.date(2026, 9, 19), "date_fin": None, "honoraires": None,
    "chef_projet_id": 1, "phase_liee_id": None, "chef_prenom": "Fadhel", "chef_nom": "Chemmem",
    "phase_liee_code": None, "phase_liee_nom": None, "heures_cumulees": None,
}

PROJET_LISTE_SANS_HEURES = {
    "id": 2, "code": "26001X", "nom": "Projet de test", "phase": "EXE", "etat": "en_cours",
    "date_debut": datetime.date(2026, 9, 19), "date_fin": None,
    "chef_prenom": "Fadhel", "chef_nom": "Chemmem", "chef_id": 1, "lots": "GO",
    "heures_cumulees": None, "prochaine_echeance": None,
}

UTILISATEUR_PROFIL = {
    "id": 1, "prenom": "Foulen", "nom": "Chedly", "email": "fadhel@midgard.tn",
    "telephone": "20 000 000", "poste": "Ingénieur", "adresse": "Tunis",
    "date_embauche": datetime.date(2021, 3, 1), "equipe_code": "MIDGARD",
    "role": "admin", "verifie": True, "actif": True, "champs_perso": {},
}

# Un AUTRE utilisateur que celui connecté (id 1 dans USER/UTILISATEUR_PROFIL) —
# utilisé pour les tests de la fiche admin/RH (routes/utilisateurs.py:fiche),
# où on doit pouvoir éditer le compte de quelqu'un d'autre sans restriction,
# contrairement à son propre compte (garde-fou anti-auto-changement de rôle).
AUTRE_UTILISATEUR = {
    "id": 2, "prenom": "Wael", "nom": "Rekik", "email": "w.rekik@midgard.tn",
    "telephone": None, "poste": "Technicien", "adresse": None,
    "date_embauche": None, "equipe_code": "URBS",
    "role": "intervenant", "verifie": True, "actif": True, "champs_perso": {},
}

# Compte "client" (role_enum, schema.sql) — pas proposable depuis
# utilisateur_creer.html/fiche.html (ROLES_CREABLES, étape 2), mais peut
# exister en base via `flask create-user --role client` : sert à vérifier
# le correctif PROMPT_CORRECTIONS.md P1 #12 (rôle hors liste verrouillé, pas
# silencieusement remplacé par le premier de la liste).
UTILISATEUR_CLIENT = {**AUTRE_UTILISATEUR, "role": "client"}

# Compte sans équipe assignée (equipe_code NULL, colonne nullable) — sert à
# vérifier le correctif PROMPT_CORRECTIONS.md P1 #12 (option vide du
# <select> Équipe).
UTILISATEUR_SANS_EQUIPE = {**AUTRE_UTILISATEUR, "equipe_code": None}

RESET_TOKEN_ROW = {"id": 1, "email": "fadhel@midgard.tn", "prenom": "Foulen", "nom": "Chedly", "actif": True}

TACHE_SANS_HEURES = {
    "id": 20, "projet_id": 2, "titre": "Première tâche", "etat": "en_cours",
    "type_deadline": "rendu_client", "date_debut": None, "date_echeance": None,
    "date_fin": None, "dossier_lien": None,
    "created_at": datetime.datetime(2026, 9, 19), "updated_at": datetime.datetime(2026, 9, 19),
    "heures_cumulees": None, "intervenants": [], "pieces_jointes": [],
}

# Fixtures pour les contrôles d'accès (IDOR, PROMPT_CORRECTIONS.md P0 #1) :
# tache_id=5/post_id=1, rattachés au projet_id=1, pour correspondre aux
# autres fixtures/appels de test_write_routes_redirect_without_crashing.
TACHE_POUR_FICHIERS = {**TACHE_SANS_HEURES, "id": 5, "projet_id": 1}
POST_POUR_ACCES = {"id": 1, "projet_id": 1, "tache_id": None, "parent_post_id": None, "auteur_id": 2}
PIECE_JOINTE_TACHE = {"id": 1, "tache_id": 5, "nom_fichier": "note_calcul.pdf", "chemin": "taches/5/x.pdf", "projet_id": 1}
PIECE_JOINTE_POST = {"id": 1, "post_id": 1, "nom_fichier": "plan.pdf", "chemin": "posts/1/x.pdf", "projet_id": 1}

LOTS = [{"code": "CM", "libelle": "Charpente Métallique"}, {"code": "GO", "libelle": "Gros Œuvre"}]

INTERVENANTS = [
    {"id": 1, "prenom": "Foulen", "nom": "Chedly", "poste": "Ingénieur", "role_label": "Chef de projet"},
    {"id": 3, "prenom": "Omar", "nom": "Aziz", "poste": "Technicien", "role_label": "Technicien"},
]

TACHES_PROJET = [
    {
        "id": 5, "projet_id": 1, "titre": "Plan ferraillage voile R+2", "etat": "bloque",
        "type_deadline": "interne", "date_debut": None, "date_echeance": datetime.date(2026, 9, 20),
        "date_fin": None, "dossier_lien": None,
        "created_at": datetime.datetime(2026, 9, 10), "updated_at": datetime.datetime(2026, 9, 10),
        "heures_cumulees": 12.0,
        "intervenants": [{"id": 1, "prenom": "Foulen", "nom": "Chedly"}, {"id": 4, "prenom": "Sana", "nom": "Trabelsi"}],
        "pieces_jointes": [{"id": 1, "nom_fichier": "note_calcul.pdf"}],
    },
    {
        "id": 6, "projet_id": 1, "titre": "Dossier DOE — plans as-built", "etat": "termine",
        "type_deadline": "rendu_client", "date_debut": None, "date_echeance": datetime.date(2026, 9, 10),
        "date_fin": datetime.date(2026, 9, 12), "dossier_lien": None,
        "created_at": datetime.datetime(2026, 9, 1), "updated_at": datetime.datetime(2026, 9, 12),
        "heures_cumulees": 18.0, "intervenants": [], "pieces_jointes": [],
    },
]

UTILISATEURS_ACTIFS = [
    {"id": 1, "prenom": "Foulen", "nom": "Chedly", "poste": "Ingénieur"},
    {"id": 3, "prenom": "Omar", "nom": "Aziz", "poste": "Technicien"},
]

# Bug corrigé (2026-09-27, retour Fadhel) : le filtre "Chef de projet" de
# /projets listait TOUS les utilisateurs actifs (Intervenants, Clients...)
# via utilisateurs.list_actifs(), au lieu des seules personnes réellement
# chef de projet d'un projet — voir projets.list_chefs_de_projet(). Fixture
# volontairement différente de UTILISATEURS_ACTIFS (id 7 "Sana Trabelsi",
# absente de UTILISATEURS_ACTIFS ; id 3 "Omar Aziz" absent d'ici) pour que
# le test distingue clairement les deux sources.
CHEFS_DE_PROJET = [
    {"id": 1, "prenom": "Foulen", "nom": "Chedly"},
    {"id": 7, "prenom": "Sana", "nom": "Trabelsi"},
]

DAILYLOG_PROJETS = [{"id": 1, "code": "26099X", "nom": "Tour Meridian"}]
DAILYLOG_ENTREES = [{"id": 1, "projet_id": 1, "tache_id": None, "heures": 5.0, "projet_nom": "Tour Meridian", "tache_titre": None}]
DAILYLOG_SUGGESTIONS = {
    "mine": [{"projet_id": 1, "code": "26099X", "nom": "Tour Meridian", "tache_id": 5, "tache_titre": "Plan ferraillage voile R+2"},
             {"projet_id": 1, "code": "26099X", "nom": "Tour Meridian", "tache_id": None, "tache_titre": None}],
    # Palier "Récemment travaillés" (retour Fadhel, 2026-09-27) — a
    # remplacé l'ancienne clé "autres" (liste statique des 50 premiers
    # projets de l'entreprise) ; voir dailylog.list_projets_recents.
    "recentes": [{"projet_id": 9, "code": "24001X", "nom": "The Hub", "tache_id": None, "tache_titre": None}],
}
DAILYLOG_JOURS_REMPLIS = [datetime.date(2026, 9, 11), datetime.date(2026, 9, 14)]

NOTIFICATIONS = [
    {"id": 10, "categorie": "projet", "message": "Foulen Chedly vous a mentionné dans un post.",
     "lu": False, "created_at": datetime.datetime(2026, 9, 18, 9, 0),
     "post_id": 3, "tache_id": None, "post_projet_id": 1, "tache_projet_id": None, "tache_titre": None},
    {"id": 9, "categorie": "rh_info", "message": "Rappel DailyLog : vous n'avez pas rempli votre journée du 17/09/2026.",
     "lu": True, "created_at": datetime.datetime(2026, 9, 18, 8, 0),
     "post_id": None, "tache_id": None, "post_projet_id": None, "tache_projet_id": None, "tache_titre": None},
]
NOTIFICATION_UNE = {
    "id": 10, "categorie": "projet", "message": "Foulen Chedly vous a mentionné dans un post.",
    "lu": False, "created_at": datetime.datetime(2026, 9, 18, 9, 0),
    "post_id": 3, "tache_id": None, "post_projet_id": 1, "tache_projet_id": None,
}

UTILISATEURS_TOUS = [
    {"id": 1, "prenom": "Foulen", "nom": "Chedly", "email": "fadhel@midgard.tn", "telephone": "+216 20 000 000",
     "poste": "Ingénieur", "equipe_code": "MIDGARD", "role": "admin", "verifie": True, "actif": True,
     "date_embauche": datetime.date(2021, 3, 1)},
    {"id": 5, "prenom": "Amine", "nom": "Ben Salah", "email": "a.bensalah@midgard.tn", "telephone": None,
     "poste": "Ingénieur", "equipe_code": "MIDGARD", "role": "intervenant", "verifie": True, "actif": False,
     "date_embauche": datetime.date(2022, 4, 1)},
]
COMPTE_UTILISATEURS = {"total": 2, "actifs": 1}


class SmokeTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["pw_fingerprint"] = password_fingerprint(MOT_DE_PASSE_HASH_PAR_DEFAUT)

    def _patched(self, **overrides):
        """`overrides` permet à un test de remplacer, par sa cible (ex.
        "app.repositories.projets.get_projet"), la valeur par défaut d'un
        seul mock sans dupliquer toute la liste ni empiler un second patch
        sur la même cible (ce qui, avec unittest.mock, fait gagner le
        patch démarré en dernier — donc le défaut, pas l'override)."""
        defaults = {
            "app.auth.get_user_by_id": USER,
            "app.repositories.projets.list_mes_projets": MES_PROJETS,
            "app.repositories.projets.list_projets": [],
            "app.repositories.projets.list_chefs_de_projet": CHEFS_DE_PROJET,
            "app.repositories.projets.get_projet": PROJET,
            "app.repositories.projets.list_lots": LOTS,
            "app.repositories.projets.list_intervenants": INTERVENANTS,
            "app.repositories.projets.user_can_manage": True,
            "app.repositories.projets.user_can_view": True,
            "app.repositories.projets.propose_code": "26099X",
            "app.repositories.taches.list_deadlines": DEADLINES,
            "app.repositories.taches.list_mes_taches": MES_TACHES,
            "app.repositories.taches.list_taches_projet": TACHES_PROJET,
            "app.repositories.taches.get_tache": TACHE_POUR_FICHIERS,
            "app.repositories.taches.get_piece_jointe": PIECE_JOINTE_TACHE,
            "app.repositories.taches.user_est_intervenant": False,
            "app.repositories.taches.set_etat": True,
            "app.repositories.taches.close_tache": 100,
            "app.repositories.posts.list_feed_mes_projets": FEED,
            "app.repositories.posts.list_feed_projet": FEED,
            "app.repositories.posts.get_post": POST_POUR_ACCES,
            "app.repositories.posts.get_piece_jointe": PIECE_JOINTE_POST,
            "app.repositories.utilisateurs.list_actifs": UTILISATEURS_ACTIFS,
            "app.repositories.dailylog.list_projets_pour_dailylog": DAILYLOG_PROJETS,
            "app.repositories.dailylog.list_entrees_jour": DAILYLOG_ENTREES,
            "app.repositories.dailylog.list_lignes_suggerees": DAILYLOG_SUGGESTIONS,
            "app.repositories.dailylog.list_jours_remplis_mois": DAILYLOG_JOURS_REMPLIS,
            "app.repositories.dailylog.jours_manques_recents": [],
            "app.repositories.dailylog.rechercher_projets": [],
            "app.repositories.utilisateurs.list_tous": UTILISATEURS_TOUS,
            "app.repositories.utilisateurs.compter": COMPTE_UTILISATEURS,
            "app.repositories.utilisateurs.rh_deja_attribue": None,
            "app.repositories.utilisateurs.get_utilisateur": UTILISATEUR_PROFIL,
            "app.repositories.utilisateurs.update_profil": None,
            "app.repositories.utilisateurs.set_reset_token": None,
            "app.repositories.utilisateurs.get_mot_de_passe_hash": MOT_DE_PASSE_HASH_PAR_DEFAUT,
            "app.repositories.projets.search": [],
            "app.repositories.notifications.compter_non_lues": 2,
            "app.repositories.notifications.list_notifications": NOTIFICATIONS,
            "app.repositories.notifications.get_notification": NOTIFICATION_UNE,
            "app.repositories.notifications.marquer_lu": None,
            "app.repositories.notifications.marquer_toutes_lues": None,
            "app.repositories.notifications.creer": 201,
            "app.repositories.notifications.creer_pour_plusieurs": None,
        }
        defaults.update(overrides)
        return [patch(target, return_value=value) for target, value in defaults.items()]

    def _get(self, path, **overrides):
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        try:
            return self.client.get(path)
        finally:
            for p in patchers:
                p.stop()

    def test_login_page_renders(self):
        resp = self.client.get("/connexion")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Se connecter", resp.data)

    def test_accueil_renders_with_full_feed(self):
        resp = self._get("/accueil")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("Tour Meridian".encode(), resp.data)
        self.assertIn("Mes tâches".encode(), resp.data)
        # Le mot interdit ne doit jamais apparaître dans le HTML rendu.
        self.assertNotIn("rebond".encode(), resp.data.lower())

    def test_projet_detail_renders_with_tasks_and_feed(self):
        resp = self._get("/projets/1")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("26099X".encode(), resp.data)
        self.assertIn("Plan ferraillage voile R+2".encode(), resp.data)
        self.assertNotIn("rebond".encode(), resp.data.lower())

    def test_post_cloture_tache_affiche_le_tag_choisi_pas_termine(self):
        # Bug corrigé (2026-09-27, retour Fadhel) : le post de clôture
        # affichait toujours la pastille "Terminé" (état de la tâche) au
        # lieu du tag (Envoi/Réponse/Question/Requête) choisi par
        # l'utilisateur à la clôture — voir partials/post_card.html.
        # Rendu via /accueil (fil "Mes projets") : ni les tâches (MES_TACHES,
        # état "bloque") ni les deadlines (DEADLINES, état "en_cours") de
        # cette page ne montrent "Terminé", donc son absence ici pointe
        # précisément vers la pastille du post.
        resp = self._get(
            "/accueil",
            **{"app.repositories.posts.list_feed_mes_projets": [FEED_POST_CLOTURE_TACHE]},
        )
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        body = resp.data.decode()
        self.assertIn("Question", body)
        self.assertNotIn("Terminé", body)

    def test_projets_liste_renders_empty(self):
        resp = self._get("/projets")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])

    def test_projet_detail_renders_for_fresh_projet_without_hours(self):
        """Régression (2026-09-19) : un projet tout juste créé, sans ligne
        DailyLog, a heures_cumulees=None (pas 0) — voir PROJET_SANS_HEURES."""
        resp = self._get(
            "/projets/2",
            **{
                "app.repositories.projets.get_projet": PROJET_SANS_HEURES,
                "app.repositories.taches.list_taches_projet": [TACHE_SANS_HEURES],
            },
        )
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("Projet de test".encode(), resp.data)
        self.assertIn("0 h".encode(), resp.data)

    def test_projets_liste_renders_for_projet_without_hours(self):
        """Même régression que ci-dessus, côté page "Tous les projets"."""
        resp = self._get(
            "/projets",
            **{"app.repositories.projets.list_projets": [PROJET_LISTE_SANS_HEURES]},
        )
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("0 h".encode(), resp.data)

    def test_dailylog_renders(self):
        resp = self._get("/dailylog")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("Daily log".encode(), resp.data)
        # Interface curseur (voir spec) : lignes/catalogue de suggestions
        # injectés en JSON pour le moteur JS, pas de formulaire une-ligne-
        # à-la-fois comme dans l'ancienne version.
        self.assertIn(b'id="dailylog-data"', resp.data)
        self.assertIn("Tour Meridian".encode(), resp.data)
        self.assertIn("The Hub".encode(), resp.data)
        self.assertNotIn(b'name="projet_id"', resp.data)
        # Bug corrigé (2026-09-27, retour Fadhel) : plus d'icône de
        # cadenas visible sur les lignes DailyLog.
        self.assertNotIn("\U0001F512".encode(), resp.data)  # 🔒
        self.assertIn(b'id="sugg-recherche-wrap"', resp.data)

    def test_dailylog_recherche_projets_api(self):
        resp = self._get(
            "/dailylog/recherche-projets?q=hub",
            **{"app.repositories.dailylog.rechercher_projets": [
                {"projet_id": 9, "code": "24001X", "nom": "The Hub", "tache_id": None, "tache_titre": None}
            ]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["resultats"][0]["nom"], "The Hub")

    def test_dailylog_recherche_projets_api_ignore_requete_trop_courte(self):
        resp = self._get("/dailylog/recherche-projets?q=h")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"resultats": []})

    def test_dailylog_with_explicit_date_renders(self):
        resp = self._get("/dailylog?date=2026-09-10")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])

    def test_dailylog_future_date_is_clamped_to_today(self):
        """Régression (2026-09-19, retour Fadhel) : on pouvait remplir le
        DailyLog de demain (ou de n'importe quel jour futur) — la route
        ramène maintenant silencieusement à aujourd'hui."""
        demain = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        resp = self._get("/dailylog?date=" + demain)
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("Aujourd'hui".encode(), resp.data)

    def test_dailylog_next_day_arrow_hidden_on_today(self):
        """Sur "aujourd'hui", plus de flèche vers un jour futur (même
        correctif que ci-dessus, côté template) : le lien vers demain est
        remplacé par un espace réservé désactivé."""
        resp = self._get("/dailylog")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        demain = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        self.assertNotIn(("date=" + demain).encode(), resp.data)
        self.assertIn(b"Pas de saisie pour un jour futur", resp.data)

    # --- Validation des lignes DailyLog à l'enregistrement (POST) —
    # PROMPT_CORRECTIONS.md P1 #10 : avant ce correctif, rien de tout ceci
    # n'était vérifié côté serveur (le curseur JS protège l'usage normal,
    # pas une requête forgée à la main). ---

    def test_dailylog_enregistrer_ignore_les_ids_non_numeriques(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.dailylog.remplacer_jour") as mock_remplacer:
                resp = self.client.post("/dailylog", data={
                    "date": "2026-09-15",
                    "ligne_projet_id": ["abc"],
                    "ligne_tache_id": [""],
                    "ligne_heures": ["4"],
                })
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(mock_remplacer.call_args.args[2], [])
        finally:
            for p in patchers:
                p.stop()

    def test_dailylog_enregistrer_ignore_les_heures_hors_bornes(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.dailylog.remplacer_jour") as mock_remplacer:
                resp = self.client.post("/dailylog", data={
                    "date": "2026-09-15",
                    "ligne_projet_id": ["1", "1"],
                    "ligne_tache_id": ["", ""],
                    "ligne_heures": ["30", "-5"],
                })
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(mock_remplacer.call_args.args[2], [])
        finally:
            for p in patchers:
                p.stop()

    def test_dailylog_enregistrer_ignore_un_projet_non_visible(self):
        self._login()
        patchers = self._patched(**{"app.repositories.projets.user_can_view": False})
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.dailylog.remplacer_jour") as mock_remplacer:
                resp = self.client.post("/dailylog", data={
                    "date": "2026-09-15",
                    "ligne_projet_id": ["1"],
                    "ligne_tache_id": [""],
                    "ligne_heures": ["4"],
                })
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(mock_remplacer.call_args.args[2], [])
        finally:
            for p in patchers:
                p.stop()

    def test_dailylog_enregistrer_ignore_une_tache_dun_autre_projet(self):
        """La tâche indiquée sur une ligne doit appartenir au projet
        indiqué sur cette MÊME ligne."""
        self._login()
        patchers = self._patched(**{
            "app.repositories.taches.get_tache": {**TACHE_POUR_FICHIERS, "projet_id": 99},
        })
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.dailylog.remplacer_jour") as mock_remplacer:
                resp = self.client.post("/dailylog", data={
                    "date": "2026-09-15",
                    "ligne_projet_id": ["1"],
                    "ligne_tache_id": ["5"],
                    "ligne_heures": ["4"],
                })
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(mock_remplacer.call_args.args[2], [])
        finally:
            for p in patchers:
                p.stop()

    def test_dailylog_enregistrer_accepte_une_ligne_valide(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.dailylog.remplacer_jour") as mock_remplacer:
                resp = self.client.post("/dailylog", data={
                    "date": "2026-09-15",
                    "ligne_projet_id": ["1"],
                    "ligne_tache_id": ["5"],
                    "ligne_heures": ["4"],
                })
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(
                mock_remplacer.call_args.args[2],
                [{"projet_id": 1, "tache_id": 5, "heures": 4.0}],
            )
        finally:
            for p in patchers:
                p.stop()

    def test_dailylog_enregistrer_date_invalide_repliee_sur_aujourdhui(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.dailylog.remplacer_jour") as mock_remplacer:
                resp = self.client.post("/dailylog", data={
                    "date": "n-importe-quoi",
                    "ligne_projet_id": [], "ligne_tache_id": [], "ligne_heures": [],
                })
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(mock_remplacer.call_args.args[1], datetime.date.today().isoformat())
        finally:
            for p in patchers:
                p.stop()

    def test_dailylog_recherche_projets_filtre_par_visibilite(self):
        """PROMPT_CORRECTIONS.md P1 #10 : rechercher_projets() doit
        maintenant recevoir l'utilisateur courant (filtre de visibilité)."""
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.dailylog.rechercher_projets", return_value=[]) as mock_recherche:
                self.client.get("/dailylog/recherche-projets?q=hub")
            mock_recherche.assert_called_once_with("hub", user_id=1)
        finally:
            for p in patchers:
                p.stop()

    def test_dailylog_jours_remplis_api(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/dailylog/jours-remplis?annee=2026&mois=9")
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"jours": ["2026-09-11", "2026-09-14"]})

    def test_deadlines_renders_gantt(self):
        resp = self._get("/deadlines")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("Note de calcul EXE".encode(), resp.data)
        self.assertIn(b"Faites d\xc3\xa9filer horizontalement", resp.data)

    def test_projets_liste_with_filters_renders(self):
        resp = self._get("/projets?etat=en_cours&phase=EXE")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])

    def test_projet_creer_form_renders(self):
        resp = self._get("/projets/nouveau")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("Cr\xe9er le projet".encode(), resp.data)

    # --- PROMPT_CORRECTIONS.md P2 #22 : code proposé (propose_code) et
    # validation de la phase à la création d'un projet. ---

    def test_projet_creer_rejette_une_phase_invalide(self):
        """Sans validation, une phase hors phase_enum (schema.sql) faisait
        planter l'INSERT (violation d'ENUM Postgres), remontant comme
        "code déjà utilisé ?" — message trompeur puisque le code n'y est
        pour rien."""
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.projets.create_projet") as mock_create:
                resp = self.client.post(
                    "/projets/nouveau",
                    data={"nom": "Test", "code": "26099X", "phase": "BIDON"},
                    follow_redirects=True,
                )
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("Phase invalide".encode(), resp.data)
        mock_create.assert_not_called()

    def test_api_code_propose_renvoie_un_code_json(self):
        resp = self._get(
            "/projets/code-propose?phase=DCE",
            **{"app.repositories.projets.propose_code": "26004D"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"code": "26004D"})

    def test_api_code_propose_rejette_une_phase_invalide(self):
        resp = self._get("/projets/code-propose?phase=BIDON")
        self.assertEqual(resp.status_code, 400)

    def test_nouveau_post_composer_renders_default_tache(self):
        resp = self._get("/projets/1/nouveau-post")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("Titre de la t\xe2che".encode(), resp.data)
        self.assertIn("Objet de la requ\xeate".encode(), resp.data)
        # Le panneau Information est un aperçu non fonctionnel (étape 2) :
        # présent sur la page, mais sans <form> qui le soumette.
        self.assertIn("\xe9tape 2".encode(), resp.data)

    def test_nouveau_post_composer_preselects_intent_from_query(self):
        resp = self._get("/projets/1/nouveau-post?intent=requete")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn(b'id="intent-requete" name="intent-toggle" class="composer-radio" checked', resp.data)

    def test_nouveau_post_composer_unknown_intent_falls_back_to_tache(self):
        resp = self._get("/projets/1/nouveau-post?intent=n-importe-quoi")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn(b'id="intent-tache" name="intent-toggle" class="composer-radio" checked', resp.data)

    def test_nouveau_post_composer_404_on_unknown_projet(self):
        self._login()
        patchers = self._patched() + [patch("app.repositories.projets.get_projet", return_value=None)]
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/projets/999/nouveau-post")
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 404)

    # --- Contrôle d'accès aux projets (IDOR, PROMPT_CORRECTIONS.md P0 #1) :
    # avant ce correctif, connaître/deviner un id de projet, de tâche, de
    # post ou de pièce jointe suffisait à le consulter/le modifier, même
    # hors de son équipe/affectations — voir user_can_view(). ---

    def test_projet_detail_404_si_non_visible(self):
        resp = self._get("/projets/1", **{"app.repositories.projets.user_can_view": False})
        self.assertEqual(resp.status_code, 404)

    def test_nouveau_post_composer_404_si_projet_non_visible(self):
        resp = self._get("/projets/1/nouveau-post", **{"app.repositories.projets.user_can_view": False})
        self.assertEqual(resp.status_code, 404)

    def test_creer_tache_404_si_projet_non_visible(self):
        self._login()
        patchers = self._patched(**{"app.repositories.projets.user_can_view": False}) + [
            patch("app.repositories.taches.create_tache", return_value=99),
        ]
        for p in patchers:
            p.start()
        try:
            resp = self.client.post("/projets/1/taches", data={"titre": "Tâche test"})
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 404)

    # --- Autres 500 qui devraient être des messages flash
    # (PROMPT_CORRECTIONS.md P1 #11) : creer_tache prenait type_deadline et
    # les dates telles quelles, sans validation — une valeur hors de
    # type_deadline_enum, une date mal formée, ou un intervenant RH
    # (garde-fou trg_check_tache_intervenant_role) faisaient toutes planter
    # la création de tâche en 500 au lieu d'un message clair. ---

    def test_creer_tache_rejette_un_type_deadline_invalide(self):
        self._login()
        patchers = self._patched() + [patch("app.repositories.taches.create_tache", return_value=99)]
        for p in patchers:
            p.start()
        try:
            resp = self.client.post(
                "/projets/1/taches",
                data={"titre": "Tâche test", "type_deadline": "autre_chose"},
            )
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
        self.assertTrue(any("chéance invalide" in msg for _, msg in flashes))

    def test_creer_tache_rejette_une_date_invalide(self):
        self._login()
        patchers = self._patched() + [patch("app.repositories.taches.create_tache", return_value=99)]
        for p in patchers:
            p.start()
        try:
            resp = self.client.post(
                "/projets/1/taches",
                data={"titre": "Tâche test", "date_echeance": "31/12/2026"},
            )
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
        self.assertTrue(any("Date de d\xe9but ou d'\xe9ch\xe9ance invalide" in msg for _, msg in flashes))

    def test_creer_tache_gere_le_garde_fou_intervenant_rh(self):
        """Un intervenant RH (garde-fou trg_check_tache_intervenant_role)
        plantait auparavant la création de tâche en 500 — même logique que
        ajouter_intervenant() sur le garde-fou équivalent côté projet."""
        self._login()
        patchers = self._patched() + [
            patch("app.repositories.taches.create_tache", side_effect=Exception(
                "Un utilisateur avec le rôle RH ne peut pas être intervenant (utilisateur id=9)."
            )),
        ]
        for p in patchers:
            p.start()
        try:
            resp = self.client.post(
                "/projets/1/taches",
                data={"titre": "Tâche test", "intervenants": ["9"]},
            )
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
        self.assertTrue(any("ne peut pas \xeatre intervenant" in msg for _, msg in flashes))

    def test_posts_creer_404_si_projet_non_visible(self):
        self._login()
        patchers = self._patched(**{"app.repositories.projets.user_can_view": False}) + [
            patch("app.repositories.posts.create_post", return_value=101),
        ]
        for p in patchers:
            p.start()
        try:
            resp = self.client.post("/posts", data={"projet_id": "1", "type_code": "envoi", "contenu": "Test"})
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 404)

    def test_posts_creer_rejette_un_rebond_vers_un_autre_projet(self):
        """Un rebond (parent_post_id) doit pointer vers un post du MÊME
        projet — sinon on pourrait relier deux projets sans lien de
        visibilité entre eux."""
        self._login()
        patchers = self._patched(**{
            "app.repositories.posts.get_post": {**POST_POUR_ACCES, "projet_id": 2},
        }) + [
            patch("app.repositories.posts.create_post", return_value=101),
        ]
        for p in patchers:
            p.start()
        try:
            resp = self.client.post(
                "/posts",
                data={"projet_id": "1", "type_code": "envoi", "contenu": "Test", "parent_post_id": "1"},
            )
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 404)

    def test_posts_creer_ignore_un_lien_javascript(self):
        """PROMPT_CORRECTIONS.md P0 #4 : un lien "javascript:..." ne doit
        jamais être enregistré — voir utils.is_lien_valide()."""
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.posts.create_post", return_value=101) as mock_create:
                resp = self.client.post(
                    "/posts",
                    data={
                        "projet_id": "1", "type_code": "envoi", "contenu": "Test",
                        "lien": "javascript:alert(document.cookie)",
                    },
                )
            self.assertEqual(resp.status_code, 302)
            self.assertIsNone(mock_create.call_args.kwargs["lien"])
        finally:
            for p in patchers:
                p.stop()

    def test_posts_creer_accepte_un_lien_unc(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.posts.create_post", return_value=101) as mock_create:
                resp = self.client.post(
                    "/posts",
                    data={
                        "projet_id": "1", "type_code": "envoi", "contenu": "Test",
                        "lien": "\\\\NAS\\Projets\\26099X\\",
                    },
                )
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(mock_create.call_args.kwargs["lien"], "\\\\NAS\\Projets\\26099X\\")
        finally:
            for p in patchers:
                p.stop()

    def test_post_card_ne_rend_pas_un_lien_javascript(self):
        """Défense en profondeur (PROMPT_CORRECTIONS.md P0 #4) : même si un
        post existant en base avait un lien invalide, le template ne doit
        jamais produire un href="javascript:...". """
        post_avec_lien_invalide = {**FEED_POST_MANUEL, "lien": "javascript:alert(1)"}
        resp = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [post_avec_lien_invalide]})
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertNotIn(b"javascript:alert", resp.data)

    def test_post_card_reaction_pointe_vers_retirer_quand_deja_reagi(self):
        """PROMPT_CORRECTIONS.md P2 #20 : sans ce correctif, le bouton
        réaction postait toujours sur posts.reagir (upsert) — impossible de
        retirer sa réaction une fois posée."""
        post_avec_reaction = {**FEED_POST_MANUEL, "ma_reaction": "pouce"}
        resp = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [post_avec_reaction]})
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn(f'action="/posts/{post_avec_reaction["id"]}/reagir/supprimer"'.encode(), resp.data)

    def test_post_card_reaction_pointe_vers_ajouter_quand_pas_encore_reagi(self):
        resp = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [FEED_POST_MANUEL]})
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn(f'action="/posts/{FEED_POST_MANUEL["id"]}/reagir"'.encode(), resp.data)
        self.assertNotIn(f'/posts/{FEED_POST_MANUEL["id"]}/reagir/supprimer'.encode(), resp.data)

    def test_posts_reagir_404_si_post_non_visible(self):
        self._login()
        patchers = self._patched(**{"app.repositories.projets.user_can_view": False})
        for p in patchers:
            p.start()
        try:
            resp = self.client.post("/posts/1/reagir", data={"reaction_code": "pouce"})
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 404)

    def test_posts_commenter_404_si_post_inexistant(self):
        self._login()
        patchers = self._patched(**{"app.repositories.posts.get_post": None})
        for p in patchers:
            p.start()
        try:
            resp = self.client.post("/posts/999/commenter", data={"contenu": "Test"})
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 404)

    def test_fichiers_download_tache_404_si_projet_non_visible(self):
        self._login()
        patchers = self._patched(**{"app.repositories.projets.user_can_view": False})
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/fichiers/taches/1")
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 404)

    def test_fichiers_download_tache_sert_le_fichier_si_visible(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.routes.fichiers.send_from_directory", return_value="ok") as mock_send:
                resp = self.client.get("/fichiers/taches/1")
            mock_send.assert_called_once()
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 200)

    def test_fichiers_download_post_404_si_projet_non_visible(self):
        self._login()
        patchers = self._patched(**{"app.repositories.projets.user_can_view": False})
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/fichiers/posts/1")
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 404)

    def test_fichiers_upload_tache_404_si_tache_inexistante_ou_non_visible(self):
        self._login()
        patchers = self._patched(**{"app.repositories.taches.get_tache": None})
        for p in patchers:
            p.start()
        try:
            resp = self.client.post(
                "/fichiers/taches/999/upload",
                data={"fichier": (io.BytesIO(b"contenu bidon"), "note.pdf")},
                content_type="multipart/form-data",
            )
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 404)

    def test_fichiers_upload_post_404_si_post_inexistant(self):
        self._login()
        patchers = self._patched(**{"app.repositories.posts.get_post": None})
        for p in patchers:
            p.start()
        try:
            resp = self.client.post(
                "/fichiers/posts/999/upload",
                data={"fichier": (io.BytesIO(b"contenu bidon"), "note.pdf")},
                content_type="multipart/form-data",
            )
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 404)

    # --- Autorisation sur les actions de tâche (PROMPT_CORRECTIONS.md
    # P0 #2) : avant ce correctif, le menu d'action de la tâche était
    # affiché à tout le monde dans projet_detail.html sans aucun contrôle
    # côté serveur — n'importe quel utilisateur connecté pouvait changer
    # l'état ou clôturer n'importe quelle tâche. ---

    def test_changer_etat_tache_refuse_si_ni_gestionnaire_ni_intervenant(self):
        self._login()
        patchers = self._patched(**{
            "app.repositories.projets.user_can_manage": False,
            "app.repositories.taches.user_est_intervenant": False,
        })
        for p in patchers:
            p.start()
        try:
            resp = self.client.post("/projets/1/taches/5/etat", data={"etat": "verifie"}, follow_redirects=False)
        finally:
            for p in patchers:
                p.stop()
        # Redirection (pas de crash), avec un message d'erreur — jamais
        # l'état effectivement modifié.
        self.assertEqual(resp.status_code, 302)

    def test_changer_etat_tache_autorise_un_intervenant_de_la_tache(self):
        """Un intervenant affecté à la tâche (mais ni chef ni co-chef) doit
        pouvoir changer son état — pas seulement le chef/co-chef."""
        self._login()
        patchers = self._patched(**{
            "app.repositories.projets.user_can_manage": False,
            "app.repositories.taches.user_est_intervenant": True,
        }) + [patch("app.repositories.taches.set_etat", return_value=True)]
        for p in patchers:
            p.start()
        try:
            resp = self.client.post("/projets/1/taches/5/etat", data={"etat": "verifie"}, follow_redirects=False)
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/projets/1", resp.headers["Location"])

    def test_changer_etat_tache_introuvable_ne_plante_pas(self):
        """set_etat() renvoie False quand la tâche n'appartient pas à ce
        projet (ou n'existe pas) — la route doit rediriger avec un message,
        jamais planter."""
        self._login()
        patchers = self._patched(**{"app.repositories.taches.set_etat": False})
        for p in patchers:
            p.start()
        try:
            resp = self.client.post("/projets/1/taches/999/etat", data={"etat": "verifie"}, follow_redirects=False)
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 302)

    def test_cloturer_tache_type_code_invalide_ne_plante_pas(self):
        """Un type_code hors de la liste valide faisait planter la clôture
        en 500 (violation de contrainte FK sur post.type_code) — doit
        maintenant juste afficher un message et rediriger."""
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            resp = self.client.post(
                "/projets/1/taches/5/cloturer", data={"type_code": "n-importe-quoi"}, follow_redirects=False,
            )
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 302)

    def test_cloturer_tache_deja_cloturee_ne_plante_pas(self):
        """close_tache() renvoie None quand la tâche est déjà clôturée (ou
        introuvable sur ce projet) — jamais d'exception non gérée."""
        self._login()
        patchers = self._patched(**{"app.repositories.taches.close_tache": None})
        for p in patchers:
            p.start()
        try:
            resp = self.client.post(
                "/projets/1/taches/5/cloturer", data={"type_code": "envoi"}, follow_redirects=False,
            )
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 302)

    def test_utilisateurs_liste_renders(self):
        resp = self._get("/utilisateurs")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("Foulen Chedly".encode(), resp.data)
        self.assertIn("Amine Ben Salah".encode(), resp.data)
        self.assertIn("Nouvel utilisateur".encode(), resp.data)

    def test_utilisateurs_liste_with_filters_renders(self):
        resp = self._get("/utilisateurs?q=amine&equipe_code=MIDGARD&role=intervenant&actif=inactifs")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])

    def test_utilisateur_creer_form_renders(self):
        resp = self._get("/utilisateurs/nouveau")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("Cr\xe9er l'utilisateur".encode(), resp.data)
        self.assertIn("Compte actif".encode(), resp.data)

    def test_utilisateur_creer_equipe_option_vide_selectionnee_par_defaut(self):
        """PROMPT_CORRECTIONS.md P1 #12 : sans option vide, le <select>
        Équipe affichait "Midgard" (première option) sans que personne ne
        l'ait choisi, et cette valeur implicite était soumise comme un choix
        explicite — un nouvel utilisateur pouvait se retrouver rattaché à
        Midgard par défaut."""
        resp = self._get("/utilisateurs/nouveau")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'<option value="" selected>', resp.data)

    def test_utilisateurs_pages_refused_to_intervenant(self):
        """role_required('admin', 'rh') doit rediriger un simple intervenant
        (voir auth.py) — accès réservé, pas de page Utilisateurs pour lui."""
        self._login()
        patchers = self._patched() + [
            patch("app.auth.get_user_by_id", return_value={**USER, "role": "intervenant"}),
        ]
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/utilisateurs", follow_redirects=False)
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accueil", resp.headers["Location"])

    def test_index_redirects_when_logged_in(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/", follow_redirects=False)
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accueil", resp.headers["Location"])

    def test_write_routes_redirect_without_crashing(self):
        """Vérifie le câblage (url_for, blueprints, formulaires) des routes
        d'écriture — la logique SQL elle-même a été validée séparément."""
        self._login()
        patchers = self._patched() + [
            patch("app.repositories.projets.user_can_manage", return_value=True),
            patch("app.repositories.taches.create_tache", return_value=99),
            patch("app.repositories.taches.set_etat", return_value=None),
            patch("app.repositories.taches.close_tache", return_value=100),
            patch("app.repositories.projets.add_intervenant", return_value=None),
            patch("app.repositories.posts.create_post", return_value=101),
            patch("app.repositories.posts.react", return_value=None),
            patch("app.repositories.posts.add_comment", return_value=102),
            patch("app.repositories.dailylog.remplacer_jour", return_value=None),
            patch("app.repositories.projets.create_projet", return_value=42),
            patch("app.routes.fichiers.save_upload", return_value=("note.pdf", "taches/5/xyz.pdf")),
            patch("app.routes.posts.save_upload", return_value=("plan.pdf", "posts/101/xyz.pdf")),
            patch("app.repositories.taches.add_piece_jointe", return_value=1),
            patch("app.repositories.posts.add_piece_jointe", return_value=1),
            patch("app.repositories.utilisateurs.create_utilisateur", return_value=42),
            patch("app.repositories.utilisateurs.toggle_actif", return_value=None),
        ]
        for p in patchers:
            p.start()
        try:
            r1 = self.client.post("/projets/1/taches", data={"titre": "Nouvelle tâche test"})
            self.assertEqual(r1.status_code, 302)

            r2 = self.client.post("/projets/1/taches/5/etat", data={"etat": "verifie"})
            self.assertEqual(r2.status_code, 302)

            r3 = self.client.post("/projets/1/taches/5/cloturer", data={"type_code": "envoi"})
            self.assertEqual(r3.status_code, 302)

            r4 = self.client.post("/projets/1/intervenants", data={"utilisateur_id": "3"})
            self.assertEqual(r4.status_code, 302)

            r5 = self.client.post("/posts", data={"projet_id": "1", "type_code": "envoi", "contenu": "Test"})
            self.assertEqual(r5.status_code, 302)

            # Composeur "Nouveau post", panneau Requête : objet + description
            # combinés en contenu, personnes taguées, lien et pièce jointe
            # en une seule soumission (voir posts.creer et post_mention).
            r5b = self.client.post(
                "/posts",
                data={
                    "projet_id": "1", "type_code": "requete",
                    "objet": "Demande de plans mis à jour", "contenu": "Merci de renvoyer la dernière version.",
                    "mentions": ["1", "3"], "lien": "\\\\NAS\\Projets\\26099X\\",
                    "fichier": (io.BytesIO(b"contenu bidon"), "plan.pdf"),
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(r5b.status_code, 302, r5b.data[:2000])

            r6 = self.client.post("/posts/1/reagir", data={"reaction_code": "pouce"})
            self.assertEqual(r6.status_code, 302)

            r7 = self.client.post("/posts/1/commenter", data={"contenu": "Un commentaire"})
            self.assertEqual(r7.status_code, 302)

            r8 = self.client.post("/dailylog", data={
                "date": "2026-09-15",
                "ligne_projet_id": ["1", "2"],
                "ligne_tache_id": ["5", ""],
                "ligne_heures": ["4", "4"],
            })
            self.assertEqual(r8.status_code, 302)

            r9 = self.client.post("/projets/nouveau", data={
                "nom": "Nouveau Projet Test", "code": "26099X", "phase": "EXE", "lots": ["GO"],
            })
            self.assertEqual(r9.status_code, 302, r9.data[:2000])

            r10 = self.client.post(
                "/fichiers/taches/5/upload",
                data={"fichier": (io.BytesIO(b"contenu bidon"), "note.pdf")},
                content_type="multipart/form-data",
            )
            self.assertEqual(r10.status_code, 302, r10.data[:2000])

            r11 = self.client.post(
                "/fichiers/posts/1/upload",
                data={"fichier": (io.BytesIO(b"contenu bidon"), "note.pdf")},
                content_type="multipart/form-data",
            )
            self.assertEqual(r11.status_code, 302, r11.data[:2000])

            r12 = self.client.post("/utilisateurs/nouveau", data={
                "prenom": "Wael", "nom": "Rekik", "email": "w.rekik@midgard.tn",
                "role": "intervenant", "equipe_code": "MIDGARD", "actif": "on",
            })
            self.assertEqual(r12.status_code, 302, r12.data[:2000])

            r13 = self.client.post("/utilisateurs/5/toggle-actif", data={
                "q": "", "equipe_code": "", "role": "", "actif": "",
            })
            self.assertEqual(r13.status_code, 302, r13.data[:2000])
        finally:
            for p in patchers:
                p.stop()

    def test_topbar_shows_unread_notifications_badge(self):
        resp = self._get("/accueil")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn(b'class="iconbtn-badge"', resp.data)
        self.assertIn(b">2<", resp.data)

    def test_notifications_liste_renders(self):
        resp = self._get("/notifications")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("mentionné dans un post".encode(), resp.data)
        self.assertIn("Rappel DailyLog".encode(), resp.data)

    def test_notifications_ouvrir_marks_read_and_redirects_to_projet(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.notifications.marquer_lu") as mock_marquer:
                resp = self.client.get("/notifications/10/ouvrir", follow_redirects=False)
                mock_marquer.assert_called_once_with(10, 1)
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/projets/1", resp.headers["Location"])

    def test_notifications_ouvrir_404_on_unknown_notification(self):
        self._login()
        patchers = self._patched() + [
            patch("app.repositories.notifications.get_notification", return_value=None),
        ]
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/notifications/999/ouvrir")
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 404)

    def test_notifications_marquer_toutes_lues_redirects(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            resp = self.client.post("/notifications/marquer-toutes-lues", follow_redirects=False)
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/notifications", resp.headers["Location"])

    def test_login_success_triggers_dailylog_reminder_check(self):
        """Câblage réel de la route /connexion (pas de _get/_login raccourci
        ici, on veut exercer le vrai POST) : vérifie que le rappel DailyLog
        est bien invoqué après une connexion réussie. La logique du rappel
        elle-même (weekend, doublon) est testée séparément ci-dessous, en
        appelant _verifier_rappel_dailylog directement."""
        user_row = {**USER, "mot_de_passe_hash": "hash-bidon"}
        with patch("app.auth.get_user_by_email", return_value=user_row), \
             patch("app.auth.verify_password", return_value=True), \
             patch("app.auth._verifier_rappel_dailylog") as mock_rappel, \
             patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.repositories.notifications.compter_non_lues", return_value=0):
            resp = self.client.post(
                "/connexion",
                data={"email": "fadhel@midgard.tn", "password": "peu-importe"},
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 302, resp.data[:2000])
        mock_rappel.assert_called_once_with(1)

    def test_login_next_ouverture_de_redirection_refusee(self):
        """PROMPT_CORRECTIONS.md P0 #5 : ?next=//evil.tld ne doit jamais
        rediriger hors du site après une connexion réussie."""
        user_row = {**USER, "mot_de_passe_hash": "hash-bidon"}
        with patch("app.auth.get_user_by_email", return_value=user_row), \
             patch("app.auth.verify_password", return_value=True), \
             patch("app.auth._verifier_rappel_dailylog"), \
             patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.repositories.notifications.compter_non_lues", return_value=0):
            resp = self.client.post(
                "/connexion?next=//evil.tld",
                data={"email": "fadhel@midgard.tn", "password": "peu-importe"},
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accueil", resp.headers["Location"])
        self.assertNotIn("evil.tld", resp.headers["Location"])

    def test_login_next_chemin_interne_est_respecte(self):
        user_row = {**USER, "mot_de_passe_hash": "hash-bidon"}
        with patch("app.auth.get_user_by_email", return_value=user_row), \
             patch("app.auth.verify_password", return_value=True), \
             patch("app.auth._verifier_rappel_dailylog"), \
             patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.repositories.notifications.compter_non_lues", return_value=0):
            resp = self.client.post(
                "/connexion?next=/projets/1",
                data={"email": "fadhel@midgard.tn", "password": "peu-importe"},
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/projets/1", resp.headers["Location"])

    def test_posts_safe_redirect_refuse_une_ouverture_de_redirection(self):
        self._login()
        patchers = self._patched(**{
            "app.repositories.posts.create_post": 101,
        })
        for p in patchers:
            p.start()
        try:
            resp = self.client.post(
                "/posts",
                data={
                    "projet_id": "1", "type_code": "envoi", "contenu": "Test",
                    "next": "//evil.tld",
                },
                follow_redirects=False,
            )
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("evil.tld", resp.headers["Location"])

    def test_fichiers_safe_redirect_refuse_une_ouverture_de_redirection(self):
        self._login()
        patchers = self._patched(**{
            "app.repositories.taches.add_piece_jointe": 1,
        }) + [patch("app.routes.fichiers.save_upload", return_value=("note.pdf", "taches/5/xyz.pdf"))]
        for p in patchers:
            p.start()
        try:
            resp = self.client.post(
                "/fichiers/taches/5/upload",
                data={
                    "fichier": (io.BytesIO(b"contenu bidon"), "note.pdf"),
                    "next": "/\\evil.tld",
                },
                content_type="multipart/form-data",
                follow_redirects=False,
            )
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("evil.tld", resp.headers["Location"])

    def test_login_echoue_conserve_email_saisi(self):
        """Retour Fadhel (2026-09-20) : après un mot de passe incorrect, le
        champ e-mail ne doit plus être vidé — on renvoie la valeur saisie
        dans l'attribut value du champ."""
        with patch("app.auth.get_user_by_email", return_value=None), \
             patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.repositories.securite.enregistrer_tentative"):
            resp = self.client.post(
                "/connexion",
                data={"email": "fadhel@midgard.tn", "password": "mauvais"},
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'value="fadhel@midgard.tn"', resp.data)

    def test_login_echoue_affiche_un_popup_flottant_pas_un_bandeau(self):
        """Retour Fadhel (2026-09-20) : "Email ou mot de passe incorrect" ne
        doit plus pousser toute la page (l'ancien .flash-wrap-login, dans le
        flux normal) — même popup flottant (.flash-wrap, position:fixed)
        que partout ailleurs dans l'appli."""
        with patch("app.auth.get_user_by_email", return_value=None), \
             patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.repositories.securite.enregistrer_tentative"):
            resp = self.client.post(
                "/connexion",
                data={"email": "fadhel@midgard.tn", "password": "mauvais"},
                follow_redirects=False,
            )
        body = resp.data.decode()
        self.assertIn("Email ou mot de passe incorrect", body)
        self.assertIn('class="flash-wrap"', body)
        self.assertNotIn("flash-wrap-login", body)

    # --- Photo de profil (retour Fadhel, 2026-09-20) : "mettre une image
    # au lieu du diminutif du nom prénom", à la création et à la
    # modification. ---

    def test_creation_utilisateur_avec_photo_de_profil(self):
        self._login()
        patchers = self._patched(**{
            "app.repositories.utilisateurs.create_utilisateur": 42,
            "app.repositories.utilisateurs.toggle_actif": None,
        })
        for p in patchers:
            p.start()
        try:
            with patch("app.routes.utilisateurs.save_upload", return_value=("photo.png", "avatars/42/xyz.png")) as mock_save, \
                 patch("app.repositories.utilisateurs.set_avatar") as mock_set_avatar:
                resp = self.client.post(
                    "/utilisateurs/nouveau",
                    data={
                        "prenom": "Wael", "nom": "Rekik", "email": "w.rekik@midgard.tn",
                        "role": "intervenant", "equipe_code": "MIDGARD", "actif": "on",
                        "avatar": (io.BytesIO(b"contenu bidon"), "photo.png"),
                    },
                    content_type="multipart/form-data",
                )
            self.assertEqual(resp.status_code, 302, resp.data[:2000])
            mock_save.assert_called_once()
            self.assertEqual(mock_save.call_args.args[1], "avatars/42")
            mock_set_avatar.assert_called_once_with(42, "avatars/42/xyz.png", 1)
        finally:
            for p in patchers:
                p.stop()

    def test_creation_utilisateur_rejette_une_photo_non_image(self):
        """Un .pdf (ou tout format hors jpg/png/gif/webp) est ignoré avec un
        message clair — ça ne doit jamais faire échouer le reste de la
        création du compte."""
        self._login()
        patchers = self._patched(**{
            "app.repositories.utilisateurs.create_utilisateur": 42,
            "app.repositories.utilisateurs.toggle_actif": None,
        })
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.utilisateurs.set_avatar") as mock_set_avatar:
                resp = self.client.post(
                    "/utilisateurs/nouveau",
                    data={
                        "prenom": "Wael", "nom": "Rekik", "email": "w.rekik@midgard.tn",
                        "role": "intervenant", "equipe_code": "MIDGARD", "actif": "on",
                        "avatar": (io.BytesIO(b"contenu bidon"), "carte.pdf"),
                    },
                    content_type="multipart/form-data",
                )
            self.assertEqual(resp.status_code, 302, resp.data[:2000])
            mock_set_avatar.assert_not_called()
        finally:
            for p in patchers:
                p.stop()

    # --- Autres 500 qui devraient être des messages flash
    # (PROMPT_CORRECTIONS.md P1 #11), suite : create_utilisateur() posait
    # toujours actif=true à l'INSERT puis, pour un compte censé naître
    # inactif, appelait toggle_actif() juste après — deux transactions
    # séparées, avec une fenêtre où le compte existait réellement actif en
    # base, et où idx_utilisateur_rh_singleton pouvait se déclencher à tort
    # pour un compte RH qu'on voulait justement créer inactif. ---

    def test_creation_utilisateur_inactif_passe_actif_directement_a_linsert(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.utilisateurs.create_utilisateur", return_value=42) as mock_create, \
                 patch("app.repositories.utilisateurs.toggle_actif") as mock_toggle:
                resp = self.client.post(
                    "/utilisateurs/nouveau",
                    data={
                        "prenom": "Wael", "nom": "Rekik", "email": "w.rekik@midgard.tn",
                        "role": "intervenant", "equipe_code": "MIDGARD",
                        # Pas de "actif": "on" → compte voulu inactif.
                    },
                )
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 302, resp.data[:2000])
        self.assertFalse(mock_create.call_args.kwargs["actif"])
        # Ancienne façon de faire : un second appel séparé à toggle_actif().
        # Le nouvel INSERT pose déjà actif=false, plus besoin de ce détour.
        mock_toggle.assert_not_called()

    def test_toggle_actif_gere_le_garde_fou_rh_singleton(self):
        """Réactiver un compte RH alors qu'un autre est déjà actif
        (idx_utilisateur_rh_singleton) plantait auparavant en 500 — même
        message clair que pour creer()/fiche() sur la même contrainte."""
        self._login()
        patchers = self._patched() + [
            patch(
                "app.repositories.utilisateurs.toggle_actif",
                side_effect=Exception('duplicate key value violates unique constraint "idx_utilisateur_rh_singleton"'),
            ),
        ]
        for p in patchers:
            p.start()
        try:
            resp = self.client.post("/utilisateurs/2/toggle-actif", data={})
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
        self.assertTrue(any("compte RH actif" in msg for _, msg in flashes))

    def test_mon_profil_post_avec_photo_appelle_set_avatar(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.utilisateurs.update_profil"), \
                 patch("app.routes.utilisateurs.save_upload", return_value=("moi.jpg", "avatars/1/abc.jpg")), \
                 patch("app.repositories.utilisateurs.set_avatar") as mock_set_avatar:
                resp = self.client.post(
                    "/utilisateurs/moi",
                    data={
                        "telephone": "20 000 000", "poste": "Chef de projet", "adresse": "Tunis",
                        "avatar": (io.BytesIO(b"contenu bidon"), "moi.jpg"),
                    },
                    content_type="multipart/form-data",
                )
            self.assertEqual(resp.status_code, 302)
            mock_set_avatar.assert_called_once_with(1, "avatars/1/abc.jpg", 1)
        finally:
            for p in patchers:
                p.stop()

    def test_mon_profil_post_sans_photo_ne_touche_pas_avatar(self):
        """Soumettre le formulaire "Infos perso" sans nouveau fichier ne
        doit jamais effacer la photo déjà en place."""
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.utilisateurs.update_profil"), \
                 patch("app.repositories.utilisateurs.set_avatar") as mock_set_avatar:
                resp = self.client.post(
                    "/utilisateurs/moi",
                    data={"telephone": "20 000 000", "poste": "Chef de projet", "adresse": "Tunis"},
                )
            self.assertEqual(resp.status_code, 302)
            mock_set_avatar.assert_not_called()
        finally:
            for p in patchers:
                p.stop()

    def test_route_avatar_sert_le_fichier_si_present(self):
        self._login()
        patchers = self._patched(**{
            "app.repositories.utilisateurs.get_utilisateur": {**UTILISATEUR_PROFIL, "avatar_chemin": "avatars/1/abc.png"},
        })
        for p in patchers:
            p.start()
        try:
            with patch("app.routes.fichiers.send_from_directory", return_value="ok") as mock_send:
                resp = self.client.get("/fichiers/avatars/1")
            mock_send.assert_called_once()
            self.assertEqual(mock_send.call_args.args[1], "avatars/1/abc.png")
        finally:
            for p in patchers:
                p.stop()

    def test_route_avatar_404_si_absent(self):
        self._login()
        patchers = self._patched(**{
            "app.repositories.utilisateurs.get_utilisateur": {**UTILISATEUR_PROFIL, "avatar_chemin": None},
        })
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/fichiers/avatars/1")
            self.assertEqual(resp.status_code, 404)
        finally:
            for p in patchers:
                p.stop()

    def test_fil_affiche_la_photo_de_profil_de_lauteur_si_presente(self):
        post_avec_avatar = {**FEED_POST_MANUEL, "auteur_avatar_chemin": "avatars/2/xyz.png"}
        resp = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [post_avec_avatar]})
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn(b'src="/fichiers/avatars/2"', resp.data)

    def test_fil_retombe_sur_les_initiales_sans_photo_de_profil(self):
        resp = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [FEED_POST_MANUEL]})
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertNotIn(b"/fichiers/avatars/", resp.data)

    # --- Deuxième vague de retours de Fadhel (2026-09-19, KAiros_Claude1.docx) :
    # bannière Deadlines pleine largeur sur l'accueil, tri de "Mes projets"
    # par échéance, carte Daily log rouge en cas de retard, commentaires/
    # réactions sur les posts, rebond enrichi (Tâche/Info/Requête), filtres
    # à puces + colonne Deadlines sur "Tous les projets", et page "Infos perso".

    def test_jours_manques_recents_ignore_weekends_et_jours_deja_remplis(self):
        from app.repositories import dailylog as dailylog_repo

        aujourdhui = datetime.date(2026, 9, 21)
        fenetre = [aujourdhui - datetime.timedelta(days=i) for i in range(1, 6)]
        jours_ouvres = [j for j in fenetre if j.weekday() < 5]
        deja_rempli = jours_ouvres[:1]
        attendu = sorted(j for j in jours_ouvres if j not in deja_rempli)

        with patch("app.repositories.dailylog.db.query_all", return_value=[{"date": j} for j in deja_rempli]):
            resultat = dailylog_repo.jours_manques_recents(user_id=1, aujourdhui=aujourdhui, fenetre_jours=5)

        self.assertEqual(resultat, attendu)
        self.assertTrue(all(j.weekday() < 5 for j in resultat))

    def test_accueil_bandeau_deadlines_pleine_largeur(self):
        resp = self._get("/accueil")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"deadline-banner", resp.data)
        self.assertIn(b'href="/deadlines"', resp.data)

    def test_accueil_dailylog_cta_verte_par_defaut(self):
        resp = self._get("/accueil")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b"card-cta-alert", resp.data)

    def test_accueil_dailylog_cta_rouge_si_jours_manques(self):
        resp = self._get("/accueil", **{
            "app.repositories.dailylog.jours_manques_recents": [datetime.date(2026, 9, 17)],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"card-cta-alert", resp.data)

    def test_accueil_trie_mes_projets_par_echeance_la_plus_proche(self):
        deadlines_multi = [
            {"id": 1, "titre": "Rendu tardif", "etat": "en_cours", "date_echeance": datetime.date(2026, 9, 25),
             "type_deadline": "rendu_client", "projet_id": 2, "projet_code": "25014X", "projet_nom": "Résidence Les Oliviers"},
            {"id": 2, "titre": "Rendu proche", "etat": "en_cours", "date_echeance": datetime.date(2026, 9, 18),
             "type_deadline": "rendu_client", "projet_id": 1, "projet_code": "26099X", "projet_nom": "Tour Meridian"},
        ]
        resp = self._get("/accueil", **{"app.repositories.taches.list_deadlines": deadlines_multi})
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        # On isole la carte "Mes projets" (pas la bannière Deadlines pleine
        # largeur, qui suit déjà l'ordre des échéances par construction)
        # pour vérifier spécifiquement son tri. La carte "Deadlines" en
        # colonne gauche a été supprimée (2026-09-27, doublon de la
        # bannière) — la carte suivante dans la colonne est "Daily log".
        debut = body.index("Mes projets")
        fin = body.index("Daily log", debut)
        section_mes_projets = body[debut:fin]
        # Tour Meridian (échéance le 18) doit apparaître avant Résidence Les
        # Oliviers (échéance le 25).
        pos_meridian = section_mes_projets.index("Tour Meridian")
        pos_oliviers = section_mes_projets.index("Résidence Les Oliviers")
        self.assertLess(pos_meridian, pos_oliviers)

    def test_post_card_affiche_et_permet_dajouter_des_commentaires(self):
        post_avec_commentaire = {
            **FEED_POST_MANUEL,
            "commentaires": [{
                "id": 1, "contenu": "Bien reçu, merci.", "created_at": datetime.datetime(2026, 9, 15, 11, 0),
                "auteur_id": 3, "auteur_prenom": "Omar", "auteur_nom": "Aziz",
            }],
            "reacteurs": [{"prenom": "Omar", "nom": "Aziz"}],
        }
        resp = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [post_avec_commentaire]})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Bien reçu, merci.".encode(), resp.data)
        self.assertIn("Écrire un commentaire".encode(), resp.data)

    def test_post_card_propose_tache_info_requete_lies_au_rebond(self):
        """Le rebond ouvre la fenêtre flottante partagée (retour Fadhel,
        2026-09-19) — un rebond est lui-même un post (Tâche/Info/Requête),
        jamais un lien vers une page séparée ni un champ texte libre."""
        resp = self._get("/accueil")
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        self.assertIn("+ Tâche", body)
        self.assertIn("+ Info", body)
        self.assertIn("+ Requête", body)
        self.assertIn('data-open-post-dialog', body)
        self.assertIn('data-parent-post-id="1"', body)
        # Le rebond n'est plus un lien vers une page séparée.
        self.assertNotIn('href="/projets/1/nouveau-post', body)
        # Plus de mini-formulaire "Répondre à ce post…" en texte libre.
        self.assertNotIn("Répondre à ce post", body)

    def test_projets_liste_applique_les_defauts_sans_filtres_actifs(self):
        resp = self._get("/projets", **{"app.repositories.projets.list_projets": [PROJET_LISTE_SANS_HEURES]})
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        self.assertIn('value="en_cours" selected', body)
        self.assertIn('value="bloque" selected', body)
        self.assertNotIn('value="termine" selected', body)
        # Chef de projet par défaut = utilisateur connecté (id 1, "Foulen Chedly")
        self.assertIn('value="1" selected', body)
        self.assertIn("Deadlines", body)

    def test_projets_liste_respecte_un_filtre_explicitement_vide(self):
        # filtres_actifs=1 sans "etat" = l'utilisateur a décoché tous les
        # états volontairement : on ne doit pas revenir aux valeurs par défaut.
        resp = self._get("/projets?filtres_actifs=1", **{"app.repositories.projets.list_projets": [PROJET_LISTE_SANS_HEURES]})
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        self.assertNotIn('value="en_cours" selected', body)

    def test_projets_liste_filtre_chef_de_projet_utilise_les_vrais_chefs(self):
        # Bug corrigé (2026-09-27, retour Fadhel) : le filtre listait tout
        # le monde (UTILISATEURS_ACTIFS) au lieu des seuls chefs de projet
        # réels (CHEFS_DE_PROJET) — voir projets.list_chefs_de_projet().
        resp = self._get("/projets", **{"app.repositories.projets.list_projets": [PROJET_LISTE_SANS_HEURES]})
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        self.assertIn("Sana Trabelsi", body)
        self.assertNotIn("Omar Aziz", body)

    def test_projets_liste_ajax_ne_renvoie_que_le_tableau(self):
        # Retour Fadhel (2026-09-27) : la recherche/les filtres sur "Tous
        # les projets" ne doivent rafraîchir que le tableau, pas toute la
        # page — voir la branche X-Requested-With de routes/projets.liste
        # et partials/projets_tableau.html.
        self._login()
        patchers = self._patched(**{"app.repositories.projets.list_projets": [PROJET_LISTE_SANS_HEURES]})
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/projets", headers={"X-Requested-With": "XMLHttpRequest"})
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        self.assertIn("Projet de test", body)
        self.assertIn("1 projet", body)
        # Ne doit pas contenir la mise en page complète (topbar, filtres…).
        self.assertNotIn("Tous les projets", body)
        self.assertNotIn("filtres-projets", body)

    def test_mon_profil_affiche_les_infos_et_la_semaine_derniere(self):
        resp = self._get("/utilisateurs/moi")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Infos perso".encode(), resp.data)
        self.assertIn(UTILISATEUR_PROFIL["email"].encode(), resp.data)
        self.assertIn("Daily log".encode(), resp.data)

    def test_mon_profil_post_met_a_jour_le_profil(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.utilisateurs.update_profil") as mock_update:
                resp = self.client.post(
                    "/utilisateurs/moi",
                    data={"telephone": "20 000 000", "poste": "Chef de projet", "adresse": "Tunis"},
                )
            self.assertEqual(resp.status_code, 302)
            mock_update.assert_called_once()
            self.assertEqual(mock_update.call_args.kwargs.get("poste"), "Chef de projet")
            self.assertEqual(mock_update.call_args.kwargs.get("adresse"), "Tunis")
        finally:
            for p in patchers:
                p.stop()

    def test_topbar_avatar_mene_a_mon_profil(self):
        resp = self._get("/accueil")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'href="/utilisateurs/moi"', resp.data)

    # --- Troisième vague de retours de Fadhel (2026-09-19, tests réels sur
    # l'appli déployée) : alignement topbar/colonnes, mini-Gantt de la
    # bannière d'accueil, position du menu de résultats de recherche,
    # session persistante, et le vrai bug SQL derrière "la page projet ne
    # fonctionne pas" (voir app/repositories/projets.py:list_projets).

    def test_topbar_contenu_aligne_sur_les_colonnes(self):
        """Le logo/la recherche/les icônes doivent être dans un conteneur
        limité à 1360px comme .page-body / .subbar-inner, pas étalés sur
        toute la largeur de la fenêtre (flèches rouges de Fadhel)."""
        resp = self._get("/accueil")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'class="topbar-inner"', resp.data)

    def test_recherche_resultats_ancres_sur_la_boite_de_recherche(self):
        """Le menu de résultats doit être positionné par rapport à
        .topbar-search-box (largeur max 420px, la boîte visible), pas
        .topbar-search (flex:1, toute la largeur restante de la topbar) —
        sinon le menu déborde et est mal centré (retour Fadhel)."""
        resp = self._get("/accueil")
        body = resp.data.decode()
        boite = body[body.index('class="topbar-search-box"'):body.index("recherche-globale-resultats")]
        self.assertIn('class="topbar-search-box" style="position:relative;"', boite)

    def test_accueil_bannière_deadlines_est_un_mini_gantt_sans_filtres(self):
        """La bannière doit désormais montrer un mini-Gantt (jours + barres),
        pas la liste horizontale de pastilles d'avant — et sans la barre de
        filtre / légende de la page /deadlines (retour Fadhel : "sans les
        options filtre et tout")."""
        resp = self._get("/accueil", **{"app.repositories.taches.list_deadlines": DEADLINES})
        body = resp.data.decode()
        self.assertIn("mini-gantt", body)
        self.assertIn("Note de calcul EXE", body)
        # Pas de champ de filtre ni de légende de couleurs dans la bannière.
        self.assertNotIn('id="filtre-deadlines"', body)
        self.assertNotIn("En retard / imminent", body)

    def test_login_rend_la_session_permanente(self):
        """"Reste connecté" (retour Fadhel) : sans session.permanent = True,
        Flask pose un cookie qui expire à la fermeture du navigateur."""
        user_row = {**USER, "mot_de_passe_hash": "hash-bidon"}
        with patch("app.auth.get_user_by_email", return_value=user_row), \
             patch("app.auth.verify_password", return_value=True), \
             patch("app.auth._verifier_rappel_dailylog"), \
             patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.repositories.notifications.compter_non_lues", return_value=0):
            resp = self.client.post(
                "/connexion",
                data={"email": "fadhel@midgard.tn", "password": "peu-importe"},
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertTrue(sess.get("_permanent"))

    # --- Refonte du composeur de post (2026-09-19, retour Fadhel après
    # relecture des captures) : un post est TOUJOURS une Tâche, une
    # Information ou une Requête créée via un formulaire à champs — jamais
    # un simple champ texte libre — et le rebond ("répondre à ce post") est
    # lui-même un post de ce type, pas une réponse texte à part. Le tout se
    # fait désormais dans une fenêtre flottante (<dialog>) partagée, sans
    # quitter la page — voir partials/post_dialog.html.

    def test_page_projet_sans_composeur_texte_libre(self):
        """Le petit formulaire "Envoi/Réponse/Question/Requête + texte
        libre" ne doit plus exister : chaque post passe par la fenêtre
        flottante à champs."""
        resp = self._get("/projets/1")
        body = resp.data.decode()
        self.assertNotIn("Écrire un post sur ce projet…", body)
        self.assertIn('id="dialog-nouveau-post"', body)
        self.assertIn('data-open-post-dialog', body)

    def test_page_projet_dialog_cible_directement_le_projet(self):
        """Sur la page projet, le projet est déjà connu : pas de sélecteur
        de projet dans la fenêtre, la Tâche se publie directement sur ce
        projet."""
        resp = self._get("/projets/1")
        body = resp.data.decode()
        self.assertIn('action="/projets/1/taches"', body)
        self.assertNotIn('id="dialog-post-projet"', body)

    def test_accueil_propose_un_nouveau_post_avec_choix_du_projet(self):
        """Retour Fadhel : "sur la page d'accueil on doit avoir aussi cette
        possibilité de faire un post" — l'accueil combine plusieurs projets,
        donc la fenêtre y propose un sélecteur de projet."""
        resp = self._get("/accueil")
        body = resp.data.decode()
        self.assertIn('data-open-post-dialog', body)
        self.assertIn('id="dialog-post-projet"', body)
        self.assertIn("26099X_Tour Meridian", body)

    def test_list_projets_caste_etat_et_phase_en_text_pour_any(self):
        """Régression (2026-09-19) : etat/phase sont des ENUM Postgres
        (projet_etat_enum / phase_enum). psycopg2 envoie une liste Python de
        chaînes comme un tableau text[], et "enum = ANY(text[])" n'existe
        pas côté Postgres ("operator does not exist: projet_etat_enum =
        text") — vérifié en conditions réelles sur une base Postgres 16 de
        test. C'était la cause du "Internal Server Error" que Fadhel
        obtenait en visitant "Tous les projets" avec les filtres par défaut.
        Le correctif caste la colonne en ::text avant le ANY(). On ne peut
        pas exécuter du vrai SQL ici (psycopg2 indisponible dans ce
        bac à sable de test), donc on verrouille le texte de la requête."""
        import inspect

        from app.repositories import projets as projets_repo

        source = inspect.getsource(projets_repo.list_projets)
        self.assertIn("p.etat::text = ANY(%(etats)s)", source)
        self.assertIn("p.phase::text = ANY(%(phases)s)", source)

    # --- Revue sécurité (2026-09-20) : anti-bourrinage, mot de passe
    # oublié, réinitialisation, email à la création, fiche admin/RH. ---

    def test_login_bloque_apres_trop_de_tentatives(self):
        """Au-delà de MAX_TENTATIVES échecs récents pour un même email, on
        n'interroge même plus la base — le message est générique, pas
        d'indice sur l'existence du compte."""
        with patch("app.repositories.securite.compter_tentatives_recentes", return_value=5), \
             patch("app.auth.get_user_by_email") as mock_get_user:
            resp = self.client.post(
                "/connexion",
                data={"email": "fadhel@midgard.tn", "password": "peu-importe"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Trop de tentatives", resp.data.decode())
        mock_get_user.assert_not_called()

    def test_login_echoue_enregistre_une_tentative(self):
        with patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.auth.get_user_by_email", return_value=None), \
             patch("app.repositories.securite.enregistrer_tentative") as mock_enregistrer:
            self.client.post(
                "/connexion",
                data={"email": "fadhel@midgard.tn", "password": "mauvais"},
            )
        mock_enregistrer.assert_called_once_with("connexion", "fadhel@midgard.tn")

    def test_mot_de_passe_oublie_page_affiche_un_formulaire(self):
        resp = self.client.get("/mot-de-passe-oublie")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'name="email"', resp.data)

    def test_mot_de_passe_oublie_message_generique_email_inconnu(self):
        """Aucun indice ne doit distinguer un email inconnu d'un email
        connu — voir la note de non-énumération dans auth.py."""
        with patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.repositories.securite.enregistrer_tentative"), \
             patch("app.auth.get_user_by_email", return_value=None), \
             patch("app.mailer.envoyer") as mock_envoyer:
            resp = self.client.post(
                "/mot-de-passe-oublie", data={"email": "inconnu@midgard.tn"},
                follow_redirects=True,
            )
        self.assertIn("un lien de r\xe9initialisation".encode(), resp.data)
        mock_envoyer.assert_not_called()

    def test_mot_de_passe_oublie_envoie_un_email_si_le_compte_existe(self):
        user_row = {**USER, "actif": True}
        with patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.repositories.securite.enregistrer_tentative"), \
             patch("app.auth.get_user_by_email", return_value=user_row), \
             patch("app.repositories.utilisateurs.set_reset_token") as mock_set_token, \
             patch("app.mailer.envoyer", return_value=True) as mock_envoyer:
            resp = self.client.post(
                "/mot-de-passe-oublie", data={"email": "fadhel@midgard.tn"},
                follow_redirects=True,
            )
        self.assertIn("un lien de r\xe9initialisation".encode(), resp.data)
        mock_set_token.assert_called_once()
        self.assertEqual(mock_set_token.call_args[0][0], user_row["id"])
        mock_envoyer.assert_called_once()
        self.assertEqual(mock_envoyer.call_args[0][0], user_row["email"])

    def test_mot_de_passe_oublie_bloque_apres_trop_de_tentatives_sans_message_different(self):
        with patch("app.repositories.securite.compter_tentatives_recentes", return_value=5), \
             patch("app.repositories.securite.enregistrer_tentative") as mock_enregistrer, \
             patch("app.mailer.envoyer") as mock_envoyer:
            resp = self.client.post(
                "/mot-de-passe-oublie", data={"email": "fadhel@midgard.tn"},
                follow_redirects=True,
            )
        self.assertIn("un lien de r\xe9initialisation".encode(), resp.data)
        mock_enregistrer.assert_not_called()
        mock_envoyer.assert_not_called()

    def test_reinitialiser_mot_de_passe_jeton_invalide(self):
        with patch("app.repositories.utilisateurs.get_par_reset_token_hash", return_value=None):
            resp = self.client.get("/reinitialiser/jeton-bidon", follow_redirects=True)
        self.assertIn("invalide ou a expir\xe9".encode(), resp.data)

    def test_reinitialiser_mot_de_passe_change_le_mot_de_passe(self):
        with patch("app.repositories.utilisateurs.get_par_reset_token_hash", return_value=RESET_TOKEN_ROW), \
             patch("app.repositories.utilisateurs.consommer_reset_token", return_value=RESET_TOKEN_ROW) as mock_consommer:
            resp = self.client.post(
                "/reinitialiser/un-vrai-jeton",
                data={"mot_de_passe": "nouveau123", "confirmation": "nouveau123"},
                follow_redirects=True,
            )
        self.assertIn("changé".encode(), resp.data)
        mock_consommer.assert_called_once()

    def test_reinitialiser_mot_de_passe_rejette_mots_de_passe_differents(self):
        with patch("app.repositories.utilisateurs.get_par_reset_token_hash", return_value=RESET_TOKEN_ROW), \
             patch("app.repositories.utilisateurs.consommer_reset_token") as mock_consommer:
            resp = self.client.post(
                "/reinitialiser/un-vrai-jeton",
                data={"mot_de_passe": "nouveau123", "confirmation": "autre-chose"},
            )
        self.assertIn("ne correspondent pas".encode(), resp.data)
        mock_consommer.assert_not_called()

    def test_reinitialiser_mot_de_passe_rejette_trop_court(self):
        with patch("app.repositories.utilisateurs.get_par_reset_token_hash", return_value=RESET_TOKEN_ROW), \
             patch("app.repositories.utilisateurs.consommer_reset_token") as mock_consommer:
            resp = self.client.post(
                "/reinitialiser/un-vrai-jeton",
                data={"mot_de_passe": "court1", "confirmation": "court1"},
            )
        self.assertIn("au moins 8 caract\xe8res".encode(), resp.data)
        mock_consommer.assert_not_called()

    def test_reinitialiser_mot_de_passe_jeton_deja_consomme_entre_temps(self):
        """PROMPT_CORRECTIONS.md P0 #3 (TOCTOU) : même si la page a été
        affichée avec un jeton valide, une consommation concurrente
        (double soumission, ou jeton déjà utilisé juste avant) doit être
        refusée sans planter — consommer_reset_token() est la SEULE source
        de vérité au moment d'écrire, pas get_par_reset_token_hash()."""
        with patch("app.repositories.utilisateurs.get_par_reset_token_hash", return_value=RESET_TOKEN_ROW), \
             patch("app.repositories.utilisateurs.consommer_reset_token", return_value=None):
            resp = self.client.post(
                "/reinitialiser/un-vrai-jeton",
                data={"mot_de_passe": "nouveau123", "confirmation": "nouveau123"},
                follow_redirects=True,
            )
        self.assertIn("invalide ou a expir\xe9".encode(), resp.data)

    def test_generer_lien_reset_est_relatif_sans_app_base_url(self):
        """Sans APP_BASE_URL configuré (voir config.py), le lien ne doit
        JAMAIS être construit à partir de l'en-tête Host de la requête
        (url_for(..., _external=True)) — PROMPT_CORRECTIONS.md P0 #3."""
        from app.auth import generer_lien_reset

        with self.app.test_request_context("/", headers={"Host": "evil.attacker.tld"}), \
             patch("app.repositories.utilisateurs.set_reset_token"):
            lien = generer_lien_reset(1)
        self.assertNotIn("evil.attacker.tld", lien)
        self.assertTrue(lien.startswith("/reinitialiser/"))

    def test_generer_lien_reset_utilise_app_base_url(self):
        from app.auth import generer_lien_reset

        self.app.config["APP_BASE_URL"] = "https://kairos.nanaki45.duckdns.org"
        try:
            with self.app.test_request_context("/", headers={"Host": "evil.attacker.tld"}), \
                 patch("app.repositories.utilisateurs.set_reset_token"):
                lien = generer_lien_reset(1)
        finally:
            self.app.config["APP_BASE_URL"] = ""
        self.assertTrue(lien.startswith("https://kairos.nanaki45.duckdns.org/reinitialiser/"))
        self.assertNotIn("evil.attacker.tld", lien)

    def test_creation_utilisateur_envoie_un_email_pour_definir_le_mot_de_passe(self):
        """Retour Fadhel (2026-09-21) : "ne pas définir un mot de passe à la
        création, envoyer un mail pour que l'utilisateur fasse son propre
        mot de passe" — plus de champ mot de passe dans le formulaire, un
        lien (même mécanisme que "mot de passe oublié") est envoyé à la
        place."""
        self._login()
        patchers = self._patched(**{
            "app.repositories.utilisateurs.create_utilisateur": 42,
            "app.repositories.utilisateurs.toggle_actif": None,
        })
        for p in patchers:
            p.start()
        try:
            with patch("app.mailer.envoyer", return_value=True) as mock_envoyer:
                resp = self.client.post(
                    "/utilisateurs/nouveau",
                    data={
                        "prenom": "Wael", "nom": "Rekik", "email": "w.rekik@midgard.tn",
                        "role": "intervenant", "equipe_code": "MIDGARD", "actif": "on",
                    },
                    follow_redirects=True,
                )
            mock_envoyer.assert_called_once()
            self.assertEqual(mock_envoyer.call_args[0][0], "w.rekik@midgard.tn")
            self.assertIn("d\xe9finisse son mot de passe".encode(), resp.data)
        finally:
            for p in patchers:
                p.stop()

    def test_creation_utilisateur_avertit_si_email_non_envoye(self):
        self._login()
        patchers = self._patched(**{
            "app.repositories.utilisateurs.create_utilisateur": 42,
            "app.repositories.utilisateurs.toggle_actif": None,
        })
        for p in patchers:
            p.start()
        try:
            with patch("app.mailer.envoyer", return_value=False):
                resp = self.client.post(
                    "/utilisateurs/nouveau",
                    data={
                        "prenom": "Wael", "nom": "Rekik", "email": "w.rekik@midgard.tn",
                        "role": "intervenant", "equipe_code": "MIDGARD", "actif": "on",
                    },
                    follow_redirects=True,
                )
            self.assertIn("SMTP non configur\xe9".encode(), resp.data)
        finally:
            for p in patchers:
                p.stop()

    def test_creation_utilisateur_inactif_n_envoie_aucun_email(self):
        """Un compte créé inactif n'a pas de sens à activer tout de suite —
        pas d'email envoyé (le lien serait de toute façon refusé tant que
        le compte n'est pas réactivé, voir reinitialiser_mot_de_passe)."""
        self._login()
        patchers = self._patched(**{
            "app.repositories.utilisateurs.create_utilisateur": 42,
            "app.repositories.utilisateurs.toggle_actif": None,
        })
        for p in patchers:
            p.start()
        try:
            with patch("app.mailer.envoyer") as mock_envoyer:
                resp = self.client.post(
                    "/utilisateurs/nouveau",
                    data={
                        "prenom": "Wael", "nom": "Rekik", "email": "w.rekik@midgard.tn",
                        "role": "intervenant", "equipe_code": "MIDGARD",
                    },
                    follow_redirects=True,
                )
            mock_envoyer.assert_not_called()
            self.assertIn("(inactif)".encode(), resp.data)
        finally:
            for p in patchers:
                p.stop()

    def test_fiche_affiche_les_infos_dun_autre_utilisateur(self):
        patchers = self._patched(**{
            "app.repositories.utilisateurs.get_utilisateur": AUTRE_UTILISATEUR,
        })
        self._login()
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/utilisateurs/2")
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Wael", resp.data)

    def test_fiche_modifie_un_autre_utilisateur(self):
        patchers = self._patched(**{
            "app.repositories.utilisateurs.get_utilisateur": AUTRE_UTILISATEUR,
        })
        self._login()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.utilisateurs.update_utilisateur_complet") as mock_update:
                resp = self.client.post(
                    "/utilisateurs/2",
                    data={
                        "prenom": "Wael", "nom": "Rekik", "email": "w.rekik@midgard.tn",
                        "role": "chef_de_projet", "equipe_code": "URBS",
                    },
                    follow_redirects=True,
                )
        finally:
            for p in patchers:
                p.stop()
        self.assertIn("mise \xe0 jour".encode(), resp.data)
        mock_update.assert_called_once()
        self.assertEqual(mock_update.call_args.kwargs["role"], "chef_de_projet")

    def test_fiche_empeche_le_changement_de_son_propre_role(self):
        """Même logique que toggle_actif : on ne peut pas se retirer
        soi-même son rôle admin par erreur depuis cet écran."""
        patchers = self._patched()  # get_utilisateur par défaut = UTILISATEUR_PROFIL (id 1, role admin)
        self._login()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.utilisateurs.update_utilisateur_complet") as mock_update:
                resp = self.client.post(
                    "/utilisateurs/1",
                    data={
                        "prenom": "Foulen", "nom": "Chedly", "email": "fadhel@midgard.tn",
                        "role": "intervenant", "equipe_code": "MIDGARD",
                    },
                )
        finally:
            for p in patchers:
                p.stop()
        self.assertIn("propre r\xf4le".encode(), resp.data)
        mock_update.assert_not_called()

    def test_fiche_rejette_un_role_invalide(self):
        """PROMPT_CORRECTIONS.md P1 #11 : contrairement à creer(), fiche()
        n'imposait aucune validation de `role` avant d'appeler
        update_utilisateur_complet() — une requête forgée à la main pouvait
        poser n'importe quelle valeur, sans même la contrainte DB (pas de
        CHECK sur utilisateur.role)."""
        patchers = self._patched(**{
            "app.repositories.utilisateurs.get_utilisateur": AUTRE_UTILISATEUR,
        })
        self._login()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.utilisateurs.update_utilisateur_complet") as mock_update:
                resp = self.client.post(
                    "/utilisateurs/2",
                    data={
                        "prenom": "Wael", "nom": "Rekik", "email": "w.rekik@midgard.tn",
                        "role": "super_admin", "equipe_code": "URBS",
                    },
                )
        finally:
            for p in patchers:
                p.stop()
        self.assertIn("R\xf4le invalide".encode(), resp.data)
        mock_update.assert_not_called()

    # --- Changement silencieux d'équipe/rôle (PROMPT_CORRECTIONS.md P1 #12) :
    # un <select> HTML sans <option> `selected` correspondant à la valeur
    # réelle affiche par défaut sa PREMIÈRE option et soumet cette valeur
    # comme n'importe quel autre choix explicite — enregistrer une fiche
    # sans équipe, ou celle d'un rôle non listé (ex. "client"), changeait
    # silencieusement la valeur en base. ---

    def test_fiche_utilisateur_sans_equipe_selectionne_loption_vide(self):
        resp = self._get("/utilisateurs/2", **{
            "app.repositories.utilisateurs.get_utilisateur": UTILISATEUR_SANS_EQUIPE,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'<option value="" selected>', resp.data)

    def test_fiche_role_hors_liste_est_verrouille(self):
        """Un compte "client" (créé via `flask create-user --role client`,
        role_enum) n'est pas proposable depuis ROLES_CREABLES — le <select>
        doit rester verrouillé sur sa valeur réelle plutôt que de basculer
        silencieusement sur "Intervenant" (première option)."""
        resp = self._get("/utilisateurs/2", **{
            "app.repositories.utilisateurs.get_utilisateur": UTILISATEUR_CLIENT,
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        self.assertIn('<option value="client" selected>', body)
        self.assertIn('<select id="role" name="role" disabled>', body)
        self.assertIn('<input type="hidden" name="role" value="client">', body)

    def test_fiche_conserve_un_role_hors_liste_non_modifie(self):
        """Le champ caché renvoie la vraie valeur ("client") — la validation
        du rôle (P1 #11) ne doit pas la rejeter tant qu'elle reste inchangée,
        sinon la fiche d'un tel compte deviendrait impossible à modifier."""
        patchers = self._patched(**{
            "app.repositories.utilisateurs.get_utilisateur": UTILISATEUR_CLIENT,
        })
        self._login()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.utilisateurs.update_utilisateur_complet") as mock_update:
                resp = self.client.post(
                    "/utilisateurs/2",
                    data={
                        "prenom": "Wael", "nom": "Rekik", "email": "w.rekik@midgard.tn",
                        "role": "client", "equipe_code": "URBS",
                        "telephone": "20 000 001",
                    },
                    follow_redirects=True,
                )
        finally:
            for p in patchers:
                p.stop()
        self.assertIn("mise \xe0 jour".encode(), resp.data)
        mock_update.assert_called_once()
        self.assertEqual(mock_update.call_args.kwargs["role"], "client")

    def test_fiche_change_le_mot_de_passe_si_fourni(self):
        patchers = self._patched(**{
            "app.repositories.utilisateurs.get_utilisateur": AUTRE_UTILISATEUR,
            "app.repositories.utilisateurs.update_utilisateur_complet": None,
        })
        self._login()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.utilisateurs.set_password") as mock_set_password:
                self.client.post(
                    "/utilisateurs/2",
                    data={
                        "prenom": "Wael", "nom": "Rekik", "email": "w.rekik@midgard.tn",
                        "role": "intervenant", "equipe_code": "URBS",
                        "nouveau_mot_de_passe": "nouveau123",
                    },
                    follow_redirects=True,
                )
        finally:
            for p in patchers:
                p.stop()
        mock_set_password.assert_called_once()
        self.assertEqual(mock_set_password.call_args[0][0], 2)

    # --- Quatrième vague de retours de Fadhel (2026-09-21) : image Kairos
    # dans les emails, rôle grisé au lieu du poste sur "Infos perso",
    # création sans mot de passe (email d'activation), changement de mot
    # de passe en libre-service, fiche en lecture seule pour les chefs de
    # projet, jours cliquables et week-end masqué dans le DailyLog de la
    # semaine dernière. ---

    def test_mon_profil_affiche_le_role_grise_au_lieu_du_poste(self):
        """Le rôle (non modifiable par l'utilisateur) remplace le poste à
        cet endroit — le poste reste modifiable plus bas dans le formulaire."""
        resp = self._get("/utilisateurs/moi")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            "g\xe9r\xe9s par l'administrateur ou le RH".encode(), resp.data,
        )
        self.assertIn(">Admin<".encode(), resp.data)

    def test_mon_profil_semaine_derniere_sans_week_end(self):
        """"Ne pas afficher samedi et dimanche" — la semaine dernière ne
        comporte plus que 5 jours (lundi à vendredi)."""
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.dailylog.list_entrees_jour", return_value=[]) as mock_entrees:
                resp = self.client.get("/utilisateurs/moi")
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_entrees.call_count, 5)
        for call in mock_entrees.call_args_list:
            self.assertLess(call[0][1].weekday(), 5)

    def test_mon_profil_lignes_dailylog_menent_au_jour_correspondant(self):
        """Cliquer sur un jour de la semaine dernière doit aller
        directement au Daily log de ce jour."""
        resp = self._get("/utilisateurs/moi")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'href="/dailylog?date=', resp.data)

    def test_mon_mot_de_passe_change_avec_le_bon_mot_de_passe_actuel(self):
        self._login()
        patchers = self._patched(**{
            "app.repositories.utilisateurs.get_mot_de_passe_hash": "hash-bidon",
        })
        for p in patchers:
            p.start()
        try:
            with patch("app.routes.utilisateurs.verify_password", return_value=True), \
                 patch("app.repositories.utilisateurs.set_password") as mock_set_password, \
                 patch("app.routes.utilisateurs.hash_password", return_value=MOT_DE_PASSE_HASH_PAR_DEFAUT):
                # set_password() est mocké (n'écrit donc rien en base) : on
                # fixe aussi le hash "nouveau" au même hash que celui déjà
                # renvoyé par get_mot_de_passe_hash ci-dessus, pour que
                # l'empreinte déposée en session par mon_mot_de_passe() reste
                # cohérente avec le hash "actuel" que la requête suivante
                # (follow_redirects) va relire — sinon la session serait
                # invalidée par erreur (PROMPT_CORRECTIONS.md P2 #17).
                resp = self.client.post(
                    "/utilisateurs/moi/mot-de-passe",
                    data={
                        "mot_de_passe_actuel": "ancien123",
                        "nouveau_mot_de_passe": "nouveau123",
                        "confirmation": "nouveau123",
                    },
                    follow_redirects=True,
                )
        finally:
            for p in patchers:
                p.stop()
        self.assertIn("Mot de passe chang\xe9".encode(), resp.data)
        mock_set_password.assert_called_once()
        self.assertEqual(mock_set_password.call_args[0][0], 1)

    def test_mon_mot_de_passe_rejette_mauvais_mot_de_passe_actuel(self):
        self._login()
        patchers = self._patched(**{
            "app.repositories.utilisateurs.get_mot_de_passe_hash": "hash-bidon",
        })
        for p in patchers:
            p.start()
        try:
            with patch("app.routes.utilisateurs.verify_password", return_value=False), \
                 patch("app.repositories.utilisateurs.set_password") as mock_set_password:
                resp = self.client.post(
                    "/utilisateurs/moi/mot-de-passe",
                    data={
                        "mot_de_passe_actuel": "mauvais",
                        "nouveau_mot_de_passe": "nouveau123",
                        "confirmation": "nouveau123",
                    },
                    follow_redirects=True,
                )
        finally:
            for p in patchers:
                p.stop()
        self.assertIn("actuel incorrect".encode(), resp.data)
        mock_set_password.assert_not_called()

    def test_mon_mot_de_passe_rejette_confirmation_differente(self):
        self._login()
        patchers = self._patched(**{
            "app.repositories.utilisateurs.get_mot_de_passe_hash": "hash-bidon",
        })
        for p in patchers:
            p.start()
        try:
            with patch("app.routes.utilisateurs.verify_password", return_value=True), \
                 patch("app.repositories.utilisateurs.set_password") as mock_set_password:
                resp = self.client.post(
                    "/utilisateurs/moi/mot-de-passe",
                    data={
                        "mot_de_passe_actuel": "ancien123",
                        "nouveau_mot_de_passe": "nouveau123",
                        "confirmation": "autre-chose",
                    },
                    follow_redirects=True,
                )
        finally:
            for p in patchers:
                p.stop()
        self.assertIn("ne correspondent pas".encode(), resp.data)
        mock_set_password.assert_not_called()

    def test_mon_mot_de_passe_rejette_trop_court(self):
        self._login()
        patchers = self._patched(**{
            "app.repositories.utilisateurs.get_mot_de_passe_hash": "hash-bidon",
        })
        for p in patchers:
            p.start()
        try:
            with patch("app.routes.utilisateurs.verify_password", return_value=True), \
                 patch("app.repositories.utilisateurs.set_password") as mock_set_password:
                resp = self.client.post(
                    "/utilisateurs/moi/mot-de-passe",
                    data={
                        "mot_de_passe_actuel": "ancien123",
                        "nouveau_mot_de_passe": "court1",
                        "confirmation": "court1",
                    },
                    follow_redirects=True,
                )
        finally:
            for p in patchers:
                p.stop()
        self.assertIn("au moins 8 caract\xe8res".encode(), resp.data)
        mock_set_password.assert_not_called()

    # --- Invalidation de session après changement de mot de passe
    # (PROMPT_CORRECTIONS.md P2 #17) ---

    def test_session_invalidee_si_le_mot_de_passe_a_change_ailleurs(self):
        """Simule un mot de passe changé depuis un autre appareil (ou par un
        admin, ou via "mot de passe oublié") pendant qu'une session reste
        ouverte ici : get_mot_de_passe_hash() renvoie désormais un hash
        différent de celui mémorisé en session à la connexion -> la session
        doit être coupée, comme si le compte avait été désactivé."""
        self._login()
        patchers = self._patched(**{
            "app.repositories.utilisateurs.get_mot_de_passe_hash": "un-autre-hash-tout-neuf",
        })
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/accueil", follow_redirects=True)
        finally:
            for p in patchers:
                p.stop()
        self.assertIn(b"Se connecter", resp.data)
        self.assertIn("Votre mot de passe a \xe9t\xe9 chang\xe9".encode(), resp.data)

    def test_session_conservee_si_le_hash_na_pas_change(self):
        """Contre-exemple : tant que get_mot_de_passe_hash() renvoie le même
        hash que celui mémorisé à la connexion, la session reste valide."""
        resp = self._get("/accueil")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertNotIn(b"Se connecter", resp.data)

    def test_mon_mot_de_passe_garde_la_session_active_apres_changement(self):
        """Changer soi-même son mot de passe ne doit PAS déconnecter la
        session en cours (seules les AUTRES sessions du compte doivent
        l'être) : mon_mot_de_passe() met à jour l'empreinte en session avec
        le nouveau hash, cohérent avec ce que get_mot_de_passe_hash()
        renverrait désormais en production."""
        self._login()
        # "Base" factice : get_mot_de_passe_hash() renvoie ce que set_password()
        # y a écrit en dernier — comme un vrai aller-retour SQL, contrairement
        # à un simple return_value figé qui renverrait la même chose avant ET
        # après l'appel à set_password() dans la route.
        etat_hash = {"valeur": MOT_DE_PASSE_HASH_PAR_DEFAUT}

        def _fake_get_hash(user_id):
            return etat_hash["valeur"]

        def _fake_set_password(user_id, nouveau_hash, current_user_id):
            etat_hash["valeur"] = nouveau_hash

        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.utilisateurs.get_mot_de_passe_hash", side_effect=_fake_get_hash), \
                 patch("app.routes.utilisateurs.verify_password", return_value=True), \
                 patch("app.repositories.utilisateurs.set_password", side_effect=_fake_set_password), \
                 patch("app.routes.utilisateurs.hash_password", return_value="nouveau-hash-genere"):
                resp = self.client.post(
                    "/utilisateurs/moi/mot-de-passe",
                    data={
                        "mot_de_passe_actuel": "ancien123",
                        "nouveau_mot_de_passe": "nouveau123",
                        "confirmation": "nouveau123",
                    },
                    follow_redirects=True,
                )
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("Mot de passe chang\xe9".encode(), resp.data)
        self.assertNotIn(b"Se connecter", resp.data)

    def test_liste_visible_pour_chef_de_projet_sans_actions_admin(self):
        """Un chef de projet peut voir la liste des utilisateurs, mais sans
        les actions réservées à l'admin/RH (création de compte, activer/
        désactiver un compte)."""
        self._login()
        patchers = self._patched() + [
            patch("app.auth.get_user_by_id", return_value={**USER, "role": "chef_de_projet"}),
        ]
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/utilisateurs")
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertNotIn("Nouvel utilisateur".encode(), resp.data)
        self.assertNotIn(b'action="/utilisateurs/1/toggle-actif"', resp.data)

    def test_fiche_chef_de_projet_vue_en_lecture_seule(self):
        """Un chef de projet voit le nom, le téléphone et le Daily log de
        la semaine dernière de n'importe qui, sans rien de modifiable."""
        self._login()
        patchers = self._patched(**{
            "app.repositories.utilisateurs.get_utilisateur": AUTRE_UTILISATEUR,
        }) + [
            patch("app.auth.get_user_by_id", return_value={**USER, "role": "chef_de_projet"}),
        ]
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/utilisateurs/2")
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn(b"Wael", resp.data)
        self.assertIn("Lecture seule".encode(), resp.data)
        self.assertNotIn(b"<form", resp.data)

    def test_fiche_chef_de_projet_ne_peut_rien_modifier(self):
        """Un POST forgé vers la fiche par un chef de projet ne doit rien
        modifier — on sort avant tout traitement d'écriture (voir fiche())."""
        self._login()
        patchers = self._patched(**{
            "app.repositories.utilisateurs.get_utilisateur": AUTRE_UTILISATEUR,
        }) + [
            patch("app.auth.get_user_by_id", return_value={**USER, "role": "chef_de_projet"}),
        ]
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.utilisateurs.update_utilisateur_complet") as mock_update:
                resp = self.client.post(
                    "/utilisateurs/2",
                    data={
                        "prenom": "Pirate", "nom": "Rekik",
                        "email": "w.rekik@midgard.tn", "role": "admin",
                    },
                )
        finally:
            for p in patchers:
                p.stop()
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        mock_update.assert_not_called()


class TestSecretKeyValidation(unittest.TestCase):
    """PROMPT_CORRECTIONS.md P0 #6 : create_app() doit refuser de démarrer
    sans une SECRET_KEY correcte (config.py n'a plus de valeur de repli).
    Ignoré en mode TESTING (TestConfig, utilisée par tous les autres
    tests de ce fichier, garde volontairement une clé courte)."""

    def test_refuse_de_demarrer_sans_secret_key(self):
        class ConfigSansCle(Config):
            SECRET_KEY = ""
            DATABASE_URL = "postgresql://fake/fake"

        with self.assertRaises(RuntimeError):
            create_app(ConfigSansCle)

    def test_refuse_une_cle_trop_courte(self):
        class ConfigCleCourte(Config):
            SECRET_KEY = "trop-courte"
            DATABASE_URL = "postgresql://fake/fake"

        with self.assertRaises(RuntimeError):
            create_app(ConfigCleCourte)

    def test_refuse_les_valeurs_dexemple_connues(self):
        for placeholder in ("dev-secret-key-change-me", "change-moi-aussi"):
            class ConfigPlaceholder(Config):
                SECRET_KEY = placeholder
                DATABASE_URL = "postgresql://fake/fake"

            with self.assertRaises(RuntimeError):
                create_app(ConfigPlaceholder)

    def test_demarre_avec_une_vraie_cle(self):
        import secrets as secrets_mod

        class ConfigOk(Config):
            SECRET_KEY = secrets_mod.token_hex(32)
            DATABASE_URL = "postgresql://fake/fake"

        create_app(ConfigOk)  # ne doit pas lever


class TestVerifierRappelDailylog(unittest.TestCase):
    """_verifier_rappel_dailylog est testée isolément (sans passer par une
    vraie requête HTTP) : logique de décision pure, seules les fonctions de
    repository qu'elle appelle sont simulées."""

    def test_cree_le_rappel_quand_veille_non_remplie(self):
        from app.auth import _verifier_rappel_dailylog

        mardi = datetime.date(2026, 9, 15)  # veille = lundi 14, pas un dimanche
        with patch("app.repositories.dailylog.list_entrees_jour", return_value=[]), \
             patch("app.repositories.notifications.a_deja_un_rappel_dailylog", return_value=False), \
             patch("app.repositories.notifications.creer") as mock_creer:
            _verifier_rappel_dailylog(1, aujourdhui=mardi)
        mock_creer.assert_called_once()
        args = mock_creer.call_args[0]
        self.assertEqual(args[0], 1)
        self.assertEqual(args[1], "rh_info")
        self.assertIn("14/09/2026", args[2])

    def test_ne_cree_rien_si_veille_deja_remplie(self):
        from app.auth import _verifier_rappel_dailylog

        mardi = datetime.date(2026, 9, 15)
        with patch("app.repositories.dailylog.list_entrees_jour", return_value=[{"id": 1}]), \
             patch("app.repositories.notifications.a_deja_un_rappel_dailylog", return_value=False), \
             patch("app.repositories.notifications.creer") as mock_creer:
            _verifier_rappel_dailylog(1, aujourdhui=mardi)
        mock_creer.assert_not_called()

    def test_ne_cree_rien_si_rappel_deja_envoye_aujourdhui(self):
        from app.auth import _verifier_rappel_dailylog

        mardi = datetime.date(2026, 9, 15)
        with patch("app.repositories.dailylog.list_entrees_jour", return_value=[]), \
             patch("app.repositories.notifications.a_deja_un_rappel_dailylog", return_value=True), \
             patch("app.repositories.notifications.creer") as mock_creer:
            _verifier_rappel_dailylog(1, aujourdhui=mardi)
        mock_creer.assert_not_called()

    def test_ne_cree_rien_un_lundi_pour_un_dimanche(self):
        from app.auth import _verifier_rappel_dailylog

        lundi = datetime.date(2026, 9, 14)  # veille = dimanche 13
        with patch("app.repositories.dailylog.list_entrees_jour") as mock_list, \
             patch("app.repositories.notifications.creer") as mock_creer:
            _verifier_rappel_dailylog(1, aujourdhui=lundi)
        mock_list.assert_not_called()
        mock_creer.assert_not_called()

    def test_ne_cree_rien_un_dimanche_pour_un_samedi(self):
        """Régression (2026-09-19, retour Fadhel) : le week-end complet doit
        être ignoré, pas seulement le dimanche — voir _verifier_rappel_dailylog."""
        from app.auth import _verifier_rappel_dailylog

        dimanche = datetime.date(2026, 9, 20)  # veille = samedi 19
        with patch("app.repositories.dailylog.list_entrees_jour") as mock_list, \
             patch("app.repositories.notifications.creer") as mock_creer:
            _verifier_rappel_dailylog(1, aujourdhui=dimanche)
        mock_list.assert_not_called()
        mock_creer.assert_not_called()


class TestProposeCode(unittest.TestCase):
    """PROMPT_CORRECTIONS.md P2 #22 : tests unitaires directs de
    projets_repo.propose_code(), sans passer par Flask — seul db.query_all
    est mocké."""

    def test_numero_suivant_normal(self):
        from app.repositories import projets as projets_repo

        with patch("app.db.query_all", return_value=[{"code": "26005X"}, {"code": "26012X"}]):
            self.assertEqual(projets_repo.propose_code("EXE", annee=2026), "26013X")

    def test_aucun_code_existant_demarre_a_001(self):
        from app.repositories import projets as projets_repo

        with patch("app.db.query_all", return_value=[]):
            self.assertEqual(projets_repo.propose_code("DCE", annee=2026), "26001D")

    def test_tri_texte_ne_casse_plus_apres_999(self):
        """Régression : "26999X" est lexicalement supérieur à "261000X"
        bien qu'inférieur numériquement — un tri texte (ORDER BY code DESC
        LIMIT 1, l'ancien code) aurait proposé "261000X" à nouveau, déjà
        pris, au lieu de "261001X"."""
        from app.repositories import projets as projets_repo

        with patch("app.db.query_all", return_value=[{"code": "26999X"}, {"code": "261000X"}]):
            self.assertEqual(projets_repo.propose_code("EXE", annee=2026), "261001X")

    def test_phase_invalide_repliee_sur_exe(self):
        from app.repositories import projets as projets_repo

        with patch("app.db.query_all", return_value=[]):
            self.assertEqual(projets_repo.propose_code("BIDON", annee=2026), "26001X")


if __name__ == "__main__":
    unittest.main()

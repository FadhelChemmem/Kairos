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
import pathlib
import re
import sys
import tempfile
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


# Dossier d'upload jetable pour toute la suite : create_app() crée
# UPLOAD_DIR au démarrage, et la valeur par défaut (/app/uploads) n'est
# pas inscriptible sur un runner GitHub Actions (utilisateur non root) —
# c'est ce qui faisait échouer la CI (159 erreurs PermissionError).
_UPLOAD_DIR_TESTS = tempfile.mkdtemp(prefix="kairos-tests-uploads-")


class TestConfig(Config):
    DATABASE_URL = "postgresql://fake/fake"  # jamais utilisé, get_cursor n'est pas appelé
    UPLOAD_DIR = _UPLOAD_DIR_TESTS
    SECRET_KEY = "test-secret"
    TESTING = True
    # La protection CSRF est désactivée pour les tests de routes (qui
    # postent directement sans passer par un formulaire rendu) — elle est
    # testée à part, activée, dans TestProtectionCSRF.
    WTF_CSRF_ENABLED = False


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
    # Répartition par rôle (retour Fadhel, 2026-09-28, Lot 5) — voir
    # v_projet_heures_par_role (schema.sql).
    "heures_chef": 180.0, "heures_intervenant": 302.0,
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
    "heures_chef": None, "heures_intervenant": None,
}

PROJET_LISTE_SANS_HEURES = {
    "id": 2, "code": "26001X", "nom": "Projet de test", "phase": "EXE", "etat": "en_cours",
    "date_debut": datetime.date(2026, 9, 19), "date_fin": None,
    "chef_prenom": "Fadhel", "chef_nom": "Chemmem", "chef_id": 1, "lots": "GO",
    "heures_cumulees": None, "prochaine_echeance": None,
    "heures_chef": None, "heures_intervenant": None,
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
    "heures_cumulees": None, "heures_chef": None, "heures_intervenant": None,
    "intervenants": [], "pieces_jointes": [],
}

# Fixtures pour les contrôles d'accès (IDOR, PROMPT_CORRECTIONS.md P0 #1) :
# tache_id=5/post_id=1, rattachés au projet_id=1, pour correspondre aux
# autres fixtures/appels de test_write_routes_redirect_without_crashing.
TACHE_POUR_FICHIERS = {**TACHE_SANS_HEURES, "id": 5, "projet_id": 1}
POST_POUR_ACCES = {"id": 1, "projet_id": 1, "tache_id": None, "parent_post_id": None, "auteur_id": 2,
                   "type_code": "envoi", "projet_etat": "en_cours"}
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
        "heures_cumulees": 12.0, "heures_chef": 4.0, "heures_intervenant": 8.0,
        "intervenants": [{"id": 1, "prenom": "Foulen", "nom": "Chedly"}, {"id": 4, "prenom": "Sana", "nom": "Trabelsi"}],
        "pieces_jointes": [{"id": 1, "nom_fichier": "note_calcul.pdf"}],
    },
    {
        "id": 6, "projet_id": 1, "titre": "Dossier DOE — plans as-built", "etat": "termine",
        "type_deadline": "rendu_client", "date_debut": None, "date_echeance": datetime.date(2026, 9, 10),
        "date_fin": datetime.date(2026, 9, 12), "dossier_lien": None,
        "created_at": datetime.datetime(2026, 9, 1), "updated_at": datetime.datetime(2026, 9, 12),
        "heures_cumulees": 18.0, "heures_chef": 0.0, "heures_intervenant": 18.0,
        "intervenants": [], "pieces_jointes": [],
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
# Lot 5 (retour Fadhel, 2026-09-28) : "calendrier à pastilles vert/bleu/
# rouge" — voir dailylog.etats_jours_mois. Les trois états sont représentés
# ici pour que les tests de rendu (pastilles/légende) puissent tous
# s'appuyer sur ce même fixture par défaut.
DAILYLOG_ETATS_JOURS = {"2026-09-11": "rempli", "2026-09-14": "absent", "2026-09-16": "manque"}

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

TACHES_EN_COURS_PROFIL = [
    {"id": 5, "titre": "Plan ferraillage voile R+2", "etat": "bloque",
     "date_echeance": datetime.date(2026, 9, 20), "projet_id": 1,
     "projet_nom": "Tour Meridian", "projet_code": "26099X"},
]

AUDIT_ENTREES = [
    {"id": 1, "table_cible": "projet", "ligne_id": 1, "action": "UPDATE",
     "created_at": datetime.datetime(2026, 9, 28, 10, 0),
     "donnees_avant": {"etat": "en_cours"}, "donnees_apres": {"etat": "bloque"},
     "auteur_id": 1, "auteur_prenom": "Foulen", "auteur_nom": "Chedly"},
]
AUDIT_AUTEURS = [{"id": 1, "prenom": "Foulen", "nom": "Chedly"}]


class SmokeBase(unittest.TestCase):
    """Outils communs (app de test, connexion, mocks par défaut) — sans
    test à lui : une classe de tests qui en hérite ne relance pas toute la
    suite de SmokeTestCase (2026-09-29)."""

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
            "app.repositories.projets.list_mes_projets_recents": MES_PROJETS,
            "app.repositories.projets.list_projets": [],
            "app.repositories.projets.list_chefs_de_projet": CHEFS_DE_PROJET,
            "app.repositories.projets.get_projet": PROJET,
            "app.repositories.projets.list_lots": LOTS,
            "app.repositories.projets.list_intervenants": INTERVENANTS,
            "app.repositories.projets.user_can_manage": True,
            "app.repositories.projets.user_can_view": True,
            "app.repositories.projets.user_est_rattache": False,
            "app.repositories.projets.propose_code": "26099X",
            "app.repositories.projets.update_projet": None,
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
            "app.repositories.utilisateurs.list_collaborateurs_recents": [3],
            "app.repositories.dailylog.list_projets_pour_dailylog": DAILYLOG_PROJETS,
            "app.repositories.dailylog.list_entrees_jour": DAILYLOG_ENTREES,
            "app.repositories.dailylog.list_lignes_suggerees": DAILYLOG_SUGGESTIONS,
            "app.repositories.dailylog.etats_jours_mois": DAILYLOG_ETATS_JOURS,
            "app.repositories.dailylog.jours_manques_recents": [],
            "app.repositories.dailylog.rechercher_projets": [],
            # Daily log v2 (migration 0008) : réglage du jour et jours
            # renseignés (heures ou absence).
            "app.repositories.dailylog.get_jour": None,
            "app.repositories.dailylog.jour_renseigne": True,
            "app.repositories.dailylog.jours_renseignes": set(),
            "app.repositories.utilisateurs.list_tous": UTILISATEURS_TOUS,
            "app.repositories.utilisateurs.compter": COMPTE_UTILISATEURS,
            "app.repositories.utilisateurs.rh_deja_attribue": None,
            "app.repositories.utilisateurs.get_utilisateur": UTILISATEUR_PROFIL,
            "app.repositories.utilisateurs.update_profil": None,
            "app.repositories.utilisateurs.set_reset_token": None,
            "app.repositories.utilisateurs.get_mot_de_passe_hash": MOT_DE_PASSE_HASH_PAR_DEFAUT,
            "app.repositories.utilisateurs.search": [],
            "app.repositories.projets.search": [],
            "app.repositories.projets.list_ids_visibles": {1},
            "app.repositories.taches.list_en_cours_pour_profil": TACHES_EN_COURS_PROFIL,
            "app.repositories.posts.list_feed_auteur": [],
            "app.repositories.notifications.compter_non_lues": 2,
            "app.repositories.notifications.list_notifications": NOTIFICATIONS,
            "app.repositories.notifications.get_notification": NOTIFICATION_UNE,
            "app.repositories.notifications.marquer_lu": None,
            "app.repositories.notifications.marquer_toutes_lues": None,
            "app.repositories.notifications.creer": 201,
            "app.repositories.notifications.creer_pour_plusieurs": None,
            "app.repositories.audit.list_entrees": AUDIT_ENTREES,
            "app.repositories.audit.list_auteurs": AUDIT_AUTEURS,
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
            for p in reversed(patchers):
                p.stop()


class SmokeTestCase(SmokeBase):
    def test_login_page_renders(self):
        resp = self.client.get("/connexion")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Se connecter", resp.data)

    def test_favicon_du_logo_sur_toutes_les_pages(self):
        """Icône d'onglet (retour Fadhel, 2026-09-29) : déclarée dans
        base.html — donc aussi sur la page de connexion — et servie."""
        for url in ("/connexion", "/accueil"):
            with self.subTest(url=url):
                resp = self._get(url) if url != "/connexion" else self.client.get(url)
                self.assertEqual(resp.status_code, 200)
                self.assertIn(b'rel="icon" type="image/svg+xml" href="/static/img/favicon.svg"', resp.data)
                self.assertIn(b'href="/static/img/favicon.ico"', resp.data)
                self.assertIn(b'rel="apple-touch-icon"', resp.data)
        for fichier, debut in (("favicon.svg", b"<svg"), ("favicon.ico", b"\x00\x00\x01\x00"),
                               ("apple-touch-icon.png", b"\x89PNG")):
            with self.subTest(fichier=fichier):
                resp = self.client.get(f"/static/img/{fichier}")
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.data.startswith(debut))
                resp.close()
        # K toujours noir, y compris en thème sombre du navigateur (Fadhel, lot 7).
        resp = self.client.get("/static/img/favicon.svg")
        self.assertNotIn(b"prefers-color-scheme", resp.data)
        resp.close()

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
            for p in reversed(patchers):
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
                    "duree": "5",  # valeur déjà enregistrée, conservée
                    "ligne_projet_id": ["1", "1"],
                    "ligne_tache_id": ["", ""],
                    "ligne_heures": ["30", "-5"],
                })
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(mock_remplacer.call_args.args[2], [])
        finally:
            for p in reversed(patchers):
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
                    "duree": "5",  # valeur déjà enregistrée, conservée
                    "ligne_projet_id": ["1"],
                    "ligne_tache_id": [""],
                    "ligne_heures": ["4"],
                })
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(mock_remplacer.call_args.args[2], [])
        finally:
            for p in reversed(patchers):
                p.stop()

    def test_dailylog_enregistrer_ignore_une_tache_dun_autre_projet(self):
        """La tâche indiquée sur une ligne doit appartenir au projet
        indiqué sur cette MÊME ligne."""
        self._login()
        patchers = self._patched(**{
            "app.repositories.taches.get_tache": {**TACHE_POUR_FICHIERS, "projet_id": 99},
            "app.repositories.dailylog.list_entrees_jour": [{"projet_id": 1, "tache_id": 5, "heures": 4.0}],
        })
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.dailylog.remplacer_jour") as mock_remplacer:
                resp = self.client.post("/dailylog", data={
                    "date": "2026-09-15",
                    "duree": "4",
                    "ligne_projet_id": ["1"],
                    "ligne_tache_id": ["5"],
                    "ligne_heures": ["4"],
                })
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(mock_remplacer.call_args.args[2], [])
        finally:
            for p in reversed(patchers):
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
                    "duree": "4",
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
            for p in reversed(patchers):
                p.stop()

    @staticmethod
    def _duree_pour(heures):
        """Daily log v2 : la journée doit être répartie à 100 % de sa durée —
        les tests d'une ligne unique envoient donc une durée égale à son
        total (8 h sinon, pour les valeurs que la validation refuse)."""
        try:
            total = sum(float(h) for h in heures)
        except ValueError:
            return "8"
        if 0 < total <= 24 and abs(total * 4 - round(total * 4)) < 1e-9:
            return str(total)
        return "8"

    def _poster_dailylog(self, heures, duree=None, **overrides):
        """`duree` : durée de la journée envoyée (par défaut le total des
        heures). Une ligne refusée garde sa valeur déjà enregistrée
        (DAILYLOG_ENTREES : 5 h sur le projet 1), qui compte dans le total
        de la journée (audit du 2026-09-29)."""
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.dailylog.remplacer_jour") as mock_remplacer:
                resp = self.client.post("/dailylog", data={
                    "date": "2026-09-15",
                    "duree": duree or self._duree_pour(heures),
                    "ligne_projet_id": ["1"] * len(heures),
                    "ligne_tache_id": [""] * len(heures),
                    "ligne_heures": heures,
                })
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302)
        return mock_remplacer

    # --- Daily log v2 (maquette validée le 2026-09-29) : durée du jour,
    #     absence, total toujours = 100 %. ---

    def _poster_jour(self, data, **overrides):
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.dailylog.remplacer_jour") as mock_remplacer:
                resp = self.client.post("/dailylog", data=dict({"date": "2026-09-15"}, **data))
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302)
        return mock_remplacer

    def test_dailylog_refuse_un_total_different_de_la_duree(self):
        mock = self._poster_jour({"duree": "8", "ligne_projet_id": ["1"], "ligne_tache_id": [""], "ligne_heures": ["4"]})
        mock.assert_not_called()
        with self.client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
        self.assertTrue(any("100 %" in msg for _, msg in flashes))

    def test_dailylog_enregistre_la_duree_du_jour(self):
        mock = self._poster_jour({"duree": "6.5", "ligne_projet_id": ["1", "2"], "ligne_tache_id": ["", ""],
                                  "ligne_heures": ["4.25", "2.25"]})
        self.assertEqual(mock.call_args.kwargs["duree_heures"], 6.5)
        self.assertFalse(mock.call_args.kwargs["absent"])
        self.assertEqual([l["heures"] for l in mock.call_args.args[2]], [4.25, 2.25])

    def test_dailylog_journee_absente_sans_lignes(self):
        mock = self._poster_jour({"duree": "8", "absent": "1", "ligne_projet_id": ["1"], "ligne_tache_id": [""], "ligne_heures": ["3"]})
        self.assertTrue(mock.call_args.kwargs["absent"])

    def test_dailylog_refuse_une_duree_invalide(self):
        for duree in ("0", "25", "abc", "7.3", "nan"):
            with self.subTest(duree=duree):
                mock = self._poster_jour({"duree": duree, "ligne_projet_id": ["1"], "ligne_tache_id": [""], "ligne_heures": ["4"]})
                mock.assert_not_called()

    def test_dailylog_page_transmet_duree_et_absence(self):
        resp = self._get("/dailylog?date=2026-09-15", **{
            "app.repositories.dailylog.get_jour": {"duree_heures": 6.5, "absent": False},
        })
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn(b'"duree": 6.5', resp.data)
        self.assertIn(b'"absent": false', resp.data)
        self.assertNotIn("Journée type".encode(), resp.data)

    def test_duree_et_absence_option_b_pour_une_ancienne_journee(self):
        """Journée enregistrée avant le v2 (pas de dailylog_jour) : sa durée
        vaut le total de ses heures — elles ne sont jamais modifiées."""
        from app.repositories import dailylog as dailylog_repo
        with patch("app.repositories.dailylog.get_jour", return_value=None):
            self.assertEqual(dailylog_repo.duree_et_absence(1, "2026-09-29", [{"heures": 2.2}, {"heures": 0.98}, {"heures": 0.82}]), (4.0, False))
            self.assertEqual(dailylog_repo.duree_et_absence(1, "2026-09-29", []), (8.0, False))
        with patch("app.repositories.dailylog.get_jour", return_value={"duree_heures": 7.5, "absent": True}):
            self.assertEqual(dailylog_repo.duree_et_absence(1, "2026-09-29", [{"heures": 3}]), (7.5, True))

    def test_dailylog_refuse_nan_et_infini(self):
        """Audit n°2 : `nan` passait les bornes (toute comparaison avec NaN
        est fausse) et rendait les totaux d'heures du projet égaux à NaN."""
        for valeur in ("nan", "NaN", "inf", "-inf"):
            with self.subTest(valeur=valeur):
                mock_remplacer = self._poster_dailylog([valeur], duree="5")
                self.assertEqual(mock_remplacer.call_args.args[2], [])

    def test_dailylog_bornes_24h_exactes(self):
        self.assertEqual(
            self._poster_dailylog(["24"]).call_args.args[2],
            [{"projet_id": 1, "tache_id": None, "heures": 24.0}],
        )
        self.assertEqual(self._poster_dailylog(["24.01"], duree="5").call_args.args[2], [])

    def test_dailylog_ligne_refusee_ne_contourne_plus_le_total(self):
        """Audit du 2026-09-29 : une ligne invalide faisait sauter le
        contrôle du total — 3 × 24 h passaient pour une journée de 8 h."""
        mock_remplacer = self._poster_dailylog(["abc", "24", "24", "24"], duree="8")
        mock_remplacer.assert_not_called()
        with self.client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
        self.assertTrue(any("100 %" in msg for _, msg in flashes))

    def test_dailylog_curseurs_gardent_le_total(self):
        """Bug remonté par Fadhel (2026-09-29) : après le retrait ou la
        désélection d'un projet, cliquer sur une ligne la mettait à la
        journée entière sans rien reprendre aux autres (12 h sur 8 h). Les
        règles de répartition passent désormais par normaliser() (au plus
        n-1 projets "touchés", total = journée) — comportement vérifié par
        1 000 clics aléatoires sous Playwright, ici on verrouille le câblage."""
        import pathlib
        tpl = (pathlib.Path(__file__).resolve().parent.parent / "app" / "templates" / "dailylog.html").read_text(encoding="utf-8")
        regler = tpl[tpl.index("function regler("):tpl.index("function reglerSansControle(")]
        self.assertEqual(regler.count("normaliser();"), 2)
        for fonction in ("function toggleSelect(", "function removeLine(", "function addLine(", "function deplacerLimite("):
            corps = tpl[tpl.index(fonction):]
            corps = corps[:corps.index("\n  }\n")]
            self.assertIn("normaliser();", corps, fonction)

    def test_dailylog_ligne_refusee_conservee_et_signalee(self):
        """Audit n°2 : une ligne refusée (ici, projet devenu invisible) ne
        doit plus être supprimée en silence — sa clé est transmise à
        remplacer_jour pour conserver la valeur déjà enregistrée, et
        l'utilisateur est prévenu."""
        mock_remplacer = self._poster_dailylog(
            ["4"], duree="5", **{"app.repositories.projets.user_can_view": False},
        )
        self.assertEqual(mock_remplacer.call_args.kwargs["conserver"], {(1, 0)})
        with self.client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
        self.assertTrue(any("valeur précédente a été conservée" in msg for _, msg in flashes))

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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
                p.stop()

    def test_dailylog_jours_remplis_api(self):
        """Lot 5 (retour Fadhel, 2026-09-28) : la réponse porte désormais un
        état par jour (rempli/partiel/manque), pas seulement une liste de
        jours "remplis" — voir dailylog.etats_jours_mois."""
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/dailylog/jours-remplis?annee=2026&mois=9")
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), {"etats": DAILYLOG_ETATS_JOURS})

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
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("Phase invalide".encode(), resp.data)
        mock_create.assert_not_called()

    # --- audit sécurité/qualité externe, 2026-09-28, relecture Luna round 4 :
    # date_debut_valide était calculée (_parser_date_tache) mais jamais
    # utilisée — la chaîne brute date_debut était repassée à create_projet()
    # à la place. Fonctionnellement inoffensif (le elif ci-dessous empêche
    # d'atteindre create_projet() avec un format invalide, donc la chaîne
    # transmise était déjà garantie valide), mais incohérent avec le reste
    # du fichier (modifier_infos()/creer_tache() passent déjà la valeur
    # validée). Corrigé pour cohérence — les deux tests ci-dessous verrouillent
    # à la fois le rejet du format invalide et le type réellement transmis. ---

    def test_projet_creer_rejette_une_date_debut_invalide(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.projets.create_projet") as mock_create:
                resp = self.client.post(
                    "/projets/nouveau",
                    data={"nom": "Test", "code": "26099X", "phase": "EXE", "date_debut": "n-importe-quoi"},
                    follow_redirects=True,
                )
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("Date de d\xe9but invalide".encode(), resp.data)
        mock_create.assert_not_called()

    def test_projet_creer_passe_la_date_debut_validee_a_create_projet(self):
        """Contre-épreuve : create_projet() doit recevoir un objet
        datetime.date (la valeur validée), pas la chaîne brute du
        formulaire — sinon ce test réussirait même sans le correctif."""
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.projets.create_projet", return_value=42) as mock_create:
                resp = self.client.post(
                    "/projets/nouveau",
                    data={"nom": "Test", "code": "26099X", "phase": "EXE", "date_debut": "2026-09-28"},
                    follow_redirects=False,
                )
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302, resp.data[:2000])
        mock_create.assert_called_once()
        self.assertEqual(mock_create.call_args.kwargs["date_debut"], datetime.date(2026, 9, 28))

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

    # --- Contrôle d'accès aux projets (IDOR, PROMPT_CORRECTIONS.md P0 #1) :
    # avant ce correctif, connaître/deviner un id de projet, de tâche, de
    # post ou de pièce jointe suffisait à le consulter/le modifier, même
    # hors de son équipe/affectations — voir user_can_view(). ---

    def test_projet_detail_404_si_non_visible(self):
        resp = self._get("/projets/1", **{"app.repositories.projets.user_can_view": False})
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
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 404)

    def test_creer_tache_refuse_un_parent_dun_autre_projet(self):
        """Audit n°2 : parent_post_id n'était pas vérifié ici — le fil du
        projet affichait alors le contenu d'un post de n'importe quel
        autre projet (fuite inter-projets)."""
        self._login()
        patchers = self._patched(**{
            "app.repositories.posts.get_post": {**POST_POUR_ACCES, "projet_id": 99},
        }) + [patch("app.repositories.taches.create_tache", return_value=99)]
        mock_create = patchers[-1]
        for p in patchers:
            p.start()
        try:
            resp = self.client.post("/projets/1/taches", data={"titre": "T", "parent_post_id": "7"})
            self.assertEqual(resp.status_code, 404)
            self.assertFalse(mock_create.target.create_tache.called)
        finally:
            for p in reversed(patchers):
                p.stop()

    def test_creer_tache_accepte_un_parent_du_meme_projet(self):
        self._login()
        patchers = self._patched(**{
            "app.repositories.posts.get_post": {**POST_POUR_ACCES, "projet_id": 1},
        })
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.taches.create_tache", return_value=99) as mock_create:
                resp = self.client.post("/projets/1/taches", data={"titre": "T", "parent_post_id": "7"})
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(mock_create.call_args.kwargs["parent_post_id"], 7)
        finally:
            for p in reversed(patchers):
                p.stop()

    def test_creer_tache_erreur_inattendue_na_pas_le_message_rh(self):
        """Audit n°2 : toute erreur base était présentée comme "un RH ne
        peut pas être intervenant"."""
        self._login()
        patchers = self._patched() + [
            patch("app.repositories.taches.create_tache", side_effect=Exception("connexion perdue")),
        ]
        for p in patchers:
            p.start()
        try:
            self.client.post("/projets/1/taches", data={"titre": "T"})
        finally:
            for p in reversed(patchers):
                p.stop()
        with self.client.session_transaction() as sess:
            messages = [msg for _, msg in sess.get("_flashes", [])]
        self.assertFalse(any("RH" in m for m in messages), messages)
        self.assertTrue(any("erreur inattendue" in m for m in messages), messages)

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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
        """L'action réellement soumise (sans JS, ou si post-reaction.js
        échoue) pointe vers "ajouter" tant qu'on n'a pas encore réagi — les
        deux URLs (reagir/supprimer) sont désormais TOUTES LES DEUX présentes
        en data-* sur le formulaire (retour Fadhel, 2026-09-28, bouton "(V)")
        pour que post-reaction.js puisse basculer de l'une à l'autre sans
        recharger la page ; seule `action=` doit rester celle qu'on soumet
        réellement pour l'instant."""
        resp = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [FEED_POST_MANUEL]})
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn(f'action="/posts/{FEED_POST_MANUEL["id"]}/reagir"'.encode(), resp.data)
        self.assertNotIn(f'action="/posts/{FEED_POST_MANUEL["id"]}/reagir/supprimer"'.encode(), resp.data)

    def test_posts_reagir_404_si_post_non_visible(self):
        self._login()
        patchers = self._patched(**{"app.repositories.projets.user_can_view": False})
        for p in patchers:
            p.start()
        try:
            resp = self.client.post("/posts/1/reagir", data={"reaction_code": "pouce"})
        finally:
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 404)

    def test_plus_d_ajout_de_fichier_apres_coup_sur_un_post_ou_un_commentaire(self):
        """Audit du 2026-09-29 : ces routes n'étaient plus utilisées et
        permettaient d'ajouter un fichier au post/commentaire d'un autre."""
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            for url in ("/fichiers/posts/1/upload", "/fichiers/posts/commentaires/1/upload"):
                with self.subTest(url=url):
                    resp = self.client.post(url, data={"fichier": (io.BytesIO(b"x"), "a.pdf")},
                                            content_type="multipart/form-data")
                    self.assertIn(resp.status_code, (404, 405))
        finally:
            for p in reversed(patchers):
                p.stop()

    def test_fichiers_upload_tache_nettoie_le_fichier_si_insert_echoue(self):
        self._login()
        patchers = self._patched() + [
            patch("app.routes.fichiers.save_upload", return_value=("note.pdf", "taches/5/xyz.pdf")),
            patch("app.repositories.taches.add_piece_jointe", side_effect=Exception("connexion perdue")),
        ]
        delete_patcher = patch("app.routes.fichiers.delete_upload")
        for p in patchers:
            p.start()
        mock_delete = delete_patcher.start()
        try:
            with self.assertRaises(Exception):
                self.client.post(
                    "/fichiers/taches/5/upload",
                    data={"fichier": (io.BytesIO(b"contenu bidon"), "note.pdf")},
                    content_type="multipart/form-data",
                )
            mock_delete.assert_called_once_with("taches/5/xyz.pdf")
        finally:
            delete_patcher.stop()
            for p in reversed(patchers):
                p.stop()

    def test_posts_creer_nettoie_le_fichier_si_creation_echoue(self):
        """Depuis le suivi P0-3 round 2 (Luna) : post + pièce jointe sont
        insérés dans LA MÊME transaction (create_post(..., piece_jointe=...))
        — un échec de cette insertion (simulé ici en faisant lever
        create_post() lui-même) doit nettoyer le fichier sur disque, sans
        laisser de post orphelin en base (contrairement à round 1, où
        create_post() committait déjà avant que la pièce jointe échoue)."""
        self._login()
        patchers = self._patched() + [
            patch("app.routes.posts.save_upload", return_value=("plan.pdf", "posts/projet-1/xyz.pdf")),
            patch("app.repositories.posts.create_post", side_effect=Exception("connexion perdue")),
        ]
        delete_patcher = patch("app.routes.posts.delete_upload")
        for p in patchers:
            p.start()
        mock_delete = delete_patcher.start()
        try:
            with self.assertRaises(Exception):
                self.client.post(
                    "/posts",
                    data={
                        "projet_id": "1", "type_code": "envoi", "contenu": "Test",
                        "fichier": (io.BytesIO(b"contenu bidon"), "plan.pdf"),
                    },
                    content_type="multipart/form-data",
                )
            mock_delete.assert_called_once_with("posts/projet-1/xyz.pdf")
        finally:
            delete_patcher.stop()
            for p in reversed(patchers):
                p.stop()

    def test_posts_creer_passe_bien_la_piece_jointe_a_create_post(self):
        """Contre-épreuve : vérifie que create_post() reçoit bien
        piece_jointe=(nom_fichier, chemin) quand un fichier est fourni —
        sans elle, le test ci-dessus passerait même si piece_jointe
        n'était jamais transmis (create_post lèverait pour une autre
        raison et le test resterait vert par accident)."""
        self._login()
        patchers = self._patched() + [
            patch("app.routes.posts.save_upload", return_value=("plan.pdf", "posts/projet-1/xyz.pdf")),
        ]
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.posts.create_post", return_value=101) as mock_create:
                resp = self.client.post(
                    "/posts",
                    data={
                        "projet_id": "1", "type_code": "envoi", "contenu": "Test",
                        "fichier": (io.BytesIO(b"contenu bidon"), "plan.pdf"),
                    },
                    content_type="multipart/form-data",
                )
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            mock_create.call_args.kwargs["piece_jointe"], ("plan.pdf", "posts/projet-1/xyz.pdf"),
        )

    def test_posts_commenter_nettoie_le_fichier_si_creation_echoue(self):
        """Même principe pour commenter() : add_comment() insère
        maintenant le commentaire et sa pièce jointe dans la même
        transaction (suivi P0-3 round 2)."""
        self._login()
        patchers = self._patched() + [
            patch("app.routes.posts.save_upload", return_value=("note.jpg", "posts/1/commentaires/xyz.jpg")),
            patch("app.repositories.posts.add_comment", side_effect=Exception("connexion perdue")),
        ]
        delete_patcher = patch("app.routes.posts.delete_upload")
        for p in patchers:
            p.start()
        mock_delete = delete_patcher.start()
        try:
            with self.assertRaises(Exception):
                self.client.post(
                    "/posts/1/commenter",
                    data={
                        "contenu": "Voici",
                        "fichier": (io.BytesIO(b"contenu bidon"), "note.jpg"),
                    },
                    content_type="multipart/form-data",
                )
            mock_delete.assert_called_once_with("posts/1/commentaires/xyz.jpg")
        finally:
            delete_patcher.stop()
            for p in reversed(patchers):
                p.stop()

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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
                resp = self.client.post("/notifications/10/ouvrir", follow_redirects=False)
                mock_marquer.assert_called_once_with(10, 1)
        finally:
            for p in reversed(patchers):
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
            resp = self.client.post("/notifications/999/ouvrir")
        finally:
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302, resp.data[:2000])
        self.assertFalse(mock_create.call_args.kwargs["actif"])
        # Ancienne façon de faire : un second appel séparé à toggle_actif().
        # Le nouvel INSERT pose déjà actif=false, plus besoin de ce détour.
        mock_toggle.assert_not_called()

    # --- audit sécurité/qualité externe, 2026-09-28, relecture Luna round 4 :
    # date_embauche n'était pas validée du tout côté applicatif, contrairement
    # à date_debut/date_echeance (tâches/projets) — un format invalide
    # plantait l'INSERT en erreur Postgres brute au lieu d'un message clair. ---

    def test_creer_rejette_une_date_embauche_invalide(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.utilisateurs.create_utilisateur") as mock_create:
                resp = self.client.post(
                    "/utilisateurs/nouveau",
                    data={
                        "prenom": "Wael", "nom": "Rekik", "email": "w.rekik@midgard.tn",
                        "role": "intervenant", "equipe_code": "MIDGARD",
                        "date_embauche": "n-importe-quoi",
                    },
                )
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn("embauche invalide".encode(), resp.data)
        mock_create.assert_not_called()

    def test_creer_passe_la_date_embauche_validee_a_create_utilisateur(self):
        """Contre-épreuve : create_utilisateur() doit recevoir un objet
        datetime.date (la valeur validée), pas la chaîne brute du
        formulaire — sinon ce test réussirait même sans le correctif."""
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.utilisateurs.create_utilisateur", return_value=42) as mock_create:
                resp = self.client.post(
                    "/utilisateurs/nouveau",
                    data={
                        "prenom": "Wael", "nom": "Rekik", "email": "w.rekik@midgard.tn",
                        "role": "intervenant", "equipe_code": "MIDGARD",
                        "date_embauche": "2026-09-28", "actif": "on",
                    },
                )
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302, resp.data[:2000])
        mock_create.assert_called_once()
        self.assertEqual(mock_create.call_args.kwargs["date_embauche"], datetime.date(2026, 9, 28))

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
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            flashes = sess.get("_flashes", [])
        self.assertTrue(any("compte RH actif" in msg for _, msg in flashes))

    def test_toggle_actif_ne_recopie_pas_le_jeton_csrf_dans_lurl(self):
        """Audit n°2 : la redirection recopiait tout request.form, donc
        aussi csrf_token, dans l'URL de la liste."""
        self._login()
        patchers = self._patched() + [patch("app.repositories.utilisateurs.toggle_actif")]
        for p in patchers:
            p.start()
        try:
            resp = self.client.post("/utilisateurs/2/toggle-actif", data={
                "csrf_token": "secret", "q": "wael", "equipe_code": "", "role": "intervenant",
            })
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("csrf_token", resp.headers["Location"])
        self.assertIn("q=wael", resp.headers["Location"])
        self.assertIn("role=intervenant", resp.headers["Location"])

    def test_fiche_changer_son_propre_mot_de_passe_garde_la_session(self):
        """Audit n°2 : un admin qui change son propre mot de passe depuis
        sa fiche était déconnecté (empreinte de session non rafraîchie)."""
        self._login()
        patchers = self._patched(**{
            "app.repositories.utilisateurs.get_utilisateur": {**UTILISATEUR_PROFIL, "id": 1},
        }) + [
            patch("app.repositories.utilisateurs.update_utilisateur_complet"),
            patch("app.repositories.utilisateurs.set_password"),
            patch("app.routes.utilisateurs.hash_password", return_value="nouveau-hash"),
        ]
        for p in patchers:
            p.start()
        try:
            resp = self.client.post("/utilisateurs/1", data={
                "prenom": "Foulen", "nom": "Chedly", "email": "fadhel@midgard.tn",
                "role": "admin", "equipe_code": "MIDGARD",
                "nouveau_mot_de_passe": "un-nouveau-mot-de-passe-solide",
            })
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302, resp.data[:1500])
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("pw_fingerprint"), password_fingerprint("nouveau-hash"))

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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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

        # `maintenant` figé à 10h (revérification du 2026-09-29) : sans ce
        # paramètre, jours_manques_recents() prend l'heure RÉELLE, et depuis
        # le Lot 5 ("rouge à partir de 16h") ajoute aujourd'hui à la liste
        # après 16h — ce test échouait donc seulement quand la suite était
        # lancée l'après-midi/le soir. Le cas "après 16h" est couvert par le
        # test suivant.
        with patch("app.repositories.dailylog.db.query_all", return_value=[{"date": j} for j in deja_rempli]):
            resultat = dailylog_repo.jours_manques_recents(
                user_id=1, aujourdhui=aujourdhui, fenetre_jours=5,
                maintenant=datetime.datetime(2026, 9, 21, 10, 0),
            )

        self.assertEqual(resultat, attendu)
        self.assertTrue(all(j.weekday() < 5 for j in resultat))

    def test_jours_manques_recents_ajoute_aujourdhui_seulement_apres_16h(self):
        """Lot 5 (retour Fadhel, 2026-09-28) : aujourd'hui ne compte comme
        manquant qu'à partir de 16h, jamais le matin."""
        from app.repositories import dailylog as dailylog_repo

        lundi = datetime.date(2026, 9, 21)
        with patch("app.repositories.dailylog.db.query_all", return_value=[]):
            matin = dailylog_repo.jours_manques_recents(
                user_id=1, aujourdhui=lundi, fenetre_jours=1,
                maintenant=datetime.datetime(2026, 9, 21, 15, 59),
            )
            apres_16h = dailylog_repo.jours_manques_recents(
                user_id=1, aujourdhui=lundi, fenetre_jours=1,
                maintenant=datetime.datetime(2026, 9, 21, 16, 0),
            )

        self.assertNotIn(lundi, matin)
        self.assertIn(lundi, apres_16h)

    # --- Lot 5 (retour Fadhel, 2026-09-28) : "calendrier à pastilles
    #     vert/bleu/rouge" — voir dailylog.etats_jours_mois. ---

    def test_etats_jours_mois_distingue_rempli_et_absent(self):
        """Daily log v2 (2026-09-29) : vert = heures saisies, bleu = journée
        marquée absente (dailylog_jour.absent)."""
        from app.repositories import dailylog as dailylog_repo

        with patch("app.repositories.dailylog.db.query_all", side_effect=[
                 [{"date": datetime.date(2026, 9, 10)}],
                 [{"date": datetime.date(2026, 9, 11)}],
             ]), \
             patch("app.repositories.dailylog.jours_manques_recents", return_value=[]):
            resultat = dailylog_repo.etats_jours_mois(user_id=1, annee=2026, mois=9)
        self.assertEqual(resultat, {"2026-09-10": "rempli", "2026-09-11": "absent"})

    def test_etats_jours_mois_ancienne_journee_incomplete_reste_rempli(self):
        """Plus d'état "partiel" : une journée enregistrée avant le v2 avec
        moins de 8 h (option B, heures conservées) est "rempli"."""
        from app.repositories import dailylog as dailylog_repo

        with patch("app.repositories.dailylog.db.query_all", side_effect=[
                 [{"date": datetime.date(2026, 9, 29)}], [],
             ]), \
             patch("app.repositories.dailylog.jours_manques_recents", return_value=[]):
            resultat = dailylog_repo.etats_jours_mois(user_id=1, annee=2026, mois=9)
        self.assertEqual(resultat, {"2026-09-29": "rempli"})

    def test_etats_jours_mois_manque_reprend_jours_manques_recents_du_mois_affiche(self):
        """"manque" (rouge) reprend jours_manques_recents (même fenêtre
        glissante/heuristique que la carte DailyLog de l'accueil) — un jour
        manqué HORS du mois demandé est exclu, pas de fuite entre mois."""
        from app.repositories import dailylog as dailylog_repo

        jours_manques = [datetime.date(2026, 9, 16), datetime.date(2026, 8, 31)]
        with patch("app.repositories.dailylog.db.query_all", return_value=[]), \
             patch("app.repositories.dailylog.jours_manques_recents", return_value=jours_manques):
            resultat = dailylog_repo.etats_jours_mois(user_id=1, annee=2026, mois=9)
        self.assertEqual(resultat, {"2026-09-16": "manque"})

    def test_etats_jours_mois_priorise_rempli_sur_manque(self):
        """Un jour avec des heures déjà enregistrées n'est jamais écrasé en
        "manque" (défensif)."""
        from app.repositories import dailylog as dailylog_repo

        with patch("app.repositories.dailylog.db.query_all", side_effect=[
                 [{"date": datetime.date(2026, 9, 16)}], [],
             ]), \
             patch("app.repositories.dailylog.jours_manques_recents", return_value=[datetime.date(2026, 9, 16)]):
            resultat = dailylog_repo.etats_jours_mois(user_id=1, annee=2026, mois=9)
        self.assertEqual(resultat, {"2026-09-16": "rempli"})

    def test_dailylog_calendrier_affiche_les_trois_pastilles(self):
        resp = self._get("/dailylog")
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        body = resp.data.decode()
        self.assertIn("rempli", body)
        self.assertIn("absent", body)
        self.assertIn("non rempli", body)
        self.assertNotIn("partiel", body)
        self.assertIn("2026-09-16", body)
        self.assertIn('"manque"', body)

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

    def test_accueil_mes_projets_suit_lordre_de_list_mes_projets_recents(self):
        """La carte "Mes projets" n'est plus triée par échéance la plus
        proche (retour Fadhel, 2026-09-28) : elle suit désormais l'ordre de
        `projets.list_mes_projets_recents` (ma dernière action perso sur
        chaque projet, projets terminés exclus) — voir cette fonction dans
        app/repositories/projets.py. Ancien test renommé : il ne testait
        plus la vraie logique de tri depuis ce changement, seulement un
        ordre de fixture qui coïncidait par hasard."""
        projets_recents = [
            {"id": 2, "code": "25014X", "nom": "Résidence Les Oliviers", "phase": "EXE",
             "etat": "en_cours", "mon_role": "intervenant"},
            {"id": 1, "code": "26099X", "nom": "Tour Meridian", "phase": "EXE",
             "etat": "bloque", "mon_role": "chef_de_projet"},
        ]
        resp = self._get("/accueil", **{"app.repositories.projets.list_mes_projets_recents": projets_recents})
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        debut = body.index("Mes projets")
        fin = body.index("Daily log", debut)
        section_mes_projets = body[debut:fin]
        pos_oliviers = section_mes_projets.index("Résidence Les Oliviers")
        pos_meridian = section_mes_projets.index("Tour Meridian")
        self.assertLess(pos_oliviers, pos_meridian)

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

    def test_post_card_reposter_ouvre_la_fenetre_a_trois_options(self):
        """"Reposter" (retour Fadhel, 2026-09-29, P2) remplace le trombone
        et la flèche : il ouvre la fenêtre flottante partagée (Tâche /
        Information / Requête) liée au post — jamais un champ texte libre."""
        feed_gere = [{**p, "je_gere": True, "projet_etat": "en_cours"} for p in FEED]
        resp = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": feed_gere})
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        bouton = re.search(r'<button[^>]*data-parent-post-id="1"[^>]*>', body, re.S).group(0)
        self.assertIn("data-open-post-dialog", bouton)
        self.assertIn('data-intents="tache,information,requete"', bouton)
        self.assertIn('data-projet-id="1"', bouton)
        self.assertNotIn("disabled", bouton)
        self.assertIn("Reposter", body)
        # Plus de trombone "Joindre un fichier" ni de flèche "Créer un post lié".
        self.assertNotIn('title="Joindre un fichier"', body)
        self.assertNotIn("Créer un post lié", body)
        self.assertNotIn("/upload", body)

    def test_reposter_sans_tache_si_on_ne_gere_pas_le_projet(self):
        feed = [{**p, "je_gere": False, "projet_etat": "en_cours"} for p in FEED]
        body = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": feed}).data.decode()
        bouton = re.search(r'<button[^>]*data-parent-post-id="1"[^>]*>', body, re.S).group(0)
        self.assertIn('data-intents="information,requete"', bouton)

    def test_reposter_desactive_sur_un_projet_termine(self):
        feed = [{**FEED_POST_MANUEL, "projet_etat": "termine"}]
        body = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": feed}).data.decode()
        bouton = re.search(r'<button[^>]*data-parent-post-id="1"[^>]*>', body, re.S).group(0)
        self.assertIn("disabled", bouton)
        self.assertIn("Projet terminé", bouton)

    def test_accueil_fenetre_post_liste_les_personnes(self):
        """Audit n°2 : utilisateurs_actifs n'était pas transmis à l'accueil —
        listes Intervenant(s)/Personnes taguées vides."""
        body = self._get("/accueil").data.decode()
        for u in UTILISATEURS_ACTIFS:
            self.assertIn(f'value="{u["id"]}"', body)

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
        #
        # Assertion volontairement scopée au SEUL <select name="chef_id">
        # (le filtre) : depuis le 2026-09-28, la page contient aussi la
        # fenêtre flottante "+ Nouveau projet" (partials/projet_dialog.html),
        # dont le champ "Chef de projet" liste lui TOUS les actifs (n'importe
        # qui de non-RH peut se voir confier un nouveau projet) — Omar Aziz
        # y apparaît légitimement, sans rapport avec ce filtre.
        resp = self._get("/projets", **{"app.repositories.projets.list_projets": [PROJET_LISTE_SANS_HEURES]})
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        debut = body.index('name="chef_id"')
        fin = body.index("</select>", debut)
        filtre_chef = body[debut:fin]
        self.assertIn("Sana Trabelsi", filtre_chef)
        self.assertNotIn("Omar Aziz", filtre_chef)

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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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

    def test_accueil_bandeau_deadlines_nom_projet_cliquable(self):
        """Retour Fadhel, 2026-09-28 : "Aller vers le projet en cliquant sur
        le projet en question" — le nom du projet, dans chaque ligne du
        mini-Gantt, doit mener directement au projet (le reste de la
        bannière continue de mener à /deadlines)."""
        resp = self._get("/accueil", **{"app.repositories.taches.list_deadlines": DEADLINES})
        body = resp.data.decode()
        self.assertIn('<a href="/projets/1" style="font-weight:600; color:inherit;">26099X_Tour Meridian</a>', body)

    def test_accueil_fil_filtrable_par_code_projet(self):
        """Retour Fadhel, 2026-09-28 : le filtre du fil d'activité doit
        aussi matcher un code de projet ("24102X"), pas seulement son nom —
        vérifié directement dans l'attribut data-fil-texte utilisé par le
        filtre JS (pas juste une présence de texte ailleurs sur la page)."""
        resp = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [FEED_POST_MANUEL]})
        body = resp.data.decode()
        debut = body.index('data-fil-texte="')
        fin = body.index('"', debut + len('data-fil-texte="'))
        self.assertIn(FEED_POST_MANUEL["projet_code"].lower(), body[debut:fin])

    def test_post_dialog_echeance_preremplie_a_aujourdhui(self):
        """Retour Fadhel, 2026-09-28 : "Dans écheance mettre par défaut la
        date d'ajd." """
        resp = self._get("/accueil")
        body = resp.data.decode()
        self.assertIn(f'id="dialog-echeance-tache" name="date_echeance" value="{datetime.date.today().isoformat()}"', body)

    def test_post_card_auteur_et_projet_cliquables_pour_chef_de_projet(self):
        """Retour Fadhel, 2026-09-28 : "Rendre le champ des personnes qui
        poste (pastille et nom) et le nom des projets cliquable." — mène à
        la page de profil (Lot 5, ouverte à tout le monde, voir
        test_fil_accueil_pointe_vers_le_profil_pas_la_fiche_admin), plus à
        l'ancienne fiche utilisateur (admin/RH/chef de projet)."""
        resp = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [FEED_POST_MANUEL]})
        body = resp.data.decode()
        self.assertIn(f'<a href="/utilisateurs/{FEED_POST_MANUEL["auteur_id"]}/profil"', body)
        self.assertIn(
            f'<a href="/projets/{FEED_POST_MANUEL["projet_id"]}" style="color:inherit;">'
            f'{FEED_POST_MANUEL["projet_code"]}_{FEED_POST_MANUEL["projet_nom"]}</a>',
            body,
        )

    def test_floating_window_js_charge_avant_post_dialog_js(self):
        """Retour Fadhel, 2026-09-28 : "On fait ça sur toutes les fenêtres
        flottantes." — floating-window.js (règle commune, réutilisable par
        de futures fenêtres) doit être chargé, et avant post-dialog.js qui
        s'appuie dessus (voir base.html) — le comportement réel (clic
        extérieur ignoré tant qu'il y a du texte saisi) est vérifié par
        Playwright, pas par ce test de rendu."""
        resp = self._get("/accueil")
        body = resp.data.decode()
        pos_floating = body.index("js/floating-window.js")
        pos_post_dialog = body.index("js/post-dialog.js")
        self.assertLess(pos_floating, pos_post_dialog)

    def test_fenetres_flottantes_comparent_a_l_ouverture(self):
        """N1 (retour Fadhel, 2026-09-29) : une fenêtre dont un champ est
        prérempli (code proposé, fiche projet) doit quand même se fermer au
        clic extérieur tant que rien n'a été changé — la règle commune
        compare à l'état capturé à l'ouverture, et les trois fenêtres
        l'utilisent (comportement réel vérifié sous Playwright)."""
        import pathlib
        js = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "js"
        commun = (js / "floating-window.js").read_text(encoding="utf-8")
        self.assertIn("aEteModifiee", commun)
        self.assertNotIn("aDuContenu", commun)
        for fichier in ("post-dialog.js", "projet-dialog.js", "projet-informations-dialog.js"):
            with self.subTest(fichier=fichier):
                self.assertIn("attacherFermetureAuFond(dialog)", (js / fichier).read_text(encoding="utf-8"))

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

    def test_accueil_champ_projet_est_un_combobox_de_recherche(self):
        """Retour Fadhel (2026-09-28) : le champ "Projet" du composeur
        listait tous les projets dans un <select> natif, pénible à
        parcourir à mesure que leur nombre grandit — remplacé par un
        champ recherche (voir app/static/js/search-combobox.js), sur le
        même principe que le filtre d'Intervenant(s) (data-chip-filter)."""
        resp = self._get("/accueil")
        body = resp.data.decode()
        self.assertIn('data-search-combobox', body)
        self.assertIn('data-search-placeholder="Rechercher un projet…"', body)

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

    def test_list_projets_caste_lots_pour_le_filtre_exclusif(self):
        """Régression P0 (2026-09-28, retour Fadhel) : "Tous les projets"
        (et "Mes projets → Voir tout", qui pointe vers la même page) était
        cassée à CHAQUE chargement — 500 systématique. Cause : le filtre
        "lots" exclusif (Lot 3, 2026-09-27) subscriptait/mesurait
        %(lots)s sans caster, et quand aucun lot n'est choisi, psycopg2
        envoie un NULL non typé — `NULL[1]` et `array_length(NULL, 1)`
        sont des erreurs de SYNTAXE Postgres (contrairement à `x =
        ANY(NULL)`, qui infère son type via l'opérateur `=` et ne plante
        pas). Reproduit et corrigé en conditions réelles sur une base
        Postgres 16 de test (`NULL[1]` -> "syntax error at or near '['",
        exactement le traceback fourni par Fadhel). On ne peut pas
        exécuter du vrai SQL ici (psycopg2 indisponible dans ce bac à
        sable de test), donc on verrouille le texte de la requête."""
        import inspect

        from app.repositories import projets as projets_repo

        source = inspect.getsource(projets_repo.list_projets)
        self.assertIn("%(lots)s::text[] IS NULL", source)
        self.assertIn("array_length(%(lots)s::text[], 1)", source)
        self.assertIn("(%(lots)s::text[])[1]", source)
        self.assertIn("ANY(%(lots)s::text[])", source)

    def test_repartition_heures_par_role_branchee_partout(self):
        """Lot 5 (2026-09-28, retour Fadhel) : "répartition des heures par
        rôle (8h intervenant/5h chef) affichée dans Informations/liste
        projets/lignes de tâches" — verrouille que les 4 requêtes
        concernées lisent bien heures_chef/heures_intervenant (vues
        v_projet_heures_par_role/v_tache_heures_par_role, schema.sql —
        vérifiées séparément en vrai sur Postgres, voir migrations/
        0006_heures_par_role.sql)."""
        import inspect

        from app.repositories import projets as projets_repo
        from app.repositories import taches as taches_repo

        self.assertIn("heures_chef", inspect.getsource(projets_repo.list_projets))
        self.assertIn("heures_intervenant", inspect.getsource(projets_repo.list_projets))
        self.assertIn("v_projet_heures_par_role", inspect.getsource(projets_repo.get_projet))
        self.assertIn("v_tache_heures_par_role", inspect.getsource(taches_repo.list_taches_projet))
        self.assertIn("v_tache_heures_par_role", inspect.getsource(taches_repo.get_tache))

    def test_repartition_heures_affichee_sur_la_page_projet(self):
        """Rendu réel : "8/5 h" en clair = heures intervenants / heures chef
        de projet (retour Fadhel, J.docx, PR4) — en-tête, panneau
        Informations (PR5) et chaque ligne de tâche."""
        resp = self._get("/projets/1")
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        self.assertIn("302/180 h", body)             # en-tête
        self.assertIn("Heures intervenants", body)  # panneau Informations
        self.assertIn("Heures chef de projet", body)
        self.assertIn(">8/4 h<", body)              # tâche 5 : 8 h interv., 4 h chef

    def test_repartition_heures_affichee_sur_la_liste_projets(self):
        resp = self._get("/projets", **{
            "app.repositories.projets.list_projets": [{
                "id": 1, "code": "26099X", "nom": "Tour Meridian", "phase": "EXE",
                "date_debut": None, "date_fin": None,
                "chef_prenom": "Foulen", "chef_nom": "Chedly", "chef_id": 1, "lots": "GO",
                "heures_cumulees": 28.0, "heures_chef": 13.0, "heures_intervenant": 15.0,
                "prochaine_echeance": None, "etat": "en_cours",
            }],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(">15/13 h<", resp.data.decode())

    def test_repartition_heures_aucune_ligne_ne_plante_pas(self):
        """Même précaution que PROJET_SANS_HEURES/TACHE_SANS_HEURES pour
        heures_cumulees : un projet/une tâche sans aucune ligne DailyLog
        donne heures_chef/heures_intervenant = None (LEFT JOIN sur une vue
        vide), pas 0 — `default(0, true)` doit absorber ça sans 500."""
        resp = self._get("/projets/1", **{
            "app.repositories.projets.get_projet": PROJET_SANS_HEURES,
            "app.repositories.taches.list_taches_projet": [TACHE_SANS_HEURES],
        })
        self.assertEqual(resp.status_code, 200)

    def test_list_deadlines_exclut_les_projets_termines_ou_abandonnes(self):
        """PROMPT_CORRECTIONS.md P2 #23 : une tâche restée "en_cours" ou
        "bloque" sur un projet déjà "termine"/"abandonne" continuait
        d'apparaître dans les échéances — le projet, lui, ne bouge plus.
        Comme pour list_projets ci-dessus, on ne peut pas exécuter du vrai
        SQL ici (psycopg2 indisponible), donc on verrouille le texte de la
        requête."""
        import inspect

        from app.repositories import taches as taches_repo

        source = inspect.getsource(taches_repo.list_deadlines)
        self.assertIn("p.etat IN ('en_cours', 'bloque')", source)

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
        # PROMPT_CORRECTIONS.md P2 #24 : une tentative échouée est
        # maintenant enregistrée à la fois par email ET par IP — le
        # compteur "email" est lié à l'IP (audit n°2), pour qu'un tiers ne
        # puisse plus verrouiller le compte de quelqu'un d'autre.
        mock_enregistrer.assert_any_call("connexion", "fadhel@midgard.tn|127.0.0.1")
        mock_enregistrer.assert_any_call("connexion_ip", "127.0.0.1")
        self.assertEqual(mock_enregistrer.call_count, 2)

    def test_login_verrouillage_email_limite_a_lip_de_lattaquant(self):
        """Audit n°2 : 5 échecs depuis une autre IP ne doivent plus
        empêcher le vrai propriétaire de se connecter depuis son poste."""
        def compter(type_, cle, fenetre):
            # 5 échecs enregistrés pour cet email, mais depuis une autre IP.
            return 5 if cle == "fadhel@midgard.tn|10.0.0.99" else 0

        user_row = {**USER, "mot_de_passe_hash": "scrypt:bidon"}
        with patch("app.repositories.securite.compter_tentatives_recentes", side_effect=compter), \
             patch("app.auth.get_user_by_email", return_value=user_row), \
             patch("app.auth.verify_password", return_value=True), \
             patch("app.auth._verifier_rappel_dailylog"), \
             patch("app.repositories.notifications.compter_non_lues", return_value=0):
            resp = self.client.post(
                "/connexion", data={"email": "fadhel@midgard.tn", "password": "bon"},
            )
        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), 1)

    def test_login_rehache_un_ancien_hash_pbkdf2(self):
        """Audit n°2 : les comptes importés de Chronos (pbkdf2) sont
        re-hachés à la première connexion réussie."""
        user_row = {**USER, "mot_de_passe_hash": "pbkdf2:sha256:600000$sel$abc"}
        with patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.auth.get_user_by_email", return_value=user_row), \
             patch("app.auth.verify_password", return_value=True), \
             patch("app.auth._verifier_rappel_dailylog"), \
             patch("app.repositories.notifications.compter_non_lues", return_value=0), \
             patch("app.repositories.utilisateurs.set_password") as mock_set:
            self.client.post("/connexion", data={"email": "fadhel@midgard.tn", "password": "bon"})
        mock_set.assert_called_once()
        self.assertTrue(mock_set.call_args.args[1].startswith("scrypt:"))

    def test_login_ne_rehache_pas_un_hash_actuel(self):
        user_row = {**USER, "mot_de_passe_hash": "scrypt:32768:8:1$sel$abc"}
        with patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.auth.get_user_by_email", return_value=user_row), \
             patch("app.auth.verify_password", return_value=True), \
             patch("app.auth._verifier_rappel_dailylog"), \
             patch("app.repositories.notifications.compter_non_lues", return_value=0), \
             patch("app.repositories.utilisateurs.set_password") as mock_set:
            self.client.post("/connexion", data={"email": "fadhel@midgard.tn", "password": "bon"})
        mock_set.assert_not_called()

    def test_notification_ouvrir_nest_plus_accessible_en_get(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/notifications/10/ouvrir")
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 405)

    def test_entetes_de_securite(self):
        resp = self.client.get("/connexion")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("frame-ancestors 'none'", resp.headers.get("Content-Security-Policy", ""))

    def test_csp_renforcee(self):
        """Audit sécurité/qualité externe, 2026-09-28, item P0-6 : la CSP ne
        posait auparavant que frame-ancestors — vérifie que les directives
        ajoutées sont bien présentes, et que la page de connexion (aucun
        script/style externe non prévu) n'en dépend pas pour s'afficher."""
        resp = self.client.get("/connexion")
        csp = resp.headers.get("Content-Security-Policy", "")
        for directive in (
            "default-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "connect-src 'self'",
            "img-src 'self' data: blob:",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
        ):
            self.assertIn(directive, csp)
        self.assertEqual(resp.status_code, 200)

    def test_fichier_statique_sans_requete_sql(self):
        """Audit n°2 : chaque fichier CSS/JS coûtait 3 requêtes SQL."""
        self._login()
        with patch("app.auth.get_user_by_id") as mock_user, \
             patch("app.repositories.notifications.compter_non_lues") as mock_notifs:
            resp = self.client.get("/static/css/app.css")
            resp.close()
        self.assertEqual(resp.status_code, 200)
        mock_user.assert_not_called()
        mock_notifs.assert_not_called()

    def test_login_bloque_apres_trop_de_tentatives_par_ip(self):
        """PROMPT_CORRECTIONS.md P2 #24 : au-delà de MAX_TENTATIVES_IP
        échecs récents pour une même IP (même avec des emails différents à
        chaque fois), on n'interroge plus la base non plus."""
        def compter(type_, cle, fenetre):
            return 30 if type_ == "connexion_ip" else 0

        with patch("app.repositories.securite.compter_tentatives_recentes", side_effect=compter), \
             patch("app.auth.get_user_by_email") as mock_get_user:
            resp = self.client.post(
                "/connexion",
                data={"email": "quelquun@midgard.tn", "password": "peu-importe"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Trop de tentatives", resp.data.decode())
        mock_get_user.assert_not_called()

    def test_login_email_inconnu_compare_a_un_hash_factice(self):
        """PROMPT_CORRECTIONS.md P2 #24 : même sans compte correspondant,
        verify_password() doit être appelée (temps de réponse comparable à
        un email existant) — sinon le temps de réponse permettrait de
        deviner quels emails sont des comptes réels."""
        with patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.repositories.securite.enregistrer_tentative"), \
             patch("app.auth.get_user_by_email", return_value=None), \
             patch("app.auth.verify_password", return_value=False) as mock_verify:
            self.client.post(
                "/connexion",
                data={"email": "inconnu@midgard.tn", "password": "peu-importe"},
            )
        mock_verify.assert_called_once()
        self.assertEqual(mock_verify.call_args.args[0], "peu-importe")

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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
                p.stop()
        self.assertIn("R\xf4le invalide".encode(), resp.data)
        mock_update.assert_not_called()

    def test_fiche_rejette_une_date_embauche_invalide(self):
        """Même correctif que creer() (audit sécurité/qualité externe,
        2026-09-28, relecture Luna round 4) : date_embauche n'était pas
        validée du tout côté applicatif dans fiche() non plus."""
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
                        "role": "intervenant", "equipe_code": "URBS",
                        "date_embauche": "n-importe-quoi",
                    },
                )
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertIn("embauche invalide".encode(), resp.data)
        mock_update.assert_not_called()

    def test_fiche_passe_la_date_embauche_validee_a_update_utilisateur_complet(self):
        """Contre-épreuve : update_utilisateur_complet() doit recevoir un
        objet datetime.date (la valeur validée), pas la chaîne brute du
        formulaire."""
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
                        "role": "intervenant", "equipe_code": "URBS",
                        "date_embauche": "2026-09-28",
                    },
                    follow_redirects=True,
                )
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertIn("mise \xe0 jour".encode(), resp.data)
        mock_update.assert_called_once()
        self.assertEqual(mock_update.call_args.kwargs["date_embauche"], datetime.date(2026, 9, 28))

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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
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
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        self.assertIn(b"Wael", resp.data)
        self.assertIn("Lecture seule".encode(), resp.data)
        # Seul formulaire autorisé : la déconnexion de la barre du haut
        # (base.html, en POST depuis PROMPT_CORRECTIONS.md P2 #25) — la
        # fiche elle-même ne doit en contenir aucun.
        contenu_page = resp.data.split(b'class="page-body', 1)[1]
        self.assertNotIn(b"<form", contenu_page)

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
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        mock_update.assert_not_called()


class TestControlesDAccesStricts(unittest.TestCase):
    """Audit n°2 (tests de mutation) : plusieurs tests de contrôle d'accès
    restaient verts même quand le contrôle était SUPPRIMÉ — ils ne
    vérifiaient qu'un code 302, que le chemin "succès" renvoie aussi, ou
    un 404 dû à un fichier de test inexistant. Ici, chaque refus vérifie
    que l'action protégée n'a JAMAIS été exécutée, et chaque
    téléchargement porte sur un vrai fichier (seul le contrôle d'accès
    peut alors expliquer un 404)."""

    _login = SmokeTestCase._login
    _patched = SmokeTestCase._patched
    _get = SmokeTestCase._get

    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self._login()

    def _requete(self, methode, chemin, espion, data=None, **overrides):
        """Exécute la requête avec les mocks par défaut (+ overrides) et un
        espion sur `espion` ; renvoie (réponse, espion)."""
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        try:
            with patch(espion) as mock_espion:
                resp = getattr(self.client, methode)(chemin, data=data or {})
        finally:
            for p in reversed(patchers):
                p.stop()
        return resp, mock_espion

    # --- Tâches : changer l'état / clôturer (P0 #2) ---
    NI_CHEF_NI_INTERVENANT = {
        "app.repositories.projets.user_can_manage": False,
        "app.repositories.taches.user_est_intervenant": False,
    }

    def test_changer_etat_refuse_nexecute_rien(self):
        resp, set_etat = self._requete(
            "post", "/projets/1/taches/5/etat", "app.repositories.taches.set_etat",
            {"etat": "verifie"}, **self.NI_CHEF_NI_INTERVENANT,
        )
        self.assertEqual(resp.status_code, 302)
        set_etat.assert_not_called()

    def test_changer_etat_projet_invisible_404(self):
        resp, set_etat = self._requete(
            "post", "/projets/1/taches/5/etat", "app.repositories.taches.set_etat",
            {"etat": "verifie"}, **{"app.repositories.projets.user_can_view": False},
        )
        self.assertEqual(resp.status_code, 404)
        set_etat.assert_not_called()

    def test_changer_etat_valeur_invalide_nexecute_rien(self):
        _, set_etat = self._requete(
            "post", "/projets/1/taches/5/etat", "app.repositories.taches.set_etat", {"etat": "termine"},
        )
        set_etat.assert_not_called()

    def test_cloturer_refuse_nexecute_rien(self):
        resp, close = self._requete(
            "post", "/projets/1/taches/5/cloturer", "app.repositories.taches.close_tache",
            {"type_code": "envoi"}, **self.NI_CHEF_NI_INTERVENANT,
        )
        self.assertEqual(resp.status_code, 302)
        close.assert_not_called()

    def test_cloturer_projet_invisible_404(self):
        resp, close = self._requete(
            "post", "/projets/1/taches/5/cloturer", "app.repositories.taches.close_tache",
            {"type_code": "envoi"}, **{"app.repositories.projets.user_can_view": False},
        )
        self.assertEqual(resp.status_code, 404)
        close.assert_not_called()

    def test_cloturer_tag_invalide_nexecute_rien(self):
        _, close = self._requete(
            "post", "/projets/1/taches/5/cloturer", "app.repositories.taches.close_tache",
            {"type_code": "inconnu"},
        )
        close.assert_not_called()

    def test_cloturer_autorise_appelle_bien_close_tache(self):
        """Contre-épreuve : sans elle, les tests ci-dessus passeraient même
        si la route n'appelait jamais close_tache."""
        _, close = self._requete(
            "post", "/projets/1/taches/5/cloturer", "app.repositories.taches.close_tache",
            {"type_code": "envoi"},
        )
        close.assert_called_once()

    # --- Création de tâche / ajout d'intervenant : chef ou co-chef ---
    def test_creer_tache_non_gestionnaire_nexecute_rien(self):
        _, create = self._requete(
            "post", "/projets/1/taches", "app.repositories.taches.create_tache", {"titre": "T"},
            **{"app.repositories.projets.user_can_manage": False},
        )
        create.assert_not_called()

    def test_ajouter_intervenant_non_gestionnaire_nexecute_rien(self):
        _, add = self._requete(
            "post", "/projets/1/intervenants", "app.repositories.projets.add_intervenant",
            {"utilisateur_id": "3"}, **{"app.repositories.projets.user_can_manage": False},
        )
        add.assert_not_called()

    def test_ajouter_intervenant_projet_invisible_404(self):
        resp, add = self._requete(
            "post", "/projets/1/intervenants", "app.repositories.projets.add_intervenant",
            {"utilisateur_id": "3"}, **{"app.repositories.projets.user_can_view": False},
        )
        self.assertEqual(resp.status_code, 404)
        add.assert_not_called()

    def test_ajouter_intervenant_compte_desactive_nexecute_rien(self):
        """Audit sécurité/qualité externe, 2026-09-28, item P1-3 : un compte
        désactivé (actif=false) ne doit jamais pouvoir devenir intervenant,
        même via une requête forgée directement sur cette route (la liste du
        formulaire normal, list_actifs, ne propose que des comptes actifs —
        mais rien ne le revérifiait côté serveur avant ce correctif)."""
        resp, add = self._requete(
            "post", "/projets/1/intervenants", "app.repositories.projets.add_intervenant",
            {"utilisateur_id": "3"},
            **{"app.repositories.utilisateurs.get_utilisateur": {**AUTRE_UTILISATEUR, "id": 3, "actif": False}},
        )
        self.assertEqual(resp.status_code, 302)
        add.assert_not_called()

    def test_ajouter_intervenant_compte_inexistant_nexecute_rien(self):
        resp, add = self._requete(
            "post", "/projets/1/intervenants", "app.repositories.projets.add_intervenant",
            {"utilisateur_id": "999"},
            **{"app.repositories.utilisateurs.get_utilisateur": None},
        )
        self.assertEqual(resp.status_code, 302)
        add.assert_not_called()

    # --- "Rejoindre ce projet" / "rejoindre cette tâche" (retour Fadhel,
    # 2026-09-28) : ajout immédiat de SOI-MÊME comme intervenant, sans
    # validation d'un chef/co-chef — à la différence de ajouter_intervenant
    # ci-dessus (qui ajoute quelqu'un d'autre et exige user_can_manage). ---
    def test_rejoindre_projet_ajoute_lutilisateur_connecte(self):
        _, add = self._requete("post", "/projets/1/rejoindre", "app.repositories.projets.add_intervenant")
        add.assert_called_once_with(1, USER["id"], USER["id"])

    def test_rejoindre_projet_deja_rattache_nexecute_rien(self):
        _, add = self._requete(
            "post", "/projets/1/rejoindre", "app.repositories.projets.add_intervenant",
            **{"app.repositories.projets.user_est_rattache": True},
        )
        add.assert_not_called()

    def test_rejoindre_projet_rh_refuse(self):
        _, add = self._requete(
            "post", "/projets/1/rejoindre", "app.repositories.projets.add_intervenant",
            **{"app.auth.get_user_by_id": {**USER, "role": "rh"}},
        )
        add.assert_not_called()

    def test_rejoindre_projet_invisible_404(self):
        resp, add = self._requete(
            "post", "/projets/1/rejoindre", "app.repositories.projets.add_intervenant",
            **{"app.repositories.projets.user_can_view": False},
        )
        self.assertEqual(resp.status_code, 404)
        add.assert_not_called()

    def test_rejoindre_tache_ajoute_lutilisateur_connecte(self):
        _, add = self._requete(
            "post", "/projets/1/taches/5/rejoindre", "app.repositories.taches.add_intervenant",
        )
        add.assert_called_once_with(5, 1, USER["id"], USER["id"])

    def test_rejoindre_tache_deja_intervenant_nexecute_rien(self):
        _, add = self._requete(
            "post", "/projets/1/taches/5/rejoindre", "app.repositories.taches.add_intervenant",
            **{"app.repositories.taches.user_est_intervenant": True},
        )
        add.assert_not_called()

    def test_rejoindre_tache_rh_refuse(self):
        _, add = self._requete(
            "post", "/projets/1/taches/5/rejoindre", "app.repositories.taches.add_intervenant",
            **{"app.auth.get_user_by_id": {**USER, "role": "rh"}},
        )
        add.assert_not_called()

    def test_rejoindre_tache_projet_invisible_404(self):
        resp, add = self._requete(
            "post", "/projets/1/taches/5/rejoindre", "app.repositories.taches.add_intervenant",
            **{"app.repositories.projets.user_can_view": False},
        )
        self.assertEqual(resp.status_code, 404)
        add.assert_not_called()

    def test_page_projet_bouton_rejoindre_projet_visible_si_non_rattache(self):
        body = self._get(
            "/projets/1", **{"app.repositories.projets.user_est_rattache": False},
        ).data.decode()
        self.assertIn("Rejoindre ce projet", body)

    def test_page_projet_bouton_rejoindre_projet_masque_si_deja_rattache(self):
        body = self._get(
            "/projets/1", **{"app.repositories.projets.user_est_rattache": True},
        ).data.decode()
        self.assertNotIn("Rejoindre ce projet", body)

    def test_page_projet_bouton_rejoindre_projet_masque_pour_rh(self):
        body = self._get(
            "/projets/1",
            **{
                "app.auth.get_user_by_id": {**USER, "role": "rh"},
                "app.repositories.projets.user_est_rattache": False,
            },
        ).data.decode()
        self.assertNotIn("Rejoindre ce projet", body)

    def test_page_projet_bouton_rejoindre_tache_selon_intervenants(self):
        """TACHES_PROJET : la tâche 5 a déjà l'utilisateur connecté (id=1)
        comme intervenant, la tâche 6 n'a aucun intervenant — le bouton ne
        doit apparaître QUE pour la tâche 6 (une seule occurrence)."""
        body = self._get("/projets/1").data.decode()
        self.assertEqual(body.count('action="/projets/1/taches/5/rejoindre"'), 0)
        self.assertEqual(body.count('action="/projets/1/taches/6/rejoindre"'), 1)

    def test_page_projet_entree_points_nouveau_post_consolides(self):
        """Retour Fadhel, 2026-09-28 (captures annotées) : la carte verte
        "Nouveau post" de la colonne gauche et les boutons rapides
        "+ Information"/"+ Requête" au-dessus du tableau des tâches sont
        retirés — seuls "+ Tâche" (au-dessus du tableau) et "+ Nouveau
        post" (près du filtre des posts) restent. Les titres ci-dessous
        sont uniques à ces boutons (le rebond de post_card.html, qui a
        lui aussi un "+ Requête", n'a pas d'attribut title)."""
        body = self._get("/projets/1").data.decode()
        self.assertNotIn("Poster une information", body)
        self.assertNotIn('title="Créer une requête sur ce projet"', body)
        self.assertIn('title="Créer une tâche sur ce projet"', body)
        self.assertIn("+ Nouveau post", body)

    def test_projets_liste_bouton_nouveau_projet_ouvre_la_fenetre_flottante(self):
        """Retour Fadhel, 2026-09-28 : "+ Nouveau projet" n'est plus un
        lien vers une page séparée mais ouvre partials/projet_dialog.html,
        même principe que "+ Nouveau post" — voir aussi projet_creer.html
        (conservée comme repli automatique en cas d'erreur de validation)."""
        body = self._get("/projets").data.decode()
        self.assertIn("data-open-projet-dialog", body)
        self.assertIn('id="dialog-nouveau-projet"', body)
        self.assertNotIn('<a href="/projets/nouveau"', body)

    # --- Fenêtre "Informations" du projet (retour Fadhel, 2026-09-28, Lot 5) ---

    def test_page_projet_bouton_informations_visible_si_peut_gerer(self):
        body = self._get("/projets/1", **{"app.repositories.projets.user_can_manage": True}).data.decode()
        self.assertIn("data-open-informations-dialog", body)
        self.assertIn('id="dialog-informations-projet"', body)
        # Préremplie avec les valeurs actuelles du projet (PROJET : nom
        # "Tour Meridian", état "bloque").
        self.assertIn('value="Tour Meridian"', body)
        self.assertIn('value="bloque" selected', body)

    def test_page_projet_bouton_informations_masque_si_ne_peut_pas_gerer(self):
        body = self._get("/projets/1", **{"app.repositories.projets.user_can_manage": False}).data.decode()
        self.assertNotIn("data-open-informations-dialog", body)
        self.assertNotIn('id="dialog-informations-projet"', body)

    def test_editer_informations_modifie_le_projet(self):
        resp, update = self._requete(
            "post", "/projets/1/informations", "app.repositories.projets.update_projet",
            {
                "nom": "Tour Meridian — révisé", "etat": "termine", "lots": ["GO"],
                "date_debut": "2025-02-03", "date_fin": "2026-10-01", "phase_liee_id": "",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["Location"], "/projets/1")
        update.assert_called_once()
        _, kwargs = update.call_args
        self.assertEqual(kwargs["nom"], "Tour Meridian — révisé")
        self.assertEqual(kwargs["etat"], "termine")
        self.assertEqual(kwargs["lots"], ["GO"])
        self.assertIsNone(kwargs["phase_liee_id"])

    def test_editer_informations_refuse_si_ne_peut_pas_gerer(self):
        resp, update = self._requete(
            "post", "/projets/1/informations", "app.repositories.projets.update_projet",
            {"nom": "X", "etat": "en_cours", "lots": []},
            **{"app.repositories.projets.user_can_manage": False},
        )
        self.assertEqual(resp.status_code, 302)
        update.assert_not_called()

    def test_editer_informations_projet_invisible_404(self):
        resp, update = self._requete(
            "post", "/projets/1/informations", "app.repositories.projets.update_projet",
            {"nom": "X", "etat": "en_cours", "lots": []},
            **{"app.repositories.projets.user_can_view": False},
        )
        self.assertEqual(resp.status_code, 404)
        update.assert_not_called()

    def test_editer_informations_etat_invalide_nexecute_rien(self):
        _, update = self._requete(
            "post", "/projets/1/informations", "app.repositories.projets.update_projet",
            {"nom": "X", "etat": "pas-un-etat", "lots": []},
        )
        update.assert_not_called()

    def test_editer_informations_lot_invalide_nexecute_rien(self):
        _, update = self._requete(
            "post", "/projets/1/informations", "app.repositories.projets.update_projet",
            {"nom": "X", "etat": "en_cours", "lots": ["ZZ"]},
        )
        update.assert_not_called()

    def test_editer_informations_nom_vide_nexecute_rien(self):
        _, update = self._requete(
            "post", "/projets/1/informations", "app.repositories.projets.update_projet",
            {"nom": "  ", "etat": "en_cours", "lots": []},
        )
        update.assert_not_called()

    def test_editer_informations_phase_liee_invisible_nexecute_rien(self):
        """Contrôle IDOR (même famille que P0 #1) : on ne doit pas pouvoir
        relier un projet à un id de "phase liée" qu'on ne peut pas voir.
        `user_can_view` doit renvoyer True pour le projet 1 (sinon 404
        avant même d'atteindre la validation de phase_liee_id) et False
        pour le 999 visé comme "phase liée" — nécessite un side_effect,
        pas juste un return_value statique, donc patché à la main plutôt
        que via _requete/_patched."""
        patchers = self._patched(
            **{"app.repositories.projets.user_can_view": True}
        )
        for p in patchers:
            p.start()
        try:
            with patch(
                "app.repositories.projets.user_can_view",
                side_effect=lambda projet_id, user_id: projet_id == 1,
            ), patch("app.repositories.projets.update_projet") as update:
                resp = self.client.post(
                    "/projets/1/informations",
                    data={"nom": "X", "etat": "en_cours", "lots": [], "phase_liee_id": "999"},
                )
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302)
        update.assert_not_called()

    # --- Pièces jointes (P0 #1) : un VRAI fichier sur disque ---
    def _ecrire_fichier(self, chemin_relatif):
        chemin = pathlib.Path(self.app.config["UPLOAD_DIR"]) / chemin_relatif
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(b"%PDF-1.4 contenu de test")
        self.addCleanup(chemin.unlink)

    def _telecharger(self, url, visible):
        patchers = self._patched(**{"app.repositories.projets.user_can_view": visible})
        for p in patchers:
            p.start()
        try:
            return self.client.get(url)
        finally:
            for p in reversed(patchers):
                p.stop()

    def test_telechargement_tache_accorde_puis_refuse(self):
        self._ecrire_fichier(PIECE_JOINTE_TACHE["chemin"])
        ok = self._telecharger("/fichiers/taches/1", True)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.data, b"%PDF-1.4 contenu de test")
        ok.close()
        self.assertEqual(self._telecharger("/fichiers/taches/1", False).status_code, 404)

    def test_telechargement_post_accorde_puis_refuse(self):
        self._ecrire_fichier(PIECE_JOINTE_POST["chemin"])
        ok = self._telecharger("/fichiers/posts/1", True)
        self.assertEqual(ok.status_code, 200)
        ok.close()
        self.assertEqual(self._telecharger("/fichiers/posts/1", False).status_code, 404)

    def test_upload_tache_projet_invisible_nenregistre_rien(self):
        resp, save = self._requete(
            "post", "/fichiers/taches/5/upload", "app.routes.fichiers.save_upload",
            {"fichier": (io.BytesIO(b"x"), "note.pdf")},
            **{"app.repositories.projets.user_can_view": False},
        )
        self.assertEqual(resp.status_code, 404)
        save.assert_not_called()

    # --- Posts : réactions, commentaires, mentions ---
    def test_reagir_projet_invisible_nexecute_rien(self):
        resp, react = self._requete(
            "post", "/posts/1/reagir", "app.repositories.posts.react", {"reaction_code": "pouce"},
            **{"app.repositories.projets.user_can_view": False},
        )
        self.assertEqual(resp.status_code, 404)
        react.assert_not_called()

    def test_reagir_code_hors_liste_nexecute_rien(self):
        _, react = self._requete(
            "post", "/posts/1/reagir", "app.repositories.posts.react", {"reaction_code": "inconnu"},
        )
        react.assert_not_called()

    def test_retirer_reaction_projet_invisible_nexecute_rien(self):
        resp, remove = self._requete(
            "post", "/posts/1/reagir/supprimer", "app.repositories.posts.remove_reaction",
            **{"app.repositories.projets.user_can_view": False},
        )
        self.assertEqual(resp.status_code, 404)
        remove.assert_not_called()

    def test_commenter_projet_invisible_nexecute_rien(self):
        resp, add = self._requete(
            "post", "/posts/1/commenter", "app.repositories.posts.add_comment", {"contenu": "x"},
            **{"app.repositories.projets.user_can_view": False},
        )
        self.assertEqual(resp.status_code, 404)
        add.assert_not_called()

    def test_mentions_filtrees_aux_personnes_qui_voient_le_projet(self):
        def peut_voir(projet_id, user_id):
            return user_id in (1, 2)  # l'auteur (1) et la personne 2 ; pas la 3

        patchers = self._patched() + [
            patch("app.repositories.projets.user_can_view", side_effect=peut_voir),
        ]
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.posts.create_post", return_value=101) as create:
                self.client.post("/posts", data={
                    "projet_id": "1", "type_code": "requete", "contenu": "x", "mentions": ["2", "3"],
                })
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(create.call_args.kwargs["mentionne_ids"], [2])


class CsrfTestConfig(TestConfig):
    WTF_CSRF_ENABLED = True


class TestProtectionCSRF(unittest.TestCase):
    """PROMPT_CORRECTIONS.md P2 #25 : protection CSRF (Flask-WTF) réellement
    active — un POST sans jeton est refusé, avec le jeton (champ caché ou
    en-tête X-CSRFToken) il passe, et /deconnexion n'accepte plus le GET."""

    _login = SmokeTestCase._login
    _patched = SmokeTestCase._patched

    def setUp(self):
        self.app = create_app(CsrfTestConfig)
        self.client = self.app.test_client()
        self._login()
        self.patchers = self._patched()
        for p in self.patchers:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patchers])

    def _jeton(self):
        """Jeton tel qu'un navigateur le reçoit : rendu dans la page (le
        GET enregistre aussi sa version signée dans la session)."""
        resp = self.client.get("/notifications")
        self.assertEqual(resp.status_code, 200)
        m = re.search(rb'name="csrf_token" value="([^"]+)"', resp.data)
        self.assertIsNotNone(m, "champ caché csrf_token absent de la page")
        return m.group(1).decode()

    def test_post_sans_jeton_est_refuse(self):
        with patch("app.repositories.notifications.marquer_toutes_lues") as mock_marquer:
            resp = self.client.post("/notifications/marquer-toutes-lues")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accueil", resp.headers["Location"])
        mock_marquer.assert_not_called()

    def test_post_avec_jeton_invalide_est_refuse(self):
        self._jeton()
        with patch("app.repositories.notifications.marquer_toutes_lues") as mock_marquer:
            resp = self.client.post("/notifications/marquer-toutes-lues",
                                    data={"csrf_token": "faux-jeton"})
        self.assertEqual(resp.status_code, 302)
        mock_marquer.assert_not_called()

    def test_refus_renvoie_vers_la_page_dorigine(self):
        resp = self.client.post("/notifications/marquer-toutes-lues",
                                headers={"Referer": "http://localhost/projets/1"})
        self.assertEqual(resp.headers["Location"], "/projets/1")

    def test_refus_ne_redirige_jamais_hors_du_site(self):
        resp = self.client.post("/notifications/marquer-toutes-lues",
                                headers={"Referer": "http://evil.tld/projets/1"})
        self.assertNotIn("evil.tld", resp.headers["Location"])

    def test_post_avec_jeton_dans_le_formulaire_passe(self):
        jeton = self._jeton()
        with patch("app.repositories.notifications.marquer_toutes_lues") as mock_marquer:
            resp = self.client.post("/notifications/marquer-toutes-lues",
                                    data={"csrf_token": jeton})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/notifications", resp.headers["Location"])
        mock_marquer.assert_called_once()

    def test_post_avec_jeton_en_entete_passe(self):
        """Chemin utilisé par les appels fetch() (en-tête ajouté par base.html)."""
        jeton = self._jeton()
        with patch("app.repositories.notifications.marquer_toutes_lues") as mock_marquer:
            resp = self.client.post("/notifications/marquer-toutes-lues",
                                    headers={"X-CSRFToken": jeton})
        self.assertEqual(resp.status_code, 302)
        mock_marquer.assert_called_once()

    def test_page_expose_le_jeton_pour_fetch(self):
        resp = self.client.get("/notifications")
        self.assertIn(b'<meta name="csrf-token" content="', resp.data)
        self.assertIn(b"X-CSRFToken", resp.data)

    def test_tous_les_formulaires_post_portent_le_jeton(self):
        """Garde-fou statique : chaque <form method="post"> des templates
        doit contenir le champ caché csrf_token."""
        racine = pathlib.Path(__file__).resolve().parent.parent / "app" / "templates"
        # Guillemets simples/doubles ou sans guillemets (audit n°2).
        form_re = re.compile(r'<form\b[^>]*method=["\']?post\b[^>]*>(.*?)</form>', re.I | re.S)
        manquants = []
        for tpl in sorted(racine.rglob("*.html")):
            for m in form_re.finditer(tpl.read_text()):
                if "csrf_token()" not in m.group(1):
                    manquants.append(tpl.name)
        self.assertEqual(manquants, [])

    def test_deconnexion_en_get_nest_plus_acceptee(self):
        resp = self.client.get("/deconnexion")
        self.assertEqual(resp.status_code, 405)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), 1)

    def test_deconnexion_en_post_sans_jeton_est_refusee(self):
        resp = self.client.post("/deconnexion")
        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), 1)

    def test_deconnexion_en_post_avec_jeton(self):
        jeton = self._jeton()
        resp = self.client.post("/deconnexion", data={"csrf_token": jeton})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/connexion", resp.headers["Location"])
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)


class TestReverseProxy(unittest.TestCase):
    """Audit n°2 : derrière un reverse proxy, sans ProxyFix, tout le monde
    avait l'IP du proxy (limite de connexions par IP partagée). Les
    en-têtes X-Forwarded-* ne sont crus que si TRUSTED_PROXY_COUNT > 0."""

    def _ip_vue_par_la_connexion(self, nb_proxys):
        class ConfigProxy(TestConfig):
            TRUSTED_PROXY_COUNT = nb_proxys

        client = create_app(ConfigProxy).test_client()
        with patch("app.repositories.securite.compter_tentatives_recentes", return_value=0), \
             patch("app.auth.get_user_by_email", return_value=None), \
             patch("app.repositories.securite.enregistrer_tentative") as mock_enregistrer:
            client.post(
                "/connexion", data={"email": "x@y.tn", "password": "z"},
                headers={"X-Forwarded-For": "203.0.113.7"},
            )
        return [c.args[1] for c in mock_enregistrer.call_args_list if c.args[0] == "connexion_ip"]

    def test_ip_reelle_derriere_un_proxy_de_confiance(self):
        self.assertEqual(self._ip_vue_par_la_connexion(1), ["203.0.113.7"])

    def test_en_tete_ignore_sans_proxy_de_confiance(self):
        self.assertEqual(self._ip_vue_par_la_connexion(0), ["127.0.0.1"])


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
            UPLOAD_DIR = _UPLOAD_DIR_TESTS

        create_app(ConfigOk)  # ne doit pas lever


class TestVerifierRappelDailylog(unittest.TestCase):
    """_verifier_rappel_dailylog est testée isolément (sans passer par une
    vraie requête HTTP) : logique de décision pure, seules les fonctions de
    repository qu'elle appelle sont simulées."""

    def test_cree_le_rappel_quand_veille_non_remplie(self):
        from app.auth import _verifier_rappel_dailylog

        mardi = datetime.date(2026, 9, 15)  # veille = lundi 14, pas un dimanche
        with patch("app.repositories.dailylog.jour_renseigne", return_value=False), \
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
        with patch("app.repositories.dailylog.jour_renseigne", return_value=True), \
             patch("app.repositories.notifications.a_deja_un_rappel_dailylog", return_value=False), \
             patch("app.repositories.notifications.creer") as mock_creer:
            _verifier_rappel_dailylog(1, aujourdhui=mardi)
        mock_creer.assert_not_called()

    def test_ne_cree_rien_si_rappel_deja_envoye_aujourdhui(self):
        from app.auth import _verifier_rappel_dailylog

        mardi = datetime.date(2026, 9, 15)
        with patch("app.repositories.dailylog.jour_renseigne", return_value=False), \
             patch("app.repositories.notifications.a_deja_un_rappel_dailylog", return_value=True), \
             patch("app.repositories.notifications.creer") as mock_creer:
            _verifier_rappel_dailylog(1, aujourdhui=mardi)
        mock_creer.assert_not_called()

    def test_ne_cree_rien_un_lundi_pour_un_dimanche(self):
        from app.auth import _verifier_rappel_dailylog

        lundi = datetime.date(2026, 9, 14)  # veille = dimanche 13
        with patch("app.repositories.dailylog.jour_renseigne") as mock_list, \
             patch("app.repositories.notifications.creer") as mock_creer:
            _verifier_rappel_dailylog(1, aujourdhui=lundi)
        mock_list.assert_not_called()
        mock_creer.assert_not_called()

    def test_ne_cree_rien_un_dimanche_pour_un_samedi(self):
        """Régression (2026-09-19, retour Fadhel) : le week-end complet doit
        être ignoré, pas seulement le dimanche — voir _verifier_rappel_dailylog."""
        from app.auth import _verifier_rappel_dailylog

        dimanche = datetime.date(2026, 9, 20)  # veille = samedi 19
        with patch("app.repositories.dailylog.jour_renseigne") as mock_list, \
             patch("app.repositories.notifications.creer") as mock_creer:
            _verifier_rappel_dailylog(1, aujourdhui=dimanche)
        mock_list.assert_not_called()
        mock_creer.assert_not_called()


class TestJournalAudit(unittest.TestCase):
    """Lot 5 (retour Fadhel, 2026-09-28) : page admin de parcours du
    journal d'audit — aucune nouvelle infrastructure (audit_log + triggers
    existent depuis le premier schéma), seulement une page Admin-only."""

    _login = SmokeTestCase._login
    _patched = SmokeTestCase._patched
    _get = SmokeTestCase._get

    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def test_admin_voit_le_journal(self):
        resp = self._get("/admin/journal")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Journal d", resp.data)

    def test_requete_type_les_dates_pour_postgres(self):
        """Bug du 2026-09-29 ("l'onglet Log ne marche pas") : sans filtre de
        date, « NULL + interval '1 day' » faisait échouer la requête dans
        Postgres (500 à l'ouverture de la page). Les tests de fumée ne
        touchent pas de vraie base : verrou textuel sur le correctif,
        vérifié en réel sur PostgreSQL 16 à la livraison."""
        import inspect
        from app.repositories import audit
        src = inspect.getsource(audit.list_entrees)
        self.assertIn("%(date_fin)s::date + interval '1 day'", src)
        self.assertIn("%(date_debut)s::date IS NULL", src)
        self.assertNotIn("%(date_fin)s + interval", src)

    def test_toutes_les_tables_auditees_sont_filtrables(self):
        """Chaque table qui a un trigger d'audit dans schema.sql doit être
        proposée dans le filtre "Table" de la page."""
        import pathlib, re
        from app.repositories import audit
        schema = (pathlib.Path(__file__).resolve().parent.parent / "schema.sql").read_text(encoding="utf-8")
        # ^ : ignore les triggers en commentaire (post_reaction n'est pas
        # audité) ; égalité dans les deux sens : pas de table proposée au
        # filtre qui ne pourrait jamais rien afficher.
        tables = set(re.findall(r"^CREATE TRIGGER trg_audit_\w+ AFTER INSERT OR UPDATE OR DELETE ON (\w+)", schema, re.M))
        self.assertTrue(tables)
        self.assertEqual(tables, set(audit.TABLES_AUDITEES))

    def test_non_admin_refuse_et_nexecute_rien(self):
        """Un chef de projet (ou tout rôle non-admin) est redirigé par
        role_required AVANT d'atteindre le repository — vérifié via un
        espion plutôt qu'un simple code 302 (audit n°2, voir
        TestControlesDAccesStricts)."""
        utilisateur_non_admin = dict(USER, role="chef_de_projet")
        self._login()
        patchers = self._patched(**{
            "app.auth.get_user_by_id": utilisateur_non_admin,
        })
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.audit.list_entrees") as mock_liste:
                resp = self.client.get("/admin/journal")
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302)
        mock_liste.assert_not_called()

    def test_filtre_table_invalide_ignore_silencieusement(self):
        """Une valeur hors TABLES_AUDITEES dans l'URL (bidouillée à la
        main) ne doit pas être transmise telle quelle au repository —
        sinon un filtre toujours faux, silencieusement (jamais une
        200/erreur visible)."""
        resp = self._get("/admin/journal?table=DROP+TABLE")
        self.assertEqual(resp.status_code, 200)

    def test_date_invalide_ignoree_plutot_que_500(self):
        resp = self._get("/admin/journal?date_debut=n-importe-quoi")
        self.assertEqual(resp.status_code, 200)

    def test_icone_journal_visible_seulement_pour_admin(self):
        resp = self._get("/accueil")
        self.assertIn(b'href="/admin/journal"', resp.data)

    def test_icone_journal_absente_pour_non_admin(self):
        utilisateur_non_admin = dict(USER, role="intervenant")
        self._login()
        patchers = self._patched(**{"app.auth.get_user_by_id": utilisateur_non_admin})
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/accueil")
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertNotIn(b'href="/admin/journal"', resp.data)


class TestProfilPersonne(unittest.TestCase):
    """Lot 5 (retour Fadhel, 2026-09-28) : page de profil d'une personne,
    ouverte à tout utilisateur connecté (contrairement à la fiche RH),
    reliée à la recherche topbar."""

    _login = SmokeTestCase._login
    _patched = SmokeTestCase._patched
    _get = SmokeTestCase._get

    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def test_page_visible_par_nimporte_quel_role_connecte(self):
        """Contrairement à /utilisateurs (fiche/liste), un simple
        intervenant peut ouvrir le profil de n'importe qui."""
        utilisateur_intervenant = dict(USER, role="intervenant")
        self._login()
        patchers = self._patched(**{"app.auth.get_user_by_id": utilisateur_intervenant})
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/utilisateurs/1/profil")
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Foulen", resp.data)

    def test_utilisateur_introuvable_redirige(self):
        resp = self._get("/utilisateurs/999/profil", **{
            "app.repositories.utilisateurs.get_utilisateur": None,
        })
        self.assertEqual(resp.status_code, 302)

    def test_dailylog_filtre_aux_projets_visibles_par_le_visiteur(self):
        """IDOR (PROMPT_CORRECTIONS.md P0 #1) : une entrée DailyLog sur un
        projet que LE VISITEUR ne peut pas voir doit disparaître de son
        profil, même si la personne consultée peut le voir, elle."""
        entree_visible = {"id": 1, "projet_id": 1, "tache_id": None, "heures": 5.0,
                           "projet_nom": "Tour Meridian", "tache_titre": None}
        entree_masquee = {"id": 2, "projet_id": 99, "tache_id": None, "heures": 3.0,
                           "projet_nom": "Projet d'une autre équipe", "tache_titre": None}
        resp = self._get("/utilisateurs/1/profil", **{
            "app.repositories.dailylog.list_entrees_jour": [entree_visible, entree_masquee],
            "app.repositories.projets.list_ids_visibles": {1},
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Tour Meridian", resp.data)
        self.assertNotIn(b"une autre \xc3\xa9quipe", resp.data)

    def test_recherche_topbar_renvoie_projets_et_personnes(self):
        resp = self._get("/recherche/api?q=to", **{
            "app.repositories.projets.search": [{"id": 1, "code": "26099X", "nom": "Tour Meridian"}],
            "app.repositories.utilisateurs.search": [{"id": 3, "prenom": "Omar", "nom": "Aziz", "poste": "Technicien"}],
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        labels = [r["label"] for r in data["resultats"]]
        self.assertIn("26099X_Tour Meridian", labels)
        self.assertIn("Omar Aziz", labels)
        personne = next(r for r in data["resultats"] if r["label"] == "Omar Aziz")
        self.assertIn("/utilisateurs/3/profil", personne["url"])

    def test_fil_accueil_pointe_vers_le_profil_pas_la_fiche_admin(self):
        """post_card.html (Lot 5) : l'avatar/le nom de l'auteur d'un post
        mène maintenant à la page de profil ouverte à tous, plus à
        l'ancienne fiche admin/RH/chef de projet réservée."""
        resp = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": FEED})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"/utilisateurs/2/profil", resp.data)
        self.assertNotIn(b'/utilisateurs/2"', resp.data)


class TestFilCommentairesReseauSocial(unittest.TestCase):
    """Lot 5 (retour Fadhel, 2026-09-28) : "refonte du fil de commentaires
    façon réseau social" (réponse en ligne, tag, pièce jointe glisser-
    déposer avec aperçu image, "reposter"). La logique SQL (structuration
    premier niveau/réponses, mentionne_user_id, pièces jointes de
    commentaire, post.evenement='repost') a été vérifiée séparément sur un
    vrai PostgreSQL — voir migrations/0007_commentaires_reseau_social.sql
    et les notes de conception. Ici : rendu du template, et surtout les
    contrôles d'accès (IDOR) et le verrou "un seul niveau de profondeur"."""

    _login = SmokeTestCase._login
    _patched = SmokeTestCase._patched
    _get = SmokeTestCase._get

    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self._login()

    # --- Rendu : réponse en ligne, tag, pièces jointes ---

    def test_commentaires_imbriques_tag_et_pieces_jointes_saffichent(self):
        post = {
            **FEED_POST_MANUEL,
            "commentaires": [{
                "id": 1, "contenu": "Bien reçu, merci !",
                "created_at": datetime.datetime(2026, 9, 15, 11, 0),
                "auteur_id": 3, "auteur_prenom": "Omar", "auteur_nom": "Aziz",
                "mentionne_user_id": 2, "mentionne_prenom": "Foulen", "mentionne_nom": "Ben Foulen",
                "pieces_jointes": [{"id": 1, "nom_fichier": "photo.jpg"}],
                "replies": [{
                    "id": 2, "contenu": "Avec plaisir, dis-moi si besoin.",
                    "created_at": datetime.datetime(2026, 9, 15, 11, 5),
                    "auteur_id": 2, "auteur_prenom": "Foulen", "auteur_nom": "Ben Foulen",
                    "mentionne_user_id": None, "mentionne_prenom": None, "mentionne_nom": None,
                    "pieces_jointes": [{"id": 2, "nom_fichier": "plan.pdf"}],
                }],
            }],
        }
        resp = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [post]})
        self.assertEqual(resp.status_code, 200, resp.data[:2000])
        body = resp.data.decode()
        self.assertIn("Bien reçu, merci !", body)
        self.assertIn("@Foulen Ben Foulen", body)
        self.assertIn("Avec plaisir, dis-moi si besoin.", body)
        self.assertIn("post-comment-replies", body)
        self.assertIn('src="/fichiers/posts/commentaires/1"', body)
        self.assertIn('href="/fichiers/posts/commentaires/2"', body)
        self.assertIn("plan.pdf", body)
        self.assertIn("Répondre", body)
        self.assertIn("Reposter", body)

    def test_tag_de_soi_meme_ignore(self):
        """"@" dans le texte (2026-09-29) : se taguer soi-même (USER, id=1)
        ne crée ni tag ni notification ; taguer Omar (id=3) oui."""
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.posts.add_comment", return_value=42) as mock_add, \
                 patch("app.repositories.notifications.creer_pour_plusieurs") as mock_notif:
                self.client.post("/posts/1/commenter", data={"contenu": "@Foulen Chedly et @omar aziz, ok ?"})
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(mock_add.call_args.kwargs["mention_ids"], [3])
        self.assertEqual(mock_notif.call_args.args[0], [3])

    # --- Réponse en ligne : un seul niveau, imposé côté serveur (IDOR,
    #     PROMPT_CORRECTIONS.md P0 #1) — verrou de non-régression. ---

    def test_repondre_a_un_commentaire_de_premier_niveau_est_accepte(self):
        commentaire_valide = {"id": 3, "post_id": 1, "parent_commentaire_id": None}
        patchers = self._patched(**{"app.repositories.posts.get_commentaire": commentaire_valide})
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.posts.add_comment", return_value=99) as mock_add:
                resp = self.client.post("/posts/1/commenter", data={
                    "contenu": "Réponse", "parent_commentaire_id": "3",
                })
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302)
        mock_add.assert_called_once_with(1, 1, "Réponse", None, 3, piece_jointe=None, mention_ids=[])

    def test_repondre_a_une_reponse_est_ignore(self):
        """Verrou de non-régression : pas de 3e niveau — répondre à un
        commentaire qui a LUI-MÊME un parent doit silencieusement omettre
        parent_commentaire_id (le commentaire est créé de premier niveau),
        jamais imbriquer plus profond."""
        commentaire_deja_reponse = {"id": 2, "post_id": 1, "parent_commentaire_id": 1}
        patchers = self._patched(**{"app.repositories.posts.get_commentaire": commentaire_deja_reponse})
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.posts.add_comment", return_value=99) as mock_add:
                resp = self.client.post("/posts/1/commenter", data={
                    "contenu": "x", "parent_commentaire_id": "2",
                })
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302)
        mock_add.assert_called_once_with(1, 1, "x", None, None, piece_jointe=None, mention_ids=[])

    def test_repondre_a_un_commentaire_dun_autre_post_est_ignore(self):
        """IDOR (PROMPT_CORRECTIONS.md P0 #1) : un id de commentaire deviné
        appartenant à un AUTRE post ne doit jamais être accepté comme
        parent — sinon on pourrait relier deux fils de posts différents."""
        commentaire_autre_post = {"id": 5, "post_id": 999, "parent_commentaire_id": None}
        patchers = self._patched(**{"app.repositories.posts.get_commentaire": commentaire_autre_post})
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.posts.add_comment", return_value=99) as mock_add:
                resp = self.client.post("/posts/1/commenter", data={
                    "contenu": "x", "parent_commentaire_id": "5",
                })
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302)
        mock_add.assert_called_once_with(1, 1, "x", None, None, piece_jointe=None, mention_ids=[])

    # --- Pièce jointe de commentaire (glisser-déposer + aperçu image) ---

    def test_commenter_avec_piece_jointe_est_associee_au_commentaire(self):
        """Depuis le suivi P0-3 round 2 (Luna) : la pièce jointe n'est plus
        insérée séparément via add_piece_jointe_commentaire() après coup —
        elle est passée à add_comment(piece_jointe=...) pour être insérée
        dans LA MÊME transaction que le commentaire (voir
        repositories/posts.py:add_comment)."""
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.posts.add_comment", return_value=42) as mock_add, \
                 patch("app.routes.posts.save_upload",
                       return_value=("photo.jpg", "posts/1/commentaires/xyz.jpg")) as mock_save:
                resp = self.client.post(
                    "/posts/1/commenter",
                    data={"contenu": "Voici", "fichier": (io.BytesIO(b"contenu bidon"), "photo.jpg")},
                    content_type="multipart/form-data",
                )
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302, resp.data[:2000])
        mock_save.assert_called_once()
        mock_add.assert_called_once_with(
            1, 1, "Voici", None, None,
            piece_jointe=("photo.jpg", "posts/1/commentaires/xyz.jpg"), mention_ids=[],
        )

    def test_fichiers_commentaire_piece_jointe_image_servie_en_ligne(self):
        """"Aperçu image" : une image est servie EN LIGNE (pas de
        as_attachment), pour l'aperçu direct dans le fil."""
        piece_image = {"id": 1, "commentaire_id": 1, "nom_fichier": "photo.jpg",
                        "chemin": "posts/1/commentaires/1/x.jpg", "projet_id": 1, "post_id": 1}
        patchers = self._patched(**{"app.repositories.posts.get_piece_jointe_commentaire": piece_image})
        for p in patchers:
            p.start()
        try:
            with patch("app.routes.fichiers.send_from_directory", return_value="ok") as mock_send:
                resp = self.client.get("/fichiers/posts/commentaires/1")
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 200)
        mock_send.assert_called_once()
        self.assertNotIn("as_attachment", mock_send.call_args.kwargs)

    def test_fichiers_commentaire_piece_jointe_fichier_servi_en_telechargement(self):
        piece_pdf = {"id": 2, "commentaire_id": 1, "nom_fichier": "plan.pdf",
                     "chemin": "posts/1/commentaires/1/y.pdf", "projet_id": 1, "post_id": 1}
        patchers = self._patched(**{"app.repositories.posts.get_piece_jointe_commentaire": piece_pdf})
        for p in patchers:
            p.start()
        try:
            with patch("app.routes.fichiers.send_from_directory", return_value="ok") as mock_send:
                resp = self.client.get("/fichiers/posts/commentaires/2")
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 200)
        mock_send.assert_called_once()
        self.assertTrue(mock_send.call_args.kwargs.get("as_attachment"))
        self.assertEqual(mock_send.call_args.kwargs.get("download_name"), "plan.pdf")

    def test_fichiers_commentaire_piece_jointe_404_si_projet_non_visible(self):
        piece = {"id": 3, "commentaire_id": 1, "nom_fichier": "x.jpg", "chemin": "y", "projet_id": 1, "post_id": 1}
        patchers = self._patched(**{
            "app.repositories.posts.get_piece_jointe_commentaire": piece,
            "app.repositories.projets.user_can_view": False,
        })
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/fichiers/posts/commentaires/3")
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 404)

    # --- "Reposter" ---

    def test_ancienne_route_reposter_supprimee(self):
        """Lot 7 : elle contournait les règles Client/équipe de creer()."""
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            resp = self.client.post("/posts/1/reposter", data={})
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 404)

    def test_post_reposte_affiche_le_libelle_et_cite_le_post_dorigine(self):
        """post.est_repost (migration 0007) distingue le rendu d'un rebond
        normal — voir posts_repo.repost() : le post d'origine cité
        réutilise le bloc parent_post_id déjà générique."""
        repost = {
            **FEED_POST_MANUEL, "id": 6, "auteur_id": 3, "auteur_prenom": "Omar", "auteur_nom": "Aziz",
            "est_repost": True, "parent_post_id": 1,
            "parent_auteur_prenom": "Foulen", "parent_auteur_nom": "Ben Foulen",
            "parent_contenu": "Envoi du dossier EXE lot GO.", "parent_type_code": "envoi",
            "contenu": "À suivre.",
        }
        resp = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [repost]})
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        self.assertIn("a reposté", body)
        self.assertIn("Envoi du dossier EXE lot GO.", body)


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



FEED_POST_INFORMATION_EQUIPE = {
    **FEED_POST_MANUEL, "id": 9, "type_code": "information", "contenu": "Bureau fermé le 25.",
    "projet_id": None, "projet_code": None, "projet_nom": None, "projet_etat": None,
    "equipes": ["Midgard", "URBS"], "je_gere": False,
}


class TestInformationEtComposeur(SmokeBase):
    """Retours Fadhel du 2026-09-29 (claude/kairos-ecarts-2026-09-29.md) :
    posts "Information" publiables, sans projet destinés à des équipes
    (N5) ; composeur limité à mes projets, le plus récent présélectionné
    (N2/N6) ; ~5 collaborateurs récents + recherche (N4) ; fil de
    l'accueil ouvert aux intervenants d'une tâche seulement (P1). Les
    requêtes SQL sont vérifiées à part sur un vrai PostgreSQL."""

    def _poster(self, data, **overrides):
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.posts.create_post", return_value=101) as mock_create:
                resp = self.client.post("/posts", data=data)
        finally:
            for p in reversed(patchers):
                p.stop()
        return resp, mock_create

    def _flashes(self):
        with self.client.session_transaction() as sess:
            return [msg for _, msg in sess.get("_flashes", [])]

    def test_information_sans_projet_vers_des_equipes(self):
        resp, mock_create = self._poster({
            "type_code": "information", "contenu": "Bureau fermé le 25.",
            "equipes": ["MIDGARD", "URBS", "BIDON", "URBS"], "mentions": ["3", "999"],
        })
        self.assertEqual(resp.status_code, 302)
        kwargs = mock_create.call_args.kwargs
        self.assertIsNone(kwargs["projet_id"])
        self.assertEqual(kwargs["type_code"], "information")
        self.assertEqual(kwargs["equipe_codes"], ["MIDGARD", "URBS"])
        self.assertEqual(kwargs["mentionne_ids"], [3])  # 999 : pas une personne active

    def test_information_sans_projet_ni_equipe_refusee(self):
        resp, mock_create = self._poster({"type_code": "information", "contenu": "X"})
        self.assertEqual(resp.status_code, 302)
        mock_create.assert_not_called()
        self.assertTrue(any("équipe" in m for m in self._flashes()))

    def test_requete_sans_projet_refusee(self):
        resp, mock_create = self._poster({"type_code": "requete", "contenu": "X", "equipes": ["MIDGARD"]})
        mock_create.assert_not_called()

    def test_information_de_projet_ignore_les_equipes(self):
        resp, mock_create = self._poster({
            "projet_id": "1", "type_code": "information", "contenu": "X", "equipes": ["MIDGARD"],
        })
        self.assertEqual(mock_create.call_args.kwargs["projet_id"], 1)
        self.assertEqual(mock_create.call_args.kwargs["equipe_codes"], [])

    def test_information_de_projet_404_si_projet_non_visible(self):
        resp, mock_create = self._poster(
            {"projet_id": "1", "type_code": "information", "contenu": "X"},
            **{"app.repositories.projets.user_can_view": False},
        )
        self.assertEqual(resp.status_code, 404)
        mock_create.assert_not_called()

    def test_reponse_sans_projet_a_un_post_de_projet_refusee(self):
        resp, mock_create = self._poster({
            "type_code": "information", "contenu": "X", "equipes": ["MIDGARD"], "parent_post_id": "1",
        })
        self.assertEqual(resp.status_code, 404)
        mock_create.assert_not_called()

    def test_reagir_a_une_information_d_equipe_suit_ses_destinataires(self):
        """Un post sans projet n'a pas de projet dont suivre la visibilité :
        routes/posts.py passe par posts_repo.peut_voir (destinataires)."""
        self._login()
        post = {**POST_POUR_ACCES, "id": 9, "projet_id": None}
        for visible, attendu in ((False, 404), (True, 302)):
            with self.subTest(visible=visible):
                patchers = self._patched(**{"app.repositories.posts.get_post": post})
                for p in patchers:
                    p.start()
                try:
                    with patch("app.repositories.posts.peut_voir", return_value=visible) as mock_voir, \
                         patch("app.repositories.posts.react"):
                        resp = self.client.post("/posts/9/reagir", data={"reaction_code": "pouce"})
                finally:
                    for p in reversed(patchers):
                        p.stop()
                self.assertEqual(resp.status_code, attendu)
                mock_voir.assert_called_once_with(9, None, 1)

    def test_composeur_accueil_information_publiable(self):
        resp = self._get("/accueil")
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        self.assertIn("Publier l'information", body)
        self.assertNotIn("pas encore publiables", body)
        # Projet vide par défaut sur l'onglet Information, marqué optionnel,
        # sans texte d'exemple (Remarques/J.docx).
        self.assertIn("data-projet-optionnel", body)
        self.assertNotIn("Ex. Le bureau sera fermé", body)
        self.assertIn('value="aucun" data-sans-projet="1"', body)
        self.assertIn('name="equipes"', body)
        # Onglet Tâche selon le projet choisi : MES_PROJETS[0] = chef, [1] = intervenant
        self.assertIn('<option value="1" data-gere="1">', body)
        self.assertIn('<option value="2" data-gere="0">', body)

    def test_composeur_projets_tries_par_ma_derniere_action(self):
        """N2/N6 : l'ordre (et donc le projet présélectionné) est celui de
        list_mes_projets_recents, projets terminés/abandonnés exclus."""
        recents = [
            {**MES_PROJETS[1], "etat": "en_cours"},
            {**MES_PROJETS[0], "id": 7, "code": "26007X", "etat": "abandonne"},
            MES_PROJETS[0],
        ]
        resp = self._get("/accueil", **{"app.repositories.projets.list_mes_projets_recents": recents})
        body = resp.data.decode()
        options = re.findall(r'<option value="(\d+)" data-gere=', body)
        self.assertEqual(options, ["2", "1"])

    def test_composeur_collaborateurs_recents_en_tete(self):
        resp = self._get("/accueil")
        body = resp.data.decode()
        bloc = body[body.index('id="dialog-intervenants-tache"'):]
        bloc = bloc[:bloc.index("</select>")]
        self.assertLess(bloc.index('value="3" data-recent="1"'), bloc.index('value="1"'))
        self.assertIn('data-chip-recent="1"', body)

    def test_fil_affiche_les_equipes_d_une_information_sans_projet(self):
        resp = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [FEED_POST_INFORMATION_EQUIPE]})
        self.assertEqual(resp.status_code, 200, resp.data[:3000])
        body = resp.data.decode()
        self.assertIn("Équipes Midgard, URBS", body)
        self.assertIn("Bureau fermé le 25.", body)
        self.assertIn('id="post-9"', body)

    def test_notification_d_une_information_sans_projet_ouvre_l_accueil(self):
        notif = {**NOTIFICATION_UNE, "post_id": 9, "post_projet_id": None, "tache_projet_id": None}
        self._login()
        patchers = self._patched(**{"app.repositories.notifications.get_notification": notif})
        for p in patchers:
            p.start()
        try:
            resp = self.client.post(f"/notifications/{notif['id']}/ouvrir")
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertTrue(resp.headers["Location"].endswith("/accueil#post-9"))

    def test_sql_fil_accueil_inclut_intervenants_de_tache_et_informations(self):
        from app.repositories import posts as posts_repo
        with patch("app.db.get_cursor") as mock_cur:
            cur = mock_cur.return_value.__enter__.return_value
            cur.fetchall.return_value = []
            posts_repo.list_feed_mes_projets(1)
        sql = cur.execute.call_args.args[0]
        self.assertIn("tache_intervenant ti", sql)
        self.assertIn("post_equipe pev", sql)
        self.assertIn("LEFT JOIN projet proj", sql)

    def test_personnes_recentes_d_abord(self):
        from app.utils import personnes_recentes_d_abord
        personnes = [{"id": 1, "nom": "A"}, {"id": 2, "nom": "B"}, {"id": 3, "nom": "C"}]
        res = personnes_recentes_d_abord(personnes, [3, 99, 1])
        self.assertEqual([(p["id"], p["recent"]) for p in res], [(3, True), (1, True), (2, False)])
        self.assertEqual([p["id"] for p in personnes_recentes_d_abord(personnes, None)], [1, 2, 3])

    def test_fenetre_nouveau_post_de_taille_fixe(self):
        import pathlib
        css = (pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn("#dialog-nouveau-post { height: min(700px, 88vh); }", css)



class TestCommentairesLot6(SmokeBase):
    """Commentaires (retours Fadhel, 2026-09-29) : toujours affichés avec
    leur champ, "@Prénom Nom" dans le texte, modification par l'auteur,
    suppression par un admin, images en visionneuse, fichier glissé sur le
    champ (comportement navigateur vérifié sous Playwright)."""

    COMMENTAIRE = {"id": 4, "post_id": 1, "parent_commentaire_id": None, "auteur_id": 1,
                   "contenu": "Avant", "projet_id": 1}

    def _post(self, url, data=None, **overrides):
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        try:
            return self.client.post(url, data=data or {})
        finally:
            for p in reversed(patchers):
                p.stop()

    def test_commentaires_affiches_sans_clic_et_champ_toujours_visible(self):
        post = {**FEED_POST_MANUEL, "commentaires": [
            {"id": i, "contenu": f"Com {i}", "auteur_id": 3, "auteur_prenom": "Omar", "auteur_nom": "Aziz",
             "parent_commentaire_id": None, "mentions": [], "pieces_jointes": [], "replies": []}
            for i in range(1, 6)
        ]}
        body = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [post]}).data.decode()
        self.assertNotIn("<details style=\"display:inline;\">", body)
        self.assertIn('id="commentaire-post-1"', body)
        self.assertIn("Voir les 2 commentaires précédents", body)
        for i in range(1, 6):
            self.assertIn(f"Com {i}", body)
        # Plus de bandeau "Glisser une image…" ni de champ "Taguer" séparé.
        self.assertNotIn("Glisser une image ou un fichier", body)
        self.assertNotIn('name="mentionne_user_id"', body)
        self.assertIn('id="kairos-personnes"', body)
        self.assertIn("js/comment-composer.js", body)
        self.assertIn("js/lightbox.js", body)

    def test_image_de_commentaire_ouverte_en_visionneuse(self):
        post = {**FEED_POST_MANUEL, "commentaires": [{
            "id": 1, "contenu": "Photo", "auteur_id": 3, "auteur_prenom": "Omar", "auteur_nom": "Aziz",
            "parent_commentaire_id": None, "pieces_jointes": [{"id": 7, "nom_fichier": "chantier.jpg"}], "replies": [],
        }]}
        body = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [post]}).data.decode()
        self.assertRegex(body, r'<a href="/fichiers/posts/commentaires/7"[^>]*data-lightbox>')

    def test_tag_dans_le_texte_surligne(self):
        post = {**FEED_POST_MANUEL, "commentaires": [{
            "id": 1, "contenu": "Vu avec @omar aziz <b>", "auteur_id": 1, "auteur_prenom": "Foulen", "auteur_nom": "Chedly",
            "parent_commentaire_id": None, "mentions": [{"id": 3, "prenom": "Omar", "nom": "Aziz"}],
            "pieces_jointes": [], "replies": [],
        }]}
        body = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [post]}).data.decode()
        self.assertIn('Vu avec <span class="post-comment-mention">@omar aziz</span> &lt;b&gt;', body)
        # Mon commentaire : "Modifier" ; admin (USER) : "Supprimer".
        self.assertIn('data-modifier="1"', body)
        self.assertIn("/posts/commentaires/1/supprimer", body)

    def test_modifier_son_commentaire(self):
        self._login()
        patchers = self._patched()
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.posts.get_commentaire", return_value=self.COMMENTAIRE), \
                 patch("app.repositories.posts.modifier_commentaire", return_value=[3]) as mock_mod, \
                 patch("app.repositories.notifications.creer_pour_plusieurs") as mock_notif:
                resp = self.client.post("/posts/commentaires/4/modifier",
                                        data={"contenu": "Après, vu @Omar Aziz", "next": "/accueil#post-1"})
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/accueil#post-1"))
        mock_mod.assert_called_once_with(4, 1, "Après, vu @Omar Aziz", [3])
        self.assertEqual(mock_notif.call_args.args[0], [3])

    def test_modifier_le_commentaire_d_un_autre_interdit(self):
        with patch("app.repositories.posts.get_commentaire", return_value={**self.COMMENTAIRE, "auteur_id": 3}), \
             patch("app.repositories.posts.modifier_commentaire") as mock_mod:
            resp = self._post("/posts/commentaires/4/modifier", {"contenu": "Pirate"})
        self.assertEqual(resp.status_code, 403)
        mock_mod.assert_not_called()

    def test_modifier_un_commentaire_non_visible_404(self):
        with patch("app.repositories.posts.get_commentaire", return_value=self.COMMENTAIRE), \
             patch("app.repositories.posts.modifier_commentaire") as mock_mod:
            resp = self._post("/posts/commentaires/4/modifier", {"contenu": "x"},
                              **{"app.repositories.projets.user_can_view": False})
        self.assertEqual(resp.status_code, 404)
        mock_mod.assert_not_called()

    def test_supprimer_reserve_aux_admins(self):
        with patch("app.repositories.posts.get_commentaire", return_value=self.COMMENTAIRE), \
             patch("app.repositories.posts.supprimer_commentaire", return_value=["posts/1/commentaires/a.png"]) as mock_sup, \
             patch("app.routes.posts.delete_upload") as mock_del:
            resp = self._post("/posts/commentaires/4/supprimer",
                              **{"app.auth.get_user_by_id": {**USER, "role": "chef_de_projet"}})
            self.assertEqual(resp.status_code, 403)
            mock_sup.assert_not_called()
            resp = self._post("/posts/commentaires/4/supprimer")
        self.assertEqual(resp.status_code, 302)
        mock_sup.assert_called_once_with(4, 1)
        mock_del.assert_called_once_with("posts/1/commentaires/a.png")

    def test_reposter_bloque_sur_projet_termine(self):
        with patch("app.repositories.posts.create_post") as mock_create:
            resp = self._post("/posts", {"projet_id": "1", "type_code": "requete", "contenu": "x", "parent_post_id": "1"},
                              **{"app.repositories.posts.get_post": {**POST_POUR_ACCES, "projet_etat": "termine"}})
        self.assertEqual(resp.status_code, 302)
        mock_create.assert_not_called()

    def test_personnes_taguees(self):
        from app.repositories.posts import personnes_taguees
        candidats = [{"id": 1, "prenom": "Ali", "nom": "Ben"}, {"id": 2, "prenom": "Ali", "nom": "Ben Salah"},
                     {"id": 3, "prenom": "Omar", "nom": "Aziz"}]
        self.assertEqual(personnes_taguees("Merci @Ali Ben Salah !", candidats), [2])
        self.assertEqual(sorted(personnes_taguees("@ali ben et @Ali Ben Salah", candidats)), [1, 2])
        self.assertEqual(personnes_taguees("@Ali Bennani", candidats), [])
        self.assertEqual(personnes_taguees("omar aziz sans arobase", candidats), [])



class TestPostsAutomatiquesEtProjet(SmokeBase):
    """Retours Fadhel du 2026-09-29 : posts automatiques (création de
    projet, changement d'état de tâche/projet, titre de tâche — P1), clic
    sur la ligne d'une tâche → fenêtre avec titre modifiable, "Rejoindre ce
    projet" comme co-chef pour un chef de projet (PR8), profil sur la
    dernière semaine avec "Voir +" (T3). SQL vérifié sur un vrai
    PostgreSQL."""

    def _post(self, url, data=None, **overrides):
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        try:
            return self.client.post(url, data=data or {})
        finally:
            for p in reversed(patchers):
                p.stop()

    def _cur(self, fetchone):
        mock_cm = patch("app.db.get_cursor")
        m = mock_cm.start()
        self.addCleanup(mock_cm.stop)
        cur = m.return_value.__enter__.return_value
        cur.fetchone.side_effect = fetchone
        return cur

    def _inserts_post(self, cur):
        return [c for c in cur.execute.call_args_list if "INSERT INTO post" in c.args[0]]

    def test_changement_d_etat_de_tache_cree_un_post(self):
        from app.repositories import taches as taches_repo
        # 2e fetchone : le projet n'était pas « En cours » (pas de bascule).
        cur = self._cur([{"etat": "en_cours"}, None])
        self.assertTrue(taches_repo.set_etat(5, 1, "bloque", 1))
        posts_ = self._inserts_post(cur)
        self.assertEqual(len(posts_), 1)
        self.assertIn("'etat_tache'", posts_[0].args[0])
        self.assertEqual(posts_[0].args[1], (1, 5, 1, "En cours → Bloqué"))

    def test_projet_suit_ses_taches_bloque_puis_en_cours(self):
        """Lot 8 (décision Fadhel) : tâche bloquée → projet bloqué ; tâche
        remise en cours ou créée → projet en cours ; post etat_projet."""
        from app.repositories import taches as taches_repo
        cur = self._cur([{"etat": "en_cours"}, {"id": 1}])
        taches_repo.set_etat(5, 1, "bloque", 1)
        maj = [c for c in cur.execute.call_args_list if c.args[0].startswith("UPDATE projet SET etat")]
        self.assertEqual(maj[0].args[1], ("bloque", 1, "en_cours"))
        self.assertEqual(self._inserts_post(cur)[-1].args[1], (1, 1, "En cours → Bloqué"))
        cur = self._cur([{"etat": "bloque"}, {"id": 1}])
        taches_repo.set_etat(5, 1, "en_cours", 1)
        maj = [c for c in cur.execute.call_args_list if c.args[0].startswith("UPDATE projet SET etat")]
        self.assertEqual(maj[0].args[1], ("en_cours", 1, "bloque"))
        cur = self._cur([{"id": 9}, {"id": 1}])
        taches_repo.create_tache(1, "Nouvelle", 1)
        maj = [c for c in cur.execute.call_args_list if c.args[0].startswith("UPDATE projet SET etat")]
        self.assertEqual(maj[0].args[1], ("en_cours", 1, "bloque"))
        # Vérifié / Arrêt / Abandonné : le projet ne bouge pas.
        cur = self._cur([{"etat": "en_cours"}])
        taches_repo.set_etat(5, 1, "arret", 1)
        self.assertFalse([c for c in cur.execute.call_args_list if c.args[0].startswith("UPDATE projet")])

    def test_meme_etat_pas_de_post_et_tache_inconnue_refusee(self):
        from app.repositories import taches as taches_repo
        cur = self._cur([{"etat": "bloque"}, None])
        self.assertTrue(taches_repo.set_etat(5, 1, "bloque", 1))
        self.assertFalse(taches_repo.set_etat(5, 2, "bloque", 1))
        self.assertEqual(self._inserts_post(cur), [])

    def test_renommer_une_tache_cree_un_post(self):
        from app.repositories import taches as taches_repo
        cur = self._cur([{"titre": "Ancien"}])
        self.assertTrue(taches_repo.set_titre(5, 1, "Nouveau", 1))
        posts_ = self._inserts_post(cur)
        self.assertIn("'titre_tache'", posts_[0].args[0])
        self.assertEqual(posts_[0].args[1], (1, 5, 1, "Ancien → Nouveau"))

    def test_creation_et_changement_d_etat_de_projet_creent_un_post(self):
        from app.repositories import projets as projets_repo
        cur = self._cur([{"id": 42}])
        projets_repo.create_projet("26077X", "Nouveau", "EXE", 1, ["CM"], equipe_code="MIDGARD", current_user_id=1)
        self.assertIn("'creation_projet'", self._inserts_post(cur)[0].args[0])
        self.assertEqual(self._inserts_post(cur)[0].args[1], (42, 1, "26077X_Nouveau"))
        cur.fetchone.side_effect = [{"etat": "en_cours"}, {"etat": "termine"}]
        cur.execute.reset_mock()
        projets_repo.update_projet(42, nom="N", etat="termine", lots=[], current_user_id=1)
        self.assertEqual(self._inserts_post(cur)[0].args[1], (42, 1, "En cours → Terminé"))
        cur.execute.reset_mock()
        projets_repo.update_projet(42, nom="N", etat="termine", lots=[], current_user_id=1)
        self.assertEqual(self._inserts_post(cur), [])

    def test_fil_affiche_les_posts_automatiques(self):
        feed = [
            {**FEED_POST_MANUEL, "id": 11, "evenement": "etat_tache", "tache_id": 5, "tache_titre": "Plan R+2",
             "contenu": "En cours → Bloqué"},
            {**FEED_POST_MANUEL, "id": 12, "evenement": "titre_tache", "tache_id": 5, "tache_titre": "Plan R+2",
             "contenu": "Plan → Plan R+2"},
            {**FEED_POST_MANUEL, "id": 13, "evenement": "creation_projet", "contenu": "26099X_Tour Meridian"},
            {**FEED_POST_MANUEL, "id": 14, "evenement": "etat_projet", "contenu": "En cours → Terminé"},
        ]
        body = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": feed}).data.decode()
        for phrase in ("a changé l&#39;état d&#39;une tâche", "a renommé une tâche", "a créé le projet",
                       "a changé l&#39;état du projet", "En cours → Bloqué", "Plan → Plan R+2"):
            self.assertIn(phrase, body)

    def test_ligne_de_tache_ouvre_sa_fenetre_avec_titre_modifiable(self):
        body = self._get("/projets/1").data.decode()
        self.assertIn('data-open-tache="5"', body)
        self.assertIn('id="dialog-tache-5"', body)
        self.assertIn("/projets/1/taches/5/titre", body)
        self.assertNotIn("Actions sur la tâche", body)
        self.assertIn("js/tache-dialog.js", body)

    def test_renommer_une_tache_route(self):
        with patch("app.repositories.taches.set_titre", return_value=True) as mock_titre:
            resp = self._post("/projets/1/taches/5/titre", {"titre": "  Nouveau titre  "})
        self.assertEqual(resp.status_code, 302)
        mock_titre.assert_called_once_with(5, 1, "Nouveau titre", 1)

    def test_renommer_refuse_sans_droit_ou_titre_vide(self):
        with patch("app.repositories.taches.set_titre") as mock_titre:
            self._post("/projets/1/taches/5/titre", {"titre": "X"},
                       **{"app.repositories.projets.user_can_manage": False})
            self._post("/projets/1/taches/5/titre", {"titre": "   "})
        mock_titre.assert_not_called()

    def test_rejoindre_comme_co_chef_pour_un_chef_de_projet(self):
        for role, attendu in (("chef_de_projet", "add_co_chef"), ("intervenant", "add_intervenant")):
            with self.subTest(role=role), \
                 patch("app.repositories.projets.add_co_chef") as mock_co, \
                 patch("app.repositories.projets.add_intervenant") as mock_int:
                self._post("/projets/1/rejoindre", **{"app.auth.get_user_by_id": {**USER, "role": role}})
                appele = mock_co if attendu == "add_co_chef" else mock_int
                pas_appele = mock_int if attendu == "add_co_chef" else mock_co
                appele.assert_called_once_with(1, 1, 1)
                pas_appele.assert_not_called()

    def test_bouton_rejoindre_comme_co_chef(self):
        body = self._get("/projets/1", **{"app.auth.get_user_by_id": {**USER, "role": "chef_de_projet"}}).data.decode()
        self.assertIn("Rejoindre ce projet comme co-chef", body)

    def test_profil_derniere_semaine_et_voir_plus(self):
        self._login()
        patchers = self._patched(**{"app.repositories.utilisateurs.get_utilisateur": {**UTILISATEUR_PROFIL, "id": 3}})
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.posts.list_feed_auteur", side_effect=[[], [FEED_POST_MANUEL]]) as mock_feed:
                resp = self.client.get("/utilisateurs/3/profil?semaines=2")
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 200, resp.data[:3000])
        body = resp.data.decode()
        depuis = mock_feed.call_args_list[0].kwargs["depuis"]
        self.assertEqual((datetime.date.today() - depuis).days, 13)
        self.assertEqual(mock_feed.call_args_list[1].kwargs["avant"], depuis)
        self.assertIn("2 dernières semaines", body)
        self.assertIn("semaines=3#posts", body)
        self.assertIn("semaines=3#dailylog", body)



class TestProjetClientHonoraires(SmokeBase):
    """Projet : client (« IPCO » par défaut) et honoraires, visibles de tous
    ceux qui voient le projet ; panneau Informations cliquable pour le chef
    de projet (retours Fadhel, Remarques du 2026-09-28 / J.docx — PR3,
    PR5, PR6 ; migration 0010)."""

    def _post(self, url, data, **overrides):
        """Les mocks du test (create_projet/update_projet) sont démarrés
        APRÈS les défauts de _patched, pour l'emporter sur eux."""
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.projets.create_projet", self.mock_create), \
                 patch("app.repositories.projets.update_projet", self.mock_update):
                return self.client.post(url, data=data)
        finally:
            for p in reversed(patchers):
                p.stop()

    def setUp(self):
        super().setUp()
        from unittest.mock import MagicMock
        self.mock_create = MagicMock(return_value=42)
        self.mock_update = MagicMock(return_value=None)

    def test_creation_avec_client_et_honoraires(self):
        resp = self._post("/projets/nouveau", {"nom": "Tour", "code": "26099X", "phase": "EXE",
                                               "chef_projet_id": "1", "client": "  SOGEA ",
                                               "honoraires": "12 500,5"})
        self.assertEqual(resp.status_code, 302)
        kwargs = self.mock_create.call_args.kwargs
        self.assertEqual(kwargs["client"], "SOGEA")
        self.assertEqual(str(kwargs["honoraires"]), "12500.50")

    def test_creation_client_vide_devient_ipco(self):
        self._post("/projets/nouveau", {"nom": "Tour", "code": "26099X", "phase": "EXE",
                                        "chef_projet_id": "1", "client": "", "honoraires": ""})
        self.assertEqual(self.mock_create.call_args.kwargs["client"], "IPCO")
        self.assertIsNone(self.mock_create.call_args.kwargs["honoraires"])

    def test_honoraires_invalides_refuses(self):
        for valeur in ("abc", "-5", "1e30"):
            with self.subTest(valeur=valeur):
                self._post("/projets/nouveau", {"nom": "T", "code": "26099X", "phase": "EXE",
                                                "chef_projet_id": "1", "honoraires": valeur})
                self._post("/projets/1/informations", {"nom": "T", "etat": "en_cours", "honoraires": valeur})
                self.mock_create.assert_not_called()
                self.mock_update.assert_not_called()

    def test_edition_des_informations_avec_client_et_honoraires(self):
        self._post("/projets/1/informations", {"nom": "Tour", "etat": "en_cours", "lots": ["GO"],
                                               "client": "IPCO", "honoraires": "8000"})
        self.assertEqual(self.mock_update.call_args.kwargs["client"], "IPCO")
        self.assertEqual(str(self.mock_update.call_args.kwargs["honoraires"]), "8000.00")

    def test_panneau_informations_client_honoraires_et_clic(self):
        projet = {**PROJET, "client": "SOGEA", "honoraires": 12500.5}
        body = self._get("/projets/1", **{"app.repositories.projets.get_projet": projet}).data.decode()
        self.assertIn("SOGEA", body)
        self.assertIn("12\u202f500,50", body)
        self.assertIn('card carte-cliquable" data-open-informations-dialog', body)
        self.assertIn('name="client" value="SOGEA"', body)
        self.assertIn('name="honoraires" inputmode="decimal" placeholder="12 500,00" value="12\u202f500,50"', body)
        body = self._get("/projets/1", **{"app.repositories.projets.get_projet": projet,
                                          "app.repositories.projets.user_can_manage": False}).data.decode()
        self.assertIn("SOGEA", body)  # visible de tous ceux qui voient le projet
        self.assertNotIn("data-open-informations-dialog", body)

    def test_fenetre_nouveau_projet_client_ipco_par_defaut(self):
        body = self._get("/projets").data.decode()
        self.assertIn('id="dialog-projet-client" name="client" value="IPCO"', body)
        self.assertIn('id="dialog-projet-honoraires"', body)

    def test_formats(self):
        from decimal import Decimal
        from app.utils import heures_interv_chef, montant_fr, parser_montant
        self.assertEqual(parser_montant("12 500,50 €"), Decimal("12500.50"))
        self.assertEqual(parser_montant("7.5"), Decimal("7.50"))
        self.assertIsNone(parser_montant("  "))
        for mauvais in ("x", "-1", "nan", "inf"):
            with self.assertRaises(ValueError):
                parser_montant(mauvais)
        self.assertEqual(montant_fr(Decimal("12500.00")), "12\u202f500")
        self.assertEqual(montant_fr(None), "")
        self.assertEqual(heures_interv_chef(8, 5), "8/5 h")
        self.assertEqual(heures_interv_chef(7.25, None), "7,2/0 h")



class TestPagesLot6(SmokeBase):
    """Retours Fadhel du 2026-09-29 sur les pages : Deadlines (barre de
    défilement seulement si besoin), Tous les projets (CM/GO, filtres sur
    une ligne, chefs sans projet masqués, export Excel, tri par date de
    rendu avec le nom de la tâche en infobulle), Utilisateurs (filtres sur
    une ligne). Rendu réel vérifié sous Playwright."""

    PROJET_LIGNE = {
        "id": 1, "code": "26099X", "nom": "Tour Meridian", "phase": "EXE", "etat": "en_cours",
        "date_debut": datetime.date(2026, 1, 5), "date_fin": None, "client": "IPCO", "honoraires": 12500,
        "chef_prenom": "Foulen", "chef_nom": "Chedly", "chef_id": 1, "lots": "CM · GO",
        "heures_cumulees": 13.0, "heures_chef": 5.0, "heures_intervenant": 8.0,
        "prochaine_echeance": datetime.date(2026, 10, 2),
        "prochain_rendu": datetime.date(2026, 10, 2), "prochain_rendu_titre": "Note de calcul",
        "prochaine_deadline": datetime.date(2026, 10, 2), "prochaine_deadline_titre": "Note de calcul",
        "prochaine_deadline_type": "rendu_client",
    }

    def test_jours_utiles_gantt(self):
        from app.utils import jours_utiles_gantt
        today = datetime.date(2026, 9, 29)
        t = lambda j: {"date_echeance": today + datetime.timedelta(days=j)}
        self.assertEqual(jours_utiles_gantt([], today), 14)
        self.assertEqual(jours_utiles_gantt([t(-3), t(5)], today), 14)
        self.assertEqual(jours_utiles_gantt([t(30)], today), 31)
        self.assertEqual(jours_utiles_gantt([t(400)], today), 90)

    def test_deadlines_aide_de_defilement_et_retard(self):
        body = self._get("/deadlines").data.decode()
        self.assertIn('id="gantt-aide-defilement" hidden', body)
        self.assertIn("--gantt-days:14;", body)
        self.assertIn("g-bar g-bar-retard", body)  # DEADLINES[0] : 18 sept., en retard

    def test_tous_les_projets_cm_go_excel_et_rendu(self):
        body = self._get("/projets", **{"app.repositories.projets.list_projets": [self.PROJET_LIGNE]}).data.decode()
        self.assertIn('<option value="CM" title="Charpente Métallique" >CM</option>', body)
        self.assertIn('id="export-excel" href="/projets/export.xlsx"', body)
        self.assertIn('title="Rendu : Note de calcul"', body)
        self.assertIn("filtres-une-ligne", body)

    def test_chefs_de_projet_limites_a_ceux_qui_ont_des_projets_actifs(self):
        with patch("app.repositories.projets.list_chefs_de_projet", return_value=CHEFS_DE_PROJET) as mock_chefs:
            self._login()
            patchers = [p for p in self._patched() if p.attribute != "list_chefs_de_projet"]
            for p in patchers:
                p.start()
            try:
                self.client.get("/projets")
            finally:
                for p in reversed(patchers):
                    p.stop()
        mock_chefs.assert_called_with(1)
        from app.repositories import projets as projets_repo
        import inspect
        source = inspect.getsource(projets_repo.list_chefs_de_projet)
        self.assertIn("p.etat IN ('en_cours', 'bloque')", source)

    def test_tri_par_date_de_rendu(self):
        import inspect
        from app.repositories import projets as projets_repo
        source = inspect.getsource(projets_repo.list_projets)
        self.assertIn("ORDER BY (pr.date_echeance IS NULL), pr.date_echeance,", source)
        self.assertIn("t.type_deadline = 'rendu_client'", source)

    def test_export_excel(self):
        import openpyxl
        self._login()
        patchers = self._patched(**{"app.repositories.projets.list_projets": [
            self.PROJET_LIGNE, {**self.PROJET_LIGNE, "id": 2, "code": "26100X", "nom": "=HYPERLINK(1)",
                                "prochain_rendu": None, "prochain_rendu_titre": None}]})
        for p in patchers:
            p.start()
        try:
            resp = self.client.get("/projets/export.xlsx?filtres_actifs=1&etat=en_cours")
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp.headers["Content-Disposition"])
        feuille = openpyxl.load_workbook(io.BytesIO(resp.data)).active
        lignes = list(feuille.iter_rows(values_only=True))
        self.assertEqual(lignes[0][:3], ("Code", "Nom", "Phase"))
        self.assertEqual(lignes[1][0], "26099X")
        self.assertEqual(lignes[1][10], "Note de calcul")
        self.assertEqual(lignes[2][1], "=HYPERLINK(1)")
        self.assertEqual(feuille["B3"].data_type, "s")  # du texte, jamais une formule

    def test_utilisateurs_filtres_sur_une_ligne(self):
        import pathlib
        css = (pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".filtres-utilisateurs { flex-wrap: nowrap !important; }", css)



class TestRelectureLot6(SmokeBase):
    """Corrections après relecture indépendante du lot (2026-09-29)."""

    def test_dates_de_commentaire_en_texte_iso(self):
        """json_agg renvoie created_at/modifie_le en texte : le fil ne doit
        pas planter (filtre il_y_a) sur un vrai PostgreSQL."""
        from app.repositories.posts import _structurer_commentaires
        rows = [{"commentaires": [{"id": 1, "parent_commentaire_id": None,
                                   "created_at": "2026-09-29T12:07:27.816896+01:00", "modifie_le": None}]}]
        c = _structurer_commentaires(rows)[0]["commentaires"][0]
        self.assertEqual(c["created_at"], datetime.datetime.fromisoformat("2026-09-29T12:07:27.816896+01:00"))
        post = {**FEED_POST_MANUEL, "commentaires": [{
            "id": 1, "contenu": "Ok", "auteur_id": 3, "auteur_prenom": "Omar", "auteur_nom": "Aziz",
            "parent_commentaire_id": None, "created_at": c["created_at"],
            "modifie_le": datetime.datetime(2026, 9, 29, 13, 0, tzinfo=datetime.timezone.utc),
            "pieces_jointes": [], "replies": []}]}
        resp = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [post]})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("· modifié", resp.data.decode())

    def test_ancienne_journee_duree_au_quart_d_heure(self):
        from app.repositories import dailylog as dailylog_repo
        with patch("app.repositories.dailylog.get_jour", return_value=None):
            self.assertEqual(dailylog_repo.duree_et_absence(1, "2026-09-01", [{"heures": 2.67}] * 3), (8.0, False))
            self.assertEqual(dailylog_repo.duree_et_absence(1, "2026-09-01", [{"heures": 0.05}]), (0.25, False))

    def test_reponse_a_une_information_d_equipe_garde_ses_equipes(self):
        self._login()
        parent = {**POST_POUR_ACCES, "id": 9, "projet_id": None, "projet_etat": None}
        patchers = self._patched(**{"app.repositories.posts.get_post": parent})
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.posts.peut_voir", side_effect=lambda pid, proj, uid: uid in (1, 3)), \
                 patch("app.repositories.posts.equipes_du_post", return_value=["SS"]), \
                 patch("app.repositories.posts.create_post", return_value=101) as mock_create:
                self.client.post("/posts", data={"type_code": "information", "contenu": "Réponse",
                                                 "parent_post_id": "9", "equipes": ["Q"], "mentions": ["3", "1"]})
        finally:
            for p in reversed(patchers):
                p.stop()
        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["equipe_codes"], ["SS"])  # pas l'équipe Q choisie
        self.assertEqual(kwargs["mentionne_ids"], [3, 1])

    def test_projet_termine_publication_bloquee_meme_pour_les_chefs(self):
        """Décision Fadhel (lot 7) : plus aucune publication sur un projet
        clos, chef et co-chefs compris."""
        self._login()
        patchers = self._patched(**{"app.repositories.projets.get_projet": {**PROJET, "etat": "termine"},
                                    "app.repositories.projets.user_can_manage": True})
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.posts.create_post", return_value=101) as mock_create:
                self.client.post("/posts", data={"projet_id": "1", "type_code": "requete", "contenu": "x"})
            body = self.client.get("/projets/1").data.decode()
        finally:
            for p in reversed(patchers):
                p.stop()
        mock_create.assert_not_called()
        self.assertNotIn("+ Nouveau post</button>", body)



class TestAuditV3(SmokeBase):
    """Corrections issues du troisième audit (2026-09-29)."""

    def test_lien_excel_garde_tous_les_filtres(self):
        body = self._get("/projets?filtres_actifs=1&phase=APS&phase=EXE&etat=en_cours").data.decode()
        self.assertIn('href="/projets/export.xlsx?filtres_actifs=1&amp;phase=APS&amp;phase=EXE&amp;etat=en_cours"', body)

    def test_fiche_semaine_derniere_filtree_par_visibilite(self):
        """Un chef de projet ne voit, sur la fiche d'un autre, que les
        lignes de DailyLog des projets qu'il voit lui-même."""
        self._login()
        entrees = [{"id": 1, "projet_id": 1, "tache_id": None, "heures": 3.0, "projet_code": "26099X",
                    "projet_nom": "Visible", "tache_titre": None},
                   {"id": 2, "projet_id": 42, "tache_id": None, "heures": 5.0, "projet_code": "26042X",
                    "projet_nom": "Projet Secret", "tache_titre": None}]
        patchers = self._patched(**{
            "app.auth.get_user_by_id": {**USER, "role": "chef_de_projet"},
            "app.repositories.utilisateurs.get_utilisateur": AUTRE_UTILISATEUR,
            "app.repositories.dailylog.list_entrees_jour": entrees,
            "app.repositories.projets.list_ids_visibles": {1},
        })
        for p in patchers:
            p.start()
        try:
            body = self.client.get("/utilisateurs/2").data.decode()
        finally:
            for p in reversed(patchers):
                p.stop()
        self.assertIn("Visible", body)
        self.assertNotIn("Projet Secret", body)

    def test_image_jointe_a_un_post_affichee(self):
        post = {**FEED_POST_MANUEL, "pieces_jointes": [{"id": 4, "nom_fichier": "capture.png"},
                                                       {"id": 5, "nom_fichier": "plan.pdf"}]}
        body = self._get("/accueil", **{"app.repositories.posts.list_feed_mes_projets": [post]}).data.decode()
        self.assertRegex(body, r'<a href="/fichiers/posts/4"[^>]*data-lightbox')
        self.assertIn('<img src="/fichiers/posts/4" alt="capture.png" class="post-attachment-img"', body)
        self.assertIn("plan.pdf</span>", body)

    def test_migrations_appliquees_au_demarrage(self):
        """Plus de fenêtre entre le --build et `flask migrer` où personne ne
        peut se connecter : le conteneur migre avant de lancer gunicorn."""
        import pathlib
        dockerfile = (pathlib.Path(__file__).resolve().parent.parent / "Dockerfile").read_text(encoding="utf-8")
        cmd = [l for l in dockerfile.splitlines() if l.startswith("CMD")][0]
        self.assertLess(cmd.index("flask migrer &&"), cmd.index("exec gunicorn"))

    def test_recherche_de_projet_entree_choisit(self):
        import pathlib
        js = (pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "search-combobox.js").read_text(encoding="utf-8")
        self.assertIn("choisir(trouves[actif])", js)
        self.assertIn("ArrowDown", js)
        # Relecture lot 7 : Entrée sans saisie garde le choix en cours, et
        # quitter le champ referme la liste en rétablissant le texte.
        self.assertIn("actif = f ? (matches.length ? 0 : -1) : courant;", js)
        self.assertIn("list.addEventListener('mousedown', function (evt) { evt.preventDefault(); });", js)

    def test_connexions_sans_jit(self):
        """JIT Postgres coupé pour les connexions de l'appli (page profil lente)."""
        from unittest import mock as _mock
        from app import db as _db
        ancien = _db._pool
        _db._pool = None
        try:
            with _mock.patch.object(_db, "ThreadedConnectionPool") as pool:
                _db.init_pool("postgresql://x@y/z")
            self.assertEqual(pool.call_args.kwargs.get("options"), "-c jit=off")
        finally:
            _db._pool = ancien

    def test_rejoindre_tache_visible_sans_survol(self):
        """Écrans tactiles : le bouton "rejoindre la tâche" ne dépend plus du survol."""
        import pathlib, re
        css = (pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"@media \(hover: none\) \{ \.task-join-form \{ opacity: 1; \} \}")

    def test_rappel_dailylog_lisible_en_theme_sombre(self):
        """Le bandeau "DailyLog d'hier non rempli" suit le thème (plus de
        fond clair en dur avec un lien vert illisible en sombre)."""
        import pathlib
        racine = pathlib.Path(__file__).resolve().parent.parent / "app"
        tpl = (racine / "templates" / "dailylog.html").read_text(encoding="utf-8")
        css = (racine / "static" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn('class="card warn-banner"', tpl)
        self.assertNotIn("#fdf3ec", tpl)
        sombre = css[css.index(':root[data-theme="dark"] {'):]
        sombre = sombre[:sombre.index("}")]
        self.assertIn("--warn-bg:", sombre)
        self.assertIn("--text-faint: #8a9680", sombre)

    def test_page_projet_n_agrege_plus_tout_le_dailylog(self):
        """Les heures de l'en-tête projet et des tâches sont calculées pour ce
        projet/ces tâches seulement, plus via les vues globales."""
        import inspect
        from app.repositories import projets as _p, taches as _t
        for f in (_p.get_projet, _t.list_taches_projet, _t.get_tache):
            src = inspect.getsource(f)
            self.assertNotIn("JOIN v_projet_heures", src)
            self.assertNotIn("JOIN v_tache_heures", src)
            self.assertIn("LATERAL", src)



RH = {**USER, "id": 7, "role": "rh", "prenom": "Rym", "nom": "Hadj", "equipe_code": None}
CLIENT = {**USER, "id": 8, "role": "client", "prenom": "Karim", "nom": "Client", "equipe_code": "MIDGARD"}
CHEF = {**USER, "id": 1, "role": "chef_de_projet"}
PROJET_CLOS = {**PROJET, "etat": "termine", "date_cloture": datetime.date(2026, 9, 10)}


class TestDecisionsLot7(SmokeBase):
    """Rôles RH / Client, Informations d'équipe et projets clos (décisions
    de Fadhel, lot 7)."""

    def _requete(self, methode, chemin, data=None, espions=(), **overrides):
        self._login()
        patchers = self._patched(**overrides)
        for p in patchers:
            p.start()
        mocks = {}
        try:
            for cible, valeur in espions:
                pp = patch(cible, return_value=valeur)
                mocks[cible] = pp.start()
                patchers.append(pp)
            resp = getattr(self.client, methode)(chemin, data=data or {})
        finally:
            for p in reversed(patchers):
                p.stop()
        return resp, mocks

    # --- RH -------------------------------------------------------------
    def test_rh_n_a_pas_acces_aux_projets_ni_au_daily_log(self):
        for chemin in ("/projets", "/projets/export.xlsx", "/dailylog", "/deadlines"):
            with self.subTest(chemin=chemin):
                resp, _ = self._requete("get", chemin, **{"app.auth.get_user_by_id": RH})
                self.assertEqual(resp.status_code, 302)
                self.assertTrue(resp.headers["Location"].endswith("/accueil"))

    def test_rh_accueil_sans_projets_mais_peut_publier_une_information(self):
        resp, mocks = self._requete("get", "/accueil", espions=[("app.repositories.taches.list_deadlines", [])],
                                    **{"app.auth.get_user_by_id": RH})
        body = resp.data.decode()
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('title="Tous les projets"', body)
        self.assertNotIn('title="Deadlines"', body)
        self.assertNotIn('title="Daily log"', body)
        self.assertNotIn("Remplir mon Daily log", body)
        self.assertNotIn("Mes tâches", body)
        self.assertIn("+ Nouveau post</button>", body)
        self.assertIn("Toutes les équipes", body)
        mocks["app.repositories.taches.list_deadlines"].assert_not_called()

    def test_pas_de_rappel_daily_log_pour_rh_ni_client(self):
        import inspect
        from app import auth
        self.assertIn('if user["role"] not in ("rh", "client"):\n                _verifier_rappel_dailylog(user["id"])',
                      inspect.getsource(auth.login))

    def test_tests_sql_joues_par_la_ci(self):
        import pathlib
        racine = pathlib.Path(__file__).resolve().parent.parent
        ci = (racine / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
        self.assertIn("for fichier in tests/sql/*.sql; do", ci)
        self.assertIn("for base in kairos montee_version; do", ci)
        self.assertTrue(list((racine / "tests" / "sql").glob("*.sql")))

    def test_visibilite_sans_rh_et_client_limite_a_son_equipe(self):
        import pathlib
        racine = pathlib.Path(__file__).resolve().parent.parent
        for fichier in ("schema.sql", "migrations/0011_roles_et_projets_clos.sql"):
            with self.subTest(fichier=fichier):
                sql = (racine / fichier).read_text(encoding="utf-8")
                vue = sql[sql.index("VIEW v_projet_visibilite AS"):]
                vue = vue[:vue.index(");")]
                self.assertIn("AND u.role <> 'rh'", vue)
                self.assertIn("u.role = 'admin'", vue)
                self.assertIn("OR (u.role <> 'client' AND (", vue)
                self.assertIn("rôle Client ne peut pas être", sql)
        self.assertIn("('0011_roles_et_projets_clos')", (racine / "schema.sql").read_text(encoding="utf-8"))

    # --- Client ---------------------------------------------------------
    def test_client_sans_daily_log_mais_avec_les_projets(self):
        for chemin in ("/dailylog", "/deadlines"):
            resp, _ = self._requete("get", chemin, **{"app.auth.get_user_by_id": CLIENT})
            self.assertEqual(resp.status_code, 302)
        resp, mocks = self._requete(
            "get", "/accueil",
            espions=[("app.repositories.projets.list_projets", [{**MES_PROJETS[1], "mon_role": None}])],
            **{"app.auth.get_user_by_id": CLIENT})
        body = resp.data.decode()
        self.assertIn('title="Tous les projets"', body)
        self.assertNotIn('title="Daily log"', body)
        self.assertNotIn('title="Deadlines"', body)
        self.assertNotIn("Remplir mon Daily log", body)
        self.assertNotIn("Mes tâches", body)
        self.assertNotIn("Aucun projet — information d", body)
        self.assertIn("Résidence Les Oliviers", body)
        self.assertEqual(mocks["app.repositories.projets.list_projets"].call_args.kwargs["etats"], ["en_cours", "bloque"])

    def test_client_n_envoie_que_requetes_et_informations_sur_un_projet(self):
        cas = [
            ({"projet_id": "1", "type_code": "requete", "contenu": "x"}, True),
            ({"projet_id": "1", "type_code": "information", "contenu": "x"}, True),
            ({"projet_id": "1", "type_code": "envoi", "contenu": "x"}, False),
            ({"type_code": "information", "contenu": "x", "equipes": "MIDGARD"}, False),
        ]
        for data, attendu in cas:
            with self.subTest(data=data):
                _, mocks = self._requete("post", "/posts", data=data,
                                         espions=[("app.repositories.posts.create_post", 101)],
                                         **{"app.auth.get_user_by_id": CLIENT})
                self.assertEqual(mocks["app.repositories.posts.create_post"].called, attendu)

    def test_client_ne_rejoint_rien_et_n_est_jamais_intervenant(self):
        for chemin, espion in (("/projets/1/rejoindre", "app.repositories.projets.add_intervenant"),
                               ("/projets/1/taches/5/rejoindre", "app.repositories.taches.add_intervenant")):
            with self.subTest(chemin=chemin):
                _, mocks = self._requete("post", chemin, espions=[(espion, True)],
                                         **{"app.auth.get_user_by_id": CLIENT})
                mocks[espion].assert_not_called()
        resp, _ = self._requete("post", "/fichiers/taches/5/upload", **{"app.auth.get_user_by_id": CLIENT})
        self.assertEqual(resp.status_code, 403)
        # Ajouté par un chef : refusé aussi.
        _, mocks = self._requete("post", "/projets/1/intervenants", data={"utilisateur_id": "8"},
                                 espions=[("app.repositories.projets.add_intervenant", None)],
                                 **{"app.repositories.utilisateurs.get_utilisateur": {**UTILISATEUR_PROFIL, "id": 8, "role": "client"}})
        mocks["app.repositories.projets.add_intervenant"].assert_not_called()
        # Nouvelle tâche : le client est retiré des intervenants.
        actifs = UTILISATEURS_ACTIFS + [{"id": 8, "prenom": "Karim", "nom": "Client", "poste": "", "role": "client"}]
        _, mocks = self._requete("post", "/projets/1/taches", data={"titre": "T", "intervenants": ["3", "8"]},
                                 espions=[("app.repositories.taches.create_tache", 9)],
                                 **{"app.repositories.utilisateurs.list_actifs": actifs})
        self.assertEqual(mocks["app.repositories.taches.create_tache"].call_args.kwargs["intervenant_ids"], [3])
        # Et il n'est pas proposé dans la liste "+ Ajouter un intervenant".
        resp, _ = self._requete("get", "/projets/1", **{"app.repositories.utilisateurs.list_actifs": actifs})
        bloc = resp.data.decode().split('name="utilisateur_id"')[1].split("</select>")[0]
        self.assertNotIn("Karim", bloc)

    def test_anciens_rattachements_d_un_client_ne_donnent_aucun_droit(self):
        """Relecture : un Client (ou RH) resté co-chef/intervenant d'avant la
        migration 0011 ne gère rien et n'agit sur aucune tâche."""
        import inspect
        from app.repositories import posts as posts_repo, projets as projets_repo, taches as taches_repo
        garde = "ux.role IN ('client', 'rh')"
        self.assertIn(garde, inspect.getsource(projets_repo.user_can_manage))
        self.assertIn(garde, inspect.getsource(taches_repo.user_est_intervenant))
        self.assertIn(garde, posts_repo._FEED_SELECT)

    def test_fichier_de_tache_reserve_au_chef_et_aux_intervenants(self):
        import io
        for gere, intervenant, attendu in ((False, False, False), (True, False, True), (False, True, True)):
            with self.subTest(gere=gere, intervenant=intervenant):
                _, mocks = self._requete(
                    "post", "/fichiers/taches/5/upload", data={"fichier": (io.BytesIO(b"x"), "n.pdf")},
                    espions=[("app.routes.fichiers.save_upload", ("n.pdf", "taches/5/x.pdf")),
                             ("app.repositories.taches.add_piece_jointe", None)],
                    **{"app.auth.get_user_by_id": {**USER, "role": "intervenant"},
                       "app.repositories.projets.user_can_manage": gere,
                       "app.repositories.taches.user_est_intervenant": intervenant})
                self.assertEqual(mocks["app.routes.fichiers.save_upload"].called, attendu)

    def test_phase_liee_des_la_creation_du_projet(self):
        """Retour Fadhel (lot 7) : lier un projet existant à la création."""
        candidats = [{"id": 2, "code": "25014D", "nom": "Résidence Les Oliviers"}]
        for chemin in ("/projets", "/projets/nouveau"):
            with self.subTest(chemin=chemin):
                body = self._requete("get", chemin, **{"app.repositories.projets.search": candidats})[0].data.decode()
                bloc = body.split('name="phase_liee_id"')[1].split("</select>")[0]
                self.assertIn('<option value="2">25014D_Résidence Les Oliviers</option>', bloc)
        donnees = {"nom": "Tour B", "code": "26100X", "phase": "EXE", "chef_projet_id": "1", "phase_liee_id": "2"}
        _, mocks = self._requete("post", "/projets/nouveau", data=donnees,
                                 espions=[("app.repositories.projets.create_projet", 77)],
                                 **{"app.repositories.utilisateurs.list_actifs": UTILISATEURS_ACTIFS})
        self.assertEqual(mocks["app.repositories.projets.create_projet"].call_args.kwargs["phase_liee_id"], 2)
        # Projet lié invisible : refusé.
        _, mocks = self._requete("post", "/projets/nouveau", data=donnees,
                                 espions=[("app.repositories.projets.create_projet", 77)],
                                 **{"app.repositories.projets.user_can_view": False})
        mocks["app.repositories.projets.create_projet"].assert_not_called()

    # --- Informations d'équipe -------------------------------------------
    def test_information_sans_projet_vers_sa_seule_equipe_sauf_admin_et_rh(self):
        cas = [
            (CHEF, ["MIDGARD"], True), (CHEF, ["MIDGARD", "URBS"], False), (CHEF, ["URBS"], False),
            (USER, ["MIDGARD", "URBS"], True), (RH, ["URBS", "SS"], True),
        ]
        for user, equipes, attendu in cas:
            with self.subTest(role=user["role"], equipes=equipes):
                _, mocks = self._requete("post", "/posts",
                                         data={"type_code": "information", "contenu": "x", "equipes": equipes},
                                         espions=[("app.repositories.posts.create_post", 101)],
                                         **{"app.auth.get_user_by_id": user})
                self.assertEqual(mocks["app.repositories.posts.create_post"].called, attendu)

    def test_composeur_propose_seulement_son_equipe_hors_admin_rh(self):
        body = self._requete("get", "/accueil", **{"app.auth.get_user_by_id": CHEF})[0].data.decode()
        equipes = body.split('id="dialog-equipes-information"')[1].split("</select>")[0]
        self.assertIn('value="MIDGARD" selected', equipes)
        self.assertNotIn('value="URBS"', equipes)
        self.assertNotIn("Toutes les équipes", body)

    # --- Projets clos -----------------------------------------------------
    def test_projet_clos_bloque_toutes_les_interventions(self):
        cas = [
            ("/projets/1/taches", {"titre": "T"}, "app.repositories.taches.create_tache"),
            ("/projets/1/taches/5/etat", {"etat": "en_cours"}, "app.repositories.taches.set_etat"),
            ("/projets/1/taches/5/titre", {"titre": "Nouveau"}, "app.repositories.taches.set_titre"),
            ("/projets/1/taches/5/cloturer", {"type_code": "envoi"}, "app.repositories.taches.close_tache"),
            ("/projets/1/intervenants", {"utilisateur_id": "3"}, "app.repositories.projets.add_intervenant"),
            ("/projets/1/rejoindre", {}, "app.repositories.projets.add_co_chef"),
            ("/projets/1/taches/5/rejoindre", {}, "app.repositories.taches.add_intervenant"),
            ("/posts", {"projet_id": "1", "type_code": "requete", "contenu": "x"}, "app.repositories.posts.create_post"),
            ("/fichiers/taches/5/upload", "fichier", "app.routes.fichiers.save_upload"),
        ]
        import io
        for chemin, data, espion in cas:
            if data == "fichier":
                data = {"fichier": (io.BytesIO(b"x"), "note.pdf")}
            with self.subTest(chemin=chemin):
                _, mocks = self._requete(
                    "post", chemin, data=data, espions=[(espion, ("note.pdf", "taches/5/x.pdf"))],
                    **{"app.auth.get_user_by_id": CHEF,
                       "app.repositories.projets.get_projet": PROJET_CLOS,
                       "app.repositories.taches.get_tache": {**TACHE_POUR_FICHIERS, "projet_etat": "termine"},
                       "app.repositories.utilisateurs.get_utilisateur": {**UTILISATEUR_PROFIL, "id": 3, "role": "intervenant"}})
                mocks[espion].assert_not_called()

    def test_posts_d_un_projet_clos_figes(self):
        post_clos = {**POST_POUR_ACCES, "projet_etat": "abandonne"}
        commentaire = {"id": 4, "post_id": 1, "parent_commentaire_id": None, "auteur_id": 1, "contenu": "a",
                       "projet_id": 1, "projet_etat": "termine"}
        cas = [
            ("/posts/1/reagir", {"reaction_code": "pouce"}, "app.repositories.posts.react"),
            ("/posts/1/reagir/supprimer", {}, "app.repositories.posts.remove_reaction"),
            ("/posts/1/commenter", {"contenu": "x"}, "app.repositories.posts.add_comment"),
            ("/posts/commentaires/4/modifier", {"contenu": "b"}, "app.repositories.posts.modifier_commentaire"),
        ]
        for chemin, data, espion in cas:
            with self.subTest(chemin=chemin):
                _, mocks = self._requete(
                    "post", chemin, data=data, espions=[(espion, None),
                                                        ("app.repositories.posts.peut_voir", True),
                                                        ("app.repositories.posts.get_commentaire", commentaire)],
                    **{"app.repositories.posts.get_post": post_clos})
                mocks[espion].assert_not_called()

    def test_page_d_un_projet_clos_sans_actions_sauf_informations(self):
        feed = [{**FEED_POST_MANUEL, "projet_etat": "termine"}]
        body = self._requete("get", "/projets/1", **{"app.repositories.projets.get_projet": PROJET_CLOS,
                                                     "app.repositories.posts.list_feed_projet": feed})[0].data.decode()
        self.assertIn("Clôturé le", body)
        self.assertNotIn("+ Nouveau post</button>", body)
        self.assertNotIn("Créer une tâche sur ce projet", body)
        self.assertNotIn("+ Ajouter un intervenant", body)
        self.assertNotIn("Rejoindre ce projet", body)
        self.assertNotIn('class="task-join-form"', body)
        self.assertNotIn("data-comment-composer", body)
        self.assertNotIn("/upload", body)
        self.assertIn("data-open-informations-dialog", body)

    def test_date_de_cloture_posee_et_effacee_automatiquement(self):
        import inspect
        from app.repositories import projets as projets_repo
        src = inspect.getsource(projets_repo.update_projet)
        self.assertIn("date_cloture = CASE WHEN %s IN ('termine', 'abandonne')", src)
        self.assertIn("THEN COALESCE(date_cloture, CURRENT_DATE) END", src)
        self.assertIn("honoraires, client, etat, projet_id)", src)

    def test_daily_log_refuse_apres_la_cloture(self):
        self._login()
        patchers = self._patched(**{"app.repositories.projets.get_projet": PROJET_CLOS})
        for p in patchers:
            p.start()
        try:
            with patch("app.repositories.dailylog.remplacer_jour") as remplacer:
                self.client.post("/dailylog", data={"date": "2026-09-15", "duree": "8", "ligne_projet_id": ["1"],
                                                    "ligne_tache_id": [""], "ligne_heures": ["8"]})
                remplacer.assert_not_called()
                # Jour de la clôture : encore permis.
                self.client.post("/dailylog", data={"date": "2026-09-10", "duree": "8", "ligne_projet_id": ["1"],
                                                    "ligne_tache_id": [""], "ligne_heures": ["8"]})
                remplacer.assert_called_once()
        finally:
            for p in reversed(patchers):
                p.stop()

    # --- Co-chef ------------------------------------------------------------
    def test_rejoindre_comme_co_chef_previent_le_chef(self):
        _, mocks = self._requete(
            "post", "/projets/1/rejoindre",
            espions=[("app.repositories.projets.add_co_chef", None), ("app.repositories.notifications.creer", 1)],
            **{"app.auth.get_user_by_id": {**CHEF, "id": 5, "prenom": "Sami", "nom": "B"},
               "app.repositories.projets.get_projet": {**PROJET, "chef_projet_id": 1}})
        mocks["app.repositories.projets.add_co_chef"].assert_called_once()
        args = mocks["app.repositories.notifications.creer"].call_args.args
        self.assertEqual(args[0], 1)
        self.assertIn("Sami B a rejoint votre projet « Tour Meridian » comme co-chef", args[2])



class TestLot8(SmokeBase):
    """Retours Fadhel du lot 8 : personnes « avec » d'un post, code de phase
    liée, contrôle des saisies."""

    def _requete(self, methode, chemin, data=None, espions=(), **overrides):
        return TestDecisionsLot7._requete(self, methode, chemin, data, espions, **overrides)

    def test_post_montre_avec_et_les_pastilles_des_personnes_ajoutees(self):
        feed = [{**FEED_POST_MANUEL, "mentions": [
            {"id": 3, "prenom": "Omar", "nom": "Aziz", "avatar_chemin": None},
            {"id": 5, "prenom": "Rim", "nom": "Jlassi", "avatar_chemin": None}]}]
        body = self._requete("get", "/accueil", **{"app.repositories.posts.list_feed_mes_projets": feed})[0].data.decode()
        bloc = body.split('class="post-avec"')[1][:1500]
        self.assertIn("<span>avec</span>", bloc)
        self.assertIn('title="Omar Aziz">OA</div>', bloc)
        self.assertIn('title="Rim Jlassi"', bloc)

    def test_personnes_avec_incluent_les_intervenants_d_une_tache_creee(self):
        from app.repositories import posts as posts_repo
        self.assertIn("WHERE p.evenement = 'creation_tache' AND ti.tache_id = p.tache_id", posts_repo._FEED_SELECT)

    def test_personnes_ajoutees_notifiees(self):
        _, mocks = self._requete("post", "/posts", data={"projet_id": "1", "type_code": "requete", "contenu": "x", "mentions": ["3"]},
                                 espions=[("app.repositories.posts.create_post", 101),
                                          ("app.repositories.notifications.creer_pour_plusieurs", None)])
        self.assertEqual(mocks["app.repositories.notifications.creer_pour_plusieurs"].call_args.args[0], [3])
        _, mocks = self._requete("post", "/projets/1/taches", data={"titre": "T", "intervenants": ["3"]},
                                 espions=[("app.repositories.taches.create_tache", 9),
                                          ("app.repositories.notifications.creer_pour_plusieurs", None)])
        self.assertEqual(mocks["app.repositories.notifications.creer_pour_plusieurs"].call_args.args[0], [3])


    def test_code_projet_verifie_lettre_de_la_phase(self):
        from app.repositories.projets import code_valide
        for code, phase, ok in (("26001X", "EXE", True), ("26001Z", "EXE", False), ("26001D", "EXE", False),
                                ("261000X", "EXE", True), ("2601X", "EXE", False), ("26001P", "APD", True),
                                ("26001p", "APS", False), ("x26001X", "EXE", False), ("26001E", "DOE", True)):
            with self.subTest(code=code, phase=phase):
                self.assertEqual(code_valide(code, phase), ok)
        donnees = {"nom": "Tour B", "code": "26001Z", "phase": "EXE", "chef_projet_id": "1"}
        _, mocks = self._requete("post", "/projets/nouveau", data=donnees,
                                 espions=[("app.repositories.projets.create_projet", 77)])
        mocks["app.repositories.projets.create_projet"].assert_not_called()

    def test_code_propose_reprend_le_numero_de_la_phase_liee(self):
        from unittest import mock as _mock
        from app.repositories import projets as projets_repo
        with _mock.patch("app.db.query_one", return_value=None):
            self.assertEqual(projets_repo.propose_code("EXE", phase_liee_code="24091D"), "24091X")
        with _mock.patch("app.db.query_one", return_value={"pris": 1}), \
                _mock.patch("app.db.query_all", return_value=[{"code": "26007P"}]):
            self.assertEqual(projets_repo.propose_code("APD", annee=2026, phase_liee_code="26001P"), "26008P")
        # API : seulement si la phase liée est visible.
        resp, mocks = self._requete("get", "/projets/code-propose?phase=EXE&phase_liee_id=2",
                                    espions=[("app.repositories.projets.propose_code", "24091X")],
                                    **{"app.repositories.projets.get_projet": {**PROJET, "code": "24091D"}})
        self.assertEqual(mocks["app.repositories.projets.propose_code"].call_args.kwargs["phase_liee_code"], "24091D")
        resp, mocks = self._requete("get", "/projets/code-propose?phase=EXE&phase_liee_id=2",
                                    espions=[("app.repositories.projets.propose_code", "26100X")],
                                    **{"app.repositories.projets.user_can_view": False})
        self.assertIsNone(mocks["app.repositories.projets.propose_code"].call_args.kwargs["phase_liee_code"])


if __name__ == "__main__":
    unittest.main()

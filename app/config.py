"""Configuration de l'application, lue depuis les variables d'environnement.

Rien de magique ici : tout vient de .env (voir .env.example) via
python-dotenv, chargé une fois au démarrage dans wsgi.py / app/__init__.py.
"""
import datetime
import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
    DATABASE_URL = os.environ.get(
        "DATABASE_URL",
        "postgresql://kairos:kairos@localhost:5432/kairos",
    )

    # Session persistante ("reste connecté" — retour Fadhel, 2026-09-19) :
    # sans ça, Flask pose un cookie de session "de navigateur" qui expire à
    # la fermeture de l'onglet/navigateur, ce qui déconnectait Fadhel à
    # chaque fois qu'il fermait Kairos. En marquant la session "permanent"
    # (voir auth.py:login) et en fixant une durée de vie longue ici, le
    # cookie devient persistant : 30 jours d'inactivité avant déconnexion
    # automatique (et cette durée est reconduite à chaque visite, puisque
    # SESSION_REFRESH_EACH_REQUEST est activé par défaut dans Flask).
    PERMANENT_SESSION_LIFETIME = datetime.timedelta(days=30)
    # En développement local (hors Docker), FLASK_ENV=development active
    # le mode debug (rechargement auto, pages d'erreur détaillées).
    DEBUG = os.environ.get("FLASK_ENV", "production") == "development"

    # Durcissement du cookie de session (revue sécurité, 2026-09-20) :
    # - HTTPONLY : déjà la valeur par défaut de Flask, mis explicite ici
    #   pour que ce soit documenté au même endroit que le reste (empêche
    #   tout JS côté page de lire le cookie de session).
    # - SAMESITE=Lax : le cookie n'est plus envoyé sur une requête
    #   POST/PUT/DELETE déclenchée par un site tiers (protection CSRF de
    #   base) tout en restant envoyé sur une navigation normale.
    # - SECURE : désactivé par défaut car l'appli tourne aujourd'hui en
    #   HTTP simple sur le LAN (pas de certificat) — un cookie "Secure"
    #   ne serait alors JAMAIS envoyé et personne ne pourrait se
    #   connecter. À passer à true (variable d'env SESSION_COOKIE_SECURE)
    #   le jour où un reverse proxy HTTPS est mis devant l'appli.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"

    # Dossier où sont stockées les pièces jointes (tâches/posts). Dans
    # Docker Compose, ce chemin est un volume monté (voir docker-compose.yml).
    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/app/uploads")

    # Taille de fichier max acceptée pour un upload (défaut 25 Mo).
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 25 * 1024 * 1024))

    # Envoi d'email (mot de passe oublié, mot de passe à la création d'un
    # compte — retour Fadhel, 2026-09-20). Tant que SMTP_HOST n'est pas
    # renseigné dans .env, app/mailer.py n'envoie rien et se contente de
    # logguer un avertissement — l'appli fonctionne normalement sans, ces
    # deux fonctionnalités précises sont juste inactives.
    SMTP_HOST = os.environ.get("SMTP_HOST") or None
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("SMTP_USER") or None
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD") or None
    SMTP_FROM = os.environ.get("SMTP_FROM") or None
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"

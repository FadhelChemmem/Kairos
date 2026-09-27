"""Configuration de l'application, lue depuis les variables d'environnement.

Rien de magique ici : tout vient de .env (voir .env.example) via
python-dotenv, chargé une fois au démarrage dans wsgi.py / app/__init__.py.
"""
import datetime
import os


class Config:
    # Pas de valeur de repli ici (revue sécurité, PROMPT_CORRECTIONS.md
    # P0 #6) : une appli qui démarrerait avec une clé par défaut connue de
    # tous ("dev-secret-key-change-me") signerait ses cookies de session
    # avec cette même valeur partout où le .env n'a pas été renseigné,
    # permettant de forger une session (se connecter en tant que
    # n'importe qui) sans rien deviner. app/__init__.py:create_app()
    # refuse maintenant de démarrer si SECRET_KEY est absente, trop
    # courte, ou a été laissée à une valeur d'exemple connue.
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
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

    # Base publique de l'application (revue sécurité, PROMPT_CORRECTIONS.md
    # P0 #3), ex. "https://kairos.nanaki45.duckdns.org" (sans / final) —
    # utilisée pour construire les liens ABSOLUS envoyés par email
    # (réinitialisation de mot de passe, création de compte) sans jamais
    # faire confiance à l'en-tête Host de la requête entrante. Sans ce
    # réglage, url_for(..., _external=True) construirait l'URL à partir du
    # Host reçu (aucun SERVER_NAME fixé) : un attaquant qui envoie une
    # demande de réinitialisation avec un Host falsifié recevrait alors un
    # lien de réinitialisation pointant vers un domaine qu'il contrôle, et
    # capturerait le jeton dès que le lien est cliqué. Voir auth.py:
    # generer_lien_reset, qui refuse de construire un lien externe tant que
    # ce réglage est vide.
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")

    # Nombre de reverse proxys de confiance devant l'appli (ex. 1 pour un
    # nginx/Synology en HTTPS devant gunicorn). 0 = accès direct : les
    # en-têtes X-Forwarded-* sont alors ignorés. Voir app/__init__.py.
    TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "0") or 0)

    # Protection CSRF (Flask-WTF CSRFProtect, PROMPT_CORRECTIONS.md P2 #25) :
    # chaque POST doit porter le jeton de session, soit dans le champ caché
    # csrf_token des formulaires, soit dans l'en-tête X-CSRFToken pour un
    # fetch() (voir base.html). SameSite=Lax (plus haut) ne suffisait pas
    # seul : il ne protège ni d'une page du même site ni des vieux
    # navigateurs. Pas de durée de vie propre au jeton (défaut Flask-WTF :
    # 1 heure) : il est déjà lié à la session, et une page DailyLog ou un
    # formulaire laissé ouvert plus d'une heure ne doit pas échouer à
    # l'enregistrement.
    WTF_CSRF_TIME_LIMIT = None

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

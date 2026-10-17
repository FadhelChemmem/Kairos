"""Configuration de l'application, lue depuis les variables d'environnement.

Rien de magique ici : tout vient de .env (voir .env.example) via
python-dotenv, chargé une fois au démarrage dans wsgi.py (en Docker, les
variables sont passées directement par docker-compose.yml).
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
    # Lot 13 (audit temps T-I3) : le cookie n'est plus renvoyé à CHAQUE
    # réponse, seulement quand la session change (connexion, mode de
    # l'Admin, message, rappel du jour…). Sinon, plusieurs onglets qui se
    # rechargent en même temps (static/js/mode-onglets.js) pouvaient
    # réécrire, avec une réponse arrivée en retard, un cookie plus récent
    # (« Agir comme » choisi entre-temps, perdu). La durée de 30 jours est
    # de toute façon plafonnée par SESSION_DUREE_ABSOLUE ci-dessous ; le
    # rappel du jour (session["rappel_le"]) reconduit le cookie chaque jour.
    SESSION_REFRESH_EACH_REQUEST = False
    # Durée de vie ABSOLUE d'une session (audit sécurité I7, lot 10) : la
    # durée ci-dessus est glissante (reconduite à chaque visite), donc un
    # cookie volé restait valable indéfiniment. Au-delà de cette durée
    # depuis la connexion, il faut se reconnecter, même en étant actif.
    SESSION_DUREE_ABSOLUE = datetime.timedelta(
        days=int(os.environ.get("SESSION_DUREE_ABSOLUE_JOURS") or 30))
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
    # P0 #3), ex. "https://kairos.exemple.tn" (sans / final) —
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
    # Nginx Proxy Manager en HTTPS devant gunicorn). 0 = accès direct : les
    # en-têtes X-Forwarded-* sont alors ignorés. Voir app/proxy.py.
    TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT") or 0)
    # Adresses (IP ou réseaux CIDR, séparés par des virgules) d'où une
    # requête peut porter des en-têtes X-Forwarded-* crus par l'appli :
    # l'adresse TCP directe vue par gunicorn, c'est-à-dire celle du proxy
    # (décision du gérant, fin du lot 10). Vide : réseaux Docker
    # (172.16.0.0/12) + 127.0.0.1 + HOST_IP, avec un avertissement au
    # démarrage si le port 8000 est publié sur le LAN. Voir app/proxy.py.
    TRUSTED_PROXY_IPS = os.environ.get("TRUSTED_PROXY_IPS", "")
    # IP LAN du serveur (facultative), ajoutée à la liste par défaut
    # ci-dessus : un proxy de l'hôte peut arriver avec cette adresse.
    HOST_IP = os.environ.get("HOST_IP", "")
    # Adresse sur laquelle docker-compose.yml publie le port 8000 (WEB_BIND
    # du .env, transmis au conteneur) : 127.0.0.1 = joignable seulement
    # depuis le serveur (pas d'avertissement pour la liste par défaut).
    WEB_BIND = os.environ.get("WEB_BIND", "0.0.0.0")

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

    # Compression gzip des pages, JSON, CSS et JS de plus de 1 Ko (lot 11,
    # audit front I1) — voir app/perf.py. À passer à false si le reverse
    # proxy compresse déjà (gzip on; dans Nginx Proxy Manager) : inutile de
    # compresser deux fois.
    COMPRESSION_GZIP = os.environ.get("COMPRESSION_GZIP", "true").lower() != "false"

    # Taille de fichier max acceptée pour un upload (défaut 25 Mo).
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH") or 25 * 1024 * 1024)

    # Envoi d'email (mot de passe oublié, mot de passe à la création d'un
    # compte — retour Fadhel, 2026-09-20). Tant que SMTP_HOST n'est pas
    # renseigné dans .env, app/mailer.py n'envoie rien et se contente de
    # logguer un avertissement — l'appli fonctionne normalement sans, ces
    # deux fonctionnalités précises sont juste inactives.
    SMTP_HOST = os.environ.get("SMTP_HOST") or None
    # « or » : une variable présente mais vide dans .env (SMTP_PORT=) faisait
    # planter le démarrage (audit QA m5).
    SMTP_PORT = int(os.environ.get("SMTP_PORT") or 587)
    SMTP_USER = os.environ.get("SMTP_USER") or None
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD") or None
    SMTP_FROM = os.environ.get("SMTP_FROM") or None
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
    # Mode test des e-mails (décision du gérant, fin du lot 10) : adresses
    # et/ou domaines (@domaine), séparés par des virgules, seuls autorisés à
    # recevoir un e-mail. Vide ou absente : aucun filtre. Voir app/mailer.py.
    MAIL_DESTINATAIRES_AUTORISES = os.environ.get("MAIL_DESTINATAIRES_AUTORISES", "")

    # Mode test de Kairos (lot 12, décision du gérant) : true active, pour
    # les Admins seulement, « Agir comme… » (modifier au nom d'un autre
    # compte, tracé à son nom ET au nom de l'Admin dans le journal d'audit)
    # et la date simulée. Toute autre valeur (absente, vide, « 1 », « oui »…)
    # vaut false : ni bouton, ni route. « Voir comme… » (lecture seule)
    # existe toujours. À couper avant la mise en service réelle — voir
    # app/modes_admin.py et la section « Mode test » du README.
    MODE_TEST = os.environ.get("KAIROS_MODE_TEST", "false").strip().lower() == "true"

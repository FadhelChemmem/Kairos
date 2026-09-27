"""Application factory Flask — Kairos."""
import logging
import os

from flask import Flask, flash, g, redirect, request, url_for
from flask.logging import default_handler as flask_default_handler
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from . import db, utils
from .config import Config

# Valeurs d'exemple connues ("copié-collé du .env.example sans y toucher")
# à refuser explicitement en plus du simple contrôle de longueur — voir
# _valider_secret_key() (revue sécurité, PROMPT_CORRECTIONS.md P0 #6).
_SECRET_KEY_PLACEHOLDERS = {"dev-secret-key-change-me", "change-moi-aussi"}
_SECRET_KEY_MIN_LEN = 32

# Protection CSRF sur tous les POST (PROMPT_CORRECTIONS.md P2 #25) — voir
# config.py (WTF_CSRF_TIME_LIMIT) et base.html (jeton pour fetch()).
csrf = CSRFProtect()


def _valider_secret_key(app: Flask) -> None:
    """Refuse de démarrer sans une SECRET_KEY correcte (revue sécurité,
    PROMPT_CORRECTIONS.md P0 #6) : config.py n'a plus de valeur de repli
    (voir sa docstring) — sans ce contrôle, une appli lancée sans .env
    renseigné démarrerait quand même, silencieusement, avec une clé vide
    ou triviale, et signerait ses cookies de session avec une valeur
    connue/devinable (donc falsifiable). Ignoré en test : TestConfig
    utilise volontairement une clé courte ("test-secret")."""
    if app.testing:
        return
    secret = app.config.get("SECRET_KEY") or ""
    if len(secret) < _SECRET_KEY_MIN_LEN or secret in _SECRET_KEY_PLACEHOLDERS:
        raise RuntimeError(
            "SECRET_KEY est manquante, trop courte (32 caractères minimum requis), "
            "ou a été laissée à une valeur d'exemple. Générez-en une nouvelle avec : "
            "python3 -c \"import secrets; print(secrets.token_hex(32))\" "
            "et renseignez-la dans .env (voir .env.example)."
        )


def _chemin_interne(url: str | None) -> str | None:
    """Réduit un Referer absolu ("http://hote/projets/3?x=1") à son chemin
    interne ("/projets/3?x=1"), pour le valider avec utils.is_safe_next
    avant d'y rediriger (jamais vers un autre hôte)."""
    if not url:
        return None
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    if parts.netloc and parts.netloc != request.host:
        return None
    return parts.path + (f"?{parts.query}" if parts.query else "")


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)
    _valider_secret_key(app)

    # Logs d'erreurs visibles dans `docker compose logs web` (retour revue
    # architecte, 2026-09-20) : avant ça, une exception non gérée en prod
    # (DEBUG=False) ne laissait aucune trace exploitable — c'est ce qui a
    # rendu le bug "Internal Server Error" du 2026-09-19 difficile à
    # diagnostiquer (une capture d'écran du navigateur, rien côté serveur).
    # Handler explicite plutôt que de compter sur le comportement par
    # défaut de Flask/gunicorn, pour être sûr que la trace complète sort
    # bien sur stderr quel que soit l'environnement.
    if not app.debug and not app.testing:
        _handler = logging.StreamHandler()
        _handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ))
        # Retire le handler par défaut de Flask (installé au premier accès
        # à app.logger), sinon chaque ligne sortait deux fois (audit n°2).
        app.logger.removeHandler(flask_default_handler)
        app.logger.addHandler(_handler)
        app.logger.setLevel(logging.INFO)

    # Derrière un reverse proxy HTTPS (APP_BASE_URL en https://...), sans
    # ProxyFix, request.remote_addr vaut l'IP du proxy pour TOUS les
    # utilisateurs : la limite de connexions par IP (auth.py) bloquait
    # alors tout le monde dès 30 échecs, et le schéma/l'hôte vus par
    # l'appli étaient faux. TRUSTED_PROXY_COUNT = nombre de proxys de
    # confiance devant l'appli (0 = accès direct, aucun en-tête X-Forwarded-*
    # n'est cru — sinon n'importe qui pourrait usurper une IP).
    nb_proxys = app.config.get("TRUSTED_PROXY_COUNT", 0)
    if nb_proxys:
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=nb_proxys, x_proto=nb_proxys,
            x_host=nb_proxys, x_port=nb_proxys,
        )

    if (app.config.get("APP_BASE_URL", "").startswith("https://")
            and not app.config.get("SESSION_COOKIE_SECURE")):
        app.logger.warning(
            "APP_BASE_URL est en https:// mais SESSION_COOKIE_SECURE=false : le "
            "cookie de session peut circuler en clair. Passez-le à true dans .env."
        )

    db.init_pool(app.config["DATABASE_URL"])
    utils.register(app)

    @app.after_request
    def _entetes_securite(response):
        # En-têtes de sécurité (audit n°2) : interdit l'affichage de
        # l'appli dans une iframe d'un autre site (clickjacking), le
        # "reniflage" de type MIME, et limite le Referer envoyé hors site.
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    @app.errorhandler(CSRFError)
    def _csrf_error(exc):
        # Jeton absent/invalide (session expirée, page ouverte avant une
        # reconnexion...) : message clair et retour à la page d'origine
        # plutôt que la page d'erreur 400 brute de Flask-WTF.
        app.logger.warning("Requête refusée (CSRF) : %s %s — %s",
                           request.method, request.path, exc.description)
        flash("Votre session a expiré ou le formulaire n'est plus valide. "
              "Veuillez réessayer.", "error")
        retour = _chemin_interne(request.referrer)
        if not utils.is_safe_next(retour):
            retour = url_for("auth.login") if g.get("user") is None else url_for("main.accueil")
        return redirect(retour)

    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    from . import auth

    app.register_blueprint(auth.bp)

    @app.before_request
    def _load_user():
        auth.load_logged_in_user()

    # Après _load_user (les before_request s'exécutent dans l'ordre
    # d'enregistrement) : ainsi g.user est déjà connu quand un jeton CSRF
    # est refusé, et _csrf_error renvoie vers la bonne page.
    csrf.init_app(app)

    from .routes.main import bp as main_bp
    from .routes.projets import bp as projets_bp
    from .routes.posts import bp as posts_bp
    from .routes.dailylog import bp as dailylog_bp
    from .routes.deadlines import bp as deadlines_bp
    from .routes.fichiers import bp as fichiers_bp
    from .routes.utilisateurs import bp as utilisateurs_bp
    from .routes.notifications import bp as notifications_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(projets_bp)
    app.register_blueprint(posts_bp)
    app.register_blueprint(dailylog_bp)
    app.register_blueprint(deadlines_bp)
    app.register_blueprint(fichiers_bp)
    app.register_blueprint(utilisateurs_bp)
    app.register_blueprint(notifications_bp)

    @app.route("/")
    def index():
        if g.user is None:
            return redirect(url_for("auth.login"))
        return redirect(url_for("main.accueil"))

    _register_cli(app)

    return app


def _register_cli(app: Flask) -> None:
    """Commande d'amorçage : le schéma ne contient aucun utilisateur au
    départ (seules les tables de référence sont pré-remplies), il faut
    donc créer le tout premier compte (admin) à la main. Usage :

        docker compose exec web flask create-user \\
            --email fadhel@midgard.tn --prenom Fadhel --nom Chemmem \\
            --password "un-mot-de-passe-solide" --role admin
    """
    import click

    @app.cli.command("create-user")
    @click.option("--email", required=True)
    @click.option("--prenom", required=True)
    @click.option("--nom", required=True)
    @click.option("--password", required=True)
    @click.option("--role", default="admin", type=click.Choice(
        ["admin", "chef_de_projet", "intervenant", "rh", "client"]
    ))
    def create_user_cmd(email, prenom, nom, password, role):
        from .auth import hash_password

        pw_hash = hash_password(password)
        try:
            with db.get_cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO utilisateur (email, mot_de_passe_hash, prenom, nom, role, verifie, actif)
                    VALUES (%s, %s, %s, %s, %s, true, true)
                    RETURNING id
                    """,
                    (email, pw_hash, prenom, nom, role),
                )
                user_id = cur.fetchone()["id"]
        except Exception as exc:
            # idx_utilisateur_rh_singleton (2026-09-16) : un seul compte RH
            # actif à la fois — message clair plutôt que la trace psycopg2 brute.
            if "idx_utilisateur_rh_singleton" in str(exc):
                click.echo(
                    "Erreur : il y a déjà un compte RH actif. "
                    "Désactivez-le d'abord pour en créer un nouveau.",
                    err=True,
                )
            elif "idx_utilisateur_email_lower" in str(exc):
                click.echo(f"Erreur : un compte existe déjà avec l'email {email}.", err=True)
            else:
                click.echo(f"Erreur lors de la création de l'utilisateur : {exc}", err=True)
            raise SystemExit(1)
        click.echo(f"Utilisateur créé : {prenom} {nom} <{email}> (id={user_id}, rôle={role})")

    @app.cli.command("migrer")
    def migrer_cmd():
        """Applique les migrations SQL du dossier migrations/ pas encore
        jouées (retour revue architecte, 2026-09-20 : plus de SQL collé à
        la main sur le NAS à chaque évolution du schéma).

        Idempotent — retient dans la table schema_migrations ce qui a déjà
        été appliqué, ne rejoue jamais une migration deux fois. À lancer
        après chaque mise à jour qui touche schema.sql :

            docker compose exec web flask migrer
        """
        import pathlib

        migrations_dir = pathlib.Path(__file__).resolve().parent.parent / "migrations"

        with db.get_cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version     VARCHAR(255) PRIMARY KEY,
                    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            cur.execute("SELECT version FROM schema_migrations")
            deja_appliquees = {row["version"] for row in cur.fetchall()}

        fichiers = sorted(migrations_dir.glob("*.sql")) if migrations_dir.exists() else []
        a_jouer = [f for f in fichiers if f.stem not in deja_appliquees]

        if not a_jouer:
            click.echo("Rien à faire : toutes les migrations sont déjà appliquées.")
            return

        for f in a_jouer:
            click.echo(f"Application de {f.name}...")
            sql = f.read_text(encoding="utf-8")
            try:
                with db.get_cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)", (f.stem,)
                    )
            except Exception as exc:
                click.echo(f"Erreur dans {f.name} : {exc}", err=True)
                click.echo(
                    "Migration arrêtée — les précédentes de cette exécution "
                    "sont déjà enregistrées, celle-ci et les suivantes non.",
                    err=True,
                )
                raise SystemExit(1)
            click.echo("  -> OK")

        click.echo(f"{len(a_jouer)} migration(s) appliquée(s).")

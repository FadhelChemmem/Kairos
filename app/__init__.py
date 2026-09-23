"""Application factory Flask — Kairos."""
import logging
import os

from flask import Flask, g, redirect, url_for

from . import db, utils
from .config import Config


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

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
        app.logger.addHandler(_handler)
        app.logger.setLevel(logging.INFO)

    db.init_pool(app.config["DATABASE_URL"])
    utils.register(app)

    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    from . import auth

    app.register_blueprint(auth.bp)

    @app.before_request
    def _load_user():
        auth.load_logged_in_user()

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

    @app.teardown_appcontext
    def _close_db(exception=None):
        # Les connexions sont gérées par le pool (voir db.get_cursor) —
        # rien à faire ici par requête, le pool reste ouvert pour tout le
        # cycle de vie du process.
        pass

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

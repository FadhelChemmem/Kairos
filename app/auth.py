"""Authentification : session Flask (cookie signé), pas de dépendance
supplémentaire — le hachage de mot de passe utilise werkzeug.security,
déjà fourni avec Flask.
"""
import datetime
import functools
import hashlib
import secrets

from flask import Blueprint, g, redirect, render_template, request, session, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, mailer
from .repositories import dailylog as dailylog_repo
from .repositories import notifications as notifications_repo
from .repositories import securite as securite_repo
from .repositories import utilisateurs as utilisateurs_repo

bp = Blueprint("auth", __name__)

# Longueur minimale d'un mot de passe — création de compte
# (routes/utilisateurs.py) et réinitialisation (ci-dessous) partagent la
# même règle (revue sécurité, 2026-09-20).
MOT_DE_PASSE_MIN_LEN = 8

# Durée de validité d'un jeton "mot de passe oublié". Choisie courte
# (1h) mais ATTENTION : ça n'a rien à voir avec la durée de la session de
# connexion normale (30 jours, voir PERMANENT_SESSION_LIFETIME dans
# config.py) — un utilisateur déjà connecté n'est jamais affecté par ce
# réglage, il ne concerne que le lien reçu par email.
RESET_TOKEN_TTL = datetime.timedelta(hours=1)

# Anti-bourrinage (revue sécurité, 2026-09-20) : au-delà de ce nombre de
# tentatives récentes pour un même email, connexion et demande de
# réinitialisation sont bloquées temporairement (voir securite_repo).
MAX_TENTATIVES = 5
FENETRE_TENTATIVES_MINUTES = 15


def get_user_by_email(email: str) -> dict | None:
    """Recherche insensible à la casse — cohérent avec idx_utilisateur_email_lower."""
    return db.query_one(
        """
        SELECT id, email, mot_de_passe_hash, nom, prenom, role, actif
        FROM utilisateur
        WHERE lower(email) = lower(%s)
        """,
        (email,),
    )


def get_user_by_id(user_id: int) -> dict | None:
    return db.query_one(
        """
        SELECT id, email, nom, prenom, role, actif, poste, equipe_code, avatar_chemin
        FROM utilisateur
        WHERE id = %s
        """,
        (user_id,),
    )


def hash_password(plain: str) -> str:
    return generate_password_hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return check_password_hash(hashed, plain)


def load_logged_in_user() -> None:
    """Appelé avant chaque requête (voir app/__init__.py) pour peupler g.user
    et, dans la foulée, le compteur de notifications non lues affiché dans
    la cloche de la barre du haut (base.html)."""
    user_id = session.get("user_id")
    g.user = get_user_by_id(user_id) if user_id else None
    g.notifications_non_lues = notifications_repo.compter_non_lues(g.user["id"]) if g.user else 0


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        if not g.user["actif"]:
            session.clear()
            flash("Ce compte a été désactivé.", "error")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def _verifier_rappel_dailylog(user_id: int, aujourdhui: "datetime.date | None" = None) -> None:
    """Notification automatique si le DailyLog de la veille n'a pas été
    rempli, déclenchée à la connexion du lendemain (voir spec). Une seule
    fois par jour : on vérifie qu'un tel rappel n'a pas déjà été créé
    aujourd'hui avant d'en recréer un. `aujourdhui` est injectable pour les
    tests (voir tests/test_smoke.py) — sinon la date du jour."""
    aujourdhui = aujourdhui or datetime.date.today()
    hier = aujourdhui - datetime.timedelta(days=1)
    # Pas de rappel pour un week-end non travaillé (heuristique simple, pas
    # de notion de jour férié/congé modélisée pour l'instant). Corrigé
    # 2026-09-19 (retour Fadhel) : ça ne sautait que le dimanche, pas le
    # samedi — weekday() 5 = samedi, 6 = dimanche.
    if hier.weekday() >= 5:
        return
    if dailylog_repo.list_entrees_jour(user_id, hier):
        return
    if notifications_repo.a_deja_un_rappel_dailylog(user_id, aujourdhui):
        return
    notifications_repo.creer(
        user_id, "rh_info",
        f"Rappel DailyLog : vous n'avez pas rempli votre journée du {hier.strftime('%d/%m/%Y')}.",
    )


def generer_lien_reset(user_id: int) -> str:
    """Génère un jeton de réinitialisation (voir RESET_TOKEN_TTL), enregistre
    uniquement son empreinte SHA-256 (voir set_reset_token) et retourne le
    lien complet à envoyer par email. Partagé par mot_de_passe_oublie()
    ci-dessous et par la création de compte sans mot de passe initial
    (routes/utilisateurs.py:creer, retour Fadhel 2026-09-21) : dans les
    deux cas, c'est ce même lien qui permet à l'utilisateur de définir
    lui-même son mot de passe."""
    jeton = secrets.token_urlsafe(32)
    jeton_hash = hashlib.sha256(jeton.encode()).hexdigest()
    expire_le = datetime.datetime.now(datetime.timezone.utc) + RESET_TOKEN_TTL
    utilisateurs_repo.set_reset_token(user_id, jeton_hash, expire_le)
    return url_for("auth.reinitialiser_mot_de_passe", jeton=jeton, _external=True)


def role_required(*roles):
    """Restreint une vue à certains rôles (ex. @role_required('admin'))."""

    def decorator(view):
        @functools.wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user["role"] not in roles:
                flash("Accès réservé.", "error")
                return redirect(url_for("main.accueil"))
            return view(*args, **kwargs)

        return wrapped

    return decorator


@bp.route("/connexion", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        error = None
        user = None

        # Anti-bourrinage (revue sécurité, 2026-09-20) : ne compte que les
        # tentatives ratées, par email — pas par IP (LAN interne, plusieurs
        # personnes derrière la même IP au bureau).
        if email and securite_repo.compter_tentatives_recentes(
            "connexion", email, FENETRE_TENTATIVES_MINUTES
        ) >= MAX_TENTATIVES:
            error = "Trop de tentatives. Réessayez dans quelques minutes."
        else:
            user = get_user_by_email(email)
            if user is None or not verify_password(password, user["mot_de_passe_hash"]):
                error = "Email ou mot de passe incorrect."
                if email:
                    securite_repo.enregistrer_tentative("connexion", email)
            elif not user["actif"]:
                error = "Ce compte a été désactivé."

        if error is None:
            session.clear()
            # Session persistante (retour Fadhel, 2026-09-19) : voir la note
            # sur PERMANENT_SESSION_LIFETIME dans app/config.py — sans ce
            # flag, Flask ignore cette durée et pose un cookie "de session"
            # qui expire à la fermeture du navigateur.
            session.permanent = True
            session["user_id"] = user["id"]
            _verifier_rappel_dailylog(user["id"])
            next_url = request.args.get("next") or url_for("main.accueil")
            return redirect(next_url)

        flash(error, "error")

    return render_template("login.html")


@bp.route("/deconnexion")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/mot-de-passe-oublie", methods=["GET", "POST"])
def mot_de_passe_oublie():
    """Retour Fadhel, 2026-09-20 : le lien existait déjà dans login.html
    mais était désactivé ("pas encore disponible"). Le message rendu est
    TOUJOURS le même, que l'email existe ou non en base (revue sécurité :
    ne jamais laisser deviner quels emails sont des comptes réels)."""
    if request.method == "POST":
        email = request.form.get("email", "").strip()

        if email:
            if securite_repo.compter_tentatives_recentes(
                "mot_de_passe_oublie", email, FENETRE_TENTATIVES_MINUTES
            ) >= MAX_TENTATIVES:
                # Même ici, pas de message différent : on ne veut pas non
                # plus qu'un compteur de demandes serve à deviner un email
                # valide. On n'envoie juste rien de plus pour celui-ci.
                pass
            else:
                securite_repo.enregistrer_tentative("mot_de_passe_oublie", email)
                user = get_user_by_email(email)
                if user is not None and user["actif"]:
                    lien = generer_lien_reset(user["id"])
                    mailer.envoyer(
                        user["email"],
                        "Kairos — réinitialisation de votre mot de passe",
                        "Bonjour,\n\n"
                        "Une réinitialisation de mot de passe a été demandée pour ce "
                        "compte Kairos.\n\n"
                        f"Ce lien est valable 1 heure : {lien}\n\n"
                        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet "
                        "email — rien ne change sur votre compte.",
                    )

        flash(
            "Si un compte existe avec cet email, un lien de réinitialisation "
            "vient d'être envoyé.",
            "success",
        )
        return redirect(url_for("auth.login"))

    return render_template("mot_de_passe_oublie.html")


@bp.route("/reinitialiser/<jeton>", methods=["GET", "POST"])
def reinitialiser_mot_de_passe(jeton):
    jeton_hash = hashlib.sha256(jeton.encode()).hexdigest()
    utilisateur = utilisateurs_repo.get_par_reset_token_hash(jeton_hash)

    if utilisateur is None or not utilisateur["actif"]:
        flash("Ce lien de réinitialisation est invalide ou a expiré.", "error")
        return redirect(url_for("auth.mot_de_passe_oublie"))

    if request.method == "POST":
        mot_de_passe = request.form.get("mot_de_passe", "")
        confirmation = request.form.get("confirmation", "")

        if mot_de_passe != confirmation:
            flash("Les deux mots de passe ne correspondent pas.", "error")
        elif len(mot_de_passe) < MOT_DE_PASSE_MIN_LEN:
            flash(f"Le mot de passe doit faire au moins {MOT_DE_PASSE_MIN_LEN} caractères.", "error")
        else:
            utilisateurs_repo.set_password(
                utilisateur["id"], hash_password(mot_de_passe), utilisateur["id"]
            )
            flash("Mot de passe changé. Vous pouvez vous connecter.", "success")
            return redirect(url_for("auth.login"))

    return render_template("reinitialiser_mot_de_passe.html", jeton=jeton)

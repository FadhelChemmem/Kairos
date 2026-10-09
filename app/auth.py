"""Authentification : session Flask (cookie signé), pas de dépendance
supplémentaire — le hachage de mot de passe utilise werkzeug.security,
déjà fourni avec Flask.
"""
import datetime
import functools
import hashlib
import logging
import secrets
import time

from flask import Blueprint, current_app, g, redirect, render_template, request, session, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, mailer, modes_admin
from .repositories import dailylog as dailylog_repo
from .repositories import notifications as notifications_repo
from .repositories import securite as securite_repo
from .repositories import utilisateurs as utilisateurs_repo
from .utils import is_safe_next, texte_rappel_daily_log

logger = logging.getLogger(__name__)

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

# Anti-bourrinage par IP (PROMPT_CORRECTIONS.md P2 #24) : une limite
# uniquement par email permet à n'importe qui connaissant l'adresse d'un
# compte (l'admin, par exemple) de le verrouiller à répétition — un simple
# déni de service, sans avoir besoin de deviner le mot de passe. Le seuil
# est volontairement plus haut que MAX_TENTATIVES : plusieurs personnes
# travaillent derrière la même IP au bureau (voir plus bas), on ne veut
# pas les bloquer tous pour l'erreur de l'un. Ça ne supprime pas la
# possibilité de verrouiller UN compte ciblé (il suffit toujours de
# connaître son email), mais ça limite un bourrinage automatisé ou touchant
# plusieurs comptes depuis une même source.
MAX_TENTATIVES_IP = 30

# Hash de mot de passe factice (PROMPT_CORRECTIONS.md P2 #24) : généré une
# fois au démarrage, jamais associé à aucun compte. Quand aucun utilisateur
# ne correspond à l'email saisi, on compare quand même le mot de passe
# fourni à CE hash (résultat ignoré) plutôt que de court-circuiter
# directement — sans ça, une tentative sur un email qui EXISTE prend
# mesurablement plus de temps (un hash à vérifier) qu'une tentative sur un
# email inconnu, ce qui permettrait de deviner quels emails sont des
# comptes réels rien qu'en chronométrant les réponses.
_HASH_FACTICE = generate_password_hash(secrets.token_urlsafe(32))
# Préfixe de la méthode de hachage actuelle ("scrypt:..."), pour repérer les
# hashes anciens (pbkdf2 importés de Chronos) à re-hacher à la connexion.
_METHODE_HASH_ACTUELLE = _HASH_FACTICE.split("$", 1)[0].split(":", 1)[0] + ":"


def get_user_by_email(email: str) -> dict | None:
    """Recherche insensible à la casse — cohérent avec idx_utilisateur_email_lower."""
    return db.query_one(
        """
        SELECT u.id, u.email, u.mot_de_passe_hash, u.nom, u.prenom, u.role, u.actif,
               u.fuseau, COALESCE(u.date_embauche, u.created_at::date) AS debut_daily_log,
               COALESCE(s.generation, 0) AS session_gen
        FROM utilisateur u
        LEFT JOIN utilisateur_session s ON s.utilisateur_id = u.id
        WHERE lower(u.email) = lower(%s)
        """,
        (email,),
    )


def get_user_by_id(user_id: int) -> dict | None:
    return db.query_one(
        """
        SELECT u.id, u.email, u.nom, u.prenom, u.role, u.actif, u.poste, u.equipe_code,
               u.avatar_chemin, u.fuseau, COALESCE(u.date_embauche, u.created_at::date) AS debut_daily_log,
               COALESCE(s.generation, 0) AS session_gen
        FROM utilisateur u
        LEFT JOIN utilisateur_session s ON s.utilisateur_id = u.id
        WHERE u.id = %s
        """,
        (user_id,),
    )


def hash_password(plain: str) -> str:
    return generate_password_hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return check_password_hash(hashed, plain)


def password_fingerprint(mot_de_passe_hash: str) -> str:
    """Empreinte non réversible du hash de mot de passe, déposée dans la
    session à la connexion (PROMPT_CORRECTIONS.md P2 #17) — jamais le hash
    lui-même : le cookie de session est signé (donc pas falsifiable) mais
    reste lisible par quiconque y a accès, et mot_de_passe_hash n'a pas à
    s'y trouver. Comparée à celle du hash actuel à chaque requête (voir
    load_logged_in_user ci-dessous) : si le mot de passe a changé entre
    temps (par soi-même sur un autre appareil, par un admin, ou via "mot de
    passe oublié"), l'empreinte ne correspond plus et la session est
    invalidée — exactement l'effet recherché."""
    return hashlib.sha256(mot_de_passe_hash.encode()).hexdigest()


def load_logged_in_user() -> None:
    """Appelé avant chaque requête (voir app/__init__.py) pour peupler g.user
    et, dans la foulée, le compteur de notifications non lues affiché dans
    la cloche de la barre du haut (base.html)."""
    if request.endpoint == "static":
        # Fichiers CSS/JS/images : pas besoin de l'utilisateur, et ça
        # évitait 3 requêtes SQL par fichier statique servi (audit n°2).
        g.user = None
        g.notifications_non_lues = 0
        return
    user_id = session.get("user_id")
    g.user = get_user_by_id(user_id) if user_id else None

    if g.user is not None:
        # Invalidation de session après changement de mot de passe (PROMPT_
        # CORRECTIONS.md P2 #17) — voir password_fingerprint() ci-dessus.
        hash_actuel = utilisateurs_repo.get_mot_de_passe_hash(user_id)
        if hash_actuel is None or session.get("pw_fingerprint") != password_fingerprint(hash_actuel):
            session.clear()
            g.user = None
            flash("Votre mot de passe a été changé, veuillez vous reconnecter.", "error")

    if g.user is not None and _session_revoquee_ou_expiree():
        session.clear()
        g.user = None
        flash("Votre session a expiré, veuillez vous reconnecter.", "error")

    # Lot 12 : « Voir / Agir comme » et date simulée, une fois la session
    # RÉELLE (celle de l'Admin) validée ci-dessus — g.user devient le compte
    # vu, g.admin_reel garde l'Admin. Voir app/modes_admin.py.
    modes_admin.appliquer()

    # Pas de rappel Daily log pendant un mode de l'Admin (aucun effet de
    # bord en « Voir comme » ; en « Agir comme » ou avec une date simulée,
    # il viserait des jours qui ne sont pas réellement manqués).
    if g.user is not None and g.admin_reel is None and g.date_simulee is None:
        _rappel_dailylog_du_jour()

    g.notifications_non_lues = notifications_repo.compter_non_lues(g.user["id"]) if g.user else 0


def _session_revoquee_ou_expiree() -> bool:
    """Audit sécurité I7 (lot 10) :
    - session révoquée : la génération mémorisée à la connexion ne
      correspond plus à celle du compte (déconnexion ailleurs, compte
      désactivé — voir utilisateurs_repo.revoquer_sessions) ; une session
      ouverte avant ce correctif n'a pas de génération et vaut 0, comme un
      compte jamais révoqué : personne n'est déconnecté au déploiement ;
    - durée absolue dépassée (SESSION_DUREE_ABSOLUE, config.py) depuis la
      connexion ; une session d'avant ce correctif démarre maintenant."""
    if session.get("gen", 0) != (g.user.get("session_gen") or 0):
        return True
    maintenant = int(time.time())
    debut = session.get("iat")
    if not isinstance(debut, int):
        session["iat"] = maintenant
        return False
    duree = current_app.config.get("SESSION_DUREE_ABSOLUE")
    return bool(duree) and maintenant - debut > duree.total_seconds()


def _rappel_dailylog_du_jour() -> None:
    """Rappel Daily log une fois par jour et par session (audit sécurité
    I13) : il n'était créé qu'à la connexion explicite, or la session dure
    30 jours — il ne partait presque jamais. Jamais bloquant : une erreur
    est journalisée, la page s'affiche."""
    # « Aujourd'hui » au fuseau de la personne (Tunis / Guyane, lot 10).
    aujourdhui = dailylog_repo.aujourdhui_pour(g.user).isoformat()
    if g.user["role"] in ("rh", "client") or session.get("rappel_le") == aujourdhui:
        return
    session["rappel_le"] = aujourdhui
    try:
        # Lot 11 : les anciens rappels dont le jour a été rempli depuis (par
        # la personne, un chef, une reprise…) sont marqués lus.
        notifications_repo.marquer_rappels_dailylog_lus(g.user["id"])
        _verifier_rappel_dailylog(g.user)
    except Exception:
        current_app.logger.exception("Rappel Daily log impossible (id=%s)", g.user["id"])


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


def _verifier_rappel_dailylog(user: dict, aujourdhui: "datetime.date | None" = None) -> None:
    """Notification automatique pour les jours ouvrés passés sans heures ni
    absence. Lot 10 : « aujourd'hui » au fuseau de la personne, et pas de
    rappel pour un jour antérieur à son arrivée (date d'embauche, à défaut
    création du compte). `aujourdhui` est injectable pour les tests.

    Lot 11 b (demande du gérant) : texte clair (« Daily log du mardi 7
    octobre non rempli »), et les jours oubliés de la fenêtre où la personne
    peut encore saisir (FENETRE_LIBRE_JOURS, week-ends exclus, aujourd'hui
    exclu) qui n'ont jamais été rappelés sont regroupés en UNE notification
    (« 3 jours de Daily log non remplis : … ») — un jour déjà rappelé, même
    par l'ancien format, ne l'est plus (notification.rappel_jours)."""
    aujourdhui = aujourdhui or dailylog_repo.aujourdhui_pour(user)
    # Heures saisies OU journée marquée absente : pas d'oubli.
    manques = [j for j in dailylog_repo.jours_manques_recents(user, aujourdhui=aujourdhui) if j < aujourdhui]
    if not manques:
        return
    notifications_repo.creer_rappel_dailylog(
        user["id"], manques, lambda jours: texte_rappel_daily_log(jours, aujourdhui))


def generer_lien_reset(user_id: int, current_user_id: int | None = None) -> str:
    """Génère un jeton de réinitialisation (voir RESET_TOKEN_TTL), enregistre
    uniquement son empreinte SHA-256 (voir set_reset_token) et retourne le
    lien complet à envoyer par email. Partagé par mot_de_passe_oublie()
    ci-dessous et par la création de compte sans mot de passe initial
    (routes/utilisateurs.py:creer, retour Fadhel 2026-09-21) : dans les
    deux cas, c'est ce même lien qui permet à l'utilisateur de définir
    lui-même son mot de passe. Aussi utilisé par le bouton « Envoyer un
    lien de réinitialisation » de la fiche (Admin/RH : le RH ne fixe plus
    lui-même un mot de passe, décision du gérant, lot 10) —
    `current_user_id` est alors celui qui a déclenché l'envoi."""
    jeton = secrets.token_urlsafe(32)
    jeton_hash = hashlib.sha256(jeton.encode()).hexdigest()
    expire_le = datetime.datetime.now(datetime.timezone.utc) + RESET_TOKEN_TTL
    utilisateurs_repo.set_reset_token(user_id, jeton_hash, expire_le, current_user_id=current_user_id)

    # PROMPT_CORRECTIONS.md P0 #3 : on construit le lien à partir
    # d'APP_BASE_URL (voir config.py), jamais avec
    # url_for(..., _external=True) — celui-ci utiliserait l'en-tête Host de
    # la requête entrante, que Flask ne valide pas par défaut (pas de
    # SERVER_NAME fixé) : un Host falsifié produirait un lien de
    # réinitialisation pointant vers un domaine contrôlé par l'attaquant.
    chemin = url_for("auth.reinitialiser_mot_de_passe", jeton=jeton)
    base = current_app.config.get("APP_BASE_URL") or ""
    if not base:
        logger.warning(
            "APP_BASE_URL n'est pas configuré (voir .env.example) : le lien "
            "envoyé par email est relatif, pas absolu — il ne fonctionnera "
            "pas correctement dans un client mail."
        )
        return chemin
    return f"{base}{chemin}"


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
        # tentatives ratées, par email — pas seulement par IP, puisque
        # plusieurs personnes travaillent derrière la même IP au bureau
        # (LAN interne). PROMPT_CORRECTIONS.md P2 #24 : une limite PAR IP
        # est ajoutée en plus (voir MAX_TENTATIVES_IP) pour freiner un
        # bourrinage automatisé/distribué sur plusieurs comptes depuis une
        # même source — ip toujours vérifiée, même sans email saisi.
        ip = request.remote_addr or "ip-inconnue"
        # Compteur par email ET par IP (audit n°2) : compté par email seul,
        # n'importe qui connaissant l'adresse d'un compte (l'admin par
        # exemple) pouvait le verrouiller pour tout le monde, à répétition.
        # Lié à l'IP, un attaquant ne verrouille plus que ses propres
        # tentatives ; le vrai propriétaire, depuis son poste, se connecte
        # toujours. Derrière un reverse proxy, remote_addr est la vraie IP
        # du client quand la requête arrive d'une adresse de
        # TRUSTED_PROXY_IPS (avec TRUSTED_PROXY_COUNT > 0, voir
        # app/proxy.py) ; d'ailleurs, c'est l'adresse TCP directe : un
        # X-Forwarded-For forgé sur le LAN ne change jamais la clé.
        # tentative_securite.cle est un VARCHAR(255) : un email plus long
        # faisait une erreur 500 (aucun compte ne peut l'avoir de toute façon).
        email = email[:254]
        cle_email_ip = f"{email}|{ip}"[:255]
        trop_de_tentatives_email = email and securite_repo.compter_tentatives_recentes(
            "connexion", cle_email_ip, FENETRE_TENTATIVES_MINUTES
        ) >= MAX_TENTATIVES
        trop_de_tentatives_ip = securite_repo.compter_tentatives_recentes(
            "connexion_ip", ip, FENETRE_TENTATIVES_MINUTES
        ) >= MAX_TENTATIVES_IP

        if trop_de_tentatives_email or trop_de_tentatives_ip:
            error = "Trop de tentatives. Réessayez dans quelques minutes."
        else:
            user = get_user_by_email(email)
            if user is None:
                # PROMPT_CORRECTIONS.md P2 #24 : comparaison à un hash
                # factice pour que ce chemin prenne un temps comparable à
                # celui où l'email existe (voir _HASH_FACTICE) — résultat
                # ignoré, seul le temps passé compte ici.
                verify_password(password, _HASH_FACTICE)
                error = "Email ou mot de passe incorrect."
                if email:
                    securite_repo.enregistrer_tentative("connexion", cle_email_ip)
                securite_repo.enregistrer_tentative("connexion_ip", ip)
            elif not verify_password(password, user["mot_de_passe_hash"]):
                error = "Email ou mot de passe incorrect."
                securite_repo.enregistrer_tentative("connexion", cle_email_ip)
                securite_repo.enregistrer_tentative("connexion_ip", ip)
            elif not user["actif"]:
                error = "Ce compte a été désactivé."

        if error is None and not user["mot_de_passe_hash"].startswith(_METHODE_HASH_ACTUELLE):
            # Comptes importés de Chronos (pbkdf2) : re-hachés avec la
            # méthode actuelle dès la première connexion réussie. Sinon leur
            # vérification, deux fois plus lente que celle du hash factice,
            # laissait deviner par chronométrage quels emails venaient de
            # Chronos (audit n°2).
            nouveau_hash = hash_password(password)
            try:
                utilisateurs_repo.set_password(user["id"], nouveau_hash, user["id"])
                user["mot_de_passe_hash"] = nouveau_hash
            except Exception:
                # Jamais bloquant : la connexion reste valide avec l'ancien hash.
                current_app.logger.exception("Re-hachage du mot de passe impossible (id=%s)", user["id"])

        if error is None:
            session.clear()
            # Session persistante (retour Fadhel, 2026-09-19) : voir la note
            # sur PERMANENT_SESSION_LIFETIME dans app/config.py — sans ce
            # flag, Flask ignore cette durée et pose un cookie "de session"
            # qui expire à la fermeture du navigateur.
            session.permanent = True
            session["user_id"] = user["id"]
            # Empreinte du mot de passe actuel (PROMPT_CORRECTIONS.md P2 #17)
            # — voir password_fingerprint().
            session["pw_fingerprint"] = password_fingerprint(user["mot_de_passe_hash"])
            # Révocation et durée absolue (audit sécurité I7, lot 10).
            session["gen"] = user.get("session_gen") or 0
            session["iat"] = int(time.time())
            # Pas de Daily log pour le RH ni un Client (lot 7).
            if user["role"] not in ("rh", "client"):
                _verifier_rappel_dailylog(user)
                session["rappel_le"] = dailylog_repo.aujourdhui_pour(user).isoformat()
            # Ouverture de redirection (PROMPT_CORRECTIONS.md P0 #5) : ?next=
            # n'est jamais fiable tel quel (lien envoyé par un tiers) — voir
            # is_safe_next() dans utils.py.
            next_url = request.args.get("next")
            if not is_safe_next(next_url):
                next_url = url_for("main.accueil")
            return redirect(next_url)

        flash(error, "error")

    return render_template("login.html")


@bp.route("/deconnexion", methods=["POST"])
def logout():
    """POST uniquement (PROMPT_CORRECTIONS.md P2 #25) : en GET, un simple
    <img src="/deconnexion"> sur n'importe quelle page suffisait à
    déconnecter l'utilisateur. Le formulaire est dans base.html.

    Audit sécurité I7 (lot 10) : vider le cookie ne suffisait pas — une
    copie de ce cookie restait valable 30 jours. La génération de sessions
    du compte est incrémentée : toutes ses sessions sont fermées (cet
    appareil et les autres)."""
    user_id = session.get("user_id")
    # Lot 12 : la déconnexion termine aussi « Voir / Agir comme » et la date
    # simulée (session vidée ci-dessous) — sortie tracée au journal.
    admin = g.get("admin_reel")
    if admin is not None and g.get("mode_admin"):
        modes_admin.journaliser(modes_admin.TABLES_JOURNAL[g.mode_admin], "SORTIE", admin["id"], g.user,
                                raison="deconnexion")
    if g.get("date_simulee") is not None and user_id:
        modes_admin.journaliser(modes_admin.TABLE_DATE, "SORTIE", user_id, date=g.date_simulee.isoformat(),
                                raison="deconnexion")
    if user_id:
        try:
            utilisateurs_repo.revoquer_sessions(user_id)
        except Exception:
            current_app.logger.exception("Révocation des sessions impossible (id=%s)", user_id)
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/mot-de-passe-oublie", methods=["GET", "POST"])
def mot_de_passe_oublie():
    """Retour Fadhel, 2026-09-20 : le lien existait déjà dans login.html
    mais était désactivé ("pas encore disponible"). Le message rendu est
    TOUJOURS le même, que l'email existe ou non en base (revue sécurité :
    ne jamais laisser deviner quels emails sont des comptes réels)."""
    if request.method == "POST":
        email = request.form.get("email", "").strip()[:254]

        if not mailer.est_configure():
            # Pas de faux succès (lot 10) : sans SMTP, aucun lien ne peut
            # partir. Le message ne dépend que de la configuration du
            # serveur, jamais de l'email saisi — il ne révèle donc pas si
            # un compte existe.
            flash(
                "Impossible d'envoyer le lien de réinitialisation : l'envoi "
                "d'e-mails n'est pas configuré sur ce serveur. Contactez "
                "l'administrateur ou le RH.",
                "error",
            )
            return redirect(url_for("auth.mot_de_passe_oublie"))

        if email and not mailer.destinataire_autorise(email):
            # Mode test des e-mails (MAIL_DESTINATAIRES_AUTORISES, décision
            # du gérant) : rien ne partira vers cette adresse, on le dit au
            # lieu d'un faux « lien envoyé ». La réponse ne dépend que de
            # l'adresse SAISIE et de la configuration, jamais de la base :
            # elle ne révèle pas si un compte existe.
            flash(
                "Kairos est en phase de test : les e-mails ne partent que vers "
                "quelques adresses autorisées, et aucun lien ne peut être envoyé "
                "à cette adresse. Contactez le RH ou l'administrateur.",
                "error",
            )
            return redirect(url_for("auth.mot_de_passe_oublie"))

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
                    # En arrière-plan (audit n°2) : un envoi SMTP synchrone
                    # rendait la réponse nettement plus lente quand l'email
                    # existe, ce qui permettait de deviner les comptes réels.
                    mailer.envoyer_en_arriere_plan(
                        user["email"],
                        "Kairos — réinitialisation de votre mot de passe",
                        "Bonjour,\n\n"
                        "Une réinitialisation de mot de passe a été demandée pour ce "
                        "compte Kairos.\n\n"
                        f"Ce lien est valable 1 heure : {lien}\n\n"
                        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet "
                        "email — rien ne change sur votre compte.",
                    )

        # Envoi en arrière-plan : son échec éventuel n'est pas connu ici
        # (et le signaler révélerait que le compte existe) — d'où un
        # message qui ne promet pas que l'e-mail est déjà parti.
        flash(
            "Si un compte actif existe avec cet email, un lien de "
            "réinitialisation va lui être envoyé. Rien reçu d'ici quelques "
            "minutes ? Vérifiez vos courriers indésirables ou contactez le RH.",
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
            # Consommation atomique du jeton (PROMPT_CORRECTIONS.md P0 #3) :
            # get_par_reset_token_hash() ci-dessus n'a servi qu'à afficher
            # la page ; la vérification qui compte est celle, atomique,
            # faite par consommer_reset_token() (voir sa docstring — évite
            # qu'un jeton valide soit utilisable deux fois en concurrence).
            consomme = utilisateurs_repo.consommer_reset_token(jeton_hash, hash_password(mot_de_passe))
            if consomme is None:
                flash("Ce lien de réinitialisation est invalide ou a expiré.", "error")
                return redirect(url_for("auth.mot_de_passe_oublie"))
            flash("Mot de passe changé. Vous pouvez vous connecter.", "success")
            return redirect(url_for("auth.login"))

    return render_template("reinitialiser_mot_de_passe.html", jeton=jeton)

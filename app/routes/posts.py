"""Actions sur les posts : création manuelle, "rebond" (voir note dans
repositories/posts.py — jamais nommé ainsi dans l'UI), réaction,
commentaire. Chaque action redirige vers la page d'où elle a été
déclenchée (`next`), pour marcher aussi bien depuis l'accueil que depuis
une page projet.
"""
from flask import Blueprint, abort, current_app, flash, g, jsonify, request, url_for

from ..auth import login_required
from ..repositories import notifications as notifications_repo
from ..repositories import posts as posts_repo
from ..repositories import projets as projets_repo
from ..repositories import utilisateurs as utilisateurs_repo
from .. import partiel
from .. import validation as v
from ..storage import delete_upload, save_upload
from ..utils import EQUIPE_CHOICES, is_lien_valide, redirect_vers_next

bp = Blueprint("posts", __name__, url_prefix="/posts")

TYPES_VALIDES = {"envoi", "reponse", "question", "requete", "information"}
EQUIPES_VALIDES = {code for code, _ in EQUIPE_CHOICES}
PROJET_CLOS = projets_repo.ETATS_CLOS
MESSAGE_PROJET_CLOS = (
    "Ce projet est clos (terminé ou abandonné)\u00a0: plus aucune intervention n’est "
    "possible tant que son chef ou un co-chef ne change pas son état."
)
# Un Client n'envoie que des Requêtes et des Informations, sur les projets de
# son équipe (décision Fadhel, lot 7).
TYPES_CLIENT = {"requete", "information"}
REACTIONS_VALIDES = {"ok", "pouce"}


def _safe_redirect(default_endpoint="main.accueil"):
    return redirect_vers_next(default_endpoint)


def _refus(message: str, statut: int = 422, champ: str | None = None):
    """Refus : JSON pour une requête partielle (lot 13 : le champ en cause
    est signalé, la saisie reste), message flash et retour à la page sinon."""
    if partiel.est_partiel():
        return partiel.refuser(message, statut, champs={champ: message} if champ else None)
    flash(message, "error")
    return _safe_redirect()


def _refus_si_clos(post: dict):
    """Post d'un projet terminé ou abandonné : plus de commentaire, de
    réaction ni de repost, pour personne (décision Fadhel, lot 7)."""
    if post.get("projet_etat") in PROJET_CLOS:
        return _refus(MESSAGE_PROJET_CLOS, 409)
    return None


# Fils de la page qui reçoivent un post publié en partiel (lot 13) :
# accueil (projet affiché sur chaque carte) et fiche projet.
FILS_PARTIELS = {"#fil-liste": True, "#fil-posts": False}


def reponse_publication(post_id: int, **fiche):
    """Réponse partielle d'une publication (lot 13, audit UX §2.2) : le post
    inséré en tête du fil de la page (cible #fil-liste ou #fil-posts, mode
    « avant »), les messages en toasts ; ailleurs (profil), toasts seuls."""
    cible = partiel.est_partiel()
    post = posts_repo.get_post_carte(post_id, g.user["id"]) if cible in FILS_PARTIELS else None
    if post is None:
        return partiel.rien()
    show_projet = FILS_PARTIELS[cible]
    next_url = url_for("main.accueil") if show_projet else url_for("projets.detail", projet_id=post["projet_id"])
    return partiel.repondre("partials/fil_item.html", post=post, show_projet=show_projet, next_url=next_url)


def _next_sans_ancre() -> str:
    """Page d'où vient l'action (champ `next`), sans l'ancre #post-N : sert
    aux liens de retour des formulaires re-rendus en partiel."""
    from ..utils import is_safe_next

    suivant = (request.form.get("next") or "").split("#", 1)[0]
    return suivant if is_safe_next(suivant) else url_for("main.accueil")


def _reponse_commentaires(post_id: int, **extra):
    """Bloc des commentaires d'un post re-rendu (lot 13, audit UX I6) : la
    cible #post-<id>-commentaires, et hors cible le compteur du post."""
    post = posts_repo.get_post_carte(post_id, g.user["id"])
    if post is None:
        abort(404)
    return partiel.repondre("partials/post_commentaires_maj.html", post=post, next_url=_next_sans_ancre(), **extra)


def _post_visible_ou_404(post_id: int) -> dict:
    """Post existant ET visible de l'utilisateur connecté (IDOR,
    PROMPT_CORRECTIONS.md P0 #1) — posts de projet comme Informations
    d'équipe sans projet (migration 0009), voir posts_repo.peut_voir."""
    post = posts_repo.get_post(post_id)
    if post is None or not posts_repo.peut_voir(post["id"], post["projet_id"], g.user["id"]):
        abort(404)
    return post


@bp.route("", methods=["POST"])
@login_required
def creer():
    """Création manuelle d'un post, ou d'un rebond si parent_post_id est
    présent (voir spec : créer un post à partir d'un post existant, en
    gardant la référence — icône flèche, jamais le mot "rebondir" dans l'UI).

    `lien`, `mentions` (personnes taguées, plusieurs ids) et `fichier`
    (pièce jointe) sont optionnels — champs du composeur "Nouveau post",
    panneau Requête (ajoutés 2026-09-18, voir spec)."""
    projet_id = request.form.get("projet_id", type=int)
    type_code = request.form.get("type_code", "envoi")
    contenu = request.form.get("contenu", "").strip()
    objet = request.form.get("objet", "").strip()
    # Longueurs (lot 8), objet et description séparément (chacun sa limite
    # dans le formulaire), avant de les réunir.
    erreur_longueur = v.premiere_erreur(
        v.trop_long(objet, v.MAX_OBJET_REQUETE, "Objet de la requête"),
        v.trop_long(contenu, v.MAX_CONTENU_POST, "Texte du post"),
        v.trop_long(request.form.get("lien", "").strip(), v.MAX_LIEN, "Lien"),
    )
    if objet:
        # Composeur Requête : "Objet" + "Description" (voir maquette) —
        # pas de colonne dédiée, on les combine dans post.contenu.
        contenu = f"{objet}\n\n{contenu}" if contenu else objet
    parent_post_id = request.form.get("parent_post_id", type=int)
    lien = request.form.get("lien", "").strip() or None
    # Schéma de lien restreint (PROMPT_CORRECTIONS.md P0 #4) : un lien
    # "javascript:..." s'exécuterait au clic pour quiconque ouvre le post
    # (post_card.html) — voir is_lien_valide(). Un lien invalide est
    # retiré plutôt que de rejeter tout le post (champ optionnel), mais
    # l'utilisateur en est maintenant prévenu (audit n°2 : il disparaissait
    # sans explication).
    lien_ignore = False
    if lien and not is_lien_valide(lien):
        lien = None
        lien_ignore = True
    mentionne_ids = v.ids_entiers(request.form.getlist("mentions"))
    # Information d'équipe (migration 0009, retour Fadhel, 2026-09-29) : le
    # projet est optionnel ; sans projet, au moins une équipe destinataire.
    equipe_codes = [c for c in dict.fromkeys(request.form.getlist("equipes")) if c in EQUIPES_VALIDES]

    if type_code not in TYPES_VALIDES or not contenu or (not projet_id and type_code != "information"):
        champ = ("objet" if type_code == "requete" else "contenu") if not contenu else None
        return _refus("Le texte du post est obligatoire." if not contenu else "Message invalide.", 422, champ)
    # Longueurs (calculées plus haut) : avant tout enregistrement de fichier.
    if erreur_longueur:
        champ = ("objet" if "Objet" in erreur_longueur else "lien" if erreur_longueur.startswith("Lien")
                 else "contenu")
        return _refus(erreur_longueur, 422, champ)
    if g.user["role"] == "client" and (type_code not in TYPES_CLIENT or not projet_id):
        return _refus("Vous pouvez envoyer des Requêtes et des Informations sur les projets de votre équipe.", 403)
    if projet_id:
        equipe_codes = []  # un post de projet suit la visibilité du projet
    elif not equipe_codes and not parent_post_id:
        return _refus("Choisissez un projet ou au moins une équipe destinataire.", 422, "equipes")
    # Information sans projet (décision Fadhel, lot 7) : seuls l'Admin et le
    # RH s'adressent à n'importe quelle équipe ; les autres, à la leur.
    if (not projet_id and not parent_post_id and g.user["role"] not in ("admin", "rh")
            and set(equipe_codes) != {g.user.get("equipe_code")}):
        return _refus("Une Information sans projet ne peut viser que votre équipe.", 422, "equipes")

    # Contrôle d'accès (IDOR, PROMPT_CORRECTIONS.md P0 #1) : on ne peut
    # publier que sur un projet qu'on voit déjà.
    if projet_id and not projets_repo.user_can_view(projet_id, g.user["id"]):
        abort(404)
    # Projet terminé ou abandonné : plus aucune publication, pour personne
    # — chef et co-chefs compris (décision Fadhel, lot 7).
    if projet_id:
        projet = projets_repo.get_projet(projet_id)
        if projet and projet["etat"] in PROJET_CLOS:
            return _refus(MESSAGE_PROJET_CLOS, 409)

    # Un rebond doit obligatoirement pointer vers un post du MÊME projet —
    # sinon on pourrait relier deux projets sans lien de visibilité entre
    # eux (et laisser deviner l'existence d'un post d'un autre projet). Un
    # post sans projet ne peut répondre qu'à un post sans projet qu'on voit.
    if parent_post_id:
        parent = posts_repo.get_post(parent_post_id)
        if (parent is None or parent["projet_id"] != projet_id
                or not posts_repo.peut_voir(parent["id"], parent["projet_id"], g.user["id"])):
            abort(404)
        # "Reposter" (retour Fadhel, 2026-09-29, P2) : bloqué sur un
        # projet terminé ou abandonné.
        refus = _refus_si_clos(parent)
        if refus:
            return refus
        # Réponse à une Information d'équipe (sans projet) : elle va aux
        # MÊMES équipes que le post d'origine — sinon le bloc "En réponse
        # à" montrerait ce post à d'autres équipes (relecture 2026-09-29).
        if parent["projet_id"] is None:
            equipe_codes = posts_repo.equipes_du_post(parent["id"])

    # Idem pour les mentions : on ne peut taguer que des personnes qui
    # voient déjà ce projet (pas de fuite d'existence d'un utilisateur vers
    # un projet auquel il n'a pas accès). Sans projet : toute personne
    # active (la tagger la rend destinataire).
    if projet_id:
        mentionne_ids = [uid for uid in mentionne_ids if projets_repo.user_can_view(projet_id, uid)]
    else:
        # Information sans projet : la mention rend destinataire — jamais un
        # Client, et (sauf Admin/RH) seulement un membre des équipes visées
        # (audit sécurité I3 : l'Information sortait de l'équipe).
        cibles = {
            u["id"] for u in utilisateurs_repo.list_actifs()
            if u.get("role") != "client"
            and (g.user["role"] in ("admin", "rh") or u.get("equipe_code") in equipe_codes)
        }
        mentionne_ids = [uid for uid in mentionne_ids if uid in cibles]
    # Une personne taguée dans une réponse doit aussi voir le post d'origine
    # (repris dans le bloc "En réponse à").
    if parent_post_id:
        mentionne_ids = [uid for uid in mentionne_ids
                         if posts_repo.peut_voir(parent["id"], parent["projet_id"], uid)]

    # Pièce jointe : sauvegardée sur disque AVANT la création du post, pour
    # pouvoir passer (nom_fichier, chemin) à create_post() et insérer les
    # deux dans LA MÊME transaction (audit sécurité/qualité externe,
    # 2026-09-28, suivi P0-3 round 2 — Luna) : avant ce correctif,
    # create_post() committait seul puis l'insertion de la pièce jointe
    # suivait dans une seconde transaction — un échec de cette dernière
    # laissait le post en base SANS sa pièce jointe (le fichier orphelin,
    # lui, était déjà nettoyé depuis P0-3 round 1). Le chemin de stockage
    # ne peut donc plus être nommé d'après post_id (pas encore connu à ce
    # stade) — projet_id, déjà connu, sert de regroupement à la place ;
    # le nom de fichier stocké reste un UUID (save_upload()), donc sans
    # impact sur l'unicité.
    fichier = request.files.get("fichier")
    piece_jointe = None
    chemin = None
    if fichier and fichier.filename:
        nom_fichier, chemin = save_upload(fichier, f"posts/projet-{projet_id}" if projet_id else "posts/information")
        piece_jointe = (nom_fichier, chemin)

    try:
        post_id = posts_repo.create_post(
            projet_id=projet_id,
            auteur_id=g.user["id"],
            type_code=type_code,
            contenu=contenu,
            parent_post_id=parent_post_id,
            lien=lien,
            mentionne_ids=mentionne_ids,
            piece_jointe=piece_jointe,
            equipe_codes=equipe_codes,
        )
    except Exception:
        if chemin:
            delete_upload(chemin)
        raise

    if mentionne_ids:
        auteur = f"{g.user['prenom']} {g.user['nom']}"
        notifications_repo.creer_pour_plusieurs(
            mentionne_ids, "projet",
            f"{auteur} vous a mentionné dans un post{_extrait(contenu)}.",
            post_id=post_id, exclure_id=g.user["id"],
        )

    if lien_ignore:
        flash(
            "Post publié, sans le lien\u00a0: seuls les liens http(s)://, file:, smb: "
            "ou les chemins réseau \\\\serveur\\partage sont acceptés.", "error",
        )
    else:
        flash({"information": "Information publiée.", "requete": "Requête publiée."}.get(type_code, "Post publié."),
              "success")
    if partiel.est_partiel():
        return reponse_publication(post_id)
    return _safe_redirect()


@bp.route("/<int:post_id>/reagir", methods=["POST"])
@login_required
def reagir(post_id: int):
    # Contrôle d'accès (IDOR, PROMPT_CORRECTIONS.md P0 #1) : impossible de
    # réagir à un post qu'on ne voit pas.
    refus = _refus_si_clos(_post_visible_ou_404(post_id))
    if refus:
        return refus
    reaction_code = request.form.get("reaction_code")
    if reaction_code not in REACTIONS_VALIDES:
        abort(400)
    posts_repo.react(post_id, g.user["id"], reaction_code)
    return _reponse_reaction(post_id)


@bp.route("/<int:post_id>/reagir/supprimer", methods=["POST"])
@login_required
def retirer_reaction(post_id: int):
    refus = _refus_si_clos(_post_visible_ou_404(post_id))
    if refus:
        return refus
    posts_repo.remove_reaction(post_id, g.user["id"])
    return _reponse_reaction(post_id)


def _reponse_reaction(post_id: int):
    """Réaction ✓ (lot 13, audit UX M4/M5) : en partiel ou AJAX, l'état réel
    en JSON (compteur, ma réaction, personnes qui ont réagi) — plus de
    rendu de toute la page suivi d'une redirection ; sinon retour à la page."""
    if not (partiel.est_partiel() or request.headers.get("X-Requested-With") == "XMLHttpRequest"):
        return _safe_redirect()
    post = posts_repo.get_post_carte(post_id, g.user["id"]) or {}
    reponse = jsonify({
        "nb": post.get("nb_reactions", 0),
        "ma_reaction": bool(post.get("ma_reaction")),
        "reacteurs": ", ".join(f"{r['prenom']} {r['nom']}" for r in post.get("reacteurs") or []),
    })
    reponse.headers["Cache-Control"] = "no-store"
    return reponse


@bp.route("/<int:post_id>/commenter", methods=["POST"])
@login_required
def commenter(post_id: int):
    """Commentaire, avec réponse en ligne/tag/pièce jointe (Lot 5, retour
    Fadhel, 2026-09-28 : "façon réseau social") — un seul formulaire
    multipart (texte + pièce jointe optionnelle en un seul envoi, pas deux
    étapes comme pour un post), utilisé aussi bien pour "écrire un
    commentaire" que pour "répondre à un commentaire" (voir
    post-comments.js/post_card.html)."""
    post = _post_visible_ou_404(post_id)
    refus = _refus_si_clos(post)
    if refus:
        return refus
    contenu = request.form.get("contenu", "").strip()
    if not contenu:
        return _refus("Le commentaire ne peut pas être vide.", 422, "contenu")
    if erreur := v.trop_long(contenu, v.MAX_COMMENTAIRE, "Commentaire"):
        return _refus(erreur, 422, "contenu")

    # Ancien champ "@ Taguer" séparé (avant le 2026-09-29) — encore accepté.
    mentionne_user_id = request.form.get("mentionne_user_id", type=int)
    if mentionne_user_id and not posts_repo.peut_voir(post["id"], post["projet_id"], mentionne_user_id):
        mentionne_user_id = None
    # Tags "@Prénom Nom" écrits dans le texte (retour Fadhel, 2026-09-29).
    mention_ids = _tags_du_texte(post, contenu)

    # Réponse en ligne (IDOR, PROMPT_CORRECTIONS.md P0 #1) : le commentaire
    # visé DOIT appartenir à CE post (pas un id deviné d'un autre post/
    # projet), et être lui-même de premier niveau — un seul niveau de
    # profondeur, imposé ici plutôt qu'en base (voir schema.sql).
    parent_commentaire_id = request.form.get("parent_commentaire_id", type=int)
    parent_commentaire = None
    if parent_commentaire_id:
        parent_commentaire = posts_repo.get_commentaire(parent_commentaire_id)
        if (parent_commentaire is None
                or parent_commentaire["post_id"] != post_id
                or parent_commentaire["parent_commentaire_id"] is not None):
            parent_commentaire_id = None
            parent_commentaire = None

    # Même principe que dans creer() ci-dessus (suivi P0-3 round 2) : le
    # fichier est sauvegardé AVANT l'insertion du commentaire, pour que
    # commentaire + pièce jointe soient insérés dans LA MÊME transaction
    # (add_comment(..., piece_jointe=...)) — un échec de l'insertion de la
    # pièce jointe annule alors aussi le commentaire, plutôt que de
    # laisser un commentaire "réussi" en apparence mais sans le fichier
    # que l'utilisateur voulait joindre. commentaire_id n'étant pas encore
    # connu à ce stade, le chemin de stockage ne descend plus qu'au niveau
    # du post (déjà connu), pas du commentaire.
    fichier = request.files.get("fichier")
    piece_jointe = None
    chemin = None
    if fichier and fichier.filename:
        nom_fichier, chemin = save_upload(fichier, f"posts/{post_id}/commentaires")
        piece_jointe = (nom_fichier, chemin)

    try:
        commentaire_id = posts_repo.add_comment(
            post_id, g.user["id"], contenu, mentionne_user_id, parent_commentaire_id,
            piece_jointe=piece_jointe, mention_ids=mention_ids,
        )
    except Exception:
        if chemin:
            delete_upload(chemin)
        raise

    a_notifier = set(mention_ids)
    if mentionne_user_id:
        a_notifier.add(mentionne_user_id)
    _notifier_tags(sorted(a_notifier), post_id, contenu)
    _notifier_auteur(post, parent_commentaire, deja=a_notifier)
    if partiel.est_partiel():
        return _reponse_commentaires(post_id, nouveau_commentaire_id=commentaire_id)
    return _safe_redirect()


def _notifier_auteur(post: dict, parent_commentaire: dict | None, deja: set) -> None:
    """Lot 13 (audit rôles M7) : une réponse prévient l'auteur du
    commentaire auquel elle répond ; un commentaire prévient l'auteur du
    post. Jamais soi-même, jamais deux fois (déjà tagué), seulement s'il
    voit encore le post. Jamais bloquant."""
    if parent_commentaire is not None:
        destinataire = parent_commentaire.get("auteur_id")
        message = f"{g.user['prenom']} {g.user['nom']} a répondu à votre commentaire."
    else:
        destinataire = post.get("auteur_id")
        message = f"{g.user['prenom']} {g.user['nom']} a commenté votre post."
    if not destinataire or destinataire == g.user["id"] or destinataire in deja:
        return
    try:
        if posts_repo.peut_voir(post["id"], post.get("projet_id"), destinataire):
            notifications_repo.creer(destinataire, "projet", message, post_id=post["id"])
    except Exception:
        current_app.logger.exception("Notification de l'auteur impossible (post %s)", post["id"])


def _tags_du_texte(post: dict, contenu: str) -> list[int]:
    """Personnes taguées "@Prénom Nom" dans `contenu`, parmi celles qui
    voient le post (on ne tague pas quelqu'un qui ne pourrait pas le lire),
    sans soi-même."""
    candidats = [u for u in utilisateurs_repo.list_actifs() if u["id"] != g.user["id"]]
    return [
        uid for uid in posts_repo.personnes_taguees(contenu, candidats)
        if posts_repo.peut_voir(post["id"], post["projet_id"], uid)
    ]


def _extrait(texte: str | None, longueur: int = 80) -> str:
    """Revue produit P1-8 : la notification cite le début du message
    («\u00a0Oui, 2 bars à l’ELS…\u00a0») ; le code du projet est affiché à côté."""
    texte = " ".join((texte or "").split())
    if not texte:
        return ""
    if len(texte) > longueur:
        texte = texte[:longueur - 1].rstrip() + "…"
    return f"\u00a0: «\u00a0{texte}\u00a0»"


def _notifier_tags(user_ids: list[int], post_id: int, contenu: str | None = None) -> None:
    ids = [uid for uid in user_ids if uid != g.user["id"]]
    if ids:
        notifications_repo.creer_pour_plusieurs(
            ids, "projet",
            f"{g.user['prenom']} {g.user['nom']} vous a mentionné dans un commentaire{_extrait(contenu)}.",
            post_id=post_id, exclure_id=g.user["id"],
        )


@bp.route("/commentaires/<int:commentaire_id>/modifier", methods=["POST"])
@login_required
def modifier_commentaire(commentaire_id: int):
    """Modification d'un commentaire par SON AUTEUR seulement (retour
    Fadhel, 2026-09-29). Les @tags sont recalculés ; seules les personnes
    nouvellement taguées sont notifiées."""
    commentaire = posts_repo.get_commentaire(commentaire_id)
    if commentaire is None or not posts_repo.peut_voir(commentaire["post_id"], commentaire["projet_id"], g.user["id"]):
        abort(404)
    if commentaire["auteur_id"] != g.user["id"]:
        abort(403)
    refus = _refus_si_clos(commentaire)
    if refus:
        return refus
    contenu = request.form.get("contenu", "").strip()
    if not contenu:
        return _refus("Le commentaire ne peut pas être vide.", 422, "contenu")
    if erreur := v.trop_long(contenu, v.MAX_COMMENTAIRE, "Commentaire"):
        return _refus(erreur, 422, "contenu")
    post = {"id": commentaire["post_id"], "projet_id": commentaire["projet_id"]}
    nouveaux = posts_repo.modifier_commentaire(commentaire_id, g.user["id"], contenu, _tags_du_texte(post, contenu))
    if nouveaux is None:
        abort(404)
    _notifier_tags(nouveaux, commentaire["post_id"], contenu)
    if partiel.est_partiel():
        return _reponse_commentaires(commentaire["post_id"], commentaire_modifie_id=commentaire_id,
                                     toasts=[partiel.toast("Commentaire modifié.")])
    return _safe_redirect()


@bp.route("/commentaires/<int:commentaire_id>/supprimer", methods=["POST"])
@login_required
def supprimer_commentaire(commentaire_id: int):
    """Suppression d'un commentaire (et de ses réponses) — réservée aux
    admins (retour Fadhel, 2026-09-29). Les fichiers joints sont effacés du
    disque après la suppression en base."""
    if g.user["role"] != "admin":
        abort(403)
    commentaire = posts_repo.get_commentaire(commentaire_id)
    if commentaire is None:
        abort(404)
    for chemin in posts_repo.supprimer_commentaire(commentaire_id, g.user["id"]):
        delete_upload(chemin)
    flash("Commentaire supprimé.", "success")
    if partiel.est_partiel():
        return _reponse_commentaires(commentaire["post_id"])
    return _safe_redirect()


# Ancienne route « /posts/<id>/reposter » (repost en un clic) supprimée au
# lot 7 : plus proposée dans l'interface depuis le 2026-09-29, elle
# contournait les règles Client / équipe de creer() (le repost copiait le
# type et les équipes du post d'origine). « Reposter » passe par creer()
# avec parent_post_id.

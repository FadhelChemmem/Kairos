"""Actions sur les posts : création manuelle, "rebond" (voir note dans
repositories/posts.py — jamais nommé ainsi dans l'UI), réaction,
commentaire. Chaque action redirige vers la page d'où elle a été
déclenchée (`next`), pour marcher aussi bien depuis l'accueil que depuis
une page projet.
"""
from flask import Blueprint, abort, flash, g, request

from ..auth import login_required
from ..repositories import notifications as notifications_repo
from ..repositories import posts as posts_repo
from ..repositories import projets as projets_repo
from ..repositories import utilisateurs as utilisateurs_repo
from ..storage import delete_upload, save_upload
from ..utils import EQUIPE_CHOICES, is_lien_valide, redirect_vers_next

bp = Blueprint("posts", __name__, url_prefix="/posts")

TYPES_VALIDES = {"envoi", "reponse", "question", "requete", "information"}
EQUIPES_VALIDES = {code for code, _ in EQUIPE_CHOICES}
REACTIONS_VALIDES = {"ok", "pouce"}


def _safe_redirect(default_endpoint="main.accueil"):
    return redirect_vers_next(default_endpoint)


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
    mentionne_ids = [int(v) for v in request.form.getlist("mentions") if v.isdigit()]
    # Information d'équipe (migration 0009, retour Fadhel, 2026-09-29) : le
    # projet est optionnel ; sans projet, au moins une équipe destinataire.
    equipe_codes = [c for c in dict.fromkeys(request.form.getlist("equipes")) if c in EQUIPES_VALIDES]

    if type_code not in TYPES_VALIDES or not contenu or (not projet_id and type_code != "information"):
        flash("Message invalide.", "error")
        return _safe_redirect()
    if not projet_id and not equipe_codes:
        flash("Choisissez un projet ou au moins une équipe destinataire.", "error")
        return _safe_redirect()
    if projet_id:
        equipe_codes = []  # un post de projet suit la visibilité du projet

    # Contrôle d'accès (IDOR, PROMPT_CORRECTIONS.md P0 #1) : on ne peut
    # publier que sur un projet qu'on voit déjà.
    if projet_id and not projets_repo.user_can_view(projet_id, g.user["id"]):
        abort(404)

    # Un rebond doit obligatoirement pointer vers un post du MÊME projet —
    # sinon on pourrait relier deux projets sans lien de visibilité entre
    # eux (et laisser deviner l'existence d'un post d'un autre projet). Un
    # post sans projet ne peut répondre qu'à un post sans projet qu'on voit.
    if parent_post_id:
        parent = posts_repo.get_post(parent_post_id)
        if (parent is None or parent["projet_id"] != projet_id
                or not posts_repo.peut_voir(parent["id"], parent["projet_id"], g.user["id"])):
            abort(404)

    # Idem pour les mentions : on ne peut taguer que des personnes qui
    # voient déjà ce projet (pas de fuite d'existence d'un utilisateur vers
    # un projet auquel il n'a pas accès). Sans projet : toute personne
    # active (la tagger la rend destinataire).
    if projet_id:
        mentionne_ids = [uid for uid in mentionne_ids if projets_repo.user_can_view(projet_id, uid)]
    else:
        actifs = {u["id"] for u in utilisateurs_repo.list_actifs()}
        mentionne_ids = [uid for uid in mentionne_ids if uid in actifs]

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
            f"{auteur} vous a mentionné dans un post.",
            post_id=post_id, exclure_id=g.user["id"],
        )

    if lien_ignore:
        flash(
            "Post publié, sans le lien : seuls les liens http(s)://, file:, smb: "
            "ou les chemins réseau \\\\serveur\\partage sont acceptés.", "error",
        )
    else:
        flash("Post publié.", "success")
    return _safe_redirect()


@bp.route("/<int:post_id>/reagir", methods=["POST"])
@login_required
def reagir(post_id: int):
    # Contrôle d'accès (IDOR, PROMPT_CORRECTIONS.md P0 #1) : impossible de
    # réagir à un post qu'on ne voit pas.
    _post_visible_ou_404(post_id)
    reaction_code = request.form.get("reaction_code")
    if reaction_code not in REACTIONS_VALIDES:
        abort(400)
    posts_repo.react(post_id, g.user["id"], reaction_code)
    return _safe_redirect()


@bp.route("/<int:post_id>/reagir/supprimer", methods=["POST"])
@login_required
def retirer_reaction(post_id: int):
    _post_visible_ou_404(post_id)
    posts_repo.remove_reaction(post_id, g.user["id"])
    return _safe_redirect()


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
    contenu = request.form.get("contenu", "").strip()
    if not contenu:
        flash("Le commentaire ne peut pas être vide.", "error")
        return _safe_redirect()

    mentionne_user_id = request.form.get("mentionne_user_id", type=int)
    if mentionne_user_id and not posts_repo.peut_voir(post["id"], post["projet_id"], mentionne_user_id):
        mentionne_user_id = None

    # Réponse en ligne (IDOR, PROMPT_CORRECTIONS.md P0 #1) : le commentaire
    # visé DOIT appartenir à CE post (pas un id deviné d'un autre post/
    # projet), et être lui-même de premier niveau — un seul niveau de
    # profondeur, imposé ici plutôt qu'en base (voir schema.sql).
    parent_commentaire_id = request.form.get("parent_commentaire_id", type=int)
    if parent_commentaire_id:
        parent_commentaire = posts_repo.get_commentaire(parent_commentaire_id)
        if (parent_commentaire is None
                or parent_commentaire["post_id"] != post_id
                or parent_commentaire["parent_commentaire_id"] is not None):
            parent_commentaire_id = None

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
            piece_jointe=piece_jointe,
        )
    except Exception:
        if chemin:
            delete_upload(chemin)
        raise

    if mentionne_user_id and mentionne_user_id != g.user["id"]:
        auteur = f"{g.user['prenom']} {g.user['nom']}"
        notifications_repo.creer(
            mentionne_user_id, "projet",
            f"{auteur} vous a mentionné dans un commentaire.",
            post_id=post_id,
        )

    return _safe_redirect()


@bp.route("/<int:post_id>/reposter", methods=["POST"])
@login_required
def reposter(post_id: int):
    """"Reposter" (Lot 5, retour Fadhel, 2026-09-28) — un clic, sans
    composeur, voir posts_repo.repost(). Un commentaire court est optionnel
    (façon "citer")."""
    _post_visible_ou_404(post_id)
    contenu = request.form.get("contenu", "").strip() or None
    posts_repo.repost(post_id, g.user["id"], contenu)
    flash("Reposté.", "success")
    return _safe_redirect()

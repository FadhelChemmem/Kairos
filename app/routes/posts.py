"""Actions sur les posts : création manuelle, "rebond" (voir note dans
repositories/posts.py — jamais nommé ainsi dans l'UI), réaction,
commentaire. Chaque action redirige vers la page d'où elle a été
déclenchée (`next`), pour marcher aussi bien depuis l'accueil que depuis
une page projet.
"""
from flask import Blueprint, abort, flash, g, redirect, request, url_for

from ..auth import login_required
from ..repositories import notifications as notifications_repo
from ..repositories import posts as posts_repo
from ..storage import save_upload

bp = Blueprint("posts", __name__, url_prefix="/posts")

TYPES_VALIDES = {"envoi", "reponse", "question", "requete"}
REACTIONS_VALIDES = {"ok", "pouce"}


def _safe_redirect(default_endpoint="main.accueil"):
    next_url = request.form.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect(url_for(default_endpoint))


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
    mentionne_ids = [int(v) for v in request.form.getlist("mentions") if v.isdigit()]

    if not projet_id or type_code not in TYPES_VALIDES or not contenu:
        flash("Message invalide.", "error")
        return _safe_redirect()

    post_id = posts_repo.create_post(
        projet_id=projet_id,
        auteur_id=g.user["id"],
        type_code=type_code,
        contenu=contenu,
        parent_post_id=parent_post_id,
        lien=lien,
        mentionne_ids=mentionne_ids,
    )

    fichier = request.files.get("fichier")
    if fichier and fichier.filename:
        nom_fichier, chemin = save_upload(fichier, f"posts/{post_id}")
        posts_repo.add_piece_jointe(post_id, nom_fichier, chemin, g.user["id"])

    if mentionne_ids:
        auteur = f"{g.user['prenom']} {g.user['nom']}"
        notifications_repo.creer_pour_plusieurs(
            mentionne_ids, "projet",
            f"{auteur} vous a mentionné dans un post.",
            post_id=post_id, exclure_id=g.user["id"],
        )

    flash("Post publié.", "success")
    return _safe_redirect()


@bp.route("/<int:post_id>/reagir", methods=["POST"])
@login_required
def reagir(post_id: int):
    reaction_code = request.form.get("reaction_code")
    if reaction_code not in REACTIONS_VALIDES:
        abort(400)
    posts_repo.react(post_id, g.user["id"], reaction_code)
    return _safe_redirect()


@bp.route("/<int:post_id>/reagir/supprimer", methods=["POST"])
@login_required
def retirer_reaction(post_id: int):
    posts_repo.remove_reaction(post_id, g.user["id"])
    return _safe_redirect()


@bp.route("/<int:post_id>/commenter", methods=["POST"])
@login_required
def commenter(post_id: int):
    contenu = request.form.get("contenu", "").strip()
    if not contenu:
        flash("Le commentaire ne peut pas être vide.", "error")
        return _safe_redirect()

    mentionne_user_id = request.form.get("mentionne_user_id", type=int)
    posts_repo.add_comment(post_id, g.user["id"], contenu, mentionne_user_id)

    if mentionne_user_id and mentionne_user_id != g.user["id"]:
        auteur = f"{g.user['prenom']} {g.user['nom']}"
        notifications_repo.creer(
            mentionne_user_id, "projet",
            f"{auteur} vous a mentionné dans un commentaire.",
            post_id=post_id,
        )

    return _safe_redirect()

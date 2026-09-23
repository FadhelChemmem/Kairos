"""Upload et téléchargement des pièces jointes (tâches et posts)."""
from flask import Blueprint, abort, current_app, flash, g, redirect, request, send_from_directory, url_for

from ..auth import login_required
from ..repositories import posts as posts_repo
from ..repositories import taches as taches_repo
from ..repositories import utilisateurs as utilisateurs_repo
from ..storage import save_upload

bp = Blueprint("fichiers", __name__, url_prefix="/fichiers")


def _safe_redirect(default_endpoint="main.accueil"):
    next_url = request.form.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect(url_for(default_endpoint))


@bp.route("/taches/<int:tache_id>/upload", methods=["POST"])
@login_required
def upload_tache(tache_id: int):
    fichier = request.files.get("fichier")
    if not fichier or not fichier.filename:
        flash("Aucun fichier sélectionné.", "error")
        return _safe_redirect()

    nom_fichier, chemin = save_upload(fichier, f"taches/{tache_id}")
    taches_repo.add_piece_jointe(tache_id, nom_fichier, chemin, g.user["id"])
    flash("Pièce jointe ajoutée.", "success")
    return _safe_redirect()


@bp.route("/taches/<int:piece_id>", methods=["GET"])
@login_required
def download_tache(piece_id: int):
    piece = taches_repo.get_piece_jointe(piece_id)
    if piece is None:
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_DIR"], piece["chemin"],
        as_attachment=True, download_name=piece["nom_fichier"],
    )


@bp.route("/posts/<int:post_id>/upload", methods=["POST"])
@login_required
def upload_post(post_id: int):
    fichier = request.files.get("fichier")
    if not fichier or not fichier.filename:
        flash("Aucun fichier sélectionné.", "error")
        return _safe_redirect()

    nom_fichier, chemin = save_upload(fichier, f"posts/{post_id}")
    posts_repo.add_piece_jointe(post_id, nom_fichier, chemin, g.user["id"])
    flash("Pièce jointe ajoutée.", "success")
    return _safe_redirect()


@bp.route("/posts/<int:piece_id>", methods=["GET"])
@login_required
def download_post(piece_id: int):
    piece = posts_repo.get_piece_jointe(piece_id)
    if piece is None:
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_DIR"], piece["chemin"],
        as_attachment=True, download_name=piece["nom_fichier"],
    )


@bp.route("/avatars/<int:user_id>", methods=["GET"])
@login_required
def avatar(user_id: int):
    """Sert la photo de profil d'un utilisateur (retour Fadhel, 2026-09-20)
    — lue en base à chaque appel (pas de chemin mis en cache côté client
    au-delà du navigateur) pour qu'un changement de photo se voie tout de
    suite. Affichée en ligne (pas de as_attachment=True) puisqu'elle est
    destinée à un <img>, pas à un téléchargement."""
    utilisateur = utilisateurs_repo.get_utilisateur(user_id)
    if utilisateur is None or not utilisateur["avatar_chemin"]:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_DIR"], utilisateur["avatar_chemin"])

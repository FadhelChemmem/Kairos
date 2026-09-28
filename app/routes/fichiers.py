"""Upload et téléchargement des pièces jointes (tâches et posts)."""
from flask import Blueprint, abort, current_app, flash, g, request, send_from_directory

from ..auth import login_required
from ..repositories import posts as posts_repo
from ..repositories import projets as projets_repo
from ..repositories import taches as taches_repo
from ..repositories import utilisateurs as utilisateurs_repo
from ..storage import delete_upload, is_image_filename, save_upload
from ..utils import redirect_vers_next

bp = Blueprint("fichiers", __name__, url_prefix="/fichiers")


def _safe_redirect(default_endpoint="main.accueil"):
    return redirect_vers_next(default_endpoint)


@bp.route("/taches/<int:tache_id>/upload", methods=["POST"])
@login_required
def upload_tache(tache_id: int):
    # Contrôle d'accès (IDOR, PROMPT_CORRECTIONS.md P0 #1) : on résout la
    # tâche -> son projet AVANT d'écrire quoi que ce soit sur le disque —
    # avant ce correctif, save_upload() était appelé sur un tache_id
    # deviné/inexistant sans aucune vérification, créant des fichiers
    # orphelins et laissant n'importe quel utilisateur connecté déposer une
    # pièce jointe sur la tâche de n'importe quel autre projet.
    tache = taches_repo.get_tache(tache_id)
    if tache is None or not projets_repo.user_can_view(tache["projet_id"], g.user["id"]):
        abort(404)

    fichier = request.files.get("fichier")
    if not fichier or not fichier.filename:
        flash("Aucun fichier sélectionné.", "error")
        return _safe_redirect()

    nom_fichier, chemin = save_upload(fichier, f"taches/{tache_id}")
    # Fichier orphelin sur disque si l'INSERT échoue juste après (audit
    # sécurité/qualité externe, 2026-09-28, item P0-3).
    try:
        taches_repo.add_piece_jointe(tache_id, nom_fichier, chemin, g.user["id"])
    except Exception:
        delete_upload(chemin)
        raise
    flash("Pièce jointe ajoutée.", "success")
    return _safe_redirect()


@bp.route("/taches/<int:piece_id>", methods=["GET"])
@login_required
def download_tache(piece_id: int):
    piece = taches_repo.get_piece_jointe(piece_id)
    if piece is None or not projets_repo.user_can_view(piece["projet_id"], g.user["id"]):
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_DIR"], piece["chemin"],
        as_attachment=True, download_name=piece["nom_fichier"],
    )


@bp.route("/posts/<int:post_id>/upload", methods=["POST"])
@login_required
def upload_post(post_id: int):
    post = posts_repo.get_post(post_id)
    if post is None or not projets_repo.user_can_view(post["projet_id"], g.user["id"]):
        abort(404)

    fichier = request.files.get("fichier")
    if not fichier or not fichier.filename:
        flash("Aucun fichier sélectionné.", "error")
        return _safe_redirect()

    nom_fichier, chemin = save_upload(fichier, f"posts/{post_id}")
    try:
        posts_repo.add_piece_jointe(post_id, nom_fichier, chemin, g.user["id"])
    except Exception:
        delete_upload(chemin)
        raise
    flash("Pièce jointe ajoutée.", "success")
    return _safe_redirect()


@bp.route("/posts/<int:piece_id>", methods=["GET"])
@login_required
def download_post(piece_id: int):
    piece = posts_repo.get_piece_jointe(piece_id)
    if piece is None or not projets_repo.user_can_view(piece["projet_id"], g.user["id"]):
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_DIR"], piece["chemin"],
        as_attachment=True, download_name=piece["nom_fichier"],
    )


@bp.route("/posts/commentaires/<int:commentaire_id>/upload", methods=["POST"])
@login_required
def upload_commentaire(commentaire_id: int):
    """Séparée de posts.commenter() (qui accepte déjà une pièce jointe à
    la création) : utilisée seulement si post-comments.js retente l'envoi
    du fichier après coup (jamais appelée dans le flux normal, gardée pour
    la même raison que upload_tache/upload_post — cohérence de l'API)."""
    commentaire = posts_repo.get_commentaire(commentaire_id)
    if commentaire is None or not projets_repo.user_can_view(commentaire["projet_id"], g.user["id"]):
        abort(404)
    fichier = request.files.get("fichier")
    if not fichier or not fichier.filename:
        flash("Aucun fichier sélectionné.", "error")
        return _safe_redirect()
    nom_fichier, chemin = save_upload(fichier, f"posts/commentaires/{commentaire_id}")
    try:
        posts_repo.add_piece_jointe_commentaire(commentaire_id, nom_fichier, chemin, g.user["id"])
    except Exception:
        delete_upload(chemin)
        raise
    flash("Pièce jointe ajoutée.", "success")
    return _safe_redirect()


@bp.route("/posts/commentaires/<int:piece_id>", methods=["GET"])
@login_required
def commentaire_piece_jointe(piece_id: int):
    """Sert la pièce jointe d'un commentaire (Lot 5, retour Fadhel,
    2026-09-28 : "aperçu image") — EN LIGNE (pas as_attachment) quand
    c'est une image, pour l'aperçu direct dans le fil ; en téléchargement
    sinon, comme les autres pièces jointes de l'appli."""
    piece = posts_repo.get_piece_jointe_commentaire(piece_id)
    if piece is None or not projets_repo.user_can_view(piece["projet_id"], g.user["id"]):
        abort(404)
    if is_image_filename(piece["nom_fichier"]):
        return send_from_directory(current_app.config["UPLOAD_DIR"], piece["chemin"])
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

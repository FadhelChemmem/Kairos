"""Upload et téléchargement des pièces jointes (tâches et posts)."""
from flask import Blueprint, abort, current_app, flash, g, request, send_from_directory

from .. import partiel
from ..auth import login_required
from ..repositories import posts as posts_repo
from ..repositories import projets as projets_repo
from ..repositories import taches as taches_repo
from ..repositories import utilisateurs as utilisateurs_repo
from ..storage import is_image_filename
from ..utils import avatar_version, redirect_vers_next

bp = Blueprint("fichiers", __name__, url_prefix="/fichiers")

CACHE_AVATAR = "private, max-age=3600"


def _safe_redirect(default_endpoint="main.accueil"):
    return redirect_vers_next(default_endpoint)


@bp.route("/taches/<int:tache_id>/upload", methods=["POST"])
@login_required
def upload_tache(tache_id: int):
    """Lot 20 (décision du gérant, déjà annoncée au lot 17) : plus de pièce
    jointe sur les tâches — les fichiers se joignent aux posts du projet.
    La route reste pour répondre clairement à un ancien formulaire ou à une
    requête forgée ; les pièces déjà déposées restent téléchargeables."""
    tache = taches_repo.get_tache(tache_id)
    if tache is None or not projets_repo.user_can_view(tache["projet_id"], g.user["id"]):
        abort(404)
    return _refus("Les pièces jointes ne s’ajoutent plus aux tâches\u00a0: joignez le fichier à un post du "
                  "projet («\u00a0+ Nouveau post\u00a0»).", 410)


def _refus(message: str, statut: int):
    """Refus d'un envoi de fichier : JSON en partiel (lot 13), message et
    retour à la page sinon."""
    if partiel.est_partiel():
        return partiel.refuser(message, statut)
    flash(message, "error")
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


@bp.route("/posts/<int:piece_id>", methods=["GET"])
@login_required
def download_post(piece_id: int):
    piece = posts_repo.get_piece_jointe(piece_id)
    if piece is None or not posts_repo.peut_voir(piece["post_id"], piece["projet_id"], g.user["id"]):
        abort(404)
    # Image : servie en ligne, affichée dans le fil et la visionneuse
    # (J.docx : « montrer les photos, on utilise beaucoup de captures
    # d'écran ») ; tout autre fichier en téléchargement.
    if is_image_filename(piece["nom_fichier"]):
        return send_from_directory(current_app.config["UPLOAD_DIR"], piece["chemin"])
    return send_from_directory(
        current_app.config["UPLOAD_DIR"], piece["chemin"],
        as_attachment=True, download_name=piece["nom_fichier"],
    )


# Plus de route d'ajout de pièce jointe APRÈS COUP sur un post ou un
# commentaire (audit du 2026-09-29) : le trombone sous les posts a été
# retiré (remplacé par « Reposter »), et un commentaire reçoit son fichier
# à la création (posts.commenter). Ces deux routes n'étaient plus appelées
# et permettaient d'ajouter un fichier au post ou au commentaire de
# quelqu'un d'autre.


@bp.route("/posts/commentaires/<int:piece_id>", methods=["GET"])
@login_required
def commentaire_piece_jointe(piece_id: int):
    """Sert la pièce jointe d'un commentaire (Lot 5, retour Fadhel,
    2026-09-28 : "aperçu image") — EN LIGNE (pas as_attachment) quand
    c'est une image, pour l'aperçu direct dans le fil ; en téléchargement
    sinon, comme les autres pièces jointes de l'appli."""
    piece = posts_repo.get_piece_jointe_commentaire(piece_id)
    if piece is None or not posts_repo.peut_voir(piece["post_id"], piece["projet_id"], g.user["id"]):
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
    # Lot 11 (intégration) : toute réponse authentifiée est en no-store
    # (app/__init__.py), sauf l'avatar demandé avec l'empreinte de la photo
    # COURANTE (?v=, voir utils.avatar_url) — cache privé d'une heure :
    # jamais dans un proxy partagé, et une nouvelle photo change l'URL.
    # Sans empreinte ou avec une ancienne : no-store, comme avant. Les
    # pièces jointes restent en no-store (documents de projet).
    if request.args.get("v") == avatar_version(utilisateur["avatar_chemin"]):
        g.cache_prive = CACHE_AVATAR
    return send_from_directory(current_app.config["UPLOAD_DIR"], utilisateur["avatar_chemin"])

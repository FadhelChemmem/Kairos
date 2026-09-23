"""Notifications : une seule liste, une cloche dans la barre du haut (voir
base.html) — pas d'emailing à cette étape (voir spec). Ouvrir une
notification la marque lue et redirige vers le projet concerné, quand il y
en a un."""
from flask import Blueprint, abort, redirect, g, render_template, url_for

from ..auth import login_required
from ..repositories import notifications as notifications_repo

bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@bp.route("")
@login_required
def liste():
    notifs = notifications_repo.list_notifications(g.user["id"])
    return render_template("notifications_liste.html", notifications=notifs)


@bp.route("/<int:notification_id>/ouvrir")
@login_required
def ouvrir(notification_id: int):
    notif = notifications_repo.get_notification(notification_id, g.user["id"])
    if notif is None:
        abort(404)

    notifications_repo.marquer_lu(notification_id, g.user["id"])

    projet_id = notif["post_projet_id"] or notif["tache_projet_id"]
    if projet_id:
        return redirect(url_for("projets.detail", projet_id=projet_id))
    return redirect(url_for("notifications.liste"))


@bp.route("/marquer-toutes-lues", methods=["POST"])
@login_required
def marquer_toutes_lues():
    notifications_repo.marquer_toutes_lues(g.user["id"])
    return redirect(url_for("notifications.liste"))

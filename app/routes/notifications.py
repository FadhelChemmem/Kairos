"""Notifications : une seule liste, une cloche dans la barre du haut (voir
base.html) — pas d'emailing à cette étape (voir spec). Ouvrir une
notification la marque lue et redirige vers le projet concerné, quand il y
en a un."""
import datetime
import re

from flask import Blueprint, abort, redirect, g, render_template, url_for

from ..auth import login_required
from ..repositories import notifications as notifications_repo

bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@bp.route("")
@login_required
def liste():
    notifs = notifications_repo.list_notifications(g.user["id"])
    return render_template("notifications_liste.html", notifications=notifs)


@bp.route("/<int:notification_id>/ouvrir", methods=["POST"])
@login_required
def ouvrir(notification_id: int):
    """POST (audit n°2) : en GET, une simple image sur une page tierce
    pouvait marquer les notifications de la victime comme lues."""
    notif = notifications_repo.get_notification(notification_id, g.user["id"])
    if notif is None:
        abort(404)

    notifications_repo.marquer_lu(notification_id, g.user["id"])

    # Rappel ou correction du Daily log (lot 10) : directement le jour cité.
    jour = _jour_daily_log(notif.get("message"))
    if jour is not None and g.user["role"] in ("admin", "chef_de_projet", "intervenant"):
        return redirect(url_for("dailylog.formulaire", date=jour.isoformat()))

    projet_id = notif["post_projet_id"] or notif["tache_projet_id"]
    if projet_id:
        return redirect(url_for("projets.detail", projet_id=projet_id))
    # Information d'équipe sans projet (migration 0009) : le post est dans
    # le fil de l'accueil.
    if notif.get("post_id"):
        return redirect(url_for("main.accueil") + f"#post-{notif['post_id']}")
    return redirect(url_for("notifications.liste"))


@bp.route("/marquer-toutes-lues", methods=["POST"])
@login_required
def marquer_toutes_lues():
    notifications_repo.marquer_toutes_lues(g.user["id"])
    return redirect(url_for("notifications.liste"))


_RE_JOUR_DAILY_LOG = re.compile(r"^(?:Rappel DailyLog|Daily log du)\b.*?([0-9]{2})/([0-9]{2})/([0-9]{4})")


def _jour_daily_log(message: str | None):
    """Date citée par une notification de rappel ou de correction du Daily
    log (« … votre journée du 03/10/2026. »), None sinon."""
    m = _RE_JOUR_DAILY_LOG.match(message or "")
    if not m:
        return None
    try:
        return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None

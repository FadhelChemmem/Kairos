"""Vue "Toutes les deadlines" — calendrier/Gantt à défilement horizontal,
fidèle à Deadlines.dc.html (voir app/utils.py:build_gantt pour le calcul)."""
import datetime

from flask import Blueprint, g, render_template

from ..auth import login_required
from ..repositories import taches
from ..utils import build_gantt

bp = Blueprint("deadlines", __name__, url_prefix="/deadlines")


@bp.route("")
@login_required
def liste():
    mes_taches = taches.list_deadlines(g.user["id"], limit=200)
    gantt = build_gantt(mes_taches, datetime.date.today(), window_days=21)
    return render_template("deadlines.html", gantt=gantt, nb_taches=len(mes_taches))

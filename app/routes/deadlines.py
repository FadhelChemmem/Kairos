"""Vue "Toutes les deadlines" — calendrier/Gantt à défilement horizontal,
fidèle à Deadlines.dc.html (voir app/utils.py:build_gantt pour le calcul)."""
from flask import Blueprint, g, render_template

from ..auth import role_required
from ..repositories import dailylog as dl
from ..repositories import taches
from ..utils import build_gantt, jours_utiles_gantt

bp = Blueprint("deadlines", __name__, url_prefix="/deadlines")


@bp.route("")
# Ni le RH (aucun accès aux projets) ni un Client (pas de tâches) — lot 7.
@role_required("admin", "chef_de_projet", "intervenant")
def liste():
    mes_taches = taches.list_deadlines(g.user["id"], limit=200)
    # « Aujourd'hui » au fuseau de la personne (lot 11 : Guyane / Tunis),
    # comme le Daily log — et non la date du serveur.
    aujourdhui = dl.aujourdhui_pour(g.user)
    gantt = build_gantt(mes_taches, aujourdhui, window_days=jours_utiles_gantt(mes_taches, aujourdhui))
    return render_template("deadlines.html", gantt=gantt, nb_taches=len(mes_taches))

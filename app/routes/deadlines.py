"""Vue "Toutes les deadlines" — calendrier/Gantt à défilement horizontal,
fidèle à Deadlines.dc.html (voir app/utils.py:build_gantt pour le calcul).

Lot 12 : chaque barre ouvre la fenêtre de sa tâche sur la fiche projet
(?tache=<id>) ; l'Admin bascule entre « Mes projets » (comme avant) et
« Tous les projets » (?vue=tous : tâches en cours de tous les projets
ouverts, avec et sans échéance, filtrables par chef de projet et équipe).
Les autres rôles sont inchangés (le paramètre est ignoré)."""
from flask import Blueprint, g, render_template, request

from ..auth import role_required
from ..repositories import dailylog as dl
from ..repositories import projets, taches
from ..utils import EQUIPE_CHOICES, build_gantt, jours_utiles_gantt
from ..validation import ids_entiers

bp = Blueprint("deadlines", __name__, url_prefix="/deadlines")


@bp.route("")
# Ni le RH (aucun accès aux projets) ni un Client (pas de tâches) — lot 7.
@role_required("admin", "chef_de_projet", "intervenant")
def liste():
    admin = g.user["role"] == "admin"
    tous = admin and request.args.get("vue") == "tous"
    filtres = {"chef": None, "equipe": None}
    sans_echeance, chefs = [], []
    if tous:
        filtres["chef"] = next(iter(ids_entiers([request.args.get("chef") or ""])), None)
        equipe = request.args.get("equipe") or None
        filtres["equipe"] = equipe if equipe in {code for code, _ in EQUIPE_CHOICES} else None
        mes_taches = taches.list_deadlines_tous(filtres["chef"], filtres["equipe"], limit=500)
        sans_echeance = taches.list_deadlines_tous(filtres["chef"], filtres["equipe"], sans_echeance=True, limit=300)
        chefs = projets.list_chefs_de_projet(g.user["id"])
    else:
        mes_taches = taches.list_deadlines(g.user["id"], limit=200)
    # « Aujourd'hui » au fuseau de la personne (lot 11 : Guyane / Tunis),
    # comme le Daily log — et non la date du serveur ; date simulée de
    # l'Admin en mode test (lot 12, app/horloge.py).
    aujourdhui = dl.aujourdhui_pour(g.user)
    gantt = build_gantt(mes_taches, aujourdhui, window_days=jours_utiles_gantt(mes_taches, aujourdhui))
    return render_template(
        "deadlines.html", gantt=gantt, nb_taches=len(mes_taches), vue_admin=admin, tous=tous,
        filtres=filtres, chefs=chefs, sans_echeance=sans_echeance,
    )

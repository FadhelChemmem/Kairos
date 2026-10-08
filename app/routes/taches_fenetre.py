"""Fenêtre d'une tâche chargée à la demande (lot 11, audit front I2).

La fiche projet ne pré-rend plus une <dialog> complète par tâche (315 Ko
sur 474 Ko pour une fiche de 76 tâches) : une seule fenêtre, remplie à
l'ouverture par ce fragment HTML, rendu par le même gabarit partiel
(partials/tache_fenetre.html). Mêmes droits que la fiche projet
(projets.detail) : projet introuvable ou invisible -> 404, tâche d'un
autre projet -> 404.
"""
from flask import Blueprint, abort, g, make_response, render_template, url_for

from ..auth import login_required
from ..repositories import projets, taches

bp = Blueprint("taches_fenetre", __name__, url_prefix="/projets")

# Tâches closes : repliées dans le tableau de la fiche, et jamais
# « Rejoindre cette tâche » (audit front I9). Même liste que les compteurs
# de tâches ouvertes de repositories/projets.py.
ETATS_TACHE_CLOSES = ("termine", "verifie", "arret", "abandonne")


@bp.record_once
def _exposer_aux_gabarits(state):
    # Lu par projet_detail.html (repli des tâches closes) et par le fragment.
    state.app.jinja_env.globals["etats_taches_closes"] = ETATS_TACHE_CLOSES


@bp.route("/<int:projet_id>/taches/<int:tache_id>/fenetre")
@login_required
def fenetre(projet_id: int, tache_id: int):
    projet = projets.get_projet(projet_id)
    if projet is None or not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    # La ligne du tableau (intervenants, pièces jointes, heures) : même
    # source que la fiche, pour un contenu identique à l'ancienne fenêtre.
    tache = next((t for t in taches.list_taches_projet(projet_id) if t["id"] == tache_id), None)
    if tache is None:
        abort(404)
    html = render_template(
        "partials/tache_fenetre.html",
        t=tache,
        projet=projet,
        peut_gerer=projets.user_can_manage(projet_id, g.user["id"]),
        projet_clos=projet["etat"] in projets.ETATS_CLOS,
        etats_reserves=taches.ETATS_RESERVES_GESTION,
        next_url=url_for("projets.detail", projet_id=projet_id),
    )
    reponse = make_response(html)
    # Repère pour tache-dialog.js : une session expirée renvoie la page de
    # connexion (redirection suivie par fetch), jamais ce fragment.
    reponse.headers["X-Kairos-Fragment"] = "tache"
    return reponse

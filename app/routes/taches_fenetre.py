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
from ..repositories import projets, taches, utilisateurs

bp = Blueprint("taches_fenetre", __name__, url_prefix="/projets")

# Tâches closes : repliées dans le tableau de la fiche, et jamais
# « Rejoindre cette tâche » (audit front I9 ; refus serveur dans
# taches.add_intervenant).
ETATS_TACHE_CLOSES = taches.ETATS_CLOS


@bp.record_once
def _exposer_aux_gabarits(state):
    # Lu par projet_detail.html (repli des tâches closes) et par le fragment.
    state.app.jinja_env.globals["etats_taches_closes"] = ETATS_TACHE_CLOSES


def contexte_fenetre(projet: dict, tache_id: int, peut_gerer: bool) -> dict | None:
    """Contexte du panneau d'une tâche (partials/tache_fenetre.html) : la
    tâche telle que la ligne du tableau la montre (intervenants, pièces
    jointes, heures) et les personnes à lui affecter. None si la tâche
    n'est pas sur ce projet."""
    liste = taches.list_taches_projet(projet["id"], tache_id=tache_id)
    tache = next((t for t in liste if t["id"] == tache_id), None)
    if tache is None:
        return None
    # Lot 13 (décision 4) : personnes à affecter — actives, ni Client ni RH,
    # qui voient le projet et ne sont pas déjà sur la tâche.
    candidats = []
    if peut_gerer and projet["etat"] not in projets.ETATS_CLOS and tache["etat"] not in ETATS_TACHE_CLOSES:
        voient = projets.ids_utilisateurs_voyant(projet["id"])
        deja = {i["id"] for i in tache["intervenants"]}
        candidats = [u for u in utilisateurs.list_affectables() if u["id"] in voient and u["id"] not in deja]
    return dict(t=tache, candidats=candidats, peut_gerer=peut_gerer,
                projet_clos=projet["etat"] in projets.ETATS_CLOS,
                etats_reserves=taches.ETATS_RESERVES_GESTION)


@bp.route("/<int:projet_id>/taches/<int:tache_id>/fenetre")
@login_required
def fenetre(projet_id: int, tache_id: int):
    projet = projets.get_projet(projet_id)
    if projet is None or not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    contexte = contexte_fenetre(projet, tache_id, projets.user_can_manage(projet_id, g.user["id"]))
    if contexte is None:
        abort(404)
    html = render_template("partials/tache_fenetre.html", projet=projet,
                           next_url=url_for("projets.detail", projet_id=projet_id), **contexte)
    reponse = make_response(html)
    # Repère pour tache-dialog.js : une session expirée renvoie la page de
    # connexion (redirection suivie par fetch), jamais ce fragment.
    reponse.headers["X-Kairos-Fragment"] = "tache"
    return reponse

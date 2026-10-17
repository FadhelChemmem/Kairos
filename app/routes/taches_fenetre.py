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
from .. import horloge
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
    # Lot 17 : bornes de la date de fin proposée à la clôture (création de
    # la tâche → aujourd'hui) et auteur de la dernière clôture.
    from ..repositories import dailylog as dl

    aujourdhui = dl.aujourdhui_pour(g.user)
    cree = tache.get("created_at")
    debut = cree.astimezone(horloge.ZoneInfo(g.user.get("fuseau") or "Africa/Tunis")).date() \
        if hasattr(cree, "astimezone") else aujourdhui
    cloture = taches.derniere_cloture(tache_id) if tache["etat"] in ("termine", "verifie") else None
    return dict(t=tache, candidats=candidats, peut_gerer=peut_gerer, cloture=cloture,
                date_fin_min=min(debut, aujourdhui), date_fin_max=aujourdhui,
                projet_clos=projet["etat"] in projets.ETATS_CLOS,
                etats_reserves=taches.ETATS_RESERVES_GESTION,
                aide_blocage=aide_blocage(projet) if tache["etat"] != "bloque" else "")


def aide_blocage(projet: dict) -> str:
    """Qui sera prévenu d'un blocage signalé par la personne connectée
    (recette du lot 14, n° 12) : le chef titulaire et les co-chefs, jamais
    elle-même (routes/projets.py:_prevenir_gestion)."""
    moi = g.user["id"]
    co_chefs = [uid for uid in projets.ids_co_chefs(projet["id"]) if uid != moi]
    chef = projet.get("chef_projet_id") not in (None, moi)
    if chef and co_chefs:
        return ("Le chef de projet et le co-chef sont prévenus." if len(co_chefs) == 1
                else "Le chef de projet et les co-chefs sont prévenus.")
    if chef:
        return "Le chef de projet est prévenu."
    if co_chefs:
        return "Le co-chef est prévenu." if len(co_chefs) == 1 else "Les co-chefs sont prévenus."
    return "Le motif s’affiche sur la tâche et dans le fil du projet."


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

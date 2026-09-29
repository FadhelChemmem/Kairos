"""Page d'accueil — porte Main.dc.html en template Jinja2 réel."""
import datetime

from flask import Blueprint, g, render_template, request, url_for

from ..auth import login_required
from ..repositories import dailylog as dailylog_repo
from ..repositories import posts, projets, taches, utilisateurs
from ..utils import build_gantt

bp = Blueprint("main", __name__)


@bp.route("/accueil")
@login_required
def accueil():
    user_id = g.user["id"]
    deadlines = taches.list_deadlines(user_id, limit=6)
    # Bannière d'accueil (retour Fadhel, 2026-09-19) : mini-Gantt simplifié
    # (jours + barres, sans les filtres/légende de la page Deadlines) sur une
    # fenêtre courte pour ne jamais déborder de la largeur des 3 colonnes.
    deadlines_gantt = build_gantt(deadlines, datetime.date.today(), window_days=14)
    # Limité à 5 (retour Fadhel, 2026-09-28) : pour ne pas encombrer la colonne.
    mes_taches = taches.list_mes_taches(user_id, limit=5)
    fil = posts.list_feed_mes_projets(user_id, limit=20)
    dailylog_jours_manques = dailylog_repo.jours_manques_recents(user_id)

    # Fenêtre "+ Nouveau post" de l'accueil (audit n°2) : seulement les
    # projets actifs (pas ceux terminés/abandonnés), la liste des personnes
    # à affecter/taguer (elle n'était pas transmise : listes vides), et
    # l'onglet ouvert par défaut adapté — "Tâche" seulement pour qui gère au
    # moins un projet (sinon le formulaire était refusé à l'envoi).
    #
    # Sélecteur de projet (retour Fadhel, 2026-09-29, N2/N6) : seulement MES
    # projets (chef, co-chef, intervenant) en cours ou bloqués, triés par
    # MA dernière action — le premier, présélectionné, est donc celui sur
    # lequel j'ai travaillé le plus récemment (avant : l'échéance la plus
    # proche). La carte "Mes projets" en affiche les 5 premiers.
    projets_recents = projets.list_mes_projets_recents(user_id, limit=500)
    projets_postables = [p for p in projets_recents if p["etat"] in ("en_cours", "bloque")]
    mes_projets_recents = projets_recents[:5]
    # Onglet ouvert par défaut : "Tâche" si je gère le projet présélectionné
    # (post-dialog.js masque ensuite l'onglet selon le projet choisi).
    gere_un_projet = bool(projets_postables) and projets_postables[0]["mon_role"] in ("chef_de_projet", "co_chef")

    return render_template(
        "accueil.html",
        mes_projets=mes_projets_recents,
        projets_postables=projets_postables,
        intent_par_defaut="tache" if gere_un_projet else "requete",
        utilisateurs_actifs=utilisateurs.list_actifs(),
        collaborateurs_recents=utilisateurs.list_collaborateurs_recents(user_id),
        deadlines=deadlines,
        deadlines_gantt=deadlines_gantt,
        mes_taches=mes_taches,
        fil=fil,
        dailylog_jours_manques=dailylog_jours_manques,
    )


@bp.route("/recherche/api")
@login_required
def recherche_api():
    """Petite API JSON interne pour la recherche de la topbar (voir
    base.html) — projets ET personnes (Lot 5, retour Fadhel, 2026-09-28 :
    la recherche de personnes était différée jusqu'ici faute de page de
    profil, voir utilisateurs.profil_personne, qui vient de la combler)."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return {"resultats": []}
    projets_trouves = projets.search(g.user["id"], q, limit=6)
    personnes_trouvees = utilisateurs.search(q, limit=6)
    resultats = [
        {"label": f"{p['code']}_{p['nom']}", "sous_titre": None,
         "url": url_for("projets.detail", projet_id=p["id"])}
        for p in projets_trouves
    ] + [
        {"label": f"{u['prenom']} {u['nom']}", "sous_titre": u["poste"],
         "url": url_for("utilisateurs.profil_personne", user_id=u["id"])}
        for u in personnes_trouvees
    ]
    return {"resultats": resultats}

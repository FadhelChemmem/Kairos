"""Page d'accueil — porte Main.dc.html en template Jinja2 réel."""
import datetime

from flask import Blueprint, g, render_template, request, url_for

from ..auth import login_required
from ..repositories import dailylog as dailylog_repo
from ..repositories import posts, projets, taches
from ..utils import build_gantt

bp = Blueprint("main", __name__)


@bp.route("/accueil")
@login_required
def accueil():
    user_id = g.user["id"]
    mes_projets = projets.list_mes_projets(user_id)
    # Toutes les échéances (pas seulement les 6 affichées) pour trier "Mes
    # projets" par échéance la plus proche (demandé par Fadhel, 2026-09-19) ;
    # la bannière et le widget de la colonne gauche n'en montrent qu'un aperçu.
    deadlines_toutes = taches.list_deadlines(user_id, limit=200)
    prochaine_par_projet = {}
    for d in deadlines_toutes:
        if d["projet_id"] not in prochaine_par_projet:
            prochaine_par_projet[d["projet_id"]] = d["date_echeance"]
    mes_projets = sorted(
        mes_projets,
        key=lambda p: (prochaine_par_projet.get(p["id"]) is None, prochaine_par_projet.get(p["id"])),
    )
    deadlines = deadlines_toutes[:6]
    # Bannière d'accueil (retour Fadhel, 2026-09-19) : mini-Gantt simplifié
    # (jours + barres, sans les filtres/légende de la page Deadlines) sur une
    # fenêtre courte pour ne jamais déborder de la largeur des 3 colonnes.
    deadlines_gantt = build_gantt(deadlines, datetime.date.today(), window_days=14)
    mes_taches = taches.list_mes_taches(user_id, limit=6)
    fil = posts.list_feed_mes_projets(user_id, limit=20)
    dailylog_jours_manques = dailylog_repo.jours_manques_recents(user_id)

    return render_template(
        "accueil.html",
        mes_projets=mes_projets,
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
    base.html) — pour l'instant limitée aux projets (recherche de
    personnes différée : pas de page de profil publique pour les
    utilisateurs autres que soi-même, voir utilisateurs.mon_profil)."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return {"resultats": []}
    trouves = projets.search(g.user["id"], q, limit=8)
    resultats = [
        {"label": f"{p['code']}_{p['nom']}", "url": url_for("projets.detail", projet_id=p["id"])}
        for p in trouves
    ]
    return {"resultats": resultats}

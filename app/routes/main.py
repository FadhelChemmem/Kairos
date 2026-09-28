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
    # Limité à 5 (retour Fadhel, 2026-09-28) : pour ne pas encombrer la colonne.
    mes_taches = taches.list_mes_taches(user_id, limit=5)
    fil = posts.list_feed_mes_projets(user_id, limit=20)
    dailylog_jours_manques = dailylog_repo.jours_manques_recents(user_id)

    # Fenêtre "+ Nouveau post" de l'accueil (audit n°2) : seulement les
    # projets actifs (pas ceux terminés/abandonnés), la liste des personnes
    # à affecter/taguer (elle n'était pas transmise : listes vides), et
    # l'onglet ouvert par défaut adapté — "Tâche" seulement pour qui gère au
    # moins un projet (sinon le formulaire était refusé à l'envoi).
    projets_postables = [p for p in mes_projets if p["etat"] in ("en_cours", "bloque")]
    gere_un_projet = any(p["mon_role"] in ("chef_de_projet", "co_chef") for p in projets_postables)

    # Carte "Mes projets" (retour Fadhel, 2026-09-28) : 5 projets triés par
    # MA dernière action dessus (pas l'activité de tout le monde), projets
    # terminés exclus — distinct de `mes_projets` ci-dessus, qui reste
    # l'ordre par échéance et sert au sélecteur de "+ Nouveau post".
    mes_projets_recents = projets.list_mes_projets_recents(user_id, limit=5)

    return render_template(
        "accueil.html",
        mes_projets=mes_projets_recents,
        projets_postables=projets_postables,
        intent_par_defaut="tache" if gere_un_projet else "requete",
        utilisateurs_actifs=utilisateurs.list_actifs(),
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

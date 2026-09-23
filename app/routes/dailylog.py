"""Saisie DailyLog façon curseur : une journée entière (plusieurs lignes
projet/tâche réparties en % d'une journée type de 8h, voir spec) est
enregistrée en un seul geste explicite. L'essentiel de l'interaction
(sélection/répartition/verrouillage des lignes, glisser du curseur) vit
côté client dans `dailylog.html`, adapté du prototype cliquable
`DailyLog.dc.html` validé avec Fadhel ; cette route ne fait que fournir
l'état initial réel (lignes déjà enregistrées, catalogue de suggestions)
et encaisser la sauvegarde finale.
"""
import datetime

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..auth import login_required
from ..repositories import dailylog

bp = Blueprint("dailylog", __name__, url_prefix="/dailylog")

STANDARD_HOURS = 8


@bp.route("", methods=["GET"])
@login_required
def formulaire():
    date_str = request.args.get("date")
    aujourdhui = datetime.date.today()
    try:
        date = datetime.date.fromisoformat(date_str) if date_str else aujourdhui
    except ValueError:
        date = aujourdhui
    # Pas de saisie pour un jour futur (retour Fadhel, 2026-09-19) — on
    # ramène silencieusement à aujourd'hui plutôt que de laisser
    # remplir/naviguer sur "demain" et au-delà.
    if date > aujourdhui:
        date = aujourdhui

    entrees = dailylog.list_entrees_jour(g.user["id"], date)
    suggestions = dailylog.list_lignes_suggerees(g.user["id"])

    if entrees:
        lignes_initiales = [
            {
                "projet_id": e["projet_id"], "tache_id": e["tache_id"],
                "nom": e["projet_nom"], "tache_titre": e["tache_titre"],
                "pct": round(float(e["heures"]) / STANDARD_HOURS * 100, 2),
            }
            for e in entrees
        ]
    else:
        # Rien d'enregistré ce jour : projets en cours proposés par défaut
        # (lignes "projet seul" du catalogue), répartis à parts égales
        # (voir spec DailyLog).
        defauts = [m for m in suggestions["mine"] if m["tache_id"] is None]
        part = round(100 / len(defauts), 2) if defauts else 0
        lignes_initiales = [
            {"projet_id": p["projet_id"], "tache_id": None, "nom": p["nom"],
             "tache_titre": None, "pct": part}
            for p in defauts
        ]

    est_aujourdhui = date == aujourdhui
    hier = date - datetime.timedelta(days=1)
    demain = date + datetime.timedelta(days=1)
    # Pas de rappel pour un week-end non travaillé (même heuristique que le
    # rappel automatique à la connexion, voir auth._verifier_rappel_dailylog).
    rappel_hier = (
        est_aujourdhui and hier.weekday() < 5
        and not dailylog.list_entrees_jour(g.user["id"], hier)
    )

    mois_ref = date.replace(day=1)
    jours_du_mois = [
        j.isoformat() for j in dailylog.list_jours_remplis_mois(g.user["id"], mois_ref.year, mois_ref.month)
    ]

    return render_template(
        "dailylog.html",
        date=date, aujourdhui=aujourdhui, est_aujourdhui=est_aujourdhui,
        hier=hier, demain=demain, rappel_hier=rappel_hier,
        lignes_initiales=lignes_initiales, suggestions=suggestions,
        jours_remplis=jours_du_mois, standard_hours=STANDARD_HOURS,
    )


@bp.route("/jours-remplis")
@login_required
def api_jours_remplis():
    """Petite API JSON interne (même origine, même session) utilisée par le
    calendrier du DailyLog pour afficher la pastille "rempli" quand on
    change de mois sans recharger toute la page."""
    annee = request.args.get("annee", type=int)
    mois = request.args.get("mois", type=int)
    if not annee or not mois:
        return {"jours": []}
    jours = dailylog.list_jours_remplis_mois(g.user["id"], annee, mois)
    return {"jours": [j.isoformat() for j in jours]}


@bp.route("", methods=["POST"])
@login_required
def enregistrer():
    date_str = request.form.get("date") or datetime.date.today().isoformat()

    projet_ids = request.form.getlist("ligne_projet_id")
    tache_ids = request.form.getlist("ligne_tache_id")
    heures_list = request.form.getlist("ligne_heures")

    lignes = []
    for pid, tid, h in zip(projet_ids, tache_ids, heures_list):
        if not pid:
            continue
        try:
            heures = round(float(h), 2)
        except (TypeError, ValueError):
            continue
        if heures <= 0:
            continue
        lignes.append({
            "projet_id": int(pid),
            "tache_id": int(tid) if tid else None,
            "heures": heures,
        })

    dailylog.remplacer_jour(g.user["id"], date_str, lignes, current_user_id=g.user["id"])
    flash("Daily log enregistré.", "success")
    return redirect(url_for("dailylog.formulaire", date=date_str))

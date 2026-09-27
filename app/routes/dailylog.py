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
from ..repositories import projets as projets_repo
from ..repositories import taches as taches_repo

bp = Blueprint("dailylog", __name__, url_prefix="/dailylog")

STANDARD_HOURS = 8

# Bornes de validation d'une ligne DailyLog (PROMPT_CORRECTIONS.md P1 #10).
MAX_HEURES_PAR_LIGNE = 24


def _parser_date(date_str: str | None) -> datetime.date:
    """Parse une date de formulaire/URL en la ramenant systématiquement à
    aujourd'hui si elle est absente, mal formée, ou dans le futur — utilisé
    aussi bien par le formulaire (GET) que par l'enregistrement (POST).

    PROMPT_CORRECTIONS.md P1 #10 : avant ce correctif, seule la route GET
    faisait ce contrôle — la route POST (enregistrer) prenait `date_str`
    tel quel, sans validation de format ni de date future, alors que rien
    n'empêche de soumettre ce formulaire directement (sans passer par la
    page GET)."""
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
    return date


@bp.route("", methods=["GET"])
@login_required
def formulaire():
    date = _parser_date(request.args.get("date"))
    aujourdhui = datetime.date.today()

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


@bp.route("/recherche-projets")
@login_required
def api_recherche_projets():
    """Recherche live du catalogue "Ajouter une ligne" (retour Fadhel,
    2026-09-27) : remplace l'ancienne liste statique des 50 premiers
    projets de l'entreprise, affichée en permanence — l'utilisateur tape,
    on cherche par code/nom parmi les projets en cours. Voir
    dailylog.rechercher_projets."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return {"resultats": []}
    return {"resultats": dailylog.rechercher_projets(q, user_id=g.user["id"])}


@bp.route("", methods=["POST"])
@login_required
def enregistrer():
    # Validation de la date (PROMPT_CORRECTIONS.md P1 #10) : voir
    # _parser_date — évite d'enregistrer sur un format invalide ou une
    # date future en soumettant directement ce formulaire.
    date = _parser_date(request.form.get("date"))
    date_str = date.isoformat()

    projet_ids = request.form.getlist("ligne_projet_id")
    tache_ids = request.form.getlist("ligne_tache_id")
    heures_list = request.form.getlist("ligne_heures")

    lignes = []
    for pid, tid, h in zip(projet_ids, tache_ids, heures_list):
        # Ids non numériques (PROMPT_CORRECTIONS.md P1 #10) : `int(pid)`
        # sur une valeur trafiquée plantait auparavant en 500 (ValueError
        # non rattrapée) — on ignore silencieusement la ligne invalide
        # plutôt que de faire échouer tout l'enregistrement.
        if not pid or not pid.isdigit():
            continue
        if tid and not tid.isdigit():
            continue
        projet_id = int(pid)
        tache_id = int(tid) if tid else None

        try:
            heures = round(float(h), 2)
        except (TypeError, ValueError):
            continue
        # Bornes des heures (PROMPT_CORRECTIONS.md P1 #10) : ni négatives/
        # nulles (déjà le cas), ni au-delà d'une journée raisonnable —
        # rien n'empêchait auparavant de soumettre une valeur aberrante
        # directement dans le formulaire (le curseur JS, lui, la borne déjà
        # à 100 % de la journée type, mais ne protège pas contre une
        # requête forgée à la main).
        if heures <= 0 or heures > MAX_HEURES_PAR_LIGNE:
            continue

        # Visibilité du projet (PROMPT_CORRECTIONS.md P1 #10) : sans ce
        # contrôle, n'importe quel utilisateur connecté pouvait enregistrer
        # des heures sur n'importe quel projet de l'entreprise, pas
        # seulement ceux de son équipe/ses affectations.
        if not projets_repo.user_can_view(projet_id, g.user["id"]):
            continue

        # La tâche doit appartenir au projet indiqué sur la MÊME ligne —
        # sinon une ligne pourrait pointer un couple projet/tâche
        # incohérent (PROMPT_CORRECTIONS.md P1 #10).
        if tache_id is not None:
            tache = taches_repo.get_tache(tache_id)
            if tache is None or tache["projet_id"] != projet_id:
                continue

        lignes.append({
            "projet_id": projet_id,
            "tache_id": tache_id,
            "heures": heures,
        })

    dailylog.remplacer_jour(g.user["id"], date_str, lignes, current_user_id=g.user["id"])
    flash("Daily log enregistré.", "success")
    return redirect(url_for("dailylog.formulaire", date=date_str))

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
import math

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..auth import role_required
from ..repositories import dailylog
from ..repositories import projets as projets_repo
from ..repositories import taches as taches_repo

bp = Blueprint("dailylog", __name__, url_prefix="/dailylog")

# Ni le RH (aucun accès aux projets) ni un Client n'ont de Daily log
# (décisions Fadhel, lot 7).
ROLES_DAILYLOG = ("admin", "chef_de_projet", "intervenant")

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
@role_required(*ROLES_DAILYLOG)
def formulaire():
    date = _parser_date(request.args.get("date"))
    aujourdhui = datetime.date.today()

    entrees = dailylog.list_entrees_jour(g.user["id"], date)
    suggestions = dailylog.list_lignes_suggerees(g.user["id"])
    # Daily log v2 (2026-09-29) : durée du jour (4-10 h, réglable par
    # double-clic) et absence ; pour une journée saisie avant cette version,
    # la durée vaut le total de ses heures (option B, heures inchangées).
    duree, absent = dailylog.duree_et_absence(g.user["id"], date, entrees)

    if entrees:
        lignes_initiales = [
            {
                "projet_id": e["projet_id"], "tache_id": e["tache_id"],
                "code": e.get("projet_code"), "nom": e["projet_nom"], "tache_titre": e["tache_titre"],
                "minutes": round(float(e["heures"]) * 60),
            }
            for e in entrees
        ]
    else:
        # Rien d'enregistré ce jour : projets en cours proposés par défaut
        # (lignes "projet seul" du catalogue), répartis à parts égales par
        # la page (minutes = None).
        defauts = [m for m in suggestions["mine"] if m["tache_id"] is None]
        lignes_initiales = [
            {"projet_id": p["projet_id"], "tache_id": None, "code": p.get("code"), "nom": p["nom"],
             "tache_titre": None, "minutes": None}
            for p in defauts
        ]

    est_aujourdhui = date == aujourdhui
    hier = date - datetime.timedelta(days=1)
    demain = date + datetime.timedelta(days=1)
    # Pas de rappel pour un week-end non travaillé (même heuristique que le
    # rappel automatique à la connexion, voir auth._verifier_rappel_dailylog).
    rappel_hier = (
        est_aujourdhui and hier.weekday() < 5
        and not dailylog.jour_renseigne(g.user["id"], hier)
    )

    mois_ref = date.replace(day=1)
    etats_du_mois = dailylog.etats_jours_mois(
        g.user["id"], mois_ref.year, mois_ref.month, standard_hours=STANDARD_HOURS,
    )

    return render_template(
        "dailylog.html",
        date=date, aujourdhui=aujourdhui, est_aujourdhui=est_aujourdhui,
        hier=hier, demain=demain, rappel_hier=rappel_hier,
        lignes_initiales=lignes_initiales, lignes_enregistrees=bool(entrees),
        suggestions=suggestions, etats_jours=etats_du_mois,
        duree=duree, absent=absent,
    )


@bp.route("/jours-remplis")
@role_required(*ROLES_DAILYLOG)
def api_jours_remplis():
    """Petite API JSON interne (même origine, même session) utilisée par le
    calendrier du DailyLog pour afficher les pastilles rempli/partiel/
    manque (Lot 5, retour Fadhel, 2026-09-28) quand on change de mois sans
    recharger toute la page. Nom de route/endpoint conservé tel quel
    (historique) même si la réponse ne se limite plus aux seuls jours
    "remplis" depuis ce chantier."""
    annee = request.args.get("annee", type=int)
    mois = request.args.get("mois", type=int)
    if not annee or not mois:
        return {"etats": {}}
    return {"etats": dailylog.etats_jours_mois(g.user["id"], annee, mois, standard_hours=STANDARD_HOURS)}


@bp.route("/recherche-projets")
@role_required(*ROLES_DAILYLOG)
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
@role_required(*ROLES_DAILYLOG)
def enregistrer():
    # Validation de la date (PROMPT_CORRECTIONS.md P1 #10) : voir
    # _parser_date — évite d'enregistrer sur un format invalide ou une
    # date future en soumettant directement ce formulaire.
    date = _parser_date(request.form.get("date"))
    date_str = date.isoformat()

    # Daily log v2 : durée de la journée (l'écran propose 4-10 h par
    # demi-heure ; on accepte aussi la durée d'une ancienne journée, option
    # B, d'où la borne large 0-24 h au quart d'heure) et absence.
    absent = request.form.get("absent") == "1"
    try:
        duree = float(request.form.get("duree") or STANDARD_HOURS)
    except ValueError:
        duree = None
    if duree is None or not math.isfinite(duree) or duree <= 0 or duree > MAX_HEURES_PAR_LIGNE \
            or abs(duree * 4 - round(duree * 4)) > 1e-6:
        flash("Durée de journée invalide.", "error")
        return redirect(url_for("dailylog.formulaire", date=date_str))

    projet_ids = request.form.getlist("ligne_projet_id")
    tache_ids = request.form.getlist("ligne_tache_id")
    heures_list = request.form.getlist("ligne_heures")

    lignes = []
    # Lignes refusées par la validation ci-dessous (projet devenu
    # invisible, tâche déplacée, heures hors bornes...) : leur éventuelle
    # valeur DÉJÀ enregistrée doit être conservée telle quelle. Avant ce
    # correctif, remplacer_jour supprimait toute ligne existante absente
    # de la soumission — une ligne refusée disparaissait donc en silence
    # alors que la page affichait "enregistré" (audit n°2).
    refusees = set()
    # Projets clos avant ce jour (décision Fadhel, lot 7) : plus d'heures
    # après leur date de clôture — toute la saisie est alors refusée.
    clotures = {}
    apres_cloture = []
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
        cle = (projet_id, tache_id or 0)

        try:
            heures = round(float(h), 2)
        except (TypeError, ValueError):
            refusees.add(cle)
            continue
        # NaN/infini (audit n°2) : `nan <= 0` et `nan > 24` sont tous deux
        # faux, NaN passait donc les bornes ci-dessous — et PostgreSQL
        # l'accepte dans NUMERIC (CHECK heures > 0 compris), ce qui
        # rendait les totaux d'heures du projet égaux à "NaN" pour de bon.
        if not math.isfinite(heures):
            refusees.add(cle)
            continue
        # Bornes des heures (PROMPT_CORRECTIONS.md P1 #10) : ni négatives/
        # nulles (déjà le cas), ni au-delà d'une journée raisonnable —
        # rien n'empêchait auparavant de soumettre une valeur aberrante
        # directement dans le formulaire (le curseur JS, lui, la borne déjà
        # à 100 % de la journée type, mais ne protège pas contre une
        # requête forgée à la main).
        if heures <= 0 or heures > MAX_HEURES_PAR_LIGNE:
            refusees.add(cle)
            continue

        # Visibilité du projet (PROMPT_CORRECTIONS.md P1 #10) : sans ce
        # contrôle, n'importe quel utilisateur connecté pouvait enregistrer
        # des heures sur n'importe quel projet de l'entreprise, pas
        # seulement ceux de son équipe/ses affectations.
        if not projets_repo.user_can_view(projet_id, g.user["id"]):
            refusees.add(cle)
            continue

        if projet_id not in clotures:
            projet = projets_repo.get_projet(projet_id)
            clotures[projet_id] = (
                (projet.get("date_cloture"), f"{projet['code']}_{projet['nom']}")
                if projet and projet["etat"] in projets_repo.ETATS_CLOS and projet.get("date_cloture")
                else None
            )
        if clotures[projet_id] and date > clotures[projet_id][0]:
            date_cloture, libelle = clotures[projet_id]
            apres_cloture.append(f"{libelle} (clos le {date_cloture.strftime('%d/%m/%Y')})")
            continue

        # La tâche doit appartenir au projet indiqué sur la MÊME ligne —
        # sinon une ligne pourrait pointer un couple projet/tâche
        # incohérent (PROMPT_CORRECTIONS.md P1 #10).
        if tache_id is not None:
            tache = taches_repo.get_tache(tache_id)
            if tache is None or tache["projet_id"] != projet_id:
                refusees.add(cle)
                continue

        lignes.append({
            "projet_id": projet_id,
            "tache_id": tache_id,
            "heures": heures,
        })

    if apres_cloture:
        flash(
            "Rien n'a été enregistré : on ne peut plus saisir d'heures après la clôture d'un projet — "
            + ", ".join(dict.fromkeys(apres_cloture)) + ". Retirez cette ligne de la journée.",
            "error",
        )
        return redirect(url_for("dailylog.formulaire", date=date_str))

    # Total toujours = durée de la journée (Daily log v2 : "toujours
    # 100 %"). La page le garantit ; ce contrôle protège d'une requête
    # forgée. Les lignes refusées gardent leur valeur déjà enregistrée :
    # elle compte donc dans le total (audit du 2026-09-29 — le contrôle
    # était sauté dès qu'une ligne était refusée, ce qui laissait
    # enregistrer 3 × 24 h sur une journée avec une ligne invalide).
    if not absent and (lignes or refusees):
        conservees = 0.0
        if refusees:
            deja = {(e["projet_id"], e["tache_id"] or 0): float(e["heures"])
                    for e in dailylog.list_entrees_jour(g.user["id"], date_str)}
            conservees = sum(deja.get(cle, 0.0) for cle in refusees)
        total = round(sum(l["heures"] for l in lignes) + conservees, 2)
        if abs(total - duree) > 0.02:
            if refusees:
                flash(
                    f"{len(refusees)} ligne(s) ne peuvent pas être modifiées (valeur invalide, ou projet "
                    f"auquel vous n'avez plus accès) : leur valeur déjà enregistrée ({conservees:g} h) est "
                    "conservée, et la journée doit rester répartie à 100 % : rien n'a été enregistré.",
                    "error",
                )
                return redirect(url_for("dailylog.formulaire", date=date_str))
            flash("La journée doit être répartie à 100 % : rien n'a été enregistré.", "error")
            return redirect(url_for("dailylog.formulaire", date=date_str))

    dailylog.remplacer_jour(
        g.user["id"], date_str, lignes, current_user_id=g.user["id"],
        conserver=refusees, duree_heures=duree, absent=absent,
    )
    if refusees:
        flash(
            f"Daily log enregistré, sauf {len(refusees)} ligne(s) invalide(s) "
            "ou sur un projet auquel vous n'avez plus accès : leur valeur "
            "précédente a été conservée.", "error",
        )
    elif absent:
        flash("Journée enregistrée comme absente.", "success")
    else:
        flash("Daily log enregistré.", "success")
    return redirect(url_for("dailylog.formulaire", date=date_str))

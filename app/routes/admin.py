"""Journal d'audit admin (retour Fadhel, 2026-09-28, Lot 5) — parcours en
lecture seule de `audit_log`, réservé à l'Admin (les mêmes données
touchent tous les rôles/toutes les équipes, contrairement à `utilisateurs`
qui est aussi ouvert au RH/chef de projet ; le journal d'audit reste
Admin-only, comme demandé).

Lot 13 (phase 2, audit a11y I6 et I10, UX §2.7) : vrai tableau groupé par
jour, 100 entrées par page avec un curseur (« Charger 100 de plus »),
filtres appliqués en mise à jour partielle, données avant / après
chargées à la demande et présentées en différences lisibles."""
import datetime
import json
import re

from flask import Blueprint, abort, flash, render_template, request, url_for

from .. import filtres_memoire, horloge, partiel
from ..auth import role_required
from ..repositories import audit as audit_repo
from ..utils import date_fr
from ..validation import DATE_MAX, DATE_MIN, ids_entiers

bp = Blueprint("admin", __name__, url_prefix="/admin")

PAR_PAGE = 100
LONGUEUR_MAX_VALEUR = 400


def _parser_date(date_str: str | None):
    """Même logique que projets._parser_date_tache : None si absent/vide,
    lève ValueError sur un format invalide plutôt que de l'avaler."""
    if not date_str:
        return None
    return datetime.date.fromisoformat(date_str)


def _lire_curseur(valeur: str | None):
    """« <created_at ISO>_<id> » -> (datetime, id), None si absent ou invalide
    (y compris hors des bornes de PostgreSQL : id bigint, décalage < 16 h,
    année 2000-2099)."""
    if not valeur or "_" not in valeur:
        return None
    instant, _, ident = valeur.rpartition("_")
    if not re.fullmatch(r"[0-9]{1,18}", ident, flags=re.ASCII):
        return None
    try:
        moment = datetime.datetime.fromisoformat(instant)
    except ValueError:
        return None
    decalage = moment.utcoffset()
    if decalage is not None and abs(decalage) >= datetime.timedelta(hours=16):
        return None
    if not DATE_MIN.year <= moment.year <= DATE_MAX.year:
        return None
    return moment, int(ident)


def _jour_local(dt) -> datetime.date:
    return dt.astimezone(horloge.maintenant_reel().tzinfo).date() if dt.tzinfo else dt.date()


def grouper_par_jour(entrees: list[dict], jour_precedent: str | None = None) -> list[dict]:
    """Entrées groupées par jour (au fuseau de l'Admin, horodatage réel) ;
    une page qui continue le jour de la précédente le dit (« suite »)."""
    aujourdhui = horloge.aujourdhui_reel()
    groupes: list[dict] = []
    fuseau = horloge.maintenant_reel().tzinfo
    for e in entrees:
        local = e["created_at"].astimezone(fuseau) if e["created_at"].tzinfo else e["created_at"]
        e["heure"] = local.strftime("%H:%M")
        jour = local.date()
        if not groupes or groupes[-1]["jour"] != jour:
            titre = ("Aujourd’hui" if jour == aujourdhui
                     else "Hier" if jour == aujourdhui - datetime.timedelta(days=1) else date_fr(jour))
            suite = not groupes and jour_precedent == jour.isoformat()
            groupes.append({"jour": jour, "titre": titre + (" (suite)" if suite else ""), "entrees": []})
        groupes[-1]["entrees"].append(e)
    return groupes


def _valeur(v) -> str:
    texte = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return texte if len(texte) <= LONGUEUR_MAX_VALEUR else texte[:LONGUEUR_MAX_VALEUR] + "…"


def differences(entree: dict) -> dict:
    """Données d'une entrée en différences lisibles : pour une modification,
    les champs changés (avant -> après) et le nombre de champs inchangés ;
    pour une création, une suppression ou un mode de l'Admin, les champs
    renseignés."""
    avant, apres = entree.get("donnees_avant"), entree.get("donnees_apres")
    if not isinstance(avant, dict) and not isinstance(apres, dict):
        brut = avant if avant is not None else apres
        return {"lignes": [], "inchanges": [], "brut": None if brut is None else _valeur(brut)}
    avant, apres = avant if isinstance(avant, dict) else {}, apres if isinstance(apres, dict) else {}
    lignes, inchanges = [], []
    for champ in list(dict.fromkeys([*avant.keys(), *apres.keys()])):
        a, b = avant.get(champ), apres.get(champ)
        if avant and apres:
            if a == b:
                inchanges.append({"champ": champ, "valeur": _valeur(a)})
            else:
                lignes.append({"champ": champ, "avant": _valeur(a), "apres": _valeur(b), "type": "modifie"})
        elif apres:
            if b is not None and b != "" and b != [] and b != {}:
                lignes.append({"champ": champ, "apres": _valeur(b), "type": "ajoute"})
        elif a is not None and a != "" and a != [] and a != {}:
            lignes.append({"champ": champ, "avant": _valeur(a), "type": "retire"})
    return {"lignes": lignes, "inchanges": inchanges, "brut": None}


def _filtres():
    """Filtres de l'adresse, validés (lot 13, audit rôles M15 : un filtre
    invalide est ignoré, mais on le dit)."""
    ignores = []
    # Lot 23 (décision du gérant) : table, action et auteur mémorisés par
    # personne (app/filtres_memoire.py) ; les dates restent dans l'adresse.
    source = filtres_memoire.source("journal") or {}
    table_cible = source.get("table") or None
    if table_cible not in audit_repo.TABLES_FILTRABLES:
        if table_cible:
            ignores.append("table")
        table_cible = None

    action = source.get("action") or None
    if action not in audit_repo.ACTIONS_VALIDES:
        if action:
            ignores.append("action")
        action = None

    utilisateur_id_str = source.get("utilisateur_id")
    utilisateur_id = next(iter(ids_entiers([utilisateur_id_str or ""])), None)
    if utilisateur_id_str and utilisateur_id is None:
        ignores.append("auteur")

    date_debut_str = request.args.get("date_debut") or ""
    date_fin_str = request.args.get("date_fin") or ""
    try:
        date_debut = _parser_date(date_debut_str)
        date_fin = _parser_date(date_fin_str)
    except ValueError:
        # Date saisie à la main dans l'URL, invalide : on l'ignore plutôt
        # que de planter la page (même choix que dailylog._parser_date).
        date_debut = date_fin = None
        date_debut_str = date_fin_str = ""
        ignores.append("dates")
    if ignores:
        flash(f"Filtre{'s' if len(ignores) > 1 else ''} invalide{'s' if len(ignores) > 1 else ''} ignoré"
              f"{'s' if len(ignores) > 1 else ''}\u00a0: {', '.join(ignores)}.", "error")
    return {
        "table": table_cible or "", "action": action or "", "utilisateur_id": utilisateur_id or "",
        "date_debut": date_debut_str, "date_fin": date_fin_str,
    }, {
        "table_cible": table_cible, "utilisateur_id": utilisateur_id, "action": action,
        "date_debut": date_debut, "date_fin": date_fin,
    }


@bp.route("/journal")
@role_required("admin")
def journal():
    # Lot 24 (FI-05) : une page suivante (« Charger 100 de plus ») garde son
    # adresse, jamais renvoyée vers le choix mémorisé.
    retour = (None if request.args.get("avant") else
              filtres_memoire.redirection("journal", "admin.journal", date_debut=request.args.get("date_debut"),
                                          date_fin=request.args.get("date_fin")))
    if retour is not None:
        return retour
    filtres, criteres = _filtres()
    filtres_memoire.memoriser("journal", dict(filtres, filtres_actifs="1"))
    curseur = _lire_curseur(request.args.get("avant"))
    deja = request.args.get("n", 0, type=int) if curseur else 0
    deja = max(0, min(deja or 0, 1_000_000))
    lignes = audit_repo.list_entrees(**criteres, avant=curseur, limit=PAR_PAGE + 1, avec_donnees=False)
    entrees, encore = lignes[:PAR_PAGE], len(lignes) > PAR_PAGE
    suite_url = None
    if encore:
        dernier = entrees[-1]
        suite_url = url_for(
            "admin.journal", **{k: v for k, v in filtres.items() if v},
            avant=f"{dernier['created_at'].isoformat()}_{dernier['id']}", n=deja + len(entrees),
            jour=_jour_local(dernier["created_at"]).isoformat(),
        )
    contexte = dict(
        groupes=grouper_par_jour(entrees, request.args.get("jour") if curseur else None),
        nb_affichees=deja + len(entrees), encore=encore, suite_url=suite_url,
        ancre_id=curseur[1] if curseur else None, suite_id=entrees[-1]["id"] if encore else None,
        filtres=filtres, filtre_actif=any(filtres.values()),
    )
    if partiel.est_partiel():
        if curseur:
            # « Charger 100 de plus » : les jours suivants, ajoutés au tableau.
            return partiel.repondre("partials/journal_pages.html", oob_suite=True, oob_compte=True, **contexte)
        return partiel.repondre("partials/journal_resultats.html", oob_compte=True, **contexte)
    return render_template(
        "admin_journal.html", **contexte,
        tables=audit_repo.TABLES_FILTRABLES, actions=audit_repo.ACTIONS_VALIDES, auteurs=audit_repo.list_auteurs(),
        suite_page=bool(curseur), filtres_url={k: v for k, v in filtres.items() if v},
    )


@bp.route("/journal/<int:entree_id>")
@role_required("admin")
def journal_entree(entree_id: int):
    """Données avant / après d'une entrée : fragment chargé au premier
    dépliage de « Voir les données » ; sans JavaScript, une page."""
    entree = audit_repo.get_entree(entree_id)
    if entree is None:
        if partiel.est_partiel():
            return partiel.refuser("Entrée du journal introuvable.", 404)
        abort(404)
    if partiel.est_partiel():
        return partiel.repondre("partials/journal_diff.html", e=entree, diff=differences(entree))
    return render_template("admin_journal_entree.html", e=entree, diff=differences(entree))

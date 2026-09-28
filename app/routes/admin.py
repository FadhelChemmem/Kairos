"""Journal d'audit admin (retour Fadhel, 2026-09-28, Lot 5) — parcours en
lecture seule de `audit_log`, réservé à l'Admin (les mêmes données
touchent tous les rôles/toutes les équipes, contrairement à `utilisateurs`
qui est aussi ouvert au RH/chef de projet ; le journal d'audit reste
Admin-only, comme demandé)."""
import datetime

from flask import Blueprint, render_template, request

from ..auth import role_required
from ..repositories import audit as audit_repo

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _parser_date(date_str: str | None):
    """Même logique que projets._parser_date_tache : None si absent/vide,
    lève ValueError sur un format invalide plutôt que de l'avaler."""
    if not date_str:
        return None
    return datetime.date.fromisoformat(date_str)


@bp.route("/journal")
@role_required("admin")
def journal():
    table_cible = request.args.get("table") or None
    if table_cible not in audit_repo.TABLES_AUDITEES:
        table_cible = None

    action = request.args.get("action") or None
    if action not in audit_repo.ACTIONS_VALIDES:
        action = None

    utilisateur_id_str = request.args.get("utilisateur_id")
    utilisateur_id = int(utilisateur_id_str) if utilisateur_id_str and utilisateur_id_str.isdigit() else None

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

    entrees = audit_repo.list_entrees(
        table_cible=table_cible, utilisateur_id=utilisateur_id, action=action,
        date_debut=date_debut, date_fin=date_fin,
    )

    return render_template(
        "admin_journal.html",
        entrees=entrees,
        tables=audit_repo.TABLES_AUDITEES,
        actions=audit_repo.ACTIONS_VALIDES,
        auteurs=audit_repo.list_auteurs(),
        table_cible=table_cible or "", action=action or "",
        utilisateur_id=utilisateur_id or "",
        date_debut=date_debut_str, date_fin=date_fin_str,
    )

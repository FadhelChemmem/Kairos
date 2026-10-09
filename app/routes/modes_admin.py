"""Lot 12 : pages et actions des modes de l'Admin (voir app/modes_admin.py).

- `modes_admin` (toujours enregistré) :
    GET  /admin/voir-comme          choix du compte (Admin)
    POST /admin/voir-comme          « Voir comme » (lecture seule)
    POST /admin/revenir             « Revenir à mon compte »
- `mode_test` (enregistré SEULEMENT si KAIROS_MODE_TEST=true : sans lui,
  ces adresses n'existent pas — 404) :
    POST /admin/agir-comme          « Agir comme » (modifications permises)
    POST /admin/date-simulee        choisir la date simulée (heure facultative, lot 13)
    POST /admin/date-simulee/effacer  « Revenir à aujourd'hui »
    POST /admin/rappel-simule       « Simuler le rappel du jour » (lot 13)

Toutes en POST protégées par le jeton CSRF (CSRFProtect global, champ
caché des formulaires). Les droits portent sur l'Admin RÉEL (g.admin_reel
pendant un mode, sinon g.user) : un autre rôle reçoit 403, quelle que soit
la requête forgée.
"""
import functools
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from .. import auth
from .. import modes_admin as modes
from ..auth import login_required
from ..repositories import utilisateurs as utilisateurs_repo
from ..utils import is_safe_next

bp = Blueprint("modes_admin", __name__, url_prefix="/admin")
bp_test = Blueprint("mode_test", __name__, url_prefix="/admin")

_RE_ID = re.compile(r"^[0-9]{1,18}$")


def _admin_reel() -> dict | None:
    admin = g.get("admin_reel") or g.get("user")
    if admin is None or admin.get("role") != "admin" or not admin.get("actif"):
        return None
    return admin


def admin_reel_requis(view):
    """L'Admin réel, actif — sinon 403 (jamais une redirection silencieuse :
    une requête forgée par un autre rôle est refusée nettement)."""
    @functools.wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if _admin_reel() is None:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def mode_test_requis(view):
    """Défense en profondeur : ces routes ne sont enregistrées qu'en mode
    test (app/__init__.py) ; si la configuration change à chaud, 404."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not modes.mode_test_actif():
            abort(404)
        return view(*args, **kwargs)
    return wrapped


def _retour(defaut: str = "main.accueil"):
    suivant = request.form.get("next")
    return redirect(suivant if is_safe_next(suivant) else url_for(defaut))


@bp.route("/voir-comme", methods=["GET"])
@admin_reel_requis
def page():
    if g.get("admin_reel") is not None:
        flash("Revenez d'abord à votre compte (bandeau en haut de la page).", "error")
        return redirect(url_for("main.accueil"))
    return render_template(
        "admin_voir_comme.html",
        comptes=utilisateurs_repo.list_cibles_voir_comme(),
        mode_test=modes.mode_test_actif(),
    )


def _commencer(mode: str):
    admin = _admin_reel()
    if g.get("admin_reel") is not None:
        flash("Revenez d'abord à votre compte avant d'en choisir un autre.", "error")
        return redirect(url_for("main.accueil"))
    brut = (request.form.get("utilisateur_id") or "").strip()
    if not brut:
        flash("Choisissez un compte dans la liste.", "error")
        return redirect(url_for("modes_admin.page"))
    cible = auth.get_user_by_id(int(brut)) if _RE_ID.match(brut) else None
    refus = modes.cible_autorisee(cible, admin)
    if refus is not None:
        flash(refus, "error")
        return redirect(url_for("modes_admin.page"))
    session[modes.CLE_MODE] = {"admin": admin["id"], "cible": cible["id"], "mode": mode}
    modes.journaliser(modes.TABLES_JOURNAL[mode], "ENTREE", admin["id"], cible)
    return redirect(url_for("main.accueil"))


@bp.route("/voir-comme", methods=["POST"])
@admin_reel_requis
def voir_comme():
    return _commencer("voir")


@bp_test.route("/agir-comme", methods=["POST"])
@mode_test_requis
@admin_reel_requis
def agir_comme():
    return _commencer("agir")


@bp.route("/revenir", methods=["POST"])
@login_required
def revenir():
    """« Revenir à mon compte » : toujours permis (même en lecture seule).
    Sans mode en cours (double clic, autre onglet) : simple retour."""
    admin = g.get("admin_reel")
    if admin is not None and g.get("mode_admin"):
        modes.journaliser(modes.TABLES_JOURNAL[g.mode_admin], "SORTIE", admin["id"], g.user, raison="retour")
        if g.mode_admin == "agir":
            modes.purger_rappels_simules(g.user["id"])
    session.pop(modes.CLE_MODE, None)
    suivant = request.form.get("next")
    if is_safe_next(suivant):
        return redirect(suivant)
    return redirect(url_for("modes_admin.page") if admin is not None else url_for("main.accueil"))


@bp_test.route("/date-simulee", methods=["POST"])
@mode_test_requis
@admin_reel_requis
def date_simulee():
    admin = _admin_reel()
    date = modes.lire_date((request.form.get("date") or "").strip())
    if date is None:
        flash(f"Date simulée invalide : choisissez une date entre le {modes.DATE_SIMULEE_MIN.strftime('%d/%m/%Y')} "
              f"et le {modes.DATE_SIMULEE_MAX.strftime('%d/%m/%Y')}.", "error")
        return _retour()
    # Heure facultative (lot 13, audit temps T-M4) : instant simulé à Tunis.
    heure_brute = (request.form.get("heure") or "").strip()
    heure = modes.lire_heure(heure_brute)
    if heure_brute and heure is None:
        flash("Heure simulée invalide : HH:MM (ex. 23:30), ou laissez le champ vide.", "error")
        return _retour()
    valeur = {"admin": admin["id"], "date": date.isoformat()}
    if heure is not None:
        valeur["heure"] = heure.strftime("%H:%M")
    session[modes.CLE_DATE] = valeur
    modes.journaliser(modes.TABLE_DATE, "ENTREE", admin["id"], date=date.isoformat(), heure=valeur.get("heure"),
                      compte_vu_id=g.user["id"] if g.get("admin_reel") else None)
    # Toast à l'arrivée (verif-ux, écart de spécification) : la page est
    # rechargée — toute la page dépend de la date —, l'Admin sait pourquoi.
    from ..utils import date_longue
    flash(f"Date simulée appliquée : {date_longue(date)}"
          f"{' à ' + valeur['heure'] + ' (Tunis)' if heure is not None else ''}.", "success")
    return _retour()


@bp_test.route("/date-simulee/effacer", methods=["POST"])
@mode_test_requis
@admin_reel_requis
def date_simulee_effacer():
    admin = _admin_reel()
    if g.get("date_simulee") is not None:
        modes.journaliser(modes.TABLE_DATE, "SORTIE", admin["id"], date=g.date_simulee.isoformat(), raison="retour")
        modes.purger_rappels_simules(admin["id"], g.user["id"] if g.get("mode_admin") == "agir" else None)
    session.pop(modes.CLE_DATE, None)
    flash("Retour à la date réelle.", "success")
    return _retour()


@bp_test.route("/rappel-simule", methods=["POST"])
@mode_test_requis
@admin_reel_requis
def rappel_simule():
    """« Simuler le rappel du jour » (lot 13, audit temps T-M6) : le rappel
    Daily log que le compte agi (ou l'Admin lui-même) recevrait aujourd'hui
    — date simulée comprise —, avec les mêmes règles que le vrai (un seul
    rappel groupé, aucun jour rappelé deux fois, rappel lu quand ses jours
    sont remplis ou hors de la fenêtre). Sous date simulée, la notification
    est marquée simulée : elle ne bloque jamais un vrai rappel, ne se voit
    que pendant le test et est supprimée à « Revenir à mon compte » /
    « Revenir à aujourd'hui ». Refusé en « Voir comme » (lecture seule,
    app/modes_admin.py) et depuis un onglet resté sur un autre mode."""
    from ..repositories import dailylog as dailylog_repo
    from ..repositories import notifications as notifications_repo

    cible = g.user
    if cible.get("role") not in ("admin", "chef_de_projet", "intervenant"):
        flash(f"{modes.nom_complet(cible)} n'a pas de Daily log : aucun rappel possible.", "error")
        return _retour()
    aujourdhui = dailylog_repo.aujourdhui_pour(cible)
    simulee = g.get("date_simulee") is not None
    notifications_repo.marquer_rappels_dailylog_lus(cible["id"])
    jours = auth._verifier_rappel_dailylog(cible, aujourdhui=aujourdhui, simulee=simulee)
    from ..utils import date_longue, texte_rappel_daily_log

    if jours:
        flash(f"Rappel {'simulé ' if simulee else ''}du {date_longue(aujourdhui)} pour {modes.nom_complet(cible)} : "
              f"« {texte_rappel_daily_log(jours, aujourdhui)} » (cloche).", "success")
    else:
        flash(f"Aucun rappel le {date_longue(aujourdhui)} pour {modes.nom_complet(cible)} : rien à rappeler "
              "(jours remplis, déjà rappelés, week-end ou avant l'arrivée).", "success")
    return _retour()

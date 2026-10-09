"""Lot 12 (demande du gérant) : « Voir comme… », « Agir comme… » et date
simulée — outils de l'Admin pour la phase de test.

- « Voir comme » (toujours disponible, Admin seulement) : l'Admin voit
  Kairos exactement comme un compte actif NON admin (menus, projets
  visibles, Mes tâches, Deadlines, Daily log, boutons et états autorisés).
  LECTURE SEULE : toute requête qui modifie est refusée (403, message clair,
  JSON pour l'API) sauf « Revenir à mon compte », la date simulée et la
  déconnexion ; toutes les transactions de la requête sont en plus ouvertes
  READ ONLY (app/db.py) — aucun effet de bord possible en lecture (rappel
  Daily log, notification lue, e-mail…).
- « Agir comme » (KAIROS_MODE_TEST=true seulement) : même chose, mais les
  modifications sont permises au nom du compte cible ; le journal d'audit
  garde l'Admin réel (audit_log.admin_reel_id, migration 0018).
- Date simulée (KAIROS_MODE_TEST=true seulement) : pour la session de
  l'Admin (et le compte vu ou agi), « aujourd'hui » vaut cette date
  (app/horloge.py ; en base, réglage kairos.date_simulee lu par
  fn_aujourdhui).

La session RÉELLE reste celle de l'Admin : session["user_id"], empreinte du
mot de passe, génération (révocation) et durée absolue du lot 10 sont
contrôlées sur SON compte, à chaque requête, avant `appliquer()`. Le mode
vit dans deux clés signées du cookie de session, liées à l'id de l'Admin ;
elles ne valent rien si le compte de la session n'est pas un Admin actif
(un cookie forgé est de toute façon refusé : signature SECRET_KEY). La
déconnexion vide toute la session.
"""
import datetime
import logging

from flask import current_app, flash, g, render_template, request, session

logger = logging.getLogger(__name__)

CLE_MODE = "mode_admin"      # {"admin": id, "cible": id, "mode": "voir" | "agir"}
CLE_DATE = "date_simulee"    # {"admin": id, "date": "AAAA-MM-JJ"}
MODES = ("voir", "agir")
TABLES_JOURNAL = {"voir": "mode_voir_comme", "agir": "mode_agir_comme"}
TABLE_DATE = "date_simulee"

# Toujours permis en « Voir comme » (aucune donnée métier modifiée).
ENDPOINTS_PERMIS_EN_LECTURE = frozenset({
    "modes_admin.revenir", "auth.logout", "mode_test.date_simulee", "mode_test.date_simulee_effacer",
})
# Jamais permis en « Agir comme » : changer le mot de passe du compte cible
# réécrirait l'empreinte de la session de l'Admin (auth.password_fingerprint).
ENDPOINTS_INTERDITS_EN_AGIR = frozenset({"utilisateurs.mon_mot_de_passe"})
METHODES_LECTURE = frozenset({"GET", "HEAD", "OPTIONS"})

# Bornes de la date simulée : celles des dates plausibles de l'appli.
DATE_SIMULEE_MIN = datetime.date(2000, 1, 1)
DATE_SIMULEE_MAX = datetime.date(2099, 12, 31)

LIBELLES_ROLE = {"chef_de_projet": "Chef de projet", "intervenant": "Intervenant", "rh": "RH",
                 "client": "Client", "admin": "Administrateur"}


def mode_test_actif() -> bool:
    """KAIROS_MODE_TEST=true (config.py) : « Agir comme » et date simulée."""
    return current_app.config.get("MODE_TEST") is True


def nom_complet(personne: dict | None) -> str:
    personne = personne or {}
    return f"{personne.get('prenom') or ''} {personne.get('nom') or ''}".strip()


def libelle_compte(personne: dict) -> str:
    """« Rim Inter (Intervenant) »."""
    return f"{nom_complet(personne)} ({LIBELLES_ROLE.get(personne.get('role'), personne.get('role') or '')})"


def cible_autorisee(cible: dict | None, admin: dict) -> str | None:
    """None si `admin` peut voir Kairos comme `cible`, sinon la raison."""
    if cible is None:
        return "Compte introuvable."
    if cible.get("id") == admin.get("id") or cible.get("role") == "admin":
        return "Impossible de voir Kairos comme un autre Admin."
    if not cible.get("actif"):
        return f"Le compte de {nom_complet(cible)} est désactivé."
    return None


def lire_date(texte) -> datetime.date | None:
    """AAAA-MM-JJ strict, entre DATE_SIMULEE_MIN et DATE_SIMULEE_MAX."""
    if not isinstance(texte, str) or len(texte) != 10 or not texte.isascii():
        return None
    try:
        d = datetime.date.fromisoformat(texte)
    except ValueError:
        return None
    return d if DATE_SIMULEE_MIN <= d <= DATE_SIMULEE_MAX else None


def journaliser(table: str, action: str, admin_id: int, cible: dict | None = None, **details) -> None:
    """Entrée / sortie d'un mode dans le journal d'audit (jamais bloquant)."""
    from .repositories import audit as audit_repo

    donnees = dict(details)
    if cible is not None:
        donnees.update(compte_vu_id=cible.get("id"), compte_vu=nom_complet(cible), role=cible.get("role"))
    try:
        audit_repo.journaliser_mode(table, action, admin_id, cible.get("id") if cible else None, donnees)
    except Exception:
        logger.exception("Journal d'audit : %s %s impossible (admin id=%s)", action, table, admin_id)


def _quitter_mode(admin: dict, mode: dict, cible: dict | None, raison: str, message: str | None) -> None:
    session.pop(CLE_MODE, None)
    if mode.get("mode") in MODES:
        journaliser(TABLES_JOURNAL[mode["mode"]], "SORTIE", admin["id"],
                    cible or {"id": mode.get("cible")}, raison=raison)
    if message:
        flash(message, "error")


def appliquer() -> None:
    """Appelé par auth.load_logged_in_user, une fois la session RÉELLE
    validée (g.user = compte de la session). Pose sur `g` :
    admin_reel, mode_admin, date_simulee, lecture_seule, admin_reel_agit —
    et remplace g.user par le compte vu en « Voir / Agir comme »."""
    g.admin_reel = None
    g.mode_admin = None
    g.date_simulee = None
    g.lecture_seule = False
    g.admin_reel_agit = None
    mode = session.get(CLE_MODE)
    date = session.get(CLE_DATE)
    if mode is None and date is None:
        return
    admin = g.get("user")
    if admin is None or not admin.get("actif") or admin.get("role") != "admin":
        # Plus d'Admin actif derrière la session (déconnecté, désactivé,
        # rôle retiré, clé posée hors d'une session Admin) : rien ne vaut.
        session.pop(CLE_MODE, None)
        session.pop(CLE_DATE, None)
        return

    if date is not None:
        valide = isinstance(date, dict) and date.get("admin") == admin["id"] and lire_date(date.get("date"))
        if valide and mode_test_actif():
            g.date_simulee = valide
        else:
            session.pop(CLE_DATE, None)
            if valide:
                journaliser(TABLE_DATE, "SORTIE", admin["id"], date=date.get("date"), raison="mode_test_coupe")

    if mode is None:
        return
    if (not isinstance(mode, dict) or mode.get("admin") != admin["id"] or mode.get("mode") not in MODES
            or not isinstance(mode.get("cible"), int) or isinstance(mode.get("cible"), bool)):
        session.pop(CLE_MODE, None)
        return
    if mode["mode"] == "agir" and not mode_test_actif():
        _quitter_mode(admin, mode, None, "mode_test_coupe",
                      "Le mode test a été coupé : « Agir comme » n'existe plus, retour à votre compte.")
        return
    from .auth import get_user_by_id

    cible = get_user_by_id(mode["cible"])
    refus = cible_autorisee(cible, admin)
    if refus is not None:
        # Compte désactivé (ou devenu Admin) pendant la session : retour
        # automatique au compte de l'Admin.
        _quitter_mode(admin, mode, cible, "compte_refuse", f"{refus} Retour à votre compte.")
        return

    g.admin_reel = admin
    g.mode_admin = mode["mode"]
    g.user = cible
    if mode["mode"] == "voir":
        g.lecture_seule = request.endpoint not in ENDPOINTS_PERMIS_EN_LECTURE
    else:
        g.admin_reel_agit = admin["id"]


def _veut_json() -> bool:
    from . import API_JSON_PREFIXES

    return (request.path.startswith(API_JSON_PREFIXES) or request.is_json
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or request.accept_mimetypes.best == "application/json")


def reponse_refus(message: str, code: str = "lecture_seule"):
    if _veut_json():
        return {"erreur": code, "message": message}, 403
    return render_template("erreur.html", code=403, titre="Lecture seule" if code == "lecture_seule"
                           else "Action non autorisée", message=message), 403


def refuser_ecriture():
    """before_request (après le chargement de l'utilisateur, avant le
    contrôle CSRF) : en « Voir comme », toute requête qui modifie est
    refusée ; en « Agir comme », le changement de mot de passe."""
    mode = g.get("mode_admin")
    if mode is None or request.method in METHODES_LECTURE:
        return None
    if mode == "voir" and request.endpoint not in ENDPOINTS_PERMIS_EN_LECTURE:
        return reponse_refus(
            f"Vous voyez Kairos comme {nom_complet(g.user)} : lecture seule, rien n'a été modifié. "
            "Revenez à votre compte (bandeau orange) pour agir.")
    if mode == "agir" and request.endpoint in ENDPOINTS_INTERDITS_EN_AGIR:
        return reponse_refus(
            f"Le mot de passe de {nom_complet(g.user)} ne se change pas en « Agir comme ».",
            code="interdit")
    return None


def contexte_gabarits() -> dict:
    """Variables du bandeau Admin (base.html, partials/bandeau_admin.html)."""
    if not g.get("user"):
        return {"bandeau_admin": None}
    admin = g.get("admin_reel") or (g.user if g.user.get("role") == "admin" else None)
    mode_test = mode_test_actif()
    if admin is None or not (g.get("mode_admin") or g.get("date_simulee") or mode_test):
        return {"bandeau_admin": None}
    return {"bandeau_admin": {
        "mode": g.get("mode_admin"),
        "cible": g.user if g.get("mode_admin") else None,
        "role_cible": LIBELLES_ROLE.get(g.user.get("role"), "") if g.get("mode_admin") else "",
        "date_simulee": g.get("date_simulee"),
        "mode_test": mode_test,
        "retour": request.full_path.rstrip("?") if request.method == "GET" else None,
    }}


def installer(app) -> None:
    """Contexte des gabarits et rappel au démarrage (journaux)."""
    app.context_processor(contexte_gabarits)
    if app.config.get("MODE_TEST") is True:
        app.logger.warning(
            "KAIROS_MODE_TEST=true : « Agir comme » et la date simulée sont disponibles pour les Admins. "
            "À couper (KAIROS_MODE_TEST=false) avant la mise en service réelle.")

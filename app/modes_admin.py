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
  l'Admin (et le compte vu ou agi), « aujourd'hui » vaut cette date, avec
  une heure facultative (instant simulé à Tunis, lot 13) — app/horloge.py ;
  en base, réglage kairos.instant_simule lu par fn_aujourdhui au fuseau de
  chacun. Aucune écriture datée après la vraie date (décision 5, lot 13).
- Plusieurs onglets (lot 13, audit temps T-I3) : chaque page porte
  l'empreinte du mode qu'elle affiche (compte, mode, date simulée ;
  <meta name="kairos-mode">) ; static/js/mode-onglets.js la renvoie avec
  chaque écriture (en-tête X-Kairos-Mode ou champ caché _mode) ; si le mode
  a changé entre-temps dans un autre onglet, l'écriture est refusée (409 /
  message) et la page rechargée.

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

from flask import current_app, flash, g, redirect, render_template, request, session, url_for

from .validation import DATE_MAX, DATE_MIN

logger = logging.getLogger(__name__)

CLE_MODE = "mode_admin"      # {"admin": id, "cible": id, "mode": "voir" | "agir"}
CLE_DATE = "date_simulee"    # {"admin": id, "date": "AAAA-MM-JJ", "heure": "HH:MM" (facultatif)}
MODES = ("voir", "agir")
TABLES_JOURNAL = {"voir": "mode_voir_comme", "agir": "mode_agir_comme"}
TABLE_DATE = "date_simulee"

# Toujours permis en « Voir comme » (aucune donnée métier modifiée).
ENDPOINTS_PERMIS_EN_LECTURE = frozenset({
    "modes_admin.revenir", "auth.logout", "mode_test.date_simulee", "mode_test.date_simulee_effacer",
})
# Écritures jamais refusées pour un changement de mode dans un autre onglet :
# connexion, déconnexion, mot de passe oublié, et les changements de mode
# eux-mêmes (choix explicite de l'Admin dans CET onglet). « Simuler le
# rappel du jour » agit sur le compte affiché : contrôlé (contre-expertise
# temps N3).
BLUEPRINTS_SANS_EMPREINTE = frozenset({"auth", "modes_admin"})
ENDPOINTS_SANS_EMPREINTE = frozenset({
    "mode_test.agir_comme", "mode_test.date_simulee", "mode_test.date_simulee_effacer",
})
ENTETE_EMPREINTE = "X-Kairos-Mode"
CHAMP_EMPREINTE = "_mode"
MESSAGE_MODE_CHANGE = ("Le mode a changé dans un autre onglet — page rechargée\u00a0: rien n’a été enregistré. "
                       "Vérifiez le compte et la date affichés, puis recommencez.")
# Jamais permis en « Agir comme » : changer le mot de passe du compte cible
# réécrirait l'empreinte de la session de l'Admin (auth.password_fingerprint).
ENDPOINTS_INTERDITS_EN_AGIR = frozenset({"utilisateurs.mon_mot_de_passe"})
METHODES_LECTURE = frozenset({"GET", "HEAD", "OPTIONS"})

# Bornes de la date simulée : celles des dates plausibles de l'appli
# (une seule paire de constantes, app/validation.py ; garde en base 0014).
DATE_SIMULEE_MIN = DATE_MIN
DATE_SIMULEE_MAX = DATE_MAX

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


def lire_heure(texte) -> datetime.time | None:
    """HH:MM strict (00:00 à 23:59), None sinon (champ vide compris)."""
    if not isinstance(texte, str) or len(texte) != 5 or not texte.isascii() or texte[2] != ":":
        return None
    try:
        return datetime.time.fromisoformat(texte)
    except ValueError:
        return None


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
        if cible is None and isinstance(mode.get("cible"), int):
            # Nom et rôle du compte vu dans le journal, même quand le mode
            # tombe sans l'avoir relu (mode test coupé : audit temps T-M9).
            from .auth import get_user_by_id

            try:
                cible = get_user_by_id(mode["cible"])
            except Exception:
                logger.exception("Compte vu introuvable pour le journal (id=%s)", mode.get("cible"))
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
    g.heure_simulee = None
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
            g.heure_simulee = lire_heure(date.get("heure"))
        else:
            session.pop(CLE_DATE, None)
            if valide:
                journaliser(TABLE_DATE, "SORTIE", admin["id"], date=date.get("date"), raison="mode_test_coupe")
                purger_rappels_simules(admin["id"], mode.get("cible") if isinstance(mode, dict) else None)

    if mode is None:
        return
    if (not isinstance(mode, dict) or mode.get("admin") != admin["id"] or mode.get("mode") not in MODES
            or not isinstance(mode.get("cible"), int) or isinstance(mode.get("cible"), bool)):
        session.pop(CLE_MODE, None)
        return
    if mode["mode"] == "agir" and not mode_test_actif():
        purger_rappels_simules(admin["id"], mode["cible"])
        _quitter_mode(admin, mode, None, "mode_test_coupe",
                      "Le mode test a été coupé\u00a0: «\u00a0Agir comme\u00a0» n’existe plus, retour à votre compte.")
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


def voit_rappels_simules() -> bool:
    """Rappels « [Simulation] » visibles (cloche, badge, liste) seulement
    pendant le test : mode test actif et date simulée (un rappel simulé
    n'existe que sous date simulée), en « Agir comme » ou sur son propre
    compte — jamais en « Voir comme », ni au réel, ni pour la vraie personne
    (contre-expertise temps N1, recette finale F3)."""
    if not mode_test_actif() or g.get("mode_admin") == "voir":
        return False
    return g.get("date_simulee") is not None


def purger_rappels_simules(*user_ids) -> None:
    """Fin d'un test (retour au compte, retour à aujourd'hui, déconnexion,
    mode test coupé) : les rappels simulés des comptes concernés sont
    supprimés (jamais bloquant)."""
    from .repositories import notifications as notifications_repo

    try:
        notifications_repo.purger_rappels_simules(user_ids)
    except Exception:
        logger.exception("Purge des rappels simulés impossible (ids=%s)", user_ids)


def _veut_json() -> bool:
    from . import API_JSON_PREFIXES, partiel

    return (request.path.startswith(API_JSON_PREFIXES) or request.is_json or partiel.est_partiel()
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or request.accept_mimetypes.best == "application/json")


def reponse_refus(message: str, code: str = "lecture_seule"):
    if _veut_json():
        return {"erreur": code, "message": message}, 403
    return render_template("erreur.html", code=403, titre="Lecture seule" if code == "lecture_seule"
                           else "Action non autorisée", message=message), 403


def empreinte_mode() -> str | None:
    """Empreinte de ce que la page affiche : compte (vu, agi ou soi), mode
    et date / heure simulées telles que choisies. None sans utilisateur."""
    user = g.get("user")
    if not user:
        return None
    simulee = g.get("date_simulee")
    heure = g.get("heure_simulee")
    date = "reel" if simulee is None else simulee.isoformat() + (f"T{heure.strftime('%H:%M')}" if heure else "")
    return f"u{user['id']}-{g.get('mode_admin') or 'soi'}-{date}"


def _empreinte_recue() -> tuple[str | None, bool]:
    """(empreinte envoyée par l'onglet, venue par l'en-tête ?) — None si
    l'onglet n'en envoie pas (page sans le script, client hors navigateur)."""
    entete = request.headers.get(ENTETE_EMPREINTE)
    if entete is not None:
        return entete, True
    if request.mimetype in ("application/x-www-form-urlencoded", "multipart/form-data"):
        return request.form.get(CHAMP_EMPREINTE), False
    return None, False


def verifier_empreinte():
    """Écriture envoyée par un onglet qui affiche un autre mode que celui de
    la session (date simulée ou compte changés dans un autre onglet, autre
    compte connecté entre-temps) : refusée avant toute action — 409 JSON
    (en-tête X-Kairos-Mode-Change, le script recharge la page) ou message et
    retour à la page, rechargée."""
    if request.method in METHODES_LECTURE or g.get("user") is None:
        return None
    if (request.blueprint or "") in BLUEPRINTS_SANS_EMPREINTE or request.endpoint in ENDPOINTS_SANS_EMPREINTE:
        return None
    recue, par_entete = _empreinte_recue()
    if recue is None or recue == empreinte_mode():
        return None
    logger.info("Écriture refusée : mode changé dans un autre onglet (%s %s)", request.method, request.path)
    if par_entete or _veut_json():
        return ({"erreur": "mode_change", "message": MESSAGE_MODE_CHANGE}, 409,
                {"X-Kairos-Mode-Change": "1"})
    flash(MESSAGE_MODE_CHANGE, "error")
    from .utils import is_safe_next

    retour = request.referrer or ""
    if retour.startswith(request.host_url):
        retour = "/" + retour[len(request.host_url):]
    return redirect(retour if is_safe_next(retour) else url_for("main.accueil"), code=303)


def refuser_ecriture():
    """before_request (après le chargement de l'utilisateur et le contrôle
    CSRF) : un onglet resté sur un autre mode est refusé
    (verifier_empreinte) ; en « Voir comme », toute requête qui modifie est
    refusée ; en « Agir comme », le changement de mot de passe."""
    refus = verifier_empreinte()
    if refus is not None:
        return refus
    mode = g.get("mode_admin")
    if mode is None or request.method in METHODES_LECTURE:
        return None
    if mode == "voir" and request.endpoint not in ENDPOINTS_PERMIS_EN_LECTURE:
        return reponse_refus(
            f"Vous voyez Kairos comme {nom_complet(g.user)}\u00a0: lecture seule, rien n’a été modifié. "
            "Revenez à votre compte (bandeau orange) pour agir.")
    if mode == "agir" and request.endpoint in ENDPOINTS_INTERDITS_EN_AGIR:
        return reponse_refus(
            f"Le mot de passe de {nom_complet(g.user)} ne se change pas en «\u00a0Agir comme\u00a0».",
            code="interdit")
    return None


def contexte_gabarits() -> dict:
    """Variables du bandeau Admin (base.html, partials/bandeau_admin.html)
    et empreinte du mode affiché (<meta name="kairos-mode">)."""
    if not g.get("user"):
        return {"bandeau_admin": None, "empreinte_mode": None}
    empreinte = empreinte_mode()
    admin = g.get("admin_reel") or (g.user if g.user.get("role") == "admin" else None)
    mode_test = mode_test_actif()
    if admin is None or not (g.get("mode_admin") or g.get("date_simulee") or mode_test):
        return {"bandeau_admin": None, "empreinte_mode": empreinte}
    from . import horloge

    return {"empreinte_mode": empreinte, "bandeau_admin": {
        "mode": g.get("mode_admin"),
        "cible": g.user if g.get("mode_admin") else None,
        "role_cible": LIBELLES_ROLE.get(g.user.get("role"), "") if g.get("mode_admin") else "",
        "date_simulee": g.get("date_simulee"),
        "heure_simulee": g.get("heure_simulee"),
        # Au fuseau du compte affiché (agi ou vu, sinon l'Admin) : un jour
        # simulé n'est « futur » que s'il l'est pour ce compte (Guyane).
        "aujourdhui_reel": horloge.aujourdhui_reel(),
        "aujourdhui_compte": horloge.aujourdhui(),
        "maintenant_compte": horloge.maintenant(),
        "fuseau_compte": horloge._zone(None).key,
        "date_min": DATE_SIMULEE_MIN,
        "date_max": DATE_SIMULEE_MAX,
        "mode_test": mode_test,
        "rappel_simulable": mode_test and g.get("mode_admin") != "voir"
                            and g.user.get("role") in ("admin", "chef_de_projet", "intervenant"),
        "retour": request.full_path.rstrip("?") if request.method == "GET" else None,
    }}


def installer(app) -> None:
    """Contexte des gabarits et rappel au démarrage (journaux)."""
    app.context_processor(contexte_gabarits)
    if app.config.get("MODE_TEST") is True:
        app.logger.warning(
            "KAIROS_MODE_TEST=true\u00a0: «\u00a0Agir comme\u00a0» et la date simulée sont disponibles pour les Admins. "
            "À couper (KAIROS_MODE_TEST=false) avant la mise en service réelle.")

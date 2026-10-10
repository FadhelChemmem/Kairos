"""Mises à jour partielles (lot 13) : contrat serveur de kairos-partiel.js.

Une requête envoyée par la brique cliente porte l'en-tête
« X-Kairos-Partiel: <cible> » (sélecteur de l'élément à remplacer). La route
répond alors par un FRAGMENT HTML (gabarit partiel) au lieu de la page
entière, et les messages passent dans l'en-tête « X-Kairos-Toasts » (JSON
encodé en pourcents) au lieu de flash(). Sans JavaScript, la même route
garde son comportement habituel (POST puis redirection) : chaque route
convertie ajoute seulement, en tête de sa réponse :

    if partiel.est_partiel():
        return partiel.repondre("partials/….html", toasts=[partiel.toast("…")], …)

Codes de réponse attendus par le client :
- 2xx : fragment remplacé ; 204 + X-Kairos-Redirection : vraie navigation ;
- 422 : fragment re-rendu avec les champs en erreur (repondre(statut=422)) ;
- 401 : session expirée (X-Kairos-Connexion = page de connexion) ;
- 403 / 409 / 4xx : JSON {"erreur", "message"} (refuser()) — l'état
  optimiste est annulé et le message affiché en toast.

installer() adapte les réponses que la route n'a pas converties : une
redirection (route encore en PRG) devient 204 + X-Kairos-Redirection (les
messages flash restent en session pour la page d'arrivée), la redirection
vers la connexion devient 401 ; voir aussi app/__init__.py (pages d'erreur
en JSON pour une requête partielle). Mode d'emploi : docs/partiel.md.
"""
import json
from urllib.parse import quote, urlsplit

from flask import g, get_flashed_messages, jsonify, make_response, render_template, request, url_for

ENTETE_PARTIEL = "X-Kairos-Partiel"
ENTETE_TOASTS = "X-Kairos-Toasts"
ENTETE_FRAGMENT = "X-Kairos-Fragment"
ENTETE_CONNEXION = "X-Kairos-Connexion"
ENTETE_REDIRECTION = "X-Kairos-Redirection"

# Catégories de flash() de l'appli -> types de toast.
TYPES_FLASH = {"success": "succes", "error": "erreur", "warning": "avertissement"}
TYPES = ("succes", "erreur", "avertissement", "info")

MESSAGE_SESSION = "Votre session a expiré\u00a0: reconnectez-vous pour continuer."


def est_partiel() -> str | None:
    """Cible demandée par kairos-partiel.js (« #utilisateurs-resultats »), ou
    None pour une requête classique (navigation, formulaire sans JS)."""
    if not request:
        return None
    cible = request.headers.get(ENTETE_PARTIEL)
    return cible.strip() or None if cible else None


def toast(texte: str, type: str = "succes", action: dict | None = None) -> dict:
    """Un message pour la zone de toasts. `action` (facultative) : bouton du
    toast, ex. {"libelle": "Annuler", "url": "/…", "methode": "POST",
    "donnees": {...}, "cible": "#u-40"} — rejoué en requête partielle."""
    t = {"type": type if type in TYPES else "info", "texte": str(texte)}
    if action:
        t["action"] = action
    return t


def lire_flash() -> list[tuple[str, str]]:
    """Messages flash() en attente, (catégorie, texte), retirés de la session
    — une seule fois par requête (Flask garde la liste lue en cache : un
    second appel les rendrait en double)."""
    if g.get("_kairos_flash_lus"):
        return []
    g._kairos_flash_lus = True
    return list(get_flashed_messages(with_categories=True))


def toasts_flash() -> list[dict]:
    """Messages flash() en attente, convertis en toasts (ils ne réapparaissent
    pas à la page suivante)."""
    return [toast(m, TYPES_FLASH.get(c, "info")) for c, m in lire_flash()]


def encoder_toasts(toasts: list[dict]) -> str:
    return quote(json.dumps(toasts, ensure_ascii=False), safe="")


def _poser_toasts(reponse, toasts: list[dict] | None) -> None:
    msgs = list(toasts or []) + toasts_flash()
    if msgs:
        reponse.headers[ENTETE_TOASTS] = encoder_toasts(msgs)


def _entetes_communs(reponse) -> None:
    reponse.headers["Cache-Control"] = "no-store"
    reponse.vary.add(ENTETE_PARTIEL)
    reponse.vary.add("Cookie")


def repondre(gabarit_fragment: str, *, statut: int = 200, toasts: list[dict] | None = None, **contexte):
    """Rend le fragment et transporte les messages en en-tête (toasts
    explicites + flash() en attente)."""
    reponse = make_response(render_template(gabarit_fragment, **contexte), statut)
    _poser_toasts(reponse, toasts)
    reponse.headers[ENTETE_FRAGMENT] = gabarit_fragment
    _entetes_communs(reponse)
    return reponse


def rien(toasts: list[dict] | None = None):
    """204 : rien à remplacer dans la page, seulement des toasts (lot 13 :
    post publié depuis une page qui n'affiche pas ce fil)."""
    reponse = make_response("", 204)
    _poser_toasts(reponse, toasts)
    _entetes_communs(reponse)
    return reponse


def refuser(message: str, statut: int = 403, *, erreur: str | None = None, toasts: list[dict] | None = None,
            champs: dict | None = None):
    """Refus (droit, lecture seule, conflit, requête invalide) : JSON
    {"erreur", "message"} ; le client annule l'état optimiste et affiche le
    message. Les flash() en attente partent avec (en-tête).
    `champs` (422) : {nom du champ: message} — le client signale ces champs
    dans le formulaire envoyé (aria-invalid, message relié, focus sur le
    premier) et garde la saisie."""
    codes = {400: "requete_invalide", 403: "interdit", 404: "introuvable", 409: "conflit", 422: "invalide"}
    corps = {"erreur": erreur or codes.get(statut, "refus"), "message": message}
    if champs:
        corps["champs"] = champs
    reponse = make_response(jsonify(corps), statut)
    _poser_toasts(reponse, toasts)
    _entetes_communs(reponse)
    return reponse


def conflit(message: str, **kw):
    return refuser(message, 409, **kw)


def url_connexion() -> str:
    """Page de connexion avec retour à la page affichée (Referer interne),
    à défaut à l'adresse demandée."""
    retour = None
    ref = request.referrer
    if ref:
        parts = urlsplit(ref)
        if not parts.netloc or parts.netloc == request.host:
            retour = parts.path + (f"?{parts.query}" if parts.query else "")
    from .utils import is_safe_next

    if not is_safe_next(retour):
        retour = request.path
    return url_for("auth.login", next=retour)


def session_expiree():
    reponse = make_response(jsonify({"erreur": "non_connecte", "message": MESSAGE_SESSION}), 401)
    reponse.headers[ENTETE_CONNEXION] = url_connexion()
    _entetes_communs(reponse)
    return reponse


def _adapter(reponse):
    """after_request : une requête partielle ne reçoit jamais une
    redirection (fetch la suivrait sans rien dire)."""
    if not est_partiel() or request.endpoint == "static":
        return reponse
    if 300 <= reponse.status_code < 400 and reponse.location:
        # login_required renvoie vers la connexion (session absente, expirée
        # ou compte désactivé) : 401, la saisie reste dans la page.
        if urlsplit(reponse.location).path == url_for("auth.login"):
            return session_expiree()
        # Route encore en PRG : le client fait une vraie navigation ; les
        # flash() restent en session pour la page d'arrivée (le cookie de
        # session est posé ensuite, sur cette nouvelle réponse).
        nouvelle = make_response("", 204)
        nouvelle.headers[ENTETE_REDIRECTION] = reponse.location
        _entetes_communs(nouvelle)
        return nouvelle
    return reponse


def installer(app) -> None:
    """À enregistrer APRÈS les autres after_request (Flask les exécute en
    ordre inverse) : la réponse adaptée reçoit ensuite les en-têtes de
    sécurité et la compression."""
    app.after_request(_adapter)

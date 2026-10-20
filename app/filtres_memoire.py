"""Filtres mémorisés par personne (lot 23, décision du gérant du 20/10).

« Tous les projets », « Équipe » et le « Journal d'audit » rouvrent sur le
dernier choix de filtres de la personne — par le menu, un nouvel onglet,
un autre PC. Mémorisé en base (utilisateur_preference.filtres, migration
0026), une chaîne de requête par page, seulement pour les clés de filtre
de cette page (jamais la recherche texte ni la pagination).

Seul un choix fait à l'écran est mémorisé : une requête partielle (filtre
automatique), ou le bouton « Filtrer » sans JavaScript (`choix=1`). Un
ancien onglet rechargé (adresse complète, GET normal) n'écrase rien. En
« Voir comme » (lecture seule), rien n'est écrit. `?defaut=1` oublie le
choix de la page.
"""
from urllib.parse import parse_qsl, urlencode

from flask import current_app, g, request
from werkzeug.datastructures import MultiDict

from . import partiel
from .repositories import utilisateurs as utilisateurs_repo

CLES = {
    # « filtres_actifs » : marqueur « formulaire soumis » de la liste des
    # projets (groupe vidé volontairement ≠ valeurs par défaut).
    "projets": ("filtres_actifs", "etat", "phase", "chef_id", "lot_contient", "lot_egal"),
    "equipe": ("equipe_code", "role", "actif"),
    "journal": ("table", "action", "utilisateur_id"),
}
MAX_LONGUEUR = 3000


def demande_explicite(page: str) -> bool:
    """L'adresse porte un choix de filtres pour cette page."""
    marqueurs = ("filtres_actifs",) if page == "projets" else CLES[page]
    return any(cle in request.args for cle in marqueurs)


def source(page: str):
    """Les filtres à appliquer : ceux de l'adresse, sinon le choix
    mémorisé de la personne, sinon None (valeurs par défaut). Sur
    `?defaut=1` : le choix est oublié. Une requête partielle (Retour du
    navigateur, filtre automatique) suit toujours son adresse : sans
    filtre dans l'adresse, aucun filtre."""
    if request.args.get("defaut"):
        oublier(page)
        return None
    if demande_explicite(page) or partiel.est_partiel():
        return request.args if demande_explicite(page) else None
    return memorises(page)


def memorises(page: str):
    brut = _lire(page)
    if not brut:
        return None
    valeurs = MultiDict([(k, v) for k, v in parse_qsl(brut, keep_blank_values=True) if k in CLES[page]])
    return valeurs or None


def redirection(page: str, endpoint: str, **extra):
    """Page complète ouverte sans filtre dans l'adresse (menu, nouvel
    onglet) : redirige vers l'adresse du choix mémorisé — l'historique
    garde des adresses explicites (Retour fiable). None sinon."""
    from flask import redirect, url_for

    if request.args.get("defaut") or demande_explicite(page) or partiel.est_partiel():
        return None
    valeurs = memorises(page)
    if not valeurs:
        return None
    params = {k: valeurs.getlist(k) for k in valeurs}
    params.update({k: v for k, v in extra.items() if v})
    return redirect(url_for(endpoint, **params))


def memoriser(page: str, valeurs: dict) -> None:
    """Retient le choix affiché (`valeurs` : clé -> valeur ou liste), s'il
    vient d'un geste à l'écran."""
    if not (partiel.est_partiel() or request.args.get("choix")) or not demande_explicite(page):
        return
    paires = []
    for cle in CLES[page]:
        brut = valeurs.get(cle)
        for x in (brut if isinstance(brut, (list, tuple)) else [brut]):
            if x is not None and x != "":
                paires.append((cle, str(x)))
    texte = urlencode(paires)
    if len(texte) <= MAX_LONGUEUR:
        _ecrire(page, texte)


def oublier(page: str) -> None:
    _ecrire(page, None)


def _lire(page: str) -> str | None:
    try:
        return utilisateurs_repo.get_filtres(g.user["id"], page)
    except Exception:
        current_app.logger.exception("Filtres mémorisés illisibles (%s)", page)
        return None


def _ecrire(page: str, valeur: str | None) -> None:
    if g.get("lecture_seule"):
        return
    try:
        utilisateurs_repo.set_filtres(g.user["id"], page, valeur)
    except Exception:
        current_app.logger.exception("Filtres non mémorisés (%s)", page)

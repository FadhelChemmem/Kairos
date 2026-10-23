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

Lot 24 (contre-expertise FI, décisions du 20/10) :
- marqueur `filtres_actifs` aussi sur Équipe et Journal : remettre toutes
  les listes à « Tous » est un choix, retenu comme tel (FI-01) ;
- Retour / Avancer (en-tête X-Kairos-Historique) et F5 (`choix=1` retiré de
  l'adresse par kairos-partiel.js) ne sont pas des gestes (FI-04, FI-09) ;
- rien n'est écrit en « Agir comme » (seulement lu) ;
- à la lecture : valeurs trop longues ou avec caractères de contrôle
  ignorées, clés inconnues jetées (FI-06, FI-07) ;
- la redirection garde la recherche, les dates et la pagination du Journal
  (FI-05), et n'a pas lieu si l'adresse serait trop longue.
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
    "equipe": ("filtres_actifs", "equipe_code", "role", "actif"),
    "journal": ("filtres_actifs", "table", "action", "utilisateur_id"),
}
MAX_LONGUEUR = 1000
MAX_ADRESSE = 2000


def demande_explicite(page: str) -> bool:
    """L'adresse porte un choix de filtres pour cette page."""
    marqueurs = ("filtres_actifs",) if page == "projets" else CLES[page]
    return any(cle in request.args for cle in marqueurs)


def geste() -> bool:
    """La requête vient d'un geste à l'écran : filtre automatique (partiel,
    hors Retour / Avancer) ou « Filtrer » sans JavaScript (`choix=1`)."""
    if request.method != "GET":
        return False
    if partiel.est_partiel():
        return request.headers.get("X-Kairos-Historique") != "1"
    return bool(request.args.get("choix"))


def source(page: str, *, oubli_permis: bool = True):
    """Les filtres à appliquer : ceux de l'adresse, sinon le choix
    mémorisé de la personne, sinon None (valeurs par défaut). Sur
    `?defaut=1` : le choix est oublié (sauf `oubli_permis` faux : export).
    Une requête partielle (Retour du navigateur, filtre automatique) suit
    toujours son adresse : sans filtre dans l'adresse, aucun filtre."""
    if request.args.get("defaut"):
        if oubli_permis and (geste() or not partiel.est_partiel()):
            oublier(page)
        return None
    if demande_explicite(page) or partiel.est_partiel():
        return request.args if demande_explicite(page) else None
    return memorises(page)


def memorises(page: str):
    brut = _lire(page)
    if not brut or len(brut) > MAX_LONGUEUR:
        return None
    valeurs = MultiDict([(k, v) for k, v in parse_qsl(brut, keep_blank_values=True)
                         if k in CLES[page] and len(v) <= 200 and v.isprintable()])
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
    adresse = url_for(endpoint, **params)
    if len(adresse) > MAX_ADRESSE:
        return None
    return redirect(adresse)


def memoriser(page: str, valeurs: dict) -> None:
    """Retient le choix affiché (`valeurs` : clé -> valeur ou liste), s'il
    vient d'un geste à l'écran."""
    if not geste() or not demande_explicite(page):
        return
    paires = []
    for cle in CLES[page]:
        brut = valeurs.get(cle)
        for x in (brut if isinstance(brut, (list, tuple)) else [brut]):
            if x is not None and x != "":
                paires.append((cle, str(x)))
    if page != "projets" and all(cle == "filtres_actifs" for cle, _ in paires):
        # Équipe / Journal : toutes les listes sur « Tous » = les valeurs
        # par défaut — le choix est oublié (le menu rouvre la page nue).
        _ecrire(page, None)
        return
    texte = urlencode(paires)
    if len(texte) <= MAX_LONGUEUR:
        _ecrire(page, texte)


def apres_geste_sans_js():
    """Lot 25 (SB-07) : « Filtrer » sans JavaScript (`choix=1`) — une fois
    le choix mémorisé, redirection (303) vers la même adresse sans `choix` :
    un F5 ne refait plus le geste (il écrasait un choix fait ailleurs).
    Lot 25 (UT-04) : de même pour `defaut=1` (« Effacer les filtres »,
    « Réinitialiser ») — un F5 n'oublie plus un choix fait entre-temps.
    None sinon (avec JavaScript, kairos-partiel.js retire `choix` et
    `defaut` de l'adresse)."""
    from flask import redirect

    if (request.method != "GET" or partiel.est_partiel()
            or not (request.args.get("choix") or request.args.get("defaut"))):
        return None
    params = [(k, v) for k, v in request.args.items(multi=True) if k not in ("choix", "defaut")]
    return redirect(request.path + ("?" + urlencode(params) if params else ""), code=303)


def oublier(page: str) -> None:
    _ecrire(page, None)


def lire(page: str) -> str | None:
    """Choix mémorisé brut d'une page (lot 25, revue RS C.2-8 : lecture
    publique pour fil.py)."""
    return _lire(page)


def _lire(page: str) -> str | None:
    try:
        return utilisateurs_repo.get_filtres(g.user["id"], page)
    except Exception:
        current_app.logger.exception("Filtres mémorisés illisibles (%s)", page)
        return None


def _ecrire(page: str, valeur: str | None) -> None:
    # « Voir comme » : lecture seule ; « Agir comme » (lot 24) : la personne
    # retrouve ses filtres, l'Admin ne les change pas.
    if g.get("lecture_seule") or g.get("admin_reel"):
        return
    try:
        utilisateurs_repo.set_filtres(g.user["id"], page, valeur)
    except Exception:
        current_app.logger.exception("Filtres non mémorisés (%s)", page)

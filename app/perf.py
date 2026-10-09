"""Performance HTTP (lot 11, audit front I1) : compression gzip des
réponses textuelles et cache long des fichiers statiques versionnés.

- **Compression** : HTML, JSON, CSS et JavaScript de plus de 1 Ko sont
  compressés en gzip (bibliothèque standard) quand le navigateur l'accepte
  (« Accept-Encoding: gzip »). Jamais pour une réponse en streaming ni pour
  un fichier téléchargé (pièces jointes, avatars) ; les feuilles de style
  et scripts de /static sont compressés une fois puis gardés en mémoire.
  Désactivable par COMPRESSION_GZIP=false quand le reverse proxy compresse
  déjà (voir README).
- **Statiques versionnés** : toute URL produite par
  url_for('static', filename=...) porte l'empreinte du fichier
  (« ?v=<sha256 tronqué> ») ; une requête qui présente l'empreinte
  courante reçoit « Cache-Control: public, max-age=31536000, immutable »
  (aucune revalidation, plus de 304 à chaque page). Un fichier modifié
  change d'empreinte, donc d'URL : pas de cache périmé après un
  déploiement. Les pages HTML gardent leur propre politique (no-store).
"""
import datetime
import gzip
import hashlib
import os
import threading

from flask import request
from werkzeug.security import safe_join

TYPES_COMPRESSIBLES = {
    "text/html", "application/json", "text/css",
    "application/javascript", "text/javascript", "image/svg+xml",
}
TAILLE_MIN = 1024
NIVEAU = 6
DUREE_CACHE_STATIQUE = 31536000
CACHE_STATIQUE = f"public, max-age={DUREE_CACHE_STATIQUE}, immutable"

_verrou = threading.Lock()
# chemin absolu -> (mtime_ns, taille, empreinte)
_empreintes: dict[str, tuple[int, int, str]] = {}
# (chemin absolu, mtime_ns, taille) -> corps gzip
_gzip_statiques: dict[tuple[str, int, int], bytes] = {}


def _chemin_statique(app, filename: str) -> str | None:
    if not filename or not app.static_folder:
        return None
    chemin = safe_join(app.static_folder, filename)
    if chemin is None or not os.path.isfile(chemin):
        return None
    return chemin


def empreinte(app, filename: str) -> str | None:
    """Empreinte (12 caractères hexadécimaux du SHA-256) du fichier statique,
    recalculée seulement s'il a changé (date ou taille) — un stat() par
    appel, négligeable devant le rendu d'une page."""
    chemin = _chemin_statique(app, filename)
    if chemin is None:
        return None
    st = os.stat(chemin)
    connu = _empreintes.get(chemin)
    if connu and connu[0] == st.st_mtime_ns and connu[1] == st.st_size:
        return connu[2]
    with open(chemin, "rb") as f:
        valeur = hashlib.sha256(f.read()).hexdigest()[:12]
    with _verrou:
        _empreintes[chemin] = (st.st_mtime_ns, st.st_size, valeur)
    return valeur


def _gzip_statique(app, filename: str) -> bytes | None:
    chemin = _chemin_statique(app, filename)
    if chemin is None:
        return None
    st = os.stat(chemin)
    cle = (chemin, st.st_mtime_ns, st.st_size)
    corps = _gzip_statiques.get(cle)
    if corps is None:
        with open(chemin, "rb") as f:
            corps = gzip.compress(f.read(), compresslevel=9, mtime=0)
        with _verrou:
            # Une seule version par fichier : l'ancienne part avec la nouvelle.
            for ancienne in [k for k in _gzip_statiques if k[0] == chemin]:
                del _gzip_statiques[ancienne]
            _gzip_statiques[cle] = corps
    return corps


def _accepte_gzip() -> bool:
    for morceau in request.headers.get("Accept-Encoding", "").lower().split(","):
        nom, _, params = morceau.strip().partition(";")
        if nom.strip() in ("gzip", "*"):
            q = params.strip()
            if q.startswith("q="):
                try:
                    return float(q[2:]) > 0
                except ValueError:
                    return False
            return True
    return False


def _ajouter_vary(response) -> None:
    if "accept-encoding" not in {v.strip().lower() for v in response.headers.get("Vary", "").split(",")}:
        response.vary.add("Accept-Encoding")


def _compresser(app, response):
    if response.status_code < 200 or response.status_code in (204, 206, 304):
        return response
    if response.mimetype not in TYPES_COMPRESSIBLES:
        return response
    if "Content-Encoding" in response.headers or "Content-Range" in response.headers:
        return response
    statique = request.endpoint == "static"
    if not statique and (response.direct_passthrough or response.is_streamed):
        # Fichier envoyé tel quel (pièce jointe, export) ou flux : jamais.
        return response
    if statique:
        taille = response.content_length or 0
        if taille < TAILLE_MIN or request.method != "GET":
            return response
        _ajouter_vary(response)
        if not _accepte_gzip():
            return response
        corps = _gzip_statique(app, request.view_args.get("filename", "") if request.view_args else "")
        if corps is None:
            return response
        fermer = getattr(response.response, "close", None)
        if fermer:
            fermer()
        response.direct_passthrough = False
        response.set_data(corps)
    else:
        donnees = response.get_data()
        if len(donnees) < TAILLE_MIN:
            return response
        _ajouter_vary(response)
        if not _accepte_gzip():
            return response
        response.set_data(gzip.compress(donnees, compresslevel=NIVEAU))
    response.headers["Content-Encoding"] = "gzip"
    # Même contenu, autre encodage : ETag faible (comme Nginx), la
    # revalidation « If-None-Match » reste valable pour les deux versions.
    etag, faible = response.get_etag()
    if etag and not faible:
        response.set_etag(etag, weak=True)
    return response


def installer(app) -> None:
    @app.url_defaults
    def _versionner_statiques(endpoint, values):
        if endpoint == "static" and "v" not in values:
            v = empreinte(app, values.get("filename", ""))
            if v:
                values["v"] = v

    @app.after_request
    def _cache_et_compression(response):
        if request.endpoint == "static" and response.status_code in (200, 304):
            filename = (request.view_args or {}).get("filename", "")
            v = request.args.get("v")
            if v and v == empreinte(app, filename):
                response.headers["Cache-Control"] = CACHE_STATIQUE
                # Expires aligné sur max-age (audit a11y-perf M14) : affecter
                # None le posait à l'instant présent (déjà expiré).
                response.expires = (datetime.datetime.now(datetime.timezone.utc)
                                    + datetime.timedelta(seconds=DUREE_CACHE_STATIQUE))
        if app.config.get("COMPRESSION_GZIP", True):
            response = _compresser(app, response)
        return response

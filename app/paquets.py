"""Paquets statiques (lot 13, audit a11y-perf N9 et R5) : moins de requêtes
et moins d'octets au premier chargement, sans outil de construction.

- **`commun.js`** : les scripts différés chargés par TOUTES les pages
  connectées (base.html), assemblés dans l'ordre en un seul fichier — 8
  requêtes de moins par page (Kairos est servi sans HTTP/2).
- **`app.css`** : la feuille de style commune, sans ses commentaires (un
  tiers du poids compressé : 35 → 22 Ko gzip) — elle bloque le premier
  rendu.

Les sources restent les fichiers de app/static (seuls à éditer). Le paquet
est assemblé en mémoire à la première demande, puis de nouveau dès qu'une
source change (date ou taille) ; son URL porte l'empreinte du contenu
(« ?v= »), servie en cache d'un an « immutable » comme les autres
statiques (perf.py), gzip compris. Commentaires retirés : CSS, tous (hors
chaînes) ; JavaScript, seulement les lignes de commentaire entières (`//`
ou bloc `/* … */` ouvert en début de ligne), jamais à l'intérieur d'une
ligne de code.
"""
import gzip
import hashlib
import os
import re
import threading

from flask import Response, abort, request, url_for

PAQUETS: dict[str, tuple[str, ...]] = {
    # Même ordre que les <script defer> qu'il remplace : kairos-partiel.js
    # d'abord (socle), texte-recherche.js avant chip-select et search-combobox.
    "commun.js": (
        "js/kairos-partiel.js",
        "js/texte-recherche.js",
        "js/chip-select.js",
        "js/search-combobox.js",
        "js/kairos-ui.js",
        "js/recherche-globale.js",
        "js/raccourcis.js",
        "js/notifications.js",
    ),
    "app.css": ("css/app.css", "css/lot13-pages.css", "css/lot14-a2.css", "css/lot14-a3.css",
                "css/lot13-visuel.css", "css/lot14-a1.css", "css/lot14-a4.css"),
}
TYPES = {".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
CACHE_LONG = "public, max-age=31536000, immutable"

_verrou = threading.Lock()
# nom -> (signature des sources, corps, corps gzip, empreinte)
_cache: dict[str, tuple[tuple, bytes, bytes, str]] = {}


def sans_commentaires_css(texte: str) -> str:
    """Retire les commentaires /* … */ (jamais dans une chaîne) et les
    lignes vides."""
    sortie, i, n = [], 0, len(texte)
    while i < n:
        c = texte[i]
        if c in "\"'":
            fin = i + 1
            while fin < n and texte[fin] != c:
                fin += 2 if texte[fin] == "\\" else 1
            sortie.append(texte[i:fin + 1])
            i = fin + 1
        elif texte.startswith("/*", i):
            fin = texte.find("*/", i + 2)
            i = n if fin == -1 else fin + 2
        else:
            sortie.append(c)
            i += 1
    return _sans_lignes_vides("".join(sortie))


_BLOC_JS = re.compile(r"^[ \t]*/\*(?:(?!\*/).)*\*/[ \t]*$", re.S | re.M)
_LIGNE_JS = re.compile(r"^[ \t]*//.*$", re.M)


def sans_commentaires_js(texte: str) -> str:
    """Retire les commentaires qui occupent des lignes entières (ligne `//`,
    bloc `/* … */` commencé en début de ligne et fini en fin de ligne)."""
    return _sans_lignes_vides(_LIGNE_JS.sub("", _BLOC_JS.sub("", texte)))


def _sans_lignes_vides(texte: str) -> str:
    return "\n".join(ligne.rstrip() for ligne in texte.splitlines() if ligne.strip()) + "\n"


def _sources(app, nom: str) -> list[str]:
    return [os.path.join(app.static_folder, chemin) for chemin in PAQUETS[nom]]


def assembler(app, nom: str) -> tuple[bytes, bytes, str]:
    """(corps, corps gzip, empreinte) du paquet, recalculés si une source a
    changé."""
    chemins = _sources(app, nom)
    signature = tuple((os.stat(c).st_mtime_ns, os.stat(c).st_size) for c in chemins)
    connu = _cache.get(nom)
    if connu and connu[0] == signature:
        return connu[1], connu[2], connu[3]
    morceaux = []
    for relatif, chemin in zip(PAQUETS[nom], chemins):
        with open(chemin, encoding="utf-8") as f:
            texte = f.read()
        if nom.endswith(".css"):
            morceaux.append(sans_commentaires_css(texte))
        else:
            # « ; » : un fichier sans point-virgule final ne se colle pas au suivant.
            morceaux.append(f"/* {relatif} */\n" + sans_commentaires_js(texte) + ";\n")
    corps = "".join(morceaux).encode("utf-8")
    empreinte = hashlib.sha256(corps).hexdigest()[:12]
    zippe = gzip.compress(corps, compresslevel=9, mtime=0)
    with _verrou:
        _cache[nom] = (signature, corps, zippe, empreinte)
    return corps, zippe, empreinte


def _accepte_gzip() -> bool:
    from .perf import _accepte_gzip as accepte
    return accepte()


def installer(app) -> None:
    @app.route("/static/paquets/<nom>", endpoint="paquet")
    def paquet(nom):
        if nom not in PAQUETS:
            abort(404)
        corps, zippe, empreinte = assembler(app, nom)
        if request.if_none_match.contains(empreinte):
            reponse = Response(status=304)
        elif _accepte_gzip():
            reponse = Response(zippe, headers={"Content-Encoding": "gzip"})
        else:
            reponse = Response(corps)
        reponse.headers["Content-Type"] = TYPES[os.path.splitext(nom)[1]]
        reponse.set_etag(empreinte)
        reponse.vary.add("Accept-Encoding")
        reponse.headers["Cache-Control"] = CACHE_LONG if request.args.get("v") == empreinte else "no-cache"
        return reponse

    def paquet_url(nom: str) -> str:
        return url_for("paquet", nom=nom, v=assembler(app, nom)[2])

    app.jinja_env.globals["paquet_url"] = paquet_url

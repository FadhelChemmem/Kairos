"""Reverse proxy de confiance (décision du gérant, fin du lot 10).

Derrière un reverse proxy (Nginx Proxy Manager sur le même serveur), sans
lecture des en-têtes X-Forwarded-*, request.remote_addr vaut l'IP du proxy
pour TOUS les utilisateurs : le limiteur de connexion (auth.py) finissait
par bloquer tout le monde, et le schéma (https) vu par l'appli était faux.
Mais ces en-têtes sont écrits par le client : les croire sur une requête
qui n'arrive PAS du proxy permettrait à n'importe qui sur le LAN de choisir
son « IP » à chaque essai de mot de passe (audit sécurité I8).

Règle : les en-têtes X-Forwarded-* ne sont pris en compte (ProxyFix, avec
TRUSTED_PROXY_COUNT sauts) QUE si l'adresse TCP directe de la requête
(REMOTE_ADDR avant ProxyFix) appartient à TRUSTED_PROXY_IPS. Sinon ils sont
retirés de la requête (personne en aval ne peut les lire par erreur) et un
avertissement est journalisé une fois par adresse, avec l'IP vue, pour
savoir quoi ajouter à TRUSTED_PROXY_IPS.
"""
import ipaddress
import logging
import threading

from werkzeug.middleware.proxy_fix import ProxyFix

logger = logging.getLogger("app.proxy")

# Défaut sûr quand TRUSTED_PROXY_IPS est vide et que le port 8000 est
# publié sur le LAN : réseaux privés de Docker (le proxy en conteneur, ou
# la passerelle du réseau Docker pour un proxy de l'hôte) et la machine
# elle-même. Une adresse du LAN (192.168.x.x) n'en fait pas partie.
RESEAUX_PAR_DEFAUT = ("172.16.0.0/12", "127.0.0.1/32", "::1/128")

_ADRESSES_LOCALES = {"127.0.0.1", "localhost", "::1", "[::1]"}

ENTETES_TRANSFERT = (
    "HTTP_X_FORWARDED_FOR", "HTTP_X_FORWARDED_PROTO", "HTTP_X_FORWARDED_HOST",
    "HTTP_X_FORWARDED_PORT", "HTTP_X_FORWARDED_PREFIX",
)

# Borne du nombre d'adresses déjà signalées (mémoire d'un worker).
_MAX_ADRESSES_SIGNALEES = 1000


def analyser_reseaux(valeur: str) -> tuple[list, list[str]]:
    """« 172.16.0.0/12, 192.168.100.17 » -> (réseaux, entrées invalides).
    Une IP seule vaut un réseau d'une adresse ; espaces et entrées vides
    ignorés."""
    reseaux, invalides = [], []
    for brut in (valeur or "").split(","):
        entree = brut.strip()
        if not entree:
            continue
        try:
            reseaux.append(ipaddress.ip_network(entree, strict=False))
        except ValueError:
            invalides.append(entree)
    return reseaux, invalides


def reseaux_de_confiance(config: dict) -> tuple[list, str]:
    """Réseaux dont les en-têtes X-Forwarded-* sont crus, et d'où vient la
    liste (pour le journal de démarrage) : TRUSTED_PROXY_IPS s'il est
    renseigné, sinon RESEAUX_PAR_DEFAUT + HOST_IP s'il est fourni. Avec
    WEB_BIND=127.0.0.1, un proxy de l'hôte arrive par la passerelle du
    réseau Docker (172.x.0.1) : couvert par ce défaut."""
    reseaux, invalides = analyser_reseaux(config.get("TRUSTED_PROXY_IPS") or "")
    for entree in invalides:
        logger.error("TRUSTED_PROXY_IPS : « %s » n'est ni une IP ni un réseau (ex. 172.16.0.0/12) : ignoré.",
                     entree)
    if reseaux:
        return reseaux, "TRUSTED_PROXY_IPS"
    defaut, _ = analyser_reseaux(",".join(RESEAUX_PAR_DEFAUT))
    hote, invalides = analyser_reseaux(config.get("HOST_IP") or "")
    for entree in invalides:
        logger.error("HOST_IP : « %s » n'est pas une adresse IP : ignorée.", entree)
    return defaut + hote, "défaut"


def _decrire(reseaux: list) -> str:
    return ", ".join(str(r) for r in reseaux) or "aucune adresse"


class ProxyDeConfiance:
    """Middleware WSGI : ProxyFix pour les requêtes venues d'un proxy de
    confiance, en-têtes X-Forwarded-* retirés pour toutes les autres."""

    def __init__(self, wsgi_app, nb_proxys: int, reseaux: list):
        self.app = wsgi_app
        self.avec_proxy = ProxyFix(wsgi_app, x_for=nb_proxys, x_proto=nb_proxys,
                                   x_host=nb_proxys, x_port=nb_proxys)
        self.reseaux = reseaux
        self._signalees: set[str] = set()
        self._verrou = threading.Lock()

    def est_de_confiance(self, adresse: str) -> bool:
        try:
            ip = ipaddress.ip_address((adresse or "").strip("[]"))
        except ValueError:
            return False
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        return any(ip in reseau for reseau in self.reseaux if reseau.version == ip.version)

    def _signaler(self, adresse: str) -> None:
        with self._verrou:
            if adresse in self._signalees or len(self._signalees) >= _MAX_ADRESSES_SIGNALEES:
                return
            self._signalees.add(adresse)
        logger.warning(
            "En-têtes X-Forwarded-* ignorés : requête reçue directement de %s, adresse absente "
            "de TRUSTED_PROXY_IPS (%s). Si %s est l'adresse de votre reverse proxy, ajoutez-la à "
            "TRUSTED_PROXY_IPS dans .env puis relancez `docker compose up -d` ; sinon, quelqu'un "
            "contourne le proxy (message affiché une fois par adresse).",
            adresse or "?", _decrire(self.reseaux), adresse or "?",
        )

    def __call__(self, environ, start_response):
        adresse = environ.get("REMOTE_ADDR", "")
        if self.est_de_confiance(adresse):
            return self.avec_proxy(environ, start_response)
        presents = [h for h in ENTETES_TRANSFERT if h in environ]
        if presents:
            self._signaler(adresse)
            for entete in presents:
                del environ[entete]
        return self.app(environ, start_response)


def installer(app) -> None:
    """Branche ProxyDeConfiance si TRUSTED_PROXY_COUNT > 0 et journalise le
    réglage retenu (visible dans `docker compose logs web`). Ne refuse
    jamais de démarrer."""
    nb_proxys = app.config.get("TRUSTED_PROXY_COUNT", 0) or 0
    if not nb_proxys:
        if (app.config.get("TRUSTED_PROXY_IPS") or "").strip():
            logger.warning("TRUSTED_PROXY_IPS est renseigné mais TRUSTED_PROXY_COUNT=0 : les en-têtes "
                           "X-Forwarded-* restent ignorés. Mettez TRUSTED_PROXY_COUNT=1 derrière un proxy.")
        return
    reseaux, origine = reseaux_de_confiance(app.config)
    web_bind = (app.config.get("WEB_BIND") or "0.0.0.0").strip()
    if origine == "défaut" and web_bind not in _ADRESSES_LOCALES:
        logger.warning(
            "TRUSTED_PROXY_COUNT=%s, port 8000 publié sur le LAN (WEB_BIND=%s) et TRUSTED_PROXY_IPS vide : "
            "les en-têtes X-Forwarded-* ne sont crus que depuis %s (réseaux Docker et serveur). Renseignez "
            "TRUSTED_PROXY_IPS dans .env avec l'adresse de votre reverse proxy ; une requête d'une autre "
            "adresse portant ces en-têtes est signalée ici avec l'IP vue.",
            nb_proxys, web_bind, _decrire(reseaux),
        )
    else:
        logger.info("Reverse proxy : en-têtes X-Forwarded-* crus depuis %s (%s), %s saut(s).",
                    _decrire(reseaux), origine, nb_proxys)
    app.wsgi_app = ProxyDeConfiance(app.wsgi_app, nb_proxys, reseaux)

"""Notifications Windows (Web Push) — lot 24, décision du gérant du 20/10 ;
lot 25 : vérification complète du 23/10 (PU-01 à PU-14) et décisions du
gérant du 23/10.

Kairos installé comme une application (Chrome / Edge : « Installer »)
reçoit ses notifications dans le centre de notifications de Windows, même
fenêtre fermée tant que le navigateur tourne en arrière-plan.

- Protocole Web Push (RFC 8030), clés VAPID (RFC 8292) et chiffrement
  « aes128gcm » (RFC 8188, RFC 8291), écrits ici avec la bibliothèque
  `cryptography` : aucune autre dépendance, l'envoi passe par http.client.
- Clés dans `.env` (jamais dans le dépôt) : VAPID_PRIVATE_KEY (32 octets en
  base64url) et VAPID_SUJET (« mailto:… »). La clé publique s'en déduit
  (VAPID_PUBLIC_KEY facultative, contrôlée si présente). Sans clés : aucun
  push, l'appli marche comme avant. Clés produites par `flask cles-push`.
- Un abonnement par appareil et navigateur (table push_abonnement, 0027),
  au plus MAX_ABONNEMENTS par compte, vers un service push PUBLIC
  seulement (HOTES_PUSH : jamais une adresse interne, PU-01), sans suivre
  de redirection, en DELAI_TOTAL_ENVOI secondes au plus (PU-02). Supprimé
  quand le service répond 403, 404 ou 410 ou que ses clés sont
  inutilisables ; la clé VAPID de l'abonnement est retenue (PU-12).
- Déconnexion, révocation des sessions, changement de mot de passe ou
  désactivation du compte : tous ses abonnements sont retirés (0028,
  décision du gérant du 23/10 : PC partagé).
- Envoi en arrière-plan (fil dédié), DELAI_SECONDES après la création de
  la notification, au-delà du toast « Annuler » : une notification retirée
  entre-temps ou déjà lue n'est pas poussée. Notification marquée en
  attente en base (`push_attente`) : reprise si le worker redémarre, jamais
  poussée deux fois. Jamais bloquant pour la requête.
- Mode test : aucun push pour une action faite en « Agir comme », sous date
  simulée, ou pour un rappel simulé ; « Voir comme » n'écrit rien.
- Contenu : un titre court (rappel / correction du Daily log, informations
  RH, ou code du projet et titre de la tâche — jamais pour un projet qui
  n'est plus visible) et le texte que montre la cloche (extrait déjà masqué
  si le projet n'est plus visible ; décision du 23/10 : extrait gardé).
"""
from __future__ import annotations

import base64
import json
import os
import queue
import re
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

CATEGORIES = {
    "projet": "Projets\u00a0: mentions, posts, commentaires et tâches",
    "rh_info": "Daily log et informations RH\u00a0: rappels, corrections",
}
DELAI_SECONDES = 15          # lot 25 (PU-06) : au-delà du toast « Annuler » (10 s)
TTL_SECONDES = 24 * 3600
TAILLE_ENREGISTREMENT = 4096
MAX_TEXTE = 300


# ---------------------------------------------------------------------
# Encodages et clés
# ---------------------------------------------------------------------
def b64url(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode("ascii")


def de_b64url(texte: str) -> bytes:
    texte = (texte or "").strip()
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def _ec():
    from cryptography.hazmat.primitives.asymmetric import ec

    return ec


def _point_public(cle_privee) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return cle_privee.public_key().public_bytes(serialization.Encoding.X962,
                                                serialization.PublicFormat.UncompressedPoint)


def generer_cles() -> dict:
    """Nouvelle paire VAPID (lignes à copier dans .env)."""
    ec = _ec()
    privee = ec.generate_private_key(ec.SECP256R1())
    brut = privee.private_numbers().private_value.to_bytes(32, "big")
    return {"VAPID_PRIVATE_KEY": b64url(brut), "VAPID_PUBLIC_KEY": b64url(_point_public(privee))}


def _cle_privee():
    brut = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    if not brut:
        return None
    try:
        valeur = int.from_bytes(de_b64url(brut), "big")
        ec = _ec()
        return ec.derive_private_key(valeur, ec.SECP256R1())
    except Exception:
        return None


def cle_publique() -> str | None:
    """Clé publique VAPID (base64url) donnée au navigateur, None sans
    configuration valide (clé publique incohérente comprise)."""
    privee = _cle_privee()
    if privee is None:
        return None
    publique = b64url(_point_public(privee))
    declaree = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    if declaree and declaree != publique:
        return None
    return publique


def sujet() -> str:
    valeur = os.environ.get("VAPID_SUJET", "").strip()
    return valeur if valeur.startswith(("mailto:", "https://")) else "mailto:admin@kairos.invalid"


def actif() -> bool:
    return cle_publique() is not None


# ---------------------------------------------------------------------
# Chiffrement aes128gcm (RFC 8291) et jeton VAPID (RFC 8292)
# ---------------------------------------------------------------------
def _hmac(cle: bytes, donnees: bytes) -> bytes:
    import hashlib
    import hmac

    return hmac.new(cle, donnees, hashlib.sha256).digest()


def chiffrer(p256dh: str, auth: str, contenu: bytes, *, sel: bytes | None = None, ephemere=None) -> bytes:
    """Corps chiffré d'un message push (un seul enregistrement)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    ec = _ec()
    ua_public = de_b64url(p256dh)
    secret_auth = de_b64url(auth)
    if len(ua_public) != 65 or len(secret_auth) < 16:
        raise ValueError("clés d'abonnement invalides")
    if len(contenu) > TAILLE_ENREGISTREMENT - 17 - 86:
        raise ValueError("message trop long")
    ephemere = ephemere or ec.generate_private_key(ec.SECP256R1())
    as_public = _point_public(ephemere)
    partage = ephemere.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    prk_cle = _hmac(secret_auth, partage)
    ikm = _hmac(prk_cle, b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    sel = sel or os.urandom(16)
    prk = _hmac(sel, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    chiffre = AESGCM(cek).encrypt(nonce, contenu + b"\x02", None)
    entete = sel + struct.pack("!L", TAILLE_ENREGISTREMENT) + bytes([len(as_public)]) + as_public
    return entete + chiffre


def jeton_vapid(endpoint: str, maintenant: float | None = None) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    ec = _ec()
    privee = _cle_privee()
    if privee is None:
        raise RuntimeError("clés VAPID absentes")
    audience = origine(endpoint)
    entete = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    corps = b64url(json.dumps({"aud": audience, "exp": int((maintenant or time.time()) + 12 * 3600),
                               "sub": sujet()}, separators=(",", ":")).encode())
    signe = f"{entete}.{corps}".encode()
    r, s = decode_dss_signature(privee.sign(signe, ec.ECDSA(hashes.SHA256())))
    return f"{entete}.{corps}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


# Services push publics (lot 25, PU-01 : SSRF). Un abonnement ne peut
# viser QUE l'un d'eux : jamais une adresse interne, une IP ou un nom
# local. Le suffixe commence par un point : « x.notify.windows.com ».
HOTES_PUSH = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com",
              ".notify.windows.com", ".push.services.mozilla.com", ".push.apple.com")
MAX_ABONNEMENTS = 10          # par compte (PU-11) : les plus anciens sont retirés
DELAI_TOTAL_ENVOI = 15        # secondes, connexion et réponse comprises (PU-02)
ESSAI_INTERVALLE = 15         # secondes entre deux notifications d'essai (PU-14)
CLE_INVALIDE = -1             # code rendu par envoyer() : clés d'abonnement inutilisables (PU-03)
_B64URL = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


def origine(endpoint: str) -> str:
    """Origine sérialisée (RFC 6454) : « https://hôte », sans le port par
    défaut (PU-13) — c'est l'« aud » attendu par le service push."""
    parties = urllib.parse.urlsplit(endpoint)
    hote = parties.hostname or ""
    if ":" in hote:
        hote = f"[{hote}]"
    port = parties.port
    return f"{parties.scheme}://{hote}" + (f":{port}" if port and port != 443 else "")


def hote_autorise(hote: str | None) -> bool:
    hote = (hote or "").lower().rstrip(".")
    return any(hote == h if not h.startswith(".") else (hote.endswith(h) and len(hote) > len(h))
               for h in HOTES_PUSH)


def endpoint_valide(endpoint: str) -> bool:
    """Adresse d'un service push PUBLIC (PU-01) : https, port 443, sans
    identifiants, et l'hôte est celui de Google, Microsoft, Mozilla ou
    Apple — jamais une adresse interne, une IP ni un nom local."""
    if not isinstance(endpoint, str) or len(endpoint) > 1000 or any(c.isspace() for c in endpoint):
        return False
    try:
        parties = urllib.parse.urlsplit(endpoint)
        port = parties.port
    except ValueError:
        return False
    return (parties.scheme == "https" and not parties.username and not parties.password
            and port in (None, 443) and hote_autorise(parties.hostname))


def cles_valides(p256dh, auth) -> bool:
    """Clés d'un abonnement (PU-03, PU-08) : base64url strict, longueurs de
    la base, `p256dh` = un vrai point de la courbe P-256, `auth` 16 à 32 o."""
    if not (isinstance(p256dh, str) and isinstance(auth, str)):
        return False
    if len(p256dh) > 200 or len(auth) > 100 or not _B64URL.match(p256dh) or not _B64URL.match(auth):
        return False
    try:
        point, secret = de_b64url(p256dh), de_b64url(auth)
        if len(point) != 65 or not 16 <= len(secret) <= 32:
            return False
        ec = _ec()
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    except (ValueError, TypeError):
        return False
    return True


def _poster(endpoint: str, corps: bytes, entetes: dict) -> int:
    """POST vers le service push, SANS suivre de redirection (PU-01) et en
    DELAI_TOTAL_ENVOI secondes au plus, connexion et réponse comprises : un
    service qui répond au goutte-à-goutte est coupé (PU-02)."""
    import http.client
    import socket
    import ssl

    parties = urllib.parse.urlsplit(endpoint)
    chemin = (parties.path or "/") + (f"?{parties.query}" if parties.query else "")
    connexion = http.client.HTTPSConnection(parties.hostname, parties.port or 443, timeout=10,
                                            context=ssl.create_default_context())

    def couper():
        try:
            if connexion.sock is not None:
                connexion.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    minuterie = threading.Timer(DELAI_TOTAL_ENVOI, couper)
    minuterie.daemon = True
    minuterie.start()
    try:
        connexion.request("POST", chemin, body=corps, headers=entetes)
        reponse = connexion.getresponse()
        return reponse.status
    except Exception:
        return 0
    finally:
        minuterie.cancel()
        connexion.close()


def envoyer(abonnement: dict, message: dict, *, ouvreur=None) -> int:
    """Envoie `message` (dictionnaire JSON) à un abonnement ; renvoie le
    code HTTP du service push, 0 s'il est injoignable, CLE_INVALIDE si les
    clés de l'abonnement sont inutilisables. `ouvreur` (tests) remplace
    l'envoi réseau par une fonction à la manière d'urlopen."""
    if not endpoint_valide(abonnement.get("endpoint")):
        return CLE_INVALIDE
    try:
        corps = chiffrer(abonnement["cle_p256dh"], abonnement["cle_auth"],
                         json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (ValueError, TypeError):
        return CLE_INVALIDE
    entetes = {
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(TTL_SECONDES),
        "Urgency": "normal",
        "Authorization": f"vapid t={jeton_vapid(abonnement['endpoint'])}, k={cle_publique()}",
    }
    if ouvreur is None:
        return _poster(abonnement["endpoint"], corps, entetes)
    requete = urllib.request.Request(abonnement["endpoint"], data=corps, method="POST", headers=entetes)
    try:
        with ouvreur(requete, timeout=10) as reponse:
            return reponse.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def a_retirer(code: int) -> bool:
    """Abonnement à supprimer : expiré (404, 410), refusé par le service
    (403 : clé VAPID changée depuis l'abonnement, PU-12) ou inutilisable."""
    return code in (403, 404, 410, CLE_INVALIDE)


def appareil_libelle(navigateur: str | None) -> str:
    """« Chrome · Windows » d'après l'agent utilisateur enregistré."""
    ua = navigateur or ""
    nav = ("Edge" if "Edg/" in ua else "Opera" if "OPR/" in ua else "Chrome" if "Chrome/" in ua
           else "Firefox" if "Firefox/" in ua else "Safari" if "Safari/" in ua else "Navigateur")
    os_ = ("Windows" if "Windows" in ua else "Android" if "Android" in ua else "iPhone" if "iPhone" in ua
           else "iPad" if "iPad" in ua else "macOS" if "Mac OS" in ua else "Linux" if "Linux" in ua else "")
    return f"{nav} · {os_}" if os_ else nav


MAX_TITRE = 60


def titre_de(notif: dict) -> str:
    """Titre de la notification Windows (lot 25, retour du gérant du
    22/10) : Windows affiche déjà « Kairos » et l'icône en en-tête, le titre
    dit donc de quoi il s'agit — rappel, correction, projet et tâche."""
    if notif.get("categorie") == "rh_info":
        if notif.get("est_rappel"):
            return "Daily log à remplir"
        if (notif.get("message") or "").startswith("Daily log"):
            return "Daily log corrigé"
        return "Informations RH"
    code, tache = notif.get("projet_code"), " ".join((notif.get("tache_titre") or "").split())
    if code and tache:
        titre = f"{code} · {tache}"
    elif code:
        titre = f"Projet {code}"
    else:
        titre = "Projet"
    return titre if len(titre) <= MAX_TITRE else titre[:MAX_TITRE - 1].rstrip() + "…"


def message_de(notif: dict) -> dict:
    texte = " ".join((notif.get("message") or "").split())
    if len(texte) > MAX_TEXTE:
        texte = texte[:MAX_TEXTE - 1].rstrip() + "…"
    return {"titre": titre_de(notif), "texte": texte,
            "url": f"/notifications?ouvrir={int(notif['id'])}", "id": int(notif["id"])}


def _abonnements_valides(utilisateur_id: int) -> list[dict]:
    """Abonnements de la personne faits avec la clé VAPID actuelle (PU-12 :
    ceux d'une ancienne clé ne peuvent plus rien recevoir)."""
    from .repositories import push as push_repo

    cle = cle_publique()
    return [a for a in push_repo.abonnements(utilisateur_id) if not a.get("cle_serveur") or a["cle_serveur"] == cle]


def _envoyer_a(abonnements: list[dict], message: dict, *, ouvreur=None) -> int:
    """Un message vers plusieurs appareils : une erreur sur l'un n'empêche
    jamais les autres (PU-03) ; abonnements morts supprimés."""
    from .repositories import push as push_repo

    envoyes = 0
    for abonnement in abonnements:
        try:
            code = envoyer(abonnement, message, ouvreur=ouvreur)
        except Exception:
            code = 0
        if a_retirer(code):
            push_repo.supprimer_endpoint(abonnement["endpoint"])
        elif 200 <= code < 300:
            envoyes += 1
    return envoyes


def traiter(notification_ids: list[int], *, ouvreur=None) -> int:
    """Pousse les notifications encore à pousser (existantes, non lues,
    non simulées, catégorie choisie par la personne) vers ses appareils ;
    renvoie le nombre d'envois réussis. Chaque notification est réservée
    avant l'envoi (`push_attente`, 0028) : poussée une seule fois, même
    reprise par plusieurs workers après un redémarrage (PU-10)."""
    from .repositories import push as push_repo

    if not actif():
        return 0
    ids = push_repo.reserver(notification_ids)
    envoyes = 0
    for notif in push_repo.notifications_a_pousser(ids):
        envoyes += _envoyer_a(_abonnements_valides(notif["utilisateur_id"]), message_de(notif), ouvreur=ouvreur)
    return envoyes


def essai(utilisateur_id: int, *, ouvreur=None) -> int:
    message = {"titre": "Notification d’essai", "texte": "Les notifications Windows de Kairos fonctionnent sur ce PC.",
               "url": "/notifications", "id": 0}
    return _envoyer_a(_abonnements_valides(utilisateur_id), message, ouvreur=ouvreur)


# ---------------------------------------------------------------------
# Envoi en arrière-plan
# ---------------------------------------------------------------------
# Une file et un fil par processus (worker gunicorn). Chaque élément :
# (échéance monotone, nature, données). Les notifications en attente sont
# aussi marquées en base : un worker qui redémarre les reprend (PU-10).
_file: queue.Queue | None = None
_verrou = threading.Lock()
_derniers_essais: dict[int, float] = {}


def _travailleur(app) -> None:
    while True:
        echeance, nature, donnees = _file.get()
        attente = echeance - time.monotonic()
        if attente > 0:
            time.sleep(attente)
        try:
            with app.app_context():
                if nature == "essai":
                    essai(donnees)
                else:
                    traiter(donnees)
        except Exception:
            app.logger.exception("Notifications push non envoyées")


def _lancer(app) -> None:
    global _file
    with _verrou:
        if _file is None:
            _file = queue.Queue()
            threading.Thread(target=_travailleur, args=(app,), daemon=True, name="kairos-push").start()


def demarrer(app) -> None:
    """Appelée au démarrage d'un worker gunicorn (gunicorn.conf.py,
    post_worker_init) : reprend les notifications marquées en attente dans
    les dernières minutes (worker arrêté avant l'envoi, PU-10), chacune à
    son échéance d'origine. Jamais dans une commande `flask` (le processus
    s'arrêterait avant l'envoi)."""
    if not actif():
        return
    try:
        from .repositories import push as push_repo

        with app.app_context():
            delai = app.config.get("PUSH_DELAI", DELAI_SECONDES)
            reprises = push_repo.en_attente_recentes(delai)
        _lancer(app)
        for ligne in reprises:
            _file.put((time.monotonic() + max(0.0, float(ligne["reste"])), "notifications", [ligne["id"]]))
    except Exception:
        app.logger.exception("Reprise des notifications push impossible")


def planifier(notification_ids: list[int]) -> None:
    """Appelée après la création de notifications : rien en mode test
    (« Agir comme », date simulée, « Voir comme »), rien sans clés. Le
    délai (DELAI_SECONDES) dépasse celui du toast « Annuler » (10 s) : un
    geste défait n'arrive pas dans Windows (PU-06)."""
    ids = [int(i) for i in notification_ids or [] if i]
    if not ids or not actif():
        return
    from flask import current_app, g, has_request_context

    from .repositories import push as push_repo

    if has_request_context() and (g.get("admin_reel") or g.get("date_simulee") or g.get("lecture_seule")):
        return
    push_repo.marquer_en_attente(ids)
    app = current_app._get_current_object()
    delai = app.config.get("PUSH_DELAI", DELAI_SECONDES)
    if app.testing and not delai:
        traiter(ids)
        return
    _lancer(app)
    _file.put((time.monotonic() + delai, "notifications", ids))


def planifier_essai(utilisateur_id: int) -> bool:
    """Notification d'essai, par la file (plus un fil par clic, PU-14) et
    au plus une toutes les ESSAI_INTERVALLE secondes par compte."""
    from flask import current_app

    maintenant = time.monotonic()
    with _verrou:
        dernier = _derniers_essais.get(utilisateur_id)
        if dernier is not None and maintenant - dernier < ESSAI_INTERVALLE:
            return False
        _derniers_essais[utilisateur_id] = maintenant
    app = current_app._get_current_object()
    if app.testing:
        essai(utilisateur_id)
        return True
    _lancer(app)
    _file.put((maintenant, "essai", utilisateur_id))
    return True

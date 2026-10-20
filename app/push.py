"""Notifications Windows (Web Push) — lot 24, décision du gérant du 20/10.

Kairos installé comme une application (Chrome / Edge : « Installer »)
reçoit ses notifications dans le centre de notifications de Windows, même
fenêtre fermée tant que le navigateur tourne en arrière-plan.

- Protocole Web Push (RFC 8030), clés VAPID (RFC 8292) et chiffrement
  « aes128gcm » (RFC 8188, RFC 8291), écrits ici avec la bibliothèque
  `cryptography` : aucune autre dépendance, l'envoi passe par urllib.
- Clés dans `.env` (jamais dans le dépôt) : VAPID_PRIVATE_KEY (32 octets en
  base64url) et VAPID_SUJET (« mailto:… »). La clé publique s'en déduit
  (VAPID_PUBLIC_KEY facultative, contrôlée si présente). Sans clés : aucun
  push, l'appli marche comme avant. Clés produites par `flask cles-push`.
- Un abonnement par appareil et navigateur (table push_abonnement, 0027) ;
  supprimé quand le service push répond 404 ou 410 (abonnement expiré).
- Envoi en arrière-plan (fil dédié), quelques secondes après la création de
  la notification : une notification retirée entre-temps (« Annuler ») ou
  déjà lue n'est pas poussée. Jamais bloquant pour la requête.
- Mode test : aucun push pour une action faite en « Agir comme », sous date
  simulée, ou pour un rappel simulé ; « Voir comme » n'écrit rien.
- Contenu : le titre « Kairos » et le texte que montre la cloche (extrait
  déjà masqué si le projet n'est plus visible) — rien de plus.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

CATEGORIES = {
    "projet": "Projets : mentions, posts, commentaires et tâches",
    "rh_info": "Daily log et informations RH : rappels, corrections",
}
DELAI_SECONDES = 8
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
    parties = urllib.parse.urlsplit(endpoint)
    audience = f"{parties.scheme}://{parties.netloc}"
    entete = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    corps = b64url(json.dumps({"aud": audience, "exp": int((maintenant or time.time()) + 12 * 3600),
                               "sub": sujet()}, separators=(",", ":")).encode())
    signe = f"{entete}.{corps}".encode()
    r, s = decode_dss_signature(privee.sign(signe, ec.ECDSA(hashes.SHA256())))
    return f"{entete}.{corps}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def endpoint_valide(endpoint: str) -> bool:
    """Adresse d'un service push : https, sans identifiants ni port exotique."""
    if not isinstance(endpoint, str) or len(endpoint) > 1000:
        return False
    parties = urllib.parse.urlsplit(endpoint)
    return (parties.scheme == "https" and bool(parties.hostname) and not parties.username
            and parties.port in (None, 443))


def envoyer(abonnement: dict, message: dict, *, ouvreur=None) -> int:
    """Envoie `message` (dictionnaire JSON) à un abonnement ; renvoie le
    code HTTP du service push (0 si injoignable)."""
    corps = chiffrer(abonnement["cle_p256dh"], abonnement["cle_auth"],
                     json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    requete = urllib.request.Request(abonnement["endpoint"], data=corps, method="POST", headers={
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(TTL_SECONDES),
        "Urgency": "normal",
        "Authorization": f"vapid t={jeton_vapid(abonnement['endpoint'])}, k={cle_publique()}",
    })
    try:
        with (ouvreur or urllib.request.urlopen)(requete, timeout=10) as reponse:
            return reponse.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


# ---------------------------------------------------------------------
# Envoi en arrière-plan
# ---------------------------------------------------------------------
_file: queue.Queue | None = None
_verrou = threading.Lock()


def message_de(notif: dict) -> dict:
    texte = " ".join((notif.get("message") or "").split())
    if len(texte) > MAX_TEXTE:
        texte = texte[:MAX_TEXTE - 1].rstrip() + "…"
    return {"titre": "Kairos" + (f" · {notif['projet_code']}" if notif.get("projet_code") else ""),
            "texte": texte, "url": f"/notifications?ouvrir={int(notif['id'])}", "id": int(notif["id"])}


def traiter(notification_ids: list[int], *, ouvreur=None) -> int:
    """Pousse les notifications encore à pousser (existantes, non lues,
    non simulées, catégorie choisie par la personne) vers ses appareils ;
    renvoie le nombre d'envois réussis. Abonnements expirés supprimés."""
    from .repositories import push as push_repo

    if not actif():
        return 0
    envoyes = 0
    for notif in push_repo.notifications_a_pousser(notification_ids):
        for abonnement in push_repo.abonnements(notif["utilisateur_id"]):
            code = envoyer(abonnement, message_de(notif), ouvreur=ouvreur)
            if code in (404, 410):
                push_repo.supprimer_endpoint(abonnement["endpoint"])
            elif 200 <= code < 300:
                envoyes += 1
    return envoyes


def _travailleur(app) -> None:
    while True:
        echeance, ids = _file.get()
        attente = echeance - time.monotonic()
        if attente > 0:
            time.sleep(attente)
        try:
            with app.app_context():
                traiter(ids)
        except Exception:
            app.logger.exception("Notifications push non envoyées")


def planifier(notification_ids: list[int]) -> None:
    """Appelée après la création de notifications : rien en mode test
    (« Agir comme », date simulée, « Voir comme »), rien sans clés."""
    global _file
    ids = [int(i) for i in notification_ids or [] if i]
    if not ids or not actif():
        return
    from flask import current_app, g, has_request_context

    if has_request_context() and (g.get("admin_reel") or g.get("date_simulee") or g.get("lecture_seule")):
        return
    app = current_app._get_current_object()
    delai = app.config.get("PUSH_DELAI", DELAI_SECONDES)
    if app.testing and not delai:
        traiter(ids)
        return
    with _verrou:
        if _file is None:
            _file = queue.Queue()
            threading.Thread(target=_travailleur, args=(app,), daemon=True, name="kairos-push").start()
    _file.put((time.monotonic() + delai, ids))

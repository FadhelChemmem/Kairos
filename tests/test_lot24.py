"""Lot 24, tests unitaires (sans base) : notifications Windows (Web Push :
VAPID, chiffrement aes128gcm, envoi, abonnements expirés), liens en temps
linéaire (N-ES01), horloge simulée qui ralentit sans se figer (N-HORL),
photos de profil valides acceptées (SR-01)."""
import base64
import datetime
import hashlib
import hmac
import io
import json
import os
import struct
import time
import unittest
from unittest import mock
from zoneinfo import ZoneInfo


def _b64(o):
    return base64.urlsafe_b64encode(o).rstrip(b"=").decode()


def _db64(t):
    return base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))


class _Navigateur:
    """Côté navigateur (agent utilisateur) : paire de clés de l'abonnement et
    déchiffrement d'un message, écrit d'après la RFC 8291 §3.4 et la RFC 8188."""

    def __init__(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        self.ec = ec
        self.privee = ec.generate_private_key(ec.SECP256R1())
        self.publique = self.privee.public_key().public_bytes(serialization.Encoding.X962,
                                                              serialization.PublicFormat.UncompressedPoint)
        self.auth = os.urandom(16)

    def abonnement(self, endpoint="https://fcm.googleapis.com/fcm/send/abc"):
        return {"endpoint": endpoint, "cle_p256dh": _b64(self.publique), "cle_auth": _b64(self.auth)}

    def dechiffrer(self, corps: bytes) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        def h(k, d):
            return hmac.new(k, d, hashlib.sha256).digest()

        sel, rs, longueur = corps[:16], struct.unpack("!L", corps[16:20])[0], corps[20]
        as_public = corps[21:21 + longueur]
        chiffre = corps[21 + longueur:]
        assert rs == 4096 and longueur == 65 and len(chiffre) <= rs
        partage = self.privee.exchange(self.ec.ECDH(),
                                       self.ec.EllipticCurvePublicKey.from_encoded_point(self.ec.SECP256R1(), as_public))
        ikm = h(h(self.auth, partage), b"WebPush: info\x00" + self.publique + as_public + b"\x01")
        prk = h(sel, ikm)
        clair = AESGCM(h(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]).decrypt(
            h(prk, b"Content-Encoding: nonce\x00\x01")[:12], chiffre, None)
        assert clair.endswith(b"\x02")
        return clair[:-1]


class _Env(unittest.TestCase):
    def setUp(self):
        from app import push

        self.push = push
        cles = push.generer_cles()
        self.env = mock.patch.dict(os.environ, {"VAPID_PRIVATE_KEY": cles["VAPID_PRIVATE_KEY"],
                                                "VAPID_PUBLIC_KEY": cles["VAPID_PUBLIC_KEY"],
                                                "VAPID_SUJET": "mailto:kairos@test.invalid"})
        self.env.start()
        self.cles = cles

    def tearDown(self):
        self.env.stop()


class TestCles(_Env):
    def test_cle_publique_deduite_et_controlee(self):
        self.assertEqual(self.push.cle_publique(), self.cles["VAPID_PUBLIC_KEY"])
        self.assertEqual(len(_db64(self.push.cle_publique())), 65)
        with mock.patch.dict(os.environ, {"VAPID_PUBLIC_KEY": self.push.generer_cles()["VAPID_PUBLIC_KEY"]}):
            self.assertIsNone(self.push.cle_publique())     # clé publique d'une autre paire
            self.assertFalse(self.push.actif())
        with mock.patch.dict(os.environ, {"VAPID_PRIVATE_KEY": "", "VAPID_PUBLIC_KEY": ""}):
            self.assertFalse(self.push.actif())
        with mock.patch.dict(os.environ, {"VAPID_PRIVATE_KEY": "pas une clé!", "VAPID_PUBLIC_KEY": ""}):
            self.assertFalse(self.push.actif())

    def test_jeton_vapid_signe_par_la_cle(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

        jeton = self.push.jeton_vapid("https://fcm.googleapis.com/fcm/send/abc", maintenant=1_800_000_000)
        entete, corps, signature = jeton.split(".")
        self.assertEqual(json.loads(_db64(entete)), {"typ": "JWT", "alg": "ES256"})
        self.assertEqual(json.loads(_db64(corps)), {"aud": "https://fcm.googleapis.com",
                                                     "exp": 1_800_000_000 + 12 * 3600,
                                                     "sub": "mailto:kairos@test.invalid"})
        brut = _db64(signature)
        publique = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), _db64(self.push.cle_publique()))
        publique.verify(encode_dss_signature(int.from_bytes(brut[:32], "big"), int.from_bytes(brut[32:], "big")),
                        f"{entete}.{corps}".encode(), ec.ECDSA(hashes.SHA256()))

    def test_adresses_de_service_push(self):
        ok = self.push.endpoint_valide
        self.assertTrue(ok("https://fcm.googleapis.com/fcm/send/x"))
        self.assertTrue(ok("https://wns2-par02p.notify.windows.com/w/?token=x"))
        for mauvais in ("http://fcm.googleapis.com/x", "https://u:p@fcm.googleapis.com/x", "https://x:8443/a",
                        "javascript:alert(1)", "https://" + "a" * 1000, None, 3):
            self.assertFalse(ok(mauvais), mauvais)


class TestChiffrement(_Env):
    def test_le_navigateur_dechiffre_le_message(self):
        nav = _Navigateur()
        message = {"titre": "Kairos · 26101X", "texte": "Rim a commenté : « Plans validés » é😀"}
        corps = self.push.chiffrer(_b64(nav.publique), _b64(nav.auth),
                                   json.dumps(message, ensure_ascii=False).encode())
        self.assertEqual(json.loads(nav.dechiffrer(corps)), message)
        # Sel et clé éphémère neufs à chaque message.
        autre = self.push.chiffrer(_b64(nav.publique), _b64(nav.auth), b"x")
        self.assertNotEqual(corps[:16], autre[:16])
        self.assertNotEqual(corps[21:86], autre[21:86])

    def test_cles_ou_taille_invalides(self):
        nav = _Navigateur()
        with self.assertRaises(ValueError):
            self.push.chiffrer(_b64(b"court"), _b64(nav.auth), b"x")
        with self.assertRaises(ValueError):
            self.push.chiffrer(_b64(nav.publique), _b64(nav.auth), b"x" * 4000)


class _Reponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestEnvoi(_Env):
    def test_requete_envoyee_au_service_push(self):
        nav = _Navigateur()
        vues = []

        def ouvreur(requete, timeout):
            vues.append(requete)
            return _Reponse(201)

        code = self.push.envoyer(nav.abonnement(), {"titre": "Kairos", "texte": "Bonjour"}, ouvreur=ouvreur)
        self.assertEqual(code, 201)
        r = vues[0]
        self.assertEqual((r.get_method(), r.full_url), ("POST", "https://fcm.googleapis.com/fcm/send/abc"))
        entetes = {k.lower(): v for k, v in r.header_items()}
        self.assertEqual(entetes["content-encoding"], "aes128gcm")
        self.assertEqual(entetes["ttl"], str(24 * 3600))
        self.assertTrue(entetes["authorization"].startswith("vapid t="))
        self.assertTrue(entetes["authorization"].endswith(", k=" + self.push.cle_publique()))
        self.assertEqual(json.loads(nav.dechiffrer(r.data)), {"titre": "Kairos", "texte": "Bonjour"})

    def test_abonnement_expire_supprime_et_rien_sans_cles(self):
        import urllib.error

        nav = _Navigateur()
        notif = {"id": 7, "utilisateur_id": 3, "message": "Ali vous a mentionné", "projet_code": "26101X"}
        codes = iter([410, 201])

        def ouvreur(requete, timeout):
            code = next(codes)
            if code >= 400:
                raise urllib.error.HTTPError(requete.full_url, code, "Gone", {}, None)
            return _Reponse(code)

        with mock.patch("app.repositories.push.notifications_a_pousser", return_value=[notif]), \
             mock.patch("app.repositories.push.abonnements",
                        return_value=[nav.abonnement("https://fcm.googleapis.com/a"),
                                      nav.abonnement("https://fcm.googleapis.com/b")]), \
             mock.patch("app.repositories.push.supprimer_endpoint") as supprimer:
            self.assertEqual(self.push.traiter([7], ouvreur=ouvreur), 1)
        supprimer.assert_called_once_with("https://fcm.googleapis.com/a")
        with mock.patch.dict(os.environ, {"VAPID_PRIVATE_KEY": ""}), \
             mock.patch("app.repositories.push.notifications_a_pousser") as lire:
            self.assertEqual(self.push.traiter([7]), 0)
            lire.assert_not_called()

    def test_message_court_vers_la_notification(self):
        m = self.push.message_de({"id": 12, "message": "x " * 400, "projet_code": None})
        self.assertEqual(m["url"], "/notifications?ouvrir=12")
        self.assertEqual(m["titre"], "Kairos")
        self.assertLessEqual(len(m["texte"]), self.push.MAX_TEXTE)


class TestAvecLiensLineaire(unittest.TestCase):
    def test_longue_suite_de_parentheses(self):
        from app.utils import avec_liens

        debut = time.perf_counter()
        html = str(avec_liens("https://x" + ")" * 100_000))
        self.assertLess(time.perf_counter() - debut, 1.0)
        self.assertIn('href="https://x"', html)
        self.assertIn('href="https://x.tn/a_(b)"', str(avec_liens("(https://x.tn/a_(b)).")))


class TestHorlogeRalentie(unittest.TestCase):
    def test_avance_puis_ralentit_sans_changer_de_jour(self):
        from app.horloge import avancer

        tz = ZoneInfo("Africa/Tunis")
        depart = datetime.datetime(2026, 10, 17, 23, 55, tzinfo=tz)
        self.assertEqual(avancer(depart, 60), depart + datetime.timedelta(minutes=1))
        a = avancer(depart, 600)          # 10 minutes de session : passé 23:59
        b = avancer(depart, 601)
        self.assertEqual(a.date(), depart.date())
        self.assertLess(a, b)              # toujours croissant
        self.assertEqual(a, datetime.datetime(2026, 10, 17, 23, 59, 0, 360_000, tzinfo=tz))
        self.assertEqual(avancer(depart, 10 ** 9).time(), datetime.time.max)


class TestPhotosValides(unittest.TestCase):
    def test_gif_60_px_et_jpeg_suivi_de_donnees(self):
        from app.storage import est_vraie_image

        class F:
            def __init__(self, b):
                self.stream = io.BytesIO(b)

        def gif(largeur, palette):
            # En-tête, palette globale de 2 couleurs, image 1×1, terminateur.
            return (b"GIF89a" + struct.pack("<HH", largeur, largeur) + b"\x80\x00\x00" + palette
                    + b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")

        jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
        for octets in (gif(60, b"\xc8\x1e\x1e\x3c\x78\xb4"), gif(64, b"\x3c\x78\xb4\x00\x00\x00"),
                       jpeg, jpeg + b"SEFHxxxxSEFT"):
            self.assertTrue(est_vraie_image(F(octets)))
        self.assertFalse(est_vraie_image(F(b"GIF89a<html><script>alert(1)</script>;")))
        self.assertFalse(est_vraie_image(F(b"\xff\xd8\xff<svg onload=alert(1)>\xff\xd9")))


if __name__ == "__main__":
    unittest.main()

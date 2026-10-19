"""Lot 21, tests unitaires (sans base) : structure des photos de profil
(contre-expertise R30 / R-04), liste d'identifiants bornée APRÈS le tri
(R-22), durée du lien de réinitialisation non recopiée (R-16)."""
import io
import struct
import unittest
import zlib
from unittest.mock import patch

from werkzeug.datastructures import FileStorage


def _bloc(type_, donnees):
    return struct.pack(">I", len(donnees)) + type_ + donnees + struct.pack(">I", zlib.crc32(type_ + donnees) & 0xFFFFFFFF)


PNG = (b"\x89PNG\r\n\x1a\n" + _bloc(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
       + _bloc(b"IDAT", zlib.compress(b"\x00\x00")) + _bloc(b"IEND", b""))
JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF\x00" + b"\x01" * 16 + b"\xff\xd9"
GIF = b"GIF89a" + b"\x01\x00\x01\x00\x00\x00\x00" + b"\x2c" + b"\x00" * 9 + b"\x02\x02\x44\x01\x00" + b"\x3b"
WEBP_CORPS = b"WEBP" + b"VP8L" + struct.pack("<I", 6) + b"\x2f\x00\x00\x00\x00\x00"
WEBP = b"RIFF" + struct.pack("<I", len(WEBP_CORPS)) + WEBP_CORPS


def fichier(octets, nom="photo.png"):
    return FileStorage(stream=io.BytesIO(octets), filename=nom)


class TestPhotoDeProfil(unittest.TestCase):
    def test_vraies_images_acceptees_et_flux_rembobine(self):
        from app.storage import est_vraie_image

        for nom, octets in (("png", PNG), ("jpeg", JPEG), ("gif", GIF), ("webp", WEBP)):
            with self.subTest(nom):
                f = fichier(octets)
                self.assertTrue(est_vraie_image(f))
                self.assertEqual(f.stream.read(), octets)

    def test_fausses_signatures_refusees(self):
        from app.storage import est_vraie_image

        cas = {
            "vide": b"",
            "png tronqué": PNG[:-12],
            "png sans IHDR": b"\x89PNG\r\n\x1a\n" + _bloc(b"tEXt", b"x") + _bloc(b"IEND", b""),
            "jpeg tronqué": JPEG[:-2],
            "gif html": b"GIF89a<html><script>alert(1)</script></html>;",
            "gif sans terminateur": GIF[:-1],
            "webp mauvaise taille": WEBP + b"\x00\x00",
            "texte": b"Bonjour, ceci n'est pas une image.",
        }
        for nom, octets in cas.items():
            with self.subTest(nom):
                self.assertFalse(est_vraie_image(fichier(octets)))

    def test_au_dela_de_10_mo_refusee(self):
        from app import storage

        with patch.object(storage, "MAX_OCTETS_AVATAR", len(PNG) - 1):
            self.assertFalse(storage.est_vraie_image(fichier(PNG)))


class TestIdsEntiers(unittest.TestCase):
    def test_invalides_en_tete_ne_masquent_pas_les_valables(self):
        from app.validation import ids_entiers

        valeurs = ["x"] * 500 + ["7"] * 300 + ["8", "²", "9"]
        self.assertEqual(ids_entiers(valeurs, maximum=3), [7, 8, 9])

    def test_borne_et_ordre(self):
        from app.validation import ids_entiers

        self.assertEqual(ids_entiers([str(i) for i in range(1000)], maximum=5), [0, 1, 2, 3, 4])
        self.assertEqual(ids_entiers(["3", "1", "3", None, "٣"]), [3, 1])


class TestLienDeReinitialisation(unittest.TestCase):
    def test_duree_du_lien_passee_a_la_requete(self):
        import datetime

        from app.repositories import utilisateurs

        with patch("app.db.query_one", return_value=None) as requete:
            utilisateurs.lien_reset_recent(4, 15, datetime.timedelta(hours=2))
        sql, params = requete.call_args[0]
        self.assertNotIn("1 hour", sql)
        self.assertEqual(params, (4, 7200.0, 15))


if __name__ == "__main__":
    unittest.main()

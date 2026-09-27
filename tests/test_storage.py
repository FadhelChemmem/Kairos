"""Tests unitaires pour app/storage.py — PROMPT_CORRECTIONS.md P2 #21.

Avant ce correctif, save_upload() passait le nom de fichier envoyé par le
navigateur dans secure_filename() pour en tirer l'extension à conserver.
secure_filename() translittère/supprime les caractères non-ASCII : un nom
comme "plan مخطط.pdf" devenait "plan.pdf" (encore correct), mais un nom
ENTIÈREMENT non-ASCII comme "مخطط.pdf" devenait "pdf" — plus de point, donc
plus d'extension du tout. Le fichier stocké se retrouvait sans extension
(mauvais Content-Type au téléchargement, extension perdue), et le nom
affiché dans l'interface perdait tout sens.
"""
import sys
import tempfile
import unittest
from pathlib import Path

# Mêmes contraintes que test_smoke.py : psycopg2 n'est pas installable
# dans cet environnement — on le stub avant d'importer quoi que ce soit
# sous app/.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_smoke import _install_fake_psycopg2  # noqa: E402

_install_fake_psycopg2()

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402
from app import storage  # noqa: E402


class FakeFileStorage:
    """Un faux werkzeug.FileStorage : juste ce dont save_upload() a besoin
    (un .filename et une méthode .save() qui écrit sur disque)."""

    def __init__(self, filename: str, contenu: bytes = b"contenu"):
        self.filename = filename
        self._contenu = contenu

    def save(self, dst):
        Path(dst).write_bytes(self._contenu)


class StorageTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

        class TestConfig(Config):
            DATABASE_URL = "postgresql://fake/fake"
            SECRET_KEY = "test-secret"
            TESTING = True
            UPLOAD_DIR = self._tmpdir.name

        self.app = create_app(TestConfig)
        self._ctx = self.app.app_context()
        self._ctx.push()
        self.addCleanup(self._ctx.pop)

    def test_nom_non_ascii_garde_son_extension(self):
        """Cas exact du bug : un nom entièrement non-ASCII ne doit pas
        perdre son extension."""
        fichier = FakeFileStorage("مخطط.pdf")
        nom_retourne, chemin = storage.save_upload(fichier, "taches/5")

        self.assertEqual(nom_retourne, "مخطط.pdf")
        self.assertTrue(chemin.endswith(".pdf"), chemin)

    def test_nom_non_ascii_garde_son_extension_meme_avec_accent(self):
        fichier = FakeFileStorage("plan écran.dwg")
        nom_retourne, chemin = storage.save_upload(fichier, "taches/5")

        self.assertEqual(nom_retourne, "plan écran.dwg")
        self.assertTrue(chemin.endswith(".dwg"), chemin)

    def test_extension_inconnue_est_ignoree(self):
        """Une extension hors liste blanche (ex. un script) ne doit pas
        être reprise pour le fichier stocké — le nom affiché, lui, reste
        intact (il n'est jamais exécuté, seulement affiché échappé)."""
        fichier = FakeFileStorage("script.exe")
        nom_retourne, chemin = storage.save_upload(fichier, "taches/5")

        self.assertEqual(nom_retourne, "script.exe")
        self.assertFalse(chemin.endswith(".exe"), chemin)

    def test_extension_connue_est_normalisee_en_minuscules(self):
        fichier = FakeFileStorage("Rapport.PDF")
        _, chemin = storage.save_upload(fichier, "posts/1")

        self.assertTrue(chemin.endswith(".pdf"), chemin)

    def test_nom_stocke_est_un_uuid_pas_le_nom_original(self):
        """Le nom sur disque doit rester un UUID généré (jamais dérivé du
        nom fourni par l'utilisateur) — aucun risque de traversée de
        chemin ni de collision."""
        fichier = FakeFileStorage("مخطط.pdf")
        _, chemin = storage.save_upload(fichier, "taches/5")

        nom_stocke = Path(chemin).stem
        self.assertNotIn("مخطط", nom_stocke)
        self.assertEqual(len(nom_stocke), 32)  # uuid4().hex


if __name__ == "__main__":
    unittest.main()

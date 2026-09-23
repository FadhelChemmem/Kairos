"""Stockage des pièces jointes (tâches/posts) sur disque, en dehors de la
base — seuls le nom d'origine et le chemin relatif sont enregistrés dans
`tache_piece_jointe` / `post_piece_jointe` (voir schema.sql).

Chaque fichier est sauvegardé sous un nom généré (uuid) pour éviter toute
collision ou tout risque lié à un nom de fichier fourni par l'utilisateur,
tout en gardant le nom d'origine affiché dans l'interface.
"""
import os
import uuid

from flask import current_app
from werkzeug.utils import secure_filename

# Photos de profil (retour Fadhel, 2026-09-20) : mêmes contraintes de
# format que n'importe quel avatar web classique — on ne veut pas qu'un
# utilisateur envoie un .pdf ou un .exe en photo de profil.
AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def is_image_filename(filename: str) -> bool:
    return os.path.splitext(filename or "")[1].lower() in AVATAR_EXTENSIONS


def save_upload(file_storage, subdir: str) -> tuple[str, str]:
    """Enregistre un fichier uploadé sous UPLOAD_DIR/<subdir>/<uuid>.<ext>.
    Retourne (nom_fichier_original, chemin_relatif) à stocker en base.
    """
    original = secure_filename(file_storage.filename) or "fichier"
    ext = os.path.splitext(original)[1]
    stored_name = f"{uuid.uuid4().hex}{ext}"
    rel_path = os.path.join(subdir, stored_name)

    abs_path = os.path.join(current_app.config["UPLOAD_DIR"], rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    file_storage.save(abs_path)

    return original, rel_path

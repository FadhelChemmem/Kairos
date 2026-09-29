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

# Photos de profil (retour Fadhel, 2026-09-20) : mêmes contraintes de
# format que n'importe quel avatar web classique — on ne veut pas qu'un
# utilisateur envoie un .pdf ou un .exe en photo de profil.
AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# Pièces jointes (tâches/posts) : liste blanche d'extensions couvrant les
# usages réels du métier (plans, devis, photos de chantier...). PROMPT_
# CORRECTIONS.md P2 #21 : on ne peut plus utiliser secure_filename() pour
# détecter l'extension (voir plus bas) — un nom de fichier arbitraire doit
# donc être validé contre cette liste avant d'être conservé, sous peine de
# stocker un fichier sans aucune extension reconnaissable côté serveur.
PIECE_JOINTE_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
    ".dwg", ".dxf", ".ifc", ".rvt",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg",
    ".zip", ".rar", ".7z",
    ".txt", ".csv",
}


def is_image_filename(filename: str) -> bool:
    return os.path.splitext(filename or "")[1].lower() in AVATAR_EXTENSIONS


def save_upload(file_storage, subdir: str) -> tuple[str, str]:
    """Enregistre un fichier uploadé sous UPLOAD_DIR/<subdir>/<uuid>.<ext>.
    Retourne (nom_fichier_original, chemin_relatif) à stocker en base.

    PROMPT_CORRECTIONS.md P2 #21 : secure_filename() translittère/supprime
    les caractères non-ASCII — un nom comme "مخطط.pdf" devenait "pdf" (sans
    point, donc SANS extension), ce qui faisait perdre l'extension réelle du
    fichier (et donc, entre autres, le bon Content-Type au téléchargement).
    On ne s'en sert plus : le nom d'origine (non modifié) est conservé tel
    quel pour l'affichage (Jinja2 l'échappe automatiquement dans les
    templates), et l'extension est prise sur ce nom brut puis validée
    contre PIECE_JOINTE_EXTENSIONS avant d'être utilisée pour le nom stocké
    sur disque (qui reste un UUID — aucun risque de traversée de chemin).
    """
    nom_brut = file_storage.filename or "fichier"
    ext = os.path.splitext(nom_brut)[1].lower()
    if ext not in PIECE_JOINTE_EXTENSIONS:
        ext = ""
    stored_name = f"{uuid.uuid4().hex}{ext}"
    rel_path = os.path.join(subdir, stored_name)

    abs_path = os.path.join(current_app.config["UPLOAD_DIR"], rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    file_storage.save(abs_path)

    return nom_brut, rel_path


def delete_upload(rel_path: str | None) -> None:
    """Supprime un fichier précédemment enregistré par save_upload().

    Utilisé pour nettoyer un fichier orphelin sur disque quand l'écriture
    en base censée le référencer (INSERT ...piece_jointe...) échoue juste
    après save_upload() (audit sécurité/qualité externe, 2026-09-28, item
    P0-3 : sans ce nettoyage, le fichier reste sur disque indéfiniment,
    sans aucune ligne en base pour le retrouver ni le supprimer). Best-
    effort : une erreur de suppression ne doit ni masquer l'exception
    d'origine ni empêcher son propre appelant de la relever."""
    if not rel_path:
        return
    # Garde-fou (revérification du 2026-09-29) : ne jamais supprimer un
    # fichier situé en dehors d'UPLOAD_DIR. Aujourd'hui rel_path vient
    # toujours de save_upload() (sous-dossier construit avec des ids
    # entiers + nom UUID), donc pas exploitable en l'état — mais un
    # chemin du type "../../etc/passwd" passé par erreur par un futur
    # appelant supprimerait réellement ce fichier (vérifié en bac à
    # sable). On résout le chemin réel et on refuse tout ce qui sort du
    # dossier d'uploads.
    base = os.path.realpath(current_app.config["UPLOAD_DIR"])
    abs_path = os.path.realpath(os.path.join(base, rel_path))
    if os.path.commonpath([base, abs_path]) != base or abs_path == base:
        return
    try:
        os.remove(abs_path)
    except OSError:
        pass

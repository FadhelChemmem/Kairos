"""Stockage des pièces jointes (tâches/posts) sur disque, en dehors de la
base — seuls le nom d'origine et le chemin relatif sont enregistrés dans
`tache_piece_jointe` / `post_piece_jointe` (voir schema.sql).

Chaque fichier est sauvegardé sous un nom généré (uuid) pour éviter toute
collision ou tout risque lié à un nom de fichier fourni par l'utilisateur,
tout en gardant le nom d'origine affiché dans l'interface.
"""
import logging
import os
import re
import time
import uuid

from flask import current_app

logger = logging.getLogger(__name__)

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


def est_vraie_image(file_storage) -> bool:
    """Lot 20 (revue 16e) : photo de profil non vide et dont le contenu est
    bien une image JPEG, PNG, GIF ou WEBP. Lot 21 (revue R30) : la structure
    est contrôlée, pas seulement les premiers octets — en-tête et fin du
    format (PNG : bloc IHDR puis IEND ; JPEG : marqueurs SOI et EOI ; GIF :
    terminateur ; WEBP : taille RIFF exacte), ce qui écarte un fichier
    texte ou HTML qui commence par une fausse signature."""
    flux = file_storage.stream
    try:
        position = flux.tell()
        donnees = flux.read(MAX_OCTETS_AVATAR + 1)
        flux.seek(position)
    except (OSError, ValueError, AttributeError):
        return False
    if not donnees or len(donnees) > MAX_OCTETS_AVATAR:
        return False
    if donnees.startswith(b"\x89PNG\r\n\x1a\n"):
        return donnees[12:16] == b"IHDR" and donnees.rstrip(b"\x00")[-8:-4] == b"IEND"
    # Lot 24 (contre-expertise SR-01) : des images valides étaient refusées
    # — JPEG suivi de données après sa fin (certains appareils), GIF dont la
    # largeur ou la palette contient l'octet « < ». On cherche désormais de
    # vraies balises HTML en tête de fichier.
    if _BALISE_HTML.search(donnees[:1024]):
        return False
    # Lot 25 (RS-08) : un script plus loin dans le fichier (après 1 Ko) est
    # refusé aussi — seules les balises longues sont cherchées partout (une
    # suite de 7 octets ou plus ne se trouve pas par hasard dans une image).
    if _SCRIPT_PARTOUT.search(donnees):
        return False
    if donnees.startswith(b"\xff\xd8\xff"):
        return b"\xff\xd9" in donnees[3:]
    if donnees[:6] in (b"GIF87a", b"GIF89a"):
        return len(donnees) > 13 and donnees.rstrip(b"\x00")[-1:] == b"\x3b"
    if donnees[:4] == b"RIFF" and donnees[8:12] == b"WEBP":
        return int.from_bytes(donnees[4:8], "little") + 8 == len(donnees)
    return False


# Lot 25 (UT-06) : seulement les balises actives — « <meta », « <html »,
# « <head » se trouvent dans des métadonnées JPEG légitimes ; la photo est
# de toute façon servie avec son type d'image et « nosniff ».
_BALISE_HTML = re.compile(rb"<\s*/?\s*(script|svg|iframe|object|embed)\b", re.IGNORECASE)
_SCRIPT_PARTOUT = re.compile(rb"<\s*(script|iframe|object|embed)[\s>/]", re.IGNORECASE)

# Photo de profil : 10 Mo au plus (au-delà, refusée).
MAX_OCTETS_AVATAR = 10 * 1024 * 1024


def refus_fichier(file_storage) -> str | None:
    """Lot 18 (audit sécurité) : message de refus d'un fichier à joindre, ou
    None s'il est acceptable — extension hors de la liste blanche, ou fichier
    vide. Appelé AVANT save_upload() par toutes les routes qui reçoivent une
    pièce jointe (posts, commentaires, tâches)."""
    nom = (file_storage.filename or "").replace("\x00", "")
    if os.path.splitext(nom)[1].lower() not in PIECE_JOINTE_EXTENSIONS:
        return f"Type de fichier non accepté\u00a0: «\u00a0{nom[:80]}\u00a0»."
    flux = file_storage.stream
    try:
        position = flux.tell()
        flux.seek(0, os.SEEK_END)
        taille = flux.tell()
        flux.seek(position)
    except (OSError, ValueError, AttributeError):
        return None
    if taille == 0:
        return f"Le fichier «\u00a0{nom[:80]}\u00a0» est vide."
    return None


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
    nom_brut = (file_storage.filename or "fichier").replace("\x00", "")
    if len(nom_brut) > 255:
        # nom_fichier est un VARCHAR(255) : au-delà, erreur 500 à l'INSERT.
        racine, extension = os.path.splitext(nom_brut)
        extension = extension[:20]
        nom_brut = racine[:255 - len(extension)] + extension
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


# Lot 15 : pièces jointes retirées (ou d'un post supprimé) effacées du
# disque 30 jours après. Pas de planificateur : la purge part d'une requête
# ordinaire (GET réussi d'une personne connectée), au plus une fois toutes les
# 6 heures par processus ; idempotente si deux processus la font en même temps.
INTERVALLE_PURGE = 6 * 3600
_derniere_purge = None


def purger_pieces_retirees() -> int:
    from .repositories import posts as posts_repo

    chemins = posts_repo.purger_pieces_retirees()
    for chemin in chemins:
        delete_upload(chemin)
    return len(chemins)


def purger_si_du() -> None:
    global _derniere_purge
    maintenant = time.monotonic()
    if _derniere_purge is not None and maintenant - _derniere_purge < INTERVALLE_PURGE:
        return
    _derniere_purge = maintenant
    try:
        n = purger_pieces_retirees()
        if n:
            logger.info("Purge : %s pièce(s) jointe(s) retirée(s) depuis 30 jours effacée(s).", n)
    except Exception:  # jamais d'erreur visible pour la personne
        logger.exception("Purge des pièces jointes retirées impossible")

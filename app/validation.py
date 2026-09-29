"""Contrôle des saisies (retour Fadhel, lot 8 : « Vérifier les saisies,
toutes les saisies »).

Une seule place pour les règles communes aux formulaires — longueurs
maximales (celles des colonnes de schema.sql, pour ne plus jamais laisser
Postgres refuser une valeur trop longue en erreur brute), dates
plausibles, email, téléphone. Chaque fonction renvoie un message d'erreur
prêt à afficher (flash), ou None si la valeur est acceptable : la route
garde la main sur l'ordre des contrôles et la redirection.
"""
import datetime
import re

# Longueurs maximales (schema.sql).
MAX_NOM_PROJET = 200
MAX_CLIENT = 150
MAX_TITRE_TACHE = 255
MAX_PRENOM_NOM = 100
MAX_POSTE = 150
MAX_EMAIL = 255
MAX_TELEPHONE = 30
# Colonnes TEXT : bornes applicatives raisonnables (un post n'est pas un
# document ; un texte collé par erreur ne doit pas encombrer le fil).
MAX_CONTENU_POST = 10000
MAX_OBJET_REQUETE = 200
MAX_COMMENTAIRE = 5000
MAX_LIEN = 2000
MAX_ADRESSE = 500
MAX_CHAMPS_PERSO = 30
MAX_CHAMP_PERSO_NOM = 100
MAX_CHAMP_PERSO_VALEUR = 500

# Dates plausibles pour un projet, une tâche ou une embauche : attrape les
# fautes de frappe (« 0202 » au lieu de « 2026 », « 20266 »).
DATE_MIN = datetime.date(1990, 1, 1)
DATE_MAX = datetime.date(2100, 12, 31)

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_TELEPHONE = re.compile(r"[0-9+ ().\-/]*")


def trop_long(valeur: str | None, maximum: int, libelle: str) -> str | None:
    if valeur and len(valeur) > maximum:
        return f"{libelle} : {maximum} caractères au plus."
    return None


def date_hors_bornes(d: datetime.date | None, libelle: str) -> str | None:
    if d is not None and not (DATE_MIN <= d <= DATE_MAX):
        return f"{libelle} invalide ({d.strftime('%d/%m/%Y')}) : vérifiez l'année."
    return None


def ordre_dates(debut: datetime.date | None, fin: datetime.date | None,
                libelle_debut: str, libelle_fin: str) -> str | None:
    """`fin` ne peut pas précéder `debut` (quand les deux sont connues)."""
    if debut is not None and fin is not None and fin < debut:
        return (f"{libelle_fin} ({fin.strftime('%d/%m/%Y')}) antérieure à "
                f"{libelle_debut} ({debut.strftime('%d/%m/%Y')}).")
    return None


def email_invalide(email: str) -> str | None:
    if len(email) > MAX_EMAIL or not _EMAIL.fullmatch(email):
        return "Adresse email invalide."
    return None


def telephone_invalide(telephone: str | None) -> str | None:
    if telephone and (len(telephone) > MAX_TELEPHONE or not _TELEPHONE.fullmatch(telephone)):
        return f"Téléphone invalide (chiffres, espaces, + ( ) . - /, {MAX_TELEPHONE} caractères au plus)."
    return None


def premiere_erreur(*messages: str | None) -> str | None:
    """Premier message non vide d'une suite de contrôles."""
    return next((m for m in messages if m), None)

"""« Aujourd'hui » centralisé (lot 12).

Toute la logique métier qui dépend de la date du jour passe par ici :
Daily log (fenêtre de 14 jours, jour futur, jours manqués, rappels),
échéances (« en retard de N j », Deadlines, calendrier), dates proposées
dans les formulaires. Côté base, fn_aujourdhui (migration 0018) joue le
même rôle pour les gardes (fn_dailylog_garde) et les dates posées par
l'appli (clôture d'une tâche ou d'un projet).

Date simulée (KAIROS_MODE_TEST=true seulement, voir app/modes_admin.py) :
pour la session de l'Admin qui l'a choisie, `aujourdhui()` rend cette date
au lieu de la vraie ; l'heure reste l'heure réelle (le rappel « aujourd'hui
compte à partir de 16 h » garde son sens). Hors requête (scripts, CLI) ou
sans date simulée : la vraie date. Les horodatages enregistrés (created_at,
journal d'audit) ne passent jamais par ici et restent réels.
"""
import datetime
from zoneinfo import ZoneInfo

FUSEAU_DEFAUT = "Africa/Tunis"


def date_simulee() -> datetime.date | None:
    """Date simulée de la requête en cours (posée par modes_admin.appliquer
    sur `g`, seulement en mode test et pour un Admin), None sinon."""
    from flask import g, has_request_context

    if not has_request_context():
        return None
    valeur = g.get("date_simulee")
    return valeur if isinstance(valeur, datetime.date) else None


def maintenant(fuseau: str | ZoneInfo | None = None) -> datetime.datetime:
    """Heure locale réelle au fuseau donné (Tunis par défaut), portée à la
    date simulée si elle existe."""
    zone = fuseau if isinstance(fuseau, ZoneInfo) else ZoneInfo(fuseau or FUSEAU_DEFAUT)
    reel = datetime.datetime.now(datetime.timezone.utc).astimezone(zone)
    simulee = date_simulee()
    if simulee is None:
        return reel
    return reel.replace(year=simulee.year, month=simulee.month, day=simulee.day)


def aujourdhui(fuseau: str | ZoneInfo | None = None) -> datetime.date:
    """« Aujourd'hui » au fuseau donné (Tunis par défaut), ou la date simulée."""
    return maintenant(fuseau).date()

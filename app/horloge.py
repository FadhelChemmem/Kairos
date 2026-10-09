"""« Aujourd'hui » centralisé (lot 12, instant simulé : lot 13).

Toute la logique métier qui dépend de la date du jour passe par ici :
Daily log (fenêtre de 14 jours, jour futur, jours manqués, rappels),
échéances (« en retard de N j », Deadlines, calendrier), dates proposées
dans les formulaires. Côté base, fn_aujourdhui (migrations 0018, 0019) joue
le même rôle pour les gardes (fn_dailylog_garde) ; fn_date_ecriture donne
la date d'une clôture (tâche, projet).

Instant simulé (KAIROS_MODE_TEST=true seulement, voir app/modes_admin.py) :
pour la session de l'Admin qui l'a choisi, « maintenant » est un instant
fixé à Tunis — la date choisie et l'heure choisie, ou à défaut l'heure
réelle de Tunis ce jour-là — lu ensuite au fuseau de chacun (23 h 30 à
Tunis = 19 h 30 à Cayenne, même jour ; 2 h à Tunis = la veille à Cayenne).
Hors requête (scripts, CLI) ou sans simulation : l'heure réelle. Les
horodatages enregistrés (created_at, journal d'audit) ne passent jamais par
ici et restent réels.

« Aujourd'hui » sans fuseau précisé : celui de la personne connectée (ou du
compte vu / agi), à défaut Tunis (lot 13, audit temps T-M3).

`aujourdhui_reel` donne la vraie date, jamais simulée : une écriture datée
après elle est refusée, même en mode test (décision 5 du lot 13).
"""
import datetime
from zoneinfo import ZoneInfo

FUSEAU_DEFAUT = "Africa/Tunis"
FUSEAUX_CONNUS = ("Africa/Tunis", "America/Cayenne")


def _contexte_requete() -> bool:
    try:
        from flask import has_request_context
    except ImportError:  # pragma: no cover - Flask est toujours là dans l'appli
        return False
    return has_request_context()


def date_simulee() -> datetime.date | None:
    """Date simulée de la requête en cours (posée par modes_admin.appliquer
    sur `g`, seulement en mode test et pour un Admin), None sinon."""
    if not _contexte_requete():
        return None
    from flask import g

    valeur = g.get("date_simulee")
    return valeur if isinstance(valeur, datetime.date) else None


def heure_simulee() -> datetime.time | None:
    """Heure simulée (à Tunis) choisie avec la date, None sinon."""
    if date_simulee() is None:
        return None
    from flask import g

    valeur = g.get("heure_simulee")
    return valeur if isinstance(valeur, datetime.time) else None


def _zone(fuseau: str | ZoneInfo | None) -> ZoneInfo:
    if isinstance(fuseau, ZoneInfo):
        return fuseau
    if fuseau is None and _contexte_requete():
        from flask import g

        user = g.get("user")
        fuseau = user.get("fuseau") if isinstance(user, dict) else None
        if fuseau not in FUSEAUX_CONNUS:
            fuseau = None
    return ZoneInfo(fuseau or FUSEAU_DEFAUT)


def instant_simule() -> datetime.datetime | None:
    """Instant simulé (aware, fuseau de Tunis), None sans simulation."""
    jour = date_simulee()
    if jour is None:
        return None
    tunis = ZoneInfo(FUSEAU_DEFAUT)
    heure = heure_simulee()
    if heure is None:
        heure = datetime.datetime.now(datetime.timezone.utc).astimezone(tunis).time().replace(microsecond=0)
    return datetime.datetime.combine(jour, heure, tzinfo=tunis)


def maintenant_reel(fuseau: str | ZoneInfo | None = None) -> datetime.datetime:
    """Heure locale réelle au fuseau donné (celui de la personne, à défaut Tunis)."""
    return datetime.datetime.now(datetime.timezone.utc).astimezone(_zone(fuseau))


def maintenant(fuseau: str | ZoneInfo | None = None) -> datetime.datetime:
    """Heure locale au fuseau donné (celui de la personne, à défaut Tunis) :
    l'instant simulé s'il existe, sinon l'heure réelle."""
    simule = instant_simule()
    if simule is None:
        return maintenant_reel(fuseau)
    return simule.astimezone(_zone(fuseau))


def aujourdhui(fuseau: str | ZoneInfo | None = None) -> datetime.date:
    """« Aujourd'hui » au fuseau donné (celui de la personne, à défaut
    Tunis), date simulée comprise."""
    return maintenant(fuseau).date()


def aujourdhui_reel(fuseau: str | ZoneInfo | None = None) -> datetime.date:
    """La vraie date au fuseau donné, jamais simulée."""
    return maintenant_reel(fuseau).date()


def date_ecriture(fuseau: str | ZoneInfo | None = None) -> datetime.date:
    """Date posée par une écriture (même règle que fn_date_ecriture) : la
    date simulée si elle est passée, jamais après la vraie date."""
    return min(aujourdhui(fuseau), aujourdhui_reel(fuseau))

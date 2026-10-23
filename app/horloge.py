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
    """Instant simulé (aware, fuseau de Tunis), None sans simulation.

    Lot 21 (revue R10) : à la microseconde, et une heure choisie AVANCE avec
    le temps réel écoulé depuis qu'elle a été posée — un blocage puis une
    création de tâche ne tombent plus au même instant figé.

    Lot 24 (contre-expertise N-HORL, SA-01, SB-05, HD-03 à HD-05) :
    - sans heure choisie, l'heure de départ est l'heure réelle de Tunis au
      moment où la date a été posée, puis elle avance de même (plus de recul
      de 24 h au passage de minuit réel) ;
    - à l'approche de minuit simulé, le temps simulé ralentit (mille fois
      plus lent à partir de 23:59:00) au lieu de se figer : les gestes
      restent dans le jour simulé et dans l'ordre, sur plus de 16 h de
      session ;
    - une date posée avant ce lot (sans `pose_le`) compte comme posée au
      premier passage (modes_admin.appliquer)."""
    jour = date_simulee()
    if jour is None:
        return None
    tunis = ZoneInfo(FUSEAU_DEFAUT)
    heure = heure_simulee()
    reel = datetime.datetime.now(datetime.timezone.utc)
    from flask import g

    pose = g.get("simulation_posee_le")
    if not isinstance(pose, (int, float)) or isinstance(pose, bool):
        pose = None
    if heure is None:
        depart = datetime.datetime.fromtimestamp(pose, tunis) if pose is not None else reel.astimezone(tunis)
        # Lot 25 (SB-04) : posée dans la dernière minute réelle avant
        # minuit, la date part au plus tard de 23:59:00 (elle se figeait).
        heure = min(depart.time(), SEUIL_RALENTI)
    instant = datetime.datetime.combine(jour, heure, tzinfo=tunis)
    if pose is None:
        return instant
    return _jamais_en_arriere(avancer(instant, max(0.0, reel.timestamp() - pose)))


SEUIL_RALENTI = datetime.time(23, 59)
FACTEUR_RALENTI = 1000
_FENETRE = 59.999        # secondes de 23:59:00 à 23:59:59.999 (la dernière ms reste au garde-fou)


def avancer(instant: datetime.datetime, ecoule: float) -> datetime.datetime:
    """Instant simulé posé à `instant`, `ecoule` secondes réelles plus tard :
    il avance au rythme réel jusqu'à 23:59:00 du jour simulé, puis de plus
    en plus lentement (d'abord mille fois plus lent), sans jamais passer au
    lendemain. Lot 25 (SA-L25-02) : la dernière minute est approchée sans
    être atteinte (plus de blocage à 23:59:59.999999 après 16 h 40)."""
    jour, tz = instant.date(), instant.tzinfo
    seuil = datetime.datetime.combine(jour, SEUIL_RALENTI, tzinfo=tz)
    if instant < seuil:
        avant_seuil = (seuil - instant).total_seconds()
        if ecoule <= avant_seuil:
            return instant + datetime.timedelta(seconds=ecoule)
        instant, ecoule = seuil, ecoule - avant_seuil
    deja = (instant - seuil).total_seconds()
    tau = _FENETRE * FACTEUR_RALENTI
    # Temps « équivalent » déjà écoulé dans la fenêtre, puis approche
    # asymptotique : pente initiale 1/1000, jamais la fin de la fenêtre.
    if deja >= _FENETRE:
        return datetime.datetime.combine(jour, datetime.time(23, 59, 59, 999000), tzinfo=tz)
    e0 = tau * deja / (_FENETRE - deja)
    e = e0 + ecoule
    return seuil + datetime.timedelta(seconds=_FENETRE * e / (e + tau))


def _jamais_en_arriere(instant: datetime.datetime) -> datetime.datetime:
    """Lot 25 (SA-L25-02, SB-04) : deux instants simulés successifs d'une
    même session ne sont jamais égaux ni décroissants (au moins une
    microseconde d'écart), toujours dans le jour simulé — un blocage puis
    une création de tâche restent dans l'ordre même après des jours."""
    try:
        from flask import session
        cle = "instant_simule_dernier"
        dernier = session.get(cle)
        jour = instant.date().isoformat()
        fin = datetime.datetime.combine(instant.date(), datetime.time.max, tzinfo=instant.tzinfo)
        if isinstance(dernier, dict) and dernier.get("jour") == jour and isinstance(dernier.get("t"), (int, float)):
            precedent = datetime.datetime.fromtimestamp(dernier["t"], instant.tzinfo)
            if instant <= precedent:
                instant = min(precedent + datetime.timedelta(microseconds=1), fin)
        session[cle] = {"jour": jour, "t": instant.timestamp()}
    except Exception:
        pass
    return instant


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

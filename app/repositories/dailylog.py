"""Daily log v9 (lot 10, maquette validée par Fadhel le 2026-10-06).

Un seul état par jour et par personne : {date, statut, lignes, version}.
- Les heures restent stockées en `dailylog_entree.heures` NUMERIC(4,2)
  (lues telles quelles par les vues d'heures, les profils, l'export et la
  reprise Chronos) ; l'API et l'écran parlent en MINUTES entières, la
  conversion se fait ici (minutes / 60, exact pour un multiple de 30).
- `dailylog_jour` porte l'absence et la version (verrou optimiste,
  migration 0014) ; `dailylog_preference` l'objectif de journée, réglage
  personnel.
- « Aujourd'hui » se calcule au fuseau de la personne (Tunis ou Guyane).

Les règles d'écriture (pas de 30 min, 10 h, fenêtre de 14 jours, droits du
chef et de l'Admin) sont validées par la route sur l'état VERROUILLÉ (voir
`enregistrer_jour`) ; la migration 0014 en double l'essentiel en base.
"""
import datetime
from zoneinfo import ZoneInfo

from .. import db, horloge
from ._like import motif_recherche

PAS_MINUTES = 30
MAX_MINUTES_JOUR = 600
OBJECTIF_MIN, OBJECTIF_MAX, OBJECTIF_DEFAUT = 240, 600, 480
FENETRE_LIBRE_JOURS = 14          # aujourd'hui et les 14 jours précédents
FENETRE_COPIE_JOURS = 62          # « Copier le … » : dernier jour rempli, 2 mois au plus
HEURE_ALERTE_AUJOURDHUI = 16      # aujourd'hui compte comme « manqué » à partir de 16 h (heure locale)
FUSEAU_DEFAUT = "Africa/Tunis"
# Bureaux (gérant, lot 10) : Tunis par défaut, Guyane modifiable par l'Admin/le RH.
FUSEAUX = {"Africa/Tunis": "Tunis (UTC+1)", "America/Cayenne": "Guyane (UTC−3)"}
ETATS_SAISISSABLES = ("en_cours", "bloque")   # Bloqué reste saisissable (gérant, lot 10)
ETATS_CLOS = ("termine", "abandonne")         # saisissables jusqu'à leur date de clôture incluse
ETATS_TACHE_PROPOSES = ("en_cours", "bloque")


class VersionPerimee(Exception):
    """La version envoyée n'est plus celle du jour (autre onglet, autre
    appareil, correction du chef) : la route répond 409."""

    def __init__(self, version_actuelle: int):
        super().__init__("version périmée")
        self.version_actuelle = version_actuelle


class SaisieRefusee(Exception):
    """Une ou plusieurs règles refusent l'enregistrement : la route répond
    422 avec la liste `erreurs` (codes stables, voir routes/dailylog.py)."""

    def __init__(self, erreurs: list[dict]):
        super().__init__("saisie refusée")
        self.erreurs = erreurs


# ---------------------------------------------------------------------
# Dates et fuseaux
# ---------------------------------------------------------------------
def _zone(user: dict) -> ZoneInfo:
    fuseau = (user or {}).get("fuseau") or FUSEAU_DEFAUT
    return ZoneInfo(fuseau if fuseau in FUSEAUX else FUSEAU_DEFAUT)


def maintenant_pour(user: dict, maintenant: datetime.datetime | None = None) -> datetime.datetime:
    """Heure locale du bureau de la personne. `maintenant` (injectable pour
    les tests) : un datetime aware, ou naïf compris en UTC. Sans lui :
    app/horloge.py (lot 12), qui porte l'heure réelle à la date simulée de
    l'Admin en mode test."""
    if maintenant is None:
        return horloge.maintenant(_zone(user))
    if maintenant.tzinfo is None:
        maintenant = maintenant.replace(tzinfo=datetime.timezone.utc)
    return maintenant.astimezone(_zone(user))


def aujourdhui_pour(user: dict, maintenant: datetime.datetime | None = None) -> datetime.date:
    """« Aujourd'hui » au fuseau de la personne : de 20 h à minuit en
    Guyane, Tunis est déjà au lendemain (4 h d'écart). Date simulée de
    l'Admin en mode test (lot 12) : cette date, pour tout le monde."""
    return maintenant_pour(user, maintenant).date()


def aujourdhui_reel_pour(user: dict) -> datetime.date:
    """La vraie date au fuseau de la personne, jamais simulée (lot 13 :
    aucune écriture datée après elle, même en mode test)."""
    return horloge.aujourdhui_reel(_zone(user))


def debut_daily_log(user: dict) -> datetime.date | None:
    """Premier jour où un oubli peut être reproché : la date d'embauche, à
    défaut la création du compte (pas de rappel pour un jour où la personne
    n'était pas encore là)."""
    user = user or {}
    debut = user.get("debut_daily_log") or user.get("date_embauche")
    if debut is None and user.get("created_at") is not None:
        debut = user["created_at"]
    if isinstance(debut, datetime.datetime):
        debut = debut.date()
    return debut


def jour_ouvre_precedent(jour: datetime.date) -> datetime.date:
    """Dernier jour ouvré avant `jour` (le lundi : le vendredi)."""
    precedent = jour - datetime.timedelta(days=1)
    while precedent.weekday() >= 5:
        precedent -= datetime.timedelta(days=1)
    return precedent


def heures_en_minutes(heures) -> int:
    return int(round(float(heures) * 60))


# Même table que fn_sans_accents (migration 0014).
_ACCENTS = str.maketrans(
    "àáâãäåçèéêëìíîïñòóôõöùúûüýÿœæÀÁÂÃÄÅÇÈÉÊËÌÍÎÏÑÒÓÔÕÖÙÚÛÜÝ",
    "aaaaaaceeeeiiiinooooouuuuyyoaaaaaaaceeeeiiiinooooouuuuy",
)


def sans_accents(texte: str) -> str:
    return (texte or "").lower().translate(_ACCENTS)


def motif_sans_accents(texte: str) -> str:
    """Motif LIKE littéral (« % », « _ » et « \\ » tapés ne sont pas des
    jokers), sans accents ni casse, à comparer à fn_sans_accents(...)."""
    t = sans_accents((texte or "").strip())
    t = t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{t}%"


# ---------------------------------------------------------------------
# Lectures pour les autres pages (profils, accueil, rappel)
# ---------------------------------------------------------------------
def list_entrees_jour(user_id: int, date) -> list[dict]:
    sql = """
        SELECT d.id, d.projet_id, d.tache_id, d.heures,
               p.code AS projet_code, p.nom AS projet_nom, t.titre AS tache_titre
        FROM dailylog_entree d
        JOIN projet p ON p.id = d.projet_id
        LEFT JOIN tache t ON t.id = d.tache_id
        WHERE d.utilisateur_id = %s AND d.date = %s
        ORDER BY d.id
    """
    return db.query_all(sql, (user_id, date))


def list_entrees_periode(user_id: int, debut, fin) -> list[dict]:
    """Toutes les lignes d'une période en UNE requête (les profils en
    faisaient une par jour : jusqu'à 84 pour « 12 semaines »)."""
    sql = """
        SELECT d.id, d.date, d.projet_id, d.tache_id, d.heures,
               p.code AS projet_code, p.nom AS projet_nom, t.titre AS tache_titre
        FROM dailylog_entree d
        JOIN projet p ON p.id = d.projet_id
        LEFT JOIN tache t ON t.id = d.tache_id
        WHERE d.utilisateur_id = %s AND d.date BETWEEN %s AND %s
        ORDER BY d.date, d.id
    """
    return db.query_all(sql, (user_id, debut, fin))


def jours_absents(user_id: int, debut, fin) -> set:
    rows = db.query_all(
        "SELECT date FROM dailylog_jour WHERE utilisateur_id = %s AND absent AND date BETWEEN %s AND %s",
        (user_id, debut, fin),
    )
    return {r["date"] for r in rows}


def jours_renseignes(user_id: int, jours: list) -> set:
    """Jours (parmi `jours`) où la personne a saisi des heures OU s'est
    marquée absente : ni l'un ni l'autre n'est un oubli."""
    if not jours:
        return set()
    rows = db.query_all(
        """
        SELECT DISTINCT date FROM dailylog_entree WHERE utilisateur_id = %s AND date = ANY(%s)
        UNION
        SELECT date FROM dailylog_jour WHERE utilisateur_id = %s AND date = ANY(%s) AND absent
        """,
        (user_id, list(jours), user_id, list(jours)),
    )
    return {r["date"] for r in rows}


def jour_renseigne(user_id: int, date) -> bool:
    return date in jours_renseignes(user_id, [date])


def jours_manques_recents(
    user: dict, aujourdhui: datetime.date | None = None, maintenant: datetime.datetime | None = None,
    fenetre_jours: int = FENETRE_LIBRE_JOURS, heure_alerte_aujourdhui: int = HEURE_ALERTE_AUJOURDHUI,
) -> list:
    """Jours ouvrés (lun-ven) des `fenetre_jours` derniers jours sans heures
    ni absence — carte de l'accueil, bannière et calendrier du Daily log.
    - Les week-ends vides ne sont jamais des oublis (gérant, lot 10).
    - Aujourd'hui ne compte qu'à partir de 16 h, heure LOCALE de la personne.
    - Rien avant sa date d'arrivée (embauche, à défaut création du compte).
    `user` : dict avec au moins `id` (et `fuseau`, `debut_daily_log`)."""
    if maintenant is None:
        maintenant = maintenant_pour(user)
    elif maintenant.tzinfo is not None:
        maintenant = maintenant.astimezone(_zone(user))
    aujourdhui = aujourdhui or maintenant.date()
    jours = [aujourdhui - datetime.timedelta(days=i) for i in range(1, fenetre_jours + 1)]
    jours = [j for j in jours if j.weekday() < 5]
    if aujourdhui.weekday() < 5 and maintenant.hour >= heure_alerte_aujourdhui:
        jours.append(aujourdhui)
    debut = debut_daily_log(user)
    if debut is not None:
        jours = [j for j in jours if j >= debut]
    if not jours:
        return []
    remplis = jours_renseignes(user["id"], jours)
    return sorted(j for j in jours if j not in remplis)


def etats_mois(user: dict, premier, dernier, manques: list | None = None,
               aujourdhui: datetime.date | None = None) -> dict:
    """{date iso: 'rempli' | 'absent' | 'vide' | 'verrouille'} entre deux
    dates (requête par plage : l'index (utilisateur_id, date, …) sert).
    'vide' : jour ouvré oublié de la fenêtre de rappel (`manques`, voir
    jours_manques_recents). 'verrouille' (lot 13, audit temps T-M8) : jour
    ouvré oublié AVANT la fenêtre de 14 jours (seuls le chef ou l'Admin
    peuvent encore le remplir), depuis l'arrivée de la personne — avec
    `aujourdhui`. Week-ends et jours futurs : pas d'entrée."""
    rows = db.query_all(
        """
        SELECT date, 'rempli' AS etat FROM dailylog_entree
         WHERE utilisateur_id = %s AND date BETWEEN %s AND %s GROUP BY date
        UNION ALL
        SELECT date, 'absent' FROM dailylog_jour
         WHERE utilisateur_id = %s AND date BETWEEN %s AND %s AND absent
        """,
        (user["id"], premier, dernier, user["id"], premier, dernier),
    )
    etats = {}
    for r in rows:
        cle = r["date"].isoformat()
        etats[cle] = "absent" if r["etat"] == "absent" else etats.get(cle, "rempli")
    for jour in manques or []:
        if premier <= jour <= dernier:
            etats.setdefault(jour.isoformat(), "vide")
    if aujourdhui is not None:
        limite = min(dernier, aujourdhui - datetime.timedelta(days=FENETRE_LIBRE_JOURS + 1))
        jour = max(premier, debut_daily_log(user) or premier)
        while jour <= limite:
            if jour.weekday() < 5:
                etats.setdefault(jour.isoformat(), "verrouille")
            jour += datetime.timedelta(days=1)
    return etats


# ---------------------------------------------------------------------
# État d'un jour
# ---------------------------------------------------------------------
def lire_jour(user_id: int, date) -> dict:
    """Lignes (en minutes), absence, version et dernier auteur d'un jour."""
    jour = db.query_one(
        """
        SELECT j.absent, j.version, j.updated_at, j.updated_by,
               u.prenom || ' ' || u.nom AS modifie_par
        FROM dailylog_jour j LEFT JOIN utilisateur u ON u.id = j.updated_by
        WHERE j.utilisateur_id = %s AND j.date = %s
        """,
        (user_id, date),
    )
    lignes = db.query_all(
        """
        SELECT d.projet_id, d.tache_id, d.heures, p.code, p.nom, t.titre AS tache_titre
        FROM dailylog_entree d
        JOIN projet p ON p.id = d.projet_id
        LEFT JOIN tache t ON t.id = d.tache_id
        WHERE d.utilisateur_id = %s AND d.date = %s
        ORDER BY d.id
        """,
        (user_id, date),
    )
    out = []
    for ligne in lignes:
        minutes = heures_en_minutes(ligne["heures"])
        out.append({
            "projet_id": ligne["projet_id"], "tache_id": ligne["tache_id"],
            "code": ligne["code"], "nom": ligne["nom"], "tache_titre": ligne["tache_titre"],
            "minutes": minutes, "hors_grille": minutes % PAS_MINUTES != 0,
        })
    absent = bool(jour and jour["absent"])
    return {
        "absent": absent,
        "version": int(jour["version"]) if jour else 0,
        "lignes": out,
        "modifie_par": jour["modifie_par"] if jour else None,
        "modifie_par_id": jour["updated_by"] if jour else None,
        "modifie_le": jour["updated_at"] if jour else None,
    }


def dernier_jour_rempli(user_id: int, avant, depuis):
    """Source de « Copier le … » : dernier jour < `avant` avec des heures
    (un jour absent n'en a pas), pas avant `depuis`. None sinon."""
    row = db.query_one(
        "SELECT max(date) AS d FROM dailylog_entree WHERE utilisateur_id = %s AND date < %s AND date >= %s",
        (user_id, avant, depuis),
    )
    return row["d"] if row else None


def projets_info(projet_ids, proprietaire_id: int, acteur_id: int) -> dict:
    """Un seul SELECT pour toutes les lignes d'un jour (fin du N+1, audit
    n°23) : état, dates, visibilité pour le PROPRIÉTAIRE des heures et pour
    l'ACTEUR, gestion par l'acteur (chef titulaire ou co-chef)."""
    ids = sorted({int(i) for i in projet_ids})
    if not ids:
        return {}
    rows = db.query_all(
        """
        SELECT p.id, p.code, p.nom, p.etat, p.date_debut, p.date_cloture,
               EXISTS (SELECT 1 FROM v_projet_visibilite v
                        WHERE v.projet_id = p.id AND v.utilisateur_id = %(proprio)s) AS visible,
               EXISTS (SELECT 1 FROM v_projet_visibilite v
                        WHERE v.projet_id = p.id AND v.utilisateur_id = %(acteur)s) AS visible_acteur,
               -- Lot 20 : retirée d'un projet d'une autre équipe → plus
               -- d'heures nouvelles (lecture seule).
               EXISTS (SELECT 1 FROM v_projet_action v
                        WHERE v.projet_id = p.id AND v.utilisateur_id = %(proprio)s) AS peut_agir,
               (p.chef_projet_id = %(acteur)s OR EXISTS (
                  SELECT 1 FROM projet_co_chef cc
                   WHERE cc.projet_id = p.id AND cc.utilisateur_id = %(acteur)s)) AS gere
        FROM projet p WHERE p.id = ANY(%(ids)s)
        """,
        {"ids": ids, "proprio": proprietaire_id, "acteur": acteur_id},
    )
    return {r["id"]: dict(r) for r in rows}


def projet_saisissable(projet: dict, date) -> str | None:
    """None si des heures peuvent être posées sur ce projet à cette date,
    sinon le code d'erreur : 'projet_clos' (Terminé/Abandonné après sa date
    de clôture, ou sans date de clôture) ou 'projet_pas_commence'."""
    if projet["etat"] in ETATS_CLOS and (projet.get("date_cloture") is None or date > projet["date_cloture"]):
        return "projet_clos"
    if projet.get("date_debut") and date < projet["date_debut"]:
        return "projet_pas_commence"
    return None


def taches_infos(tache_ids, utilisateur_id: int | None = None) -> dict:
    """{tache_id: {projet_id, ouverte, fermee_le, intervenant}} : projet de la
    tâche, dernier jour où elle était ouverte (lot 20 : pas d'heures
    nouvelles sur une tâche close après sa date de fin ; lot 21 : toute
    tâche close a une date de fin) et si `utilisateur_id` en est
    intervenant (lot 21, revue R9)."""
    ids = sorted({int(i) for i in tache_ids if i})
    if not ids:
        return {}
    return {r["id"]: dict(r) for r in db.query_all(
        """
        SELECT t.id, t.projet_id, (t.etat IN ('en_cours', 'bloque')) AS ouverte,
               COALESCE(t.date_fin, (t.updated_at AT TIME ZONE 'Africa/Tunis')::date) AS fermee_le,
               EXISTS (SELECT 1 FROM tache_intervenant ti
                        WHERE ti.tache_id = t.id AND ti.utilisateur_id = %s) AS intervenant
        FROM tache t WHERE t.id = ANY(%s)
        """, (utilisateur_id, ids))}


def tache_saisissable(info: dict | None, date) -> bool:
    """Heures nouvelles possibles sur cette tâche à `date` : ouverte, ou
    close à cette date ou après (lot 20, rapport de tests N4)."""
    return info is None or info["ouverte"] or (info["fermee_le"] is not None and date <= info["fermee_le"])


def taches_ouvertes(projet_id: int) -> list[dict]:
    """Tâches en cours ou bloquées d'un projet (imputation à une tâche
    précise, gardée par le gérant)."""
    return db.query_all(
        """
        SELECT t.id AS tache_id, t.titre AS tache_titre, t.etat
        FROM tache t
        WHERE t.projet_id = %s AND t.etat IN ('en_cours', 'bloque')
        ORDER BY t.titre, t.id
        LIMIT 200
        """,
        (projet_id,),
    )


# ---------------------------------------------------------------------
# Catalogue « + Ajouter un projet »
# ---------------------------------------------------------------------
_NB_TACHES = """(SELECT count(*) FROM tache tt WHERE tt.projet_id = p.id
                  AND tt.etat IN ('en_cours', 'bloque'))"""


def _ligne_catalogue(r, tache=False) -> dict:
    debut = r.get("date_debut")
    return {
        "projet_id": r["projet_id"], "code": r["code"], "nom": r["nom"],
        "tache_id": r["tache_id"] if tache else None,
        "tache_titre": r["tache_titre"] if tache else None,
        "nb_taches": int(r.get("nb_taches") or 0),
        # Le client ne propose pas, sur un jour antérieur, un projet qui
        # n'avait pas encore commencé (le serveur le refuserait).
        "date_debut": debut.isoformat() if hasattr(debut, "isoformat") else debut,
    }


def list_lignes_suggerees(user_id: int, gere_par: int | None = None) -> dict:
    """Catalogue de l'amorce :
    - `mine` : mes projets (chef, co-chef, intervenant du projet ou d'une
      tâche ouverte) en cours ou bloqués, puis mes tâches ouvertes ;
    - `recentes` : 5 projets où j'ai saisi récemment, hors `mine`.
    Le reste passe par la recherche serveur (`rechercher_projets`).
    `gere_par` (correction par un chef) : seulement les projets que ce chef
    gère, visibles par la personne corrigée. Lot 21 (revue R14) : jamais un
    projet où la personne n'est plus qu'en lecture seule (retirée) — la
    saisie y serait refusée."""
    filtre_gere = ""
    params = {"uid": user_id, "gere": gere_par}
    if gere_par is not None:
        filtre_gere = """AND (p.chef_projet_id = %(gere)s OR EXISTS (
            SELECT 1 FROM projet_co_chef g WHERE g.projet_id = p.id AND g.utilisateur_id = %(gere)s))"""
        projets = db.query_all(
            f"""
            SELECT p.id AS projet_id, p.code, p.nom, p.date_debut, NULL AS tache_id, NULL AS tache_titre,
                   {_NB_TACHES} AS nb_taches
            FROM projet p
            WHERE p.etat IN ('en_cours', 'bloque') {filtre_gere}
              AND EXISTS (SELECT 1 FROM v_projet_action v WHERE v.projet_id = p.id AND v.utilisateur_id = %(uid)s)
            ORDER BY p.nom, p.code
            LIMIT 200
            """,
            params,
        )
        return {"mine": [_ligne_catalogue(r) for r in projets], "recentes": []}

    projets = db.query_all(
        f"""
        SELECT p.id AS projet_id, p.code, p.nom, p.date_debut, NULL AS tache_id, NULL AS tache_titre,
               {_NB_TACHES} AS nb_taches
        FROM projet p
        WHERE p.etat IN ('en_cours', 'bloque')
          AND (
                p.chef_projet_id = %(uid)s
             OR EXISTS (SELECT 1 FROM projet_co_chef cc WHERE cc.projet_id = p.id AND cc.utilisateur_id = %(uid)s)
             OR EXISTS (SELECT 1 FROM projet_intervenant pi WHERE pi.projet_id = p.id AND pi.utilisateur_id = %(uid)s)
             OR EXISTS (SELECT 1 FROM tache t JOIN tache_intervenant ti ON ti.tache_id = t.id
                         WHERE t.projet_id = p.id AND ti.utilisateur_id = %(uid)s
                           AND t.etat IN ('en_cours', 'bloque'))
              )
          AND EXISTS (SELECT 1 FROM v_projet_action v WHERE v.projet_id = p.id AND v.utilisateur_id = %(uid)s)
        ORDER BY p.nom, p.code
        LIMIT 200
        """,
        params,
    )
    taches = db.query_all(
        f"""
        SELECT p.id AS projet_id, p.code, p.nom, p.date_debut, t.id AS tache_id, t.titre AS tache_titre,
               {_NB_TACHES} AS nb_taches
        FROM tache t
        JOIN projet p ON p.id = t.projet_id
        WHERE t.etat IN ('en_cours', 'bloque') AND p.etat IN ('en_cours', 'bloque')
          AND EXISTS (SELECT 1 FROM tache_intervenant ti WHERE ti.tache_id = t.id AND ti.utilisateur_id = %(uid)s)
          AND EXISTS (SELECT 1 FROM v_projet_action v WHERE v.projet_id = p.id AND v.utilisateur_id = %(uid)s)
        ORDER BY p.nom, t.titre
        LIMIT 200
        """,
        params,
    )
    mine = [_ligne_catalogue(r) for r in projets] + [_ligne_catalogue(r, tache=True) for r in taches]
    exclure = sorted({m["projet_id"] for m in mine}) or [0]
    recentes = db.query_all(
        f"""
        SELECT p.id AS projet_id, p.code, p.nom, p.date_debut, NULL AS tache_id, NULL AS tache_titre,
               {_NB_TACHES} AS nb_taches, max(d.date) AS derniere
        FROM dailylog_entree d
        JOIN projet p ON p.id = d.projet_id
        WHERE d.utilisateur_id = %(uid)s AND p.etat IN ('en_cours', 'bloque') AND p.id <> ALL(%(exclure)s)
          AND EXISTS (SELECT 1 FROM v_projet_action v WHERE v.projet_id = p.id AND v.utilisateur_id = %(uid)s)
        GROUP BY p.id, p.code, p.nom, p.date_debut
        ORDER BY derniere DESC
        LIMIT 5
        """,
        {**params, "exclure": exclure},
    )
    return {"mine": mine, "recentes": [_ligne_catalogue(r) for r in recentes]}


# ---------------------------------------------------------------------
# Lignes proposées d'une journée vierge (lot 14, revue produit P0-4 ;
# lot 20, demande du gérant du 19/10)
# ---------------------------------------------------------------------
# L'écran en montre 5, puis 5 de plus à chaque « Afficher plus ».
MAX_PROPOSEES = 60
PROPOSEES_PAR_PAGE = 5


def lignes_proposees(user: dict, date) -> list[dict]:
    """Lignes proposées à 0 h sur une journée vierge (désactivable), dans
    l'ordre où l'écran les montre (5 d'abord, puis 5 par 5) :
    1. ses tâches EN COURS À CETTE DATE (intervenant de la tâche), de la
       plus proche échéance à la plus lointaine (sans échéance à la fin) ;
    2. puis une ligne « projet seul » pour chaque AUTRE projet EN COURS À
       CETTE DATE auquel elle participe (chef, co-chef, intervenant du projet
       ou d'une tâche, ou heures déjà saisies), le plus récemment saisi
       d'abord.
    « En cours à cette date » (lot 20) : quand on revient en arrière dans le
    calendrier, ce sont les tâches et projets ouverts CE JOUR-LÀ, pas
    aujourd'hui : commencés (date de début, à défaut création — une tâche
    créée le lendemain reste proposée, le travail précède souvent sa
    saisie) et pas encore clos (tâche : date de fin ; projet : date de
    clôture). Projets visibles et où elle peut agir (v_projet_action).
    Jamais stockées : la route les joint à l'état du jour."""
    params = {"uid": user["id"], "date": date}
    en_cours_a_la_date = """
        COALESCE(p.date_debut, (p.created_at AT TIME ZONE 'Africa/Tunis')::date) <= %(date)s
        AND (p.etat IN ('en_cours', 'bloque') OR (p.date_cloture IS NOT NULL AND p.date_cloture >= %(date)s))"""
    # Lot 21 (revue R9) : sa tâche reste proposée jusqu'à sa date de fin,
    # même si elle ne lui donne plus que la lecture du projet (autre équipe,
    # tâche close aujourd'hui) ; un projet seul exige le droit d'agir.
    projet_ouvert = """
        EXISTS (SELECT 1 FROM v_projet_action v WHERE v.projet_id = p.id AND v.utilisateur_id = %(uid)s)
        AND """ + en_cours_a_la_date
    taches = db.query_all(
        f"""
        SELECT p.id AS projet_id, p.code, p.nom, t.id AS tache_id, t.titre AS tache_titre
        FROM tache t JOIN projet p ON p.id = t.projet_id
        WHERE EXISTS (SELECT 1 FROM v_projet_visibilite v WHERE v.projet_id = p.id AND v.utilisateur_id = %(uid)s)
          AND {en_cours_a_la_date}
          AND EXISTS (SELECT 1 FROM tache_intervenant ti WHERE ti.tache_id = t.id AND ti.utilisateur_id = %(uid)s)
          AND COALESCE(t.date_debut, (t.created_at AT TIME ZONE 'Africa/Tunis')::date - 1) <= %(date)s
          AND (t.etat IN ('en_cours', 'bloque')
               OR COALESCE(t.date_fin, (t.updated_at AT TIME ZONE 'Africa/Tunis')::date) >= %(date)s)
          -- Lot 23 (retour du gérant) : pas une tâche bloquée ce jour-là
          -- (en attente : on n'y travaille pas) ; bloquée APRÈS ce jour, elle
          -- était encore en cours et reste proposée.
          AND NOT (t.etat = 'bloque' AND COALESCE((t.bloque_le AT TIME ZONE 'Africa/Tunis')::date, %(date)s) <= %(date)s)
        ORDER BY t.date_echeance NULLS LAST, p.code, t.titre, t.id
        LIMIT %(limit)s
        """,
        {**params, "limit": MAX_PROPOSEES},
    )
    projets = db.query_all(
        f"""
        SELECT p.id AS projet_id, p.code, p.nom,
               (SELECT max(d.date) FROM dailylog_entree d
                 WHERE d.utilisateur_id = %(uid)s AND d.projet_id = p.id AND d.date < %(date)s) AS derniere
        FROM projet p
        WHERE {projet_ouvert}
          AND (p.chef_projet_id = %(uid)s
               OR EXISTS (SELECT 1 FROM projet_co_chef cc WHERE cc.projet_id = p.id AND cc.utilisateur_id = %(uid)s)
               OR EXISTS (SELECT 1 FROM projet_intervenant pi WHERE pi.projet_id = p.id AND pi.utilisateur_id = %(uid)s)
               OR EXISTS (SELECT 1 FROM tache t JOIN tache_intervenant ti ON ti.tache_id = t.id
                          WHERE t.projet_id = p.id AND ti.utilisateur_id = %(uid)s)
               OR EXISTS (SELECT 1 FROM dailylog_entree d WHERE d.utilisateur_id = %(uid)s AND d.projet_id = p.id))
        ORDER BY derniere DESC NULLS LAST, p.code
        LIMIT %(limit)s
        """,
        {**params, "limit": MAX_PROPOSEES},
    )
    sortie = [{"projet_id": t["projet_id"], "tache_id": t["tache_id"], "code": t["code"], "nom": t["nom"],
               "tache_titre": t["tache_titre"]} for t in taches]
    # Un projet déjà proposé par une de ses tâches n'a pas en plus sa ligne
    # « projet seul » (« + Ajouter un projet » reste là pour ça).
    avec_tache = {t["projet_id"] for t in taches}
    sortie += [{"projet_id": p["projet_id"], "tache_id": None, "code": p["code"], "nom": p["nom"],
                "tache_titre": None} for p in projets if p["projet_id"] not in avec_tache]
    # Lot 21 (revue, question 15) : 60 tâches au plus, PUIS 60 projets au
    # plus — les projets suivis ne sont plus évincés par les tâches.
    return sortie


# ---------------------------------------------------------------------
# Daily log de l'équipe (lot 14, revue produit P1-9)
# ---------------------------------------------------------------------
def membres_equipe(gere_par: int | None) -> list[dict]:
    """Personnes du « Daily log de l'équipe », actives et avec un Daily log :
    - `gere_par` None (Admin) : tout le bureau — chefs de projet et
      intervenants, plus les Admins qui ont saisi des heures ces 90 derniers
      jours ;
    - sinon (chef de projet) : les personnes de ses projets en cours ou
      bloqués (titulaire ou co-chef) — chef, co-chefs, intervenants du
      projet ou d'une tâche ouverte —, lui compris."""
    colonnes = "u.id, u.prenom, u.nom, u.role, u.poste, u.avatar_chemin, u.fuseau, u.date_embauche, u.created_at"
    if gere_par is None:
        return db.query_all(
            f"""
            SELECT {colonnes} FROM utilisateur u
            WHERE u.actif AND (u.role IN ('chef_de_projet', 'intervenant')
                  OR (u.role = 'admin' AND EXISTS (SELECT 1 FROM dailylog_entree d WHERE d.utilisateur_id = u.id
                                                     AND d.date >= fn_aujourdhui() - 90)))
            ORDER BY u.prenom, u.nom, u.id
            """
        )
    return db.query_all(
        f"""
        WITH mes_projets AS (
            SELECT p.id, p.chef_projet_id FROM projet p
            WHERE p.etat IN ('en_cours', 'bloque')
              AND (p.chef_projet_id = %(moi)s OR EXISTS (SELECT 1 FROM projet_co_chef cc
                     WHERE cc.projet_id = p.id AND cc.utilisateur_id = %(moi)s))
        ), personnes AS (
            SELECT %(moi)s::bigint AS uid
            UNION SELECT chef_projet_id FROM mes_projets
            UNION SELECT cc.utilisateur_id FROM projet_co_chef cc JOIN mes_projets m ON m.id = cc.projet_id
            UNION SELECT pi.utilisateur_id FROM projet_intervenant pi JOIN mes_projets m ON m.id = pi.projet_id
            UNION SELECT ti.utilisateur_id FROM tache_intervenant ti JOIN tache t ON t.id = ti.tache_id
                   JOIN mes_projets m ON m.id = t.projet_id WHERE t.etat IN ('en_cours', 'bloque')
        )
        SELECT {colonnes} FROM utilisateur u JOIN personnes x ON x.uid = u.id
        WHERE u.actif AND u.role IN ('admin', 'chef_de_projet', 'intervenant')
        ORDER BY u.prenom, u.nom, u.id
        """,
        {"moi": gere_par},
    )


def manquants_du_jour(gere_par: int | None, jour) -> list[dict]:
    """Personnes du « Daily log de l'équipe » (membres_equipe, même
    périmètre) dont le jour `jour` est « non renseigné » (etat_case, mêmes
    règles que la colonne de ce jour) : compteur « Daily log manquants » de
    la Vue d'ensemble et de « À traiter » (recette du lot 14, n° 9 — un
    seul périmètre, les mêmes chiffres des deux côtés)."""
    personnes = membres_equipe(gere_par)
    synthese = synthese_periode([p["id"] for p in personnes], jour, jour)
    return [p for p in personnes if etat_case(p, jour, synthese.get((p["id"], jour))) == "manquant"]


def synthese_periode(user_ids, debut, fin) -> dict:
    """{(utilisateur_id, date): {"minutes": n, "absent": bool}} sur une
    période, en une requête (heures et absences de toute l'équipe)."""
    ids = sorted({int(i) for i in user_ids})
    if not ids:
        return {}
    rows = db.query_all(
        """
        SELECT utilisateur_id, date, sum(heures) AS heures, false AS absent FROM dailylog_entree
         WHERE utilisateur_id = ANY(%(ids)s) AND date BETWEEN %(debut)s AND %(fin)s GROUP BY utilisateur_id, date
        UNION ALL
        SELECT utilisateur_id, date, 0, true FROM dailylog_jour
         WHERE utilisateur_id = ANY(%(ids)s) AND date BETWEEN %(debut)s AND %(fin)s AND absent
        """,
        {"ids": ids, "debut": debut, "fin": fin},
    )
    out: dict = {}
    for r in rows:
        case = out.setdefault((r["utilisateur_id"], r["date"]), {"minutes": 0, "absent": False})
        case["minutes"] += heures_en_minutes(r["heures"])
        case["absent"] = case["absent"] or bool(r["absent"])
    return out


def jours_ouvres_recents(aujourdhui, nombre: int = 10) -> list:
    """Les `nombre` derniers jours ouvrés, aujourd'hui compris s'il en est
    un, du plus récent au plus ancien (fiche d'une personne, lot 14)."""
    jours, jour = [], aujourdhui
    while len(jours) < nombre:
        if jour.weekday() < 5:
            jours.append(jour)
        jour -= datetime.timedelta(days=1)
    return jours


def etat_case(user: dict, date, case: dict | None, maintenant: datetime.datetime | None = None) -> str:
    """État d'un jour d'une personne pour les vues d'équipe (lot 14) :
    'rempli', 'absent', 'manquant' (oubli de la fenêtre de rappel),
    'attente' (aujourd'hui avant 16 h), 'verrouille' (oubli au-delà de 14
    jours), 'futur', 'avant' (avant l'arrivée), 'week_end'. Mêmes règles que
    jours_manques_recents (fuseau de la personne)."""
    case = case or {}
    if case.get("minutes"):
        return "rempli"
    if case.get("absent"):
        return "absent"
    maintenant = maintenant_pour(user, maintenant)
    aujourdhui = maintenant.date()
    if date > aujourdhui:
        return "futur"
    if date.weekday() >= 5:
        return "week_end"
    debut = debut_daily_log(user)
    if debut is not None and date < debut:
        return "avant"
    if date == aujourdhui and maintenant.hour < HEURE_ALERTE_AUJOURDHUI:
        return "attente"
    if date < aujourdhui - datetime.timedelta(days=FENETRE_LIBRE_JOURS):
        return "verrouille"
    return "manquant"


def rechercher_projets(q: str, user_id: int, date, gere_par: int | None = None, limit: int = 20) -> list[dict]:
    """Recherche serveur du catalogue (≥ 2 caractères) : code ou nom, sans
    accents ni casse (« ete » trouve « Résidence Été » ; fn_recherche des
    deux côtés depuis le lot 11, comme la recherche globale), jokers LIKE
    littéraux. Projets visibles par la personne dont c'est le Daily log,
    en cours ou bloqués — ou clos au plus tôt à `date` (une saisie
    antidatée sur un projet terminé depuis reste possible)."""
    q = (q or "").strip()
    if not q:
        return []
    filtre_gere = ""
    if gere_par is not None:
        filtre_gere = """AND (p.chef_projet_id = %(gere)s OR EXISTS (
            SELECT 1 FROM projet_co_chef g WHERE g.projet_id = p.id AND g.utilisateur_id = %(gere)s))"""
    rows = db.query_all(
        f"""
        SELECT p.id AS projet_id, p.code, p.nom, p.date_debut, NULL AS tache_id, NULL AS tache_titre,
               {_NB_TACHES} AS nb_taches
        FROM projet p
        WHERE (p.etat IN ('en_cours', 'bloque')
               OR (p.etat IN ('termine', 'abandonne') AND p.date_cloture >= %(date)s))
          AND (p.date_debut IS NULL OR p.date_debut <= %(date)s)
          AND fn_recherche(p.code || ' ' || p.nom) LIKE fn_recherche(%(motif)s)
          AND EXISTS (SELECT 1 FROM v_projet_action v WHERE v.projet_id = p.id AND v.utilisateur_id = %(uid)s)
          {filtre_gere}
        ORDER BY p.nom, p.code
        LIMIT %(limit)s
        """,
        {"date": date, "motif": motif_recherche(q), "uid": user_id, "gere": gere_par, "limit": limit},
    )
    return [_ligne_catalogue(r) for r in rows]


# ---------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------
def enregistrer_jour(user_id: int, date, version_attendue: int, acteur_id: int, preparer) -> dict:
    """Écrit l'état complet d'un jour en UNE transaction, au nom de
    l'acteur (updated_by et audit_log : le chef ou l'Admin qui corrige) :

    1. verrou consultatif (personne, jour) — sérialise deux onglets, même
       quand aucune ligne dailylog_jour n'existe encore ;
    2. version lue sous le verrou ; ≠ `version_attendue` → VersionPerimee ;
    3. `preparer(existantes, absent_actuel)` valide la demande contre l'état
       VERROUILLÉ ({(projet_id, tache_id or 0): minutes}) et rend
       (absent, voulues) — ou lève SaisieRefusee ;
    4. diff : seules les lignes nouvelles, changées ou retirées sont
       écrites (une ligne inchangée garde sa valeur ancienne, hors grille
       comprise, et ne fait pas de bruit dans audit_log) ;
    5. rien ne change → rien n'est écrit, la version ne bouge pas.
    Les triggers différés de 0014 revérifient 10 h et l'absence au COMMIT.
    Retourne {"version": n, "change": bool}."""
    with db.get_cursor(user_id=acteur_id) as cur:
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"kairos:dailylog:{int(user_id)}:{date.isoformat()}",),
        )
        cur.execute("SELECT absent, version FROM dailylog_jour WHERE utilisateur_id = %s AND date = %s",
                    (user_id, date))
        jour = cur.fetchone()
        version = int(jour["version"]) if jour else 0
        absent_actuel = bool(jour and jour["absent"])
        if version != int(version_attendue):
            raise VersionPerimee(version)
        cur.execute(
            "SELECT id, projet_id, tache_id, heures FROM dailylog_entree WHERE utilisateur_id = %s AND date = %s",
            (user_id, date),
        )
        lignes = {(r["projet_id"], r["tache_id"] or 0): r for r in cur.fetchall()}
        existantes = {cle: heures_en_minutes(r["heures"]) for cle, r in lignes.items()}

        absent, voulues = preparer(existantes, absent_actuel)

        change = absent != absent_actuel
        a_supprimer = [r["id"] for cle, r in lignes.items() if cle not in voulues]
        if a_supprimer:
            change = True
            cur.execute("DELETE FROM dailylog_entree WHERE id = ANY(%s)", (a_supprimer,))
        for (projet_id, tache0), minutes in voulues.items():
            if existantes.get((projet_id, tache0)) == minutes:
                continue
            change = True
            cur.execute(
                """
                INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (utilisateur_id, date, projet_id, COALESCE(tache_id, 0))
                DO UPDATE SET heures = EXCLUDED.heures
                """,
                (user_id, date, projet_id, tache0 or None, round(minutes / 60, 2), acteur_id),
            )
        if not change:
            return {"version": version, "change": False}
        cur.execute(
            """
            INSERT INTO dailylog_jour (utilisateur_id, date, absent, version, updated_by)
            VALUES (%s, %s, %s, 1, %s)
            ON CONFLICT (utilisateur_id, date)
            DO UPDATE SET absent = EXCLUDED.absent, version = dailylog_jour.version + 1
            RETURNING version
            """,
            (user_id, date, absent, acteur_id),
        )
        version = int(cur.fetchone()["version"])
        # Jour rempli ou marqué absent : son rappel n'a plus lieu d'être
        # (lot 11), dans la même transaction.
        if absent or voulues:
            from . import notifications
            notifications.marquer_rappels_dailylog_lus(user_id, cur=cur)
        return {"version": version, "change": True}


def get_objectif(user_id: int) -> int:
    row = db.query_one("SELECT objectif_minutes FROM dailylog_preference WHERE utilisateur_id = %s", (user_id,))
    return int(row["objectif_minutes"]) if row else OBJECTIF_DEFAUT


def set_objectif(user_id: int, minutes: int) -> None:
    with db.get_cursor(user_id=user_id) as cur:
        cur.execute(
            """
            INSERT INTO dailylog_preference (utilisateur_id, objectif_minutes) VALUES (%s, %s)
            ON CONFLICT (utilisateur_id)
            DO UPDATE SET objectif_minutes = EXCLUDED.objectif_minutes, updated_at = now()
            """,
            (user_id, minutes),
        )

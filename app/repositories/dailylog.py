"""DailyLog — saisie des heures, façon curseur (voir spec et le prototype
`DailyLog.dc.html`) : une journée entière (plusieurs lignes projet/tâche,
réparties en % de la journée type de 8h) est enregistrée en un seul geste
explicite (`remplacer_jour`), pas ligne par ligne.
"""
from .. import db


def list_projets_pour_dailylog(user_id: int) -> list[dict]:
    """Projets proposés par défaut : ceux où l'utilisateur est intervenant
    sur une tâche en cours, ou qu'il gère (chef/co-chef) avec des tâches
    en cours (voir spec DailyLog)."""
    sql = """
        SELECT DISTINCT p.id, p.code, p.nom
        FROM projet p
        LEFT JOIN projet_co_chef cc ON cc.projet_id = p.id AND cc.utilisateur_id = %(uid)s
        LEFT JOIN tache t ON t.projet_id = p.id AND t.etat NOT IN ('termine', 'abandonne')
        LEFT JOIN tache_intervenant ti ON ti.tache_id = t.id AND ti.utilisateur_id = %(uid)s
        WHERE p.etat = 'en_cours'
          AND (
                (p.chef_projet_id = %(uid)s OR cc.utilisateur_id IS NOT NULL) AND t.id IS NOT NULL
                OR ti.utilisateur_id IS NOT NULL
              )
        ORDER BY p.nom
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"uid": user_id})
        return [dict(r) for r in cur.fetchall()]


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


DUREE_TYPE = 8  # heures — journée type par défaut (voir spec DailyLog)


def get_jour(user_id: int, date) -> dict | None:
    """Réglage de la journée (Daily log v2, migration 0008) : durée et
    absence, ou None si la journée n'a jamais été enregistrée depuis."""
    return db.query_one(
        "SELECT duree_heures, absent FROM dailylog_jour WHERE utilisateur_id = %s AND date = %s",
        (user_id, date),
    )


def duree_et_absence(user_id: int, date, entrees: list[dict]) -> tuple[float, bool]:
    """Durée (heures) et absence à afficher pour ce jour.

    Sans réglage enregistré : 8 h, sauf pour une journée déjà saisie
    avant le Daily log v2 — sa durée vaut alors le total de ses heures
    (option B, 2026-09-29 : on ne modifie jamais des heures déjà
    enregistrées, même quand elles ne faisaient pas une journée
    complète)."""
    jour = get_jour(user_id, date)
    if jour is not None:
        return float(jour["duree_heures"]), bool(jour["absent"])
    total = round(sum(float(e["heures"]) for e in entrees), 2)
    if total > 0:
        # Au quart d'heure le plus proche (relecture du 2026-09-29) : une
        # ancienne journée de 3 × 2,67 h (8,01 h) ne doit pas donner une
        # durée que l'enregistrement refuse ensuite. L'écran répartit alors
        # les lignes sur cette durée (dailylog.html).
        return min(max(round(total * 4) / 4, 0.25), 24.0), False
    return float(DUREE_TYPE), False


def jours_renseignes(user_id: int, jours: list) -> set:
    """Jours (parmi `jours`) où l'utilisateur a saisi des heures OU s'est
    marqué absent — utilisé partout où l'on cherche un jour "oublié"
    (rappel de connexion, bandeau d'hier, carte de l'accueil,
    calendrier)."""
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


def list_projets_recents(user_id: int, exclude_ids: list[int], limit: int = 5) -> list[dict]:
    """Jusqu'à `limit` projets sur lesquels l'utilisateur a le plus
    récemment saisi des heures (historique DailyLog), en excluant ceux déjà
    proposés dans "Vos projets" (`exclude_ids`). Deuxième palier du
    catalogue "Ajouter une ligne" (retour Fadhel, 2026-09-27) : l'utilisateur
    n'a pas à voir tous les projets de l'entreprise d'un coup — seulement
    ceux avec des tâches en cours (`list_projets_pour_dailylog`), puis ceux
    qu'il a récemment touchés, puis une recherche pour le reste
    (`rechercher_projets`)."""
    exclure = list(exclude_ids) or [0]
    sql = """
        SELECT p.id AS projet_id, p.code, p.nom, MAX(d.date) AS derniere_saisie
        FROM dailylog_entree d
        JOIN projet p ON p.id = d.projet_id
        WHERE d.utilisateur_id = %s AND p.etat = 'en_cours' AND p.id != ALL(%s)
          -- PROMPT_CORRECTIONS.md P1 #10 : filtre de visibilité (déjà
          -- utilisé par list_projets/search en 2026-09-27) — un projet où
          -- l'utilisateur a saisi des heures par le passé, mais dont il a
          -- depuis été retiré (changement d'équipe, retrait comme
          -- intervenant), ne doit plus réapparaître dans "Récemment
          -- travaillés".
          AND EXISTS (
                SELECT 1 FROM v_projet_visibilite vv
                WHERE vv.projet_id = p.id AND vv.utilisateur_id = %s
              )
        GROUP BY p.id, p.code, p.nom
        ORDER BY derniere_saisie DESC
        LIMIT %s
    """
    rows = db.query_all(sql, (user_id, exclure, user_id, limit))
    return [
        {"projet_id": r["projet_id"], "code": r["code"], "nom": r["nom"],
         "tache_id": None, "tache_titre": None}
        for r in rows
    ]


def rechercher_projets(q: str, user_id: int, limit: int = 20) -> list[dict]:
    """Recherche libre par code/nom parmi les projets en cours — troisième
    palier du catalogue "Ajouter une ligne" (retour Fadhel, 2026-09-27),
    remplace l'ancienne liste statique des 50 premiers projets de
    l'entreprise (affichée en permanence, quelle que soit sa pertinence
    pour l'utilisateur). Utilisée par la recherche live côté route
    `dailylog.api_recherche_projets`.

    `user_id` (PROMPT_CORRECTIONS.md P1 #10) : sans filtre de visibilité,
    n'importe quel utilisateur connecté pouvait rechercher et découvrir
    (puis y saisir des heures) N'IMPORTE QUEL projet en cours de
    l'entreprise, pas seulement ceux de son équipe/ses affectations —
    même filtre que list_projets/search (v_projet_visibilite)."""
    q = (q or "").strip()
    if not q:
        return []
    like = f"%{q}%"
    rows = db.query_all(
        """
        SELECT id AS projet_id, code, nom
        FROM projet
        WHERE etat = 'en_cours' AND (code ILIKE %s OR nom ILIKE %s)
          AND EXISTS (
                SELECT 1 FROM v_projet_visibilite vv
                WHERE vv.projet_id = projet.id AND vv.utilisateur_id = %s
              )
        ORDER BY nom
        LIMIT %s
        """,
        (like, like, user_id, limit),
    )
    return [
        {"projet_id": r["projet_id"], "code": r["code"], "nom": r["nom"],
         "tache_id": None, "tache_titre": None}
        for r in rows
    ]


def list_lignes_suggerees(user_id: int) -> dict:
    """Catalogue du panneau "Ajouter une ligne" — trois paliers (retour
    Fadhel, 2026-09-27 : l'utilisateur ne doit plus voir tous les projets
    de l'entreprise en bas de page) :
    - `mine` : les tâches en cours où l'utilisateur est intervenant (ligne
      pré-remplie avec la tâche), plus une ligne "projet seul" pour chaque
      projet où il est intervenant ou chef/co-chef (voir
      `list_projets_pour_dailylog`) — ajout direct, pas besoin de
      s'affecter au préalable.
    - `recentes` : jusqu'à 5 projets récemment travaillés (historique
      DailyLog, voir `list_projets_recents`), en dehors de `mine`.
    - le reste (auparavant `autres`, jusqu'à 50 projets affichés en
      permanence) n'est plus pré-chargé ici : voir `rechercher_projets`,
      utilisée par la recherche live du catalogue.
    """
    mes_taches = db.query_all(
        """
        SELECT t.id AS tache_id, t.titre AS tache_titre, p.id AS projet_id, p.code, p.nom
        FROM tache t
        JOIN projet p ON p.id = t.projet_id
        WHERE t.etat NOT IN ('termine', 'abandonne')
          -- Même règle que les projets proposés (list_projets_pour_dailylog) :
          -- pas les tâches d'un projet terminé/abandonné (lot 7).
          AND p.etat = 'en_cours'
          AND EXISTS (
                SELECT 1 FROM tache_intervenant ti
                WHERE ti.tache_id = t.id AND ti.utilisateur_id = %s
              )
        ORDER BY p.nom, t.titre
        """,
        (user_id,),
    )
    mes_projets = list_projets_pour_dailylog(user_id)

    mine = [
        {"projet_id": t["projet_id"], "code": t["code"], "nom": t["nom"],
         "tache_id": t["tache_id"], "tache_titre": t["tache_titre"]}
        for t in mes_taches
    ] + [
        {"projet_id": p["id"], "code": p["code"], "nom": p["nom"],
         "tache_id": None, "tache_titre": None}
        for p in mes_projets
    ]

    exclure = list({p["id"] for p in mes_projets} | {t["projet_id"] for t in mes_taches}) or [0]
    recentes = list_projets_recents(user_id, exclude_ids=exclure, limit=5)

    return {"mine": mine, "recentes": recentes}


def etats_jours_mois(user_id: int, annee: int, mois: int, standard_hours: float = 8) -> dict:
    """État de chaque jour "notable" du mois, pour les pastilles du
    calendrier DailyLog (Daily log v2, retour Fadhel, 2026-09-29 : "vert =
    rempli, bleu = absent, rouge = rien de rempli, sauf week-end") :

    - 'rempli' (vert) : au moins une ligne d'heures enregistrée. Depuis le
      v2 une journée enregistrée fait toujours 100 % de sa durée : plus
      d'état "partiel".
    - 'absent' (bleu) : journée marquée absente (dailylog_jour.absent).
    - 'manque' (rouge) : jour ouvré sans rien, dans la fenêtre de
      `jours_manques_recents` (même règle que la carte de l'accueil, dont
      le délai de grâce jusqu'à 16 h le jour même) — bornée à cette
      fenêtre pour ne pas peindre en rouge des mois entiers d'avant la
      création du compte.

    Un jour futur, un week-end, ou un jour vide hors de cette fenêtre :
    pas d'entrée (pas de pastille). `standard_hours` n'est plus utilisé,
    gardé pour compatibilité d'appel."""
    rows = db.query_all(
        """
        SELECT DISTINCT date FROM dailylog_entree
        WHERE utilisateur_id = %s AND EXTRACT(YEAR FROM date) = %s AND EXTRACT(MONTH FROM date) = %s
        """,
        (user_id, annee, mois),
    )
    etats = {r["date"].isoformat(): "rempli" for r in rows}
    absents = db.query_all(
        """
        SELECT date FROM dailylog_jour
        WHERE utilisateur_id = %s AND absent AND EXTRACT(YEAR FROM date) = %s AND EXTRACT(MONTH FROM date) = %s
        """,
        (user_id, annee, mois),
    )
    for r in absents:
        etats[r["date"].isoformat()] = "absent"
    for jour in jours_manques_recents(user_id):
        if jour.year == annee and jour.month == mois:
            etats.setdefault(jour.isoformat(), "manque")
    return etats


def jours_manques_recents(
    user_id: int, aujourdhui=None, fenetre_jours: int = 14,
    maintenant=None, heure_alerte_aujourdhui: int = 16,
) -> list:
    """Jours ouvrés (lun-ven, même heuristique que le rappel de connexion —
    voir auth._verifier_rappel_dailylog — sans notion de jour férié ni de
    date d'embauche, non modélisées) pour lesquels l'utilisateur n'a rien
    saisi, dans les `fenetre_jours` derniers jours. Utilisé pour la carte
    Daily log de l'accueil (alerte tant qu'il reste du retard, demandé par
    Fadhel le 2026-09-19) — jamais pour bloquer la saisie, seulement pour
    l'alerte visuelle.

    Le jour même (retour Fadhel, 2026-09-28 : "ne pas mettre en rouge dès
    le matin, mettre en rouge vers 16h+ si toutes les autres journées sont
    remplies") n'est ajouté à la liste qu'à partir de `heure_alerte_aujourdhui`
    (16h par défaut) — avant cette heure, ne pas avoir encore saisi
    aujourd'hui reste normal (message calme dans accueil.html, jamais
    d'alerte). Les jours PASSÉS manquants, eux, comptent toujours
    immédiatement, sans délai de grâce — seul "aujourd'hui" bénéficie de
    ces quelques heures."""
    import datetime

    aujourdhui = aujourdhui or datetime.date.today()
    maintenant = maintenant or datetime.datetime.now()

    jours_ouvres = [
        aujourdhui - datetime.timedelta(days=i)
        for i in range(1, fenetre_jours + 1)
    ]
    jours_ouvres = [j for j in jours_ouvres if j.weekday() < 5]

    if aujourdhui.weekday() < 5 and maintenant.hour >= heure_alerte_aujourdhui:
        jours_ouvres.append(aujourdhui)

    if not jours_ouvres:
        return []

    # Un jour marqué absent (Daily log v2) n'est pas un oubli.
    jours_remplis = jours_renseignes(user_id, jours_ouvres)
    return sorted(j for j in jours_ouvres if j not in jours_remplis)


def remplacer_jour(user_id: int, date, lignes: list[dict], current_user_id: int,
                   conserver: set | None = None, duree_heures: float | None = None,
                   absent: bool = False) -> None:
    """Remplace en une fois toutes les lignes DailyLog d'un utilisateur pour
    un jour donné : les lignes absentes de `lignes` sont supprimées, les
    autres insérées/mises à jour — cohérent avec la sauvegarde explicite
    "journée entière" du prototype curseur (pas d'auto-save ligne par
    ligne). Une ligne par utilisateur/jour/projet/tâche
    (`idx_dailylog_unique`).

    `conserver` : clés (projet_id, tache_id or 0) de lignes soumises mais
    refusées par la validation de la route — une valeur déjà enregistrée
    pour ces clés n'est jamais supprimée (audit n°2 : une ligne refusée
    disparaissait auparavant en silence). Deux lignes soumises avec la
    même clé sont additionnées au lieu que la dernière écrase l'autre.

    `duree_heures` / `absent` (Daily log v2, migration 0008) : réglage de
    la journée, enregistré dans la même transaction que ses lignes. Une
    journée marquée absente perd toutes ses lignes d'heures."""
    conserver = conserver or set()
    fusionnees: dict = {}
    for ligne in lignes:
        cle = (ligne["projet_id"], ligne.get("tache_id") or 0)
        if cle in fusionnees:
            # Plafonné à 24 h, comme une ligne seule (contrainte
            # dailylog_entree_heures_valides, migration 0005).
            fusionnees[cle]["heures"] = min(24, round(fusionnees[cle]["heures"] + ligne["heures"], 2))
        else:
            fusionnees[cle] = dict(ligne)
    lignes = list(fusionnees.values())
    if absent:
        lignes, conserver = [], set()
    with db.get_cursor(user_id=current_user_id) as cur:
        if duree_heures is not None or absent:
            cur.execute(
                """
                INSERT INTO dailylog_jour (utilisateur_id, date, duree_heures, absent, updated_by)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (utilisateur_id, date)
                DO UPDATE SET duree_heures = EXCLUDED.duree_heures, absent = EXCLUDED.absent,
                              updated_by = EXCLUDED.updated_by
                """,
                (user_id, date, duree_heures if duree_heures is not None else DUREE_TYPE, absent, current_user_id),
            )
        cur.execute(
            "SELECT id, projet_id, tache_id FROM dailylog_entree WHERE utilisateur_id = %s AND date = %s",
            (user_id, date),
        )
        existantes = {(r["projet_id"], r["tache_id"] or 0): r["id"] for r in cur.fetchall()}
        gardees = set()

        for ligne in lignes:
            cle = (ligne["projet_id"], ligne.get("tache_id") or 0)
            gardees.add(cle)
            cur.execute(
                """
                INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (utilisateur_id, date, projet_id, COALESCE(tache_id, 0))
                DO UPDATE SET heures = EXCLUDED.heures, updated_by = EXCLUDED.updated_by
                """,
                (user_id, date, ligne["projet_id"], ligne.get("tache_id"), ligne["heures"], current_user_id),
            )

        a_supprimer = [
            existantes[cle] for cle in existantes
            if cle not in gardees and cle not in conserver
        ]
        if a_supprimer:
            cur.execute("DELETE FROM dailylog_entree WHERE id = ANY(%s)", (a_supprimer,))

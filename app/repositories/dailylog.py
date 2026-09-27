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
               p.nom AS projet_nom, t.titre AS tache_titre
        FROM dailylog_entree d
        JOIN projet p ON p.id = d.projet_id
        LEFT JOIN tache t ON t.id = d.tache_id
        WHERE d.utilisateur_id = %s AND d.date = %s
        ORDER BY d.id
    """
    return db.query_all(sql, (user_id, date))


def upsert_entree(
    user_id: int,
    date,
    projet_id: int,
    heures,
    tache_id: int | None = None,
    current_user_id: int | None = None,
) -> dict:
    """Une seule ligne par (utilisateur, jour, projet, tâche) — y compris
    quand tache_id est vide, grâce à l'index fonctionnel COALESCE validé
    sur le schéma (idx_dailylog_unique). `current_user_id` est en général
    égal à `user_id`, sauf correction faite par un admin pour quelqu'un
    d'autre.
    """
    author = current_user_id if current_user_id is not None else user_id
    sql = """
        INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures, updated_by)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (utilisateur_id, date, projet_id, COALESCE(tache_id, 0))
        DO UPDATE SET heures = EXCLUDED.heures, updated_by = EXCLUDED.updated_by
        RETURNING id, heures
        """
    with db.get_cursor(user_id=author) as cur:
        cur.execute(sql, (user_id, date, projet_id, tache_id, heures, author))
        return dict(cur.fetchone())


def delete_entree(entree_id: int, current_user_id: int) -> None:
    db.execute(
        "DELETE FROM dailylog_entree WHERE id = %s",
        (entree_id,),
        user_id=current_user_id,
    )


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


def list_jours_remplis_mois(user_id: int, annee: int, mois: int) -> list:
    """Dates (du mois donné) où l'utilisateur a au moins une ligne
    enregistrée — pour la pastille verte du calendrier du DailyLog. La
    pastille "manquant" du prototype n'a pas été reprise : elle demanderait
    de définir ce qu'est un jour normalement travaillé (jours fériés,
    date d'embauche, etc.), non modélisé pour l'instant."""
    rows = db.query_all(
        """
        SELECT DISTINCT date FROM dailylog_entree
        WHERE utilisateur_id = %s AND EXTRACT(YEAR FROM date) = %s AND EXTRACT(MONTH FROM date) = %s
        """,
        (user_id, annee, mois),
    )
    return [r["date"] for r in rows]


def jours_manques_recents(user_id: int, aujourdhui=None, fenetre_jours: int = 14) -> list:
    """Jours ouvrés (lun-ven, même heuristique que le rappel de connexion —
    voir auth._verifier_rappel_dailylog — sans notion de jour férié ni de
    date d'embauche, non modélisées) strictement avant aujourd'hui, dans
    les `fenetre_jours` derniers jours, pour lesquels l'utilisateur n'a
    rien saisi. Utilisé pour la carte Daily log de l'accueil (fond rouge
    tant qu'il reste du retard, demandé par Fadhel le 2026-09-19) — jamais
    pour bloquer la saisie, seulement pour l'alerte visuelle."""
    import datetime

    aujourdhui = aujourdhui or datetime.date.today()
    jours_ouvres = [
        aujourdhui - datetime.timedelta(days=i)
        for i in range(1, fenetre_jours + 1)
    ]
    jours_ouvres = [j for j in jours_ouvres if j.weekday() < 5]
    if not jours_ouvres:
        return []

    remplis = db.query_all(
        """
        SELECT DISTINCT date FROM dailylog_entree
        WHERE utilisateur_id = %s AND date = ANY(%s)
        """,
        (user_id, jours_ouvres),
    )
    jours_remplis = {r["date"] for r in remplis}
    return sorted(j for j in jours_ouvres if j not in jours_remplis)


def remplacer_jour(user_id: int, date, lignes: list[dict], current_user_id: int,
                   conserver: set | None = None) -> None:
    """Remplace en une fois toutes les lignes DailyLog d'un utilisateur pour
    un jour donné : les lignes absentes de `lignes` sont supprimées, les
    autres insérées/mises à jour — cohérent avec la sauvegarde explicite
    "journée entière" du prototype curseur (pas d'auto-save ligne par
    ligne). Mêmes contraintes que `upsert_entree` (une ligne par
    utilisateur/jour/projet/tâche, `idx_dailylog_unique`).

    `conserver` : clés (projet_id, tache_id or 0) de lignes soumises mais
    refusées par la validation de la route — une valeur déjà enregistrée
    pour ces clés n'est jamais supprimée (audit n°2 : une ligne refusée
    disparaissait auparavant en silence). Deux lignes soumises avec la
    même clé sont additionnées au lieu que la dernière écrase l'autre."""
    conserver = conserver or set()
    fusionnees: dict = {}
    for ligne in lignes:
        cle = (ligne["projet_id"], ligne.get("tache_id") or 0)
        if cle in fusionnees:
            fusionnees[cle]["heures"] = round(fusionnees[cle]["heures"] + ligne["heures"], 2)
        else:
            fusionnees[cle] = dict(ligne)
    lignes = list(fusionnees.values())
    with db.get_cursor(user_id=current_user_id) as cur:
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

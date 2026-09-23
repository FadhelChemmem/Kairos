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


def list_lignes_suggerees(user_id: int) -> dict:
    """Catalogue du panneau "Ajouter une ligne" — deux groupes, comme dans
    le prototype :
    - `mine` : les tâches en cours où l'utilisateur est intervenant (ligne
      pré-remplie avec la tâche), plus une ligne "projet seul" pour chaque
      projet où il est intervenant ou chef/co-chef (voir
      `list_projets_pour_dailylog`) — ajout direct, pas besoin de
      s'affecter au préalable.
    - `autres` : le reste des projets en cours de l'entreprise — ajout
      seulement "ponctuel" côté UI (voir spec), pas de tâche précise
      proposée puisque l'utilisateur n'y est pas rattaché.
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
    autres_projets = db.query_all(
        """
        SELECT id AS projet_id, code, nom
        FROM projet
        WHERE etat = 'en_cours' AND id != ALL(%s)
        ORDER BY nom
        LIMIT 50
        """,
        (exclure,),
    )
    autres = [
        {"projet_id": p["projet_id"], "code": p["code"], "nom": p["nom"],
         "tache_id": None, "tache_titre": None}
        for p in autres_projets
    ]

    return {"mine": mine, "autres": autres}


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


def remplacer_jour(user_id: int, date, lignes: list[dict], current_user_id: int) -> None:
    """Remplace en une fois toutes les lignes DailyLog d'un utilisateur pour
    un jour donné : les lignes absentes de `lignes` sont supprimées, les
    autres insérées/mises à jour — cohérent avec la sauvegarde explicite
    "journée entière" du prototype curseur (pas d'auto-save ligne par
    ligne). Mêmes contraintes que `upsert_entree` (une ligne par
    utilisateur/jour/projet/tâche, `idx_dailylog_unique`)."""
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

        a_supprimer = [existantes[cle] for cle in existantes if cle not in gardees]
        if a_supprimer:
            cur.execute("DELETE FROM dailylog_entree WHERE id = ANY(%s)", (a_supprimer,))

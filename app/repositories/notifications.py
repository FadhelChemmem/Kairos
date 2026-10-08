"""Notifications — un seul mécanisme (même table, même composant/bouton
dans l'UI), différencié par `categorie` ('projet' pour tout ce qui touche
au travail/projets, 'rh_info' pour le reste — non contraint en base à ce
stade, voir schema.sql). Étape 1 : pas d'emailing, uniquement une cloche
dans l'appli (voir spec)."""
from .. import db


def creer(
    utilisateur_id: int,
    categorie: str,
    message: str,
    post_id: int | None = None,
    tache_id: int | None = None,
) -> int:
    """Crée une notification pour un utilisateur. Appelée depuis les routes
    (posts, projets, auth), après que l'action déclenchante a réussi —
    jamais dans la même transaction que celle-ci, pour ne jamais faire
    échouer l'action principale si la notification pose problème."""
    row = db.query_one(
        """
        INSERT INTO notification (utilisateur_id, categorie, post_id, tache_id, message)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (utilisateur_id, categorie, post_id, tache_id, message),
    )
    return row["id"]


def creer_pour_plusieurs(utilisateur_ids: list[int], categorie: str, message: str,
                          post_id: int | None = None, tache_id: int | None = None,
                          exclure_id: int | None = None) -> None:
    """Même notification pour plusieurs personnes (ex. tous les intervenants
    ajoutés à une tâche) — `exclure_id` sert à ne jamais notifier l'auteur
    de l'action lui-même. Chaque personne n'est notifiée qu'une fois, même
    si son id est répété (audit sécurité I12)."""
    for uid in dict.fromkeys(utilisateur_ids):
        if uid == exclure_id:
            continue
        creer(uid, categorie, message, post_id=post_id, tache_id=tache_id)


def list_notifications(user_id: int, limit: int = 50) -> list[dict]:
    sql = """
        SELECT n.id, n.categorie, n.message, n.lu, n.created_at,
               n.post_id, n.tache_id,
               p.projet_id AS post_projet_id,
               t.projet_id AS tache_projet_id, t.titre AS tache_titre
        FROM notification n
        LEFT JOIN post p ON p.id = n.post_id
        LEFT JOIN tache t ON t.id = n.tache_id
        WHERE n.utilisateur_id = %s
        ORDER BY n.created_at DESC
        LIMIT %s
    """
    return db.query_all(sql, (user_id, limit))


def get_notification(notification_id: int, user_id: int) -> dict | None:
    """Restreint à `user_id` : on ne peut ouvrir que sa propre notification."""
    sql = """
        SELECT n.id, n.categorie, n.message, n.lu, n.created_at,
               n.post_id, n.tache_id, n.rappel_jours,
               p.projet_id AS post_projet_id,
               t.projet_id AS tache_projet_id
        FROM notification n
        LEFT JOIN post p ON p.id = n.post_id
        LEFT JOIN tache t ON t.id = n.tache_id
        WHERE n.id = %s AND n.utilisateur_id = %s
    """
    return db.query_one(sql, (notification_id, user_id))


def compter_non_lues(user_id: int) -> int:
    row = db.query_one(
        "SELECT count(*) AS n FROM notification WHERE utilisateur_id = %s AND lu = false",
        (user_id,),
    )
    return row["n"] if row else 0


def marquer_lu(notification_id: int, user_id: int) -> None:
    """Restreint à `user_id` : on ne peut marquer comme lue que sa propre
    notification (pas de vérification de rôle nécessaire, l'appartenance
    suffit)."""
    db.execute(
        "UPDATE notification SET lu = true WHERE id = %s AND utilisateur_id = %s",
        (notification_id, user_id),
    )


def marquer_toutes_lues(user_id: int) -> None:
    db.execute(
        "UPDATE notification SET lu = true WHERE utilisateur_id = %s AND lu = false",
        (user_id,),
    )


def creer_rappel_dailylog(user_id: int, jours: list, texte) -> list:
    """Rappel « Daily log non rempli » (lot 11 b) : UNE notification pour
    les jours oubliés de `jours` qui n'ont encore jamais été rappelés —
    `texte(jours_retenus)` en fait le message. La clé est la colonne
    notification.rappel_jours (migration 0017, qui l'a aussi posée sur les
    rappels de l'ancien format) : plus de LIKE sur le texte. Verrou
    consultatif par personne : deux sessions ouvertes en même temps (deux
    appareils) n'envoient pas deux fois le même rappel. Renvoie les jours
    rappelés (liste vide : rien de nouveau)."""
    jours = sorted(set(jours))
    if not jours:
        return []
    with db.get_cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('kairos.rappel_dailylog'), %s::int)", (user_id,))
        cur.execute(
            """
            SELECT DISTINCT j.jour
            FROM notification n, unnest(n.rappel_jours) AS j(jour)
            WHERE n.utilisateur_id = %s AND n.rappel_jours IS NOT NULL
              AND n.rappel_jours && %s::date[]
            """,
            (user_id, jours),
        )
        deja = {r["jour"] for r in cur.fetchall()}
        nouveaux = [j for j in jours if j not in deja]
        if nouveaux:
            cur.execute(
                """
                INSERT INTO notification (utilisateur_id, categorie, message, rappel_jours)
                VALUES (%s, 'rh_info', %s, %s::date[])
                """,
                (user_id, texte(nouveaux), nouveaux),
            )
        return nouveaux


# Rappels Daily log (rappel_jours, ancien et nouveau format) dont TOUS les
# jours cités sont depuis remplis (au moins une ligne d'heures) ou marqués
# absents.
_SQL_RAPPELS_DEVENUS_INUTILES = """
    UPDATE notification n SET lu = true
    WHERE n.utilisateur_id = %(uid)s AND NOT n.lu AND n.rappel_jours IS NOT NULL
      AND NOT EXISTS (
            SELECT 1 FROM unnest(n.rappel_jours) AS r(jour)
            WHERE NOT EXISTS (SELECT 1 FROM dailylog_entree e WHERE e.utilisateur_id = %(uid)s AND e.date = r.jour)
              AND NOT EXISTS (SELECT 1 FROM dailylog_jour j
                              WHERE j.utilisateur_id = %(uid)s AND j.date = r.jour AND j.absent)
          )
"""


def marquer_rappels_dailylog_lus(user_id: int, cur=None) -> None:
    """Lot 11 : un rappel « Daily log … non rempli » est marqué lu dès que
    ses jours sont remplis ou marqués absents — par la personne ou par un
    chef qui corrige (appelé dans la transaction d'enregistrement du Daily
    log, `cur`), et une fois par jour au rappel quotidien (jours remplis
    autrement). Lot 11 b : reconnu par rappel_jours (un rappel regroupant
    plusieurs jours reste non lu tant qu'il en manque un)."""
    if cur is not None:
        cur.execute(_SQL_RAPPELS_DEVENUS_INUTILES, {"uid": user_id})
    else:
        db.execute(_SQL_RAPPELS_DEVENUS_INUTILES, {"uid": user_id})


def a_deja_la_notification(user_id: int, message: str, jour) -> bool:
    """Même message déjà envoyé ce jour-là à cette personne (ex. « Daily
    log du … corrigé par … » : un chef qui corrige plusieurs fois le même
    jour ne prévient qu'une fois)."""
    row = db.query_one(
        """
        SELECT 1 FROM notification
        WHERE utilisateur_id = %s AND message = %s AND created_at::date = %s
        """,
        (user_id, message, jour),
    )
    return row is not None

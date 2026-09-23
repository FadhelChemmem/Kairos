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
    de l'action lui-même."""
    for uid in utilisateur_ids:
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
               n.post_id, n.tache_id,
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


def a_deja_un_rappel_dailylog(user_id: int, jour) -> bool:
    """Évite de recréer le même rappel "DailyLog de la veille non rempli" à
    chaque connexion du même jour (voir spec : déclenché "à la connexion
    du lendemain", donc une fois par jour suffit)."""
    row = db.query_one(
        """
        SELECT 1 FROM notification
        WHERE utilisateur_id = %s
          AND categorie = 'rh_info'
          AND message LIKE 'Rappel DailyLog%%'
          AND created_at::date = %s
        """,
        (user_id, jour),
    )
    return row is not None

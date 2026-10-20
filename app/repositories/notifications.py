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
    projet_id: int | None = None,
    commentaire_id: int | None = None,
    pousser: bool = True,
) -> int:
    """Crée une notification pour un utilisateur. Appelée depuis les routes
    (posts, projets, auth), après que l'action déclenchante a réussi —
    jamais dans la même transaction que celle-ci, pour ne jamais faire
    échouer l'action principale si la notification pose problème.
    `projet_id` (migration 0019) : projet à ouvrir quand la notification ne
    porte ni post ni tâche (« ajouté au projet »)."""
    row = db.query_one(
        """
        INSERT INTO notification (utilisateur_id, categorie, post_id, tache_id, projet_id, message, commentaire_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (utilisateur_id, categorie, post_id, tache_id, projet_id, message, commentaire_id),
    )
    if pousser:
        _pousser([row["id"]])
    return row["id"]


def _pousser(ids: list[int]) -> None:
    """Lot 24 : notification Windows (app/push.py), jamais bloquante."""
    try:
        from .. import push

        push.planifier(ids)
    except Exception:
        from flask import current_app

        current_app.logger.exception("Notification push non planifiée")


def creer_pour_plusieurs(utilisateur_ids: list[int], categorie: str, message: str,
                          post_id: int | None = None, tache_id: int | None = None,
                          exclure_id: int | None = None, projet_id: int | None = None,
                          commentaire_id: int | None = None) -> list[int]:
    """Même notification pour plusieurs personnes (ex. tous les intervenants
    ajoutés à une tâche) — `exclure_id` sert à ne jamais notifier l'auteur
    de l'action lui-même. Chaque personne n'est notifiée qu'une fois, même
    si son id est répété (audit sécurité I12). Renvoie les ids créés (lot
    14 : « Annuler » ne retire que les notifications de son geste)."""
    ids = []
    for uid in dict.fromkeys(utilisateur_ids):
        if uid == exclure_id:
            continue
        ids.append(creer(uid, categorie, message, post_id=post_id, tache_id=tache_id, projet_id=projet_id,
                         commentaire_id=commentaire_id, pousser=False))
    _pousser(ids)
    return ids


def retirer(ids: list[int], tache_id: int) -> int:
    """« Annuler » d'un blocage ou d'une clôture (lot 14) : les
    notifications créées par CE geste (ids gardés dans l'action « Annuler »,
    recette du lot 14 n° 4), sur cette tâche et encore non lues, sont
    retirées — le chef n'est pas alerté d'un geste défait. Une notification
    déjà lue reste ; celles d'un autre geste ne sont jamais touchées.
    Renvoie le nombre retiré."""
    ids = [int(i) for i in ids or []]
    if not ids:
        return 0
    with db.get_cursor() as cur:
        cur.execute("DELETE FROM notification WHERE id = ANY(%s) AND tache_id = %s AND NOT lu", (ids, tache_id))
        return cur.rowcount


# Lot 24 : colonnes et jointures communes à la liste (cloche, page) et aux
# notifications Windows (app/push.py) — le push montre exactement ce que
# montre la cloche.
_SELECT_AFFICHE = """
        SELECT n.id, n.utilisateur_id, n.categorie,
               -- Lot 16 (revue sécurité) : l'extrait d'un post supprimé ne
               -- reste pas lisible dans les notifications.
               -- Lot 18 (audit droits) : plus d'extrait si le projet n'est plus
               -- visible par la personne (retirée du projet, changée d'équipe).
               CASE WHEN COALESCE(n.projet_id, p.projet_id, t.projet_id) IS NOT NULL
                         AND NOT EXISTS (SELECT 1 FROM v_projet_visibilite vv
                                         WHERE vv.projet_id = COALESCE(n.projet_id, p.projet_id, t.projet_id)
                                           AND vv.utilisateur_id = n.utilisateur_id)
                    THEN 'Notification d’un projet auquel vous n’avez plus accès.'
                    WHEN p.supprime_le IS NOT NULL
                    THEN regexp_replace(n.message, '[[:space:] ]*:[[:space:] ]*«.*$', '') || ' (post supprimé).'
                    -- Lot 20 (revue 9c) : l'extrait d'un commentaire supprimé ou
                    -- modifié, ou d'un post modifié depuis, ne reste pas lisible.
                    WHEN c.supprime_le IS NOT NULL
                    THEN regexp_replace(n.message, '[[:space:] ]*:[[:space:] ]*«.*$', '') || ' (commentaire supprimé).'
                    -- Lot 24 (SB-04) : une modification sous une date simulée
                    -- passée est datée de la création (GREATEST) : comptée aussi.
                    WHEN strpos(n.message, '«') > 0 AND (c.modifie_le > n.created_at OR c.modifie_le = c.created_at
                                              OR (n.commentaire_id IS NULL AND (p.modifie_le > n.created_at
                                                                                OR p.modifie_le = p.created_at)))
                    THEN regexp_replace(n.message, '[[:space:] ]*:[[:space:] ]*«.*$', '') || ' (modifié depuis).'
                    ELSE n.message END AS message,
               n.lu, n.created_at,
               n.post_id, n.tache_id, n.projet_id, n.simulee,
               p.projet_id AS post_projet_id,
               t.projet_id AS tache_projet_id, t.titre AS tache_titre,
               -- Lot 24 (MX-03) : ni le code d'un projet que la personne ne
               -- voit plus.
               CASE WHEN EXISTS (SELECT 1 FROM v_projet_visibilite vv
                                 WHERE vv.projet_id = pr.id AND vv.utilisateur_id = n.utilisateur_id)
                    THEN pr.code END AS projet_code
        FROM notification n
        LEFT JOIN post p ON p.id = n.post_id
        LEFT JOIN tache t ON t.id = n.tache_id
        LEFT JOIN post_commentaire c ON c.id = n.commentaire_id
        -- Revue visuelle P2-31 : le code du projet remplace la pastille
        -- « Projet » répétée sur chaque ligne.
        LEFT JOIN projet pr ON pr.id = COALESCE(n.projet_id, p.projet_id, t.projet_id)
"""


def list_notifications(user_id: int, limit: int = 50, avec_simulees: bool = False) -> list[dict]:
    """`avec_simulees` (contre-expertise temps N1) : les rappels
    « [Simulation] » ne se voient que pendant le test de l'Admin
    (modes_admin.voit_rappels_simules), jamais par la vraie personne."""
    sql = _SELECT_AFFICHE + """
        WHERE n.utilisateur_id = %s AND (%s OR NOT n.simulee)
        ORDER BY n.created_at DESC
        LIMIT %s
    """
    return db.query_all(sql, (user_id, avec_simulees, limit))


def get_notification(notification_id: int, user_id: int) -> dict | None:
    """Restreint à `user_id` : on ne peut ouvrir que sa propre notification."""
    sql = """
        SELECT n.id, n.categorie, n.message, n.lu, n.created_at,
               n.post_id, n.tache_id, n.rappel_jours, n.projet_id,
               p.projet_id AS post_projet_id,
               t.projet_id AS tache_projet_id
        FROM notification n
        LEFT JOIN post p ON p.id = n.post_id
        LEFT JOIN tache t ON t.id = n.tache_id
        WHERE n.id = %s AND n.utilisateur_id = %s
    """
    return db.query_one(sql, (notification_id, user_id))


def compter_non_lues(user_id: int, avec_simulees: bool = False) -> int:
    row = db.query_one(
        "SELECT count(*) AS n FROM notification WHERE utilisateur_id = %s AND lu = false AND (%s OR NOT simulee)",
        (user_id, avec_simulees),
    )
    return row["n"] if row else 0


def purger_rappels_simules(user_ids) -> int:
    """Rappels « [Simulation] » supprimés quand l'Admin quitte le test
    (« Revenir à mon compte » depuis « Agir comme », « Revenir à
    aujourd'hui ») : rien ne reste chez la vraie personne."""
    ids = sorted({i for i in user_ids if isinstance(i, int)})
    if not ids:
        return 0
    with db.get_cursor() as cur:
        cur.execute("DELETE FROM notification WHERE simulee AND utilisateur_id = ANY(%s)", (ids,))
        return cur.rowcount


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


def creer_rappel_dailylog(user_id: int, jours: list, texte, simulee: bool = False) -> list:
    """Rappel « Daily log non rempli » (lot 11 b) : UNE notification pour
    les jours oubliés de `jours` qui n'ont encore jamais été rappelés —
    `texte(jours_retenus)` en fait le message. La clé est la colonne
    notification.rappel_jours (migration 0017, qui l'a aussi posée sur les
    rappels de l'ancien format) : plus de LIKE sur le texte. Verrou
    consultatif par personne : deux sessions ouvertes en même temps (deux
    appareils) n'envoient pas deux fois le même rappel. Renvoie les jours
    rappelés (liste vide : rien de nouveau).

    `simulee` (lot 13, « Simuler le rappel du jour ») : la notification est
    marquée simulée et préfixée « [Simulation] » ; un rappel simulé ne
    compte jamais pour le dédoublonnage d'un vrai rappel (il peut citer des
    jours du futur réel), l'inverse oui."""
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
              AND (%s OR NOT n.simulee)
            """,
            (user_id, jours, simulee),
        )
        deja = {r["jour"] for r in cur.fetchall()}
        nouveaux = [j for j in jours if j not in deja]
        if nouveaux:
            cur.execute(
                """
                INSERT INTO notification (utilisateur_id, categorie, message, rappel_jours, simulee)
                VALUES (%s, 'rh_info', %s, %s::date[], %s)
                RETURNING id
                """,
                (user_id, ("[Simulation] " if simulee else "") + texte(nouveaux), nouveaux, simulee),
            )
            cree = cur.fetchone()["id"]
    if nouveaux and not simulee:
        _pousser([cree])
    return nouveaux


# Rappels Daily log (rappel_jours, ancien et nouveau format) dont TOUS les
# jours cités sont depuis remplis (au moins une ligne d'heures), marqués
# absents, ou sortis de la fenêtre de 14 jours où la personne peut encore
# les saisir (lot 13, audit temps T-M7 : le rappel restait non lu pour
# toujours). La fenêtre se compte sur la VRAIE date (fn_aujourdhui_reel) :
# une date simulée ne marque jamais lu un vrai rappel ; un rappel simulé,
# lui, suit la date simulée.
_SQL_RAPPELS_DEVENUS_INUTILES = """
    UPDATE notification n SET lu = true
    FROM utilisateur u
    WHERE u.id = n.utilisateur_id
      AND n.utilisateur_id = %(uid)s AND NOT n.lu AND n.rappel_jours IS NOT NULL
      AND NOT EXISTS (
            SELECT 1 FROM unnest(n.rappel_jours) AS r(jour)
            WHERE NOT EXISTS (SELECT 1 FROM dailylog_entree e WHERE e.utilisateur_id = %(uid)s AND e.date = r.jour)
              AND NOT EXISTS (SELECT 1 FROM dailylog_jour j
                              WHERE j.utilisateur_id = %(uid)s AND j.date = r.jour AND j.absent)
              AND r.jour >= (CASE WHEN n.simulee THEN fn_aujourdhui(u.fuseau) ELSE fn_aujourdhui_reel(u.fuseau) END)
                            - %(fenetre)s
          )
"""
FENETRE_RAPPEL_JOURS = 14


def marquer_rappels_dailylog_lus(user_id: int, cur=None) -> None:
    """Lot 11 : un rappel « Daily log … non rempli » est marqué lu dès que
    ses jours sont remplis ou marqués absents — par la personne ou par un
    chef qui corrige (appelé dans la transaction d'enregistrement du Daily
    log, `cur`), et une fois par jour au rappel quotidien (jours remplis
    autrement). Lot 11 b : reconnu par rappel_jours (un rappel regroupant
    plusieurs jours reste non lu tant qu'il en manque un)."""
    params = {"uid": user_id, "fenetre": FENETRE_RAPPEL_JOURS}
    if cur is not None:
        cur.execute(_SQL_RAPPELS_DEVENUS_INUTILES, params)
    else:
        db.execute(_SQL_RAPPELS_DEVENUS_INUTILES, params)


def a_deja_la_notification(user_id: int, message: str) -> bool:
    """Même message déjà envoyé AUJOURD'HUI à cette personne (ex. « Daily
    log du … corrigé par … » : un chef qui corrige plusieurs fois le même
    jour ne prévient qu'une fois). Lot 13 (audit temps T-M1) : au fuseau de
    la personne, jamais celui de la session (Tunis, déjà le lendemain le
    soir en Guyane). Lot 20 : l'horodatage suit la date simulée (mode test),
    le jour comparé aussi. Lot 21 : une écriture n'est jamais datée dans le
    futur réel (fn_maintenant plafonné) : le jour comparé est celui de
    fn_maintenant(), pas fn_aujourdhui() qui peut être dans le futur."""
    row = db.query_one(
        """
        SELECT 1 FROM notification n JOIN utilisateur u ON u.id = n.utilisateur_id
        WHERE n.utilisateur_id = %s AND n.message = %s
          AND (n.created_at AT TIME ZONE u.fuseau)::date
              = (fn_maintenant() AT TIME ZONE u.fuseau)::date
        """,
        (user_id, message),
    )
    return row is not None


def pour_push(notification_ids: list[int]) -> list[dict]:
    """Lot 24 : notifications à pousser vers Windows — encore présentes
    (« Annuler » ne les a pas retirées), non lues, non simulées, d'une
    catégorie que la personne (active) a gardée pour le push."""
    ids = [int(i) for i in notification_ids or []]
    if not ids:
        return []
    return db.query_all(_SELECT_AFFICHE + """
        JOIN utilisateur u ON u.id = n.utilisateur_id AND u.actif
        LEFT JOIN utilisateur_preference up ON up.utilisateur_id = n.utilisateur_id
        WHERE n.id = ANY(%s) AND NOT n.lu AND NOT n.simulee
          AND (up.push_categories IS NULL OR n.categorie = ANY(up.push_categories))
        ORDER BY n.id
    """, (ids,))

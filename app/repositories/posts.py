"""Requêtes SQL liées au fil de posts (feed), réactions et commentaires."""
from .. import db

_FEED_SELECT = """
    SELECT p.id, p.type_code, p.contenu, p.lien, p.created_at, p.tache_id, p.parent_post_id,
           p.projet_id, proj.code AS projet_code, proj.nom AS projet_nom,
           u.id AS auteur_id, u.prenom AS auteur_prenom, u.nom AS auteur_nom,
           u.avatar_chemin AS auteur_avatar_chemin,
           t.titre AS tache_titre, t.etat AS tache_etat,
           (p.tache_id IS NOT NULL AND p.created_at = t.created_at) AS est_creation_tache,
           (p.tache_id IS NOT NULL AND t.date_fin IS NOT NULL AND p.created_at = t.updated_at)
             AS est_cloture_tache,
           (SELECT count(*) FROM post_reaction r WHERE r.post_id = p.id) AS nb_reactions,
           (SELECT count(*) FROM post_commentaire c WHERE c.post_id = p.id) AS nb_commentaires,
           (SELECT pr.reaction_code FROM post_reaction pr
             WHERE pr.post_id = p.id AND pr.utilisateur_id = %(uid)s) AS ma_reaction,
           COALESCE(
             (SELECT json_agg(json_build_object('prenom', ru.prenom, 'nom', ru.nom)
                               ORDER BY ru.nom)
              FROM post_reaction pr2 JOIN utilisateur ru ON ru.id = pr2.utilisateur_id
              WHERE pr2.post_id = p.id),
             '[]'
           ) AS reacteurs,
           COALESCE(
             (SELECT json_agg(json_build_object(
                                'id', c.id, 'contenu', c.contenu, 'created_at', c.created_at,
                                'auteur_id', cu.id, 'auteur_prenom', cu.prenom, 'auteur_nom', cu.nom,
                                'auteur_avatar_chemin', cu.avatar_chemin)
                               ORDER BY c.created_at)
              FROM post_commentaire c JOIN utilisateur cu ON cu.id = c.auteur_id
              WHERE c.post_id = p.id),
             '[]'
           ) AS commentaires,
           COALESCE(
             (SELECT json_agg(json_build_object('id', pj.id, 'nom_fichier', pj.nom_fichier)
                               ORDER BY pj.uploaded_at)
              FROM post_piece_jointe pj WHERE pj.post_id = p.id),
             '[]'
           ) AS pieces_jointes,
           COALESCE(
             (SELECT json_agg(json_build_object('id', mu.id, 'prenom', mu.prenom, 'nom', mu.nom)
                               ORDER BY mu.nom)
              FROM post_mention pm JOIN utilisateur mu ON mu.id = pm.utilisateur_id
              WHERE pm.post_id = p.id),
             '[]'
           ) AS mentions,
           parent.contenu AS parent_contenu, parent.type_code AS parent_type_code,
           parent_auteur.prenom AS parent_auteur_prenom, parent_auteur.nom AS parent_auteur_nom,
           parent_tache.titre AS parent_tache_titre
    FROM post p
    JOIN utilisateur u ON u.id = p.auteur_id
    JOIN projet proj ON proj.id = p.projet_id
    LEFT JOIN tache t ON t.id = p.tache_id
    LEFT JOIN post parent ON parent.id = p.parent_post_id
    LEFT JOIN utilisateur parent_auteur ON parent_auteur.id = parent.auteur_id
    LEFT JOIN tache parent_tache ON parent_tache.id = parent.tache_id
"""


def list_feed_projet(projet_id: int, current_user_id: int, limit: int = 30) -> list[dict]:
    sql = _FEED_SELECT + """
        WHERE p.projet_id = %(pid)s
        ORDER BY p.created_at DESC
        LIMIT %(limit)s
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"uid": current_user_id, "pid": projet_id, "limit": limit})
        return [dict(r) for r in cur.fetchall()]


def list_feed_mes_projets(current_user_id: int, limit: int = 30) -> list[dict]:
    """Fil d'activité de l'accueil : tous les posts des projets où
    l'utilisateur est chef, co-chef ou intervenant."""
    sql = _FEED_SELECT + """
        WHERE p.projet_id IN (
            SELECT pj.id FROM projet pj
            LEFT JOIN projet_co_chef cc ON cc.projet_id = pj.id AND cc.utilisateur_id = %(uid)s
            LEFT JOIN projet_intervenant pi ON pi.projet_id = pj.id AND pi.utilisateur_id = %(uid)s
            WHERE pj.chef_projet_id = %(uid)s
               OR cc.utilisateur_id IS NOT NULL
               OR pi.utilisateur_id IS NOT NULL
        )
        ORDER BY p.created_at DESC
        LIMIT %(limit)s
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"uid": current_user_id, "limit": limit})
        return [dict(r) for r in cur.fetchall()]


def create_post(
    projet_id: int,
    auteur_id: int,
    type_code: str,
    contenu: str | None,
    tache_id: int | None = None,
    parent_post_id: int | None = None,
    lien: str | None = None,
    mentionne_ids: list[int] | None = None,
) -> int:
    """Création manuelle d'un post (Envoi/Réponse/Question/Requête), ou
    d'un "rebond" quand parent_post_id est renseigné (voir spec : l'action
    interne "rebondir", jamais affichée sous ce nom dans l'UI — seulement
    une icône flèche).

    `lien` et `mentionne_ids` (personnes taguées) sont optionnels, ajoutés
    2026-09-18 pour le composeur "Nouveau post" (panneau Requête)."""
    with db.get_cursor(user_id=auteur_id) as cur:
        cur.execute(
            """
            INSERT INTO post (projet_id, tache_id, parent_post_id, auteur_id, type_code, contenu, lien)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (projet_id, tache_id, parent_post_id, auteur_id, type_code, contenu, lien),
        )
        post_id = cur.fetchone()["id"]

        for uid in mentionne_ids or []:
            cur.execute(
                "INSERT INTO post_mention (post_id, utilisateur_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (post_id, uid),
            )

        return post_id


def react(post_id: int, user_id: int, reaction_code: str) -> None:
    """Une réaction par utilisateur par post, modifiable (upsert validé
    directement sur Postgres pendant la conception du schéma)."""
    db.execute(
        """
        INSERT INTO post_reaction (post_id, utilisateur_id, reaction_code)
        VALUES (%s, %s, %s)
        ON CONFLICT (post_id, utilisateur_id)
        DO UPDATE SET reaction_code = EXCLUDED.reaction_code
        """,
        (post_id, user_id, reaction_code),
    )


def remove_reaction(post_id: int, user_id: int) -> None:
    db.execute(
        "DELETE FROM post_reaction WHERE post_id = %s AND utilisateur_id = %s",
        (post_id, user_id),
    )


def add_comment(post_id: int, auteur_id: int, contenu: str, mentionne_user_id: int | None = None) -> int:
    with db.get_cursor(user_id=auteur_id) as cur:
        cur.execute(
            """
            INSERT INTO post_commentaire (post_id, auteur_id, contenu, mentionne_user_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (post_id, auteur_id, contenu, mentionne_user_id),
        )
        return cur.fetchone()["id"]


def add_piece_jointe(post_id: int, nom_fichier: str, chemin: str, uploaded_by: int) -> int:
    with db.get_cursor(user_id=uploaded_by) as cur:
        cur.execute(
            """
            INSERT INTO post_piece_jointe (post_id, nom_fichier, chemin, uploaded_by)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (post_id, nom_fichier, chemin, uploaded_by),
        )
        return cur.fetchone()["id"]


def get_piece_jointe(piece_id: int) -> dict | None:
    return db.query_one(
        "SELECT id, post_id, nom_fichier, chemin FROM post_piece_jointe WHERE id = %s",
        (piece_id,),
    )


def list_comments(post_id: int) -> list[dict]:
    sql = """
        SELECT c.id, c.contenu, c.created_at,
               u.id AS auteur_id, u.prenom AS auteur_prenom, u.nom AS auteur_nom,
               u.avatar_chemin AS auteur_avatar_chemin,
               m.prenom AS mentionne_prenom, m.nom AS mentionne_nom
        FROM post_commentaire c
        JOIN utilisateur u ON u.id = c.auteur_id
        LEFT JOIN utilisateur m ON m.id = c.mentionne_user_id
        WHERE c.post_id = %s
        ORDER BY c.created_at
    """
    return db.query_all(sql, (post_id,))

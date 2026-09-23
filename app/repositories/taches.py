"""Requêtes SQL liées aux tâches.

Convention utilisée pour distinguer, dans le fil de posts, un post
« système » de création/clôture de tâche d'un post écrit à la main
(voir posts.py `annoter_evenement_tache`) : à l'intérieur d'une même
transaction, tous les appels à now() renvoient exactement la même
valeur (comportement documenté de PostgreSQL — l'horloge de transaction,
pas l'horloge de l'instruction). En créant le post système dans LA MÊME
transaction que l'INSERT/UPDATE sur `tache`, on obtient :
  - post.created_at == tache.created_at  →  post de création de tâche
  - post.created_at == tache.updated_at  →  post de clôture de tâche
Aucune colonne supplémentaire n'était nécessaire pour ça.
"""
from .. import db


def list_taches_projet(projet_id: int) -> list[dict]:
    sql = """
        SELECT t.id, t.projet_id, t.titre, t.etat, t.type_deadline,
               t.date_debut, t.date_echeance, t.date_fin, t.dossier_lien,
               t.created_at, t.updated_at,
               vh.heures_cumulees,
               COALESCE(
                 (SELECT json_agg(json_build_object('id', u.id, 'prenom', u.prenom, 'nom', u.nom,
                                                     'avatar_chemin', u.avatar_chemin)
                                   ORDER BY u.nom)
                  FROM tache_intervenant ti
                  JOIN utilisateur u ON u.id = ti.utilisateur_id
                  WHERE ti.tache_id = t.id),
                 '[]'
               ) AS intervenants,
               COALESCE(
                 (SELECT json_agg(json_build_object('id', pj.id, 'nom_fichier', pj.nom_fichier)
                                   ORDER BY pj.uploaded_at)
                  FROM tache_piece_jointe pj
                  WHERE pj.tache_id = t.id),
                 '[]'
               ) AS pieces_jointes
        FROM tache t
        LEFT JOIN v_tache_heures vh ON vh.tache_id = t.id
        WHERE t.projet_id = %s
        ORDER BY (t.etat NOT IN ('termine', 'abandonne')) DESC,
                 t.date_echeance NULLS LAST,
                 t.id
    """
    return db.query_all(sql, (projet_id,))


def get_tache(tache_id: int) -> dict | None:
    sql = """
        SELECT t.*, p.nom AS projet_nom, p.code AS projet_code,
               vh.heures_cumulees
        FROM tache t
        JOIN projet p ON p.id = t.projet_id
        LEFT JOIN v_tache_heures vh ON vh.tache_id = t.id
        WHERE t.id = %s
    """
    return db.query_one(sql, (tache_id,))


def list_mes_taches(user_id: int, limit: int = 10) -> list[dict]:
    """Tâches en cours dont l'utilisateur est l'intervenant ou le créateur
    (carte "Mes tâches" de l'accueil)."""
    sql = """
        SELECT t.id, t.titre, t.etat, t.date_echeance, p.id AS projet_id, p.nom AS projet_nom
        FROM tache t
        JOIN projet p ON p.id = t.projet_id
        WHERE t.etat NOT IN ('termine', 'abandonne')
          AND (
                t.created_by = %(uid)s
                OR EXISTS (
                     SELECT 1 FROM tache_intervenant ti
                     WHERE ti.tache_id = t.id AND ti.utilisateur_id = %(uid)s
                   )
              )
        ORDER BY t.date_echeance NULLS LAST
        LIMIT %(limit)s
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"uid": user_id, "limit": limit})
        return [dict(r) for r in cur.fetchall()]


def list_deadlines(user_id: int, limit: int = 20) -> list[dict]:
    """Échéances à venir sur les projets où l'utilisateur est impliqué
    (chef, co-chef, intervenant projet, ou intervenant tâche)."""
    sql = """
        SELECT DISTINCT t.id, t.titre, t.etat, t.date_echeance, t.type_deadline,
               p.id AS projet_id, p.code AS projet_code, p.nom AS projet_nom
        FROM tache t
        JOIN projet p ON p.id = t.projet_id
        LEFT JOIN projet_co_chef cc ON cc.projet_id = p.id AND cc.utilisateur_id = %(uid)s
        LEFT JOIN projet_intervenant pi ON pi.projet_id = p.id AND pi.utilisateur_id = %(uid)s
        LEFT JOIN tache_intervenant ti ON ti.tache_id = t.id AND ti.utilisateur_id = %(uid)s
        WHERE t.etat NOT IN ('termine', 'abandonne')
          AND t.date_echeance IS NOT NULL
          AND (
                p.chef_projet_id = %(uid)s
                OR cc.utilisateur_id IS NOT NULL
                OR pi.utilisateur_id IS NOT NULL
                OR ti.utilisateur_id IS NOT NULL
              )
        ORDER BY t.date_echeance
        LIMIT %(limit)s
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"uid": user_id, "limit": limit})
        return [dict(r) for r in cur.fetchall()]


def create_tache(
    projet_id: int,
    titre: str,
    current_user_id: int,
    type_deadline: str = "rendu_client",
    date_debut=None,
    date_echeance=None,
    intervenant_ids: list[int] | None = None,
    parent_post_id: int | None = None,
) -> int:
    """Crée la tâche ET son post système de création, dans une seule
    transaction (voir la note en tête de fichier sur la convention
    created_at == created_at). `parent_post_id` relie ce post système au
    post d'origine quand la tâche est créée via un "rebond" (voir
    routes/projets.py:nouveau_post et posts.py)."""
    with db.get_cursor(user_id=current_user_id) as cur:
        cur.execute(
            """
            INSERT INTO tache (projet_id, titre, type_deadline, date_debut, date_echeance, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (projet_id, titre, type_deadline, date_debut, date_echeance, current_user_id),
        )
        tache_id = cur.fetchone()["id"]

        for uid in intervenant_ids or []:
            cur.execute(
                "INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (%s, %s)",
                (tache_id, uid),
            )

        cur.execute(
            """
            INSERT INTO post (projet_id, tache_id, parent_post_id, auteur_id, type_code, contenu)
            VALUES (%s, %s, %s, %s, 'envoi', %s)
            """,
            (projet_id, tache_id, parent_post_id, current_user_id, titre),
        )
        return tache_id


def set_etat(tache_id: int, etat: str, current_user_id: int) -> None:
    """Changement d'état simple (En cours / Bloqué / Vérifié / Arrêt /
    Abandonné) — pas de post automatique, contrairement à la clôture
    ("Terminé", voir close_tache)."""
    db.execute(
        "UPDATE tache SET etat = %s WHERE id = %s",
        (etat, tache_id),
        user_id=current_user_id,
    )


def add_piece_jointe(tache_id: int, nom_fichier: str, chemin: str, uploaded_by: int) -> int:
    with db.get_cursor(user_id=uploaded_by) as cur:
        cur.execute(
            """
            INSERT INTO tache_piece_jointe (tache_id, nom_fichier, chemin, uploaded_by)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (tache_id, nom_fichier, chemin, uploaded_by),
        )
        return cur.fetchone()["id"]


def get_piece_jointe(piece_id: int) -> dict | None:
    return db.query_one(
        "SELECT id, tache_id, nom_fichier, chemin FROM tache_piece_jointe WHERE id = %s",
        (piece_id,),
    )


def close_tache(tache_id: int, current_user_id: int, type_code: str, contenu: str | None = None) -> int:
    """Clôture une tâche (etat='termine', date_fin=aujourd'hui) et génère
    toujours le post automatique associé, avec le tag choisi par
    l'utilisateur au moment de la clôture (voir spec : "son tag est
    choisi par l'utilisateur à ce moment-là, ce n'est pas systématiquement
    'Envoi'"). Les deux écritures sont dans la même transaction pour que
    post.created_at == tache.updated_at (marqueur d'évènement de clôture,
    voir la note en tête de fichier).
    """
    with db.get_cursor(user_id=current_user_id) as cur:
        cur.execute(
            """
            UPDATE tache SET etat = 'termine', date_fin = CURRENT_DATE
            WHERE id = %s
            RETURNING id, projet_id, titre
            """,
            (tache_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Tâche {tache_id} introuvable")

        cur.execute(
            """
            INSERT INTO post (projet_id, tache_id, auteur_id, type_code, contenu)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (row["projet_id"], tache_id, current_user_id, type_code, contenu),
        )
        return cur.fetchone()["id"]

"""Requêtes SQL liées aux tâches.

Les posts « système » de création et de clôture d'une tâche sont marqués
explicitement par la colonne `post.evenement` ('creation_tache' /
'cloture_tache', migrations 0004-0005), écrite ici dans la même
transaction que l'INSERT/UPDATE sur `tache`. L'ancienne heuristique
(post.created_at == tache.created_at / updated_at) n'est plus utilisée :
elle cassait dès que la tâche était modifiée après sa clôture.
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
          -- Projets terminés/abandonnés exclus, comme pour les échéances
          -- (PROMPT_CORRECTIONS.md P2 #23, étendu à "Mes tâches" — audit n°2).
          AND p.etat IN ('en_cours', 'bloque')
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
          -- PROMPT_CORRECTIONS.md P2 #23 : sans ce filtre, une tâche
          -- restée "en_cours"/"bloque" sur un projet déjà terminé ou
          -- abandonné continuait d'apparaître dans les échéances — le
          -- projet, lui, ne bouge plus, donc cette deadline ne sera
          -- jamais traitée.
          AND p.etat IN ('en_cours', 'bloque')
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
    transaction, marqué evenement='creation_tache' (voir la note en tête
    de fichier). `parent_post_id` relie ce post système au post d'origine
    quand la tâche est créée via un "rebond" (voir routes/projets.py:
    creer_tache, qui vérifie que ce post appartient au même projet)."""
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
            INSERT INTO post (projet_id, tache_id, parent_post_id, auteur_id, type_code, contenu, evenement)
            VALUES (%s, %s, %s, %s, 'envoi', %s, 'creation_tache')
            """,
            (projet_id, tache_id, parent_post_id, current_user_id, titre),
        )
        return tache_id


def user_est_intervenant(tache_id: int, user_id: int) -> bool:
    """Vrai si `user_id` est affecté comme intervenant sur cette tâche —
    en plus du chef de projet et des co-chefs (voir projets.user_can_manage),
    un intervenant de la tâche peut changer son état ou la clôturer
    (PROMPT_CORRECTIONS.md P0 #2)."""
    sql = "SELECT 1 FROM tache_intervenant WHERE tache_id = %s AND utilisateur_id = %s"
    with db.get_cursor() as cur:
        cur.execute(sql, (tache_id, user_id))
        return cur.fetchone() is not None


def set_etat(tache_id: int, projet_id: int, etat: str, current_user_id: int) -> bool:
    """Changement d'état simple (En cours / Bloqué / Vérifié / Arrêt /
    Abandonné) — pas de post automatique, contrairement à la clôture
    ("Terminé", voir close_tache).

    `projet_id` est ajouté au WHERE (PROMPT_CORRECTIONS.md P0 #2) : sans
    ça, connaître un tache_id suffisait à le modifier depuis n'importe
    quelle URL de projet, même un projet où l'appelant n'a aucun droit de
    gestion. Retourne False (au lieu de ne rien signaler) si la tâche
    n'existe pas ou n'appartient pas à ce projet.

    `date_fin` (PROMPT_CORRECTIONS.md P1 #9) : effacée seulement quand la
    tâche est ROUVERTE (En cours / Bloqué / Arrêt) — une tâche rouverte ne
    doit plus afficher une date de fin qui ne correspond plus à rien. Le
    passage à "Vérifié" (étape normale APRÈS la clôture) ou "Abandonné"
    garde en revanche la date de clôture (audit n°2 : elle était effacée
    à tort dès qu'une tâche terminée était vérifiée)."""
    rowcount = db.execute(
        """
        UPDATE tache
        SET etat = %s,
            date_fin = CASE WHEN %s IN ('en_cours', 'bloque', 'arret') THEN NULL ELSE date_fin END
        WHERE id = %s AND projet_id = %s
        """,
        (etat, etat, tache_id, projet_id),
        user_id=current_user_id,
    )
    return rowcount > 0


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
    """Inclut `projet_id` (jointure sur `tache`) pour permettre le contrôle
    d'accès à la volée avant de servir le fichier (PROMPT_CORRECTIONS.md
    P0 #1) — sans ça, un id de pièce jointe deviné/incrémenté suffisait à
    télécharger n'importe quel fichier de l'entreprise."""
    return db.query_one(
        """
        SELECT pj.id, pj.tache_id, pj.nom_fichier, pj.chemin, t.projet_id
        FROM tache_piece_jointe pj
        JOIN tache t ON t.id = pj.tache_id
        WHERE pj.id = %s
        """,
        (piece_id,),
    )


def close_tache(
    tache_id: int, projet_id: int, current_user_id: int, type_code: str, contenu: str | None = None,
) -> int | None:
    """Clôture une tâche (etat='termine', date_fin=aujourd'hui) et génère
    toujours le post automatique associé, avec le tag choisi par
    l'utilisateur au moment de la clôture (voir spec : "son tag est
    choisi par l'utilisateur à ce moment-là, ce n'est pas systématiquement
    'Envoi'"). Les deux écritures sont dans la même transaction pour que
    post.created_at == tache.updated_at (marqueur d'évènement de clôture,
    voir la note en tête de fichier).

    `projet_id` (PROMPT_CORRECTIONS.md P0 #2) : même garde-fou que
    set_etat(), on n'agit que sur une tâche appartenant bien à ce projet.
    `AND etat NOT IN ('termine', 'verifie')` empêche de clôturer deux fois
    la même tâche (y compris une tâche déjà clôturée puis vérifiée) —
    une reclôture écraserait date_fin et créerait un second post de
    clôture, en plus de casser le marqueur post.created_at==tache.updated_at
    utilisé pour l'affichage (voir la note en tête de fichier). Retourne
    None (jamais d'exception) si la tâche n'existe pas, n'appartient pas à
    ce projet, ou est déjà clôturée — la route transforme ça en message
    flash plutôt qu'en erreur 500."""
    with db.get_cursor(user_id=current_user_id) as cur:
        cur.execute(
            """
            UPDATE tache SET etat = 'termine', date_fin = CURRENT_DATE
            WHERE id = %s AND projet_id = %s AND etat NOT IN ('termine', 'verifie')
            RETURNING id, projet_id, titre
            """,
            (tache_id, projet_id),
        )
        row = cur.fetchone()
        if row is None:
            return None

        cur.execute(
            """
            INSERT INTO post (projet_id, tache_id, auteur_id, type_code, contenu, evenement)
            VALUES (%s, %s, %s, %s, %s, 'cloture_tache')
            RETURNING id
            """,
            (row["projet_id"], tache_id, current_user_id, type_code, contenu),
        )
        return cur.fetchone()["id"]

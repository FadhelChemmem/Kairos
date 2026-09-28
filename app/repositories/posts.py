"""Requêtes SQL liées au fil de posts (feed), réactions et commentaires."""
from .. import db

_FEED_SELECT = """
    SELECT p.id, p.type_code, p.contenu, p.lien, p.created_at, p.tache_id, p.parent_post_id,
           p.projet_id, proj.code AS projet_code, proj.nom AS projet_nom,
           u.id AS auteur_id, u.prenom AS auteur_prenom, u.nom AS auteur_nom,
           u.avatar_chemin AS auteur_avatar_chemin,
           t.titre AS tache_titre, t.etat AS tache_etat,
           -- PROMPT_CORRECTIONS.md P1 #9 : marqueur explicite (colonne
           -- post.evenement, migration 0004) au lieu de l'ancienne
           -- heuristique post.created_at == tache.created_at/updated_at,
           -- cassée par trg_tache_updated_at qui réécrit updated_at à
           -- CHAQUE modification de la tâche (pas seulement sa clôture) —
           -- voir repositories/taches.py.
           (p.evenement = 'creation_tache') AS est_creation_tache,
           (p.evenement = 'cloture_tache') AS est_cloture_tache,
           -- "Reposter" (Lot 5, retour Fadhel, 2026-09-28) : distingue au
           -- rendu un repost (post.evenement = 'repost') d'un rebond normal
           -- (parent_post_id renseigné mais evenement NULL) — voir
           -- posts.repost() / post_card.html.
           (p.evenement = 'repost') AS est_repost,
           -- L'utilisateur gère-t-il le projet du post (chef ou co-chef) ?
           -- Sert à n'afficher "+ Tâche" (rebond) qu'à ceux qui pourront
           -- effectivement la créer (audit n°2 : le bouton était montré à
           -- tous, puis refusé par le serveur une fois le formulaire rempli).
           (proj.chef_projet_id = %(uid)s OR EXISTS (
              SELECT 1 FROM projet_co_chef cc
              WHERE cc.projet_id = p.projet_id AND cc.utilisateur_id = %(uid)s
           )) AS je_gere,
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
           -- Commentaires façon réseau social (Lot 5, retour Fadhel,
           -- 2026-09-28) : renvoyés à plat ici (comme avant), restructurés
           -- en (premier niveau + réponses imbriquées) juste après la
           -- lecture — voir _structurer_commentaires ci-dessous, appliqué
           -- par chaque fonction list_feed_*.
           COALESCE(
             (SELECT json_agg(json_build_object(
                                'id', c.id, 'contenu', c.contenu, 'created_at', c.created_at,
                                'parent_commentaire_id', c.parent_commentaire_id,
                                'auteur_id', cu.id, 'auteur_prenom', cu.prenom, 'auteur_nom', cu.nom,
                                'auteur_avatar_chemin', cu.avatar_chemin,
                                'mentionne_user_id', c.mentionne_user_id,
                                'mentionne_prenom', mu2.prenom, 'mentionne_nom', mu2.nom,
                                'pieces_jointes', COALESCE(
                                  (SELECT json_agg(json_build_object('id', cpj.id, 'nom_fichier', cpj.nom_fichier)
                                                    ORDER BY cpj.uploaded_at)
                                   FROM post_commentaire_piece_jointe cpj
                                   WHERE cpj.commentaire_id = c.id),
                                  '[]'
                                ))
                               ORDER BY c.created_at)
              FROM post_commentaire c
              JOIN utilisateur cu ON cu.id = c.auteur_id
              LEFT JOIN utilisateur mu2 ON mu2.id = c.mentionne_user_id
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


def _structurer_commentaires(rows: list[dict]) -> list[dict]:
    """Restructure, pour chaque post, sa liste PLATE de commentaires
    (celle renvoyée par _FEED_SELECT) en (commentaires de premier niveau
    + réponses imbriquées sous `replies`) — Lot 5, retour Fadhel,
    2026-09-28 : "réponse en ligne". Fait en Python plutôt qu'en SQL
    (json_agg récursif serait nettement moins lisible) ; le volume par
    post reste petit, donc le coût est négligeable."""
    for post in rows:
        plats = post["commentaires"]
        par_id = {c["id"]: {**c, "replies": []} for c in plats}
        racine = []
        for c in plats:
            noeud = par_id[c["id"]]
            if c["parent_commentaire_id"] and c["parent_commentaire_id"] in par_id:
                par_id[c["parent_commentaire_id"]]["replies"].append(noeud)
            else:
                racine.append(noeud)
        post["commentaires"] = racine
    return rows


def list_feed_projet(projet_id: int, current_user_id: int, limit: int = 30) -> list[dict]:
    sql = _FEED_SELECT + """
        WHERE p.projet_id = %(pid)s
        ORDER BY p.created_at DESC
        LIMIT %(limit)s
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"uid": current_user_id, "pid": projet_id, "limit": limit})
        return _structurer_commentaires([dict(r) for r in cur.fetchall()])


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
        return _structurer_commentaires([dict(r) for r in cur.fetchall()])


def list_feed_auteur(auteur_id: int, viewer_id: int, limit: int = 8) -> list[dict]:
    """Posts récents d'UNE personne (page de profil, Lot 5, retour Fadhel
    2026-09-28) — filtrés à ce que LE VISITEUR (`viewer_id`) peut voir
    (v_projet_visibilite), pas ce que l'auteur peut voir : un profil ne
    doit pas devenir un détour pour lire le fil d'une équipe à laquelle
    on n'appartient pas (même logique que taches.list_en_cours_pour_profil
    / projets.list_ids_visibles). `%(uid)s` reste le VISITEUR — c'est
    aussi lui dont dépendent "je_gere"/"ma_reaction" dans _FEED_SELECT."""
    sql = _FEED_SELECT + """
        WHERE p.auteur_id = %(auteur_id)s
          AND EXISTS (
                SELECT 1 FROM v_projet_visibilite vv
                WHERE vv.projet_id = p.projet_id AND vv.utilisateur_id = %(uid)s
              )
        ORDER BY p.created_at DESC
        LIMIT %(limit)s
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"uid": viewer_id, "auteur_id": auteur_id, "limit": limit})
        return _structurer_commentaires([dict(r) for r in cur.fetchall()])


def get_post(post_id: int) -> dict | None:
    """Version minimale d'un post (id, projet, tâche, parent, auteur) —
    utilisée pour les contrôles d'accès (visibilité du projet porteur)
    avant de réagir/commenter/rebondir sur un post existant, voir
    PROMPT_CORRECTIONS.md P0 #1."""
    return db.query_one(
        "SELECT id, projet_id, tache_id, parent_post_id, auteur_id FROM post WHERE id = %s",
        (post_id,),
    )


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


def add_comment(
    post_id: int, auteur_id: int, contenu: str,
    mentionne_user_id: int | None = None, parent_commentaire_id: int | None = None,
) -> int:
    """`parent_commentaire_id` (Lot 5, retour Fadhel, 2026-09-28 : "réponse
    en ligne") DOIT déjà avoir été validé par l'appelant — voir
    routes/posts.py:commenter — comme référençant un commentaire du MÊME
    post_id et lui-même de premier niveau (pas de fil imbriqué à
    l'infini)."""
    with db.get_cursor(user_id=auteur_id) as cur:
        cur.execute(
            """
            INSERT INTO post_commentaire (post_id, auteur_id, contenu, mentionne_user_id, parent_commentaire_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (post_id, auteur_id, contenu, mentionne_user_id, parent_commentaire_id),
        )
        return cur.fetchone()["id"]


def get_commentaire(commentaire_id: int) -> dict | None:
    """Inclut `post_id`/`projet_id` (contrôle d'accès, IDOR) et
    `parent_commentaire_id` (pour vérifier qu'on ne répond pas à une
    réponse — voir add_comment/routes/posts.py:commenter)."""
    return db.query_one(
        """
        SELECT c.id, c.post_id, c.parent_commentaire_id, p.projet_id
        FROM post_commentaire c
        JOIN post p ON p.id = c.post_id
        WHERE c.id = %s
        """,
        (commentaire_id,),
    )


def add_piece_jointe_commentaire(commentaire_id: int, nom_fichier: str, chemin: str, uploaded_by: int) -> int:
    with db.get_cursor(user_id=uploaded_by) as cur:
        cur.execute(
            """
            INSERT INTO post_commentaire_piece_jointe (commentaire_id, nom_fichier, chemin, uploaded_by)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (commentaire_id, nom_fichier, chemin, uploaded_by),
        )
        return cur.fetchone()["id"]


def get_piece_jointe_commentaire(piece_id: int) -> dict | None:
    """Inclut `projet_id` (double jointure jusqu'à `post`) pour le
    contrôle d'accès (IDOR, PROMPT_CORRECTIONS.md P0 #1), même principe
    que get_piece_jointe ci-dessous."""
    return db.query_one(
        """
        SELECT cpj.id, cpj.commentaire_id, cpj.nom_fichier, cpj.chemin, p.projet_id
        FROM post_commentaire_piece_jointe cpj
        JOIN post_commentaire c ON c.id = cpj.commentaire_id
        JOIN post p ON p.id = c.post_id
        WHERE cpj.id = %s
        """,
        (piece_id,),
    )


def repost(post_id: int, auteur_id: int, contenu: str | None = None) -> int:
    """"Reposter" (Lot 5, retour Fadhel, 2026-09-28) — distinct du
    "rebond" (parent_post_id + composeur, une nouvelle Tâche/Requête/etc.
    liée) : ici, un clic partage À NOUVEAU le post d'origine dans le même
    projet, avec le même type, et un commentaire court optionnel ajouté
    par le reposteur (façon "citer" un retweet) — jamais le contenu
    d'origine dupliqué en clair, le rendu (voir post_card.html) va
    chercher le post d'origine via parent_post_id, comme pour un rebond.
    `evenement='repost'` (migration 0007) distingue ce cas d'un rebond
    normal (evenement NULL) au rendu."""
    original = get_post(post_id)
    if original is None:
        raise ValueError(f"Post {post_id} introuvable")
    with db.get_cursor(user_id=auteur_id) as cur:
        cur.execute(
            """
            INSERT INTO post (projet_id, parent_post_id, auteur_id, type_code, contenu, evenement)
            SELECT projet_id, id, %(auteur_id)s, type_code, %(contenu)s, 'repost'
            FROM post WHERE id = %(post_id)s
            RETURNING id
            """,
            {"auteur_id": auteur_id, "contenu": contenu, "post_id": post_id},
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
    """Inclut `projet_id` (jointure sur `post`) pour permettre le contrôle
    d'accès à la volée avant de servir le fichier (PROMPT_CORRECTIONS.md
    P0 #1) — sans ça, un id de pièce jointe deviné/incrémenté suffisait à
    télécharger n'importe quel fichier de l'entreprise."""
    return db.query_one(
        """
        SELECT pj.id, pj.post_id, pj.nom_fichier, pj.chemin, p.projet_id
        FROM post_piece_jointe pj
        JOIN post p ON p.id = pj.post_id
        WHERE pj.id = %s
        """,
        (piece_id,),
    )



"""Requêtes SQL liées au fil de posts (feed), réactions et commentaires."""
from .. import db

# Qui voit un post (migration 0009, posts "Information", retour Fadhel,
# 2026-09-29) — `%(uid)s` est le lecteur :
# - post d'un projet : ceux qui voient le projet (v_projet_visibilite,
#   même règle que projets.user_can_view) ;
# - post SANS projet (Information d'équipe) : les membres des équipes
#   destinataires (post_equipe), l'auteur, les personnes taguées, et les
#   Admin/RH.
_POST_SANS_PROJET_VISIBLE = """
    (p.projet_id IS NULL AND (
        p.auteur_id = %(uid)s
        OR EXISTS (SELECT 1 FROM post_mention pmv WHERE pmv.post_id = p.id AND pmv.utilisateur_id = %(uid)s)
        OR EXISTS (
            SELECT 1 FROM utilisateur uv
            WHERE uv.id = %(uid)s AND uv.actif
              AND (uv.role IN ('admin', 'rh')
                   OR EXISTS (SELECT 1 FROM post_equipe pev
                              WHERE pev.post_id = p.id AND pev.equipe_code = uv.equipe_code))
        )
    ))
"""
_POST_VISIBLE = """
    (
      (p.projet_id IS NOT NULL AND EXISTS (
          SELECT 1 FROM v_projet_visibilite vv
          WHERE vv.projet_id = p.projet_id AND vv.utilisateur_id = %(uid)s))
      OR """ + _POST_SANS_PROJET_VISIBLE + """
    )
"""

_FEED_SELECT = """
    SELECT p.id, p.type_code, p.contenu, p.lien, p.created_at, p.tache_id, p.parent_post_id,
           p.projet_id, proj.code AS projet_code, proj.nom AS projet_nom, proj.etat AS projet_etat,
           -- Équipes destinataires d'une Information sans projet (migration 0009).
           COALESCE(
             (SELECT json_agg(e.libelle ORDER BY e.libelle)
              FROM post_equipe pe JOIN equipe e ON e.code = pe.equipe_code
              WHERE pe.post_id = p.id),
             '[]'
           ) AS equipes,
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
           -- Posts automatiques (migration 0009) : creation_projet,
           -- etat_projet, etat_tache, titre_tache — voir post_card.html.
           p.evenement,
           -- L'utilisateur gère-t-il le projet du post (chef ou co-chef) ?
           -- Sert à n'afficher "+ Tâche" (rebond) qu'à ceux qui pourront
           -- effectivement la créer (audit n°2 : le bouton était montré à
           -- tous, puis refusé par le serveur une fois le formulaire rempli).
           COALESCE(proj.chef_projet_id = %(uid)s OR EXISTS (
              SELECT 1 FROM projet_co_chef cc
              WHERE cc.projet_id = p.projet_id AND cc.utilisateur_id = %(uid)s
           ), false) AS je_gere,
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
                                'modifie_le', c.modifie_le,
                                -- @tags écrits dans le texte (migration 0009)
                                'mentions', COALESCE(
                                  (SELECT json_agg(json_build_object('id', cmu.id, 'prenom', cmu.prenom, 'nom', cmu.nom))
                                   FROM post_commentaire_mention cm JOIN utilisateur cmu ON cmu.id = cm.utilisateur_id
                                   WHERE cm.commentaire_id = c.id),
                                  '[]'
                                ),
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
    LEFT JOIN projet proj ON proj.id = p.projet_id
    LEFT JOIN tache t ON t.id = p.tache_id
    LEFT JOIN post parent ON parent.id = p.parent_post_id
    LEFT JOIN utilisateur parent_auteur ON parent_auteur.id = parent.auteur_id
    LEFT JOIN tache parent_tache ON parent_tache.id = parent.tache_id
"""


def _en_datetime(valeur):
    """Horodatage lu dans un json_agg (texte ISO, ex.
    "2026-09-29T12:07:27.816896+01:00") → datetime ; laissé tel quel s'il
    en est déjà un (fixtures de tests), None si vide ou illisible."""
    import datetime

    if valeur is None or isinstance(valeur, datetime.datetime):
        return valeur
    try:
        return datetime.datetime.fromisoformat(str(valeur))
    except ValueError:
        return None


def _structurer_commentaires(rows: list[dict]) -> list[dict]:
    """Restructure, pour chaque post, sa liste PLATE de commentaires
    (celle renvoyée par _FEED_SELECT) en (commentaires de premier niveau
    + réponses imbriquées sous `replies`) — Lot 5, retour Fadhel,
    2026-09-28 : "réponse en ligne". Fait en Python plutôt qu'en SQL
    (json_agg récursif serait nettement moins lisible) ; le volume par
    post reste petit, donc le coût est négligeable."""
    for post in rows:
        plats = post["commentaires"]
        # json_agg renvoie les dates en texte ISO (psycopg2 décode le JSON,
        # pas les timestamps qu'il contient) : les templates attendent des
        # datetime (filtre il_y_a) — relecture du 2026-09-29.
        for c in plats:
            for cle in ("created_at", "modifie_le"):
                c[cle] = _en_datetime(c.get(cle))
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
    l'utilisateur est chef, co-chef, intervenant — ou intervenant d'une
    tâche seulement (retour Fadhel, 2026-09-29, P1 : ces personnes ne
    voyaient rien du projet sur leur accueil) — plus les Informations
    d'équipe qui lui sont destinées (migration 0009)."""
    sql = _FEED_SELECT + """
        WHERE p.projet_id IN (
            SELECT pj.id FROM projet pj
            WHERE pj.chef_projet_id = %(uid)s
               OR EXISTS (SELECT 1 FROM projet_co_chef cc WHERE cc.projet_id = pj.id AND cc.utilisateur_id = %(uid)s)
               OR EXISTS (SELECT 1 FROM projet_intervenant pi WHERE pi.projet_id = pj.id AND pi.utilisateur_id = %(uid)s)
               OR EXISTS (SELECT 1 FROM tache tt JOIN tache_intervenant ti ON ti.tache_id = tt.id
                          WHERE tt.projet_id = pj.id AND ti.utilisateur_id = %(uid)s)
        )
        OR """ + _POST_SANS_PROJET_VISIBLE + """
        ORDER BY p.created_at DESC
        LIMIT %(limit)s
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"uid": current_user_id, "limit": limit})
        return _structurer_commentaires([dict(r) for r in cur.fetchall()])


def list_feed_auteur(auteur_id: int, viewer_id: int, limit: int = 8, depuis=None, avant=None) -> list[dict]:
    """Posts récents d'UNE personne (page de profil, Lot 5, retour Fadhel
    2026-09-28) — filtrés à ce que LE VISITEUR (`viewer_id`) peut voir
    (v_projet_visibilite), pas ce que l'auteur peut voir : un profil ne
    doit pas devenir un détour pour lire le fil d'une équipe à laquelle
    on n'appartient pas (même logique que taches.list_en_cours_pour_profil
    / projets.list_ids_visibles). `%(uid)s` reste le VISITEUR — c'est
    aussi lui dont dépendent "je_gere"/"ma_reaction" dans _FEED_SELECT.

    `depuis` / `avant` (dates, retour Fadhel, 2026-09-29, T3 : "ce qui est
    récent, sur une semaine, avec voir +") : posts publiés à partir de /
    avant ce jour-là."""
    sql = _FEED_SELECT + """
        WHERE p.auteur_id = %(auteur_id)s
          AND """ + _POST_VISIBLE + """
          AND (%(depuis)s::date IS NULL OR p.created_at >= %(depuis)s::date)
          AND (%(avant)s::date IS NULL OR p.created_at < %(avant)s::date)
        ORDER BY p.created_at DESC
        LIMIT %(limit)s
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"uid": viewer_id, "auteur_id": auteur_id, "limit": limit,
                          "depuis": depuis, "avant": avant})
        return _structurer_commentaires([dict(r) for r in cur.fetchall()])


def get_post(post_id: int) -> dict | None:
    """Version minimale d'un post (id, projet, tâche, parent, auteur, type)
    — utilisée pour les contrôles d'accès (voir peut_voir) avant de
    réagir/commenter/reposter sur un post existant, voir
    PROMPT_CORRECTIONS.md P0 #1."""
    return db.query_one(
        """
        SELECT p.id, p.projet_id, p.tache_id, p.parent_post_id, p.auteur_id, p.type_code,
               proj.etat AS projet_etat
        FROM post p LEFT JOIN projet proj ON proj.id = p.projet_id
        WHERE p.id = %s
        """,
        (post_id,),
    )


def peut_voir(post_id: int, projet_id: int | None, user_id: int) -> bool:
    """Contrôle d'accès DIRECT à un post (réagir, commenter, reposter,
    télécharger une pièce jointe…) — même règle que les listes du fil
    (_POST_VISIBLE). Un post de projet suit la visibilité du projet ; un
    post sans projet (Information d'équipe, migration 0009) suit ses
    destinataires."""
    if projet_id is not None:
        from . import projets as projets_repo
        return projets_repo.user_can_view(projet_id, user_id)
    return db.query_one(
        "SELECT 1 FROM post p WHERE p.id = %(pid)s AND " + _POST_SANS_PROJET_VISIBLE,
        {"pid": post_id, "uid": user_id},
    ) is not None


def create_post(
    projet_id: int | None,
    auteur_id: int,
    type_code: str,
    contenu: str | None,
    tache_id: int | None = None,
    parent_post_id: int | None = None,
    lien: str | None = None,
    mentionne_ids: list[int] | None = None,
    piece_jointe: tuple[str, str] | None = None,
    equipe_codes: list[str] | None = None,
) -> int:
    """Création manuelle d'un post (Envoi/Réponse/Question/Requête), ou
    d'un "rebond" quand parent_post_id est renseigné (voir spec : l'action
    interne "rebondir", jamais affichée sous ce nom dans l'UI — seulement
    une icône flèche).

    `lien` et `mentionne_ids` (personnes taguées) sont optionnels, ajoutés
    2026-09-18 pour le composeur "Nouveau post" (panneau Requête).

    `piece_jointe` (nom_fichier, chemin), optionnel : quand fourni, la
    pièce jointe est insérée dans LA MÊME transaction que le post (audit
    sécurité/qualité externe, 2026-09-28, suivi P0-3 round 2 — Luna).
    Avant ce correctif, routes/posts.py appelait create_post() puis, dans
    un second temps/une seconde transaction déjà committée, l'insertion
    de la pièce jointe : si celle-ci échouait, le fichier orphelin était
    bien nettoyé (P0-3 round 1), mais le post restait en base SANS sa
    pièce jointe — un post créé par erreur en apparence "réussi" alors
    que l'utilisateur voulait joindre un fichier. En passant `piece_jointe`
    ici, un échec de l'insertion fait échouer TOUT le bloc `with
    db.get_cursor()`, qui annule alors aussi la création du post lui-même
    (rollback automatique) — le fichier sur disque reste alors à nettoyer
    par l'appelant (voir routes/posts.py).

    `projet_id` None + `equipe_codes` : Information d'équipe sans projet
    (migration 0009) — les équipes destinataires sont enregistrées dans la
    même transaction."""
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

        for code in equipe_codes or []:
            cur.execute(
                "INSERT INTO post_equipe (post_id, equipe_code) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (post_id, code),
            )

        if piece_jointe is not None:
            nom_fichier, chemin = piece_jointe
            cur.execute(
                """
                INSERT INTO post_piece_jointe (post_id, nom_fichier, chemin, uploaded_by)
                VALUES (%s, %s, %s, %s)
                """,
                (post_id, nom_fichier, chemin, auteur_id),
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
    piece_jointe: tuple[str, str] | None = None,
    mention_ids: list[int] | None = None,
) -> int:
    """`parent_commentaire_id` (Lot 5, retour Fadhel, 2026-09-28 : "réponse
    en ligne") DOIT déjà avoir été validé par l'appelant — voir
    routes/posts.py:commenter — comme référençant un commentaire du MÊME
    post_id et lui-même de premier niveau (pas de fil imbriqué à
    l'infini).

    `piece_jointe` (nom_fichier, chemin), optionnel : même principe que
    create_post() ci-dessus — insérée dans LA MÊME transaction que le
    commentaire, pour qu'un échec de cette insertion annule aussi le
    commentaire plutôt que de laisser un commentaire sans sa pièce jointe
    (audit sécurité/qualité externe, 2026-09-28, suivi P0-3 round 2).

    `mention_ids` (migration 0009) : personnes taguées "@Prénom Nom" dans
    le texte, déjà filtrées par l'appelant (routes/posts.py)."""
    with db.get_cursor(user_id=auteur_id) as cur:
        cur.execute(
            """
            INSERT INTO post_commentaire (post_id, auteur_id, contenu, mentionne_user_id, parent_commentaire_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (post_id, auteur_id, contenu, mentionne_user_id, parent_commentaire_id),
        )
        commentaire_id = cur.fetchone()["id"]

        for uid in mention_ids or []:
            cur.execute(
                """
                INSERT INTO post_commentaire_mention (commentaire_id, utilisateur_id)
                VALUES (%s, %s) ON CONFLICT DO NOTHING
                """,
                (commentaire_id, uid),
            )

        if piece_jointe is not None:
            nom_fichier, chemin = piece_jointe
            cur.execute(
                """
                INSERT INTO post_commentaire_piece_jointe (commentaire_id, nom_fichier, chemin, uploaded_by)
                VALUES (%s, %s, %s, %s)
                """,
                (commentaire_id, nom_fichier, chemin, auteur_id),
            )

        return commentaire_id


def modifier_commentaire(commentaire_id: int, auteur_id: int, contenu: str, mention_ids: list[int]) -> list[int] | None:
    """Modification d'un commentaire PAR SON AUTEUR (retour Fadhel,
    2026-09-29) — `auteur_id` au WHERE : l'appelant a déjà vérifié, mais
    la requête ne touche de toute façon que les commentaires de cette
    personne. Les @tags sont recalculés depuis le nouveau texte. Retourne
    les personnes NOUVELLEMENT taguées (à notifier), ou None si le
    commentaire n'existe pas / n'est pas de cet auteur."""
    with db.get_cursor(user_id=auteur_id) as cur:
        cur.execute(
            """
            UPDATE post_commentaire SET contenu = %s, modifie_le = now()
            WHERE id = %s AND auteur_id = %s
            RETURNING id
            """,
            (contenu, commentaire_id, auteur_id),
        )
        if cur.fetchone() is None:
            return None
        cur.execute(
            "SELECT utilisateur_id FROM post_commentaire_mention WHERE commentaire_id = %s",
            (commentaire_id,),
        )
        avant = {int(r["utilisateur_id"]) for r in cur.fetchall()}
        cur.execute(
            "DELETE FROM post_commentaire_mention WHERE commentaire_id = %s AND NOT (utilisateur_id = ANY(%s::bigint[]))",
            (commentaire_id, list(mention_ids)),
        )
        for uid in mention_ids:
            cur.execute(
                """
                INSERT INTO post_commentaire_mention (commentaire_id, utilisateur_id)
                VALUES (%s, %s) ON CONFLICT DO NOTHING
                """,
                (commentaire_id, uid),
            )
        return [uid for uid in mention_ids if uid not in avant]


def supprimer_commentaire(commentaire_id: int, current_user_id: int) -> list[str]:
    """Suppression d'un commentaire (réservée aux admins — contrôlé par la
    route, retour Fadhel, 2026-09-29), avec ses réponses, leurs @tags et
    leurs pièces jointes (ON DELETE CASCADE). Retourne les chemins des
    fichiers à effacer du disque APRÈS la validation de la transaction."""
    with db.get_cursor(user_id=current_user_id) as cur:
        cur.execute(
            """
            SELECT cpj.chemin FROM post_commentaire_piece_jointe cpj
            JOIN post_commentaire c ON c.id = cpj.commentaire_id
            WHERE c.id = %(id)s OR c.parent_commentaire_id = %(id)s
            """,
            {"id": commentaire_id},
        )
        chemins = [r["chemin"] for r in cur.fetchall()]
        cur.execute("DELETE FROM post_commentaire WHERE id = %s", (commentaire_id,))
        return chemins


def get_commentaire(commentaire_id: int) -> dict | None:
    """Inclut `post_id`/`projet_id` (contrôle d'accès, IDOR) et
    `parent_commentaire_id` (pour vérifier qu'on ne répond pas à une
    réponse — voir add_comment/routes/posts.py:commenter)."""
    return db.query_one(
        """
        SELECT c.id, c.post_id, c.parent_commentaire_id, c.auteur_id, c.contenu, p.projet_id
        FROM post_commentaire c
        JOIN post p ON p.id = c.post_id
        WHERE c.id = %s
        """,
        (commentaire_id,),
    )


def get_piece_jointe_commentaire(piece_id: int) -> dict | None:
    """Inclut `projet_id` (double jointure jusqu'à `post`) pour le
    contrôle d'accès (IDOR, PROMPT_CORRECTIONS.md P0 #1), même principe
    que get_piece_jointe ci-dessous."""
    return db.query_one(
        """
        SELECT cpj.id, cpj.commentaire_id, cpj.nom_fichier, cpj.chemin, p.projet_id, c.post_id
        FROM post_commentaire_piece_jointe cpj
        JOIN post_commentaire c ON c.id = cpj.commentaire_id
        JOIN post p ON p.id = c.post_id
        WHERE cpj.id = %s
        """,
        (piece_id,),
    )


def personnes_taguees(texte: str, candidats: list[dict]) -> list[int]:
    """Ids des personnes de `candidats` dont "@Prénom Nom" figure dans
    `texte` (tag écrit directement dans le commentaire, retour Fadhel,
    2026-09-29) — insensible à la casse, et jamais un préfixe d'un nom plus
    long ("@Ali Ben" ne tague pas "Ali Ben Salah" quand c'est lui qu'on a
    écrit : le nom le plus long l'emporte)."""
    import re

    reste = texte or ""
    trouves = []
    for p in sorted(candidats, key=lambda c: -len(f"{c['prenom']} {c['nom']}")):
        motif = re.compile(re.escape(f"@{p['prenom']} {p['nom']}") + r"(?!\w)", re.IGNORECASE)
        if not motif.search(reste):
            continue
        trouves.append(p["id"])
        reste = motif.sub(" ", reste)
    return trouves


def equipes_du_post(post_id: int) -> list[str]:
    """Codes des équipes destinataires d'une Information sans projet."""
    rows = db.query_all("SELECT equipe_code FROM post_equipe WHERE post_id = %s ORDER BY equipe_code", (post_id,))
    return [r["equipe_code"] for r in rows]


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
        nouveau_id = cur.fetchone()["id"]
        # Information d'équipe sans projet : le repost va aux mêmes équipes
        # (sinon seuls l'auteur et les Admin/RH le verraient).
        cur.execute(
            """
            INSERT INTO post_equipe (post_id, equipe_code)
            SELECT %s, equipe_code FROM post_equipe WHERE post_id = %s
            """,
            (nouveau_id, post_id),
        )
        return nouveau_id


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



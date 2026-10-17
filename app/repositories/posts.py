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
                   -- Lot 13 (décision 6, audit rôles M3) : une Information
                   -- interne d'équipe n'arrive jamais chez un Client (sauf
                   -- s'il y est nommément mentionné).
                   OR (uv.role <> 'client' AND EXISTS (SELECT 1 FROM post_equipe pev
                              WHERE pev.post_id = p.id AND pev.equipe_code = uv.equipe_code)))
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

# Lot 14 (revue produit P1-3) : post automatique (« Activité ») — tout
# évènement sauf « Donner suite » (repost) et la clôture d'une tâche
# accompagnée d'un message écrit par la personne (« Échanges »). Voir app/fil.py.
# Lot 14 (fusion) : le signalement d'un blocage porte le motif écrit par la
# personne (« Échanges ») ; une clôture sans message (texte automatique
# « Tâche terminée. », TEXTE_CLOTURE_SANS_MESSAGE) reste de l'« Activité ».
# Lot 16 : la levée d'un blocage va aussi dans « Échanges » (sinon la carte
# du blocage laissait croire la tâche toujours bloquée).
_EST_ACTIVITE = """(p.evenement IS NOT NULL AND p.evenement NOT IN ('repost', 'blocage_tache', 'deblocage_tache')
    AND NOT (p.evenement = 'cloture_tache'
             AND COALESCE(btrim(p.contenu), '') NOT IN ('', 'Tâche terminée.')))"""
_FILTRE_CATEGORIE = {"tout": "TRUE", "echanges": "NOT " + _EST_ACTIVITE, "activite": _EST_ACTIVITE}

_FEED_SELECT = """
    SELECT p.id, p.type_code, p.contenu, p.lien, p.created_at, p.tache_id, p.parent_post_id,
           p.modifie_le, p.supprime_le,
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
           -- post_card.html (reposts faits avant le lot 7).
           (p.evenement = 'repost') AS est_repost,
           -- Posts automatiques (migration 0009) : creation_projet,
           -- etat_projet, etat_tache, titre_tache — voir post_card.html.
           p.evenement,
           """ + _EST_ACTIVITE + """ AS est_activite,
           -- L'utilisateur gère-t-il le projet du post (chef ou co-chef) ?
           -- Sert à n'afficher "+ Tâche" (rebond) qu'à ceux qui pourront
           -- effectivement la créer (audit n°2 : le bouton était montré à
           -- tous, puis refusé par le serveur une fois le formulaire rempli).
           -- Jamais un Client ni le RH (lot 7, voir projets.user_can_manage).
           COALESCE((proj.chef_projet_id = %(uid)s OR EXISTS (
              SELECT 1 FROM projet_co_chef cc
              WHERE cc.projet_id = p.projet_id AND cc.utilisateur_id = %(uid)s
           ) OR (p.projet_id IS NOT NULL AND EXISTS (
              SELECT 1 FROM utilisateur ua WHERE ua.id = %(uid)s AND ua.role = 'admin'
           ))) AND NOT EXISTS (SELECT 1 FROM utilisateur ux WHERE ux.id = %(uid)s AND ux.role IN ('client', 'rh')), false) AS je_gere,
           (SELECT count(*) FROM post_reaction r WHERE r.post_id = p.id) AS nb_reactions,
           (SELECT count(*) FROM post_commentaire c WHERE c.post_id = p.id AND c.supprime_le IS NULL) AS nb_commentaires,
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
                                   WHERE cpj.commentaire_id = c.id AND cpj.retire_le IS NULL),
                                  '[]'
                                ))
                               ORDER BY c.created_at)
              FROM post_commentaire c
              JOIN utilisateur cu ON cu.id = c.auteur_id
              LEFT JOIN utilisateur mu2 ON mu2.id = c.mentionne_user_id
              WHERE c.post_id = p.id AND c.supprime_le IS NULL),
             '[]'
           ) AS commentaires,
           COALESCE(
             (SELECT json_agg(json_build_object('id', pj.id, 'nom_fichier', pj.nom_fichier)
                               ORDER BY pj.uploaded_at)
              FROM post_piece_jointe pj WHERE pj.post_id = p.id AND pj.retire_le IS NULL),
             '[]'
           ) AS pieces_jointes,
           -- Personnes ajoutées au post, affichées « avec » + pastilles (retour
           -- Fadhel, lot 8) : les personnes taguées d'une Information ou d'une
           -- Requête, et pour la création d'une tâche ses intervenants.
           COALESCE(
             (SELECT json_agg(json_build_object('id', x.id, 'prenom', x.prenom, 'nom', x.nom,
                                                'avatar_chemin', x.avatar_chemin)
                               ORDER BY x.nom, x.prenom)
              FROM (
                SELECT mu.id, mu.prenom, mu.nom, mu.avatar_chemin
                FROM post_mention pm JOIN utilisateur mu ON mu.id = pm.utilisateur_id
                WHERE pm.post_id = p.id
                UNION
                SELECT iu.id, iu.prenom, iu.nom, iu.avatar_chemin
                FROM tache_intervenant ti JOIN utilisateur iu ON iu.id = ti.utilisateur_id
                WHERE p.evenement = 'creation_tache' AND ti.tache_id = p.tache_id
              ) x),
             '[]'
           ) AS mentions,
           parent.contenu AS parent_contenu, parent.type_code AS parent_type_code,
           (parent.supprime_le IS NOT NULL) AS parent_supprime,
           parent.evenement AS parent_evenement,
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


def _lire_fil(condition: str, params: dict, limit: int, categorie: str = "tout", avant=None) -> list[dict]:
    """Une page du fil (lot 14) : les ids d'abord — `condition`, catégorie
    (Échanges / Activité) et curseur `avant` (created_at, id) dans le WHERE,
    tri et LIMIT sur l'index des dates —, puis le détail de ces seuls posts
    (réactions, commentaires, pièces jointes… : sous-requêtes de
    _FEED_SELECT calculées pour la page, jamais pour tous les candidats)."""
    filtre = _FILTRE_CATEGORIE.get(categorie, "TRUE")
    sql = """
        WITH page AS (
            SELECT p.id, p.created_at FROM post p
            WHERE p.supprime_le IS NULL AND (""" + condition + """)
              AND """ + filtre + """
              AND (%(avant_date)s::timestamptz IS NULL
                   OR (p.created_at, p.id) < (%(avant_date)s::timestamptz, %(avant_id)s::bigint))
            ORDER BY p.created_at DESC, p.id DESC
            LIMIT %(limit)s
        )
    """ + _FEED_SELECT + """
        WHERE p.id = ANY (ARRAY(SELECT id FROM page))
        ORDER BY p.created_at DESC, p.id DESC
    """
    avant_date, avant_id = avant if avant else (None, None)
    with db.get_cursor() as cur:
        cur.execute(sql, {**params, "limit": limit, "avant_date": avant_date, "avant_id": avant_id})
        return _structurer_commentaires([dict(r) for r in cur.fetchall()])


_CONDITION_MES_PROJETS = """
    p.projet_id IN (
        SELECT pj.id FROM projet pj
        WHERE (
           -- Rattachements : jamais pour un Client (lot 7), même s'il en
           -- reste d'avant la migration 0011.
           NOT EXISTS (SELECT 1 FROM utilisateur ux WHERE ux.id = %(uid)s AND ux.role = 'client')
           AND (pj.chef_projet_id = %(uid)s
           OR EXISTS (SELECT 1 FROM projet_co_chef cc WHERE cc.projet_id = pj.id AND cc.utilisateur_id = %(uid)s)
           OR EXISTS (SELECT 1 FROM projet_intervenant pi WHERE pi.projet_id = pj.id AND pi.utilisateur_id = %(uid)s)
           OR EXISTS (SELECT 1 FROM tache tt JOIN tache_intervenant ti ON ti.tache_id = tt.id
                      WHERE tt.projet_id = pj.id AND ti.utilisateur_id = %(uid)s))
        )
           -- Client (lot 7) : jamais rattaché, il suit les projets de son équipe.
           OR EXISTS (SELECT 1 FROM utilisateur uc
                      WHERE uc.id = %(uid)s AND uc.role = 'client' AND uc.equipe_code = pj.equipe_code)
           -- Lot 17 (gérant) : l'Admin suit les échanges de tous les projets ouverts.
           OR (pj.etat NOT IN ('termine', 'abandonne')
               AND EXISTS (SELECT 1 FROM utilisateur ua WHERE ua.id = %(uid)s AND ua.role = 'admin'))
    )
    OR """ + _POST_SANS_PROJET_VISIBLE


def _rang_dans_fil(condition: str, params: dict, categorie: str, post_id: int) -> int:
    """Rang du post `post_id` dans le fil (1 = le plus récent) : nombre de
    posts du fil jusqu'à lui, lui compris ; 0 s'il n'est pas dans ce fil
    (autre projet, invisible, autre catégorie). Sert à ouvrir le fil
    jusqu'à un post ancien (lien d'une notification, recette du lot 14
    n° 13)."""
    filtre = _FILTRE_CATEGORIE.get(categorie, "TRUE")
    sql = """
        WITH ancre AS (
            SELECT p.created_at, p.id FROM post p
            WHERE p.id = %(ancre)s AND p.supprime_le IS NULL AND (""" + condition + """) AND """ + filtre + """
        )
        SELECT count(*) AS n FROM post p, ancre
        WHERE p.supprime_le IS NULL AND (""" + condition + """) AND """ + filtre + """
          AND (p.created_at, p.id) >= (ancre.created_at, ancre.id)
    """
    ligne = db.query_one(sql, {**params, "ancre": post_id})
    return int(ligne["n"] or 0) if ligne else 0


def rang_dans_fil_projet(projet_id: int, current_user_id: int, categorie: str, post_id: int) -> int:
    return _rang_dans_fil("p.projet_id = %(pid)s", {"uid": current_user_id, "pid": projet_id}, categorie, post_id)


def rang_dans_fil_mes_projets(current_user_id: int, categorie: str, post_id: int) -> int:
    return _rang_dans_fil(_CONDITION_MES_PROJETS, {"uid": current_user_id}, categorie, post_id)


def list_feed_projet(projet_id: int, current_user_id: int, limit: int = 30, categorie: str = "tout",
                     avant=None) -> list[dict]:
    return _lire_fil("p.projet_id = %(pid)s", {"uid": current_user_id, "pid": projet_id}, limit, categorie, avant)


def list_feed_mes_projets(current_user_id: int, limit: int = 30, categorie: str = "tout", avant=None) -> list[dict]:
    """Fil d'activité de l'accueil : tous les posts des projets où
    l'utilisateur est chef, co-chef, intervenant — ou intervenant d'une
    tâche seulement (retour Fadhel, 2026-09-29, P1 : ces personnes ne
    voyaient rien du projet sur leur accueil) ; pour un Client, les projets
    de son équipe (lot 7) — plus les Informations d'équipe qui lui sont
    destinées (migration 0009). Le RH n'a que ces dernières."""
    return _lire_fil(_CONDITION_MES_PROJETS, {"uid": current_user_id}, limit, categorie, avant)


# --------------------------------------------------------------------------
# Lot 17 : posts pas encore vus du fil de l'accueil (migration 0022).
# --------------------------------------------------------------------------
CATEGORIES_VUES = ("echanges", "activite")


def fil_vu(user_id: int) -> dict:
    """{catégorie: dernière consultation} ; catégorie absente : jamais vue."""
    rows = db.query_all("SELECT categorie, vu_le FROM utilisateur_fil_vu WHERE utilisateur_id = %s", (user_id,))
    return {r["categorie"]: r["vu_le"] for r in rows}


def compter_non_vus(user_id: int, vus: dict) -> dict:
    """Posts du fil de l'accueil publiés depuis la dernière consultation de
    leur catégorie, hors ceux de la personne. Catégorie jamais vue : 0 (la
    première visite ne transforme pas tout l'historique en nouveautés)."""
    e, a = vus.get("echanges"), vus.get("activite")
    if e is None and a is None:
        return {"echanges": 0, "activite": 0}
    row = db.query_one(
        """
        SELECT count(*) FILTER (WHERE NOT """ + _EST_ACTIVITE + """ AND %(e)s::timestamptz IS NOT NULL
                                AND p.created_at > %(e)s::timestamptz) AS echanges,
               count(*) FILTER (WHERE """ + _EST_ACTIVITE + """ AND %(a)s::timestamptz IS NOT NULL
                                AND p.created_at > %(a)s::timestamptz) AS activite
        FROM post p
        WHERE p.supprime_le IS NULL AND p.auteur_id <> %(uid)s
          AND p.created_at > LEAST(COALESCE(%(e)s::timestamptz, 'infinity'), COALESCE(%(a)s::timestamptz, 'infinity'))
          AND (""" + _CONDITION_MES_PROJETS + """)
        """,
        {"uid": user_id, "e": e, "a": a},
    )
    return {"echanges": int(row["echanges"] or 0), "activite": int(row["activite"] or 0)} if row else \
        {"echanges": 0, "activite": 0}


def marquer_fil_vu(user_id: int, categories) -> None:
    """La personne vient de regarder ces catégories du fil."""
    cats = [c for c in categories if c in CATEGORIES_VUES]
    if not cats:
        return
    db.execute(
        """
        INSERT INTO utilisateur_fil_vu (utilisateur_id, categorie, vu_le)
        SELECT %s, c, now() FROM unnest(%s::text[]) AS c
        ON CONFLICT (utilisateur_id, categorie) DO UPDATE SET vu_le = EXCLUDED.vu_le
        """,
        (user_id, cats),
        user_id=user_id,
    )


def list_feed_auteur(auteur_id: int, viewer_id: int, limit: int = 8, depuis=None, avant=None,
                     categorie: str = "tout") -> list[dict]:
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
    condition = """
        p.auteur_id = %(auteur_id)s
          AND """ + _POST_VISIBLE + """
          AND (%(depuis)s::date IS NULL OR p.created_at >= %(depuis)s::date)
          AND (%(avant_jour)s::date IS NULL OR p.created_at < %(avant_jour)s::date)
    """
    return _lire_fil(condition, {"uid": viewer_id, "auteur_id": auteur_id, "depuis": depuis, "avant_jour": avant},
                     limit, categorie)


def get_post_carte(post_id: int, viewer_id: int) -> dict | None:
    """Un post tel que le fil l'affiche pour `viewer_id` (réactions,
    commentaires, pièces jointes…) : fragment d'une mise à jour partielle
    (lot 13). La visibilité est contrôlée par l'appelant (peut_voir)."""
    with db.get_cursor() as cur:
        cur.execute(_FEED_SELECT + " WHERE p.id = %(pid)s", {"uid": viewer_id, "pid": post_id})
        rows = _structurer_commentaires([dict(r) for r in cur.fetchall()])
    return rows[0] if rows else None


def id_post_creation_tache(tache_id: int) -> int | None:
    """Post automatique « a créé une tâche » de `tache_id` (lot 13 : inséré
    en tête du fil après « + Tâche »)."""
    row = db.query_one(
        "SELECT id FROM post WHERE tache_id = %s AND evenement = 'creation_tache' ORDER BY id DESC LIMIT 1",
        (tache_id,),
    )
    return row["id"] if row else None


def get_post(post_id: int) -> dict | None:
    """Version minimale d'un post (id, projet, tâche, parent, auteur, type)
    — utilisée pour les contrôles d'accès (voir peut_voir) avant de
    réagir/commenter/reposter sur un post existant, voir
    PROMPT_CORRECTIONS.md P0 #1."""
    return db.query_one(
        """
        SELECT p.id, p.projet_id, p.tache_id, p.parent_post_id, p.auteur_id, p.type_code,
               p.evenement, p.contenu, p.lien, p.supprime_le, p.supprime_par, p.created_at,
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
    pieces_jointes: list[tuple[str, str]] | None = None,
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

        # Lot 17 : plusieurs pièces jointes, dans la même transaction.
        for nom_fichier, chemin in ([piece_jointe] if piece_jointe is not None else []) + list(pieces_jointes or []):
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


def supprimer_commentaire(commentaire_id: int, current_user_id: int) -> tuple[list[int], str | None]:
    """Suppression LOGIQUE d'un commentaire et de ses réponses (lot 15,
    migration 0021) : « Annuler » la lève (restaurer_commentaires). Les
    droits sont contrôlés par la route. Retourne les ids supprimés et
    l'horodatage de CETTE suppression (lié au jeton « Annuler »)."""
    with db.get_cursor(user_id=current_user_id) as cur:
        cur.execute(
            """
            UPDATE post_commentaire SET supprime_le = now(), supprime_par = %(u)s
            WHERE (id = %(id)s OR parent_commentaire_id = %(id)s) AND supprime_le IS NULL
            RETURNING id, supprime_le
            """,
            {"id": commentaire_id, "u": current_user_id},
        )
        lignes = cur.fetchall()
        if not lignes:
            return [], None
        return [int(r["id"]) for r in lignes], lignes[0]["supprime_le"].isoformat()


def restaurer_commentaires(ids: list[int], current_user_id: int, quand: str) -> int:
    """« Annuler » une suppression de commentaire (lot 15) : seulement
    CELLE-LÀ (même personne, même instant), jamais une suppression
    ultérieure par quelqu'un d'autre."""
    with db.get_cursor(user_id=current_user_id) as cur:
        cur.execute(
            """
            UPDATE post_commentaire c SET supprime_le = NULL, supprime_par = NULL
            WHERE c.id = ANY(%(ids)s::bigint[]) AND c.supprime_le = %(t)s::timestamptz AND c.supprime_par = %(u)s
              -- Lot 16 : jamais une réponse dont le commentaire parent a été
              -- supprimé entre-temps (réponse orpheline).
              AND (c.parent_commentaire_id IS NULL OR c.parent_commentaire_id = ANY(%(ids)s::bigint[])
                   OR NOT EXISTS (SELECT 1 FROM post_commentaire par
                                  WHERE par.id = c.parent_commentaire_id AND par.supprime_le IS NOT NULL))
            """,
            {"ids": [int(i) for i in ids], "t": quand, "u": current_user_id},
        )
        return cur.rowcount


def get_commentaire(commentaire_id: int) -> dict | None:
    """Inclut `post_id`/`projet_id` (contrôle d'accès, IDOR) et
    `parent_commentaire_id` (pour vérifier qu'on ne répond pas à une
    réponse — voir add_comment/routes/posts.py:commenter)."""
    return db.query_one(
        """
        SELECT c.id, c.post_id, c.parent_commentaire_id, c.auteur_id, c.contenu, p.projet_id,
               proj.etat AS projet_etat, c.supprime_le
        FROM post_commentaire c
        JOIN post p ON p.id = c.post_id
        LEFT JOIN projet proj ON proj.id = p.projet_id
        WHERE c.id = %s AND p.supprime_le IS NULL
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
        WHERE cpj.id = %s AND cpj.retire_le IS NULL AND c.supprime_le IS NULL AND p.supprime_le IS NULL
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
        WHERE pj.id = %s AND pj.retire_le IS NULL AND p.supprime_le IS NULL
        """,
        (piece_id,),
    )




# --------------------------------------------------------------------------
# Lot 15 (migration 0021) : modifier ou supprimer un post, retirer ou
# ajouter une pièce jointe. Droits contrôlés par la route (routes/posts.py).
# --------------------------------------------------------------------------

def modifier_post(post_id: int, auteur_id: int, contenu: str, lien: str | None,
                  pj_retirees: list[int], pj_ajoutees: list[tuple[str, str]],
                  mention_ids: list[int] | None = None) -> list[int] | None:
    """Texte, lien et pièces jointes d'un post, PAR SON AUTEUR. Les pièces
    retirées le sont logiquement (fichier purgé 30 jours après). Retourne
    les pièces effectivement retirées, None si le post n'est pas modifiable
    par cette personne (absent, supprimé, autre auteur)."""
    with db.get_cursor(user_id=auteur_id) as cur:
        cur.execute(
            """
            UPDATE post SET contenu = %s, lien = %s, modifie_le = now()
            WHERE id = %s AND auteur_id = %s AND supprime_le IS NULL
            RETURNING id
            """,
            (contenu, lien, post_id, auteur_id),
        )
        if cur.fetchone() is None:
            return None
        retirees = []
        if pj_retirees:
            cur.execute(
                """
                UPDATE post_piece_jointe SET retire_le = now(), retire_par = %s
                WHERE post_id = %s AND id = ANY(%s::bigint[]) AND retire_le IS NULL
                RETURNING id
                """,
                (auteur_id, post_id, [int(i) for i in pj_retirees]),
            )
            retirees = [int(r["id"]) for r in cur.fetchall()]
        for nom_fichier, chemin in pj_ajoutees:
            cur.execute(
                "INSERT INTO post_piece_jointe (post_id, nom_fichier, chemin, uploaded_by) VALUES (%s, %s, %s, %s)",
                (post_id, nom_fichier, chemin, auteur_id),
            )
        if mention_ids is not None:
            cur.execute("SELECT utilisateur_id FROM post_mention WHERE post_id = %s", (post_id,))
            avant = {int(r["utilisateur_id"]) for r in cur.fetchall()}
            for uid in mention_ids:
                if uid not in avant:
                    cur.execute("INSERT INTO post_mention (post_id, utilisateur_id) VALUES (%s, %s) "
                                "ON CONFLICT DO NOTHING", (post_id, uid))
        return retirees


def supprimer_post(post_id: int, current_user_id: int) -> str | None:
    """Suppression LOGIQUE (« Annuler » : restaurer_post). Retourne
    l'horodatage de la suppression (lié au jeton), None si déjà supprimé."""
    with db.get_cursor(user_id=current_user_id) as cur:
        cur.execute(
            "UPDATE post SET supprime_le = now(), supprime_par = %s WHERE id = %s AND supprime_le IS NULL "
            "RETURNING supprime_le",
            (current_user_id, post_id),
        )
        ligne = cur.fetchone()
        return ligne["supprime_le"].isoformat() if ligne else None


def restaurer_post(post_id: int, current_user_id: int, quand: str) -> bool:
    """« Annuler » CETTE suppression (même personne, même instant)."""
    with db.get_cursor(user_id=current_user_id) as cur:
        cur.execute(
            "UPDATE post SET supprime_le = NULL, supprime_par = NULL "
            "WHERE id = %s AND supprime_le = %s::timestamptz AND supprime_par = %s",
            (post_id, quand, current_user_id),
        )
        return cur.rowcount == 1


def restaurer_pieces(ids: list[int], current_user_id: int, *, post_id: int | None = None,
                     commentaire_id: int | None = None) -> int:
    """« Annuler » le retrait de pièces jointes d'UN post ou d'UN
    commentaire, retirées par cette personne."""
    if (post_id is None) == (commentaire_id is None):
        raise ValueError("post_id ou commentaire_id, exactement un")
    if commentaire_id is not None:
        table, colonne, parent = "post_commentaire_piece_jointe", "commentaire_id", commentaire_id
    else:
        table, colonne, parent = "post_piece_jointe", "post_id", post_id
    with db.get_cursor(user_id=current_user_id) as cur:
        cur.execute(
            f"UPDATE {table} SET retire_le = NULL, retire_par = NULL "
            f"WHERE id = ANY(%s::bigint[]) AND {colonne} = %s AND retire_par = %s AND retire_le IS NOT NULL",
            ([int(i) for i in ids], parent, current_user_id),
        )
        return cur.rowcount


def pieces_du_post(post_id: int) -> list[dict]:
    return db.query_all(
        "SELECT id, nom_fichier FROM post_piece_jointe WHERE post_id = %s AND retire_le IS NULL ORDER BY uploaded_at",
        (post_id,),
    )


def pieces_du_commentaire(commentaire_id: int) -> list[dict]:
    return db.query_all(
        "SELECT id, nom_fichier FROM post_commentaire_piece_jointe "
        "WHERE commentaire_id = %s AND retire_le IS NULL ORDER BY uploaded_at",
        (commentaire_id,),
    )


def pieces_commentaire_modifiees(commentaire_id: int, auteur_id: int, retirees: list[int],
                                 ajoutees: list[tuple[str, str]]) -> list[int]:
    """Pièces jointes d'un commentaire modifié par son auteur : retraits
    logiques et ajouts. Retourne les pièces retirées."""
    with db.get_cursor(user_id=auteur_id) as cur:
        ids = []
        if retirees:
            cur.execute(
                """
                UPDATE post_commentaire_piece_jointe SET retire_le = now(), retire_par = %s
                WHERE commentaire_id = %s AND id = ANY(%s::bigint[]) AND retire_le IS NULL
                RETURNING id
                """,
                (auteur_id, commentaire_id, [int(i) for i in retirees]),
            )
            ids = [int(r["id"]) for r in cur.fetchall()]
        for nom_fichier, chemin in ajoutees:
            cur.execute(
                "INSERT INTO post_commentaire_piece_jointe (commentaire_id, nom_fichier, chemin, uploaded_by) "
                "VALUES (%s, %s, %s, %s)",
                (commentaire_id, nom_fichier, chemin, auteur_id),
            )
        return ids


DELAI_PURGE_JOURS = 30


def purger_pieces_retirees(jours: int = DELAI_PURGE_JOURS) -> list[str]:
    """Pièces jointes retirées depuis plus de `jours` jours : lignes
    supprimées, chemins rendus pour effacer les fichiers (après la
    transaction). Idempotent."""
    with db.get_cursor() as cur:
        chemins = []
        p = {"j": int(jours)}
        for sql in (
            "DELETE FROM post_piece_jointe WHERE retire_le < now() - make_interval(days => %(j)s) RETURNING chemin",
            "DELETE FROM post_commentaire_piece_jointe WHERE retire_le < now() - make_interval(days => %(j)s) "
            "RETURNING chemin",
            # Pièces d'un post ou d'un commentaire supprimé depuis 30 jours.
            "DELETE FROM post_piece_jointe pj USING post po WHERE po.id = pj.post_id "
            "AND po.supprime_le < now() - make_interval(days => %(j)s) RETURNING pj.chemin",
            "DELETE FROM post_commentaire_piece_jointe cpj USING post_commentaire c WHERE c.id = cpj.commentaire_id "
            "AND c.supprime_le < now() - make_interval(days => %(j)s) RETURNING cpj.chemin",
            # Pièces des commentaires d'un post supprimé depuis 30 jours.
            "DELETE FROM post_commentaire_piece_jointe cpj USING post_commentaire c, post po "
            "WHERE c.id = cpj.commentaire_id AND po.id = c.post_id "
            "AND po.supprime_le < now() - make_interval(days => %(j)s) RETURNING cpj.chemin",
        ):
            cur.execute(sql, p)
            chemins += [r["chemin"] for r in cur.fetchall()]
        return chemins

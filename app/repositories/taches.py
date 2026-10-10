"""Requêtes SQL liées aux tâches.

Les posts « système » de création et de clôture d'une tâche sont marqués
explicitement par la colonne `post.evenement` ('creation_tache' /
'cloture_tache', migrations 0004-0005), écrite ici dans la même
transaction que l'INSERT/UPDATE sur `tache`. L'ancienne heuristique
(post.created_at == tache.created_at / updated_at) n'est plus utilisée :
elle cassait dès que la tâche était modifiée après sa clôture.
"""
from .. import db
from ._like import motif_recherche

# États qu'une tâche ne peut prendre OU quitter que par le chef de projet
# titulaire, un co-chef ou l'Admin (décision du gérant, lot 10) — les
# intervenants gardent En cours / Terminée / Bloquée. Même liste que le
# trigger trg_garde_etat_tache (migration 0015), dernier rempart en base.
ETATS_RESERVES_GESTION = ("verifie", "arret", "abandonne")

MESSAGE_ETAT_RESERVE = (
    "Seuls le chef de projet, un co-chef ou un Admin peuvent passer une tâche "
    "en Vérifiée, Arrêtée ou Abandonnée, ou la faire sortir de ces états."
)


# Tâches closes (lot 11) : repliées dans le tableau de la fiche projet,
# et jamais « Rejoindre cette tâche » (bouton masqué ET refus serveur,
# add_intervenant). Même liste que les compteurs de tâches ouvertes de
# repositories/projets.py.
ETATS_CLOS = ("termine", "verifie", "arret", "abandonne")


class TacheClose(Exception):
    """« Rejoindre cette tâche » refusé : la tâche est close (ETATS_CLOS)."""


class EtatReserve(Exception):
    """Changement d'état refusé : il touche un état réservé (voir
    ETATS_RESERVES_GESTION) et l'utilisateur ne gère pas le projet."""


def est_refus_etat_reserve(exc: Exception) -> bool:
    """Vrai si `exc` est le refus du trigger trg_garde_etat_tache (migration
    0015) — normalement déjà évité par le contrôle de l'appli."""
    if isinstance(exc, EtatReserve):
        return True
    diag = getattr(exc, "diag", None)
    if getattr(diag, "constraint_name", None) == "tache_etat_reserve":
        return True
    # Sans diag (pilote minimal) : code SQLSTATE et texte du trigger.
    return getattr(exc, "pgcode", None) == "42501" and "Vérifiée, Arrêtée ou Abandonnée" in str(exc)


def list_taches_projet(projet_id: int, tache_id: int | None = None) -> list[dict]:
    """Tâches du projet, telles qu'affichées dans la fiche. `tache_id` :
    une seule (fenêtre de tâche chargée à la demande, lot 11) — même
    requête, donc même contenu que la ligne du tableau."""
    sql = """
        SELECT t.id, t.projet_id, t.titre, t.etat, t.type_deadline,
               t.date_debut, t.date_echeance, t.date_fin, t.dossier_lien,
               t.created_at, t.updated_at,
               t.bloque_motif, t.bloque_le, ub.prenom AS bloque_par_prenom, ub.nom AS bloque_par_nom,
               h.heures_cumulees, h.heures_chef, h.heures_intervenant,
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
        -- Heures de la tâche calculées pour CETTE tâche seulement (audit,
        -- lot 7) plutôt que via v_tache_heures / v_tache_heures_par_role,
        -- qui agrégeaient tout le DailyLog : même calcul, rôle évalué sur
        -- le projet de la tâche.
        LEFT JOIN LATERAL (
          SELECT SUM(de.heures) AS heures_cumulees,
                 SUM(CASE WHEN de.utilisateur_id = pr.chef_projet_id
                            OR EXISTS (SELECT 1 FROM projet_co_chef pc
                                       WHERE pc.projet_id = t.projet_id AND pc.utilisateur_id = de.utilisateur_id)
                          THEN de.heures ELSE 0 END) AS heures_chef,
                 SUM(CASE WHEN de.utilisateur_id = pr.chef_projet_id
                            OR EXISTS (SELECT 1 FROM projet_co_chef pc
                                       WHERE pc.projet_id = t.projet_id AND pc.utilisateur_id = de.utilisateur_id)
                          THEN 0 ELSE de.heures END) AS heures_intervenant
          FROM dailylog_entree de
          JOIN projet pr ON pr.id = t.projet_id
          WHERE de.tache_id = t.id
        ) h ON true
        LEFT JOIN utilisateur ub ON ub.id = t.bloque_par
        WHERE t.projet_id = %s
          AND (%s::int IS NULL OR t.id = %s)
        -- Tri (retour Fadhel, lot 8) : échéance la plus proche d'abord ; les
        -- tâches closes (terminée, vérifiée, abandonnée) en bas — une tâche
        -- « vérifiée » restait avant mêlée aux tâches en cours.
        ORDER BY (t.etat IN ('termine', 'verifie', 'abandonne')),
                 t.date_echeance NULLS LAST,
                 t.id
    """
    return db.query_all(sql, (projet_id, tache_id, tache_id))


def premiere_date(projet_id: int):
    """Plus ancienne date du projet côté tâches (début ou échéance) et
    Daily log (heures saisies), ou None — la date de début du projet ne
    peut pas la dépasser (lot 8)."""
    row = db.query_one(
        """
        SELECT LEAST(
          (SELECT LEAST(min(date_debut), min(date_echeance)) FROM tache WHERE projet_id = %(p)s),
          (SELECT min(date) FROM dailylog_entree WHERE projet_id = %(p)s)
        ) AS d
        """,
        {"p": projet_id},
    )
    return row["d"] if row else None


def get_tache(tache_id: int) -> dict | None:
    sql = """
        SELECT t.*, p.nom AS projet_nom, p.code AS projet_code, p.etat AS projet_etat,
               h.heures_cumulees, h.heures_chef, h.heures_intervenant
        FROM tache t
        JOIN projet p ON p.id = t.projet_id
        -- Heures de la tâche calculées pour CETTE tâche seulement (audit,
        -- lot 7) plutôt que via v_tache_heures / v_tache_heures_par_role,
        -- qui agrégeaient tout le DailyLog : même calcul, rôle évalué sur
        -- le projet de la tâche.
        LEFT JOIN LATERAL (
          SELECT SUM(de.heures) AS heures_cumulees,
                 SUM(CASE WHEN de.utilisateur_id = pr.chef_projet_id
                            OR EXISTS (SELECT 1 FROM projet_co_chef pc
                                       WHERE pc.projet_id = t.projet_id AND pc.utilisateur_id = de.utilisateur_id)
                          THEN de.heures ELSE 0 END) AS heures_chef,
                 SUM(CASE WHEN de.utilisateur_id = pr.chef_projet_id
                            OR EXISTS (SELECT 1 FROM projet_co_chef pc
                                       WHERE pc.projet_id = t.projet_id AND pc.utilisateur_id = de.utilisateur_id)
                          THEN 0 ELSE de.heures END) AS heures_intervenant
          FROM dailylog_entree de
          JOIN projet pr ON pr.id = t.projet_id
          WHERE de.tache_id = t.id
        ) h ON true
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
        WHERE t.etat = 'en_cours'  -- décision 5 (lot 10) : ni Vérifiée, ni Arrêt, ni Bloquée, Terminée, Abandonnée
          -- Une tâche bloquée est traitée comme terminée/abandonnée dans
          -- ce widget (retour Fadhel, 2026-09-28) : elle n'avance plus,
          -- pas la peine de continuer à encombrer "Mes tâches" avec.
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


def list_en_cours_pour_profil(user_id: int, viewer_id: int, limit: int = 8) -> list[dict]:
    """Variante de list_mes_taches() pour la page de profil d'une personne
    (Lot 5, retour Fadhel, 2026-09-28) : même sélection de tâches, mais
    restreinte à ce que LE VISITEUR (`viewer_id`) peut voir
    (v_projet_visibilite) plutôt qu'à ce que la personne consultée
    (`user_id`) peut voir elle-même — voir projets.list_ids_visibles."""
    sql = """
        SELECT t.id, t.titre, t.etat, t.date_echeance,
               p.id AS projet_id, p.nom AS projet_nom, p.code AS projet_code
        FROM tache t
        JOIN projet p ON p.id = t.projet_id
        WHERE t.etat = 'en_cours'  -- décision 5 (lot 10), même règle que Mes tâches
          AND p.etat IN ('en_cours', 'bloque')
          AND (
                t.created_by = %(uid)s
                OR EXISTS (
                     SELECT 1 FROM tache_intervenant ti
                     WHERE ti.tache_id = t.id AND ti.utilisateur_id = %(uid)s
                   )
              )
          AND EXISTS (
                SELECT 1 FROM v_projet_visibilite vv
                WHERE vv.projet_id = p.id AND vv.utilisateur_id = %(viewer_id)s
              )
        ORDER BY t.date_echeance NULLS LAST
        LIMIT %(limit)s
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"uid": user_id, "viewer_id": viewer_id, "limit": limit})
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
        WHERE t.etat = 'en_cours'  -- décision 5 (lot 10) : ni Vérifiée, ni Arrêt
          -- Une tâche bloquée n'apparaît plus dans les deadlines non plus
          -- (retour Fadhel, 2026-09-28) : traitée comme terminée/abandonnée,
          -- puisqu'elle n'avance plus tant qu'elle est bloquée.
          AND t.date_echeance IS NOT NULL
          -- PROMPT_CORRECTIONS.md P2 #23 : sans ce filtre, une tâche
          -- restée "en_cours" sur un projet déjà terminé ou abandonné
          -- continuait d'apparaître dans les échéances — le projet, lui,
          -- ne bouge plus, donc cette deadline ne sera jamais traitée.
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


def list_deadlines_tous(chef_id: int | None = None, equipe_code: str | None = None,
                        sans_echeance: bool = False, limit: int = 500) -> list[dict]:
    """Vue Admin des Deadlines (lot 12) : les tâches en cours de TOUS les
    projets ouverts (en cours ou bloqués), avec échéance (triées par date)
    ou sans (`sans_echeance`, triées par projet) — mêmes règles que
    list_deadlines (décision 5 du lot 10), sans le filtre « mes projets ».
    Filtres facultatifs : chef de projet titulaire, équipe du projet."""
    sql = f"""
        SELECT t.id, t.titre, t.etat, t.date_echeance, t.type_deadline,
               p.id AS projet_id, p.code AS projet_code, p.nom AS projet_nom, p.equipe_code,
               u.id AS chef_id, u.prenom AS chef_prenom, u.nom AS chef_nom
        FROM tache t
        JOIN projet p ON p.id = t.projet_id
        JOIN utilisateur u ON u.id = p.chef_projet_id
        WHERE t.etat = 'en_cours'
          AND p.etat IN ('en_cours', 'bloque')
          AND t.date_echeance IS {'NULL' if sans_echeance else 'NOT NULL'}
          AND (%(chef)s::bigint IS NULL OR p.chef_projet_id = %(chef)s::bigint)
          AND (%(equipe)s::text IS NULL OR p.equipe_code = %(equipe)s::text)
        ORDER BY {'p.code, t.titre, t.id' if sans_echeance else 't.date_echeance, p.code, t.id'}
        LIMIT %(limit)s
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"chef": chef_id, "equipe": equipe_code, "limit": limit})
        return [dict(r) for r in cur.fetchall()]


def list_bloquees(user_id: int | None = None, *, tous: bool = False, chef_id: int | None = None,
                  equipe_code: str | None = None, limit: int = 50) -> list[dict]:
    """Tâches bloquées des projets ouverts (lot 14, revue produit P0-1 :
    section « Bloquées (n) » de l'accueil et des Deadlines), le blocage le
    plus ancien d'abord, avec son motif et son auteur. Sans `tous` : celles
    des projets où `user_id` est chef, co-chef, intervenant du projet ou de
    la tâche, ou qu'il a créées (portée de list_deadlines et de Mes tâches) ;
    avec `tous` (Admin) : tout le bureau, filtres facultatifs chef de projet
    titulaire et équipe du projet (vue « Tous les projets » des Deadlines)."""
    return db.query_all(
        """
        SELECT t.id, t.titre, t.date_echeance, t.type_deadline, t.bloque_motif, t.bloque_le,
               ub.prenom AS bloque_par_prenom, ub.nom AS bloque_par_nom,
               p.id AS projet_id, p.code AS projet_code, p.nom AS projet_nom,
               u.prenom AS chef_prenom, u.nom AS chef_nom
        FROM tache t
        JOIN projet p ON p.id = t.projet_id
        JOIN utilisateur u ON u.id = p.chef_projet_id
        LEFT JOIN utilisateur ub ON ub.id = t.bloque_par
        WHERE t.etat = 'bloque'
          AND p.etat IN ('en_cours', 'bloque')
          AND (%(tous)s OR p.chef_projet_id = %(uid)s OR t.created_by = %(uid)s
               OR EXISTS (SELECT 1 FROM projet_co_chef cc WHERE cc.projet_id = p.id AND cc.utilisateur_id = %(uid)s)
               OR EXISTS (SELECT 1 FROM projet_intervenant pi WHERE pi.projet_id = p.id AND pi.utilisateur_id = %(uid)s)
               OR EXISTS (SELECT 1 FROM tache_intervenant ti WHERE ti.tache_id = t.id AND ti.utilisateur_id = %(uid)s))
          AND (%(chef)s::bigint IS NULL OR p.chef_projet_id = %(chef)s::bigint)
          AND (%(equipe)s::text IS NULL OR p.equipe_code = %(equipe)s::text)
        ORDER BY t.bloque_le NULLS FIRST, p.code, t.id
        LIMIT %(limit)s
        """,
        {"uid": user_id, "tous": tous, "chef": chef_id, "equipe": equipe_code, "limit": limit},
    )


def search(user_id: int, q: str, limit: int = 6) -> list[dict]:
    """Recherche globale de la topbar (lot 11) : tâches dont le titre
    contient `q`, sans accents ni casse, sur les seuls projets visibles par
    `user_id` (v_projet_visibilite) — avec leur projet, pour le lien. Les
    tâches ouvertes d'abord, puis les plus récemment modifiées."""
    return db.query_all(
        """
        SELECT t.id, t.titre, t.etat, p.id AS projet_id, p.code AS projet_code, p.nom AS projet_nom
        FROM tache t
        JOIN projet p ON p.id = t.projet_id
        WHERE fn_recherche(t.titre) LIKE fn_recherche(%(q)s)
          AND EXISTS (SELECT 1 FROM v_projet_visibilite vv
                      WHERE vv.projet_id = p.id AND vv.utilisateur_id = %(uid)s)
        ORDER BY (t.etat IN ('en_cours', 'bloque')) DESC, t.updated_at DESC, t.id DESC
        LIMIT %(limit)s
        """,
        {"q": motif_recherche(q), "uid": user_id, "limit": limit},
    )


def _verrouiller_projet(cur, projet_id: int) -> None:
    """À appeler EN PREMIER dans toute transaction qui peut changer l'état
    d'une tâche (audit données lot 10, I2). Sans ce verrou, deux tâches
    bloquées clôturées en même temps voient chacune l'autre encore bloquée
    (instantanés concurrents) : aucune ne débloque le projet, qui reste
    « Bloqué » sans tâche bloquée. Pris au début et en NO KEY UPDATE : pas
    d'interblocage avec les verrous FOR KEY SHARE que posent les clés
    étrangères des posts insérés dans la même transaction."""
    cur.execute("SELECT 1 FROM projet WHERE id = %s FOR NO KEY UPDATE", (projet_id,))


# « Annuler » d'un toast (lot 13, contre-expertise UX N9) : rejoué dans ce
# délai, le retour à l'état d'avant retire le post automatique de l'aller
# (s'il est resté sans réaction, commentaire, réponse ni notification) au
# lieu d'en ajouter un second ; la suppression reste au journal d'audit.
DELAI_ANNULATION_SECONDES = 60

# Contenu quelconque (_retirer_post_annule) : le post de clôture d'une tâche,
# avec ou sans message (lot 14, P0-2).
TOUT_CONTENU = object()


def _retirer_post_annule(cur, projet_id: int, auteur_id: int, evenement: str, contenu,
                         tache_id: int | None = None) -> bool:
    """Supprime le dernier post automatique `evenement` de l'auteur (sur la
    tâche, ou sur le projet sans tâche), récent et intact, de contenu
    `contenu` (TOUT_CONTENU : quel qu'il soit). Vrai si un post a été retiré."""
    tout = contenu is TOUT_CONTENU
    cur.execute(
        """
        DELETE FROM post p
        WHERE p.id = (
                SELECT id FROM post
                WHERE projet_id = %(p)s AND tache_id IS NOT DISTINCT FROM %(t)s AND evenement = %(e)s
                ORDER BY created_at DESC, id DESC LIMIT 1)
          AND p.auteur_id = %(a)s
          AND (%(tout)s OR p.contenu IS NOT DISTINCT FROM %(c)s)
          AND p.created_at > now() - make_interval(secs => %(d)s)
          AND NOT EXISTS (SELECT 1 FROM post_commentaire c WHERE c.post_id = p.id)
          AND NOT EXISTS (SELECT 1 FROM post_reaction r WHERE r.post_id = p.id)
          AND NOT EXISTS (SELECT 1 FROM post_piece_jointe j WHERE j.post_id = p.id)
          AND NOT EXISTS (SELECT 1 FROM notification n WHERE n.post_id = p.id)
          AND NOT EXISTS (SELECT 1 FROM post r WHERE r.parent_post_id = p.id)
        RETURNING p.id
        """,
        {"p": projet_id, "t": tache_id, "e": evenement, "a": auteur_id, "c": None if tout else contenu,
         "tout": tout, "d": DELAI_ANNULATION_SECONDES},
    )
    return cur.fetchone() is not None


def recalculer_etat_projet(cur, projet_id: int, current_user_id: int | None,
                           annulation: bool = False) -> tuple[str, str] | None:
    """État d'un projet OUVERT recalculé d'après ses tâches (décision 1 du
    lot 13, règle du lot 11) : Bloqué si et seulement si une de ses tâches
    est bloquée, En cours sinon ; un projet Terminé ou Abandonné ne bouge
    pas. Fonction unique, appelée dans la transaction de TOUTE écriture de
    tâche ou de projet (création, changement d'état, clôture, informations
    du projet), sous le verrou du projet (_verrouiller_projet ou FOR
    UPDATE) — même règle que fn_etat_projet_recalcule (migration 0019), qui
    sert ici. Un changement donne le post automatique habituel « En cours →
    Bloqué » au nom de l'acteur. Renvoie (avant, après), None sans
    changement.

    Pourquoi dans l'appli plutôt qu'un trigger : le post automatique porte
    l'auteur de l'action (un trigger ne le connaît pas toujours : scripts,
    rechargement Chronos), le verrou du projet est déjà pris par chaque
    écriture, et le rechargement Chronos applique déjà la même règle sans
    déclencher des milliers de recalculs ligne à ligne."""
    from ..utils import projet_etat_style

    cur.execute(
        """
        UPDATE projet p SET etat = fn_etat_projet_recalcule(p.etat, p.id)
        FROM (SELECT etat AS ancien FROM projet WHERE id = %(p)s) a
        WHERE p.id = %(p)s AND p.etat <> fn_etat_projet_recalcule(p.etat, p.id)
        RETURNING a.ancien, p.etat
        """,
        {"p": projet_id},
    )
    row = cur.fetchone()
    if row is None:
        return None
    avant, apres = str(row["ancien"]), str(row["etat"])
    if current_user_id is not None and not (annulation and _retirer_post_annule(
            cur, projet_id, current_user_id, "etat_projet",
            f"{projet_etat_style(apres)['label']} → {projet_etat_style(avant)['label']}")):
        cur.execute(
            """
            INSERT INTO post (projet_id, auteur_id, type_code, contenu, evenement)
            VALUES (%s, %s, 'information', %s, 'etat_projet')
            """,
            (projet_id, current_user_id,
             f"{projet_etat_style(avant)['label']} → {projet_etat_style(apres)['label']}"),
        )
    return avant, apres


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
        _verrouiller_projet(cur, projet_id)
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
        # Lot 13 : l'état du projet suit TOUTES ses tâches (une nouvelle tâche
        # ne débloque plus un projet qui garde une tâche bloquée).
        recalculer_etat_projet(cur, projet_id, current_user_id)
        return tache_id


def user_est_intervenant(tache_id: int, user_id: int) -> bool:
    """Vrai si `user_id` est affecté comme intervenant sur cette tâche —
    en plus du chef de projet et des co-chefs (voir projets.user_can_manage),
    un intervenant de la tâche peut changer son état ou la clôturer
    (PROMPT_CORRECTIONS.md P0 #2). Jamais un Client ni le RH (lot 7, même
    raison que projets.user_can_manage)."""
    sql = """
        SELECT 1 FROM tache_intervenant
        WHERE tache_id = %(tid)s AND utilisateur_id = %(uid)s
          AND NOT EXISTS (SELECT 1 FROM utilisateur ux WHERE ux.id = %(uid)s AND ux.role IN ('client', 'rh'))
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"tid": tache_id, "uid": user_id})
        return cur.fetchone() is not None


def add_intervenant(tache_id: int, projet_id: int, utilisateur_id: int, current_user_id: int) -> bool:
    """Ajoute `utilisateur_id` comme intervenant de la tâche `tache_id` —
    bouton « rejoindre cette tâche » (retour Fadhel, 2026-09-28), ajout
    immédiat sans validation, même principe que projets.add_intervenant.

    `projet_id` au WHERE : même garde-fou que set_etat/close_tache
    (PROMPT_CORRECTIONS.md P0 #2) — la tâche doit bien appartenir à ce
    projet. Retourne False (au lieu de planter) si la tâche n'existe pas
    ou n'appartient pas à ce projet.

    Lot 11 : lève TacheClose si la tâche est close — le bouton n'est plus
    proposé, mais une requête forgée (ou une page restée ouverte) passait.
    FOR SHARE : un changement d'état concurrent attend la fin de l'ajout."""
    with db.get_cursor(user_id=current_user_id) as cur:
        cur.execute("SELECT etat FROM tache WHERE id = %s AND projet_id = %s FOR SHARE", (tache_id, projet_id))
        ligne = cur.fetchone()
        if ligne is None:
            return False
        if ligne["etat"] in ETATS_CLOS:
            raise TacheClose()
        cur.execute(
            """
            INSERT INTO tache_intervenant (tache_id, utilisateur_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (tache_id, utilisateur_id),
        )
        return True


class MotifBlocageRequis(Exception):
    """Passage en « Bloquée » sans motif (lot 14, revue produit P0-1)."""


MOTIF_BLOCAGE_MAX = 500


class TacheModifiee(Exception):
    """« Annuler » périmé (recette du lot 14, n° 5) : la tâche n'est plus
    dans l'état que le geste annulé avait produit (quelqu'un l'a changée
    entre-temps) ; rien n'est défait."""


def normaliser_motif(texte: str | None) -> str | None:
    """Motif d'un blocage tel qu'il est gardé (recette du lot 14, n° 3) :
    caractères de format retirés (largeur nulle U+200B, U+FEFF, U+2060…),
    caractères de contrôle et blancs (espaces insécables compris) ramenés à
    une espace ; None s'il ne reste ni lettre, ni chiffre, ni ponctuation,
    ni symbole (motif « invisible »)."""
    import unicodedata

    morceaux = []
    for c in texte or "":
        categorie = unicodedata.category(c)
        if categorie == "Cf":
            continue
        morceaux.append(" " if categorie.startswith(("C", "Z")) or c.isspace() else c)
    propre = " ".join("".join(morceaux).split())
    if not any(unicodedata.category(c)[0] in "LNPS" for c in propre):
        return None
    return propre


def version(tache_id: int) -> str | None:
    """Version d'une tâche (son updated_at, exact) : jointe à l'action
    « Annuler » pour reconnaître l'état produit par le geste."""
    ligne = db.query_one("SELECT extract(epoch FROM updated_at)::text AS v FROM tache WHERE id = %s", (tache_id,))
    return ligne["v"] if ligne else None


def set_etat(tache_id: int, projet_id: int, etat: str, current_user_id: int, *, peut_gerer: bool = False,
             annulation: bool = False, motif: str | None = None, version_attendue: str | None = None) -> bool:
    """Changement d'état simple (En cours / Bloqué / Vérifié / Arrêt /
    Abandonné) — avec un post automatique "ancien état → nouvel état"
    depuis le 2026-09-29 (P1) ; la clôture ("Terminé", voir close_tache)
    garde son propre post, avec le tag choisi.

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
    à tort dès qu'une tâche terminée était vérifiée).

    `peut_gerer` (décision du gérant, lot 10) : vrai pour le chef titulaire,
    un co-chef ou l'Admin (projets.user_can_manage). Sans lui, passer la
    tâche dans un état de ETATS_RESERVES_GESTION ou l'en faire sortir lève
    EtatReserve — contrôlé sur l'état LU SOUS VERROU, pas sur celui affiché
    au moment du clic. Faux par défaut : un appelant qui oublie de le
    préciser n'obtient que les droits d'un intervenant.

    `annulation` (« Annuler » d'un toast, contre-expertise UX N9) : le post
    automatique de l'aller (changement d'état, blocage, levée du blocage ou
    clôture) est retiré au lieu d'ajouter celui du retour
    (_retirer_post_annule).

    `motif` (lot 14, revue produit P0-1) : « Qu'est-ce qui bloque ? »,
    obligatoire pour passer en Bloquée (MotifBlocageRequis), gardé sur la
    tâche (bloque_motif, bloque_le, bloque_par) et porté par le post
    automatique 'blocage_tache' (« a signalé un blocage ») ; la sortie du
    blocage donne 'deblocage_tache' (« a levé le blocage »). En annulation
    (retour au blocage d'avant), un motif absent garde celui de la tâche,
    et le même motif garde la date et l'auteur du blocage d'origine. Une
    tâche déjà bloquée ne change que de motif.

    `version_attendue` (« Annuler », recette du lot 14 n° 5) : version de
    la tâche (voir `version`) produite par le geste annulé ; si la tâche a
    changé depuis, TacheModifiee est levée et rien n'est écrit."""
    from ..utils import tache_etat_style

    motif = normaliser_motif(motif)
    with db.get_cursor(user_id=current_user_id) as cur:
        _verrouiller_projet(cur, projet_id)
        cur.execute(
            """SELECT etat, bloque_motif, extract(epoch FROM updated_at)::text AS version
               FROM tache WHERE id = %s AND projet_id = %s FOR UPDATE""",
            (tache_id, projet_id),
        )
        avant = cur.fetchone()
        if avant is None:
            return False
        if version_attendue is not None and avant["version"] != version_attendue:
            raise TacheModifiee()
        if not peut_gerer and (etat in ETATS_RESERVES_GESTION or avant["etat"] in ETATS_RESERVES_GESTION):
            raise EtatReserve(MESSAGE_ETAT_RESERVE)
        if etat == "bloque":
            if motif is None and not annulation and avant["etat"] != "bloque":
                raise MotifBlocageRequis()
            motif = motif or avant.get("bloque_motif")
        cur.execute(
            """
            UPDATE tache
            SET etat = %(etat)s,
                date_fin = CASE WHEN %(etat)s IN ('en_cours', 'bloque', 'arret') THEN NULL ELSE date_fin END,
                bloque_le = CASE WHEN %(etat)s <> 'bloque' THEN bloque_le
                                 WHEN etat = 'bloque' AND bloque_le IS NOT NULL THEN bloque_le
                                 WHEN %(annulation)s AND bloque_motif IS NOT DISTINCT FROM %(motif)s
                                      AND bloque_le IS NOT NULL THEN bloque_le
                                 ELSE now() END,
                bloque_par = CASE WHEN %(etat)s <> 'bloque' THEN bloque_par
                                  WHEN (etat = 'bloque' OR %(annulation)s) AND bloque_motif IS NOT DISTINCT FROM %(motif)s
                                       AND bloque_par IS NOT NULL THEN bloque_par
                                  ELSE %(uid)s END,
                bloque_motif = CASE WHEN %(etat)s = 'bloque' THEN %(motif)s ELSE bloque_motif END
            WHERE id = %(t)s AND projet_id = %(p)s
            """,
            {"etat": etat, "annulation": annulation, "motif": motif, "uid": current_user_id,
             "t": tache_id, "p": projet_id},
        )
        if avant["etat"] != etat:
            libelle = lambda e: tache_etat_style(e)["label"]  # noqa: E731
            # Post de l'aller à retirer (« Annuler »), selon le geste annulé.
            if avant["etat"] == "termine":
                aller = ("cloture_tache", TOUT_CONTENU)
            elif avant["etat"] == "bloque":
                aller = ("blocage_tache", avant.get("bloque_motif"))
            elif etat == "bloque":
                aller = ("deblocage_tache", f"{libelle('bloque')} → {libelle(avant['etat'])}")
            else:
                aller = ("etat_tache", f"{libelle(etat)} → {libelle(avant['etat'])}")
            retire = annulation and _retirer_post_annule(cur, projet_id, current_user_id, aller[0], aller[1], tache_id)
            if not retire:
                if etat == "bloque":
                    evenement, contenu = "blocage_tache", motif
                elif avant["etat"] == "bloque":
                    evenement, contenu = "deblocage_tache", f"{libelle('bloque')} → {libelle(etat)}"
                else:
                    evenement, contenu = "etat_tache", f"{libelle(avant['etat'])} → {libelle(etat)}"
                cur.execute(
                    f"""
                    INSERT INTO post (projet_id, tache_id, auteur_id, type_code, contenu, evenement)
                    VALUES (%s, %s, %s, 'information', %s, '{evenement}')
                    """,
                    (projet_id, tache_id, current_user_id, contenu),
                )
            recalculer_etat_projet(cur, projet_id, current_user_id, annulation=annulation)
        return True


def set_titre(tache_id: int, projet_id: int, titre: str, current_user_id: int) -> bool:
    """Modification du titre d'une tâche (retour Fadhel, 2026-09-29 : clic
    sur la ligne de la tâche → fenêtre flottante) ; le changement apparaît
    dans le fil ("ancien → nouveau", evenement='titre_tache'), dans la même
    transaction. Même garde-fou `projet_id` que set_etat."""
    with db.get_cursor(user_id=current_user_id) as cur:
        cur.execute(
            "SELECT titre FROM tache WHERE id = %s AND projet_id = %s FOR UPDATE",
            (tache_id, projet_id),
        )
        avant = cur.fetchone()
        if avant is None:
            return False
        if avant["titre"] == titre:
            return True
        cur.execute("UPDATE tache SET titre = %s WHERE id = %s", (titre, tache_id))
        cur.execute(
            """
            INSERT INTO post (projet_id, tache_id, auteur_id, type_code, contenu, evenement)
            VALUES (%s, %s, %s, 'information', %s, 'titre_tache')
            """,
            (projet_id, tache_id, current_user_id, f"{avant['titre']} → {titre}"),
        )
        return True


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


# Texte du post de clôture laissé sans message (lot 14, revue produit P0-2 :
# plus de post « Envoi » vide ; le titre de la tâche est affiché au-dessus).
TEXTE_CLOTURE_SANS_MESSAGE = "Tâche terminée."


def close_tache(
    tache_id: int, projet_id: int, current_user_id: int, type_code: str, contenu: str | None = None,
    *, peut_gerer: bool = False,
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
    flash plutôt qu'en erreur 500.

    `peut_gerer` : comme pour set_etat, clôturer une tâche Arrêtée ou
    Abandonnée la fait sortir d'un état réservé — EtatReserve sans lui
    (décision du gérant, lot 10)."""
    reserves_hors_cloture = tuple(e for e in ETATS_RESERVES_GESTION if e not in ("termine", "verifie"))
    with db.get_cursor(user_id=current_user_id) as cur:
        _verrouiller_projet(cur, projet_id)
        # date_fin (lot 13, décision 5 et audit temps T-I2 / T-M3) : la date du
        # jour au fuseau de l'acteur, date simulée comprise mais jamais après
        # la vraie date (fn_date_ecriture, migration 0019).
        cur.execute(
            """
            WITH avant AS (SELECT etat FROM tache WHERE id = %s)
            UPDATE tache SET etat = 'termine',
                             date_fin = fn_date_ecriture((SELECT fuseau FROM utilisateur WHERE id = %s))
            WHERE id = %s AND projet_id = %s AND etat NOT IN ('termine', 'verifie')
              AND (%s OR etat::text <> ALL (%s))
            RETURNING id, projet_id, titre, (SELECT etat FROM avant) AS ancien_etat
            """,
            (tache_id, current_user_id, tache_id, projet_id, peut_gerer, list(reserves_hors_cloture)),
        )
        row = cur.fetchone()
        if row is None:
            if not peut_gerer:
                # Rien de clôturé : si c'est à cause d'un état réservé, le dire.
                cur.execute("SELECT etat FROM tache WHERE id = %s AND projet_id = %s", (tache_id, projet_id))
                etat = cur.fetchone()
                if etat is not None and etat["etat"] in reserves_hors_cloture:
                    raise EtatReserve(MESSAGE_ETAT_RESERVE)
            return None

        cur.execute(
            """
            INSERT INTO post (projet_id, tache_id, auteur_id, type_code, contenu, evenement)
            VALUES (%s, %s, %s, %s, %s, 'cloture_tache')
            RETURNING id
            """,
            (row["projet_id"], tache_id, current_user_id, type_code,
             (contenu or "").strip() or TEXTE_CLOTURE_SANS_MESSAGE),
        )
        post_id = cur.fetchone()["id"]
        recalculer_etat_projet(cur, row["projet_id"], current_user_id)
        return post_id


# ---------------------------------------------------------------------
# Intervenants et échéance d'une tâche existante (lot 13, décision 4)
# ---------------------------------------------------------------------
def _noms(cur, ids: list[int]) -> dict:
    cur.execute("SELECT id, prenom, nom, role FROM utilisateur WHERE id = ANY(%s)", (list(ids),))
    return {r["id"]: dict(r) for r in cur.fetchall()}


def _nom_complet(u: dict | None) -> str:
    u = u or {}
    return f"{u.get('prenom') or ''} {u.get('nom') or ''}".strip()


def _tache_ouverte_sous_verrou(cur, tache_id: int, projet_id: int) -> dict | None:
    """Projet puis tâche verrouillés (même ordre que set_etat) ; None si la
    tâche n'est pas de ce projet ; TacheClose si elle est close."""
    _verrouiller_projet(cur, projet_id)
    cur.execute(
        "SELECT id, titre, etat, date_debut, date_echeance, type_deadline FROM tache "
        "WHERE id = %s AND projet_id = %s FOR UPDATE",
        (tache_id, projet_id),
    )
    tache = cur.fetchone()
    if tache is not None and tache["etat"] in ETATS_CLOS:
        raise TacheClose()
    return tache


def ajouter_intervenants(tache_id: int, projet_id: int, utilisateur_ids: list[int], current_user_id: int) -> dict | None:
    """Ajoute des intervenants à une tâche OUVERTE (le chef, un co-chef ou
    l'Admin : contrôlé par la route) — post automatique 'intervenant_tache'
    dans la même transaction. Un chef de projet ajouté devient co-chef du
    projet (trigger 0013) : il est signalé dans `co_chefs`. Renvoie
    {post_id, titre, ajoutes: [ids], co_chefs: [ids]} (ajoutes vide : tous
    déjà affectés, pas de post), None si la tâche n'est pas de ce projet."""
    with db.get_cursor(user_id=current_user_id) as cur:
        tache = _tache_ouverte_sous_verrou(cur, tache_id, projet_id)
        if tache is None:
            return None
        cur.execute("SELECT utilisateur_id FROM projet_co_chef WHERE projet_id = %s", (projet_id,))
        co_chefs_avant = {r["utilisateur_id"] for r in cur.fetchall()}
        ajoutes = []
        for uid in dict.fromkeys(utilisateur_ids):
            cur.execute(
                "INSERT INTO tache_intervenant (tache_id, utilisateur_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (tache_id, uid),
            )
            if cur.rowcount == 1:
                ajoutes.append(uid)
        if not ajoutes:
            return {"post_id": None, "titre": tache["titre"], "ajoutes": [], "co_chefs": []}
        cur.execute("SELECT utilisateur_id FROM projet_co_chef WHERE projet_id = %s", (projet_id,))
        co_chefs = [uid for uid in ajoutes if uid not in co_chefs_avant
                    and uid in {r["utilisateur_id"] for r in cur.fetchall()}]
        gens = _noms(cur, ajoutes + [current_user_id])
        noms = ", ".join(_nom_complet(gens.get(uid)) for uid in ajoutes)
        cur.execute(
            """
            INSERT INTO post (projet_id, tache_id, auteur_id, type_code, contenu, evenement)
            VALUES (%s, %s, %s, 'information', %s, 'intervenant_tache')
            RETURNING id
            """,
            (projet_id, tache_id, current_user_id, f"{_nom_complet(gens.get(current_user_id))} a ajouté {noms}."),
        )
        return {"post_id": cur.fetchone()["id"], "titre": tache["titre"], "ajoutes": ajoutes, "co_chefs": co_chefs}


def retirer_intervenant(tache_id: int, projet_id: int, utilisateur_id: int, current_user_id: int) -> dict | None:
    """Retire un intervenant d'une tâche OUVERTE, post automatique
    'intervenant_tache' dans la même transaction (ses heures restent).
    Renvoie {post_id, titre, personne} ; {} s'il n'était pas affecté ; None
    si la tâche n'est pas de ce projet."""
    with db.get_cursor(user_id=current_user_id) as cur:
        tache = _tache_ouverte_sous_verrou(cur, tache_id, projet_id)
        if tache is None:
            return None
        cur.execute("DELETE FROM tache_intervenant WHERE tache_id = %s AND utilisateur_id = %s",
                    (tache_id, utilisateur_id))
        if cur.rowcount == 0:
            return {}
        gens = _noms(cur, [utilisateur_id, current_user_id])
        cur.execute(
            """
            INSERT INTO post (projet_id, tache_id, auteur_id, type_code, contenu, evenement)
            VALUES (%s, %s, %s, 'information', %s, 'intervenant_tache')
            RETURNING id
            """,
            (projet_id, tache_id, current_user_id,
             f"{_nom_complet(gens.get(current_user_id))} a retiré {_nom_complet(gens.get(utilisateur_id))}."),
        )
        return {"post_id": cur.fetchone()["id"], "titre": tache["titre"], "personne": gens.get(utilisateur_id)}


TYPES_DEADLINE_LIBELLES = {"rendu_client": "rendu client", "interne": "interne"}


def set_echeance(tache_id: int, projet_id: int, date_echeance, type_deadline: str, current_user_id: int) -> dict | None:
    """Échéance et type d'échéance d'une tâche OUVERTE (« modifiable » selon
    la spécification) — post automatique 'echeance_tache' « 14 oct. 2026
    (rendu client) → 21 oct. 2026 (interne) » dans la même transaction.
    `date_echeance` None : sans échéance. Renvoie {post_id, titre, avant,
    apres} ({} si rien ne change), None si la tâche n'est pas de ce projet.
    Les dates incohérentes (échéance avant le début de la tâche) sont
    refusées par la route, puis par le trigger trg_check_dates_tache_maj."""
    from ..utils import date_courte

    def libelle(d, t):
        return f"{date_courte(d, True) if d else 'sans échéance'} ({TYPES_DEADLINE_LIBELLES.get(t, t)})"

    with db.get_cursor(user_id=current_user_id) as cur:
        tache = _tache_ouverte_sous_verrou(cur, tache_id, projet_id)
        if tache is None:
            return None
        if tache["date_echeance"] == date_echeance and tache["type_deadline"] == type_deadline:
            return {}
        cur.execute("UPDATE tache SET date_echeance = %s, type_deadline = %s WHERE id = %s",
                    (date_echeance, type_deadline, tache_id))
        avant = libelle(tache["date_echeance"], tache["type_deadline"])
        apres = libelle(date_echeance, type_deadline)
        cur.execute(
            """
            INSERT INTO post (projet_id, tache_id, auteur_id, type_code, contenu, evenement)
            VALUES (%s, %s, %s, 'information', %s, 'echeance_tache')
            RETURNING id
            """,
            (projet_id, tache_id, current_user_id, f"Échéance : {avant} → {apres}"),
        )
        return {"post_id": cur.fetchone()["id"], "titre": tache["titre"], "avant": avant, "apres": apres,
                "date_debut": tache["date_debut"]}

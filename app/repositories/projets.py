"""Requêtes SQL liées aux projets.

Toutes les requêtes ici sont des SELECT (lecture) sauf create_projet, donc
la plupart n'ont pas besoin de user_id (pas de trace à écrire). Seule
create_projet passe user_id pour alimenter created_by/updated_by + audit_log.
"""
from .. import db
from ._like import motif_recherche


def list_mes_projets(user_id: int) -> list[dict]:
    """Projets où l'utilisateur est chef de projet, co-chef ou intervenant
    (carte "Mes projets" de l'accueil) — avec son rôle sur chacun.
    """
    sql = """
        SELECT p.id, p.code, p.nom, p.phase, p.etat,
               CASE
                 WHEN p.chef_projet_id = %(user_id)s THEN 'chef_de_projet'
                 WHEN cc.utilisateur_id IS NOT NULL THEN 'co_chef'
                 ELSE 'intervenant'
               END AS mon_role
        FROM projet p
        LEFT JOIN projet_co_chef cc
               ON cc.projet_id = p.id AND cc.utilisateur_id = %(user_id)s
        LEFT JOIN projet_intervenant pi
               ON pi.projet_id = p.id AND pi.utilisateur_id = %(user_id)s
        WHERE p.chef_projet_id = %(user_id)s
           OR cc.utilisateur_id IS NOT NULL
           OR pi.utilisateur_id IS NOT NULL
        ORDER BY (p.etat = 'bloque') DESC, p.updated_at DESC
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"user_id": user_id})
        return [dict(r) for r in cur.fetchall()]


def list_mes_projets_recents(user_id: int, limit: int = 5) -> list[dict]:
    """5 projets parmi "mes projets" (même périmètre que list_mes_projets)
    triés par ma dernière action dessus — pas l'activité de tout le monde,
    la MIENNE (retour Fadhel, 2026-09-28) : création du projet, création/
    modification d'une tâche par moi, poste/commentaire de moi, ou saisie
    DailyLog de moi sur ce projet. Les projets terminés sont exclus (sinon
    "liste à n'en pas finir" — ceux bloqués/à l'arrêt restent, eux, un
    signal d'activité pertinent)."""
    sql = """
        SELECT p.id, p.code, p.nom, p.phase, p.etat,
               CASE
                 WHEN p.chef_projet_id = %(user_id)s THEN 'chef_de_projet'
                 WHEN cc.utilisateur_id IS NOT NULL THEN 'co_chef'
                 ELSE 'intervenant'
               END AS mon_role,
               GREATEST(
                 CASE WHEN p.created_by = %(user_id)s THEN p.created_at END,
                 (SELECT MAX(t.updated_at) FROM tache t
                   WHERE t.projet_id = p.id
                     AND (t.created_by = %(user_id)s OR t.updated_by = %(user_id)s)),
                 (SELECT MAX(po.created_at) FROM post po
                   WHERE po.projet_id = p.id AND po.auteur_id = %(user_id)s),
                 -- Un commentaire compte aussi comme une action (retour
                 -- Fadhel, 2026-09-29, L1 — annoncé mais oublié jusqu'ici).
                 (SELECT MAX(COALESCE(co.modifie_le, co.created_at)) FROM post_commentaire co
                   JOIN post pc ON pc.id = co.post_id
                   WHERE pc.projet_id = p.id AND co.auteur_id = %(user_id)s),
                 (SELECT MAX(de.created_at) FROM dailylog_entree de
                   WHERE de.projet_id = p.id AND de.utilisateur_id = %(user_id)s)
               ) AS ma_derniere_action
        FROM projet p
        LEFT JOIN projet_co_chef cc
               ON cc.projet_id = p.id AND cc.utilisateur_id = %(user_id)s
        LEFT JOIN projet_intervenant pi
               ON pi.projet_id = p.id AND pi.utilisateur_id = %(user_id)s
        WHERE (
                p.chef_projet_id = %(user_id)s
                OR cc.utilisateur_id IS NOT NULL
                OR pi.utilisateur_id IS NOT NULL
              )
          AND p.etat <> 'termine'
        ORDER BY ma_derniere_action DESC NULLS LAST
        LIMIT %(limit)s
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"user_id": user_id, "limit": limit})
        return [dict(r) for r in cur.fetchall()]


# Filtres de "Tous les projets" : partagés par la liste (paginée), son
# compteur et l'export Excel (lot 11 : la liste était tronquée à 200 lignes
# sans le dire, alors que le compteur affichait « 200 projets »).
_FILTRES_LISTE = """
        WHERE (%(etats)s IS NULL OR p.etat::text = ANY(%(etats)s))
          AND (%(phases)s IS NULL OR p.phase::text = ANY(%(phases)s))
          AND (%(chef_ids)s IS NULL OR p.chef_projet_id = ANY(%(chef_ids)s))
          -- Filtre lots à TROIS états par lot (retour Fadhel, 2026-10-01),
          -- deux listes indépendantes :
          --   lot_contient : le projet DOIT avoir chacun de ces lots (parmi
          --                  d'autres éventuels) — "contient GO".
          --   lot_egal     : l'ENSEMBLE des lots du projet est exactement
          --                  cette liste — "= GO" (uniquement ce lot).
          -- Les deux peuvent être combinés (ET) ; une combinaison
          -- contradictoire (= GO + contient CM) ne renvoie rien, ce qui est
          -- le comportement attendu.
          --
          -- `::text[]` sur un paramètre NULL lève l'ambiguïté de type AVANT
          -- toute subscription/array_length (l'erreur serait levée à
          -- l'analyse de la requête, pas à l'exécution).
          AND (
                %(lots_contient)s::text[] IS NULL
                OR (SELECT count(DISTINCT pl.lot_code) FROM projet_lot pl
                     WHERE pl.projet_id = p.id
                       AND pl.lot_code = ANY(%(lots_contient)s::text[]))
                    = array_length(%(lots_contient)s::text[], 1)
              )
          AND (
                %(lots_egal)s::text[] IS NULL
                OR (
                     (SELECT count(DISTINCT pl.lot_code) FROM projet_lot pl
                        WHERE pl.projet_id = p.id)
                       = array_length(%(lots_egal)s::text[], 1)
                     AND NOT EXISTS (
                           SELECT 1 FROM projet_lot pl
                           WHERE pl.projet_id = p.id
                             AND pl.lot_code <> ALL(%(lots_egal)s::text[])
                         )
                   )
              )
          -- Recherche sans accents ni casse (lot 11, fn_recherche : migration 0016).
          AND (%(q)s IS NULL OR fn_recherche(p.code || '_' || p.nom) LIKE fn_recherche(%(q)s))
          AND EXISTS (
                SELECT 1 FROM v_projet_visibilite vv
                WHERE vv.projet_id = p.id AND vv.utilisateur_id = %(user_id)s
              )
"""


def _params_liste(user_id, etats, phases, chef_ids, lots_contient, lots_egal, q) -> dict:
    return {
        "etats": etats or None, "phases": phases or None,
        "chef_ids": chef_ids or None,
        "lots_contient": lots_contient or None, "lots_egal": lots_egal or None,
        "q": motif_recherche(q) if q else None,
        "user_id": user_id,
    }


def list_projets(
    user_id: int, limit: int | None = 200,
    etats: list[str] | None = None, phases: list[str] | None = None,
    chef_ids: list[int] | None = None,
    lots_contient: list[str] | None = None, lots_egal: list[str] | None = None,
    q: str | None = None, offset: int = 0,
) -> list[dict]:
    """Projets visibles par `user_id` (vue "Tous les projets") avec le nom
    du chef de projet, les lots concaténés et la prochaine échéance —
    filtrable par états/phases/chefs de projet/lots (multi-sélection,
    sélecteur à puces — voir projets_liste.html) et par recherche libre sur
    "Code_nom". Une page de `limit` lignes à partir de `offset` (lot 11 :
    pagination, total donné par compter_projets) ; `limit=None` : tout
    (export Excel).

    Visibilité par équipe (2026-09-16, voir schema.sql / v_projet_visibilite) :
    un utilisateur ne voit que les projets de sa propre équipe, sauf s'il y
    est explicitement rattaché (chef, co-chef, intervenant) même hors de son
    équipe, ou s'il est Admin (accès total) — le RH ne voit aucun projet et
    un Client seulement ceux de son équipe (migration 0011).
    """
    sql = """
        SELECT p.id, p.code, p.nom, p.phase, p.etat, p.date_debut, p.date_fin,
               p.client, p.honoraires,
               u.prenom AS chef_prenom, u.nom AS chef_nom, u.id AS chef_id,
               u.avatar_chemin AS chef_avatar_chemin,
               COALESCE(
                 (SELECT string_agg(pl.lot_code, ' · ' ORDER BY pl.lot_code)
                  FROM projet_lot pl WHERE pl.projet_id = p.id),
                 ''
               ) AS lots,
               -- Sous-requête plutôt que LEFT JOIN v_projet_heures (audit
               -- n°2) : la vue agrégeait TOUT dailylog_entree à chaque
               -- appel ; ici la somme n'est calculée que pour les lignes
               -- retenues par le LIMIT (index idx_dailylog_projet).
               (SELECT sum(de.heures) FROM dailylog_entree de
                 WHERE de.projet_id = p.id) AS heures_cumulees,
               -- Répartition par rôle (retour Fadhel, 2026-09-28, Lot 5) —
               -- même choix "sous-requête plutôt que vue" que ci-dessus,
               -- et même définition du rôle que v_projet_heures_par_role
               -- (schema.sql) : chef titulaire ou co-chef du projet.
               (SELECT sum(de.heures) FROM dailylog_entree de
                 WHERE de.projet_id = p.id
                   AND (de.utilisateur_id = p.chef_projet_id
                        OR EXISTS (SELECT 1 FROM projet_co_chef pc
                                   WHERE pc.projet_id = p.id AND pc.utilisateur_id = de.utilisateur_id))
               ) AS heures_chef,
               (SELECT sum(de.heures) FROM dailylog_entree de
                 WHERE de.projet_id = p.id
                   AND NOT (de.utilisateur_id = p.chef_projet_id
                        OR EXISTS (SELECT 1 FROM projet_co_chef pc
                                   WHERE pc.projet_id = p.id AND pc.utilisateur_id = de.utilisateur_id))
               ) AS heures_intervenant,
               (SELECT min(t.date_echeance) FROM tache t
                 WHERE t.projet_id = p.id AND t.etat = 'en_cours'
                   AND t.date_echeance IS NOT NULL) AS prochaine_echeance,
               -- Prochain rendu client et prochaine échéance, avec le nom
               -- de la tâche (infobulle de la colonne Deadlines, retour
               -- Fadhel, 2026-09-29) — tâches En cours seulement, même
               -- règle que Deadlines (taches.list_deadlines) : ni Bloquée
               -- (lot 11 : des tâches bloquées depuis 2022 passaient en tête
               -- de liste), ni Vérifiée, Arrêtée, Terminée ou Abandonnée.
               pr.date_echeance AS prochain_rendu, pr.titre AS prochain_rendu_titre,
               pe.date_echeance AS prochaine_deadline, pe.titre AS prochaine_deadline_titre,
               pe.type_deadline AS prochaine_deadline_type
        FROM projet p
        JOIN utilisateur u ON u.id = p.chef_projet_id
        LEFT JOIN LATERAL (
            SELECT t.date_echeance, t.titre FROM tache t
            WHERE t.projet_id = p.id AND t.etat = 'en_cours'
              AND t.date_echeance IS NOT NULL AND t.type_deadline = 'rendu_client'
            ORDER BY t.date_echeance, t.id LIMIT 1
        ) pr ON true
        LEFT JOIN LATERAL (
            SELECT t.date_echeance, t.titre, t.type_deadline FROM tache t
            WHERE t.projet_id = p.id AND t.etat = 'en_cours'
              AND t.date_echeance IS NOT NULL
            ORDER BY t.date_echeance, (t.type_deadline <> 'rendu_client'), t.id LIMIT 1
        ) pe ON true
    """ + _FILTRES_LISTE + """
        -- Tri (retour Fadhel, 2026-09-29) : d'abord les projets qui ont un
        -- rendu client, du plus proche au plus lointain (en retard en
        -- tête), puis ceux qui n'ont qu'une échéance interne, puis les
        -- autres (les plus récemment modifiés d'abord) ; l'id départage
        -- (pagination stable).
        ORDER BY (pr.date_echeance IS NULL), pr.date_echeance,
                 (pe.date_echeance IS NULL), pe.date_echeance,
                 p.updated_at DESC, p.id DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """
    params = _params_liste(user_id, etats, phases, chef_ids, lots_contient, lots_egal, q)
    params.update(limit=limit, offset=max(0, offset or 0))
    with db.get_cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def compter_projets(
    user_id: int,
    etats: list[str] | None = None, phases: list[str] | None = None,
    chef_ids: list[int] | None = None,
    lots_contient: list[str] | None = None, lots_egal: list[str] | None = None,
    q: str | None = None,
) -> int:
    """Nombre total de projets de la liste, mêmes filtres que list_projets
    (compteur « 653 projets » et pagination, lot 11)."""
    row = db.query_one(
        "SELECT count(*) AS n FROM projet p" + _FILTRES_LISTE,
        _params_liste(user_id, etats, phases, chef_ids, lots_contient, lots_egal, q),
    )
    return int(row["n"]) if row else 0


def list_chefs_de_projet(user_id: int | None = None) -> list[dict]:
    """Personnes ayant effectivement été chef de projet d'au moins un
    projet — alimente le filtre "Chef de projet" de /projets.

    Bug corrigé (2026-09-27, retour Fadhel) : ce filtre utilisait
    `utilisateurs.list_actifs()`, qui renvoie TOUS les utilisateurs actifs
    non-RH (Intervenants et Clients compris) — pertinent pour choisir QUI
    devient chef de projet à la création (n'importe qui de non-RH peut se
    voir confier un projet), mais pas pour un filtre qui ne doit lister que
    des personnes réellement chef de projet d'un projet existant. On
    requête donc directement les `chef_projet_id` distincts de la table
    `projet`, plutôt que de filtrer par rôle (un Admin peut légitimement
    être chef de projet, ce que `role = 'chef_de_projet'` exclurait).

    `user_id` (retour Fadhel, 2026-09-29 : « ne pas montrer les chefs de
    projets sans projets ») : seulement les chefs d'au moins un projet en
    cours ou bloqué que cette personne voit."""
    sql = """
        SELECT DISTINCT u.id, u.prenom, u.nom, u.avatar_chemin
        FROM utilisateur u
        JOIN projet p ON p.chef_projet_id = u.id
        WHERE (%(user_id)s::bigint IS NULL OR (
                p.etat IN ('en_cours', 'bloque')
                AND EXISTS (SELECT 1 FROM v_projet_visibilite vv
                            WHERE vv.projet_id = p.id AND vv.utilisateur_id = %(user_id)s)
              ))
        ORDER BY u.nom, u.prenom
    """
    return db.query_all(sql, {"user_id": user_id})


def search(user_id: int, q: str, limit: int = 8) -> list[dict]:
    """Recherche libre sur "Code_nom", limitée aux projets visibles par
    `user_id` — pour la barre de recherche de la topbar (demandé par
    Fadhel, 2026-09-19). Sans accents ni casse (lot 11 : « residence »
    trouve « Résidence »)."""
    sql = """
        SELECT p.id, p.code, p.nom, p.etat
        FROM projet p
        WHERE fn_recherche(p.code || '_' || p.nom) LIKE fn_recherche(%(q)s)
          AND EXISTS (
                SELECT 1 FROM v_projet_visibilite vv
                WHERE vv.projet_id = p.id AND vv.utilisateur_id = %(user_id)s
              )
        ORDER BY p.updated_at DESC
        LIMIT %(limit)s
    """
    return db.query_all(sql, {"q": motif_recherche(q), "user_id": user_id, "limit": limit})


def list_ouverts_chef_inactif() -> list[dict]:
    """Projets En cours ou Bloqués dont le chef de projet titulaire est un
    compte désactivé (lot 11 : encart de la liste Utilisateurs, vue Admin) —
    plus personne ne les pilote."""
    return db.query_all(
        """
        SELECT p.id, p.code, p.nom, p.etat, u.id AS chef_id, u.prenom AS chef_prenom, u.nom AS chef_nom
        FROM projet p
        JOIN utilisateur u ON u.id = p.chef_projet_id
        WHERE p.etat IN ('en_cours', 'bloque') AND NOT u.actif
        ORDER BY u.nom, u.prenom, p.code
        """
    )


def get_projet(projet_id: int) -> dict | None:
    """Détail d'un projet (en-tête de la page projet)."""
    sql = """
        SELECT p.id, p.code, p.nom, p.phase, p.etat, p.date_debut, p.date_fin, p.date_cloture,
               p.honoraires, p.client, p.chef_projet_id, p.phase_liee_id,
               u.prenom AS chef_prenom, u.nom AS chef_nom,
               u.avatar_chemin AS chef_avatar_chemin,
               pl.code AS phase_liee_code, pl.nom AS phase_liee_nom,
               h.heures_cumulees, h.heures_chef, h.heures_intervenant
        FROM projet p
        JOIN utilisateur u ON u.id = p.chef_projet_id
        LEFT JOIN projet pl ON pl.id = p.phase_liee_id
        -- Sous-requête limitée au projet plutôt que les vues
        -- v_projet_heures / v_projet_heures_par_role (audit, lot 7) : même
        -- calcul, mais seulement sur les lignes de CE projet
        -- (idx_dailylog_projet) au lieu de tout le DailyLog.
        LEFT JOIN LATERAL (
          SELECT SUM(de.heures) AS heures_cumulees,
                 SUM(CASE WHEN de.utilisateur_id = p.chef_projet_id
                            OR EXISTS (SELECT 1 FROM projet_co_chef pc
                                       WHERE pc.projet_id = p.id AND pc.utilisateur_id = de.utilisateur_id)
                          THEN de.heures ELSE 0 END) AS heures_chef,
                 SUM(CASE WHEN de.utilisateur_id = p.chef_projet_id
                            OR EXISTS (SELECT 1 FROM projet_co_chef pc
                                       WHERE pc.projet_id = p.id AND pc.utilisateur_id = de.utilisateur_id)
                          THEN 0 ELSE de.heures END) AS heures_intervenant
          FROM dailylog_entree de
          WHERE de.projet_id = p.id
        ) h ON true
        WHERE p.id = %s
    """
    return db.query_one(sql, (projet_id,))


def update_projet(
    projet_id: int,
    nom: str,
    etat: str,
    lots: list[str],
    date_debut=None,
    date_fin=None,
    phase_liee_id: int | None = None,
    current_user_id: int | None = None,
    honoraires=None,
    client: str = "IPCO",
) -> None:
    """Édition des informations du projet — fenêtre flottante
    "Informations" (retour Fadhel, 2026-09-28), réservée au chef de
    projet/co-chef (voir user_can_manage). `updated_by`/`updated_at`
    sont posés automatiquement par trg_projet_updated_at (schema.sql),
    pas ici.

    Volontairement PAS éditables ici : `code` (identifiant stable, utilisé
    dans les URLs/exports) et `phase` — la table "Draft entities" de la
    spec liste la phase comme fixée "à la création" (elle détermine la
    lettre du code), et une transition de phase se fait en créant un
    NOUVEAU projet relié via `phase_liee_id` (champ "Phase liée"), pas en
    éditant la phase d'un projet existant."""
    from ..utils import projet_etat_style

    with db.get_cursor(user_id=current_user_id) as cur:
        cur.execute("SELECT etat FROM projet WHERE id = %s FOR UPDATE", (projet_id,))
        avant = cur.fetchone()
        cur.execute(
            """
            UPDATE projet
            SET nom = %s, etat = %s, date_debut = %s, date_fin = %s, phase_liee_id = %s,
                honoraires = %s, client = %s,
                -- Date de clôture (migration 0011, décision Fadhel) : posée au
                -- passage à Terminé/Abandonné (gardée de l'un à l'autre),
                -- effacée à la réouverture.
                date_cloture = CASE WHEN %s IN ('termine', 'abandonne')
                                    THEN COALESCE(date_cloture, CURRENT_DATE) END
            WHERE id = %s
            """,
            (nom, etat, date_debut, date_fin, phase_liee_id, honoraires, client, etat, projet_id),
        )
        # Post automatique quand l'état change (retour Fadhel, 2026-09-29,
        # P1), dans la même transaction.
        if avant is not None and avant["etat"] != etat:
            cur.execute(
                """
                INSERT INTO post (projet_id, auteur_id, type_code, contenu, evenement)
                VALUES (%s, %s, 'information', %s, 'etat_projet')
                """,
                (projet_id, current_user_id,
                 f"{projet_etat_style(avant['etat'])['label']} → {projet_etat_style(etat)['label']}"),
            )
        # Remplace les lots (supprime puis réinsère) — même principe que
        # dailylog.remplacer_jour : plus simple qu'un diff, et le volume
        # (CM/GO, 1 à 2 lignes) ne justifie pas mieux.
        cur.execute("DELETE FROM projet_lot WHERE projet_id = %s", (projet_id,))
        for lot_code in lots:
            cur.execute(
                "INSERT INTO projet_lot (projet_id, lot_code) VALUES (%s, %s)",
                (projet_id, lot_code),
            )


def list_lots(projet_id: int) -> list[dict]:
    sql = """
        SELECT l.code, l.libelle
        FROM projet_lot pjl
        JOIN lot l ON l.code = pjl.lot_code
        WHERE pjl.projet_id = %s
        ORDER BY l.code
    """
    return db.query_all(sql, (projet_id,))


def list_intervenants(projet_id: int) -> list[dict]:
    """Toutes les personnes ayant travaillé sur le projet — chef de projet,
    co-chefs, intervenants du projet ET intervenants d'une de ses tâches
    (retour Fadhel, 2026-09-28 : ces derniers manquaient entièrement du
    panneau "Intervenants" jusqu'ici) —, dédupliquées et triées : le chef
    de projet d'abord, puis les AUTRES personnes dont le rôle global est
    "chef_de_projet" (qu'elles soient ici co-chef ou simple intervenant),
    puis le reste des intervenants."""
    sql = """
        WITH gens AS (
            SELECT p.chef_projet_id AS utilisateur_id, 'Chef de projet' AS role_label, 1 AS label_ord
            FROM projet p WHERE p.id = %(pid)s

            UNION ALL

            SELECT cc.utilisateur_id, 'Co-chef', 2
            FROM projet_co_chef cc WHERE cc.projet_id = %(pid)s

            UNION ALL

            SELECT pi.utilisateur_id, NULL, 3
            FROM projet_intervenant pi WHERE pi.projet_id = %(pid)s

            UNION ALL

            SELECT ti.utilisateur_id, NULL, 3
            FROM tache_intervenant ti JOIN tache t ON t.id = ti.tache_id
            WHERE t.projet_id = %(pid)s
        ),
        dedup AS (
            -- Une personne peut apparaître via plusieurs sources (co-chef ET
            -- intervenant d'une tâche, par ex.) : on garde son meilleur
            -- libellé d'affichage (label_ord le plus petit).
            SELECT DISTINCT ON (utilisateur_id) utilisateur_id, role_label, label_ord
            FROM gens
            ORDER BY utilisateur_id, label_ord
        )
        SELECT u.id, u.prenom, u.nom, u.poste, u.avatar_chemin,
               COALESCE(d.role_label, u.poste, 'Intervenant') AS role_label,
               CASE
                 WHEN d.label_ord = 1 THEN 1
                 WHEN u.role = 'chef_de_projet' THEN 2
                 ELSE 3
               END AS ord
        FROM dedup d
        JOIN utilisateur u ON u.id = d.utilisateur_id
        ORDER BY ord, u.nom
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"pid": projet_id})
        return [dict(r) for r in cur.fetchall()]


def list_ids_visibles(user_id: int) -> set[int]:
    """Ensemble des id de projets visibles par `user_id` (v_projet_visibilite,
    voir schema.sql) — pour filtrer, côté appli, des données qui
    référencent un projet sans passer par list_projets/search (page de
    profil d'une personne, Lot 5 : le DailyLog/les tâches/les posts
    d'un AUTRE utilisateur ne doivent montrer que les projets que LE
    VISITEUR peut voir, pas ceux de la personne consultée — sinon un
    profil deviendrait un détour pour voir les projets d'une équipe à
    laquelle on n'appartient pas, IDOR, PROMPT_CORRECTIONS.md P0 #1)."""
    rows = db.query_all(
        "SELECT projet_id FROM v_projet_visibilite WHERE utilisateur_id = %s", (user_id,)
    )
    return {r["projet_id"] for r in rows}


def user_can_view(projet_id: int, user_id: int) -> bool:
    """Vrai si `user_id` a le droit de voir le projet `projet_id`, selon
    exactement la même règle que la vue `v_projet_visibilite` (équipe,
    chef, co-chef, intervenant du projet ou d'une de ses tâches, ou
    Admin ; jamais le RH ; un Client : son équipe seulement — voir
    schema.sql / migration 0011).

    À utiliser pour tout accès DIRECT à un objet (page projet, création de
    post/tâche, téléchargement de pièce jointe...), en miroir des listes
    (list_projets/search) qui filtrent déjà par cette vue — corrige un
    contrôle d'accès manquant de type IDOR (PROMPT_CORRECTIONS.md P0 #1) :
    avant ce correctif, connaître/deviner un id de projet suffisait à en
    voir le détail, quelle que soit l'équipe de l'utilisateur."""
    sql = """
        SELECT 1
        FROM v_projet_visibilite vv
        WHERE vv.projet_id = %s AND vv.utilisateur_id = %s
    """
    with db.get_cursor() as cur:
        cur.execute(sql, (projet_id, user_id))
        return cur.fetchone() is not None


# États d'un projet clos (décision Fadhel, lot 7) : plus aucune
# intervention — posts, commentaires, réactions, tâches, fichiers,
# intervenants — tant que son chef ou un co-chef ne le rouvre pas (seule la
# fenêtre "Informations" reste utilisable, pour changer l'état).
ETATS_CLOS = ("termine", "abandonne")


def user_can_manage(projet_id: int, user_id: int) -> bool:
    """Droits de gestion (créer/éditer des tâches, intervenants, fenêtre
    Informations, rouvrir un projet clos) :
    - l'Admin, sur TOUS les projets, réouverture comprise (décision 2,
      lot 10) ;
    - le chef de projet titulaire et les co-chefs. Un chef de projet ajouté
      comme intervenant (projet ou tâche) EST co-chef (décision 3, lot 10) :
      l'appli l'inscrit dans projet_co_chef (add_intervenant) et les
      triggers de la migration 0013 font de même pour tout autre chemin.
    Jamais un Client ni le RH (lot 7, même s'il reste un rattachement
    d'avant la migration 0011), jamais un compte désactivé."""
    sql = """
        SELECT 1
        FROM projet p
        JOIN utilisateur ux ON ux.id = %(uid)s
        WHERE p.id = %(pid)s
          AND ux.actif AND ux.role NOT IN ('client', 'rh')
          AND (
                ux.role = 'admin'
             OR p.chef_projet_id = ux.id
             OR EXISTS (SELECT 1 FROM projet_co_chef cc
                        WHERE cc.projet_id = p.id AND cc.utilisateur_id = ux.id)
              )
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"pid": projet_id, "uid": user_id})
        return cur.fetchone() is not None


def user_est_rattache(projet_id: int, user_id: int) -> bool:
    """Vrai si `user_id` est déjà chef de projet, co-chef, ou intervenant
    (niveau projet) de `projet_id` — utilisé pour savoir si le bouton
    « Rejoindre ce projet » doit être proposé (retour Fadhel, 2026-09-28) :
    seules les personnes qui voient déjà le projet (même équipe, voir
    user_can_view) mais n'y sont pas encore formellement rattachées
    doivent pouvoir le rejoindre en un clic."""
    sql = """
        SELECT 1
        FROM projet p
        LEFT JOIN projet_co_chef cc ON cc.projet_id = p.id AND cc.utilisateur_id = %(uid)s
        LEFT JOIN projet_intervenant pi ON pi.projet_id = p.id AND pi.utilisateur_id = %(uid)s
        WHERE p.id = %(pid)s
          AND (p.chef_projet_id = %(uid)s OR cc.utilisateur_id IS NOT NULL OR pi.utilisateur_id IS NOT NULL)
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"pid": projet_id, "uid": user_id})
        return cur.fetchone() is not None


def add_co_chef(projet_id: int, utilisateur_id: int, current_user_id: int) -> None:
    """« Rejoindre ce projet » pour un chef de projet (retour Fadhel,
    2026-09-29, PR8) : il rejoint comme co-chef, pas comme intervenant."""
    db.execute(
        """
        INSERT INTO projet_co_chef (projet_id, utilisateur_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (projet_id, utilisateur_id),
        user_id=current_user_id,
    )


def add_intervenant(projet_id: int, utilisateur_id: int, current_user_id: int) -> bool:
    """Rattache `utilisateur_id` au projet. Un utilisateur de rôle
    « chef_de_projet » devient co-chef (décision 3, lot 10) au lieu
    d'intervenant — jamais co-chef de son propre projet. Retourne True si
    un rattachement a été CRÉÉ (False s'il existait déjà), pour ne notifier
    qu'une fois."""
    with db.get_cursor(user_id=current_user_id) as cur:
        cur.execute("SELECT role FROM utilisateur WHERE id = %s", (utilisateur_id,))
        row = cur.fetchone()
        if row and row["role"] == "chef_de_projet":
            cur.execute(
                """
                INSERT INTO projet_co_chef (projet_id, utilisateur_id)
                SELECT p.id, %s FROM projet p WHERE p.id = %s AND p.chef_projet_id <> %s
                ON CONFLICT DO NOTHING
                """,
                (utilisateur_id, projet_id, utilisateur_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO projet_intervenant (projet_id, utilisateur_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (projet_id, utilisateur_id),
            )
        return cur.rowcount == 1


# Phases valides (phase_enum, schema.sql) — voir PROMPT_CORRECTIONS.md P2
# #22 : propose_code() ne validait pas `phase`, une valeur inconnue
# tombait silencieusement sur la lettre "X" (celle d'EXE).
PHASES_VALIDES = {"APS", "APD", "DCE", "EXE", "DOE"}


LETTRE_PHASE = {"APS": "P", "APD": "P", "DCE": "D", "EXE": "X", "DOE": "E"}


def code_valide(code: str, phase: str) -> bool:
    """Format d'un code projet (retour Fadhel, lot 8 : « on ne peut pas
    mettre 26001Z, Z ne veut rien dire ») : l'année sur 2 chiffres, un
    numéro d'au moins 3 chiffres, puis la lettre de la phase (APS/APD → P,
    DCE → D, EXE → X, DOE → E). Ex. 26001X pour un EXE."""
    import re

    lettre = LETTRE_PHASE.get(phase)
    # 20 caractères au plus (projet.code VARCHAR(20)).
    return bool(lettre) and re.fullmatch(rf"\d{{5,19}}{lettre}", code or "") is not None


# Série 9xx (lot 11, décision du gérant) : numéros réservés, saisis à la
# main (projets internes, essais…) — jamais proposés automatiquement, et
# jamais pris comme « dernier numéro » de l'année.
SERIE_RESERVEE = range(900, 1000)


def propose_code(phase: str, annee: int | None = None, phase_liee_code: str | None = None) -> str:
    """Propose le prochain code projet pour une année/phase données
    (ex. "26099X"), modifiable ensuite par l'utilisateur — voir spec :
    le code reste semi-automatique côté application, la base ne fait que
    garantir son unicité (contrainte UNIQUE sur projet.code).

    Lot 11 (décision du gérant) : le numéro d'AFFAIRE est global à
    l'année, toutes phases confondues — le plus grand numéro de l'année
    hors série 9xx, + 1 ; seule la lettre dépend de la phase (APS/APD → P,
    DCE → D, EXE → X, DOE → E). Avant, le maximum était calculé par lettre :
    26922P était proposé alors que 26922 était déjà l'affaire 26922X, et la
    série 9xx était proposée. Si le numéro suivant tombe dans la série 9xx,
    on passe à 1000 et au-delà (comparaison numérique, pas de tri texte :
    PROMPT_CORRECTIONS.md P2 #22).

    Une phase liée garde le numéro de sa phase liée, avec la lettre de la
    nouvelle phase (26001D → 26001X), s'il est libre ; sinon (APS → APD,
    même lettre P) on retombe sur le numéro suivant de l'année.
    """
    import datetime
    import re

    if phase not in PHASES_VALIDES:
        phase = "EXE"
    lettre = LETTRE_PHASE[phase]

    if phase_liee_code:
        m = re.fullmatch(r"(\d{5,})[A-Z]", phase_liee_code)
        if m:
            candidat = f"{m.group(1)}{lettre}"
            if db.query_one("SELECT 1 AS pris FROM projet WHERE code = %s", (candidat,)) is None:
                return candidat

    annee = annee or datetime.date.today().year
    prefixe = f"{annee % 100:02d}"

    rows = db.query_all("SELECT code FROM projet WHERE code LIKE %s", (f"{prefixe}%",))
    motif = re.compile(rf"^{re.escape(prefixe)}(\d{{3,}})[A-Z]$")
    numeros = [int(m.group(1)) for m in (motif.match(r["code"]) for r in rows) if m]
    suivant = max((n for n in numeros if n < SERIE_RESERVEE.start), default=0) + 1
    if suivant in SERIE_RESERVEE:
        suivant = max((n for n in numeros if n >= SERIE_RESERVEE.stop), default=SERIE_RESERVEE.stop - 1) + 1
    return f"{prefixe}{suivant:03d}{lettre}"


def create_projet(
    code: str,
    nom: str,
    phase: str,
    chef_projet_id: int,
    lots: list[str],
    date_debut=None,
    phase_liee_id: int | None = None,
    equipe_code: str | None = None,
    current_user_id: int | None = None,
    honoraires=None,
    client: str = "IPCO",
) -> int:
    """`equipe_code` (2026-09-16) : équipe "propriétaire" du projet, utilisée
    pour la visibilité (voir v_projet_visibilite dans schema.sql). Si non
    précisé, on reprend automatiquement l'équipe du chef de projet — comme
    décidé avec Fadhel ("proposée automatiquement, modifiable")."""
    if equipe_code is None:
        chef = db.query_one("SELECT equipe_code FROM utilisateur WHERE id = %s", (chef_projet_id,))
        equipe_code = chef["equipe_code"] if chef else None

    with db.get_cursor(user_id=current_user_id) as cur:
        cur.execute(
            """
            INSERT INTO projet (code, nom, phase, chef_projet_id, date_debut, phase_liee_id, equipe_code,
                                created_by, honoraires, client)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (code, nom, phase, chef_projet_id, date_debut, phase_liee_id, equipe_code, current_user_id,
             honoraires, client),
        )
        projet_id = cur.fetchone()["id"]
        for lot_code in lots:
            cur.execute(
                "INSERT INTO projet_lot (projet_id, lot_code) VALUES (%s, %s)",
                (projet_id, lot_code),
            )
        # Post automatique (retour Fadhel, 2026-09-29, P1) : la création du
        # projet apparaît dans le fil, dans la même transaction.
        cur.execute(
            """
            INSERT INTO post (projet_id, auteur_id, type_code, contenu, evenement)
            VALUES (%s, %s, 'information', %s, 'creation_projet')
            """,
            (projet_id, current_user_id or chef_projet_id, f"{code}_{nom}"),
        )
        return projet_id

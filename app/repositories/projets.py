"""Requêtes SQL liées aux projets.

Toutes les requêtes ici sont des SELECT (lecture) sauf create_projet, donc
la plupart n'ont pas besoin de user_id (pas de trace à écrire). Seule
create_projet passe user_id pour alimenter created_by/updated_by + audit_log.
"""
from .. import db


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


def list_projets(
    user_id: int, limit: int = 200,
    etats: list[str] | None = None, phases: list[str] | None = None,
    chef_ids: list[int] | None = None, lots: list[str] | None = None,
    q: str | None = None,
) -> list[dict]:
    """Liste complète des projets visibles par `user_id` (vue "Tous les
    projets") avec le nom du chef de projet, les lots concaténés et la
    prochaine échéance — filtrable par états/phases/chefs de
    projet/lots (multi-sélection, sélecteur à puces — voir
    projets_liste.html) et par recherche libre sur "Code_nom".

    Visibilité par équipe (2026-09-16, voir schema.sql / v_projet_visibilite) :
    un utilisateur ne voit que les projets de sa propre équipe, sauf s'il y
    est explicitement rattaché (chef, co-chef, intervenant) même hors de son
    équipe, ou s'il est Admin/RH (accès total).
    """
    sql = """
        SELECT p.id, p.code, p.nom, p.phase, p.etat, p.date_debut, p.date_fin,
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
               (SELECT min(t.date_echeance) FROM tache t
                 WHERE t.projet_id = p.id AND t.etat NOT IN ('termine', 'abandonne')
                   AND t.date_echeance IS NOT NULL) AS prochaine_echeance
        FROM projet p
        JOIN utilisateur u ON u.id = p.chef_projet_id
        WHERE (%(etats)s IS NULL OR p.etat::text = ANY(%(etats)s))
          AND (%(phases)s IS NULL OR p.phase::text = ANY(%(phases)s))
          AND (%(chef_ids)s IS NULL OR p.chef_projet_id = ANY(%(chef_ids)s))
          -- Filtre lots (retour Fadhel, 2026-09-28) : quand UN SEUL lot est
          -- sélectionné, exclusif — seulement les projets qui N'ONT QUE ce
          -- lot (pas ceux qui l'ont parmi d'autres). Avec plusieurs lots
          -- sélectionnés, on garde le comportement "contient au moins un
          -- de ces lots" (comme avant), le cas exclusif n'ayant été demandé
          -- que pour la sélection à un seul lot.
          --
          -- BUG CORRIGÉ (2026-09-28, retour Fadhel — 500 sur /projets à
          -- CHAQUE chargement, "Tous les projets" et "Mes projets → Voir
          -- tout" étant tous deux inutilisables) : quand aucun lot n'est
          -- sélectionné, psycopg2 envoie %(lots)s comme un NULL non typé,
          -- et `NULL[1]`/`array_length(NULL, 1)` sont des erreurs de
          -- syntaxe côté Postgres — contrairement à `x = ANY(NULL)`
          -- (etats/phases ci-dessus), qui infère le type via l'opérateur
          -- `=` et ne plante pas. `NULL::text[]` lève l'ambiguïté de type
          -- AVANT toute subscription/array_length, y compris pour la
          -- branche jamais atteinte à l'exécution (l'erreur est levée à
          -- l'analyse de la requête, pas au moment de l'évaluation du OR).
          AND (
                %(lots)s::text[] IS NULL
                OR (
                     array_length(%(lots)s::text[], 1) = 1
                     AND EXISTS (
                           SELECT 1 FROM projet_lot pl2
                           WHERE pl2.projet_id = p.id AND pl2.lot_code = (%(lots)s::text[])[1]
                         )
                     AND (SELECT count(*) FROM projet_lot pl3 WHERE pl3.projet_id = p.id) = 1
                   )
                OR (
                     array_length(%(lots)s::text[], 1) > 1
                     AND EXISTS (
                           SELECT 1 FROM projet_lot pl2
                           WHERE pl2.projet_id = p.id AND pl2.lot_code = ANY(%(lots)s::text[])
                         )
                   )
              )
          AND (%(q)s IS NULL OR lower(p.code || '_' || p.nom) LIKE %(q)s)
          AND EXISTS (
                SELECT 1 FROM v_projet_visibilite vv
                WHERE vv.projet_id = p.id AND vv.utilisateur_id = %(user_id)s
              )
        ORDER BY p.updated_at DESC
        LIMIT %(limit)s
    """
    params = {
        "etats": etats or None, "phases": phases or None,
        "chef_ids": chef_ids or None, "lots": lots or None,
        "q": f"%{q.strip().lower()}%" if q else None,
        "limit": limit, "user_id": user_id,
    }
    with db.get_cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def list_chefs_de_projet() -> list[dict]:
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
    être chef de projet, ce que `role = 'chef_de_projet'` exclurait)."""
    sql = """
        SELECT DISTINCT u.id, u.prenom, u.nom
        FROM utilisateur u
        JOIN projet p ON p.chef_projet_id = u.id
        ORDER BY u.nom, u.prenom
    """
    return db.query_all(sql)


def search(user_id: int, q: str, limit: int = 8) -> list[dict]:
    """Recherche libre sur "Code_nom", limitée aux projets visibles par
    `user_id` — pour la barre de recherche de la topbar (demandé par
    Fadhel, 2026-09-19)."""
    sql = """
        SELECT p.id, p.code, p.nom
        FROM projet p
        WHERE lower(p.code || '_' || p.nom) LIKE %(q)s
          AND EXISTS (
                SELECT 1 FROM v_projet_visibilite vv
                WHERE vv.projet_id = p.id AND vv.utilisateur_id = %(user_id)s
              )
        ORDER BY p.updated_at DESC
        LIMIT %(limit)s
    """
    return db.query_all(sql, {"q": f"%{q.strip().lower()}%", "user_id": user_id, "limit": limit})


def get_projet(projet_id: int) -> dict | None:
    """Détail d'un projet (en-tête de la page projet)."""
    sql = """
        SELECT p.id, p.code, p.nom, p.phase, p.etat, p.date_debut, p.date_fin,
               p.honoraires, p.chef_projet_id, p.phase_liee_id,
               u.prenom AS chef_prenom, u.nom AS chef_nom,
               u.avatar_chemin AS chef_avatar_chemin,
               pl.code AS phase_liee_code, pl.nom AS phase_liee_nom,
               vh.heures_cumulees
        FROM projet p
        JOIN utilisateur u ON u.id = p.chef_projet_id
        LEFT JOIN projet pl ON pl.id = p.phase_liee_id
        LEFT JOIN v_projet_heures vh ON vh.projet_id = p.id
        WHERE p.id = %s
    """
    return db.query_one(sql, (projet_id,))


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


def user_can_view(projet_id: int, user_id: int) -> bool:
    """Vrai si `user_id` a le droit de voir le projet `projet_id`, selon
    exactement la même règle que la vue `v_projet_visibilite` (équipe,
    chef, co-chef, intervenant du projet ou d'une de ses tâches, ou
    Admin/RH — voir schema.sql).

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


def user_can_manage(projet_id: int, user_id: int) -> bool:
    """Chef de projet OU co-chef : seuls eux peuvent créer des tâches sur
    ce projet (cf. décision "co-chef simple" — voir spec)."""
    sql = """
        SELECT 1
        FROM projet p
        LEFT JOIN projet_co_chef cc ON cc.projet_id = p.id AND cc.utilisateur_id = %(uid)s
        WHERE p.id = %(pid)s AND (p.chef_projet_id = %(uid)s OR cc.utilisateur_id IS NOT NULL)
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


def add_intervenant(projet_id: int, utilisateur_id: int, current_user_id: int) -> None:
    db.execute(
        """
        INSERT INTO projet_intervenant (projet_id, utilisateur_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (projet_id, utilisateur_id),
        user_id=current_user_id,
    )


# Phases valides (phase_enum, schema.sql) — voir PROMPT_CORRECTIONS.md P2
# #22 : propose_code() ne validait pas `phase`, une valeur inconnue
# tombait silencieusement sur la lettre "X" (celle d'EXE).
PHASES_VALIDES = {"APS", "APD", "DCE", "EXE", "DOE"}


def propose_code(phase: str, annee: int | None = None) -> str:
    """Propose le prochain code projet pour une année/phase données
    (ex. "26099X"), modifiable ensuite par l'utilisateur — voir spec :
    le code reste semi-automatique côté application, la base ne fait que
    garantir son unicité (contrainte UNIQUE sur projet.code).

    PROMPT_CORRECTIONS.md P2 #22 : le numéro n'est plus déduit d'un tri
    texte (`ORDER BY code DESC LIMIT 1`), qui casse dès que le numéro
    dépasse 999 — "26999X" est lexicalement supérieur à "261000X" bien
    qu'inférieur numériquement, ce qui aurait proposé un code déjà pris.
    On récupère tous les codes de l'année/phase et on prend le MAX() du
    numéro extrait par regex.
    """
    import datetime
    import re

    if phase not in PHASES_VALIDES:
        phase = "EXE"
    lettre = {"APS": "P", "APD": "P", "DCE": "D", "EXE": "X", "DOE": "E"}[phase]
    annee = annee or datetime.date.today().year
    prefixe = f"{annee % 100:02d}"

    sql = "SELECT code FROM projet WHERE code LIKE %s"
    rows = db.query_all(sql, (f"{prefixe}%{lettre}",))
    motif = re.compile(rf"^{re.escape(prefixe)}(\d+){re.escape(lettre)}$")
    numero_max = 0
    for row in rows:
        m = motif.match(row["code"])
        if m:
            numero_max = max(numero_max, int(m.group(1)))
    return f"{prefixe}{numero_max + 1:03d}{lettre}"


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
            INSERT INTO projet (code, nom, phase, chef_projet_id, date_debut, phase_liee_id, equipe_code, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (code, nom, phase, chef_projet_id, date_debut, phase_liee_id, equipe_code, current_user_id),
        )
        projet_id = cur.fetchone()["id"]
        for lot_code in lots:
            cur.execute(
                "INSERT INTO projet_lot (projet_id, lot_code) VALUES (%s, %s)",
                (projet_id, lot_code),
            )
        return projet_id

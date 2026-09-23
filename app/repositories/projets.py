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
               vh.heures_cumulees,
               (SELECT min(t.date_echeance) FROM tache t
                 WHERE t.projet_id = p.id AND t.etat NOT IN ('termine', 'abandonne')
                   AND t.date_echeance IS NOT NULL) AS prochaine_echeance
        FROM projet p
        JOIN utilisateur u ON u.id = p.chef_projet_id
        LEFT JOIN v_projet_heures vh ON vh.projet_id = p.id
        WHERE (%(etats)s IS NULL OR p.etat::text = ANY(%(etats)s))
          AND (%(phases)s IS NULL OR p.phase::text = ANY(%(phases)s))
          AND (%(chef_ids)s IS NULL OR p.chef_projet_id = ANY(%(chef_ids)s))
          AND (%(lots)s IS NULL OR EXISTS (
                SELECT 1 FROM projet_lot pl2
                WHERE pl2.projet_id = p.id AND pl2.lot_code = ANY(%(lots)s)
              ))
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


def list_co_chefs(projet_id: int) -> list[dict]:
    sql = """
        SELECT u.id, u.prenom, u.nom
        FROM projet_co_chef cc
        JOIN utilisateur u ON u.id = cc.utilisateur_id
        WHERE cc.projet_id = %s
        ORDER BY u.nom
    """
    return db.query_all(sql, (projet_id,))


def list_intervenants(projet_id: int) -> list[dict]:
    """Chef de projet + co-chefs + intervenants, avec un libellé de rôle —
    alimente le panneau "Intervenants" de la page projet.
    """
    sql = """
        SELECT u.id, u.prenom, u.nom, u.poste, u.avatar_chemin, 'Chef de projet' AS role_label, 1 AS ord
        FROM projet p JOIN utilisateur u ON u.id = p.chef_projet_id
        WHERE p.id = %(pid)s

        UNION ALL

        SELECT u.id, u.prenom, u.nom, u.poste, u.avatar_chemin, 'Co-chef' AS role_label, 2 AS ord
        FROM projet_co_chef cc JOIN utilisateur u ON u.id = cc.utilisateur_id
        WHERE cc.projet_id = %(pid)s

        UNION ALL

        SELECT u.id, u.prenom, u.nom, u.poste, u.avatar_chemin,
               COALESCE(u.poste, 'Intervenant') AS role_label, 3 AS ord
        FROM projet_intervenant pi JOIN utilisateur u ON u.id = pi.utilisateur_id
        WHERE pi.projet_id = %(pid)s

        ORDER BY ord, nom
    """
    with db.get_cursor() as cur:
        cur.execute(sql, {"pid": projet_id})
        return [dict(r) for r in cur.fetchall()]


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


def propose_code(phase: str, annee: int | None = None) -> str:
    """Propose le prochain code projet pour une année/phase données
    (ex. "26099X"), modifiable ensuite par l'utilisateur — voir spec :
    le code reste semi-automatique côté application, la base ne fait que
    garantir son unicité (contrainte UNIQUE sur projet.code).
    """
    import datetime

    lettre = {"APS": "P", "APD": "P", "DCE": "D", "EXE": "X", "DOE": "E"}.get(phase, "X")
    annee = annee or datetime.date.today().year
    prefixe = f"{annee % 100:02d}"

    sql = """
        SELECT code FROM projet
        WHERE code LIKE %s
        ORDER BY code DESC
        LIMIT 1
    """
    row = db.query_one(sql, (f"{prefixe}%{lettre}",))
    if row is None:
        numero = 1
    else:
        # ex. "26099X" -> "099" -> 99
        chiffres = row["code"][2:-1]
        numero = int(chiffres) + 1 if chiffres.isdigit() else 1
    return f"{prefixe}{numero:03d}{lettre}"


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

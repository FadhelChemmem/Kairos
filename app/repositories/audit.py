"""Journal d'audit (retour Fadhel, 2026-09-28, Lot 5) — lecture seule sur
`audit_log`, table + triggers qui existent depuis le tout premier schéma
(2026-09-15, voir schema.sql : fn_audit_log() + un trigger par table
métier). Ce chantier n'ajoute donc AUCUNE infrastructure nouvelle : juste
une page admin pour parcourir des données déjà tracées automatiquement à
chaque INSERT/UPDATE/DELETE (le hash de mot de passe et le token de reset
sont déjà retirés des lignes stockées, côté fn_audit_log()).

Volontairement PAS de pagination offset/limit : comme list_projets() et
le reste de l'appli, un simple LIMIT (le plus récent d'abord) suffit pour
un journal qu'on consulte pour une recherche ponctuelle, pas pour tout
parcourir.
"""
from .. import db

# Tables couvertes par un trigger d'audit (voir schema.sql, section
# "Audit") — alimente le filtre "Table" de la page. Garder synchronisé
# avec les CREATE TRIGGER trg_audit_* de schema.sql.
TABLES_AUDITEES = [
    "utilisateur", "projet", "projet_lot", "projet_co_chef",
    "projet_intervenant", "tache", "tache_intervenant",
    "tache_piece_jointe", "dailylog_entree", "dailylog_jour", "post", "post_piece_jointe",
    "post_mention", "post_equipe", "post_commentaire", "post_commentaire_piece_jointe",
    "post_commentaire_mention",
]

# Lot 12 (migration 0018) : pas des tables, mais les entrées / sorties des
# modes de l'Admin, écrites par journaliser_mode ci-dessous — proposées
# elles aussi au filtre « Table » de la page.
TABLES_MODES = ["mode_voir_comme", "mode_agir_comme", "date_simulee"]
TABLES_FILTRABLES = TABLES_AUDITEES + TABLES_MODES

ACTIONS_VALIDES = ["INSERT", "UPDATE", "DELETE", "ENTREE", "SORTIE"]


def journaliser_mode(table_cible: str, action: str, admin_id: int, compte_vu_id: int | None,
                     donnees: dict) -> None:
    """Entrée ou sortie d'un mode de l'Admin (lot 12) : « Voir comme »,
    « Agir comme » (ligne_id = compte vu) ou date simulée. Auteur et Admin
    réel = l'Admin ; created_at réel (now()), jamais la date simulée."""
    import json

    with db.get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log (table_cible, ligne_id, action, utilisateur_id, admin_reel_id, donnees_apres)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            (table_cible, compte_vu_id, action, admin_id, admin_id, json.dumps(donnees, ensure_ascii=False)),
        )


def list_entrees(
    table_cible: str | None = None, utilisateur_id: int | None = None,
    action: str | None = None, date_debut=None, date_fin=None,
    limit: int = 300,
) -> list[dict]:
    """Journal filtré, le plus récent d'abord — avec le nom de l'auteur
    (peut être NULL : action système, ou compte supprimé depuis) et, lot 12,
    celui de l'Admin réel quand il « agissait comme » l'auteur (le filtre
    « Auteur » retrouve aussi ces lignes pour cet Admin)."""
    sql = """
        SELECT a.id, a.table_cible, a.ligne_id, a.action, a.created_at,
               a.donnees_avant, a.donnees_apres,
               u.id AS auteur_id, u.prenom AS auteur_prenom, u.nom AS auteur_nom,
               ar.id AS admin_reel_id, ar.prenom AS admin_reel_prenom, ar.nom AS admin_reel_nom
        FROM audit_log a
        LEFT JOIN utilisateur u ON u.id = a.utilisateur_id
        LEFT JOIN utilisateur ar ON ar.id = a.admin_reel_id
        WHERE (%(table_cible)s IS NULL OR a.table_cible = %(table_cible)s)
          AND (%(utilisateur_id)s IS NULL OR a.utilisateur_id = %(utilisateur_id)s
               OR a.admin_reel_id = %(utilisateur_id)s)
          AND (%(action)s IS NULL OR a.action = %(action)s)
          -- ::date obligatoire (bug corrigé le 2026-09-29, "l'onglet Log ne
          -- marche pas") : sans filtre de date, psycopg2 envoie un NULL non
          -- typé, et « NULL + interval '1 day' » fait échouer TOUTE la
          -- requête côté Postgres (opérateur ambigu) — la page plantait en
          -- 500 dès son ouverture.
          AND (%(date_debut)s::date IS NULL OR a.created_at >= %(date_debut)s::date)
          AND (%(date_fin)s::date IS NULL OR a.created_at < %(date_fin)s::date + interval '1 day')
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT %(limit)s
    """
    params = {
        "table_cible": table_cible or None,
        "utilisateur_id": utilisateur_id or None,
        "action": action or None,
        "date_debut": date_debut or None,
        "date_fin": date_fin or None,
        "limit": limit,
    }
    with db.get_cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def list_auteurs() -> list[dict]:
    """Personnes ayant au moins une entrée dans le journal — alimente le
    filtre "Auteur" (inclut les comptes désactivés : on veut pouvoir
    retrouver l'historique de quelqu'un qui est parti)."""
    sql = """
        SELECT u.id, u.prenom, u.nom
        FROM utilisateur u
        WHERE EXISTS (SELECT 1 FROM audit_log a WHERE a.utilisateur_id = u.id)
           OR EXISTS (SELECT 1 FROM audit_log a WHERE a.admin_reel_id = u.id)
        ORDER BY u.prenom, u.nom
    """
    with db.get_cursor() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]

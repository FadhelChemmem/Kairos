"""Tableaux de bord de l'accueil (lot 14) : « Vue d'ensemble » de l'Admin
(revue produit P0-3) et carte « À traiter » du chef de projet (P1-2).

Périmètre : TOUS les projets ouverts (en cours ou bloqués) pour l'Admin
(`tous=True`), sinon les projets ouverts dont la personne est chef
titulaire ou co-chef. Tâche ouverte = en cours ou bloquée (les autres
états sont clos, voir taches.ETATS_CLOS) ; en retard = en cours, échéance
passée (décision 5 du lot 10 : une tâche bloquée n'a plus d'échéance
suivie). Daily log manquant : dailylog.manquants_du_jour (recette du lot
14, n° 9 : périmètre de la page « Daily log de l'équipe »).

Une requête par bloc affiché : les compteurs en une seule (agrégats
filtrés), la liste détaillée d'un compteur à la demande, le tableau
« Par chef de projet » en une seule.
"""
from .. import db

CLES = ("retard", "bloquees", "sans_intervenant", "sans_echeance", "projets_sans_tache", "dailylog")

_PERIMETRE = """
    perim AS (
        SELECT p.id, p.code, p.nom, p.etat, p.phase, p.chef_projet_id
        FROM projet p
        WHERE p.etat IN ('en_cours', 'bloque')
          AND (%(tous)s
               OR p.chef_projet_id = %(uid)s
               OR EXISTS (SELECT 1 FROM projet_co_chef cc
                          WHERE cc.projet_id = p.id AND cc.utilisateur_id = %(uid)s))
    ),
    ouvertes AS (
        SELECT t.id, t.titre, t.etat, t.date_echeance, t.type_deadline, t.updated_at, t.projet_id,
               t.bloque_motif, t.bloque_le, t.bloque_par
        FROM tache t JOIN perim ON perim.id = t.projet_id
        WHERE t.etat IN ('en_cours', 'bloque')
    )"""

def _params(uid: int, tous: bool, aujourdhui, jour) -> dict:
    return {"uid": uid, "tous": bool(tous), "auj": aujourdhui, "jour": jour}


def compteurs(uid: int, tous: bool, aujourdhui, jour) -> dict:
    """Les compteurs de tâches et de projets, le nombre de projets ouverts
    du périmètre et le plus grand retard (en jours), en une requête. Le
    compteur « Daily log manquants » vient de dailylog.manquants_du_jour
    (même périmètre que la page « Daily log de l'équipe »)."""
    sql = "WITH" + _PERIMETRE + """
        SELECT
          (SELECT count(*) FROM perim) AS projets,
          (SELECT count(*) FROM ouvertes WHERE etat = 'en_cours' AND date_echeance < %(auj)s) AS retard,
          (SELECT max(%(auj)s - date_echeance) FROM ouvertes WHERE etat = 'en_cours' AND date_echeance < %(auj)s) AS retard_max,
          (SELECT count(*) FROM ouvertes WHERE etat = 'bloque') AS bloquees,
          (SELECT count(DISTINCT projet_id) FROM ouvertes WHERE etat = 'bloque') AS projets_bloques,
          (SELECT count(*) FROM ouvertes o
            WHERE NOT EXISTS (SELECT 1 FROM tache_intervenant ti JOIN utilisateur ia ON ia.id = ti.utilisateur_id AND ia.actif WHERE ti.tache_id = o.id)) AS sans_intervenant,
          (SELECT count(*) FROM ouvertes WHERE etat = 'en_cours' AND date_echeance IS NULL) AS sans_echeance,
          (SELECT count(*) FROM perim
            WHERE NOT EXISTS (SELECT 1 FROM ouvertes o WHERE o.projet_id = perim.id)) AS projets_sans_tache
    """
    row = db.query_one(sql, _params(uid, tous, aujourdhui, jour)) or {}
    return {k: int(row.get(k) or 0) for k in ("projets", "retard", "retard_max", "bloquees", "projets_bloques",
                                               "sans_intervenant", "sans_echeance", "projets_sans_tache")}


_TACHES = """
        SELECT o.id, o.titre, o.etat, o.date_echeance, o.type_deadline, o.updated_at,
               o.bloque_motif, o.bloque_le,
               (SELECT ub.prenom FROM utilisateur ub WHERE ub.id = o.bloque_par) AS bloque_par_prenom,
               (SELECT ub.nom FROM utilisateur ub WHERE ub.id = o.bloque_par) AS bloque_par_nom,
               perim.id AS projet_id, perim.code AS projet_code, perim.nom AS projet_nom,
               u.id AS chef_id, u.prenom AS chef_prenom, u.nom AS chef_nom,
               (SELECT string_agg(iu.prenom || ' ' || iu.nom, ', ' ORDER BY iu.nom, iu.prenom)
                  FROM tache_intervenant ti JOIN utilisateur iu ON iu.id = ti.utilisateur_id
                 WHERE ti.tache_id = o.id) AS intervenants
        FROM ouvertes o
        JOIN perim ON perim.id = o.projet_id
        JOIN utilisateur u ON u.id = perim.chef_projet_id
        WHERE {condition}
        ORDER BY {ordre}
        LIMIT %(limit)s"""

_LISTES = {
    "retard": ("o.etat = 'en_cours' AND o.date_echeance < %(auj)s", "o.date_echeance, perim.code, o.id"),
    # Même ordre que la section « Bloquées » (taches.list_bloquees, recette
    # du lot 14 n° 10) : le blocage le plus ancien d'abord.
    "bloquees": ("o.etat = 'bloque'", "o.bloque_le NULLS FIRST, perim.code, o.id"),
    "sans_intervenant": ("NOT EXISTS (SELECT 1 FROM tache_intervenant ti JOIN utilisateur ia ON ia.id = ti.utilisateur_id AND ia.actif WHERE ti.tache_id = o.id)",
                         "o.date_echeance NULLS LAST, perim.code, o.id"),
    "sans_echeance": ("o.etat = 'en_cours' AND o.date_echeance IS NULL", "perim.code, o.titre, o.id"),
}


def liste(cle: str, uid: int, tous: bool, aujourdhui, jour, limit: int = 100) -> list[dict]:
    """Lignes d'un compteur (tâches, projets ou personnes), `limit` au plus."""
    params = {**_params(uid, tous, aujourdhui, jour), "limit": limit}
    if cle in _LISTES:
        condition, ordre = _LISTES[cle]
        return db.query_all("WITH" + _PERIMETRE + _TACHES.format(condition=condition, ordre=ordre), params)
    if cle == "projets_sans_tache":
        return db.query_all("WITH" + _PERIMETRE + """
            SELECT perim.id, perim.code, perim.nom, perim.etat, perim.phase,
                   u.id AS chef_id, u.prenom AS chef_prenom, u.nom AS chef_nom,
                   (SELECT max(COALESCE(t.date_fin, t.updated_at::date)) FROM tache t
                     WHERE t.projet_id = perim.id) AS derniere_tache
            FROM perim JOIN utilisateur u ON u.id = perim.chef_projet_id
            WHERE NOT EXISTS (SELECT 1 FROM ouvertes o WHERE o.projet_id = perim.id)
            ORDER BY derniere_tache NULLS FIRST, perim.code
            LIMIT %(limit)s""", params)
    return []


def par_chef(aujourdhui, lundi) -> list[dict]:
    """Tableau « Par chef de projet » de la Vue d'ensemble : pour chaque chef
    titulaire d'au moins un projet ouvert, ses projets ouverts, leurs tâches
    en retard et bloquées, et les heures saisies sur ses projets (tous
    intervenants, chef compris) depuis lundi."""
    return db.query_all(
        """
        WITH perim AS (
            SELECT p.id, p.chef_projet_id FROM projet p WHERE p.etat IN ('en_cours', 'bloque')
        ),
        par_projet AS (
            SELECT perim.chef_projet_id, count(*) AS projets,
                   sum((SELECT count(*) FROM tache t WHERE t.projet_id = perim.id AND t.etat = 'en_cours'
                          AND t.date_echeance < %(auj)s)) AS retard,
                   sum((SELECT count(*) FROM tache t WHERE t.projet_id = perim.id AND t.etat = 'bloque')) AS bloquees
            FROM perim GROUP BY perim.chef_projet_id
        ),
        heures AS (
            SELECT p.chef_projet_id, sum(d.heures) AS heures
            FROM dailylog_entree d JOIN projet p ON p.id = d.projet_id
            WHERE d.date BETWEEN %(lundi)s AND %(auj)s
            GROUP BY p.chef_projet_id
        )
        SELECT u.id, u.prenom, u.nom, u.avatar_chemin, u.actif,
               pp.projets, pp.retard, pp.bloquees, COALESCE(h.heures, 0) AS heures
        FROM par_projet pp
        JOIN utilisateur u ON u.id = pp.chef_projet_id
        LEFT JOIN heures h ON h.chef_projet_id = pp.chef_projet_id
        ORDER BY pp.projets DESC, u.nom, u.prenom
        """,
        {"auj": aujourdhui, "lundi": lundi},
    )


def gere_des_projets(uid: int) -> bool:
    """Chef titulaire ou co-chef d'au moins un projet ouvert."""
    return db.query_one(
        """
        SELECT EXISTS (
            SELECT 1 FROM projet p
            WHERE p.etat IN ('en_cours', 'bloque')
              AND (p.chef_projet_id = %(uid)s
                   OR EXISTS (SELECT 1 FROM projet_co_chef cc WHERE cc.projet_id = p.id AND cc.utilisateur_id = %(uid)s))
        ) AS oui
        """,
        {"uid": uid},
    )["oui"]


def saisit_des_heures(uid: int) -> bool:
    """L'Admin a-t-il déjà saisi des heures ou une absence (revue produit
    P2-1 : la carte Daily log est masquée pour un Admin qui n'en saisit pas) ?"""
    return db.query_one(
        """
        SELECT EXISTS (SELECT 1 FROM dailylog_entree WHERE utilisateur_id = %(uid)s)
            OR EXISTS (SELECT 1 FROM dailylog_jour WHERE utilisateur_id = %(uid)s) AS oui
        """,
        {"uid": uid},
    )["oui"]


def pastilles_projets(projet_ids: list[int], aujourdhui) -> dict[int, dict]:
    """Carte « Mes projets » : tâches en retard et prochaine échéance (tâches
    en cours) de chaque projet, en une requête."""
    if not projet_ids:
        return {}
    rows = db.query_all(
        """
        SELECT t.projet_id,
               count(*) FILTER (WHERE t.date_echeance < %(auj)s) AS retard,
               min(t.date_echeance) FILTER (WHERE t.date_echeance >= %(auj)s) AS prochaine
        FROM tache t
        WHERE t.projet_id = ANY(%(ids)s) AND t.etat = 'en_cours' AND t.date_echeance IS NOT NULL
        GROUP BY t.projet_id
        """,
        {"ids": list(projet_ids), "auj": aujourdhui},
    )
    return {r["projet_id"]: {"retard": int(r["retard"] or 0), "prochaine": r["prochaine"]} for r in rows}


def taches_de_mes_projets(uid: int, limit: int = 200) -> list[dict]:
    """Carte « Tâches de mes projets » (revue produit P1-2) : les tâches en
    cours des projets ouverts que la personne gère (chef, co-chef), celles
    où elle intervient et celles qu'elle a créées, avec `mienne` (elle en
    est intervenante). Échéance la plus proche d'abord."""
    return db.query_all(
        """
        SELECT t.id, t.titre, t.etat, t.date_echeance, p.id AS projet_id, p.code AS projet_code, p.nom AS projet_nom,
               EXISTS (SELECT 1 FROM tache_intervenant ti WHERE ti.tache_id = t.id AND ti.utilisateur_id = %(uid)s) AS mienne
        FROM tache t
        JOIN projet p ON p.id = t.projet_id
        WHERE t.etat = 'en_cours'
          AND p.etat IN ('en_cours', 'bloque')
          AND (p.chef_projet_id = %(uid)s
               OR t.created_by = %(uid)s
               OR EXISTS (SELECT 1 FROM projet_co_chef cc WHERE cc.projet_id = p.id AND cc.utilisateur_id = %(uid)s)
               OR EXISTS (SELECT 1 FROM tache_intervenant ti WHERE ti.tache_id = t.id AND ti.utilisateur_id = %(uid)s))
          -- Lot 18 : « créée par moi » ne suffit plus si je ne vois plus le projet.
          AND EXISTS (SELECT 1 FROM v_projet_visibilite vv WHERE vv.projet_id = p.id AND vv.utilisateur_id = %(uid)s)
        ORDER BY (t.date_echeance < CURRENT_DATE - 90), t.date_echeance NULLS LAST, p.code, t.id
        LIMIT %(limit)s
        """,
        {"uid": uid, "limit": limit},
    )

"""Abonnements Web Push (lot 24, migration 0027) : un par appareil et
navigateur, rattaché au compte connecté au moment de l'activation."""
from .. import db
from . import notifications as notifications_repo


def enregistrer(utilisateur_id: int, endpoint: str, p256dh: str, auth: str, navigateur: str | None,
                cle_serveur: str | None = None, maximum: int = 10) -> bool:
    """Crée l'abonnement, ou le rattache à ce compte quand le MÊME
    navigateur (mêmes clés) est utilisé par une autre personne : l'ancien
    titulaire ne reçoit plus rien sur ce poste. Lot 25 (PU-04) : un endpoint
    connu présenté avec d'autres clés n'est pas repris (False). Au plus
    `maximum` appareils par compte (PU-11) : les moins récents sont retirés.
    `cle_serveur` : clé VAPID publique du serveur au moment de l'abonnement
    (PU-12)."""
    with db.get_cursor(user_id=utilisateur_id) as cur:
        cur.execute(
            """
            INSERT INTO push_abonnement (utilisateur_id, endpoint, cle_p256dh, cle_auth, navigateur, cle_serveur)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (endpoint) DO UPDATE SET
              utilisateur_id = EXCLUDED.utilisateur_id, navigateur = EXCLUDED.navigateur,
              cle_serveur = EXCLUDED.cle_serveur, vu_le = now()
            WHERE push_abonnement.cle_p256dh = EXCLUDED.cle_p256dh AND push_abonnement.cle_auth = EXCLUDED.cle_auth
            RETURNING id
            """,
            (utilisateur_id, endpoint, p256dh, auth, (navigateur or "")[:200] or None, cle_serveur),
        )
        if cur.fetchone() is None:
            return False
        cur.execute(
            """
            DELETE FROM push_abonnement WHERE id IN (
              SELECT id FROM push_abonnement WHERE utilisateur_id = %s
              ORDER BY vu_le DESC, id DESC OFFSET %s)
            """,
            (utilisateur_id, maximum),
        )
    return True


def supprimer(utilisateur_id: int, endpoint: str) -> int:
    with db.get_cursor(user_id=utilisateur_id) as cur:
        cur.execute("DELETE FROM push_abonnement WHERE utilisateur_id = %s AND endpoint = %s",
                    (utilisateur_id, endpoint))
        return cur.rowcount


def supprimer_par_id(utilisateur_id: int, abonnement_id: int) -> int:
    """« Retirer » un appareil depuis la liste de Mes informations (lot 25,
    U4 : PC perdu ou partagé)."""
    with db.get_cursor(user_id=utilisateur_id) as cur:
        cur.execute("DELETE FROM push_abonnement WHERE utilisateur_id = %s AND id = %s",
                    (utilisateur_id, abonnement_id))
        return cur.rowcount


def supprimer_endpoint(endpoint: str) -> None:
    """Abonnement expiré ou refusé par le service push (403, 404, 410) ou
    aux clés inutilisables."""
    db.execute("DELETE FROM push_abonnement WHERE endpoint = %s", (endpoint,))


def abonnements(utilisateur_id: int) -> list[dict]:
    return db.query_all("SELECT endpoint, cle_p256dh, cle_auth, cle_serveur FROM push_abonnement "
                        "WHERE utilisateur_id = %s ORDER BY id", (utilisateur_id,))


def appareils(utilisateur_id: int) -> list[dict]:
    """Appareils activés de la personne (Mes informations, lot 25 U4)."""
    return db.query_all("SELECT id, navigateur, created_at, vu_le FROM push_abonnement WHERE utilisateur_id = %s "
                        "ORDER BY vu_le DESC, id DESC", (utilisateur_id,))


def compter(utilisateur_id: int) -> int:
    ligne = db.query_one("SELECT count(*) AS n FROM push_abonnement WHERE utilisateur_id = %s", (utilisateur_id,))
    return ligne["n"] if ligne else 0


def est_abonne(utilisateur_id: int, endpoint: str, cle_serveur: str | None = None) -> bool:
    """Abonné pour CE compte, avec la clé VAPID actuelle (PU-12 : après un
    changement de clés, la carte propose de nouveau « Activer »)."""
    return db.query_one("SELECT 1 AS x FROM push_abonnement WHERE utilisateur_id = %s AND endpoint = %s "
                        "AND (cle_serveur IS NULL OR %s::text IS NULL OR cle_serveur = %s::text)",
                        (utilisateur_id, endpoint, cle_serveur, cle_serveur)) is not None


def marquer_en_attente(notification_ids: list[int]) -> None:
    """Lot 25 (PU-10) : notifications à pousser, retenues en base pour être
    reprises si le worker s'arrête avant l'envoi."""
    db.execute("UPDATE notification SET push_attente = true WHERE id = ANY(%s)", ([int(i) for i in notification_ids],))


def reserver(notification_ids: list[int]) -> list[int]:
    """Réserve les notifications encore en attente : un seul worker les
    pousse, une seule fois."""
    ids = [int(i) for i in notification_ids or []]
    if not ids:
        return []
    lignes = db.query_all("UPDATE notification SET push_attente = false WHERE id = ANY(%s) AND push_attente "
                          "RETURNING id", (ids,))
    return [ligne["id"] for ligne in lignes]


def en_attente_recentes(delai: float, minutes: int = 15) -> list[dict]:
    """Notifications restées en attente (worker arrêté) depuis moins de
    `minutes` : identifiant et secondes restant avant leur échéance."""
    return db.query_all(
        """
        SELECT id, GREATEST(0, %s - EXTRACT(EPOCH FROM (now() - created_at))) AS reste
        FROM notification
        WHERE push_attente AND created_at > now() - make_interval(mins => %s)
        ORDER BY id
        """,
        (float(delai), int(minutes)),
    )


def get_categories(utilisateur_id: int) -> list[str] | None:
    ligne = db.query_one("SELECT push_categories FROM utilisateur_preference WHERE utilisateur_id = %s",
                         (utilisateur_id,))
    return ligne["push_categories"] if ligne else None


def set_categories(utilisateur_id: int, categories: list[str] | None) -> None:
    db.execute(
        """
        INSERT INTO utilisateur_preference (utilisateur_id, push_categories) VALUES (%s, %s)
        ON CONFLICT (utilisateur_id) DO UPDATE SET push_categories = EXCLUDED.push_categories, updated_at = now()
        """,
        (utilisateur_id, categories),
        user_id=utilisateur_id,
    )


def notifications_a_pousser(notification_ids: list[int]) -> list[dict]:
    return notifications_repo.pour_push(notification_ids)

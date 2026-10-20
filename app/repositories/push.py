"""Abonnements Web Push (lot 24, migration 0027) : un par appareil et
navigateur, rattaché au compte connecté au moment de l'activation."""
from .. import db
from . import notifications as notifications_repo


def enregistrer(utilisateur_id: int, endpoint: str, p256dh: str, auth: str, navigateur: str | None) -> None:
    """Crée l'abonnement, ou le rattache à ce compte (même navigateur
    utilisé ensuite par une autre personne : l'ancien titulaire ne reçoit
    plus rien sur ce poste)."""
    db.execute(
        """
        INSERT INTO push_abonnement (utilisateur_id, endpoint, cle_p256dh, cle_auth, navigateur)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (endpoint) DO UPDATE SET
          utilisateur_id = EXCLUDED.utilisateur_id, cle_p256dh = EXCLUDED.cle_p256dh,
          cle_auth = EXCLUDED.cle_auth, navigateur = EXCLUDED.navigateur, vu_le = now()
        """,
        (utilisateur_id, endpoint, p256dh, auth, (navigateur or "")[:200] or None),
        user_id=utilisateur_id,
    )


def supprimer(utilisateur_id: int, endpoint: str) -> int:
    with db.get_cursor(user_id=utilisateur_id) as cur:
        cur.execute("DELETE FROM push_abonnement WHERE utilisateur_id = %s AND endpoint = %s",
                    (utilisateur_id, endpoint))
        return cur.rowcount


def supprimer_endpoint(endpoint: str) -> None:
    """Abonnement expiré (le service push a répondu 404 ou 410)."""
    db.execute("DELETE FROM push_abonnement WHERE endpoint = %s", (endpoint,))


def abonnements(utilisateur_id: int) -> list[dict]:
    return db.query_all("SELECT endpoint, cle_p256dh, cle_auth FROM push_abonnement WHERE utilisateur_id = %s "
                        "ORDER BY id", (utilisateur_id,))


def compter(utilisateur_id: int) -> int:
    ligne = db.query_one("SELECT count(*) AS n FROM push_abonnement WHERE utilisateur_id = %s", (utilisateur_id,))
    return ligne["n"] if ligne else 0


def est_abonne(utilisateur_id: int, endpoint: str) -> bool:
    return db.query_one("SELECT 1 AS x FROM push_abonnement WHERE utilisateur_id = %s AND endpoint = %s",
                        (utilisateur_id, endpoint)) is not None


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

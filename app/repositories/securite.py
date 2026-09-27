"""Limite de tentatives (revue sécurité, 2026-09-20) — connexion et "mot
de passe oublié". Fenêtre glissante simple sur une table dédiée
(tentative_securite, schema.sql) plutôt qu'un compteur en mémoire : ça
fonctionne correctement même avec plusieurs workers gunicorn (chacun a sa
propre mémoire, mais tous partagent la même base).
"""
from .. import db


def compter_tentatives_recentes(type_: str, cle: str, fenetre_minutes: int = 15) -> int:
    row = db.query_one(
        """
        SELECT count(*) AS n FROM tentative_securite
        WHERE type = %s AND cle = %s
          AND created_at > now() - (%s || ' minutes')::interval
        """,
        (type_, cle.strip().lower(), fenetre_minutes),
    )
    return row["n"] if row else 0


def enregistrer_tentative(type_: str, cle: str) -> None:
    """Enregistre une tentative ratée, et purge au passage celles de plus
    d'un jour (audit n°2 : la table n'était jamais nettoyée et grossissait
    à chaque échec de connexion ; seules les 15 dernières minutes servent)."""
    with db.get_cursor() as cur:
        cur.execute(
            "INSERT INTO tentative_securite (type, cle) VALUES (%s, %s)",
            (type_, cle.strip().lower()),
        )
        cur.execute("DELETE FROM tentative_securite WHERE created_at < now() - interval '1 day'")

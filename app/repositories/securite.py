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
    db.execute(
        "INSERT INTO tentative_securite (type, cle) VALUES (%s, %s)",
        (type_, cle.strip().lower()),
    )

"""Accès à la base de données — SQL brut via psycopg2, pas d'ORM.

Choix assumé : le schéma (schema.sql) est écrit et durci à la main
(ENUM, index fonctionnels, trigger d'audit générique — voir les
commentaires en tête de schema.sql) ; un ORM re-générerait ses propres
migrations et entrerait en conflit avec ce schéma. Le prix à payer est
que chaque requête un peu spécifique est écrite ici en SQL explicite —
en échange, on garde un contrôle total et un schéma lisible d'un bloc.

Le mécanisme de traçabilité (updated_by + audit_log, voir schema.sql)
repose entièrement sur UNE variable de session Postgres :

    SET LOCAL app.current_user_id = '<id>';

Cette ligne doit être exécutée AU DÉBUT de la même transaction que les
écritures qu'elle doit tracer (SET LOCAL est annulé au COMMIT/ROLLBACK
suivant — c'est le comportement voulu : chaque requête HTTP obtient sa
propre transaction et son propre "auteur"). C'est exactement ce que
`get_cursor()` fait ci-dessous, et c'est le même motif que celui déjà
validé manuellement via psql pendant la conception du schéma :

    BEGIN;
    SET LOCAL app.current_user_id = '2';
    UPDATE tache SET etat = 'termine', ... WHERE id = 1;
    INSERT INTO post (...) VALUES (...);
    COMMIT;
"""
import contextlib
import logging

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

_pool: ThreadedConnectionPool | None = None


def init_pool(database_url: str, minconn: int = 1, maxconn: int = 10) -> None:
    """À appeler une fois au démarrage de l'appli (voir app/__init__.py)."""
    global _pool
    if _pool is not None:
        return
    _pool = ThreadedConnectionPool(minconn, maxconn, dsn=database_url)
    logger.info("Pool de connexions Postgres initialisé (min=%s, max=%s)", minconn, maxconn)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


@contextlib.contextmanager
def get_cursor(user_id: int | None = None, commit: bool = True):
    """Fournit un curseur (lignes sous forme de dict) sur une connexion du pool.

    - Ouvre une transaction explicite (nécessaire pour que SET LOCAL ait
      un effet — voir la note en tête de fichier).
    - Si `user_id` est fourni, alimente app.current_user_id pour cette
      transaction : chaque INSERT/UPDATE/DELETE qui suit sera tracé avec
      cet auteur dans updated_by et audit_log, automatiquement, sans
      rien changer au SQL métier lui-même.
    - Commit automatique en sortie normale du bloc `with`, rollback
      automatique si une exception est levée à l'intérieur.
    - La connexion est toujours rendue au pool (bloc finally), même en
      cas d'erreur.
    """
    if _pool is None:
        raise RuntimeError("db.init_pool() n'a pas été appelé — vérifier app/__init__.py")

    conn = _pool.getconn()
    conn.autocommit = False
    cur = None
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if user_id is not None:
            # SET LOCAL n'accepte pas les paramètres de requête classiques
            # (ce n'est pas une commande DML) ; psycopg2 réalise la
            # substitution côté client (mogrify) donc %s reste sûr contre
            # l'injection SQL. On force un int avant coup pour être
            # explicite sur le type attendu.
            cur.execute("SET LOCAL app.current_user_id = %s", (str(int(user_id)),))
        yield cur
        if commit:
            conn.commit()
        else:
            conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        if cur is not None:
            cur.close()
        _pool.putconn(conn)


def query_all(sql: str, params: tuple = (), user_id: int | None = None) -> list[dict]:
    """SELECT retournant toutes les lignes (liste de dicts)."""
    with get_cursor(user_id=user_id) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def query_one(sql: str, params: tuple = (), user_id: int | None = None) -> dict | None:
    """SELECT retournant une seule ligne (dict) ou None."""
    with get_cursor(user_id=user_id) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row is not None else None


def execute(sql: str, params: tuple = (), user_id: int | None = None) -> int:
    """INSERT/UPDATE/DELETE sans besoin de récupérer de ligne. Retourne rowcount."""
    with get_cursor(user_id=user_id) as cur:
        cur.execute(sql, params)
        return cur.rowcount

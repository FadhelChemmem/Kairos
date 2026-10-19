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
import threading
import time

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

_pool: ThreadedConnectionPool | None = None

# Lot 20 (revue QA, N5) : après un redémarrage de PostgreSQL, chaque
# connexion du pool était morte et la première requête de chaque worker
# finissait en erreur 500. Une connexion inutilisée depuis SEUIL_PING
# secondes est testée (SELECT 1) avant d'être prêtée ; morte, elle est
# jetée et remplacée.
SEUIL_PING = 2.0
_derniere_utilisation: dict[int, float] = {}
_verrou_usage = threading.Lock()


class LectureSeule(Exception):
    """Écriture tentée pendant « Voir comme » (lot 12) : la transaction est
    READ ONLY (voir get_cursor) et PostgreSQL l'a refusée (25006). La page
    répond 403 « lecture seule » (app/__init__.py), jamais une erreur 500."""


def _reglages_requete() -> tuple[bool, int | None, "datetime.datetime | None"]:
    """Réglages de la requête HTTP en cours, posés par
    app/modes_admin.py:appliquer (lot 12) : (lecture seule, Admin réel qui
    « agit comme », instant simulé — lot 13). Hors requête (CLI, scripts) :
    rien."""
    try:
        from flask import g, has_request_context
    except ImportError:  # pragma: no cover - Flask est toujours là dans l'appli
        return False, None, None
    if not has_request_context():
        return False, None, None
    from . import horloge

    return bool(g.get("lecture_seule")), g.get("admin_reel_agit"), horloge.instant_simule()


def init_pool(database_url: str, minconn: int = 1, maxconn: int = 10) -> None:
    """À appeler une fois au démarrage de l'appli (voir app/__init__.py)."""
    global _pool
    if _pool is not None:
        return
    # jit=off (audit, lot 7) : sur nos petites requêtes, la compilation JIT
    # de Postgres coûtait plus qu'elle ne rapportait (page profil lente,
    # plusieurs centaines de ms passées à compiler). Réglé ici pour
    # chaque connexion de l'appli, sans toucher à la configuration du
    # serveur Postgres.
    _pool = ThreadedConnectionPool(minconn, maxconn, dsn=database_url, options="-c jit=off")
    logger.info("Pool de connexions Postgres initialisé (min=%s, max=%s)", minconn, maxconn)


@contextlib.contextmanager
def get_cursor(user_id: int | None = None, commit: bool = True):
    """Fournit un curseur (lignes sous forme de dict) sur une connexion du pool.

    - Ouvre une transaction explicite (nécessaire pour que SET LOCAL ait
      un effet — voir la note en tête de fichier).
    - Si `user_id` est fourni, alimente app.current_user_id pour cette
      transaction : chaque INSERT/UPDATE/DELETE qui suit sera tracé avec
      cet auteur dans updated_by et audit_log, automatiquement, sans
      rien changer au SQL métier lui-même.
    - Lot 12 (modes de l'Admin, app/modes_admin.py) : en « Voir comme »,
      la transaction est READ ONLY (aucune écriture possible, même par un
      chemin oublié) ; en « Agir comme », app.admin_reel_id porte l'Admin
      réel (recopié par fn_audit_log, migration 0018) ; avec une date
      simulée (mode test seulement), kairos.instant_simule porte l'instant
      simulé (fn_aujourdhui au fuseau de chacun, gardes du Daily log,
      migration 0019).
    - Commit automatique en sortie normale du bloc `with`, rollback
      automatique si une exception est levée à l'intérieur.
    - La connexion est toujours rendue au pool (bloc finally), même en
      cas d'erreur.
    """
    if _pool is None:
        raise RuntimeError("db.init_pool() n'a pas été appelé — vérifier app/__init__.py")

    lecture_seule, admin_reel_id, instant_simule = _reglages_requete()
    conn = _connexion_vivante()
    conn.autocommit = False
    cur = None
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if lecture_seule:
            # Premier ordre de la transaction (exigé par PostgreSQL).
            cur.execute("SET TRANSACTION READ ONLY")
        if user_id is not None:
            # SET LOCAL n'accepte pas les paramètres de requête classiques
            # (ce n'est pas une commande DML) ; psycopg2 réalise la
            # substitution côté client (mogrify) donc %s reste sûr contre
            # l'injection SQL. On force un int avant coup pour être
            # explicite sur le type attendu.
            cur.execute("SET LOCAL app.current_user_id = %s", (str(int(user_id)),))
        if admin_reel_id is not None:
            cur.execute("SET LOCAL app.admin_reel_id = %s", (str(int(admin_reel_id)),))
        if instant_simule is not None:
            cur.execute("SET LOCAL kairos.instant_simule = %s", (instant_simule.isoformat(timespec="microseconds"),))
        yield cur
        if commit:
            conn.commit()
        else:
            conn.rollback()
    except Exception as exc:
        # Après un redémarrage de PostgreSQL, la connexion du pool est morte :
        # rollback() lèverait alors sa propre InterfaceError et masquerait
        # l'erreur d'origine dans les journaux (audit n°2).
        try:
            conn.rollback()
        except Exception:
            pass
        if lecture_seule and getattr(exc, "pgcode", None) == "25006":
            raise LectureSeule() from exc
        raise
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        # Une connexion fermée n'est pas remise dans le pool (close=True) :
        # la requête suivante en obtiendra une neuve au lieu d'échouer à son
        # tour.
        with _verrou_usage:
            if conn.closed:
                _derniere_utilisation.pop(id(conn), None)
            else:
                _derniere_utilisation[id(conn)] = time.monotonic()
        _pool.putconn(conn, close=bool(conn.closed))


def _connexion_vivante():
    """Connexion du pool, testée si elle n'a pas servi depuis SEUIL_PING
    secondes (voir plus haut) ; trois connexions testées et écartées au
    plus, puis une quatrième rendue sans test (l'erreur éventuelle remonte
    alors normalement)."""
    erreurs = tuple(e for e in (getattr(psycopg2, "OperationalError", None),
                                getattr(psycopg2, "InterfaceError", None)) if e)
    for _ in range(3):
        conn = _pool.getconn()
        with _verrou_usage:
            dernier = _derniere_utilisation.get(id(conn))
        if not conn.closed and dernier is not None and time.monotonic() - dernier < SEUIL_PING:
            return conn
        if not conn.closed:
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                conn.rollback()
                return conn
            except erreurs:
                pass
        logger.warning("Connexion Postgres morte écartée du pool (redémarrage de la base\u00a0?)")
        with _verrou_usage:
            _derniere_utilisation.pop(id(conn), None)
        try:
            _pool.putconn(conn, close=True)
        except Exception:
            pass
    return _pool.getconn()


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

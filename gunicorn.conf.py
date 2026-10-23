"""Configuration gunicorn (chargée par `gunicorn -c gunicorn.conf.py`, voir
le CMD du Dockerfile) — audits sécurité I10 et QA I8 du lot 10.

Les liens « mot de passe oublié » et de création de compte contiennent un
jeton secret dans le CHEMIN (/reinitialiser/<jeton>) : le journal d'accès
de gunicorn (`docker compose logs web`) l'écrivait en clair, dans la
requête ET dans le Referer de la requête suivante. Ce filtre le remplace
par *** avant écriture.
"""
import logging
import re

_JETON = re.compile(r"(/reinitialiser/)[^\s?\"/#]+")


def masquer_jeton(texte):
    return _JETON.sub(r"\1***", texte) if isinstance(texte, str) else texte


class MasqueJetonReset(logging.Filter):
    def filter(self, record):
        # gunicorn passe ses « atomes » (r = ligne de requête, f = Referer,
        # U = chemin...) dans record.args, un dict : modifié EN PLACE pour
        # garder son type (valeurs par défaut des en-têtes absents).
        if isinstance(record.args, dict):
            for cle, valeur in list(record.args.items()):
                record.args[cle] = masquer_jeton(valeur)
        elif isinstance(record.args, tuple):
            record.args = tuple(masquer_jeton(v) for v in record.args)
        record.msg = masquer_jeton(record.msg)
        return True


def on_starting(server):
    logging.getLogger("gunicorn.access").addFilter(MasqueJetonReset())


def post_fork(server, worker):
    # Ceinture et bretelles : le filtre est porté par le logger, hérité au
    # fork ; on s'assure qu'il est bien présent dans chaque worker.
    access = logging.getLogger("gunicorn.access")
    if not any(isinstance(f, MasqueJetonReset) for f in access.filters):
        access.addFilter(MasqueJetonReset())


def post_worker_init(worker):
    # Lot 25 (PU-10) : notifications Windows restées en attente quand un
    # worker s'est arrêté (redémarrage, déploiement) reprises par le
    # nouveau worker. Jamais bloquant.
    try:
        from app import push

        push.demarrer(worker.wsgi)
    except Exception:
        logging.getLogger("gunicorn.error").exception("Reprise des notifications Windows impossible")

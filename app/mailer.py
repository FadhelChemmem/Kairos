"""Envoi d'email — SMTP simple (smtplib, déjà dans la bibliothèque
standard, aucune dépendance supplémentaire). Volontairement "best
effort" : un email qui échoue (SMTP non configuré, serveur mail en
panne...) ne doit jamais faire planter une création de compte ou une
demande de réinitialisation — voir la revue sécurité/fiabilité du
2026-09-20. L'appelant décide quoi dire à l'utilisateur si `envoyer`
renvoie False (ex. flash d'avertissement pour l'admin).
"""
import logging
import smtplib
import ssl
import threading
from email.message import EmailMessage

from flask import current_app

logger = logging.getLogger(__name__)


def _liste_autorisee(config) -> tuple[set[str], set[str]] | None:
    """MAIL_DESTINATAIRES_AUTORISES (mode test, décision du gérant, fin du
    lot 10) -> (adresses, domaines « @domaine »), en minuscules. None si la
    variable est vide ou absente : comportement normal, aucun filtre.
    Renseignée mais sans aucune entrée valide : rien n'est autorisé (on ne
    retombe jamais sur « tout le monde » à cause d'une faute de frappe)."""
    brut = (config.get("MAIL_DESTINATAIRES_AUTORISES") or "").strip()
    if not brut:
        return None
    adresses, domaines = set(), set()
    for entree in (e.strip().lower() for e in brut.split(",")):
        if not entree:
            continue
        if entree.startswith("@") and len(entree) > 1 and "@" not in entree[1:]:
            domaines.add(entree)
        elif entree.count("@") == 1 and not entree.endswith("@"):
            adresses.add(entree)
        else:
            logger.error("MAIL_DESTINATAIRES_AUTORISES : « %s » n'est ni une adresse ni un "
                         "@domaine : ignoré.", entree)
    return adresses, domaines


def masquer(adresse: str) -> str:
    """« medfadhel@gmail.com » -> « me***@gmail.com » (journaux)."""
    adresse = (adresse or "").strip()
    local, arobase, domaine = adresse.rpartition("@")
    if not arobase:
        return adresse[:2] + "***"
    return f"{local[:2]}***@{domaine}"


def destinataire_autorise(adresse: str) -> bool:
    """Vrai si un e-mail peut partir vers `adresse` : toujours sans
    MAIL_DESTINATAIRES_AUTORISES ; sinon seulement une adresse de la liste
    ou d'un de ses @domaines (casse ignorée). Ne dépend que de l'adresse et
    de la configuration, jamais de la base : le dire à l'écran ne révèle
    pas si un compte existe."""
    liste = _liste_autorisee(current_app.config)
    if liste is None:
        return True
    adresses, domaines = liste
    adresse = (adresse or "").strip().lower()
    if adresse.count("@") != 1:
        return False
    return adresse in adresses or "@" + adresse.split("@")[1] in domaines


def journaliser_mode_test(app) -> None:
    """Au démarrage : rappelle dans `docker compose logs web` que les
    e-mails sont limités (mode test)."""
    liste = _liste_autorisee(app.config)
    if liste is not None:
        adresses, domaines = liste
        logger.warning(
            "Mode test des e-mails (MAIL_DESTINATAIRES_AUTORISES) : seuls %s recevront un e-mail ; "
            "tout autre envoi est bloqué et journalisé.",
            ", ".join(sorted(adresses | domaines)) or "personne (aucune entrée valide)",
        )


def est_configure() -> bool:
    """Vrai si un serveur SMTP est renseigné (SMTP_HOST). Permet de dire
    clairement « l'e-mail n'a pas pu partir » au lieu d'un faux succès —
    sans rien révéler sur le compte visé, puisque la réponse ne dépend que
    de la configuration du serveur."""
    return bool(current_app.config.get("SMTP_HOST"))


def _bloque_par_voir_comme(destinataire: str, sujet: str) -> bool:
    """« Voir comme » (lot 12) : lecture seule, aucun e-mail ne part —
    défense en profondeur, les actions qui envoient sont déjà refusées."""
    from flask import g, has_request_context

    if has_request_context() and g.get("mode_admin") == "voir":
        logger.warning("E-mail NON envoyé à %s (« Voir comme » : lecture seule) : %s", masquer(destinataire), sujet)
        return True
    return False


def envoyer(destinataire: str, sujet: str, corps: str) -> bool:
    """Envoie un email texte simple. Retourne True si l'envoi a réussi,
    False sinon (et log la raison — jamais d'exception qui remonte).

    Mode test (MAIL_DESTINATAIRES_AUTORISES) : un destinataire hors liste
    n'est JAMAIS contacté — c'est vérifié ici, pour tous les chemins
    d'envoi ; journalisé sans le contenu, adresse masquée. « Agir comme »
    (lot 12) y reste soumis ; « Voir comme » n'envoie rien."""
    if _bloque_par_voir_comme(destinataire, sujet):
        return False
    if not destinataire_autorise(destinataire):
        logger.warning(
            "E-mail NON envoyé à %s (mode test : adresse hors de MAIL_DESTINATAIRES_AUTORISES) : %s",
            masquer(destinataire), sujet,
        )
        return False
    hote = current_app.config.get("SMTP_HOST")
    if not hote:
        logger.warning(
            "Email non envoyé à %s (SMTP_HOST non configuré dans .env) : %s",
            destinataire, sujet,
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = sujet
    msg["From"] = current_app.config.get("SMTP_FROM") or current_app.config.get("SMTP_USER") or "kairos@localhost"
    msg["To"] = destinataire
    msg.set_content(corps)

    port = current_app.config.get("SMTP_PORT", 587)
    utilisateur = current_app.config.get("SMTP_USER")
    mot_de_passe = current_app.config.get("SMTP_PASSWORD")
    use_tls = current_app.config.get("SMTP_USE_TLS", True)

    try:
        with smtplib.SMTP(hote, port, timeout=10) as serveur:
            if use_tls:
                # Certificat du serveur vérifié (audit sécurité I9) : sans
                # contexte, starttls() ne vérifie ni le certificat ni le nom.
                serveur.starttls(context=ssl.create_default_context())
            if utilisateur and mot_de_passe:
                serveur.login(utilisateur, mot_de_passe)
            serveur.send_message(msg)
        return True
    except Exception:
        logger.exception("Échec de l'envoi d'email à %s (sujet : %s)", destinataire, sujet)
        return False


def envoyer_en_arriere_plan(destinataire: str, sujet: str, corps: str) -> None:
    """Comme `envoyer`, mais sans faire attendre la requête HTTP : utilisé
    quand le temps de réponse ne doit rien révéler (mot de passe oublié —
    un envoi SMTP de plusieurs secondes trahissait qu'un compte existe).
    En mode test, l'envoi reste synchrone pour rester vérifiable."""
    if _bloque_par_voir_comme(destinataire, sujet):
        return
    app = current_app._get_current_object()
    if app.testing:
        envoyer(destinataire, sujet, corps)
        return

    def _envoyer():
        with app.app_context():
            envoyer(destinataire, sujet, corps)

    threading.Thread(target=_envoyer, daemon=True).start()

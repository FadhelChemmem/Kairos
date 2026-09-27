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
import threading
from email.message import EmailMessage

from flask import current_app

logger = logging.getLogger(__name__)


def envoyer(destinataire: str, sujet: str, corps: str) -> bool:
    """Envoie un email texte simple. Retourne True si l'envoi a réussi,
    False sinon (et log la raison — jamais d'exception qui remonte)."""
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
                serveur.starttls()
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
    app = current_app._get_current_object()
    if app.testing:
        envoyer(destinataire, sujet, corps)
        return

    def _envoyer():
        with app.app_context():
            envoyer(destinataire, sujet, corps)

    threading.Thread(target=_envoyer, daemon=True).start()

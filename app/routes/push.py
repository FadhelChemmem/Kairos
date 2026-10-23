"""Application installable et notifications Windows (lot 24, décision du
gérant du 20/10) : manifeste, service worker à la racine, abonnements Web
Push par appareil, notification d'essai, catégories poussées. Voir
app/push.py."""
import functools
import json
import os

from flask import Blueprint, Response, current_app, flash, g, jsonify, redirect, request, url_for

from .. import partiel, push
from ..auth import login_required
from ..repositories import push as push_repo

bp = Blueprint("push", __name__)

COULEUR_THEME = "#ffffff"   # barre du haut de Kairos (--surface)
COULEUR_FOND = "#f5f6f3"    # fond des pages (--bg)


@bp.route("/manifest.webmanifest")
def manifeste():
    """Manifeste de l'application installable (Chrome / Edge : « Installer
    Kairos ») : fenêtre propre, icône dans la barre des tâches et le menu
    Démarrer, ouverture sur l'accueil."""
    donnees = {
        "name": "Kairos",
        "short_name": "Kairos",
        "description": "Projets, tâches, Daily log et fil de Midgard Engineering.",
        "id": "/accueil",
        "start_url": "/accueil",
        "scope": "/",
        # Lot 25 (décision du gérant, option 2) : dans l'appli installée, la
        # barre du haut de Kairos prend la place de la barre de titre
        # (Window Controls Overlay) ; ailleurs, fenêtre classique.
        "display_override": ["window-controls-overlay", "standalone"],
        "display": "standalone",
        "lang": "fr",
        "background_color": COULEUR_FOND,
        "theme_color": COULEUR_THEME,
        "icons": [
            {"src": url_for("static", filename="img/icone-192.png"), "sizes": "192x192", "type": "image/png",
             "purpose": "any"},
            {"src": url_for("static", filename="img/icone-512.png"), "sizes": "512x512", "type": "image/png",
             "purpose": "any"},
            {"src": url_for("static", filename="img/icone-maskable-192.png"), "sizes": "192x192",
             "type": "image/png", "purpose": "maskable"},
            {"src": url_for("static", filename="img/icone-maskable-512.png"), "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }
    reponse = Response(json.dumps(donnees, ensure_ascii=False), mimetype="application/manifest+json")
    reponse.headers["Cache-Control"] = "no-cache"
    return reponse


@bp.route("/sw.js")
def service_worker():
    """Service worker à la racine (portée « / ») : réception des
    notifications Windows et ouverture de la notification cliquée. Pas de
    cache hors ligne (données vivantes). Jamais « immutable » : le
    navigateur revérifie le fichier à chaque visite."""
    chemin = os.path.join(current_app.static_folder, "js", "sw.js")
    with open(chemin, encoding="utf-8") as f:
        reponse = Response(f.read(), mimetype="application/javascript")
    reponse.headers["Cache-Control"] = "no-cache"
    reponse.headers["Service-Worker-Allowed"] = "/"
    return reponse


def _refus_mode():
    """« Voir comme » / « Agir comme » : le navigateur de l'Admin ne
    s'abonne jamais aux notifications d'un autre compte."""
    if g.get("admin_reel") or g.get("lecture_seule"):
        return jsonify({"erreur": "mode_admin",
                        "message": "Indisponible en «\u00a0Voir comme\u00a0» ou «\u00a0Agir comme\u00a0»."}), 403
    return None


def _json_connecte(vue):
    """Routes JSON de la carte « Notifications Windows » (lot 25, PU-09) :
    sans session, une réponse JSON 401 — jamais une redirection que fetch
    suivrait et prendrait pour un succès."""
    @functools.wraps(vue)
    def enveloppe(*args, **kwargs):
        if g.user is None or not g.user.get("actif", True):
            return jsonify({"erreur": "non_connecte", "message": "Session expirée\u00a0: rechargez la page."}), 401
        return vue(*args, **kwargs)

    return enveloppe


def _corps() -> dict:
    """Corps JSON : toujours un objet (PU-07 : une chaîne, un nombre ou une
    liste donnaient une erreur 500)."""
    corps = request.get_json(silent=True)
    return corps if isinstance(corps, dict) else {}


@bp.route("/push/cle")
@_json_connecte
def cle():
    reponse = jsonify({"cle": push.cle_publique(), "abonnements": push_repo.compter(g.user["id"])})
    reponse.headers["Cache-Control"] = "no-store"
    return reponse


@bp.route("/push/etat", methods=["POST"])
@_json_connecte
def etat():
    """Cet appareil est-il abonné pour CE compte, avec la clé actuelle ?
    (l'adresse d'abonnement n'est envoyée qu'en POST, jamais dans une URL)."""
    endpoint = _corps().get("endpoint")
    return jsonify({"abonne": bool(push.endpoint_valide(endpoint)
                                   and push_repo.est_abonne(g.user["id"], endpoint, push.cle_publique()))})


@bp.route("/push/abonnement", methods=["POST"])
@_json_connecte
def abonner():
    refus = _refus_mode()
    if refus:
        return refus
    if not push.actif():
        return jsonify({"erreur": "inactif", "message": "Notifications Windows non configurées sur le serveur."}), 409
    corps = _corps()
    endpoint = corps.get("endpoint")
    cles = corps.get("keys") if isinstance(corps.get("keys"), dict) else {}
    if not push.endpoint_valide(endpoint):
        return jsonify({"erreur": "invalide",
                        "message": "Service de notification inconnu\u00a0: utilisez Chrome ou Edge."}), 400
    if not push.cles_valides(cles.get("p256dh"), cles.get("auth")):
        return jsonify({"erreur": "invalide", "message": "Abonnement invalide."}), 400
    navigateur = (request.headers.get("User-Agent") or "")[:200]
    if not push_repo.enregistrer(g.user["id"], endpoint, cles["p256dh"], cles["auth"], navigateur,
                                 cle_serveur=push.cle_publique(), maximum=push.MAX_ABONNEMENTS):
        return jsonify({"erreur": "invalide", "message": "Abonnement invalide."}), 400
    return jsonify({"ok": True, "message": "Notifications activées sur ce PC."})


@bp.route("/push/desabonnement", methods=["POST"])
@_json_connecte
def desabonner():
    refus = _refus_mode()
    if refus:
        return refus
    endpoint = _corps().get("endpoint")
    if push.endpoint_valide(endpoint):
        push_repo.supprimer(g.user["id"], endpoint)
    return jsonify({"ok": True, "message": "Notifications désactivées sur ce PC."})


@bp.route("/push/essai", methods=["POST"])
@_json_connecte
def essai():
    """« Envoyer une notification d'essai » à tous les appareils activés de
    la personne, par la file d'envoi (lot 25, PU-14 : plus un fil par clic,
    une toutes les 15 s au plus)."""
    refus = _refus_mode()
    if refus:
        return refus
    if not push.actif() or not push_repo.compter(g.user["id"]):
        return jsonify({"erreur": "aucun", "message": "Aucun PC n’est activé pour vos notifications."}), 409
    if not push.planifier_essai(g.user["id"]):
        return jsonify({"erreur": "trop_tot",
                        "message": "Notification d’essai déjà envoyée\u00a0: patientez quelques secondes."}), 429
    return jsonify({"ok": True, "message": "Notification d’essai envoyée."})


@bp.route("/push/appareils/<int:abonnement_id>/retirer", methods=["POST"])
@login_required
def retirer_appareil(abonnement_id):
    """Retirer un appareil de la liste (lot 25, U4 : PC perdu, ancien PC,
    PC partagé)."""
    if g.get("admin_reel") or g.get("lecture_seule"):
        flash("Indisponible en «\u00a0Voir comme\u00a0» ou «\u00a0Agir comme\u00a0».", "error")
    elif push_repo.supprimer_par_id(g.user["id"], abonnement_id):
        flash("Appareil retiré\u00a0: il ne reçoit plus vos notifications Windows.", "success")
    return redirect(url_for("utilisateurs.mon_profil") + "#notifications-windows")


@bp.route("/push/categories", methods=["POST"])
@login_required
def categories():
    """Catégories envoyées en notification Windows (toutes par défaut).
    Formulaire classique (sans JavaScript) ou partiel."""
    if g.get("admin_reel") or g.get("lecture_seule"):
        message = "Indisponible en «\u00a0Voir comme\u00a0» ou «\u00a0Agir comme\u00a0»."
        # Lot 25 (matrice U2) : en partiel, un refus 403 comme les autres routes.
        if partiel.est_partiel():
            return partiel.refuser(message, 403, erreur="mode_admin")
        flash(message, "error")
        return redirect(url_for("utilisateurs.mon_profil"))
    choisies = [c for c in request.form.getlist("categories") if c in push.CATEGORIES]
    push_repo.set_categories(g.user["id"], None if len(choisies) == len(push.CATEGORIES) else choisies)
    message = "Choix des notifications Windows enregistré."
    if partiel.est_partiel():
        return partiel.repondre("partials/push_categories.html", toasts=[partiel.toast(message)],
                                push_categories=choisies, push_libelles=push.CATEGORIES)
    flash(message, "success")
    return redirect(url_for("utilisateurs.mon_profil") + "#notifications-windows")

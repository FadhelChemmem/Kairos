"""Application installable et notifications Windows (lot 24, décision du
gérant du 20/10) : manifeste, service worker à la racine, abonnements Web
Push par appareil, notification d'essai, catégories poussées. Voir
app/push.py."""
import json
import os
import threading

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


@bp.route("/push/cle")
@login_required
def cle():
    reponse = jsonify({"cle": push.cle_publique(), "abonnements": push_repo.compter(g.user["id"])})
    reponse.headers["Cache-Control"] = "no-store"
    return reponse


@bp.route("/push/etat", methods=["POST"])
@login_required
def etat():
    """Cet appareil est-il abonné pour CE compte ? (l'adresse d'abonnement
    n'est envoyée qu'en POST, jamais dans une URL)."""
    corps = request.get_json(silent=True) or {}
    endpoint = corps.get("endpoint")
    return jsonify({"abonne": bool(push.endpoint_valide(endpoint) and push_repo.est_abonne(g.user["id"], endpoint))})


@bp.route("/push/abonnement", methods=["POST"])
@login_required
def abonner():
    refus = _refus_mode()
    if refus:
        return refus
    if not push.actif():
        return jsonify({"erreur": "inactif", "message": "Notifications Windows non configurées sur le serveur."}), 409
    corps = request.get_json(silent=True) or {}
    endpoint = corps.get("endpoint")
    cles = corps.get("keys") if isinstance(corps.get("keys"), dict) else {}
    p256dh, auth = cles.get("p256dh"), cles.get("auth")
    valide = push.endpoint_valide(endpoint) and isinstance(p256dh, str) and isinstance(auth, str)
    if valide:
        try:
            valide = len(push.de_b64url(p256dh)) == 65 and 16 <= len(push.de_b64url(auth)) <= 32
        except (ValueError, TypeError):
            valide = False
    if not valide:
        return jsonify({"erreur": "invalide", "message": "Abonnement invalide."}), 400
    navigateur = (request.headers.get("User-Agent") or "")[:200]
    push_repo.enregistrer(g.user["id"], endpoint, p256dh, auth, navigateur)
    return jsonify({"ok": True, "message": "Notifications activées sur ce PC."})


@bp.route("/push/desabonnement", methods=["POST"])
@login_required
def desabonner():
    refus = _refus_mode()
    if refus:
        return refus
    corps = request.get_json(silent=True) or {}
    endpoint = corps.get("endpoint")
    if push.endpoint_valide(endpoint):
        push_repo.supprimer(g.user["id"], endpoint)
    return jsonify({"ok": True, "message": "Notifications désactivées sur ce PC."})


@bp.route("/push/essai", methods=["POST"])
@login_required
def essai():
    """« Envoyer une notification d'essai » à tous les appareils activés de
    la personne (en arrière-plan)."""
    refus = _refus_mode()
    if refus:
        return refus
    abonnements = push_repo.abonnements(g.user["id"]) if push.actif() else []
    if not abonnements:
        return jsonify({"erreur": "aucun", "message": "Aucun PC n’est activé pour vos notifications."}), 409
    message = {"titre": "Kairos", "texte": "Notification d’essai\u00a0: les notifications Windows fonctionnent.",
               "url": "/notifications", "id": 0}
    app = current_app._get_current_object()

    def _envoyer():
        with app.app_context():
            for abonnement in abonnements:
                code = push.envoyer(abonnement, message)
                if code in (404, 410):
                    push_repo.supprimer_endpoint(abonnement["endpoint"])

    if app.testing:
        _envoyer()
    else:
        threading.Thread(target=_envoyer, daemon=True).start()
    return jsonify({"ok": True, "message": "Notification d’essai envoyée."})


@bp.route("/push/categories", methods=["POST"])
@login_required
def categories():
    """Catégories envoyées en notification Windows (toutes par défaut).
    Formulaire classique (sans JavaScript) ou partiel."""
    if g.get("admin_reel") or g.get("lecture_seule"):
        flash("Indisponible en «\u00a0Voir comme\u00a0» ou «\u00a0Agir comme\u00a0».", "error")
        return redirect(url_for("utilisateurs.mon_profil"))
    choisies = [c for c in request.form.getlist("categories") if c in push.CATEGORIES]
    push_repo.set_categories(g.user["id"], None if len(choisies) == len(push.CATEGORIES) else choisies)
    message = "Choix des notifications Windows enregistré."
    if partiel.est_partiel():
        return partiel.repondre("partials/push_categories.html", toasts=[partiel.toast(message)],
                                push_categories=choisies, push_libelles=push.CATEGORIES)
    flash(message, "success")
    return redirect(url_for("utilisateurs.mon_profil") + "#notifications-windows")

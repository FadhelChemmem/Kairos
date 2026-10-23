"""Notifications : une seule liste, une cloche dans la barre du haut (voir
base.html) — pas d'emailing à cette étape (voir spec). Ouvrir une
notification la marque lue et redirige vers le projet concerné, quand il y
en a un."""
import datetime
import re

from flask import Blueprint, abort, flash, jsonify, redirect, g, render_template, request, url_for

from .. import horloge, modes_admin, partiel
from ..auth import login_required
from ..repositories import dailylog as dailylog_repo
from ..repositories import notifications as notifications_repo
from ..repositories import projets as projets_repo
from ..utils import date_fr

bp = Blueprint("notifications", __name__, url_prefix="/notifications")


NB_APERCU = 10


def grouper_par_jour(notifs: list[dict]) -> list[dict]:
    """Notifications groupées par jour (lot 13, audit UX §3.2) : « Aujourd'hui »,
    « Hier », puis la date, au fuseau de la personne. Lot 21 (revue R22) :
    les notifications étant datées de l'instant simulé en mode test,
    « Aujourd'hui » est lui aussi le jour simulé."""
    fuseau = horloge.maintenant().tzinfo
    aujourdhui = horloge.aujourdhui()
    groupes: list[dict] = []
    for n in notifs:
        cree = n.get("created_at")
        jour = (cree.astimezone(fuseau) if cree and cree.tzinfo else cree).date() if cree else aujourdhui
        if not groupes or groupes[-1]["jour"] != jour:
            if jour == aujourdhui:
                titre = "Aujourd’hui"
            elif jour == aujourdhui - datetime.timedelta(days=1):
                titre = "Hier"
            else:
                titre = date_fr(jour)
            groupes.append({"jour": jour, "titre": titre, "notifications": []})
        groupes[-1]["notifications"].append(n)
    return groupes


PAGE_NOTIFICATIONS = 50
MAX_NOTIFICATIONS = 1000


def _contexte_liste(apercu: bool = False) -> dict:
    simulees = modes_admin.voit_rappels_simules()
    if apercu:
        notifs = notifications_repo.list_notifications(g.user["id"], limit=NB_APERCU, avec_simulees=simulees)
        plus_url = premiere_nouvelle_id = None
    else:
        # Lot 25 (FL-04) : « Afficher plus » au-delà de 50 (les plus
        # anciennes n'étaient plus atteignables), par pages de 50.
        n = request.args.get("n", type=int) or PAGE_NOTIFICATIONS
        limite = min(max(PAGE_NOTIFICATIONS, n - n % PAGE_NOTIFICATIONS), MAX_NOTIFICATIONS)
        notifs = notifications_repo.list_notifications(g.user["id"], limit=limite + 1, avec_simulees=simulees)
        plus_url = (url_for("notifications.liste", n=limite + PAGE_NOTIFICATIONS)
                    if len(notifs) > limite and limite < MAX_NOTIFICATIONS else None)
        notifs = notifs[:limite]
        premiere_nouvelle_id = (notifs[limite - PAGE_NOTIFICATIONS]["id"]
                                if limite > PAGE_NOTIFICATIONS and len(notifs) > limite - PAGE_NOTIFICATIONS else None)
    nb_non_lues = notifications_repo.compter_non_lues(g.user["id"], avec_simulees=simulees)
    return {"notifications": notifs, "groupes": grouper_par_jour(notifs), "nb_non_lues": nb_non_lues,
            "plus_url": plus_url, "premiere_nouvelle_id": premiere_nouvelle_id}


def _fragment(cible: str | None, toasts=None):
    """Fragment demandé : l'aperçu de la cloche (#notifs-apercu) ou la liste
    de la page (#notifications-liste) ; le badge suit (#notifs-nb, hors cible)."""
    if cible == "#notifs-apercu":
        return partiel.repondre("partials/notifications_apercu.html", toasts=toasts, oob_nb=True, **_contexte_liste(apercu=True))
    return partiel.repondre("partials/notifications_liste.html", toasts=toasts, oob_nb=True, oob_compte=True, **_contexte_liste())


@bp.route("")
@login_required
def liste():
    if partiel.est_partiel():
        return _fragment(partiel.est_partiel())
    # Lot 24 : notification Windows cliquée — la page l'ouvre aussitôt par
    # son formulaire POST habituel (push.js) ; jamais d'écriture sur un GET.
    ouvrir_id = request.args.get("ouvrir", type=int)
    if ouvrir_id and notifications_repo.get_notification(ouvrir_id, g.user["id"]) is None:
        ouvrir_id = None
    return render_template("notifications_liste.html", ouvrir_id=ouvrir_id, **_contexte_liste())


@bp.route("/compte")
@login_required
def compte():
    """Badge de la cloche tenu à jour sans recharger (lot 13) : nombre de
    notifications non lues, en JSON."""
    reponse = jsonify({"non_lues": notifications_repo.compter_non_lues(g.user["id"], avec_simulees=modes_admin.voit_rappels_simules())})
    reponse.headers["Cache-Control"] = "no-store"
    return reponse


@bp.route("/<int:notification_id>/lue", methods=["POST"])
@login_required
def marquer_lue(notification_id: int):
    """« Marquer comme lue » sans ouvrir (lot 13, lecture optimiste dans la
    liste et dans l'aperçu de la cloche). Restreint à SA notification."""
    notif = notifications_repo.get_notification(notification_id, g.user["id"])
    if notif is None:
        if partiel.est_partiel():
            return partiel.refuser("Notification introuvable.", 404)
        abort(404)
    notifications_repo.marquer_lu(notification_id, g.user["id"])
    if partiel.est_partiel():
        return partiel.repondre("partials/notification_item.html", n={**notif, "lu": True}, oob_item=True,
                                nb_non_lues=notifications_repo.compter_non_lues(g.user["id"], avec_simulees=modes_admin.voit_rappels_simules()))
    return redirect(url_for("notifications.liste"))


@bp.route("/<int:notification_id>/ouvrir", methods=["POST"])
@login_required
def ouvrir(notification_id: int):
    """POST (audit n°2) : en GET, une simple image sur une page tierce
    pouvait marquer les notifications de la victime comme lues."""
    notif = notifications_repo.get_notification(notification_id, g.user["id"])
    if notif is None:
        abort(404)

    notifications_repo.marquer_lu(notification_id, g.user["id"])

    # Rappel ou correction du Daily log (lot 10) : directement le jour cité.
    # Lot 11 b : un rappel porte ses jours (rappel_jours, ancien et nouveau
    # format) — le premier encore à remplir, à défaut le premier cité.
    jour = None
    rappel_jours = sorted(notif.get("rappel_jours") or [])
    if rappel_jours:
        remplis = dailylog_repo.jours_renseignes(g.user["id"], rappel_jours)
        jour = next((j for j in rappel_jours if j not in remplis), rappel_jours[0])
    else:
        jour = _jour_daily_log(notif.get("message"))
    if jour is not None and g.user["role"] in ("admin", "chef_de_projet", "intervenant"):
        return redirect(url_for("dailylog.formulaire", date=jour.isoformat()))

    # Projet devenu invisible (retiré du projet, autre équipe : contre-expertise
    # rôles N1) : retour à la liste avec un message plutôt qu'une page 404.
    projet_vise = notif["post_projet_id"] or notif["tache_projet_id"] or notif.get("projet_id")
    if projet_vise and not projets_repo.user_can_view(projet_vise, g.user["id"]):
        flash("Vous n’avez plus accès à ce projet.", "error")
        return redirect(url_for("notifications.liste"))

    # Notification d'une tâche (affectation…) : la fiche du projet ouvre la
    # fenêtre de cette tâche (lot 11 b, ?tache=<id>).
    if notif.get("tache_id") and notif["tache_projet_id"] and not notif["post_projet_id"]:
        return redirect(url_for("projets.detail", projet_id=notif["tache_projet_id"], tache=notif["tache_id"]))
    # Post d'un projet (mention, commentaire…) : la fiche, sur ce post
    # (lot 13, audit rôles M8).
    # Lot 23 (décision du gérant) : toujours sur « Tout », chargé jusqu'au
    # post (?jusqua=), qui est signalé une fois à l'arrivée (filtre-fil.js).
    # Lot 25 (U2) : post supprimé — un message, et la fiche sans recherche
    # du post (elle partait pour rien et restait dans l'adresse).
    if notif.get("post_supprime"):
        flash("Ce post a été supprimé.", "warning")
        if notif["post_projet_id"]:
            return redirect(url_for("projets.detail", projet_id=notif["post_projet_id"]))
        return redirect(url_for("notifications.liste"))
    # Lot 25 (U3) : le commentaire visé est déplié et signalé (filtre-fil.js).
    vise = {"commentaire": notif["commentaire_id"]} if notif.get("commentaire_id") else {}
    if notif["post_projet_id"]:
        return redirect(url_for("projets.detail", projet_id=notif["post_projet_id"], fil="tout",
                                jusqua=notif["post_id"], **vise) + f"#post-{notif['post_id']}")
    # « Ajouté au projet », « a rejoint votre projet » (notification.projet_id,
    # migration 0019, audit rôles I8).
    projet_id = notif["tache_projet_id"] or notif.get("projet_id")
    if projet_id:
        return redirect(url_for("projets.detail", projet_id=projet_id))
    # Information d'équipe sans projet (migration 0009) : le post est dans
    # le fil de l'accueil.
    if notif.get("post_id"):
        return redirect(url_for("main.accueil", fil="tout", jusqua=notif["post_id"], **vise)
                        + f"#post-{notif['post_id']}")
    return redirect(url_for("notifications.liste"))


@bp.route("/marquer-toutes-lues", methods=["POST"])
@login_required
def marquer_toutes_lues():
    notifications_repo.marquer_toutes_lues(g.user["id"])
    if partiel.est_partiel():
        return _fragment(partiel.est_partiel(), toasts=[partiel.toast("Toutes vos notifications sont marquées comme lues.")])
    return redirect(url_for("notifications.liste"))


_RE_JOUR_DAILY_LOG = re.compile(r"^(?:Rappel DailyLog|Daily log du)\b.*?([0-9]{2})/([0-9]{2})/([0-9]{4})")


def _jour_daily_log(message: str | None):
    """Date citée par une notification de correction du Daily log (« Daily
    log du 03/10/2026 corrigé par … ») ou un ancien rappel sans
    rappel_jours (« … votre journée du 03/10/2026. »), None sinon."""
    m = _RE_JOUR_DAILY_LOG.match(message or "")
    if not m:
        return None
    try:
        return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None

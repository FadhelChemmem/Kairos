"""Vues projet : liste, détail (page façon Main.dc.html/Projet.dc.html),
et les actions sur les tâches d'un projet (création, clôture, changement
d'état)."""
import datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..auth import login_required
from ..repositories import notifications as notifications_repo
from ..repositories import posts, projets, taches, utilisateurs

bp = Blueprint("projets", __name__, url_prefix="/projets")

PHASES = ["APS", "APD", "DCE", "EXE", "DOE"]


@bp.route("")
@login_required
def liste():
    # Filtres à puces (voir projets_liste.html) : tant que le formulaire n'a
    # pas été soumis une première fois (marqueur filtres_actifs), on
    # applique les valeurs par défaut demandées par Fadhel (2026-09-19) —
    # État "En cours"+"Bloqué", Chef de projet = utilisateur connecté,
    # Phases toutes cochées (= pas de filtre). Une fois soumis, même un
    # groupe vidé volontairement (tout décoché) est respecté tel quel.
    if request.args.get("filtres_actifs"):
        etats = request.args.getlist("etat") or None
        phases = request.args.getlist("phase") or None
        chef_ids = [int(v) for v in request.args.getlist("chef_id") if v.isdigit()] or None
        lots = request.args.getlist("lot") or None
    else:
        etats = ["en_cours", "bloque"]
        phases = list(PHASES)
        chef_ids = [g.user["id"]]
        lots = None
    q = request.args.get("q") or None

    tous = projets.list_projets(
        user_id=g.user["id"], etats=etats, phases=phases, chef_ids=chef_ids, lots=lots, q=q,
    )
    utilisateurs_actifs = utilisateurs.list_actifs()
    return render_template(
        "projets_liste.html", projets=tous, q=q or "",
        etats=etats or [], phases=phases or [], chef_ids=chef_ids or [], lots=lots or [],
        phases_choices=PHASES, utilisateurs_actifs=utilisateurs_actifs,
    )


@bp.route("/nouveau", methods=["GET", "POST"])
@login_required
def creer():
    if g.user["role"] not in ("admin", "chef_de_projet"):
        flash("Seuls les chefs de projet et l'admin peuvent créer un projet.", "error")
        return redirect(url_for("projets.liste"))

    if request.method == "POST":
        nom = request.form.get("nom", "").strip()
        phase = request.form.get("phase", "EXE")
        code = request.form.get("code", "").strip()
        chef_projet_id = request.form.get("chef_projet_id", type=int) or g.user["id"]
        date_debut = request.form.get("date_debut") or None
        lots = request.form.getlist("lots")

        if not nom or not code:
            flash("Le code et le nom du projet sont obligatoires.", "error")
        else:
            try:
                projet_id = projets.create_projet(
                    code=code, nom=nom, phase=phase, chef_projet_id=chef_projet_id,
                    lots=lots, date_debut=date_debut, current_user_id=g.user["id"],
                )
            except Exception:
                flash("Impossible de créer ce projet (code déjà utilisé ?).", "error")
            else:
                flash("Projet créé.", "success")
                return redirect(url_for("projets.detail", projet_id=projet_id))

    utilisateurs_actifs = utilisateurs.list_actifs()
    code_propose = projets.propose_code(request.args.get("phase", "EXE"))
    return render_template(
        "projet_creer.html",
        utilisateurs_actifs=utilisateurs_actifs,
        code_propose=code_propose,
        # Pré-rempli avec la date du jour, modifiable — demandé par Fadhel
        # (2026-09-19), le champ apparaissait vide (jj/mm/aaaa).
        date_du_jour=datetime.date.today().isoformat(),
    )


@bp.route("/<int:projet_id>")
@login_required
def detail(projet_id: int):
    projet = projets.get_projet(projet_id)
    if projet is None:
        abort(404)

    lots = projets.list_lots(projet_id)
    intervenants = projets.list_intervenants(projet_id)
    liste_taches = taches.list_taches_projet(projet_id)
    fil = posts.list_feed_projet(projet_id, g.user["id"])
    peut_gerer = projets.user_can_manage(projet_id, g.user["id"])

    nb_taches = len(liste_taches)
    nb_en_cours = sum(1 for t in liste_taches if t["etat"] == "en_cours")
    utilisateurs_actifs = utilisateurs.list_actifs()

    return render_template(
        "projet_detail.html",
        projet=projet,
        lots=lots,
        intervenants=intervenants,
        taches=liste_taches,
        fil=fil,
        peut_gerer=peut_gerer,
        nb_taches=nb_taches,
        nb_en_cours=nb_en_cours,
        utilisateurs_actifs=utilisateurs_actifs,
    )


@bp.route("/<int:projet_id>/nouveau-post")
@login_required
def nouveau_post(projet_id: int):
    """Composeur "Nouveau post" (Tâche / Information / Requête), voir
    maquette Post-creer.dc.html. "Information" reste un aperçu non
    fonctionnel — différé à l'étape 2 (post RH hors-projet, ciblage
    équipe(s)), voir spec. `intent` pré-sélectionne le panneau, utilisé
    par les boutons rapides "+ Tâche"/"+ Information"/"+ Requête" de la
    page projet."""
    projet = projets.get_projet(projet_id)
    if projet is None:
        abort(404)

    intent = request.args.get("intent", "tache")
    if intent not in ("tache", "information", "requete"):
        intent = "tache"
    # Rebond (voir post_card.html) : le post d'origine reste référencé sur
    # le post système créé ici, qu'il s'agisse d'une tâche ou d'une requête.
    parent_post_id = request.args.get("parent_post_id", type=int)

    utilisateurs_actifs = utilisateurs.list_actifs()
    return render_template(
        "nouveau_post.html",
        projet=projet,
        intent=intent,
        parent_post_id=parent_post_id,
        utilisateurs_actifs=utilisateurs_actifs,
    )


@bp.route("/<int:projet_id>/taches", methods=["POST"])
@login_required
def creer_tache(projet_id: int):
    if not projets.user_can_manage(projet_id, g.user["id"]):
        flash("Seul le chef de projet ou un co-chef peut créer une tâche sur ce projet.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    titre = request.form.get("titre", "").strip()
    if not titre:
        flash("Le titre de la tâche est obligatoire.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    type_deadline = request.form.get("type_deadline", "rendu_client")
    date_debut = request.form.get("date_debut") or None
    date_echeance = request.form.get("date_echeance") or None
    intervenant_ids = [int(v) for v in request.form.getlist("intervenants") if v.isdigit()]
    parent_post_id = request.form.get("parent_post_id", type=int)

    tache_id = taches.create_tache(
        projet_id=projet_id,
        titre=titre,
        current_user_id=g.user["id"],
        type_deadline=type_deadline,
        date_debut=date_debut,
        date_echeance=date_echeance,
        intervenant_ids=intervenant_ids,
        parent_post_id=parent_post_id,
    )

    if intervenant_ids:
        notifications_repo.creer_pour_plusieurs(
            intervenant_ids, "projet",
            f"Vous avez été affecté à la tâche « {titre} ».",
            tache_id=tache_id, exclure_id=g.user["id"],
        )

    flash("Tâche créée.", "success")
    return redirect(url_for("projets.detail", projet_id=projet_id))


@bp.route("/<int:projet_id>/taches/<int:tache_id>/etat", methods=["POST"])
@login_required
def changer_etat_tache(projet_id: int, tache_id: int):
    """Changement d'état simple (pas de clôture) — voir cloturer_tache
    pour "Terminé", qui exige un tag de post."""
    etat = request.form.get("etat")
    etats_valides = {"en_cours", "bloque", "verifie", "arret", "abandonne"}
    if etat not in etats_valides:
        flash("État invalide.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    taches.set_etat(tache_id, etat, g.user["id"])
    flash("État de la tâche mis à jour.", "success")
    return redirect(url_for("projets.detail", projet_id=projet_id))


@bp.route("/<int:projet_id>/taches/<int:tache_id>/cloturer", methods=["POST"])
@login_required
def cloturer_tache(projet_id: int, tache_id: int):
    """Toute tâche terminée génère toujours un post automatique ; le tag
    (Envoi/Réponse/Question/Requête) est choisi ici par l'utilisateur au
    moment de la clôture (voir spec)."""
    type_code = request.form.get("type_code", "envoi")
    contenu = request.form.get("contenu") or None

    taches.close_tache(tache_id, g.user["id"], type_code, contenu)
    flash("Tâche clôturée.", "success")
    return redirect(url_for("projets.detail", projet_id=projet_id))


@bp.route("/<int:projet_id>/intervenants", methods=["POST"])
@login_required
def ajouter_intervenant(projet_id: int):
    if not projets.user_can_manage(projet_id, g.user["id"]):
        flash("Seul le chef de projet ou un co-chef peut ajouter un intervenant.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    utilisateur_id = request.form.get("utilisateur_id", type=int)
    if not utilisateur_id:
        flash("Utilisateur invalide.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    try:
        projets.add_intervenant(projet_id, utilisateur_id, g.user["id"])
    except Exception:
        # Garde-fou base de données (trg_check_projet_intervenant_role) :
        # un RH ne peut pas être intervenant. Ne devrait pas arriver via
        # l'UI normale (list_actifs exclut déjà le RH des listes), mais on
        # évite une page d'erreur brute si ça arrive quand même.
        flash("Impossible d'ajouter cet utilisateur comme intervenant (le RH ne peut pas être intervenant).", "error")
    else:
        if utilisateur_id != g.user["id"]:
            projet = projets.get_projet(projet_id)
            nom_projet = projet["nom"] if projet else ""
            notifications_repo.creer(
                utilisateur_id, "projet",
                f"Vous avez été ajouté comme intervenant sur le projet « {nom_projet} ».",
            )
        flash("Intervenant ajouté.", "success")
    return redirect(url_for("projets.detail", projet_id=projet_id))

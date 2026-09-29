"""Vues projet : liste, détail (page façon Main.dc.html/Projet.dc.html),
et les actions sur les tâches d'un projet (création, clôture, changement
d'état)."""
import datetime

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from ..auth import login_required
from ..repositories import notifications as notifications_repo
from ..repositories import posts, projets, taches, utilisateurs
from ..utils import parser_montant

bp = Blueprint("projets", __name__, url_prefix="/projets")

PHASES = ["APS", "APD", "DCE", "EXE", "DOE"]

# Tags de clôture valides (mêmes codes actifs que post_type, voir
# routes/posts.py:TYPES_VALIDES) — un type_code hors de cette liste faisait
# planter la clôture en 500 (violation de contrainte FK sur post.type_code),
# voir PROMPT_CORRECTIONS.md P0 #2.
TYPES_CLOTURE_VALIDES = {"envoi", "reponse", "question", "requete"}

# Valeurs valides de tache.type_deadline (type_deadline_enum, schema.sql) —
# une valeur hors de cette liste faisait planter creer_tache en 500
# (violation de l'ENUM Postgres), voir PROMPT_CORRECTIONS.md P1 #11.
TYPE_DEADLINE_VALIDES = {"rendu_client", "interne"}

# Codes de lot valides (table `lot`, schema.sql) — un code inconnu faisait
# échouer l'INSERT, présenté comme "code déjà utilisé ?" (audit n°2).
LOTS_VALIDES = {"CM", "GO"}

# Valeurs valides de projet.etat (projet_etat_enum, schema.sql) — même
# garde-fou que TYPE_DEADLINE_VALIDES/LOTS_VALIDES ci-dessus : une valeur
# hors de cette liste ferait échouer l'UPDATE (violation de l'ENUM
# Postgres) plutôt qu'un message clair (fenêtre "Informations", Lot 5).
ETATS_PROJET_VALIDES = {"en_cours", "bloque", "termine", "abandonne"}


def _message_erreur_intervenant(exc: Exception, action: str) -> str:
    """Message d'erreur à afficher quand l'ajout d'intervenant(s) échoue en
    base. Seul le garde-fou RH (trg_check_*_intervenant_role, qui lève
    "Un utilisateur avec le rôle RH ne peut pas être ...") justifie le
    message RH ; toute autre erreur (clé étrangère, connexion perdue...)
    était auparavant présentée à tort comme un problème de RH — elle est
    maintenant journalisée et signalée comme une erreur générique."""
    if "rôle RH" in str(exc):
        return f"Impossible {action} : un RH ne peut pas être intervenant."
    current_app.logger.exception("Échec inattendu (%s)", action)
    return f"Impossible {action} (erreur inattendue, réessayez)."


def _client_et_honoraires():
    """Champs Client et Honoraires d'un projet (migration 0010) : client
    "IPCO" par défaut s'il est laissé vide ; honoraires optionnels
    (montant à la française) — False si la saisie est invalide."""
    client = (request.form.get("client") or "").strip()[:150] or "IPCO"
    try:
        honoraires = parser_montant(request.form.get("honoraires"))
    except ValueError:
        honoraires = False
    return client, honoraires


def _parser_date_tache(date_str: str | None):
    """Parse une date du formulaire "Nouvelle tâche" (date_debut/date_echeance),
    ou None si absente/vide. Lève ValueError sur un format invalide — à la
    différence de dailylog._parser_date (qui ramène silencieusement à
    aujourd'hui), on préfère ici prévenir clairement l'utilisateur plutôt que
    d'enregistrer une date différente de celle saisie (PROMPT_CORRECTIONS.md
    P1 #11 : un format invalide plantait auparavant l'INSERT en 500 via une
    erreur Postgres, faute de validation applicative)."""
    if not date_str:
        return None
    return datetime.date.fromisoformat(date_str)


@bp.route("")
@login_required
def liste():
    # Filtres à puces (voir projets_liste.html) : tant que le formulaire n'a
    # pas été soumis une première fois (marqueur filtres_actifs), on
    # applique les valeurs par défaut demandées par Fadhel (2026-09-19) —
    # État "En cours"+"Bloqué", Chef de projet = utilisateur connecté,
    # Phases toutes cochées (= pas de filtre). Une fois soumis, même un
    # groupe vidé volontairement (tout décoché) est respecté tel quel.
    # Bug corrigé (2026-09-27, retour Fadhel) : le filtre "Chef de projet"
    # listait tout le monde (Intervenants, Clients...) via
    # utilisateurs.list_actifs() — voir list_chefs_de_projet().
    chefs_de_projet = projets.list_chefs_de_projet()
    if request.args.get("filtres_actifs"):
        etats = request.args.getlist("etat") or None
        phases = request.args.getlist("phase") or None
        chef_ids = [int(v) for v in request.args.getlist("chef_id") if v.isdigit()] or None
        lots = request.args.getlist("lot") or None
    else:
        etats = ["en_cours", "bloque"]
        phases = list(PHASES)
        # "Chef de projet = moi" seulement si l'utilisateur EST chef d'au
        # moins un projet (audit n°2) : sinon un intervenant voyait "0 projet"
        # par défaut, sans comprendre pourquoi (aucune puce cochée).
        est_chef = any(c["id"] == g.user["id"] for c in chefs_de_projet)
        chef_ids = [g.user["id"]] if est_chef else None
        lots = None
    q = request.args.get("q") or None

    tous = projets.list_projets(
        user_id=g.user["id"], etats=etats, phases=phases, chef_ids=chef_ids, lots=lots, q=q,
    )
    contexte = dict(
        projets=tous, q=q or "",
        etats=etats or [], phases=phases or [], chef_ids=chef_ids or [], lots=lots or [],
        phases_choices=PHASES, utilisateurs_actifs=chefs_de_projet,
    )
    # Rafraîchissement AJAX (retour Fadhel, 2026-09-27) : la recherche/les
    # filtres ne doivent recharger que le tableau, pas toute la page — voir
    # le script de projets_liste.html, qui appelle cette même route avec cet
    # en-tête au lieu de faire un submit() classique.
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render_template("partials/projets_tableau.html", **contexte)

    # Contexte de la fenêtre flottante "+ Nouveau projet" (retour Fadhel,
    # 2026-09-28, voir partials/projet_dialog.html) — calculé seulement
    # pour qui peut créer un projet (même règle que projets.creer) : pas la
    # peine d'interroger utilisateurs.list_actifs() pour tout le monde.
    # Note : utilisateurs_actifs ci-dessus est déjà pris par la liste des
    # CHEFS DE PROJET EXISTANTS (filtre) — le sélecteur "Chef de projet" de
    # ce formulaire de création doit lister TOUS les actifs (n'importe qui
    # de non-RH peut se voir confier un nouveau projet), d'où un nom dédié.
    if g.user["role"] in ("admin", "chef_de_projet"):
        contexte["utilisateurs_creation_projet"] = utilisateurs.list_actifs()
        contexte["phases_creation"] = PHASES
        contexte["phase_initiale_dialog"] = "EXE"
        contexte["code_propose_dialog"] = projets.propose_code("EXE")
        contexte["date_du_jour"] = datetime.date.today().isoformat()

    return render_template("projets_liste.html", **contexte)


@bp.route("/nouveau", methods=["GET", "POST"])
@login_required
def creer():
    if g.user["role"] not in ("admin", "chef_de_projet"):
        flash("Seuls les chefs de projet et l'admin peuvent créer un projet.", "error")
        return redirect(url_for("projets.liste"))

    utilisateurs_actifs = utilisateurs.list_actifs()
    saisie = {}
    if request.method == "POST":
        nom = request.form.get("nom", "").strip()
        phase = request.form.get("phase", "EXE")
        code = request.form.get("code", "").strip()
        chef_projet_id = request.form.get("chef_projet_id", type=int) or g.user["id"]
        date_debut = request.form.get("date_debut") or None
        lots = request.form.getlist("lots")
        client, honoraires = _client_et_honoraires()
        # Saisie renvoyée au formulaire en cas d'erreur (audit n°2 : tout
        # était perdu, phase revenue à EXE et code reproposé pour EXE).
        saisie = {
            "nom": nom, "code": code, "phase": phase, "chef_projet_id": chef_projet_id,
            "date_debut": date_debut or "", "lots": lots,
            "client": client, "honoraires": request.form.get("honoraires", ""),
        }

        try:
            date_debut_valide = _parser_date_tache(date_debut)
        except ValueError:
            date_debut_valide = False

        if not nom or not code:
            flash("Le code et le nom du projet sont obligatoires.", "error")
        elif date_debut_valide is False:
            flash("Date de début invalide.", "error")
        elif honoraires is False:
            flash("Honoraires invalides (un montant positif, ex. 12 500,00).", "error")
        elif any(l not in LOTS_VALIDES for l in lots):
            flash("Lot invalide.", "error")
        elif chef_projet_id not in {u["id"] for u in utilisateurs_actifs}:
            flash("Chef de projet invalide.", "error")
        elif phase not in PHASES:
            # PROMPT_CORRECTIONS.md P2 #22 : `phase` n'était pas validée —
            # une valeur hors de phase_enum (schema.sql) plantait l'INSERT
            # (violation d'ENUM Postgres), remontant jusqu'ici comme
            # "code déjà utilisé ?" alors que le code n'y était pour rien.
            flash("Phase invalide.", "error")
        else:
            try:
                # date_debut_valide (déjà calculée ci-dessus : un objet
                # datetime.date, ou None si le champ est laissé vide — jamais
                # False à ce stade, le elif au-dessus intercepte le format
                # invalide avant d'arriver ici) — pas la chaîne brute
                # date_debut, par cohérence avec le reste du fichier
                # (modifier_infos()/creer_tache() ci-dessous passent déjà la
                # valeur validée, pas la chaîne). Fonctionnellement
                # équivalent (Postgres caste déjà une chaîne ISO valide),
                # mais évite de calculer une valeur validée pour ne jamais
                # s'en servir (audit sécurité/qualité externe, 2026-09-28,
                # relecture Luna round 4).
                projet_id = projets.create_projet(
                    code=code, nom=nom, phase=phase, chef_projet_id=chef_projet_id,
                    lots=lots, date_debut=date_debut_valide, current_user_id=g.user["id"],
                    honoraires=honoraires, client=client,
                )
            except Exception as exc:
                # Seule une violation d'unicité du code justifie ce message ;
                # le reste était auparavant présenté à tort comme "code déjà
                # utilisé ?" (audit n°2).
                if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                    flash(f"Le code « {code} » est déjà utilisé par un autre projet.", "error")
                else:
                    current_app.logger.exception("Échec inattendu de création de projet")
                    flash("Impossible de créer ce projet (erreur inattendue, réessayez).", "error")
            else:
                flash("Projet créé.", "success")
                return redirect(url_for("projets.detail", projet_id=projet_id))

    phase_initiale = saisie.get("phase") or request.args.get("phase", "EXE")
    if phase_initiale not in PHASES:
        phase_initiale = "EXE"
    code_propose = saisie.get("code") or projets.propose_code(phase_initiale)
    return render_template(
        "projet_creer.html",
        utilisateurs_actifs=utilisateurs_actifs,
        code_propose=code_propose,
        phase_initiale=phase_initiale,
        phases=PHASES,
        saisie=saisie,
        # Pré-rempli avec la date du jour, modifiable — demandé par Fadhel
        # (2026-09-19), le champ apparaissait vide (jj/mm/aaaa).
        date_du_jour=datetime.date.today().isoformat(),
    )


@bp.route("/code-propose")
@login_required
def api_code_propose():
    """Petite API JSON interne (même origine, même session), même
    principe que dailylog.api_jours_remplis — PROMPT_CORRECTIONS.md P2
    #22 : le code proposé n'était calculé qu'une fois, au chargement de la
    page (voir creer() ci-dessus) — il ne se mettait jamais à jour quand on
    changeait la phase dans le formulaire. Appelée en JS par
    projet_creer.html à chaque changement de phase (voir son script)."""
    phase = request.args.get("phase", "EXE")
    if phase not in PHASES:
        return {"erreur": "Phase invalide."}, 400
    return {"code": projets.propose_code(phase)}


@bp.route("/<int:projet_id>")
@login_required
def detail(projet_id: int):
    projet = projets.get_projet(projet_id)
    if projet is None:
        abort(404)
    # Contrôle d'accès (IDOR, PROMPT_CORRECTIONS.md P0 #1) : un projet hors
    # de l'équipe/affectations de l'utilisateur ne doit pas être consultable
    # en devinant/itérant simplement son id dans l'URL.
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)

    lots = projets.list_lots(projet_id)
    intervenants = projets.list_intervenants(projet_id)
    liste_taches = taches.list_taches_projet(projet_id)
    fil = posts.list_feed_projet(projet_id, g.user["id"])
    peut_gerer = projets.user_can_manage(projet_id, g.user["id"])

    nb_taches = len(liste_taches)
    nb_en_cours = sum(1 for t in liste_taches if t["etat"] == "en_cours")
    utilisateurs_actifs = utilisateurs.list_actifs()

    # "Rejoindre ce projet" (retour Fadhel, 2026-09-28) : proposé seulement
    # à qui voit déjà le projet (garanti ici, voir plus haut) mais n'y est
    # pas encore formellement rattaché, et jamais à un compte RH (qui ne
    # peut pas être intervenant — contrainte déjà en base, voir schema.sql).
    peut_rejoindre_projet = (
        g.user["role"] != "rh" and not projets.user_est_rattache(projet_id, g.user["id"])
    )

    contexte = dict(
        projet=projet,
        lots=lots,
        intervenants=intervenants,
        taches=liste_taches,
        fil=fil,
        peut_gerer=peut_gerer,
        peut_rejoindre_projet=peut_rejoindre_projet,
        nb_taches=nb_taches,
        nb_en_cours=nb_en_cours,
        utilisateurs_actifs=utilisateurs_actifs,
        collaborateurs_recents=utilisateurs.list_collaborateurs_recents(g.user["id"]),
    )

    # Fenêtre "Informations" (retour Fadhel, 2026-09-28, Lot 5) : liste des
    # projets candidats pour "Phase liée" — seulement calculée pour qui
    # peut ouvrir cette fenêtre (chef de projet/co-chef), même principe que
    # utilisateurs_creation_projet dans liste(). Réutilise projets.search()
    # (déjà limité aux projets visibles) avec une chaîne vide : renvoie les
    # projets les plus récemment actifs plutôt que rien.
    if peut_gerer:
        contexte["projets_phase_liee"] = [
            p for p in projets.search(g.user["id"], "", limit=200) if p["id"] != projet_id
        ]

    return render_template("projet_detail.html", **contexte)


@bp.route("/<int:projet_id>/informations", methods=["POST"])
@login_required
def editer_informations(projet_id: int):
    """Fenêtre flottante "Informations" (retour Fadhel, 2026-09-28, Lot 5) :
    édite nom/état/lots/dates/phase liée. Réservée au chef de projet/co-chef
    — même autorisation que creer_tache/ajouter_intervenant (user_can_manage)."""
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    if not projets.user_can_manage(projet_id, g.user["id"]):
        flash("Seul le chef de projet ou un co-chef peut modifier les informations du projet.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    nom = request.form.get("nom", "").strip()
    etat = request.form.get("etat", "")
    lots = request.form.getlist("lots")
    date_debut = request.form.get("date_debut") or None
    date_fin = request.form.get("date_fin") or None
    phase_liee_id = request.form.get("phase_liee_id", type=int) or None
    client, honoraires = _client_et_honoraires()

    if honoraires is False:
        flash("Honoraires invalides (un montant positif, ex. 12 500,00).", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))
    if not nom:
        flash("Le nom du projet est obligatoire.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))
    if etat not in ETATS_PROJET_VALIDES:
        flash("État invalide.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))
    if any(l not in LOTS_VALIDES for l in lots):
        flash("Lot invalide.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    try:
        date_debut_valide = _parser_date_tache(date_debut)
        date_fin_valide = _parser_date_tache(date_fin)
    except ValueError:
        flash("Date invalide.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    # "Phase liée" doit rester un projet réellement visible par
    # l'utilisateur (même contrôle IDOR que pour le projet lui-même) —
    # sinon on pourrait relier un projet à un id deviné/invisible.
    if phase_liee_id is not None and not projets.user_can_view(phase_liee_id, g.user["id"]):
        flash("Projet lié invalide.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    try:
        projets.update_projet(
            projet_id, nom=nom, etat=etat, lots=lots,
            date_debut=date_debut_valide, date_fin=date_fin_valide,
            phase_liee_id=phase_liee_id, current_user_id=g.user["id"],
            honoraires=honoraires, client=client,
        )
    except Exception:
        current_app.logger.exception("Échec inattendu de modification des informations (projet %s)", projet_id)
        flash("Impossible d'enregistrer les informations (erreur inattendue, réessayez).", "error")
    else:
        flash("Informations du projet mises à jour.", "success")

    return redirect(url_for("projets.detail", projet_id=projet_id))


@bp.route("/<int:projet_id>/taches", methods=["POST"])
@login_required
def creer_tache(projet_id: int):
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    if not projets.user_can_manage(projet_id, g.user["id"]):
        flash("Seul le chef de projet ou un co-chef peut créer une tâche sur ce projet.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    titre = request.form.get("titre", "").strip()
    if not titre:
        flash("Le titre de la tâche est obligatoire.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    type_deadline = request.form.get("type_deadline", "rendu_client")
    if type_deadline not in TYPE_DEADLINE_VALIDES:
        flash("Type d'échéance invalide.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    try:
        date_debut = _parser_date_tache(request.form.get("date_debut"))
        date_echeance = _parser_date_tache(request.form.get("date_echeance"))
    except ValueError:
        flash("Date de début ou d'échéance invalide.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    # Seules des personnes qui voient déjà le projet peuvent y être
    # affectées (même règle que les mentions dans routes/posts.py) — un id
    # inexistant est ainsi écarté ici au lieu de faire échouer l'INSERT.
    intervenant_ids = [
        int(v) for v in request.form.getlist("intervenants")
        if v.isdigit() and projets.user_can_view(projet_id, int(v))
    ]

    # Un rebond doit pointer vers un post du MÊME projet (même contrôle que
    # routes/posts.py:creer) : sinon le fil de ce projet afficherait le
    # contenu, l'auteur et la tâche d'un post de n'importe quel autre
    # projet — fuite de données inter-projets (revue sécurité, audit n°2).
    parent_post_id = request.form.get("parent_post_id", type=int)
    if parent_post_id:
        parent = posts.get_post(parent_post_id)
        if parent is None or parent["projet_id"] != projet_id:
            abort(404)
        # "Reposter" (retour Fadhel, 2026-09-29, P2) : pas sur un projet
        # terminé ou abandonné (même règle que routes/posts.py:creer).
        if parent.get("projet_etat") in ("termine", "abandonne"):
            flash("Ce projet est terminé : on ne peut plus y reposter.", "error")
            return redirect(url_for("projets.detail", projet_id=projet_id))

    try:
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
    except Exception as exc:
        # Garde-fou base de données (trg_check_tache_intervenant_role, même
        # contrainte que trg_check_projet_intervenant_role côté projet — voir
        # ajouter_intervenant ci-dessous) : un RH ne peut pas être
        # intervenant sur une tâche. Ne devrait pas arriver via l'UI normale
        # (list_actifs exclut déjà le RH des listes), mais une requête
        # forgée à la main plantait auparavant en 500
        # (PROMPT_CORRECTIONS.md P1 #11).
        flash(_message_erreur_intervenant(exc, "de créer cette tâche"), "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

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
    pour "Terminé", qui exige un tag de post.

    Autorisation (PROMPT_CORRECTIONS.md P0 #2) : chef de projet, co-chef,
    OU intervenant affecté à CETTE tâche — le menu d'action de la tâche
    était affiché à tout le monde dans projet_detail.html, sans aucun
    contrôle côté serveur, ce qui permettait à n'importe quel utilisateur
    connecté de changer l'état de n'importe quelle tâche."""
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    autorise = (
        projets.user_can_manage(projet_id, g.user["id"])
        or taches.user_est_intervenant(tache_id, g.user["id"])
    )
    if not autorise:
        flash("Seul le chef de projet, un co-chef ou un intervenant de cette tâche peut changer son état.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    etat = request.form.get("etat")
    etats_valides = {"en_cours", "bloque", "verifie", "arret", "abandonne"}
    if etat not in etats_valides:
        flash("État invalide.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    if not taches.set_etat(tache_id, projet_id, etat, g.user["id"]):
        flash("Tâche introuvable sur ce projet.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    flash("État de la tâche mis à jour.", "success")
    return redirect(url_for("projets.detail", projet_id=projet_id))


@bp.route("/<int:projet_id>/taches/<int:tache_id>/titre", methods=["POST"])
@login_required
def modifier_titre_tache(projet_id: int, tache_id: int):
    """Titre d'une tâche, depuis la fenêtre ouverte par un clic sur sa ligne
    (retour Fadhel, 2026-09-29) — même autorisation que le changement
    d'état. Le changement apparaît dans le fil (taches.set_titre)."""
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    autorise = (
        projets.user_can_manage(projet_id, g.user["id"])
        or taches.user_est_intervenant(tache_id, g.user["id"])
    )
    if not autorise:
        flash("Seul le chef de projet, un co-chef ou un intervenant de cette tâche peut la renommer.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))
    titre = request.form.get("titre", "").strip()
    if not titre or len(titre) > 255:
        flash("Titre invalide.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))
    if not taches.set_titre(tache_id, projet_id, titre, g.user["id"]):
        flash("Tâche introuvable sur ce projet.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))
    flash("Tâche renommée.", "success")
    return redirect(url_for("projets.detail", projet_id=projet_id))


@bp.route("/<int:projet_id>/taches/<int:tache_id>/cloturer", methods=["POST"])
@login_required
def cloturer_tache(projet_id: int, tache_id: int):
    """Toute tâche terminée génère toujours un post automatique ; le tag
    (Envoi/Réponse/Question/Requête) est choisi ici par l'utilisateur au
    moment de la clôture (voir spec).

    Même autorisation que changer_etat_tache (PROMPT_CORRECTIONS.md P0 #2),
    plus une validation du tag choisi (un type_code invalide faisait
    planter la clôture en 500 via une violation de contrainte FK)."""
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    autorise = (
        projets.user_can_manage(projet_id, g.user["id"])
        or taches.user_est_intervenant(tache_id, g.user["id"])
    )
    if not autorise:
        flash("Seul le chef de projet, un co-chef ou un intervenant de cette tâche peut la clôturer.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    type_code = request.form.get("type_code", "envoi")
    if type_code not in TYPES_CLOTURE_VALIDES:
        flash("Tag de clôture invalide.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))
    contenu = request.form.get("contenu") or None

    if taches.close_tache(tache_id, projet_id, g.user["id"], type_code, contenu) is None:
        flash("Impossible de clôturer cette tâche (introuvable sur ce projet, ou déjà clôturée).", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    flash("Tâche clôturée.", "success")
    return redirect(url_for("projets.detail", projet_id=projet_id))


@bp.route("/<int:projet_id>/intervenants", methods=["POST"])
@login_required
def ajouter_intervenant(projet_id: int):
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    if not projets.user_can_manage(projet_id, g.user["id"]):
        flash("Seul le chef de projet ou un co-chef peut ajouter un intervenant.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    utilisateur_id = request.form.get("utilisateur_id", type=int)
    if not utilisateur_id:
        flash("Utilisateur invalide.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    # Un compte désactivé (actif=false) ne doit jamais pouvoir devenir
    # intervenant — la liste utilisée par le formulaire (list_actifs) ne
    # propose que des comptes actifs, mais rien ne vérifiait ce point côté
    # serveur : une requête forgée avec l'id d'un compte désactivé passait
    # jusqu'ici sans contrôle (seul le garde-fou RH,
    # trg_check_projet_intervenant_role, était vérifié) (audit sécurité/
    # qualité externe, 2026-09-28, item P1-3).
    candidat = utilisateurs.get_utilisateur(utilisateur_id)
    if candidat is None or not candidat["actif"]:
        flash("Utilisateur invalide.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    try:
        projets.add_intervenant(projet_id, utilisateur_id, g.user["id"])
    except Exception as exc:
        # Garde-fou base de données (trg_check_projet_intervenant_role) :
        # un RH ne peut pas être intervenant. Ne devrait pas arriver via
        # l'UI normale (list_actifs exclut déjà le RH des listes), mais on
        # évite une page d'erreur brute si ça arrive quand même.
        flash(_message_erreur_intervenant(exc, "d'ajouter cet intervenant"), "error")
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


@bp.route("/<int:projet_id>/rejoindre", methods=["POST"])
@login_required
def rejoindre(projet_id: int):
    """Bouton « + Rejoindre ce projet » (retour Fadhel, 2026-09-28) :
    ajout immédiat de l'utilisateur connecté comme intervenant, sans
    validation d'un chef/co-chef — à la différence de ajouter_intervenant
    ci-dessus (qui ajoute QUELQU'UN D'AUTRE et exige user_can_manage), ici
    on ne s'ajoute que SOI-MÊME, donc aucune notification n'est nécessaire."""
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    if g.user["role"] == "rh":
        flash("Un RH ne peut pas être intervenant sur un projet.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))
    if projets.user_est_rattache(projet_id, g.user["id"]):
        flash("Vous êtes déjà rattaché à ce projet.", "success")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    # Un chef de projet rejoint comme co-chef (retour Fadhel, 2026-09-29,
    # PR8) ; les autres comme intervenant.
    comme_co_chef = g.user["role"] == "chef_de_projet"
    try:
        if comme_co_chef:
            projets.add_co_chef(projet_id, g.user["id"], g.user["id"])
        else:
            projets.add_intervenant(projet_id, g.user["id"], g.user["id"])
    except Exception as exc:
        flash(_message_erreur_intervenant(exc, "de rejoindre ce projet"), "error")
    else:
        flash("Vous avez rejoint le projet comme co-chef." if comme_co_chef else "Vous avez rejoint le projet.", "success")
    return redirect(url_for("projets.detail", projet_id=projet_id))


@bp.route("/<int:projet_id>/taches/<int:tache_id>/rejoindre", methods=["POST"])
@login_required
def rejoindre_tache(projet_id: int, tache_id: int):
    """Bouton « rejoindre cette tâche » (retour Fadhel, 2026-09-28),
    révélé au survol de la ligne — même principe que rejoindre() ci-dessus
    mais au niveau tâche : ajout immédiat de l'utilisateur connecté comme
    intervenant de la tâche, sans validation."""
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    if g.user["role"] == "rh":
        flash("Un RH ne peut pas être intervenant sur une tâche.", "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))
    if taches.user_est_intervenant(tache_id, g.user["id"]):
        flash("Vous êtes déjà intervenant sur cette tâche.", "success")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    try:
        ok = taches.add_intervenant(tache_id, projet_id, g.user["id"], g.user["id"])
    except Exception as exc:
        flash(_message_erreur_intervenant(exc, "de rejoindre cette tâche"), "error")
        return redirect(url_for("projets.detail", projet_id=projet_id))

    if not ok:
        flash("Tâche introuvable sur ce projet.", "error")
    else:
        flash("Vous avez rejoint la tâche.", "success")
    return redirect(url_for("projets.detail", projet_id=projet_id))

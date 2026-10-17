"""Vues projet : liste, détail (page façon Main.dc.html/Projet.dc.html),
et les actions sur les tâches d'un projet (création, clôture, changement
d'état)."""
import datetime
import re
from urllib.parse import quote

from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, url_for

from ..auth import login_required
from ..repositories import notifications as notifications_repo
from ..repositories import posts, projets, taches, utilisateurs
from .. import fil as film
from .. import horloge, partiel
from .. import validation as v
from ..utils import parser_montant, post_type_style, tache_etat_style

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
# Lot 13 (décision 1) : la fenêtre ne propose plus « Bloqué » — En cours et
# Bloqué découlent des tâches ; « bloque » reçu (ancien onglet) vaut En cours.
ETATS_PROJET_VALIDES = {"en_cours", "bloque", "termine", "abandonne"}


MESSAGE_PROJET_CLOS = (
    "Ce projet est clos (terminé ou abandonné)\u00a0: plus aucune intervention n’est "
    "possible tant que son chef ou un co-chef ne change pas son état."
)


def _refus_si_clos(projet_id: int):
    """Projet terminé ou abandonné (décision Fadhel, lot 7) : toute
    intervention est refusée, pour tout le monde — chef et co-chefs compris
    —, sauf la fenêtre "Informations" qui permet de le rouvrir. Renvoie la
    redirection à retourner, ou None si le projet est ouvert."""
    projet = projets.get_projet(projet_id)
    if projet is not None and projet["etat"] in projets.ETATS_CLOS:
        return _refus(MESSAGE_PROJET_CLOS, 409, projet_id)
    return None


def _refus(message: str, statut: int, projet_id: int, tache_id: int | None = None, *, champs: dict | None = None,
           vers_tache: bool = False):
    """Refus d'une action de la fiche projet : JSON {message} pour une
    requête partielle (lot 13 : l'état optimiste est annulé, le message
    affiché en toast ou sous les champs `champs`), message flash et retour
    à la fiche sinon (fenêtre de la tâche rouverte si `vers_tache`)."""
    if partiel.est_partiel():
        return partiel.refuser(message, statut, champs=champs)
    flash(message, "error")
    if vers_tache and tache_id:
        return _vers_tache(projet_id, tache_id)
    return redirect(url_for("projets.detail", projet_id=projet_id))


def _code_nom(projet: dict | None) -> str:
    """« 26089X_Résidence Les Palmiers » : nomme le projet dans une
    notification (lot 13, audit rôles M10 : homonymes fréquents)."""
    projet = projet or {}
    return f"{projet.get('code') or ''}_{projet.get('nom') or ''}".strip("_")


def _vers_tache(projet_id: int, tache_id: int):
    """Retour à la fiche, fenêtre de la tâche rouverte (?tache=<id>)."""
    return redirect(url_for("projets.detail", projet_id=projet_id, tache=tache_id))


def _chefs_possibles() -> list[dict]:
    """Candidats chef de projet (création et changement, décision 3 du lot
    13) : comptes actifs chef de projet ou Admin."""
    return [u for u in utilisateurs.list_actifs() if u.get("role") in projets.ROLES_CHEF_POSSIBLES]


def _refus_rh():
    """Le RH n'a pas accès aux projets (décision Fadhel, lot 7)."""
    if g.user["role"] == "rh":
        flash("Le RH n’a pas accès aux projets.", "error")
        return redirect(url_for("main.accueil"))
    return None


def _message_erreur_intervenant(exc: Exception, action: str) -> str:
    """Message d'erreur à afficher quand l'ajout d'intervenant(s) échoue en
    base. Seul le garde-fou RH (trg_check_*_intervenant_role, qui lève
    "Un utilisateur avec le rôle RH ne peut pas être ...") justifie le
    message RH ; toute autre erreur (clé étrangère, connexion perdue...)
    était auparavant présentée à tort comme un problème de RH — elle est
    maintenant journalisée et signalée comme une erreur générique."""
    if "rôle RH" in str(exc):
        return f"Impossible {action}\u00a0: un RH ne peut pas être intervenant."
    if "rôle Client" in str(exc):
        return f"Impossible {action}\u00a0: un client ne peut pas être intervenant."
    current_app.logger.exception("Échec inattendu (%s)", action)
    return f"Impossible {action} (erreur inattendue, réessayez)."


def _client_et_honoraires():
    """Champs Client et Honoraires d'un projet (migration 0010) : client
    "IPCO" par défaut s'il est laissé vide ; honoraires optionnels
    (montant à la française) — False si la saisie est invalide."""
    # Plus de troncature silencieuse (lot 8) : une saisie trop longue est
    # refusée avec un message (voir les routes).
    client = (request.form.get("client") or "").strip() or "IPCO"
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


# Taille d'une page de "Tous les projets" (lot 11 : pagination au lieu de
# la troncature silencieuse à 200 lignes).
PROJETS_PAR_PAGE = 50


def _filtres_liste() -> dict:
    """Filtres de "Tous les projets" (liste, rafraîchissement AJAX et
    export Excel utilisent exactement les mêmes)."""
    # Filtres à puces (voir projets_liste.html) : tant que le formulaire n'a
    # pas été soumis une première fois (marqueur filtres_actifs), on
    # applique les valeurs par défaut demandées par Fadhel (2026-09-19) —
    # État "En cours"+"Bloqué", Chef de projet = utilisateur connecté,
    # Phases toutes cochées (= pas de filtre). Une fois soumis, même un
    # groupe vidé volontairement (tout décoché) est respecté tel quel.
    # Bug corrigé (2026-09-27, retour Fadhel) : le filtre "Chef de projet"
    # listait tout le monde (Intervenants, Clients...) via
    # utilisateurs.list_actifs() — voir list_chefs_de_projet().
    chefs_de_projet = projets.list_chefs_de_projet(g.user["id"])
    if request.args.get("filtres_actifs"):
        etats = request.args.getlist("etat") or None
        phases = request.args.getlist("phase") or None
        chef_ids = v.ids_entiers(request.args.getlist("chef_id")) or None
        # Filtre lots à trois états par lot (retour Fadhel, 2026-10-01) :
        # "contient" (le projet A ce lot, même parmi d'autres) et "="
        # (le projet n'a QUE ce lot) — deux listes distinctes. Voir
        # projets_liste.html (data-chip-tristate) et list_projets.
        lots_contient = request.args.getlist("lot_contient") or None
        lots_egal = request.args.getlist("lot_egal") or None
    else:
        etats = ["en_cours", "bloque"]
        phases = list(PHASES)
        # "Chef de projet = moi" seulement si l'utilisateur EST chef d'au
        # moins un projet (audit n°2) : sinon un intervenant voyait "0 projet"
        # par défaut, sans comprendre pourquoi (aucune puce cochée).
        est_chef = any(c["id"] == g.user["id"] for c in chefs_de_projet)
        chef_ids = [g.user["id"]] if est_chef else None
        lots_contient = None
        lots_egal = None
    q = (request.args.get("q") or "").strip() or None
    # Recherche texte (lot 11) : elle porte sur tous les projets visibles —
    # le filtre par défaut « Chef de projet = moi » est ignoré (et signalé
    # à l'écran) ; « Villa Louison » d'un autre chef restait introuvable.
    chef_ignore = bool(q) and chef_ids == [g.user["id"]]
    if chef_ignore:
        chef_ids = None
    return dict(etats=etats, phases=phases, chef_ids=chef_ids, lots_contient=lots_contient,
                lots_egal=lots_egal, q=q, chefs_de_projet=chefs_de_projet, chef_ignore=chef_ignore)


def _criteres(f: dict) -> dict:
    return {k: f[k] for k in ("etats", "phases", "chef_ids", "lots_contient", "lots_egal", "q")}


@bp.route("")
@login_required
def liste():
    refus = _refus_rh()
    if refus:
        return refus
    f = _filtres_liste()
    total = projets.compter_projets(user_id=g.user["id"], **_criteres(f))
    nb_pages = max(1, -(-total // PROJETS_PAR_PAGE))
    page = min(max(1, request.args.get("page", 1, type=int) or 1), nb_pages)
    tous = projets.list_projets(user_id=g.user["id"], limit=PROJETS_PAR_PAGE,
                                offset=(page - 1) * PROJETS_PAR_PAGE, **_criteres(f))

    # Liens de pagination : les filtres EFFECTIFS (valeurs par défaut
    # comprises) — lot 13 : l'adresse d'une page décrit tout l'état de la
    # liste, pour que Retour y retrouve les mêmes puces.
    chef_ids_affiches = [g.user["id"]] if f["chef_ignore"] else (f["chef_ids"] or [])
    filtres_url = {"filtres_actifs": 1, "etat": f["etats"] or [], "phase": f["phases"] or [],
                   "chef_id": chef_ids_affiches, "lot_contient": f["lots_contient"] or [],
                   "lot_egal": f["lots_egal"] or []}
    if f["q"]:
        filtres_url["q"] = f["q"]

    def url_page(n):
        return url_for("projets.liste", **filtres_url, page=n)

    contexte = dict(
        projets=tous, q=f["q"] or "", total=total, page=page, nb_pages=nb_pages,
        premier=(page - 1) * PROJETS_PAR_PAGE + 1 if tous else 0,
        dernier=(page - 1) * PROJETS_PAR_PAGE + len(tous),
        url_precedente=url_page(page - 1) if page > 1 else None,
        url_suivante=url_page(page + 1) if page < nb_pages else None,
        chef_ignore=f["chef_ignore"],
        etats=f["etats"] or [], phases=f["phases"] or [], chef_ids=f["chef_ids"] or [],
        lots_contient=f["lots_contient"] or [], lots_egal=f["lots_egal"] or [],
        phases_choices=PHASES, utilisateurs_actifs=f["chefs_de_projet"],
    )
    # Recherche ignorant « Chef = moi » : les puces du filtre gardent le
    # choix de la personne (il revient dès que la recherche est vidée).
    if f["chef_ignore"]:
        contexte["chef_ids"] = [g.user["id"]]
    # Export aux filtres affichés : toute la chaîne de requête (plusieurs
    # valeurs par filtre), sans la page.
    args_export = [(k, v_) for k, v_ in request.args.items(multi=True) if k != "page"]
    contexte["export_url"] = url_for("projets.export_excel") + (
        "?" + "&".join(f"{quote(k)}={quote(v_)}" for k, v_ in args_export) if args_export else "")
    # Rafraîchissement partiel (lot 13, socle : filtres automatiques,
    # pagination, Retour) : les résultats seuls, le statut et le lien
    # d'export hors cible. X-Requested-With : ancien appel (compatibilité).
    if partiel.est_partiel():
        return partiel.repondre("partials/projets_tableau.html", partiel=True, **contexte)
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
        # Lot 13 (décision 3, audit rôles I4 / M14) : chef de projet ou
        # Admin actif seulement, même sélecteur à recherche qu'Informations.
        contexte["utilisateurs_creation_projet"] = _chefs_possibles()
        contexte["phases_creation"] = PHASES
        contexte["phase_initiale_dialog"] = "EXE"
        contexte["code_propose_dialog"] = projets.propose_code("EXE")
        contexte["date_du_jour"] = horloge.date_ecriture().isoformat()
        # « Phase liée » dès la création (retour Fadhel, lot 7) : mêmes
        # candidats que dans la fenêtre Informations (projets visibles).
        # Lot 13 (a11y-perf M11) : candidats chargés à la demande
        # (api_phase_liee_candidats) au lieu de 200 <option> dans la page.
        contexte["projets_phase_liee"] = []

    return render_template("projets_liste.html", **contexte)


@bp.route("/export.xlsx")
@login_required
def export_excel():
    """« Télécharger en Excel » (retour Fadhel, 2026-09-29) : la liste
    affichée, avec les mêmes filtres et le même ordre, en .xlsx."""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    refus = _refus_rh()
    if refus:
        return refus
    # Toutes les lignes (lot 11 : plus de plafond), mêmes filtres et même
    # ordre que la liste affichée.
    lignes = projets.list_projets(user_id=g.user["id"], limit=None, **_criteres(_filtres_liste()))
    classeur = Workbook()
    feuille = classeur.active
    feuille.title = "Projets"
    entetes = ["Code", "Nom", "Phase", "Lots", "Chef de projet", "Client", "Honoraires",
               "Heures intervenants", "Heures chef de projet", "Prochain rendu", "Tâche du rendu",
               "Prochaine échéance", "Tâche de l’échéance", "État", "Début"]
    feuille.append(entetes)
    for cellule in feuille[1]:
        cellule.font = Font(bold=True)
    etat_libelle = {"en_cours": "En cours", "bloque": "Bloqué", "termine": "Terminé", "abandonne": "Abandonné"}

    def nombre(v):
        return float(v) if v is not None else None

    def texte(v):
        return "" if v is None else str(v)

    for p in lignes:
        feuille.append([
            texte(p["code"]), texte(p["nom"]), p["phase"], texte(p.get("lots")),
            texte(f"{p['chef_prenom']} {p['chef_nom']}"), texte(p.get("client")), nombre(p.get("honoraires")),
            nombre(p.get("heures_intervenant")) or 0, nombre(p.get("heures_chef")) or 0,
            p.get("prochain_rendu"), texte(p.get("prochain_rendu_titre")),
            p.get("prochaine_deadline"), texte(p.get("prochaine_deadline_titre")),
            etat_libelle.get(p["etat"], p["etat"]), p.get("date_debut"),
        ])
        # Jamais de formule : un texte saisi qui commence par "=" (nom de
        # projet, client…) reste du texte dans Excel (injection de formule).
        for cellule in feuille[feuille.max_row]:
            if isinstance(cellule.value, str) and cellule.value.startswith("="):
                cellule.data_type = "s"
    for i, largeur in enumerate([10, 40, 8, 10, 24, 18, 14, 12, 12, 14, 36, 14, 36, 11, 12], start=1):
        feuille.column_dimensions[get_column_letter(i)].width = largeur
    for colonne in ("J", "L", "O"):
        for cellule in feuille[colonne][1:]:
            cellule.number_format = "DD/MM/YYYY"
    feuille.freeze_panes = "A2"

    tampon = io.BytesIO()
    classeur.save(tampon)
    nom = f"projets-kairos-{horloge.aujourdhui().isoformat()}.xlsx"
    return tampon.getvalue(), 200, {
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": f'attachment; filename="{nom}"',
    }


@bp.route("/nouveau", methods=["GET", "POST"])
@login_required
def creer():
    if g.user["role"] not in ("admin", "chef_de_projet"):
        flash("Seuls les chefs de projet et l’admin peuvent créer un projet.", "error")
        return redirect(url_for("projets.liste"))

    # Chef de projet (lot 13, décision 3) : compte actif, chef de projet ou
    # Admin — la même règle que pour changer de chef (trigger 0017).
    utilisateurs_actifs = _chefs_possibles()
    saisie = {}
    erreurs = {}
    if request.method == "POST":
        nom = request.form.get("nom", "").strip()
        phase = request.form.get("phase", "EXE")
        code = request.form.get("code", "").strip()
        chef_projet_id = request.form.get("chef_projet_id", type=int) or g.user["id"]
        date_debut = request.form.get("date_debut") or None
        lots = request.form.getlist("lots")
        client, honoraires = _client_et_honoraires()
        phase_liee_id = request.form.get("phase_liee_id", type=int) or None
        # Saisie renvoyée au formulaire en cas d'erreur (audit n°2 : tout
        # était perdu, phase revenue à EXE et code reproposé pour EXE).
        saisie = {
            "nom": nom, "code": code, "phase": phase, "chef_projet_id": chef_projet_id,
            "date_debut": date_debut or "", "lots": lots,
            "client": client, "honoraires": request.form.get("honoraires", ""),
            "phase_liee_id": phase_liee_id,
        }

        try:
            date_debut_valide = _parser_date_tache(date_debut)
        except ValueError:
            date_debut_valide = False

        champ, erreur = None, None
        if not nom or not code:
            champ, erreur = ("nom" if not nom else "code"), "Le code et le nom du projet sont obligatoires."
        elif phase in PHASES and not projets.code_valide(code, phase):
            champ, erreur = "code", (
                f"Code invalide\u00a0: l’année sur 2 chiffres, un numéro d’au moins 3 chiffres, puis la lettre "
                f"de la phase {phase} ({projets.LETTRE_PHASE[phase]}) — ex. 26001{projets.LETTRE_PHASE[phase]}."
            )
        elif message := v.trop_long(nom, v.MAX_NOM_PROJET, "Nom du projet"):
            champ, erreur = "nom", message
        elif message := v.trop_long(client, v.MAX_CLIENT, "Client"):
            champ, erreur = "client", message
        elif message := v.date_hors_bornes(date_debut_valide or None, "Date de début"):
            champ, erreur = "date_debut", message
        elif date_debut_valide is False:
            champ, erreur = "date_debut", "Date de début invalide."
        elif honoraires is False:
            champ, erreur = "honoraires", "Honoraires invalides (un montant positif, ex. 12 500,00)."
        elif any(l not in LOTS_VALIDES for l in lots):
            champ, erreur = "lots", "Lot invalide."
        elif not lots:
            # Lot 13 (audit rôles M12) : un projet a au moins un lot.
            champ, erreur = "lots", "Choisissez au moins un lot (CM ou GO)."
        elif chef_projet_id not in {u["id"] for u in utilisateurs_actifs}:
            champ, erreur = "chef_projet_id", projets.MESSAGE_CHEF_INVALIDE
        elif phase_liee_id is not None and not projets.user_can_view(phase_liee_id, g.user["id"]):
            # Même contrôle IDOR que dans la fenêtre Informations.
            champ, erreur = "phase_liee_id", "Projet lié invalide."
        elif phase not in PHASES:
            # PROMPT_CORRECTIONS.md P2 #22 : `phase` n'était pas validée.
            champ, erreur = "phase", "Phase invalide."
        else:
            try:
                projet_id = projets.create_projet(
                    code=code, nom=nom, phase=phase, chef_projet_id=chef_projet_id,
                    lots=lots, date_debut=date_debut_valide, current_user_id=g.user["id"],
                    honoraires=honoraires, client=client, phase_liee_id=phase_liee_id,
                )
            except Exception as exc:
                # Seule une violation d'unicité du code justifie ce message
                # (audit n°2).
                if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                    champ, erreur = "code", f"Le code «\u00a0{code}\u00a0» est déjà utilisé par un autre projet."
                else:
                    current_app.logger.exception("Échec inattendu de création de projet")
                    erreur = "Impossible de créer ce projet (erreur inattendue, réessayez)."
            else:
                # Le créateur qui confie le projet à un autre chef en devient
                # co-chef (create_projet) ; s'il ne le voit quand même pas, pas
                # de page introuvable (lot 13, audit rôles I5).
                if not projets.user_can_view(projet_id, g.user["id"]):
                    flash(f"Projet {code} créé et confié à son chef de projet\u00a0: il n’est pas visible "
                          "depuis votre compte.", "success")
                    return redirect(url_for("projets.liste"))
                if chef_projet_id != g.user["id"] and g.user["role"] != "admin":
                    flash("Projet créé\u00a0: vous en êtes co-chef.", "success")
                else:
                    flash("Projet créé.", "success")
                # Changement de contexte voulu : vraie navigation vers la
                # fiche (en partiel : 204 + X-Kairos-Redirection).
                return redirect(url_for("projets.detail", projet_id=projet_id))
        # Lot 13 (audit a11y I5) : l'erreur est reliée à son champ — dans la
        # fenêtre « Nouveau projet » (422, la saisie reste), ou sur la page
        # complète (aria-invalid, message sous le champ, focus dessus).
        if partiel.est_partiel():
            return partiel.refuser(erreur, 422, champs={champ: erreur} if champ else None)
        if champ:
            erreurs[champ] = erreur
        else:
            flash(erreur, "error")

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
        projets_phase_liee=_phase_liee_choisie(saisie.get("phase_liee_id")),
        erreurs=erreurs,
        # Pré-rempli avec la date du jour, modifiable — demandé par Fadhel
        # (2026-09-19), le champ apparaissait vide (jj/mm/aaaa).
        # Jamais après la vraie date (date simulée future : contre-expertise
        # temps N6, décision 5).
        date_du_jour=horloge.date_ecriture().isoformat(),
    )


@bp.route("/code-propose")
@login_required
def api_code_propose():
    """Petite API JSON interne (même origine, même session), même
    principe que dailylog.api_jours_remplis — PROMPT_CORRECTIONS.md P2
    #22 : le code proposé n'était calculé qu'une fois, au chargement de la
    page (voir creer() ci-dessus) — il ne se mettait jamais à jour quand on
    changeait la phase dans le formulaire. Appelée en JS par
    projet_creer.html à chaque changement de phase (voir son script).
    Lot 13 (audit rôles M5) : mêmes rôles que la création (le prochain
    numéro d'affaire n'a pas à être lu par un client ou le RH)."""
    if g.user["role"] not in ("admin", "chef_de_projet"):
        return {"erreur": "Accès réservé."}, 403
    phase = request.args.get("phase", "EXE")
    if phase not in PHASES:
        return {"erreur": "Phase invalide."}, 400
    # Phase liée choisie (lot 8) : même numéro que ce projet — seulement
    # s'il est visible (pas de fuite du code d'un projet invisible).
    code_lie = None
    phase_liee_id = request.args.get("phase_liee_id", type=int)
    if phase_liee_id and projets.user_can_view(phase_liee_id, g.user["id"]):
        lie = projets.get_projet(phase_liee_id)
        code_lie = lie["code"] if lie else None
    return {"code": projets.propose_code(phase, phase_liee_code=code_lie)}


NB_CANDIDATS_PHASE_LIEE = 20


@bp.route("/phase-liee/candidats")
@login_required
def api_phase_liee_candidats():
    """Candidats « Phase liée » chargés à la demande par le champ de
    recherche (data-search-url, search-combobox.js) au lieu de 200 <option>
    dans chaque page (audit a11y-perf M11). Mêmes droits que les listes
    qu'elle remplace : création d'un projet (chef de projet, Admin) ou
    fenêtre Informations du projet `exclure` (user_can_manage) ; projets
    visibles seulement (projets.search), le projet lui-même exclu."""
    exclure = request.args.get("exclure", type=int)
    if g.user["role"] not in ("admin", "chef_de_projet") and not (
            exclure and projets.user_can_manage(exclure, g.user["id"])):
        return {"erreur": "interdit", "message": "Accès réservé."}, 403
    q = (request.args.get("q") or "").strip()[:200]
    trouves = projets.search(g.user["id"], q, limit=NB_CANDIDATS_PHASE_LIEE + 1)
    resultats = [{"id": p["id"], "libelle": f"{p['code']}_{p['nom']}"} for p in trouves if p["id"] != exclure]
    reponse = jsonify({"resultats": resultats[:NB_CANDIDATS_PHASE_LIEE]})
    reponse.headers["Cache-Control"] = "no-store"
    return reponse


def _phase_liee_choisie(phase_liee_id: int | None) -> list[dict]:
    """Seule option rendue avec la page : la phase liée déjà choisie (les
    autres sont chargées à la demande, api_phase_liee_candidats)."""
    if not phase_liee_id or not projets.user_can_view(phase_liee_id, g.user["id"]):
        return []
    lie = projets.get_projet(phase_liee_id)
    return [lie] if lie else []


def _contexte_fil(projet_id: int, fil_limite: int = film.TAILLE_PAGE) -> dict:
    """Fil de la fiche (lot 14, revue produit P1-3) : catégorie (adresse, ou
    page d'où part l'action en partiel), page à partir du curseur `avant`,
    évènements automatiques regroupés, adresse de la page suivante."""
    categorie = film.categorie_demandee()
    fil_limite = film.taille_jusqua(
        fil_limite, lambda post_id: posts.rang_dans_fil_projet(projet_id, g.user["id"], categorie, post_id))
    lus = posts.list_feed_projet(projet_id, g.user["id"], limit=fil_limite + 1, categorie=categorie,
                                 avant=film.curseur_demande())
    fil, curseur = film.page(lus, fil_limite)
    return dict(fil=fil, fil_entrees=film.regrouper(fil), fil_categorie=categorie,
                fil_suite_id="fil-suite", fil_suite_cible="#fil-posts",
                fil_suite_url=(url_for("projets.detail", projet_id=projet_id, fil=categorie, avant=curseur)
                               if curseur else None))


def _contexte_fiche(projet: dict, *, fil_limite: int = film.TAILLE_PAGE) -> dict:
    """Contexte de la fiche projet : page complète (detail) et fragments des
    réponses partielles (lot 13, _maj_fiche) — mêmes données, mêmes droits."""
    projet_id = projet["id"]
    lots = projets.list_lots(projet_id)
    intervenants = projets.list_intervenants(projet_id)
    liste_taches = taches.list_taches_projet(projet_id)
    peut_gerer = projets.user_can_manage(projet_id, g.user["id"])

    nb_taches = len(liste_taches)
    nb_en_cours = sum(1 for t in liste_taches if t["etat"] == "en_cours")
    utilisateurs_actifs = utilisateurs.list_actifs()

    # "Rejoindre ce projet" (retour Fadhel, 2026-09-28) : proposé seulement
    # à qui voit déjà le projet mais n'y est pas encore formellement
    # rattaché ; ni RH ni Client (migration 0011), jamais sur un projet clos.
    projet_clos = projet["etat"] in projets.ETATS_CLOS
    # L'Admin gère déjà tous les projets : jamais « Rejoindre » (lot 13, M11).
    peut_rejoindre_projet = (
        g.user["role"] not in ("rh", "client", "admin") and not projet_clos
        and not projets.user_est_rattache(projet_id, g.user["id"])
    )

    contexte = dict(
        projet=projet,
        lots=lots,
        intervenants=intervenants,
        taches=liste_taches,
        **_contexte_fil(projet_id, fil_limite),
        peut_gerer=peut_gerer,
        etats_reserves=taches.ETATS_RESERVES_GESTION,
        peut_rejoindre_projet=peut_rejoindre_projet,
        projet_clos=projet_clos,
        nb_taches=nb_taches,
        nb_en_cours=nb_en_cours,
        utilisateurs_actifs=utilisateurs_actifs,
        utilisateurs_affectables=[u for u in utilisateurs_actifs if u.get("role") != "client"],
        collaborateurs_recents=utilisateurs.list_collaborateurs_recents(g.user["id"]),
        # Intervenants proposés pour une nouvelle tâche et personnes
        # mentionnables : ceux qui voient le projet (lot 13 ; lot 16 pour les
        # mentions, proposées à tous).
        ids_voient_projet=projets.ids_utilisateurs_voyant(projet_id),
    )

    # Fenêtre "Informations" (retour Fadhel, 2026-09-28, Lot 5) : projets
    # candidats pour "Phase liée", seulement pour qui peut l'ouvrir.
    if peut_gerer:
        # Lot 13 (a11y-perf M11) : seule la phase liée choisie est rendue,
        # les autres candidats sont chargés à la demande.
        contexte["projets_phase_liee"] = _phase_liee_choisie(projet.get("phase_liee_id"))
        # Changement de chef (lot 11 b) : comptes actifs chef de projet ou
        # Admin ; le chef actuel reste le choix affiché même s'il n'en fait
        # plus partie (compte désactivé). Projet clos : Admin seulement.
        chefs = [u for u in utilisateurs_actifs if u.get("role") in projets.ROLES_CHEF_POSSIBLES]
        # « Retirer » de la carte Intervenants (lot 13, décision 4) : seulement
        # les personnes qui ont un rattachement retirable.
        contexte["intervenants_retirables"] = set() if projet_clos else projets.ids_retirables(projet_id)
        if not any(u["id"] == projet["chef_projet_id"] for u in chefs):
            chef_actuel = utilisateurs.get_utilisateur(projet["chef_projet_id"]) or {}
            chefs.insert(0, {"id": projet["chef_projet_id"], "prenom": projet["chef_prenom"],
                             "nom": projet["chef_nom"], "role": chef_actuel.get("role"),
                             "poste": chef_actuel.get("poste"), "avatar_chemin": projet.get("chef_avatar_chemin"),
                             "inactif": not chef_actuel.get("actif", False)})
        contexte["chefs_possibles"] = chefs
        contexte["chef_modifiable"] = not projet_clos or g.user["role"] == "admin"
    return contexte


@bp.route("/<int:projet_id>/taches-choix")
@login_required
def api_taches_choix(projet_id: int):
    """Lot 15 : tâches ouvertes d'un projet visible, pour « Tâche concernée »
    d'une Requête (fenêtre « + Nouveau post », chargées au choix du projet)."""
    if not projets.user_can_view(projet_id, g.user["id"]):
        return {"erreur": "introuvable", "message": "Projet introuvable."}, 404
    rows = taches.list_ouvertes_choix(projet_id)
    reponse = jsonify({"taches": [{"id": r["id"], "titre": r["titre"], "bloquee": r["etat"] == "bloque"}
                                  for r in rows]})
    reponse.headers["Cache-Control"] = "no-store"
    return reponse


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

    # Lot 14 : changement de catégorie du fil (liste remplacée) ou
    # « Afficher plus » (page suivante ajoutée à la fin), en partiel.
    if partiel.est_partiel() == "#fil-posts":
        contexte = dict(projet=projet, **_contexte_fil(projet_id))
        if film.curseur_demande():
            return partiel.repondre("partials/fil_page.html", show_projet=False,
                                    next_url=url_for("projets.detail", projet_id=projet_id,
                                                     fil=contexte["fil_categorie"]), **contexte)
        return partiel.repondre("partials/fil_maj.html", fil_gabarit="partials/fil_projet.html", **contexte)
    contexte = _contexte_fiche(projet)
    # Encart Admin « Projets ouverts dont le chef est désactivé » (liste
    # Utilisateurs) : fenêtre Informations ouverte, champ chef prêt.
    contexte["ouvrir_informations"] = (contexte["peut_gerer"] and request.args.get("informations") == "chef"
                                       and contexte["chef_modifiable"])

    # Recherche globale et notifications d'une tâche (lot 11 b) :
    # ?tache=<id> ouvre la fenêtre de cette tâche (chargée à la demande) ;
    # une tâche close est dépliée. Une tâche d'un autre projet est ignorée.
    tache_demandee = request.args.get("tache", type=int)
    liste_taches = contexte["taches"]
    t_ouvrir = next((t for t in liste_taches if t["id"] == tache_demandee), None) if tache_demandee else None
    contexte["tache_a_ouvrir"] = t_ouvrir["id"] if t_ouvrir else None
    contexte["deplier_taches_closes"] = bool(t_ouvrir) and t_ouvrir["etat"] in taches.ETATS_CLOS

    return render_template("projet_detail.html", **contexte)


# Fragments de la fiche projet rendus par une réponse partielle (lot 13).
FRAGMENTS_FICHE = {
    "fenetre": ["partials/tache_fenetre.html"],
    "ligne": ["partials/tache_ligne.html"],
    "compteur": ["partials/taches_compteur.html"],
    "taches": ["partials/carte_taches.html"],
    "projet": ["partials/projet_topbar.html", "partials/projet_subbar.html", "partials/projet_entete.html",
               "partials/carte_informations.html"],
    "intervenants": ["partials/carte_intervenants.html"],
    "fil": ["partials/fil_nouveaux.html"],
    "fil_complet": ["partials/fil_projet.html", "partials/fil_outils.html", "partials/fil_suite.html"],
    "informations": ["partials/projet_informations_form.html"],
    "post": ["partials/fil_item.html"],
}


def _maj_fiche(projet_id: int, racine: str | None, parties, *, tache_id: int | None = None,
               toasts: list | None = None, statut: int = 200, **extra):
    """Réponse partielle d'une action de la fiche projet (lot 13) : le
    fragment `racine` (la cible de la requête) puis les fragments `parties`
    hors cible (data-partiel-oob) — tous calculés comme la page complète,
    pour l'utilisateur connecté. Une tâche disparue ou invisible n'a plus
    de panneau ni de ligne."""
    from .taches_fenetre import contexte_fenetre

    projet = projets.get_projet(projet_id)
    contexte = _contexte_fiche(projet)
    contexte["fil_recent"] = contexte["fil"][:5]
    parties = list(parties)
    if tache_id is not None:
        fenetre = contexte_fenetre(projet, tache_id, contexte["peut_gerer"])
        if fenetre is None:
            parties = [p for p in parties if p not in ("fenetre", "ligne")]
            racine = None if racine in ("fenetre", "ligne") else racine
        else:
            contexte.update(fenetre)
    contexte.update(extra)
    gabarits = [g_ for p in parties if p != racine for g_ in FRAGMENTS_FICHE[p]]
    return partiel.repondre("partials/fiche_maj.html", statut=statut, toasts=toasts,
                            racine=FRAGMENTS_FICHE[racine][0] if racine else None, parties=gabarits, **contexte)


def _reponse_tache(projet_id: int, tache_id: int, toasts: list | None = None, *, deplacee: bool = False,
                   **extra):
    """Réponse partielle d'une action sur une tâche (lot 13) : le panneau
    (ou la ligne, selon la cible), puis hors cible la ligne — ou toute la
    carte si la tâche passe d'ouverte à close (`deplacee`) —, le compteur,
    l'état du projet (recalcul Bloqué / En cours), la carte Intervenants et
    les nouveaux posts du fil."""
    cible = partiel.est_partiel() or ""
    racine = "ligne" if cible.startswith("#tache-ligne-") else "fenetre"
    parties = ["fenetre", "ligne"] + (["taches"] if deplacee else ["compteur"]) + ["projet", "intervenants", "fil"]
    if deplacee:
        # La carte contient la ligne : elle la remplace aussi.
        parties.remove("ligne")
    return _maj_fiche(projet_id, racine, parties, tache_id=tache_id, toasts=toasts, surligner=tache_id, **extra)


def _action_annuler(url: str, donnees: dict, tache_id: int, libelle: str = "Annuler") -> dict:
    """Action « Annuler » d'un toast (lot 13), rejouée en partiel sur la
    ligne de la tâche (toujours présente, panneau ouvert ou non)."""
    return {"libelle": libelle, "url": url, "methode": "POST", "donnees": {**donnees, "annulation": "1"},
            "cible": f"#tache-ligne-{tache_id}"}


@bp.route("/<int:projet_id>/informations", methods=["POST"])
@login_required
def editer_informations(projet_id: int):
    """Fenêtre flottante "Informations" (retour Fadhel, 2026-09-28, Lot 5) :
    édite nom/état/lots/dates/phase liée. Réservée au chef de projet/co-chef
    — même autorisation que creer_tache/ajouter_intervenant (user_can_manage).

    Lot 11 b (demande du gérant) : aussi le chef de projet (champ
    `chef_projet_id`, absent = inchangé). Mêmes droits que le reste de la
    fenêtre ; projet clos : Admin seulement (les autres le rouvrent
    d'abord) ; nouveau chef actif, chef de projet ou Admin. Revérifié sous
    verrou par projets.update_projet et en base (migration 0017)."""
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    if not projets.user_can_manage(projet_id, g.user["id"]):
        return _refus("Seul le chef de projet ou un co-chef peut modifier les informations du projet.", 403, projet_id)

    def erreur(message: str, champ: str | None = None):
        # Lot 13 (audit a11y I5) : en partiel, le champ en cause est signalé
        # dans la fenêtre (422), la saisie reste.
        return _refus(message, 422, projet_id, champs={champ: message} if champ else None)

    actuel = projets.get_projet(projet_id) or {}
    acteur_admin = g.user["role"] == "admin"
    chef_brut = (request.form.get("chef_projet_id") or "").strip()
    nouveau_chef_id = None
    if chef_brut:
        # Chiffres ASCII seulement, taille d'un BIGINT (« ² » passe isdigit()).
        if not re.fullmatch(r"[0-9]{1,18}", chef_brut):
            return erreur(projets.MESSAGE_CHEF_INVALIDE, "chef_projet_id")
        nouveau_chef_id = int(chef_brut)
    if nouveau_chef_id is not None and nouveau_chef_id != actuel.get("chef_projet_id"):
        if actuel.get("etat") in projets.ETATS_CLOS and not acteur_admin:
            return erreur(projets.MESSAGE_CHEF_PROJET_CLOS, "chef_projet_id")
        candidat = utilisateurs.get_utilisateur(nouveau_chef_id)
        if candidat is None or not candidat.get("actif") or candidat.get("role") not in projets.ROLES_CHEF_POSSIBLES:
            return erreur(projets.MESSAGE_CHEF_INVALIDE, "chef_projet_id")
    else:
        nouveau_chef_id = None

    nom = request.form.get("nom", "").strip()
    etat = request.form.get("etat", "")
    lots = request.form.getlist("lots")
    date_debut = request.form.get("date_debut") or None
    date_fin = request.form.get("date_fin") or None
    phase_liee_id = request.form.get("phase_liee_id", type=int) or None
    client, honoraires = _client_et_honoraires()

    if honoraires is False:
        return erreur("Honoraires invalides (un montant positif, ex. 12 500,00).", "honoraires")
    if not nom:
        return erreur("Le nom du projet est obligatoire.", "nom")
    if message := v.trop_long(nom, v.MAX_NOM_PROJET, "Nom du projet"):
        return erreur(message, "nom")
    if message := v.trop_long(client, v.MAX_CLIENT, "Client"):
        return erreur(message, "client")
    if etat not in ETATS_PROJET_VALIDES:
        return erreur("État invalide.", "etat")
    if any(l not in LOTS_VALIDES for l in lots):
        return erreur("Lot invalide.", "lots")
    if not lots and request.form.get("lots_envoyes") == "1" and projets.list_lots(projet_id):
        # Lot 13 (audit rôles M12) : la fenêtre Informations (marqueur
        # lots_envoyes) ne vide plus les lots d'un projet ; un ancien projet
        # repris sans lot reste modifiable tel quel.
        return erreur("Gardez au moins un lot (CM ou GO).", "lots")

    try:
        date_debut_valide = _parser_date_tache(date_debut)
    except ValueError:
        return erreur("Date de début invalide.", "date_debut")
    try:
        date_fin_valide = _parser_date_tache(date_fin)
    except ValueError:
        return erreur("Date de fin invalide.", "date_fin")
    # Dates cohérentes (retour Fadhel, lot 8) : années plausibles, fin
    # prévue pas avant le début, et pas de début après une tâche ou des
    # heures déjà datées du projet. Contrôlé seulement si les dates CHANGENT :
    # un projet ancien aux dates incohérentes (ex. repris de Chronos) reste
    # modifiable pour tout le reste — le renommer, le clore, le rouvrir.
    dates_changees = (date_debut_valide != actuel.get("date_debut")
                      or date_fin_valide != actuel.get("date_fin"))
    if dates_changees:
        premiere = taches.premiere_date(projet_id) if date_debut_valide else None
        avant_debut = None
        if premiere and premiere < date_debut_valide:
            avant_debut = (
                f"Date de début impossible\u00a0: une tâche ou des heures du projet datent du "
                f"{premiere.strftime('%d/%m/%Y')}, avant le {date_debut_valide.strftime('%d/%m/%Y')}."
            )
        for champ, message in (
            ("date_debut", v.date_hors_bornes(date_debut_valide, "Date de début")),
            ("date_fin", v.date_hors_bornes(date_fin_valide, "Date de fin")),
            ("date_fin", v.ordre_dates(date_debut_valide, date_fin_valide, "la date de début", "Date de fin")),
            ("date_debut", avant_debut),
        ):
            if message:
                return erreur(message, champ)

    # "Phase liée" doit rester un projet réellement visible par
    # l'utilisateur (même contrôle IDOR que pour le projet lui-même) —
    # sinon on pourrait relier un projet à un id deviné/invisible.
    if phase_liee_id is not None and not projets.user_can_view(phase_liee_id, g.user["id"]):
        return erreur("Projet lié invalide.", "phase_liee_id")

    # Clôture confirmée (lot 13, décision 2) : la liste des tâches ouvertes
    # que la personne a vue ; revérifiée sous verrou par update_projet.
    taches_a_clore = None
    if request.form.get("confirmer_cloture") == "1":
        taches_a_clore = v.ids_entiers(request.form.getlist("taches_a_clore"))
    bilan = {}

    try:
        changement = projets.update_projet(
            projet_id, nom=nom, etat=etat, lots=lots,
            date_debut=date_debut_valide, date_fin=date_fin_valide,
            phase_liee_id=phase_liee_id, current_user_id=g.user["id"],
            honoraires=honoraires, client=client,
            chef_projet_id=nouveau_chef_id, acteur_admin=acteur_admin,
            taches_a_clore=taches_a_clore, bilan=bilan,
        )
    except projets.ClotureAConfirmer as attente:
        return _confirmer_cloture(projet_id, etat, attente)
    except Exception as exc:
        if isinstance(exc, projets.ChangementChefRefuse):
            return _refus(exc.message, 409, projet_id, champs={"chef_projet_id": exc.message})
        if projets.est_refus_changement_chef(exc):
            # Dernier rempart en base (trg_garde_chef_projet) : l'état a
            # changé entre le contrôle et l'enregistrement.
            return _refus("Changement de chef refusé\u00a0: rechargez la page et vérifiez l’état du projet.", 409,
                          projet_id)
        current_app.logger.exception("Échec inattendu de modification des informations (projet %s)", projet_id)
        return _refus("Impossible d’enregistrer les informations (erreur inattendue, réessayez).", 500, projet_id)
    else:
        if isinstance(changement, dict):
            nouveau, ancien = changement["nouveau"], changement["ancien"]
            if nouveau["id"] != g.user["id"]:
                # Après coup, comme les autres notifications : un échec ici
                # ne défait pas le changement (déjà enregistré).
                try:
                    notifications_repo.creer(
                        nouveau["id"], "projet",
                        f"{g.user['prenom']} {g.user['nom']} vous a confié le projet "
                        f"«\u00a0{actuel.get('code', '')}_{nom}\u00a0»\u00a0: vous en êtes le chef de projet.",
                        post_id=changement["post_id"],
                    )
                except Exception:
                    current_app.logger.exception("Notification du nouveau chef impossible (projet %s)", projet_id)
            flash(f"Informations du projet mises à jour\u00a0: projet confié à {nouveau['prenom']} {nouveau['nom']} "
                  f"({ancien['prenom']} {ancien['nom']} devient co-chef).", "success")
        elif bilan.get("taches_closes"):
            # Message fondé sur l'effet (recette finale) : un double envoi de
            # la confirmation ne prétend pas clore des tâches déjà closes.
            n = bilan["taches_closes"]
            participe = "terminée" if etat == "termine" else "abandonnée"
            flash(f"Projet clos avec sa tâche ouverte ({participe})." if n == 1
                  else f"Projet clos avec ses {n} tâches ouvertes ({participe}s).", "success")
        elif taches_a_clore is not None and bilan.get("etat_avant") == etat:
            flash("Projet déjà clos\u00a0: informations enregistrées, aucune tâche à clore.", "info")
        else:
            flash("Informations du projet mises à jour.", "success")

    if partiel.est_partiel():
        # Lot 13 : fenêtre fermée (data-enregistre), fiche mise à jour en place.
        return _maj_fiche(projet_id, "informations", ["projet", "taches", "intervenants", "fil_complet"],
                          enregistre_informations=True)
    return redirect(url_for("projets.detail", projet_id=projet_id))


# Champs de la fenêtre Informations renvoyés tels quels par la page de
# confirmation de clôture (lot 13) : rien d'autre n'est recopié.
CHAMPS_INFORMATIONS = ("nom", "etat", "lots", "lots_envoyes", "date_debut", "date_fin", "phase_liee_id",
                       "client", "honoraires", "chef_projet_id")


def _confirmer_cloture(projet_id: int, etat: str, attente):
    """Étape de confirmation (lot 13, décision 2, audit rôles I3) : clore un
    projet qui a des tâches ouvertes. Page complète (fonctionne sans
    JavaScript) qui renvoie le même formulaire avec la liste des tâches
    confirmées ; fragment seul pour une requête AJAX (X-Requested-With)."""
    projet = projets.get_projet(projet_id)
    champs = [(nom, valeur) for nom in CHAMPS_INFORMATIONS for valeur in request.form.getlist(nom)]
    contexte = dict(
        projet=projet, etat_demande=etat, taches_ouvertes=attente.taches, champs=champs,
        liste_changee=attente.liste_changee,
    )
    if partiel.est_partiel():
        # Lot 13 : la confirmation remplace le formulaire dans la fenêtre
        # Informations (même id, #informations-form).
        return partiel.repondre("partials/projet_cloture_confirmation.html", dans_fenetre=True, **contexte)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render_template("partials/projet_cloture_confirmation.html", **contexte)
    return render_template("projet_cloture_confirmer.html", **contexte)


@bp.route("/<int:projet_id>/informations", methods=["GET"])
@login_required
def informations_formulaire(projet_id: int):
    """Formulaire de la fenêtre Informations seul (lot 13) : rendu à la
    fermeture de la fenêtre quand la confirmation de clôture l'a remplacé.
    Mêmes droits que l'enregistrement."""
    projet = projets.get_projet(projet_id)
    if projet is None or not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    if not projets.user_can_manage(projet_id, g.user["id"]):
        abort(403)
    return partiel.repondre("partials/projet_informations_form.html", **_contexte_fiche(projet, fil_limite=1))


def _intervenants_possibles(projet_id: int, brut: list[str]) -> tuple[list[int], list[dict]]:
    """Ids demandés comme intervenants d'une tâche → (retenus, écartés).
    Retenus : comptes actifs, ni Client ni RH, qui voient le projet ;
    écartés : les autres comptes existants (nommés dans le message)."""
    demandes = v.ids_entiers(brut)
    if not demandes:
        return [], []
    affectables = {u["id"]: u for u in utilisateurs.list_affectables()}
    retenus, ecartes = [], []
    for uid in demandes:
        if uid in affectables and projets.user_can_view(projet_id, uid):
            retenus.append(uid)
        else:
            personne = affectables.get(uid) or utilisateurs.get_utilisateur(uid)
            if personne is not None:
                ecartes.append(personne)
    return retenus, ecartes


def _message_ecartes(ecartes: list[dict]) -> str:
    if not ecartes:
        return ""
    noms = ", ".join(f"{p.get('prenom') or ''} {p.get('nom') or ''}".strip() for p in ecartes)
    if len(ecartes) == 1:
        return f" {noms} n’a pas accès à ce projet (ou ne peut pas être intervenant)\u00a0: non affecté."
    return f" {noms} n’ont pas accès à ce projet (ou ne peuvent pas être intervenants)\u00a0: non affectés."


def _signaler_co_chefs(projet_id: int, projet: dict | None, intervenant_ids: list[int], avant: set[int]) -> str:
    """Un chef de projet affecté à une tâche devient co-chef du projet
    (trigger 0013) : il en est prévenu, le chef titulaire aussi (lot 13,
    audit rôles M9, comme pour « Rejoindre »). Renvoie le complément du
    message affiché."""
    if not intervenant_ids:
        return ""
    apres = projets.ids_co_chefs(projet_id)
    nouveaux = [uid for uid in intervenant_ids if uid not in avant and uid in apres]
    if not nouveaux:
        return ""
    projet = projet or projets.get_projet(projet_id) or {}
    noms = []
    for uid in nouveaux:
        personne = utilisateurs.get_utilisateur(uid) or {}
        nom = f"{personne.get('prenom') or ''} {personne.get('nom') or ''}".strip()
        noms.append(nom)
        try:
            if uid != g.user["id"]:
                notifications_repo.creer(uid, "projet",
                                         f"Affecté à une tâche du projet «\u00a0{_code_nom(projet)}\u00a0», vous en êtes "
                                         "maintenant co-chef.", projet_id=projet_id)
            chef_id = projet.get("chef_projet_id")
            if chef_id and chef_id not in (uid, g.user["id"]):
                notifications_repo.creer(chef_id, "projet",
                                         f"{nom} est maintenant co-chef de votre projet «\u00a0{_code_nom(projet)}\u00a0» "
                                         "(affecté à une tâche).", projet_id=projet_id)
        except Exception:
            current_app.logger.exception("Notification de co-chef impossible (projet %s)", projet_id)
    return f" {', '.join(noms)} {'deviennent co-chefs' if len(noms) > 1 else 'devient co-chef'} du projet."


@bp.route("/<int:projet_id>/taches", methods=["POST"])
@login_required
def creer_tache(projet_id: int):
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    if not projets.user_can_manage(projet_id, g.user["id"]):
        return _refus("Seul le chef de projet ou un co-chef peut créer une tâche sur ce projet.", 403, projet_id)
    refus = _refus_si_clos(projet_id)
    if refus:
        return refus

    titre = request.form.get("titre", "").strip()
    if not titre:
        return _refus("Le titre de la tâche est obligatoire.", 422, projet_id,
                      champs={"titre": "Le titre de la tâche est obligatoire."})
    if erreur := v.trop_long(titre, v.MAX_TITRE_TACHE, "Titre de la tâche"):
        return _refus(erreur, 422, projet_id, champs={"titre": erreur})

    type_deadline = request.form.get("type_deadline", "rendu_client")
    if type_deadline not in TYPE_DEADLINE_VALIDES:
        return _refus("Type d’échéance invalide.", 422, projet_id, champs={"type_deadline": "Type d’échéance invalide."})

    try:
        date_debut = _parser_date_tache(request.form.get("date_debut"))
        date_echeance = _parser_date_tache(request.form.get("date_echeance"))
    except ValueError:
        return _refus("Date de début ou d’échéance invalide.", 422, projet_id,
                      champs={"date_echeance": "Date de début ou d’échéance invalide."})
    # Dates cohérentes (retour Fadhel, lot 8) : pas de tâche antérieure au
    # début du projet, pas d'échéance avant le début de la tâche.
    projet = projets.get_projet(projet_id)
    debut_projet = projet.get("date_debut") if projet else None
    for champ, erreur in (
        ("date_debut", v.date_hors_bornes(date_debut, "Date de début")),
        ("date_echeance", v.date_hors_bornes(date_echeance, "Échéance")),
        ("date_echeance", v.ordre_dates(date_debut, date_echeance, "la date de début de la tâche", "Échéance")),
        ("date_debut", v.ordre_dates(debut_projet, date_debut, "la date de début du projet", "Date de début de la tâche")),
        ("date_echeance", v.ordre_dates(debut_projet, date_echeance, "la date de début du projet", "Échéance")),
    ):
        if erreur:
            return _refus(erreur, 422, projet_id, champs={champ: erreur})

    # Seules des personnes qui voient déjà le projet peuvent y être
    # affectées (même règle que les mentions dans routes/posts.py) — un id
    # inexistant est ainsi écarté ici au lieu de faire échouer l'INSERT.
    # Jamais un Client (migration 0011). Lot 13 (audit rôles I7) : une
    # personne écartée est nommée dans le message, plus rien en silence.
    intervenant_ids, ecartes = _intervenants_possibles(projet_id, request.form.getlist("intervenants"))

    # Un rebond doit pointer vers un post du MÊME projet (même contrôle que
    # routes/posts.py:creer) : sinon le fil de ce projet afficherait le
    # contenu, l'auteur et la tâche d'un post de n'importe quel autre
    # projet — fuite de données inter-projets (revue sécurité, audit n°2).
    parent_post_id = request.form.get("parent_post_id", type=int)
    if parent_post_id:
        parent = posts.get_post(parent_post_id)
        if parent is None or parent["projet_id"] != projet_id or parent.get("supprime_le") is not None:
            abort(404)

    co_chefs_avant = projets.ids_co_chefs(projet_id)
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
        return _refus(_message_erreur_intervenant(exc, "de créer cette tâche"), 422, projet_id)

    if intervenant_ids:
        notifications_repo.creer_pour_plusieurs(
            intervenant_ids, "projet",
            f"Nouvelle tâche pour vous\u00a0: «\u00a0{titre}\u00a0» ({projet['code']}).",
            tache_id=tache_id, exclure_id=g.user["id"],
        )
    co_chefs = _signaler_co_chefs(projet_id, projet, intervenant_ids, co_chefs_avant)

    message_cree = "Tâche créée." + co_chefs + _message_ecartes(ecartes)
    if partiel.est_partiel() and partiel.est_partiel() != "#fil-posts":
        # Lot 15 (revue UX) : créée hors de la fiche (accueil), le toast
        # propose d'ouvrir la tâche.
        from .posts import reponse_publication

        ouvrir = {"libelle": "Ouvrir", "url": url_for("projets.detail", projet_id=projet_id, tache=tache_id),
                  "methode": "GET"}
        post_id = posts.id_post_creation_tache(tache_id)
        toast = [partiel.toast(message_cree, action=ouvrir)]
        return reponse_publication(post_id, toasts=toast) if post_id else partiel.rien(toast)
    flash(message_cree, "success")
    if partiel.est_partiel():
        # Lot 13 (audit UX §2.4) : la fenêtre se ferme, le post de création
        # arrive en tête du fil ; sur la fiche, la ligne est insérée et
        # surlignée dans le tableau.
        from .posts import reponse_publication

        post_id = posts.id_post_creation_tache(tache_id)
        if partiel.est_partiel() != "#fil-posts" or post_id is None:
            return reponse_publication(post_id) if post_id else partiel.rien()
        post = posts.get_post_carte(post_id, g.user["id"])
        # Lot 14 : le post de création (Activité) n'arrive pas dans la vue
        # « Échanges » du fil.
        racine = None if film.categorie_demandee() == "echanges" else "post"
        return _maj_fiche(projet_id, racine, ["taches", "projet", "intervenants"], post=post, show_projet=False,
                          next_url=url_for("projets.detail", projet_id=projet_id), surligner=tache_id)
    return redirect(url_for("projets.detail", projet_id=projet_id))


MESSAGE_MOTIF_REQUIS = "Indiquez ce qui bloque la tâche."


def _phrase(texte: str, maximum: int = 200) -> str:
    """Texte saisi cité dans une notification : une ligne, coupé à
    `maximum` caractères, terminé par un point s'il n'a pas de ponctuation."""
    texte = " ".join((texte or "").split())
    if len(texte) > maximum:
        texte = texte[:maximum - 1].rstrip() + "…"
    return texte if texte.endswith((".", "!", "?", "…")) else texte + "."


def _acteur() -> str:
    return f"{g.user['prenom']} {g.user['nom']}".strip()


def _prevenir_gestion(projet: dict, tache_id: int, message: str) -> tuple[list[dict], list[int]]:
    """Notification au chef titulaire et aux co-chefs du projet (lot 14,
    revue produit P0-1 / P0-2 : un blocage ou une clôture arrivent jusqu'au
    chef), jamais à l'acteur ; elle ouvre la tâche. Après coup, comme les
    autres notifications : un échec ne défait pas l'action. Renvoie les
    personnes prévenues (pour le toast) et les ids des notifications créées
    (retirées par « Annuler », et seulement elles)."""
    ids = [projet.get("chef_projet_id")] + sorted(projets.ids_co_chefs(projet["id"]))
    destinataires = [uid for uid in dict.fromkeys(ids) if uid and uid != g.user["id"]]
    try:
        crees = notifications_repo.creer_pour_plusieurs(destinataires, "projet", message, tache_id=tache_id)
    except Exception:
        current_app.logger.exception("Notification au chef de projet impossible (tâche %s)", tache_id)
        return [], []
    return [u for u in (utilisateurs.get_utilisateur(uid) for uid in destinataires) if u], list(crees or [])


# « Annuler » d'un changement d'état ou d'une clôture (recette du lot 14,
# n° 2, 4 et 5) : l'action du toast porte un jeton signé — tâche, personne,
# état à rendre (et son motif), version de la tâche produite par le geste,
# notifications créées par lui. Sans jeton valide, « annulation » n'a aucun
# effet (un blocage exige son motif, le chef est prévenu) ; un jeton dont
# la tâche a changé depuis est refusé (409).
SEL_ANNULER = "kairos-annuler-etat-tache"
DUREE_JETON_ANNULER = 30 * 60
MESSAGE_ANNULER_PERIME = ("La tâche a changé entre-temps (action d’une autre personne)\u00a0: "
                          "«\u00a0Annuler\u00a0» n’est plus possible.")


def _signeur_annuler():
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(current_app.secret_key, salt=SEL_ANNULER)


def _jeton_annuler(projet_id: int, tache_id: int, etat: str, motif: str | None, notifications: list[int]) -> str:
    return _signeur_annuler().dumps({"p": projet_id, "t": tache_id, "u": g.user["id"], "e": etat, "m": motif,
                                     "v": taches.version(tache_id), "n": [int(i) for i in notifications]})


def _lire_jeton_annuler(projet_id: int, tache_id: int) -> dict | None:
    """Contenu du jeton « Annuler » de la requête, s'il est valide pour
    cette tâche et cette personne ; None sinon."""
    from itsdangerous import BadData

    brut = request.form.get("jeton") or ""
    if not brut:
        return None
    try:
        jeton = _signeur_annuler().loads(brut, max_age=DUREE_JETON_ANNULER)
    except BadData:
        return None
    if not isinstance(jeton, dict) or (jeton.get("p"), jeton.get("t"), jeton.get("u")) != (projet_id, tache_id,
                                                                                             g.user["id"]):
        return None
    return jeton


def _noms_prevenus(personnes: list[dict]) -> str:
    noms = [f"{p.get('prenom') or ''} {p.get('nom') or ''}".strip() for p in personnes]
    if len(noms) > 1:
        return ", ".join(noms[:-1]) + " et " + noms[-1]
    return noms[0] if noms else ""


@bp.route("/<int:projet_id>/taches/<int:tache_id>/etat", methods=["POST"])
@login_required
def changer_etat_tache(projet_id: int, tache_id: int):
    """Changement d'état simple (pas de clôture) — voir cloturer_tache
    pour "Terminé", qui exige un tag de post.

    Autorisation (PROMPT_CORRECTIONS.md P0 #2) : chef de projet, co-chef,
    OU intervenant affecté à CETTE tâche.

    Décision du gérant (lot 10) : Vérifiée, Arrêtée et Abandonnée sont
    réservées au chef titulaire, aux co-chefs et à l'Admin — dans les deux
    sens (y entrer, en sortir). L'état actuel est revérifié sous verrou par
    taches.set_etat, et en base par le trigger de la migration 0015.

    Lot 13 (audit UX I5) : en partiel, le panneau et la ligne de la tâche,
    le compteur, l'état du projet et le fil sont mis à jour sans recharger ;
    toast « État : … » avec « Annuler » (retour à l'état d'avant)."""
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    peut_gerer = projets.user_can_manage(projet_id, g.user["id"])
    autorise = peut_gerer or taches.user_est_intervenant(tache_id, g.user["id"])
    if not autorise:
        return _refus("Seul le chef de projet, un co-chef ou un intervenant de cette tâche peut changer son état.", 403,
                      projet_id)
    refus = _refus_si_clos(projet_id)
    if refus:
        return refus

    etat = request.form.get("etat")
    etats_valides = {"en_cours", "bloque", "verifie", "arret", "abandonne"}
    if etat not in etats_valides:
        return _refus("État invalide.", 422, projet_id)
    if etat in taches.ETATS_RESERVES_GESTION and not peut_gerer:
        return _refus(taches.MESSAGE_ETAT_RESERVE, 403, projet_id)
    # « Annuler » (recette du lot 14, n° 2 et 5) : seulement avec le jeton
    # de l'action, qui dit l'état exact à rendre ; un jeton périmé ou
    # étranger est refusé, une demande sans jeton est un changement normal.
    jeton = None
    if request.form.get("annulation"):
        jeton = _lire_jeton_annuler(projet_id, tache_id)
        if jeton is None and request.form.get("jeton"):
            return _refus(MESSAGE_ANNULER_PERIME, 409, projet_id, tache_id, vers_tache=True)
        if jeton is not None:
            etat = jeton["e"]
            if etat not in etats_valides or (etat in taches.ETATS_RESERVES_GESTION and not peut_gerer):
                return _refus(MESSAGE_ANNULER_PERIME, 409, projet_id, tache_id, vers_tache=True)
    annulation = jeton is not None
    # Lot 14 (revue produit P0-1) : « Qu'est-ce qui bloque ? » obligatoire
    # (sauf « Annuler » d'une levée de blocage : le motif d'avant revient).
    motif = None
    if etat == "bloque":
        if annulation:
            motif = jeton.get("m")
        else:
            motif = taches.normaliser_motif(request.form.get("motif"))
            erreur = MESSAGE_MOTIF_REQUIS if not motif else v.trop_long(motif, taches.MOTIF_BLOCAGE_MAX,
                                                                        "Motif du blocage")
            if erreur:
                return _refus(erreur, 422, projet_id, tache_id, vers_tache=True, champs={"motif": erreur})

    avant = taches.get_tache(tache_id)
    remplace: dict = {}
    try:
        trouvee = taches.set_etat(tache_id, projet_id, etat, g.user["id"], peut_gerer=peut_gerer,
                                  annulation=annulation, remplace=remplace, **({"motif": motif} if etat == "bloque" else {}),
                                  **({"version_attendue": jeton.get("v")} if annulation else {}))
    except taches.MotifBlocageRequis:
        return _refus(MESSAGE_MOTIF_REQUIS, 422, projet_id, tache_id, vers_tache=True,
                      champs={"motif": MESSAGE_MOTIF_REQUIS})
    except taches.TacheModifiee:
        return _refus(MESSAGE_ANNULER_PERIME, 409, projet_id, tache_id, vers_tache=True)
    except Exception as exc:
        if not taches.est_refus_etat_reserve(exc):
            raise
        return _refus(taches.MESSAGE_ETAT_RESERVE, 403, projet_id)
    if not trouvee:
        return _refus("Tâche introuvable sur ce projet.", 404, projet_id)

    avant = avant if isinstance(avant, dict) else {}
    # Lot 18 : l'état remplacé est celui lu sous verrou par set_etat.
    avant = {**avant, **remplace}
    etat_avant = avant.get("etat")
    texte = None
    notifications_creees: list[int] = []
    if etat == "bloque" and etat_avant != "bloque" and not annulation:
        # Le chef et les co-chefs sont prévenus, avec le motif (P0-1).
        projet = projets.get_projet(projet_id) or {"id": projet_id}
        prevenus, notifications_creees = _prevenir_gestion(
            projet, tache_id,
            f"{_acteur()} a bloqué «\u00a0{avant.get('titre') or ''}\u00a0» ({projet.get('code') or ''})\u00a0: "
            f"{_phrase(motif)}")
        texte = f"Blocage signalé à {_noms_prevenus(prevenus)}." if prevenus else "Blocage signalé."
    elif annulation and jeton.get("n"):
        # « Annuler » d'un blocage ou d'une clôture : le chef n'est plus
        # alerté d'un geste défait — seulement les notifications de CE
        # geste (recette du lot 14, n° 4), encore non lues.
        try:
            notifications_repo.retirer(jeton["n"], tache_id)
        except Exception:
            current_app.logger.exception("Notifications non retirées (tâche %s)", tache_id)
    if etat_avant == "bloque" and etat == "en_cours" and not annulation:
        # Lot 16 : la levée du blocage prévient qui l'avait signalé et les
        # intervenants de la tâche (jamais l'acteur) ; « Annuler » retire
        # ces notifications.
        projet = projets.get_projet(projet_id) or {}
        ids = [avant.get("bloque_par")] + taches.ids_intervenants(tache_id)
        destinataires = [uid for uid in dict.fromkeys(ids) if uid and uid != g.user["id"]]
        prevenus = []
        if destinataires:
            try:
                notifications_creees = list(notifications_repo.creer_pour_plusieurs(
                    destinataires, "projet",
                    f"{_acteur()} a levé le blocage de « {avant.get('titre') or ''} » "
                    f"({projet.get('code') or ''}).", tache_id=tache_id) or [])
                prevenus = [u for u in (utilisateurs.get_utilisateur(uid) for uid in destinataires) if u]
            except Exception:
                current_app.logger.exception("Notification de levée de blocage impossible (tâche %s)", tache_id)
        texte = f"Blocage levé : {_noms_prevenus(prevenus)} prévenu{'s' if len(prevenus) > 1 else ''}." \
            if prevenus else "Blocage levé."

    if partiel.est_partiel():
        libelle = tache_etat_style(etat)["libelle"]
        action = None
        # « Annuler » : seulement vers un état que cette personne peut
        # redonner par la même route (pas « Terminée », qui passe par la
        # clôture ; pas un état réservé pour un intervenant). Retour au
        # blocage : avec son motif.
        if (not annulation and etat_avant and etat_avant != etat and etat_avant in etats_valides
                and (peut_gerer or etat_avant not in taches.ETATS_RESERVES_GESTION)):
            jeton_retour = _jeton_annuler(projet_id, tache_id, etat_avant,
                                          avant.get("bloque_motif") if etat_avant == "bloque" else None,
                                          notifications_creees)
            donnees = {"etat": etat_avant, "jeton": jeton_retour}
            action = _action_annuler(url_for("projets.changer_etat_tache", projet_id=projet_id, tache_id=tache_id),
                                     donnees, tache_id)
        deplacee = (etat_avant in taches.ETATS_CLOS) != (etat in taches.ETATS_CLOS)
        return _reponse_tache(projet_id, tache_id,
                              [partiel.toast(texte or f"État de la tâche\u00a0: {libelle}.", action=action)],
                              deplacee=deplacee)
    flash(texte or "État de la tâche mis à jour.", "success")
    return redirect(url_for("projets.detail", projet_id=projet_id))


@bp.route("/<int:projet_id>/taches/<int:tache_id>/titre", methods=["POST"])
@login_required
def modifier_titre_tache(projet_id: int, tache_id: int):
    """Titre d'une tâche, depuis la fenêtre ouverte par un clic sur sa ligne
    (retour Fadhel, 2026-09-29) — même autorisation que le changement
    d'état. Le changement apparaît dans le fil (taches.set_titre). Lot 13 :
    édition en place, en partiel (coche « Enregistré »)."""
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    autorise = (
        projets.user_can_manage(projet_id, g.user["id"])
        or taches.user_est_intervenant(tache_id, g.user["id"])
    )
    if not autorise:
        return _refus("Seul le chef de projet, un co-chef ou un intervenant de cette tâche peut la renommer.", 403,
                      projet_id)
    refus = _refus_si_clos(projet_id)
    if refus:
        return refus
    titre = request.form.get("titre", "").strip()
    if not titre or len(titre) > 255:
        message = "Le titre de la tâche est obligatoire." if not titre else "Titre trop long (255 caractères au plus)."
        return _refus(message, 422, projet_id, champs={"titre": message})
    if not taches.set_titre(tache_id, projet_id, titre, g.user["id"]):
        return _refus("Tâche introuvable sur ce projet.", 404, projet_id)
    if partiel.est_partiel():
        return _reponse_tache(projet_id, tache_id, [partiel.toast("Tâche renommée.")], enregistre="titre")
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
    planter la clôture en 500 via une violation de contrainte FK).

    Clôturer une tâche Arrêtée ou Abandonnée la fait sortir d'un état
    réservé au chef / co-chef / Admin (décision du gérant, lot 10).
    Lot 13 : en partiel, la ligne passe dans les tâches closes, toast avec
    « Annuler » (la tâche est rouverte)."""
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    peut_gerer = projets.user_can_manage(projet_id, g.user["id"])
    autorise = peut_gerer or taches.user_est_intervenant(tache_id, g.user["id"])
    if not autorise:
        return _refus("Seul le chef de projet, un co-chef ou un intervenant de cette tâche peut la clôturer.", 403,
                      projet_id)
    refus = _refus_si_clos(projet_id)
    if refus:
        return refus

    type_code = request.form.get("type_code", "envoi")
    if type_code not in TYPES_CLOTURE_VALIDES:
        return _refus("Tag de clôture invalide.", 422, projet_id, champs={"type_code": "Tag de clôture invalide."})
    contenu = (request.form.get("contenu") or "").strip() or None
    if erreur := v.trop_long(contenu, v.MAX_CONTENU_POST, "Message de clôture"):
        return _refus(erreur, 422, projet_id)
    # Lot 17 : date de fin choisie (oubli d'hier ou d'avant-hier) : jamais
    # dans le futur, jamais avant la création de la tâche.
    date_fin = None
    brute = (request.form.get("date_fin") or "").strip()
    if brute:
        from ..repositories import dailylog as dl

        try:
            date_fin = datetime.date.fromisoformat(brute)
        except ValueError:
            return _refus("Date de fin invalide.", 422, projet_id, champs={"date_fin": "Date de fin invalide."})
        tache_avant = taches.get_tache(tache_id) or {}
        cree = tache_avant.get("created_at")
        debut = cree.astimezone(horloge.ZoneInfo(g.user.get("fuseau") or "Africa/Tunis")).date() \
            if hasattr(cree, "astimezone") else None
        aujourdhui = dl.aujourdhui_pour(g.user)
        if date_fin > aujourdhui:
            return _refus("La date de fin ne peut pas être dans le futur.", 422, projet_id,
                          champs={"date_fin": "La date de fin ne peut pas être dans le futur."})
        # Lot 18 : même borne basse que le champ de la fenêtre (date simulée
        # antérieure à la création, en mode test).
        if debut and date_fin < min(debut, aujourdhui):
            message = f"La tâche a été créée le {debut.strftime('%d/%m/%Y')}\u00a0: date de fin trop ancienne."
            return _refus(message, 422, projet_id, champs={"date_fin": message})

    try:
        post_id = taches.close_tache(tache_id, projet_id, g.user["id"], type_code, contenu,
                                     peut_gerer=peut_gerer, date_fin=date_fin)
    except Exception as exc:
        if not taches.est_refus_etat_reserve(exc):
            raise
        return _refus(taches.MESSAGE_ETAT_RESERVE, 403, projet_id)
    if post_id is None:
        return _refus("Impossible de clôturer cette tâche (introuvable sur ce projet, ou déjà clôturée).", 409,
                      projet_id)

    # Lot 14 (revue produit P0-2) : quand un intervenant (ni chef ni
    # co-chef) termine une tâche, le chef et les co-chefs sont prévenus,
    # avec le type de post et le début du message.
    texte = "Tâche terminée\u00a0: post publié dans le fil."
    notifications_creees: list[int] = []
    projet = projets.get_projet(projet_id) or {"id": projet_id}
    if g.user["id"] != projet.get("chef_projet_id") and g.user["id"] not in projets.ids_co_chefs(projet_id):
        tache = taches.get_tache(tache_id)
        titre = tache.get("titre") if isinstance(tache, dict) else ""
        message = (f"{_acteur()} a terminé «\u00a0{titre or ''}\u00a0» ({projet.get('code') or ''}) — "
                   f"{post_type_style(type_code)['label']}")
        prevenus, notifications_creees = _prevenir_gestion(
            projet, tache_id, message + (f"\u00a0: {_phrase(contenu)}" if contenu else "."))
        if prevenus:
            texte = f"Tâche terminée\u00a0: post publié, {_noms_prevenus(prevenus)} prévenu{'s' if len(prevenus) > 1 else ''}."

    if partiel.est_partiel():
        action = _action_annuler(url_for("projets.changer_etat_tache", projet_id=projet_id, tache_id=tache_id),
                                 {"etat": "en_cours",
                                  "jeton": _jeton_annuler(projet_id, tache_id, "en_cours", None, notifications_creees)},
                                 tache_id)
        return _reponse_tache(projet_id, tache_id, [partiel.toast(texte, action=action)], deplacee=True)
    flash(texte, "success")
    return redirect(url_for("projets.detail", projet_id=projet_id))


@bp.route("/<int:projet_id>/intervenants", methods=["POST"])
@login_required
def ajouter_intervenant(projet_id: int):
    """Ajouter quelqu'un au projet (carte Intervenants, lot 11). Lot 13 : en
    partiel, la carte seule est remplacée (plus de rechargement de secours),
    le message part en toast."""
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    if not projets.user_can_manage(projet_id, g.user["id"]):
        return _refus("Seul le chef de projet ou un co-chef peut ajouter un intervenant.", 403, projet_id)
    refus = _refus_si_clos(projet_id)
    if refus:
        return refus

    utilisateur_id = request.form.get("utilisateur_id", type=int)
    if not utilisateur_id:
        return _refus("Utilisateur invalide.", 422, projet_id)

    # Un compte désactivé (actif=false) ne doit jamais pouvoir devenir
    # intervenant (audit sécurité/qualité externe, 2026-09-28, item P1-3).
    candidat = utilisateurs.get_utilisateur(utilisateur_id)
    if candidat is None or not candidat["actif"]:
        return _refus("Utilisateur invalide.", 422, projet_id)
    if candidat.get("role") == "client":
        return _refus("Un client ne peut pas être intervenant.", 422, projet_id)

    try:
        ajoute = projets.add_intervenant(projet_id, utilisateur_id, g.user["id"])
    except Exception as exc:
        # Garde-fou base de données (trg_check_projet_intervenant_role) :
        # un RH ne peut pas être intervenant.
        return _refus(_message_erreur_intervenant(exc, "d’ajouter cet intervenant"), 422, projet_id)
    # Un chef de projet ajouté devient co-chef (décision 3, lot 10).
    # Notification seulement si le rattachement est NOUVEAU (audit
    # sécurité I12).
    comme_co_chef = candidat.get("role") == "chef_de_projet"
    if ajoute and utilisateur_id != g.user["id"]:
        # projet_id (lot 13, audit rôles I8) : la notification ouvre la fiche.
        projet = projets.get_projet(projet_id)
        notifications_repo.creer(
            utilisateur_id, "projet",
            f"Vous avez été ajouté comme {'co-chef' if comme_co_chef else 'intervenant'} "
            f"sur le projet «\u00a0{_code_nom(projet)}\u00a0».",
            projet_id=projet_id,
        )
    if not ajoute:
        flash("Cette personne est déjà rattachée au projet.", "success")
    elif comme_co_chef:
        flash("Chef de projet ajouté\u00a0: il devient co-chef du projet.", "success")
    else:
        flash("Intervenant ajouté.", "success")
    if partiel.est_partiel():
        return _maj_fiche(projet_id, "intervenants", ["fil"])
    return redirect(url_for("projets.detail", projet_id=projet_id))


def _garde_gestion(projet_id: int, action: str, tache_id: int | None = None):
    """Contrôles communs des actions de gestion d'une tâche existante ou de
    l'équipe du projet (lot 13, décision 4) : projet visible (404 sinon),
    chef titulaire / co-chef / Admin, projet ouvert. Renvoie la réponse de
    refus, ou None. « Voir comme » (lecture seule) et le jeton CSRF sont
    contrôlés avant, pour toute écriture (app/modes_admin.py, CSRFProtect)."""
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    if not projets.user_can_manage(projet_id, g.user["id"]):
        return _refus(f"Seul le chef de projet, un co-chef ou un Admin peut {action}.", 403, projet_id)
    return _refus_si_clos(projet_id)


@bp.route("/<int:projet_id>/taches/<int:tache_id>/intervenants", methods=["POST"])
@login_required
def ajouter_intervenants_tache(projet_id: int, tache_id: int):
    """Affecter une ou plusieurs personnes à une tâche existante (lot 13,
    décision 4, audit rôles I6) : chef titulaire, co-chef ou Admin ;
    personnes actives, ni Client ni RH, qui voient le projet (les autres
    sont nommées dans le message). Notification aux personnes ajoutées,
    post automatique, audit (triggers)."""
    refus = _garde_gestion(projet_id, "affecter quelqu’un à une tâche")
    if refus:
        return refus
    retenus, ecartes = _intervenants_possibles(projet_id, request.form.getlist("utilisateur_id"))
    if not retenus:
        return _refus(("Personne à affecter." if not ecartes else _message_ecartes(ecartes).strip()), 422,
                      projet_id, tache_id, vers_tache=True)
    co_chefs_avant = projets.ids_co_chefs(projet_id)
    try:
        resultat = taches.ajouter_intervenants(tache_id, projet_id, retenus, g.user["id"])
    except taches.TacheClose:
        return _refus("Cette tâche est close\u00a0: rouvrez-la pour changer ses intervenants.", 409, projet_id, tache_id,
                      vers_tache=True)
    except Exception as exc:
        return _refus(_message_erreur_intervenant(exc, "d’affecter cette personne"), 422, projet_id, tache_id,
                      vers_tache=True)
    if resultat is None:
        return _refus("Tâche introuvable sur ce projet.", 404, projet_id)
    if not resultat["ajoutes"]:
        flash("Déjà affecté à cette tâche." + _message_ecartes(ecartes), "success")
    else:
        projet = projets.get_projet(projet_id)
        try:
            notifications_repo.creer_pour_plusieurs(
                resultat["ajoutes"], "projet",
                f"Nouvelle tâche pour vous\u00a0: «\u00a0{resultat['titre']}\u00a0» ({projet['code']}).",
                tache_id=tache_id, exclure_id=g.user["id"],
            )
        except Exception:
            current_app.logger.exception("Notification d'affectation impossible (tâche %s)", tache_id)
        co_chefs = _signaler_co_chefs(projet_id, projet, resultat["ajoutes"], co_chefs_avant)
        n = len(resultat["ajoutes"])
        flash(f"{n} intervenant{'s' if n > 1 else ''} ajouté{'s' if n > 1 else ''} à la tâche."
              + co_chefs + _message_ecartes(ecartes), "success")
    if partiel.est_partiel():
        return _reponse_tache(projet_id, tache_id)
    return _vers_tache(projet_id, tache_id)


@bp.route("/<int:projet_id>/taches/<int:tache_id>/intervenants/<int:utilisateur_id>/retirer", methods=["POST"])
@login_required
def retirer_intervenant_tache(projet_id: int, tache_id: int, utilisateur_id: int):
    """Retirer quelqu'un d'une tâche ouverte (lot 13, décision 4) : mêmes
    droits ; la personne est prévenue ; ses heures restent. En partiel :
    toast avec « Annuler » (la personne est réaffectée)."""
    refus = _garde_gestion(projet_id, "retirer quelqu’un d’une tâche")
    if refus:
        return refus
    try:
        resultat = taches.retirer_intervenant(tache_id, projet_id, utilisateur_id, g.user["id"])
    except taches.TacheClose:
        return _refus("Cette tâche est close\u00a0: rouvrez-la pour changer ses intervenants.", 409, projet_id, tache_id,
                      vers_tache=True)
    if resultat is None:
        return _refus("Tâche introuvable sur ce projet.", 404, projet_id)
    if not resultat:
        return _refus("Cette personne n’est pas affectée à cette tâche.", 409, projet_id, tache_id, vers_tache=True)
    if utilisateur_id != g.user["id"]:
        try:
            notifications_repo.creer(
                utilisateur_id, "projet",
                f"{g.user['prenom']} {g.user['nom']} vous a retiré de la tâche «\u00a0{resultat['titre']}\u00a0» du projet "
                f"«\u00a0{_code_nom(projets.get_projet(projet_id))}\u00a0».",
                projet_id=projet_id,
            )
        except Exception:
            current_app.logger.exception("Notification de retrait impossible (tâche %s)", tache_id)
    personne = resultat.get("personne") or {}
    message = f"{personne.get('prenom', '')} {personne.get('nom', '')} retiré de la tâche.".strip()
    if partiel.est_partiel():
        action = _action_annuler(url_for("projets.ajouter_intervenants_tache", projet_id=projet_id, tache_id=tache_id),
                                 {"utilisateur_id": str(utilisateur_id)}, tache_id)
        return _reponse_tache(projet_id, tache_id, [partiel.toast(message, action=action)])
    flash(message, "success")
    return _vers_tache(projet_id, tache_id)


@bp.route("/<int:projet_id>/taches/<int:tache_id>/echeance", methods=["POST"])
@login_required
def modifier_echeance_tache(projet_id: int, tache_id: int):
    """Échéance et type d'échéance d'une tâche ouverte (lot 13, décision 4) :
    chef titulaire, co-chef ou Admin. Champ date vide : sans échéance. Les
    intervenants de la tâche sont prévenus ; post automatique. En partiel :
    une date refusée est signalée sous le champ (422)."""
    refus = _garde_gestion(projet_id, "changer l’échéance d’une tâche")
    if refus:
        return refus
    type_deadline = request.form.get("type_deadline", "rendu_client")
    if type_deadline not in TYPE_DEADLINE_VALIDES:
        return _refus("Type d’échéance invalide.", 422, projet_id, tache_id, vers_tache=True,
                      champs={"type_deadline": "Type d’échéance invalide."})
    try:
        date_echeance = _parser_date_tache(request.form.get("date_echeance"))
    except ValueError:
        return _refus("Échéance invalide.", 422, projet_id, tache_id, vers_tache=True,
                      champs={"date_echeance": "Échéance invalide."})
    tache = taches.get_tache(tache_id)
    if tache is None or tache["projet_id"] != projet_id:
        return _refus("Tâche introuvable sur ce projet.", 404, projet_id)
    projet = projets.get_projet(projet_id) or {}
    erreur = v.premiere_erreur(
        v.date_hors_bornes(date_echeance, "Échéance"),
        v.ordre_dates(tache.get("date_debut"), date_echeance, "la date de début de la tâche", "Échéance"),
        v.ordre_dates(projet.get("date_debut"), date_echeance, "la date de début du projet", "Échéance"),
    )
    if erreur:
        return _refus(erreur, 422, projet_id, tache_id, vers_tache=True, champs={"date_echeance": erreur})
    try:
        resultat = taches.set_echeance(tache_id, projet_id, date_echeance, type_deadline, g.user["id"])
    except taches.TacheClose:
        return _refus("Cette tâche est close\u00a0: rouvrez-la pour changer son échéance.", 409, projet_id, tache_id,
                      vers_tache=True)
    if resultat is None:
        return _refus("Tâche introuvable sur ce projet.", 404, projet_id)
    if not resultat:
        flash("Échéance inchangée.", "success")
    else:
        try:
            intervenants = [i["id"] for i in (taches.list_taches_projet(projet_id, tache_id=tache_id) or [{}])[0]
                            .get("intervenants", [])]
            notifications_repo.creer_pour_plusieurs(
                intervenants, "projet",
                f"Échéance de la tâche «\u00a0{resultat['titre']}\u00a0» ({_code_nom(projet)})\u00a0: {resultat['avant']} → "
                f"{resultat['apres']}.",
                tache_id=tache_id, exclure_id=g.user["id"],
            )
        except Exception:
            current_app.logger.exception("Notification d'échéance impossible (tâche %s)", tache_id)
        flash(f"Échéance mise à jour\u00a0: {resultat['apres']}.", "success")
    if partiel.est_partiel():
        return _reponse_tache(projet_id, tache_id)
    return _vers_tache(projet_id, tache_id)


@bp.route("/<int:projet_id>/intervenants/<int:utilisateur_id>/retirer", methods=["POST"])
@login_required
def retirer_intervenant_projet(projet_id: int, utilisateur_id: int):
    """Retirer quelqu'un du projet (lot 13, décision 4) : co-chef,
    intervenant du projet et de ses tâches ouvertes ; jamais le chef
    titulaire. La personne est prévenue ; post automatique ; audit. En
    partiel : la carte Intervenants, les tâches et le fil suivent."""
    refus = _garde_gestion(projet_id, "retirer un intervenant du projet")
    if refus:
        return refus
    try:
        resultat = projets.retirer_intervenant(projet_id, utilisateur_id, g.user["id"])
    except projets.RetraitRefuse as exc:
        return _refus(exc.message, 409, projet_id)
    personne = resultat["personne"]
    if utilisateur_id != g.user["id"]:
        try:
            notifications_repo.creer(
                utilisateur_id, "projet",
                f"{g.user['prenom']} {g.user['nom']} vous a retiré du projet «\u00a0{_code_nom(projets.get_projet(projet_id))}\u00a0»"
                + (f" et de {len(resultat['taches'])} tâche(s) en cours." if resultat["taches"] else "."),
                projet_id=projet_id,
            )
        except Exception:
            current_app.logger.exception("Notification de retrait du projet impossible (projet %s)", projet_id)
    n = len(resultat["taches"])
    flash(f"{personne['prenom']} {personne['nom']} retiré du projet"
          + (f" et de {n} tâche{'s' if n > 1 else ''} en cours." if n else "."), "success")
    if partiel.est_partiel():
        if utilisateur_id == g.user["id"]:
            # Se retirer soi-même peut changer ses droits sur toute la page.
            return redirect(url_for("projets.detail", projet_id=projet_id))
        return _maj_fiche(projet_id, "intervenants", ["taches", "projet", "fil"])
    return redirect(url_for("projets.detail", projet_id=projet_id))


@bp.route("/<int:projet_id>/rejoindre", methods=["POST"])
@login_required
def rejoindre(projet_id: int):
    """Bouton « + Rejoindre ce projet » (retour Fadhel, 2026-09-28) :
    ajout immédiat de l'utilisateur connecté comme intervenant, sans
    validation d'un chef/co-chef — on ne s'ajoute que SOI-MÊME. Un chef de
    projet qui rejoint comme co-chef est signalé au chef du projet
    (décision Fadhel, lot 7). Lot 13 : en partiel, la carte Intervenants
    est remplacée ; en co-chef (droits de gestion sur toute la page), la
    fiche est rechargée."""
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    if g.user["role"] in ("rh", "client", "admin"):
        # Lot 18 : l'Admin gère déjà tous les projets (le bouton ne lui est
        # pas montré) ; un POST forgé ne l'inscrit plus comme intervenant.
        return _refus("Votre rôle ne permet pas de rejoindre un projet.", 403, projet_id)
    refus = _refus_si_clos(projet_id)
    if refus:
        return refus
    if projets.user_est_rattache(projet_id, g.user["id"]):
        flash("Vous êtes déjà rattaché à ce projet.", "success")
        if partiel.est_partiel():
            return _maj_fiche(projet_id, "intervenants", [])
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
        return _refus(_message_erreur_intervenant(exc, "de rejoindre ce projet"), 422, projet_id)
    if comme_co_chef:
        projet = projets.get_projet(projet_id)
        if projet and projet["chef_projet_id"] != g.user["id"]:
            notifications_repo.creer(
                projet["chef_projet_id"], "projet",
                f"{g.user['prenom']} {g.user['nom']} a rejoint votre projet «\u00a0{_code_nom(projet)}\u00a0» comme co-chef.",
                projet_id=projet_id,
            )
    flash("Vous avez rejoint le projet comme co-chef." if comme_co_chef else "Vous avez rejoint le projet.", "success")
    if partiel.est_partiel() and not comme_co_chef:
        return _maj_fiche(projet_id, "intervenants", ["fil"])
    return redirect(url_for("projets.detail", projet_id=projet_id))


@bp.route("/<int:projet_id>/taches/<int:tache_id>/rejoindre", methods=["POST"])
@login_required
def rejoindre_tache(projet_id: int, tache_id: int):
    """Bouton « rejoindre cette tâche » (retour Fadhel, 2026-09-28), au
    survol de la ligne ou dans le panneau : ajout immédiat de l'utilisateur
    connecté comme intervenant de la tâche, sans validation. Lot 13 : en
    partiel (la ligne ou le panneau, selon la cible ; la carte Intervenants
    suit)."""
    if not projets.user_can_view(projet_id, g.user["id"]):
        abort(404)
    if g.user["role"] in ("rh", "client"):
        return _refus("Votre rôle ne permet pas de rejoindre une tâche.", 403, projet_id)
    refus = _refus_si_clos(projet_id)
    if refus:
        return refus
    if taches.user_est_intervenant(tache_id, g.user["id"]):
        flash("Vous êtes déjà intervenant sur cette tâche.", "success")
        if partiel.est_partiel():
            return _reponse_tache(projet_id, tache_id)
        return redirect(url_for("projets.detail", projet_id=projet_id))

    try:
        ok = taches.add_intervenant(tache_id, projet_id, g.user["id"], g.user["id"])
    except taches.TacheClose:
        return _refus("Cette tâche est close\u00a0: on ne peut plus la rejoindre.", 409, projet_id)
    except Exception as exc:
        return _refus(_message_erreur_intervenant(exc, "de rejoindre cette tâche"), 422, projet_id)

    if not ok:
        return _refus("Tâche introuvable sur ce projet.", 404, projet_id)
    flash("Vous avez rejoint la tâche.", "success")
    if partiel.est_partiel():
        return _reponse_tache(projet_id, tache_id)
    return redirect(url_for("projets.detail", projet_id=projet_id))

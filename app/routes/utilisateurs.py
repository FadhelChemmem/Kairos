"""Pages Utilisateurs (liste + création) : gestion réservée à l'admin et au
RH, consultation en lecture seule pour le chef de projet —
pour que le RH puisse gérer les comptes sans passer par la commande CLI
`flask create-user` (voir app/__init__.py). La page "Infos perso" (`/moi`)
est différente : accessible à tout utilisateur connecté, uniquement sur
son propre compte (voir demande de Fadhel, 2026-09-19 : cliquer sur son
propre nom/avatar affiche ses infos, modifiables, avec le Daily log de la
semaine dernière)."""
import datetime
import secrets

from flask import (
    Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for,
)

from .. import fil as film
from .. import filtres_memoire, horloge, mailer, partiel
from ..auth import (
    MOT_DE_PASSE_MIN_LEN, generer_lien_reset, hash_password, login_required,
    password_fingerprint, role_required, verify_password,
)
from ..repositories import dailylog as dailylog_repo
from ..repositories import posts as posts_repo
from ..repositories import projets as projets_repo
from ..repositories import taches as taches_repo
from .. import push
from ..repositories import push as push_repo
from ..repositories import utilisateurs as utilisateurs_repo
from ..storage import MAX_OCTETS_AVATAR, delete_upload, est_vraie_image, is_image_filename, save_upload
from .. import validation as v
from ..utils import EQUIPE_CHOICES

bp = Blueprint("utilisateurs", __name__, url_prefix="/utilisateurs")

# RH et Client ne sont pas proposables depuis ce formulaire : RH est un
# rôle unique (voir idx_utilisateur_rh_singleton) affiché mais désactivé
# quand déjà attribué, et Client arrive à l'étape 2 (voir spec) — on ne
# l'affiche pas du tout pour l'instant, comme dans la maquette.
ROLES_CREABLES = ["intervenant", "chef_de_projet", "admin", "rh"]


def _roles_attribuables() -> list[str]:
    """Rôles que l'utilisateur connecté peut attribuer (décision 1 du
    gérant, lot 10) : le RH ne crée ni ne promeut jamais un Admin. Le
    trigger trg_garde_comptes_admin (migration 0013) l'interdit aussi en
    base."""
    if g.user["role"] == "admin":
        return list(ROLES_CREABLES)
    return [r for r in ROLES_CREABLES if r != "admin"]


def _cible_protegee(utilisateur: dict) -> bool:
    """Vrai si l'utilisateur connecté (RH) n'a pas le droit de toucher à ce
    compte : un compte Admin n'est modifiable que par un Admin (mot de
    passe, email, activation, rôle, fiche — décision 1, lot 10)."""
    return g.user["role"] != "admin" and utilisateur.get("role") == "admin"


# Champs par lesquels un mot de passe pourrait être fixé depuis la fiche ou
# la création (le second n'existe dans aucun formulaire : requête forgée).
CHAMPS_MOT_DE_PASSE = ("nouveau_mot_de_passe", "mot_de_passe")


def _refuser_mot_de_passe_hors_admin() -> None:
    """Décision du gérant (lot 10) : le RH ne fixe plus lui-même le mot de
    passe d'un employé — il envoie un lien de réinitialisation (voir
    envoyer_lien_reinitialisation). Le champ n'est plus affiché pour lui ;
    s'il est quand même envoyé (requête forgée), toute la requête est
    refusée (403) plutôt que le champ ignoré en silence. L'Admin garde la
    possibilité de fixer un mot de passe depuis la fiche."""
    if g.user["role"] != "admin" and any(request.form.get(c) for c in CHAMPS_MOT_DE_PASSE):
        abort(403)


def _motif_echec_email(email: str | None = None) -> str:
    """Raison affichée quand un e-mail n'a pas pu partir — jamais de faux
    succès (lot 10). Mode test (MAIL_DESTINATAIRES_AUTORISES, décision du
    gérant) : une adresse hors liste est dite comme telle."""
    if not mailer.est_configure():
        return "SMTP non configuré sur ce serveur"
    if email is not None and not mailer.destinataire_autorise(email):
        return ("mode test\u00a0: cette adresse n’est pas dans la liste des destinataires "
                "autorisés, MAIL_DESTINATAIRES_AUTORISES")
    return "serveur SMTP indisponible ou en erreur"


def _envoyer_lien_mot_de_passe(user_id: int, email: str, creation: bool) -> bool:
    """Génère un jeton (même mécanisme que « mot de passe oublié », voir
    auth.generer_lien_reset) et l'envoie, de façon synchrone, à `email` —
    l'adresse ENREGISTRÉE du compte, jamais une adresse saisie à côté.
    Retourne False si l'e-mail n'est pas parti, sans lever d'exception :
    le compte, lui, existe déjà. Adresse hors de MAIL_DESTINATAIRES_AUTORISES
    (mode test) : aucun jeton n'est généré, rien ne part."""
    if not mailer.destinataire_autorise(email):
        current_app.logger.warning("Lien de mot de passe non envoyé à %s (mode test des e-mails).",
                                   mailer.masquer(email))
        return False
    try:
        lien = generer_lien_reset(user_id, current_user_id=g.user["id"])
    except Exception:
        current_app.logger.exception("Lien de réinitialisation impossible à générer (id=%s)", user_id)
        return False
    if creation:
        sujet = "Kairos — création de votre compte"
        corps = (
            "Bonjour,\n\n"
            "Un compte Kairos vient d’être créé pour vous.\n\n"
            f"Adresse e-mail\u00a0: {email}\n\n"
            "Pour définir votre mot de passe et activer votre "
            f"compte, utilisez ce lien (valable 1 heure)\u00a0: {lien}\n\n"
            "Si ce lien a expiré, utilisez \"Mot de passe "
            "oublié\u202f?\" sur la page de connexion avec cette même "
            "adresse email pour en recevoir un nouveau."
        )
    else:
        sujet = "Kairos — réinitialisation de votre mot de passe"
        corps = (
            "Bonjour,\n\n"
            f"{g.user['prenom']} {g.user['nom']} vous a envoyé un lien pour "
            "choisir un nouveau mot de passe Kairos.\n\n"
            f"Ce lien est valable 1 heure\u00a0: {lien}\n\n"
            "Votre mot de passe actuel reste valable tant que vous n’en avez "
            "pas choisi un nouveau. Si vous n’attendiez pas ce message, "
            "prévenez l’administrateur."
        )
    return mailer.envoyer(email, sujet, corps)


def _message_garde_admin(exc: Exception) -> str | None:
    """Message clair pour les refus du trigger trg_garde_comptes_admin
    (migration 0013) — normalement déjà évités par les contrôles de route,
    qui n'en sont que le premier rempart."""
    texte = str(exc)
    if "dernier Admin actif" in texte:
        return "Impossible\u00a0: ce compte est le dernier Admin actif."
    if "Le RH ne peut ni créer" in texte:
        return "Seul un Admin peut créer, modifier ou désactiver un compte Admin."
    return None


def _enregistrer_avatar_si_fourni(user_id: int, current_user_id: int) -> None:
    """Photo de profil optionnelle (retour Fadhel, 2026-09-20) — n'importe
    quel formulaire de création/modification d'utilisateur qui accepte un
    champ fichier `avatar` passe par ici. Ignore silencieusement l'absence
    de fichier (soumission sans nouvelle photo) ; avertit sur un format
    non pris en charge sans faire échouer le reste du formulaire."""
    fichier = request.files.get("avatar")
    if not fichier or not fichier.filename:
        return
    if not is_image_filename(fichier.filename) or not est_vraie_image(fichier):
        # Lot 24 (SR-R16) : la vraie raison du refus.
        trop_grande = False
        try:
            fichier.stream.seek(0, 2)
            trop_grande = fichier.stream.tell() > MAX_OCTETS_AVATAR
            fichier.stream.seek(0)
        except (OSError, ValueError, AttributeError):
            pass
        flash("Photo de profil ignorée\u00a0: 10\u00a0Mo au plus." if trop_grande else
              "Photo de profil ignorée\u00a0: fichier illisible ou format non accepté (jpg, png, gif, webp).", "error")
        return
    _, chemin = save_upload(fichier, f"avatars/{user_id}")
    # Fichier orphelin sur disque si l'UPDATE échoue juste après (audit
    # sécurité/qualité externe, 2026-09-28, item P0-3).
    try:
        ancien = utilisateurs_repo.set_avatar(user_id, chemin, current_user_id)
    except Exception:
        delete_upload(chemin)
        raise
    # Lot 20 (rapport N7) : l'ancienne photo ne reste plus sur le disque.
    if ancien and ancien != chemin:
        try:
            delete_upload(ancien)
        except Exception:
            current_app.logger.warning("Ancienne photo de profil non supprimée\u00a0: %s", ancien)


# Rôles qui ne voient des projets que par leur équipe (lot 13, audit rôles M4).
ROLES_EQUIPE_OBLIGATOIRE = ("intervenant", "chef_de_projet")


ORDRE_CHAMPS = ("prenom", "nom", "avatar", "email", "telephone", "poste", "date_embauche", "adresse",
                "equipe_code", "role", "fuseau", "nouveau_mot_de_passe", "champs_perso",
                "mot_de_passe_actuel", "confirmation")


def _ordonner(erreurs: dict) -> dict:
    """Erreurs dans l'ordre du formulaire : la première reçoit le focus."""
    return {**{c: erreurs[c] for c in ORDRE_CHAMPS if c in erreurs},
            **{c: m for c, m in erreurs.items() if c not in ORDRE_CHAMPS}}


def _erreurs_fiche(prenom, nom, email, telephone, poste, adresse, date_embauche, equipe_code,
                   champs_perso) -> dict:
    """Contrôle commun des formulaires Créer / Modifier un utilisateur
    (retour Fadhel, lot 8 : « vérifier toutes les saisies »). Avant, un
    champ trop long, une équipe inconnue ou un email mal formé finissaient
    en « Impossible de créer ce compte » (erreur Postgres) ou passaient.
    Lot 13 (audit a11y I5) : une erreur par champ, {champ: message}."""
    import datetime

    erreurs: dict = {}

    def poser(champ, message):
        if message and champ not in erreurs:
            erreurs[champ] = message

    poser("prenom", v.trop_long(prenom, v.MAX_PRENOM_NOM, "Prénom"))
    poser("nom", v.trop_long(nom, v.MAX_PRENOM_NOM, "Nom"))
    if email:
        poser("email", v.email_invalide(email))
    poser("telephone", v.telephone_invalide(telephone))
    poser("poste", v.trop_long(poste, v.MAX_POSTE, "Poste"))
    poser("adresse", v.trop_long(adresse, v.MAX_ADRESSE, "Adresse"))
    poser("date_embauche", v.date_hors_bornes(date_embauche, "Date d’embauche"))
    if date_embauche and date_embauche > horloge.aujourdhui() + datetime.timedelta(days=366):
        poser("date_embauche", "Date d’embauche invalide\u00a0: plus d’un an dans le futur.")
    if equipe_code and equipe_code not in {c for c, _ in EQUIPE_CHOICES}:
        poser("equipe_code", "Équipe invalide.")
    if len(champs_perso) > v.MAX_CHAMPS_PERSO:
        poser("champs_perso", f"{v.MAX_CHAMPS_PERSO} champs personnalisés au plus.")
    poser("champs_perso", next((f"Champ personnalisé «\u00a0{n[:30]}\u00a0»\u00a0: nom ou valeur trop long." for n, val in champs_perso.items()
                                if len(n) > v.MAX_CHAMP_PERSO_NOM or len(val) > v.MAX_CHAMP_PERSO_VALEUR), None))
    return erreurs


def _erreur_fiche(prenom, nom, email, telephone, poste, adresse, date_embauche, equipe_code,
                  champs_perso) -> str | None:
    """Premier message de _erreurs_fiche (ou None)."""
    erreurs = _erreurs_fiche(prenom, nom, email, telephone, poste, adresse, date_embauche, equipe_code, champs_perso)
    return next(iter(erreurs.values()), None)


def _resume_erreurs(erreurs: dict) -> str:
    """Message d'ensemble (rendu complet sans JavaScript, en plus des
    messages sous les champs)."""
    manquants = [c for c in ("prenom", "nom", "email") if erreurs.get(c) == "Obligatoire."]
    if manquants:
        return "Prénom, nom et email sont obligatoires."
    return next(iter(erreurs.values()))


def _parser_date_embauche(date_str: str | None):
    """Date d'embauche du formulaire Créer/Modifier un utilisateur — même
    principe que projets._parser_date_tache/dailylog._parser_date/
    admin._parser_date : None si absent/vide, lève ValueError sur un
    format invalide. Avant ce correctif, date_embauche n'était pas validée
    du tout côté applicatif — un format invalide (requête forgée ; le
    <input type="date"> normal ne peut pas en produire) plantait
    l'INSERT/UPDATE en erreur Postgres brute au lieu d'un message clair,
    contrairement au même champ de date pour les tâches/projets (audit
    sécurité/qualité externe, 2026-09-28, relecture Luna round 4)."""
    if not date_str:
        return None
    return datetime.date.fromisoformat(date_str)


def _jours_daily_log(utilisateur: dict, jours: list, projets_visibles_ids: set | None) -> list[dict]:
    """Daily log de `utilisateur` sur `jours`, en DEUX requêtes (lignes et
    absences de la période) au lieu d'une par jour (lot 10 : jusqu'à 84
    requêtes pour « 12 semaines »).

    `projets_visibles_ids` : pour le Daily log d'une AUTRE personne, seules
    les lignes des projets que le visiteur peut voir (audit du 2026-09-29) —
    retirées, pas masquées : un profil ne doit pas laisser deviner qu'une
    personne travaille sur un projet d'une autre équipe."""
    if not jours:
        return []
    debut, fin = min(jours), max(jours)
    par_jour: dict = {}
    for e in dailylog_repo.list_entrees_periode(utilisateur["id"], debut, fin):
        if projets_visibles_ids is not None and e["projet_id"] not in projets_visibles_ids:
            continue
        par_jour.setdefault(e["date"], []).append(e)
    absents = dailylog_repo.jours_absents(utilisateur["id"], debut, fin)
    return [
        {
            "date": jour,
            "entrees": par_jour.get(jour, []),
            "total_heures": sum(float(e["heures"]) for e in par_jour.get(jour, [])),
            "absent": jour in absents,
        }
        for jour in jours
    ]


def _peut_corriger(utilisateur: dict) -> bool:
    """Lien « Corriger » (lot 10) : l'Admin et les chefs de projet ouvrent le
    Daily log d'un employé ; la page ne leur laisse modifier que ce qu'ils
    ont le droit de corriger (lignes de leurs projets pour un chef)."""
    return (g.user["role"] in ("admin", "chef_de_projet") and utilisateur["id"] != g.user["id"]
            and utilisateur.get("role") in ("admin", "chef_de_projet", "intervenant"))


def _semaine_derniere(utilisateur: dict, projets_visibles_ids: set | None = None) -> list[dict]:
    """Daily log en lecture seule de la semaine dernière — lundi à vendredi
    uniquement (retour Fadhel, 2026-09-21 : "ne pas afficher samedi et
    dimanche"), partagé par /moi (mon_profil) et par la fiche en lecture
    seule d'un chef de projet. Semaine calculée au fuseau de la personne
    (lot 10)."""
    aujourdhui = dailylog_repo.aujourdhui_pour(utilisateur)
    lundi_cette_semaine = aujourdhui - datetime.timedelta(days=aujourdhui.weekday())
    lundi_semaine_derniere = lundi_cette_semaine - datetime.timedelta(days=7)
    jours = [lundi_semaine_derniere + datetime.timedelta(days=i) for i in range(5)]
    return _jours_daily_log(utilisateur, jours, projets_visibles_ids)


def _dix_jours_ouvres(utilisateur: dict, projets_visibles_ids: set | None) -> list[dict]:
    """Fiche d'une personne vue par l'Admin ou un chef (lot 14, revue
    produit P1-9) : les 10 derniers jours ouvrés, aujourd'hui compris, du
    plus récent au plus ancien, avec leur état (rempli, absent, non
    renseigné…) calculé sur TOUTES les heures du jour ; les lignes
    affichées restent limitées aux projets que le visiteur voit."""
    jours = dailylog_repo.jours_ouvres_recents(dailylog_repo.aujourdhui_pour(utilisateur), 10)
    synthese = dailylog_repo.synthese_periode([utilisateur["id"]], min(jours), max(jours))
    sortie = _jours_daily_log(utilisateur, jours, projets_visibles_ids)
    for jour in sortie:
        case = synthese.get((utilisateur["id"], jour["date"]))
        jour["etat"] = dailylog_repo.etat_case(utilisateur, jour["date"], case)
    return sortie


def _fenetre_7_jours(utilisateur: dict, projets_visibles_ids: set, nb_jours: int = 7) -> list[dict]:
    """Daily log glissant (aujourd'hui inclus, en remontant, au fuseau de la
    personne), pour la page de profil d'une personne (Lot 5, retour Fadhel,
    2026-09-28 : "fenêtre 7 jours"). Du plus récent au plus ancien : « Voir
    + » ajoute les semaines précédentes en dessous. Lot 15 : un samedi ou un
    dimanche sans heures n'est plus listé (« 0 h · Corriger » sans objet)."""
    aujourdhui = dailylog_repo.aujourdhui_pour(utilisateur)
    jours = [aujourdhui - datetime.timedelta(days=i) for i in range(nb_jours)]
    sortie = [j for j in _jours_daily_log(utilisateur, jours, projets_visibles_ids)
              if j["date"].weekday() < 5 or j.get("entrees") or j.get("absent")]
    # Lot 15 (page unique, reprise de la fiche du lot 14) : état réel de
    # chaque jour ouvré (rempli, non renseigné, pas encore saisi…), calculé
    # sur TOUTES les heures du jour ; les lignes restent filtrées.
    synthese = dailylog_repo.synthese_periode([utilisateur["id"]], min(jours), max(jours))
    for jour in sortie:
        if jour["date"].weekday() < 5:
            jour["etat"] = dailylog_repo.etat_case(utilisateur, jour["date"], synthese.get((utilisateur["id"], jour["date"])))
    return sortie


@bp.route("/<int:user_id>/profil")
@login_required
def profil_personne(user_id: int):
    """Page de profil d'une personne (Lot 5, retour Fadhel, 2026-09-28) :
    "accessible via la recherche topbar 'chercher des personnes' — profil,
    daily logs, tâches en cours, posts récents, fenêtre 7 jours". Ouverte
    à TOUT utilisateur connecté (contrairement à fiche()/liste(), réservées
    à admin/RH/chef de projet) : strictement en lecture seule, et avec des
    champs volontairement limités (pas d'email/téléphone/adresse — ceux-là
    restent réservés à la fiche RH). Tout ce qui référence un projet
    (DailyLog, tâches, posts) est filtré à ce que LE VISITEUR peut voir,
    pas la personne consultée (voir _fenetre_7_jours/list_en_cours_pour_profil/
    list_feed_auteur) : sinon un profil deviendrait un détour pour voir les
    projets d'une équipe à laquelle on n'appartient pas (IDOR,
    PROMPT_CORRECTIONS.md P0 #1)."""
    utilisateur = utilisateurs_repo.get_utilisateur(user_id)
    if utilisateur is None:
        flash("Utilisateur introuvable.", "error")
        return redirect(url_for("main.accueil"))
    # Lot 13 (audit rôles M2) : un Client ne consulte pas le profil d'un
    # compte désactivé (la recherche les lui masque déjà).
    if g.user["role"] == "client" and not utilisateur.get("actif") and user_id != g.user["id"]:
        # Lot 20 (rapport N6) : même réponse qu'un compte inexistant — un
        # 404 ici révélait quels identifiants sont des comptes désactivés.
        flash("Utilisateur introuvable.", "error")
        return redirect(url_for("main.accueil"))

    viewer_id = g.user["id"]
    projets_visibles_ids = projets_repo.list_ids_visibles(viewer_id)
    # "Ce qui est récent, sur une semaine, avec la possibilité de voir +"
    # (retour Fadhel, J.docx, T3) : daily log et posts de la dernière
    # semaine ; chaque "Voir +" ajoute une semaine (12 au plus).
    semaines = min(max(request.args.get("semaines", 1, type=int) or 1, 1), 12)
    depuis = dailylog_repo.aujourdhui_pour(g.user) - datetime.timedelta(days=7 * semaines - 1)
    # Lot 14 (revue produit P1-3) : Tout · Échanges · Activité, évènements
    # automatiques regroupés.
    fil_categorie = film.categorie_demandee("profil")
    posts_recents = posts_repo.list_feed_auteur(user_id, viewer_id, limit=100, depuis=depuis, categorie=fil_categorie)
    posts_plus_anciens = bool(posts_repo.list_feed_auteur(user_id, viewer_id, limit=1, avant=depuis,
                                                          categorie=fil_categorie))
    fil_posts = dict(posts_recents=posts_recents, posts_plus_anciens=posts_plus_anciens,
                     fil_entrees=film.regrouper(posts_recents), fil_categorie=fil_categorie)
    if partiel.est_partiel() == "#profil-posts":
        return partiel.repondre("partials/profil_posts_liste.html", utilisateur=utilisateur, semaines=semaines,
                                **fil_posts)
    # Daily log d'un collègue (audit sécurité I5, lot 10) : spec du 16/09
    # « intervenant = accès limité à ses tâches/Daily log », le chef voit
    # tout (18/09). Visible pour soi-même, l'Admin et le chef de projet ;
    # plus pour un intervenant. Client : visible en lecture (décision du
    # gérant, fin du lot 10 — le Client voit heures, honoraires et pièces
    # jointes des projets qu'il voit), limité à ces projets comme pour
    # tout le monde (projets_visibles_ids).
    voir_daily_log = (utilisateur.get("role") in ("admin", "chef_de_projet", "intervenant")
                      and (user_id == viewer_id or g.user["role"] in ("admin", "chef_de_projet", "client")))
    jours = (_fenetre_7_jours(utilisateur, projets_visibles_ids, nb_jours=7 * semaines)
             if voir_daily_log else None)
    if jours is not None and g.user["role"] == "client" and user_id != viewer_id:
        # Lot 13 (audit rôles M2) : un Client ne voit que les heures posées
        # sur SES projets — ni les absences, ni les jours sans rien pour lui.
        jours = [{**j, "absent": False} for j in jours if j["entrees"]]

    # Premier jour qu'ajoutera « Voir la semaine précédente » (focus).
    # Lot 15 : les samedis et dimanches sans heures n'étant plus listés, le
    # premier jour ajouté est le dernier jour ouvré avant la fenêtre.
    jour_suivant = None
    if jours:
        jour_suivant = jours[-1]["date"] - datetime.timedelta(days=1)
        while jour_suivant.weekday() >= 5:
            jour_suivant -= datetime.timedelta(days=1)
    if partiel.est_partiel():
        # Lot 13 : « Voir la semaine précédente » — Daily log et posts
        # remplacés en place (#profil-activite), l'adresse suit.
        return partiel.repondre(
            "partials/profil_activite.html", utilisateur=utilisateur, jours=jours, jour_suivant=jour_suivant,
            peut_corriger=voir_daily_log and _peut_corriger(utilisateur), semaines=semaines,
            utilisateurs_actifs=utilisateurs_repo.list_actifs(), **fil_posts,
        )
    projets_postables = [p for p in projets_repo.list_mes_projets_recents(viewer_id, limit=500)
                         if p["etat"] in ("en_cours", "bloque")]
    return render_template(
        "utilisateur_profil_personne.html",
        utilisateur=utilisateur, jour_suivant=jour_suivant,
        jours=jours,
        peut_corriger=voir_daily_log and _peut_corriger(utilisateur),
        semaines=semaines,
        # Lot 15 : une seule page par personne — ses tâches ouvertes (retards,
        # bloquées) et ses projets en cours, le contact pour qui gère.
        taches_ouvertes=taches_repo.list_ouvertes_pour_profil(user_id, viewer_id, dailylog_repo.aujourdhui_pour(g.user)),
        projets_en_cours=projets_repo.list_en_cours_pour_profil(user_id, viewer_id),
        aujourdhui=dailylog_repo.aujourdhui_pour(g.user),
        voir_contact=g.user["role"] in ("admin", "rh", "chef_de_projet") or user_id == viewer_id,
        peut_modifier_fiche=g.user["role"] in ("admin", "rh") and not _cible_protegee(utilisateur),
        **fil_posts,
        # Lot 5 (retour Fadhel, 2026-09-28) : "@ Taguer" dans le
        # composeur de commentaire de post_card.html a besoin de la même
        # liste que sur l'accueil/la page projet (voir main.accueil /
        # projets.detail) — sinon le champ de tag serait vide ici.
        utilisateurs_actifs=utilisateurs_repo.list_actifs(),
        # "Reposter" ouvre la fenêtre "Nouveau post" (2026-09-29) : mêmes
        # données que sur l'accueil (voir main.accueil).
        projets_postables=projets_postables,
        voient_par_projet=projets_repo.ids_voient_projets(projets_postables),
        collaborateurs_recents=utilisateurs_repo.list_collaborateurs_recents(viewer_id),
    )


@bp.route("")
@role_required("admin", "rh", "chef_de_projet")
def liste():
    q = request.args.get("q") or None
    # Lot 23 (décision du gérant) : équipe, rôle et état mémorisés par
    # personne (app/filtres_memoire.py) ; la recherche reste dans l'adresse.
    retour = filtres_memoire.redirection("equipe", "utilisateurs.liste", q=q)
    if retour is not None:
        return retour
    source = filtres_memoire.source("equipe") or {}
    equipe_code = source.get("equipe_code") or None
    # Lot 24 (FI-06) : équipe hors liste ignorée, comme le rôle et l'état.
    if equipe_code not in {code for code, _ in EQUIPE_CHOICES}:
        equipe_code = None
    role = source.get("role") or None
    # Valeur hors role_enum (URL forgée) : erreur 500 « invalid input value
    # for enum » auparavant (audit sécurité I14) -> filtre ignoré.
    if role not in (None, "admin", "chef_de_projet", "intervenant", "rh", "client"):
        role = None
    actif_param = source.get("actif") or None
    if actif_param not in (None, "actifs", "inactifs", "tous"):
        actif_param = None
    filtres_memoire.memoriser("equipe", {"filtres_actifs": "1", "equipe_code": equipe_code, "role": role,
                                         "actif": actif_param})
    actif = {"actifs": True, "inactifs": False}.get(actif_param)

    tous = utilisateurs_repo.list_tous(q=q, equipe_code=equipe_code, role=role, actif=actif)
    compte = utilisateurs_repo.compter()
    # Lot 13 : filtres appliqués en mise à jour partielle (tableau seul,
    # compteur hors cible).
    if partiel.est_partiel():
        return partiel.repondre(
            "partials/utilisateurs_resultats.html", oob_compte=True,
            utilisateurs=tous, compte=compte, peut_gerer=g.user["role"] in ("admin", "rh"),
            q=q or "", equipe_code=equipe_code, role=role, actif_param=actif_param or "",
        )
    # Lot 11 (vue Admin) : projets ouverts dont le chef est désactivé, à
    # réaffecter — la fenêtre Informations ne change pas le chef : liste
    # avec un lien vers chaque projet.
    projets_chef_inactif = projets_repo.list_ouverts_chef_inactif() if g.user["role"] == "admin" else []

    return render_template(
        "utilisateurs_liste.html",
        utilisateurs=tous, compte=compte, projets_chef_inactif=projets_chef_inactif,
        q=q or "", equipe_code=equipe_code, role=role, actif_param=actif_param or "",
        equipe_choices=EQUIPE_CHOICES,
    )


@bp.route("/nouveau", methods=["GET", "POST"])
@role_required("admin", "rh")
def creer():
    erreurs: dict = {}
    if request.method == "POST":
        _refuser_mot_de_passe_hors_admin()
        prenom = request.form.get("prenom", "").strip()
        nom = request.form.get("nom", "").strip()
        email = request.form.get("email", "").strip()
        telephone = request.form.get("telephone", "").strip() or None
        poste = request.form.get("poste", "").strip() or None
        adresse = request.form.get("adresse", "").strip() or None
        date_embauche = request.form.get("date_embauche") or None
        equipe_code = request.form.get("equipe_code") or None
        role = request.form.get("role", "intervenant")
        actif_compte = request.form.get("actif") == "on"
        fuseau = request.form.get("fuseau") or dailylog_repo.FUSEAU_DEFAUT

        noms_champs = request.form.getlist("champ_perso_nom")
        valeurs_champs = request.form.getlist("champ_perso_valeur")
        champs_perso = {
            n.strip(): v.strip()
            for n, v in zip(noms_champs, valeurs_champs)
            if n.strip()
        }

        try:
            date_embauche_valide = _parser_date_embauche(date_embauche)
        except ValueError:
            date_embauche_valide = False

        # Lot 13 (audit a11y I5) : toutes les erreurs, chacune sous son champ.
        for champ, valeur in (("prenom", prenom), ("nom", nom), ("email", email)):
            if not valeur:
                erreurs[champ] = "Obligatoire."
        if role not in _roles_attribuables():
            erreurs["role"] = "Rôle invalide."
        if fuseau not in dailylog_repo.FUSEAUX:
            erreurs["fuseau"] = "Bureau (fuseau horaire) invalide."
        if date_embauche_valide is False:
            erreurs["date_embauche"] = "Date d’embauche invalide."
        if role in ROLES_EQUIPE_OBLIGATOIRE and not equipe_code:
            # Lot 13 (audit rôles M4) : sans équipe, un intervenant ou un chef
            # de projet ne voit aucun projet et n'a rien à saisir.
            erreurs["equipe_code"] = "Choisissez l’équipe de ce compte (intervenant ou chef de projet)."
        for champ, message in _erreurs_fiche(prenom, nom, email, telephone, poste, adresse,
                                             date_embauche_valide or None, equipe_code, champs_perso).items():
            erreurs.setdefault(champ, message)
        if not erreurs:
            try:
                # Pas de mot de passe défini ici (retour Fadhel, 2026-09-21 :
                # "ne pas définir un mot de passe à la création, envoyer un
                # mail pour que l'utilisateur fasse son propre mot de
                # passe") — un hash aléatoire et jamais communiqué occupe la
                # colonne (NOT NULL) le temps que l'utilisateur définisse le
                # sien via le lien reçu par email, exactement comme pour
                # "mot de passe oublié". `verifie=False` tant qu'il ne l'a
                # pas fait (set_password le passera à true).
                user_id = utilisateurs_repo.create_utilisateur(
                    email=email, mot_de_passe_hash=hash_password(secrets.token_urlsafe(32)),
                    prenom=prenom, nom=nom, role=role, telephone=telephone,
                    poste=poste, adresse=adresse, date_embauche=date_embauche_valide,
                    equipe_code=equipe_code, verifie=False, actif=actif_compte,
                    champs_perso=champs_perso, current_user_id=g.user["id"], fuseau=fuseau,
                )
            except Exception as exc:
                if "idx_utilisateur_rh_singleton" in str(exc):
                    erreurs["role"] = ("Il y a déjà un compte RH actif. Désactivez-le d’abord "
                                       "pour en créer un nouveau.")
                elif "idx_utilisateur_email_lower" in str(exc):
                    erreurs["email"] = f"Un compte existe déjà avec l’email {email}."
                else:
                    flash("Impossible de créer ce compte.", "error")
            else:
                # À partir d'ici le compte EXISTE (lot 10) : une panne de la
                # photo, du jeton ou de l'e-mail ne doit plus finir en
                # « Impossible de créer ce compte » — on le recréerait en
                # doublon. Chaque étape est donc isolée et signalée.
                try:
                    _enregistrer_avatar_si_fourni(user_id, g.user["id"])
                except Exception:
                    current_app.logger.exception("Photo de profil non enregistrée (id=%s)", user_id)
                    flash("Photo de profil non enregistrée — ajoutez-la depuis la fiche.", "error")
                if not actif_compte:
                    flash(
                        f"Compte créé pour {prenom} {nom} (inactif) — aucun "
                        "email envoyé. Réactivez le compte pour qu’il puisse "
                        "définir son mot de passe.", "success",
                    )
                elif _envoyer_lien_mot_de_passe(user_id, email, creation=True):
                    flash(
                        f"Compte créé pour {prenom} {nom}. Un email lui a été "
                        "envoyé pour qu’il définisse son mot de passe.", "success",
                    )
                else:
                    # Le RH ne fixe plus de mot de passe (décision du gérant,
                    # lot 10) : seul l'Admin se voit proposer cette option.
                    autre_option = (
                        ", ou définissez-lui un mot de passe depuis sa fiche"
                        if g.user["role"] == "admin" else ""
                    )
                    # Revue produit (§ 3) : deux phrases au lieu de quatre lignes.
                    flash(
                        f"Compte créé pour {prenom} {nom}, mais l’e-mail n’a pas pu être envoyé "
                        f"({_motif_echec_email(email)}). Renvoyez-lui le lien depuis sa fiche "
                        f"(«\u00a0Envoyer un lien de réinitialisation\u00a0»){autre_option}.", "error",
                    )
                # Lot 13 : en mise à jour partielle, la redirection devient
                # une navigation (204 + X-Kairos-Redirection), messages compris.
                return redirect(url_for("utilisateurs.liste"))
        erreurs = _ordonner(erreurs)
        if erreurs and not partiel.est_partiel():
            flash(_resume_erreurs(erreurs), "error")

    contexte = dict(equipe_choices=EQUIPE_CHOICES, rh_titulaire=utilisateurs_repo.rh_deja_attribue(),
                    fuseaux=dailylog_repo.FUSEAUX, erreurs=erreurs)
    if partiel.est_partiel():
        return partiel.repondre("partials/utilisateur_creer_form.html", statut=422 if erreurs else 200, **contexte)
    return render_template("utilisateur_creer.html", **contexte)


def _rendre_mon_profil(erreurs_infos=None, erreurs_mdp=None, statut=200):
    utilisateur = utilisateurs_repo.get_utilisateur(g.user["id"])
    if erreurs_infos:
        # Saisie réaffichée telle quelle, à corriger.
        utilisateur = {**utilisateur, **{c: request.form.get(c, "") for c in ("telephone", "adresse")}}
    # Daily log de la semaine dernière (lundi → vendredi — voir
    # _semaine_derniere), demandé par Fadhel (2026-09-19), affiché en
    # lecture seule ici (la saisie reste sur /dailylog ; chaque ligne y
    # renvoie directement, voir utilisateur_profil.html).
    return render_template(
        "utilisateur_profil.html", utilisateur=utilisateur, semaine_derniere=_semaine_derniere(utilisateur),
        preferences=utilisateurs_repo.get_preferences(g.user["id"]),
        erreurs_infos=erreurs_infos or {}, erreurs_mdp=erreurs_mdp or {},
        # Lot 24 : notifications Windows (app/push.py).
        push_categories=push_repo.get_categories(g.user["id"]), push_libelles=push.CATEGORIES,
    ), statut


@bp.route("/moi", methods=["GET", "POST"])
@login_required
def mon_profil():
    user_id = g.user["id"]

    if request.method == "POST":
        # Lot 15 : le poste n'est plus modifiable par la personne (Admin et
        # RH seulement, fiche Utilisateurs) ; un champ envoyé est ignoré.
        telephone = request.form.get("telephone", "").strip() or None
        adresse = request.form.get("adresse", "").strip() or None
        erreurs = {c: m for c, m in (
            ("telephone", v.telephone_invalide(telephone)),
            ("adresse", v.trop_long(adresse, v.MAX_ADRESSE, "Adresse")),
        ) if m}
        if erreurs:
            # Lot 13 (audit a11y I5) : message sous le champ, focus dessus ;
            # la saisie n'est plus perdue (redirection auparavant).
            if partiel.est_partiel():
                utilisateur = {**utilisateurs_repo.get_utilisateur(user_id),
                               "telephone": telephone, "adresse": adresse}
                return partiel.repondre("partials/mes_infos_form.html", statut=422, utilisateur=utilisateur,
                                        erreurs_infos=erreurs)
            flash(next(iter(erreurs.values())), "error")
            return _rendre_mon_profil(erreurs_infos=erreurs)
        utilisateurs_repo.update_profil(
            user_id, telephone=telephone, adresse=adresse,
            current_user_id=user_id,
        )
        photo = bool(request.files.get("avatar") and request.files["avatar"].filename)
        _enregistrer_avatar_si_fourni(user_id, user_id)
        flash("Vos informations ont été mises à jour.", "success")
        if partiel.est_partiel():
            # Formulaire remplacé en place ; la photo suit dans l'en-tête de
            # la carte et dans la barre du haut (hors cible).
            return partiel.repondre("partials/mes_infos_form.html", utilisateur=utilisateurs_repo.get_utilisateur(user_id),
                                    erreurs_infos={}, oob_avatar=photo)
        return redirect(url_for("utilisateurs.mon_profil"))

    return _rendre_mon_profil()


@bp.route("/moi/mot-de-passe", methods=["POST"])
@login_required
def mon_mot_de_passe():
    """Changement de son propre mot de passe, depuis "Infos perso" (retour
    Fadhel, 2026-09-21 : "donner la possibilité dans son espace de modifier
    son mot de passe") — formulaire séparé de mon_profil() (pas le même
    enctype, et une erreur ici ne doit pas faire perdre les autres champs).
    L'ancien mot de passe est exigé, comme tout changement de mot de passe
    volontaire par son titulaire. Lot 13 (audit a11y I5) : l'erreur est
    reliée à son champ, qui reçoit le focus."""
    user_id = g.user["id"]
    actuel = request.form.get("mot_de_passe_actuel", "")
    nouveau = request.form.get("nouveau_mot_de_passe", "")
    confirmation = request.form.get("confirmation", "")

    hash_actuel = utilisateurs_repo.get_mot_de_passe_hash(user_id)

    erreurs = {}
    # Lot 18 (audit sécurité) : même freinage que la connexion — avec un
    # cookie volé ou un poste laissé ouvert, l'ancien mot de passe ne se
    # devine plus à la chaîne. Compté sous le type « connexion » avec une
    # clé propre (pas de migration).
    from ..auth import FENETRE_TENTATIVES_MINUTES, MAX_TENTATIVES
    from ..repositories import securite as securite_repo

    cle_mdp = f"changement-mdp|{user_id}"
    if securite_repo.compter_tentatives_recentes("connexion", cle_mdp, FENETRE_TENTATIVES_MINUTES) >= MAX_TENTATIVES:
        erreurs["mot_de_passe_actuel"] = "Trop de tentatives. Réessayez dans quelques minutes."
    elif hash_actuel is None or not verify_password(actuel, hash_actuel):
        securite_repo.enregistrer_tentative("connexion", cle_mdp)
        erreurs["mot_de_passe_actuel"] = "Mot de passe actuel incorrect."
    elif nouveau != confirmation:
        erreurs["confirmation"] = "Les deux nouveaux mots de passe ne correspondent pas."
    elif len(nouveau) < MOT_DE_PASSE_MIN_LEN:
        erreurs["nouveau_mot_de_passe"] = f"Le nouveau mot de passe doit faire au moins {MOT_DE_PASSE_MIN_LEN} caractères."
    else:
        nouveau_hash = hash_password(nouveau)
        utilisateurs_repo.set_password(user_id, nouveau_hash, user_id)
        # Garder CETTE session connectée après le changement — seules les
        # AUTRES sessions ouvertes pour ce compte doivent être invalidées
        # (PROMPT_CORRECTIONS.md P2 #17, voir load_logged_in_user()) : sans
        # cette ligne, la prochaine requête déconnecterait aussi
        # l'utilisateur qui vient de changer son propre mot de passe.
        session["pw_fingerprint"] = password_fingerprint(nouveau_hash)
        flash("Mot de passe changé.", "success")

    if partiel.est_partiel():
        return partiel.repondre("partials/mot_de_passe_form.html", statut=422 if erreurs else 200, erreurs_mdp=erreurs)
    if erreurs:
        flash(next(iter(erreurs.values())), "error")
        return _rendre_mon_profil(erreurs_mdp=erreurs)
    return redirect(url_for("utilisateurs.mon_profil"))


@bp.route("/<int:user_id>", methods=["GET", "POST"])
@role_required("admin", "rh", "chef_de_projet")
def fiche(user_id: int):
    """Fiche complète d'un utilisateur, modifiable par l'admin/RH (retour
    Fadhel, 2026-09-20 : "donner la main au RH et admin de voir les fichiers
    utilisateurs et de modifier les informations"). Contrairement à
    /moi (libre-service, limité), tout est modifiable ici, y compris le
    rôle — SAUF le sien propre : on ne peut pas se retirer soi-même son
    rôle admin par erreur depuis cet écran (même logique que
    toggle_actif, qui bloque déjà l'auto-désactivation).

    Un chef de projet, lui, n'a accès qu'à une vue en lecture seule — nom,
    téléphone et DailyLog de la semaine dernière, rien de plus (retour
    Fadhel, 2026-09-21 : "laisser la possibilité aux chefs de projet de
    voir n'importe qui... sans pouvoir modifier ça"). On sort avant tout
    traitement de POST : un chef de projet ne peut rien modifier depuis
    cet écran, même par une requête forgée à la main."""
    utilisateur = utilisateurs_repo.get_utilisateur(user_id)
    if utilisateur is None:
        flash("Utilisateur introuvable.", "error")
        return redirect(url_for("utilisateurs.liste"))

    # Lot 15 : une seule page par personne. Le chef de projet (lecture
    # seule) arrive sur la page de la personne, qui montre aussi son
    # téléphone, ses tâches, ses projets et son Daily log.
    if g.user["role"] == "chef_de_projet":
        return redirect(url_for("utilisateurs.profil_personne", user_id=user_id))

    enregistre = utilisateur
    if request.method == "POST" and _cible_protegee(utilisateur):
        if partiel.est_partiel():
            return partiel.refuser("Seul un Admin peut modifier le compte d’un Admin.", 403)
        flash("Seul un Admin peut modifier le compte d’un Admin.", "error")
        return redirect(url_for("utilisateurs.fiche", user_id=user_id))

    erreurs: dict = {}
    if request.method == "POST":
        _refuser_mot_de_passe_hors_admin()
        prenom = request.form.get("prenom", "").strip()
        nom = request.form.get("nom", "").strip()
        email = request.form.get("email", "").strip()
        telephone = request.form.get("telephone", "").strip() or None
        poste = request.form.get("poste", "").strip() or None
        adresse = request.form.get("adresse", "").strip() or None
        date_embauche = request.form.get("date_embauche") or None
        equipe_code = request.form.get("equipe_code") or None
        role = request.form.get("role", utilisateur["role"])
        fuseau = request.form.get("fuseau") or utilisateur.get("fuseau") or dailylog_repo.FUSEAU_DEFAUT

        noms_champs = request.form.getlist("champ_perso_nom")
        valeurs_champs = request.form.getlist("champ_perso_valeur")
        champs_perso = {
            n.strip(): v.strip()
            for n, v in zip(noms_champs, valeurs_champs)
            if n.strip()
        }

        # Validation du rôle (PROMPT_CORRECTIONS.md P1 #11) : le champ
        # <select> du formulaire n'offre que les rôles de ROLES_CREABLES,
        # mais rien côté serveur n'empêchait auparavant une requête forgée
        # à la main de poser n'importe quelle valeur — acceptée telle
        # quelle par update_utilisateur_complet(), sans même la contrainte
        # DB (pas de CHECK sur utilisateur.role). `role != utilisateur["role"]`
        # laisse passer un rôle inchangé même hors ROLES_CREABLES : "client"
        # (role_enum, schema.sql) existe en base — via `flask create-user
        # --role client` — mais n'est pas encore proposable depuis cet écran
        # (étape 2, voir ROLES_CREABLES) ; sans cette exception, la seule
        # fiche d'un tel compte deviendrait impossible à modifier, même pour
        # ses autres champs (voir aussi utilisateur_fiche.html, qui verrouille
        # déjà le <select> dans ce cas — PROMPT_CORRECTIONS.md P1 #12).
        try:
            date_embauche_valide = _parser_date_embauche(date_embauche)
        except ValueError:
            date_embauche_valide = False

        # Adresse e-mail réservée à l'Admin (lot 10) : le lien de
        # réinitialisation part vers cette adresse ; si le RH pouvait la
        # changer, il y mettrait la sienne, s'enverrait le lien et
        # prendrait la main sur le compte. Une simple différence de casse
        # n'est pas un changement : on garde l'adresse enregistrée.
        email_change_refuse = False
        if g.user["role"] != "admin":
            if email.lower() == (utilisateur["email"] or "").lower():
                email = utilisateur["email"]
            elif email:
                email_change_refuse = True

        # Lot 13 (audit a11y I5) : toutes les erreurs, chacune sous son champ.
        if user_id == g.user["id"] and role != utilisateur["role"]:
            erreurs["role"] = "Vous ne pouvez pas changer votre propre rôle depuis cet écran."
        elif role not in _roles_attribuables() and role != utilisateur["role"]:
            erreurs["role"] = "Rôle invalide."
        if fuseau not in dailylog_repo.FUSEAUX:
            erreurs["fuseau"] = "Bureau (fuseau horaire) invalide."
        for champ, valeur in (("prenom", prenom), ("nom", nom), ("email", email)):
            if not valeur:
                erreurs[champ] = "Obligatoire."
        if email_change_refuse:
            erreurs["email"] = ("Seul un Admin peut changer l’adresse e-mail d’un compte (c’est "
                                "à cette adresse que part le lien de réinitialisation).")
        if date_embauche_valide is False:
            erreurs["date_embauche"] = "Date d’embauche invalide."
        if role in ROLES_EQUIPE_OBLIGATOIRE and not equipe_code:
            # Contre-expertise rôles M4 : même règle qu'à la création.
            erreurs["equipe_code"] = "Choisissez l’équipe de ce compte (intervenant ou chef de projet)."
        for champ, message in _erreurs_fiche(prenom, nom, email, telephone, poste, adresse,
                                             date_embauche_valide or None, equipe_code, champs_perso).items():
            erreurs.setdefault(champ, message)
        avertissement_mdp = None
        if not erreurs:
            try:
                utilisateurs_repo.update_utilisateur_complet(
                    user_id, prenom=prenom, nom=nom, email=email, telephone=telephone,
                    poste=poste, adresse=adresse, date_embauche=date_embauche_valide,
                    equipe_code=equipe_code, role=role, champs_perso=champs_perso,
                    current_user_id=g.user["id"], fuseau=fuseau,
                )
                _enregistrer_avatar_si_fourni(user_id, g.user["id"])
                # Admin uniquement : pour le RH, la requête a déjà été
                # refusée plus haut (_refuser_mot_de_passe_hors_admin).
                nouveau_mot_de_passe = request.form.get("nouveau_mot_de_passe", "")
                if nouveau_mot_de_passe:
                    if len(nouveau_mot_de_passe) < MOT_DE_PASSE_MIN_LEN:
                        avertissement_mdp = (
                            f"Fiche mise à jour, mais le mot de passe doit faire au "
                            f"moins {MOT_DE_PASSE_MIN_LEN} caractères — il n’a pas été "
                            "changé.")
                    else:
                        nouveau_hash = hash_password(nouveau_mot_de_passe)
                        utilisateurs_repo.set_password(user_id, nouveau_hash, g.user["id"])
                        # Un admin/RH qui change SON PROPRE mot de passe depuis
                        # sa fiche garde sa session (comme depuis "Infos
                        # perso") — sans ça, l'empreinte ne correspondait plus
                        # et il était déconnecté à la requête suivante (P2 #17).
                        if user_id == g.user["id"]:
                            session["pw_fingerprint"] = password_fingerprint(nouveau_hash)
            except Exception as exc:
                if "idx_utilisateur_rh_singleton" in str(exc):
                    erreurs["role"] = ("Il y a déjà un compte RH actif. Désactivez-le d’abord "
                                       "pour en attribuer ce rôle.")
                elif "idx_utilisateur_email_lower" in str(exc):
                    erreurs["email"] = f"Un compte existe déjà avec l’email {email}."
                elif "rôle RH" in str(exc):
                    # trg_check_passage_role_rh (migration 0005).
                    erreurs["role"] = (
                        "Impossible de passer cette personne au rôle RH\u00a0: elle est "
                        "encore chef de projet, co-chef ou intervenant. Retirez-la "
                        "d’abord de ses projets et tâches.")
                elif message := _message_garde_admin(exc):
                    erreurs["role"] = message
                else:
                    flash("Impossible de mettre à jour ce compte.", "error")
            else:
                if avertissement_mdp:
                    if partiel.est_partiel():
                        erreurs["nouveau_mot_de_passe"] = (
                            f"{MOT_DE_PASSE_MIN_LEN} caractères au moins\u00a0: le mot de passe n’a pas été changé "
                            "(le reste de la fiche est enregistré).")
                        return _fiche_partielle(user_id, erreurs, statut=422,
                                                toasts=[partiel.toast("Fiche mise à jour, sauf le mot de passe.", "avertissement")])
                    flash(avertissement_mdp, "error")
                    return redirect(url_for("utilisateurs.fiche", user_id=user_id))
                flash("Fiche mise à jour.", "success")
                if partiel.est_partiel():
                    return _fiche_partielle(user_id, {})
                return redirect(url_for("utilisateurs.fiche", user_id=user_id))

        erreurs = _ordonner(erreurs)
        if erreurs and not partiel.est_partiel():
            flash(_resume_erreurs(erreurs), "error")
        # Erreur : on réaffiche la saisie (audit n°2 — la fiche revenait aux
        # valeurs enregistrées, toutes les modifications étaient perdues).
        utilisateur = {
            **utilisateurs_repo.get_utilisateur(user_id),
            "prenom": prenom, "nom": nom,
            "email": utilisateur["email"] if email_change_refuse else email, "telephone": telephone,
            "poste": poste, "adresse": adresse, "date_embauche": date_embauche,
            "equipe_code": equipe_code, "role": role, "champs_perso": champs_perso,
            "fuseau": fuseau,
        }
        if partiel.est_partiel():
            return _fiche_partielle(user_id, erreurs, statut=422 if erreurs else 200, utilisateur=utilisateur)

    return render_template(
        "utilisateur_fiche.html",
        utilisateur=utilisateur, equipe_choices=EQUIPE_CHOICES,
        roles_creables=_roles_attribuables(),
        lecture_seule=_cible_protegee(utilisateur),
        fuseaux=dailylog_repo.FUSEAUX, erreurs=erreurs,
        dix_jours=(_dix_jours_ouvres(enregistre, None) if g.user["role"] == "admin" and _peut_corriger(enregistre)
                   else None),
        peut_corriger=g.user["role"] == "admin" and _peut_corriger(enregistre),
    )


def _fiche_partielle(user_id: int, erreurs: dict, statut: int = 200, utilisateur: dict | None = None, toasts=None):
    """Lot 13 : formulaire de la fiche re-rendu en place (après Enregistrer
    ou avec les erreurs reliées aux champs), le nom du titre suit."""
    enregistre = utilisateurs_repo.get_utilisateur(user_id)
    return partiel.repondre(
        "partials/utilisateur_fiche_form.html", statut=statut, toasts=toasts,
        utilisateur=utilisateur or enregistre, titre=enregistre, oob_titre=True, equipe_choices=EQUIPE_CHOICES,
        roles_creables=_roles_attribuables(), lecture_seule=_cible_protegee(enregistre),
        fuseaux=dailylog_repo.FUSEAUX, erreurs=erreurs,
    )


@bp.route("/<int:user_id>/envoyer-lien", methods=["POST"])
@role_required("admin", "rh")
def envoyer_lien_reinitialisation(user_id: int):
    """Bouton « Envoyer un lien de réinitialisation » de la fiche (décision
    du gérant, lot 10) : c'est la seule façon pour le RH d'aider un employé
    à retrouver l'accès — il ne fixe plus lui-même de mot de passe. Le lien
    part TOUJOURS vers l'adresse enregistrée du compte (aucune adresse n'est
    lue dans le formulaire), adresse que seul un Admin peut changer (voir
    fiche()). Le mot de passe actuel reste valable tant que l'employé n'en
    a pas choisi un nouveau : un envoi ne bloque personne."""
    cible = utilisateurs_repo.get_utilisateur(user_id)
    if cible is None:
        if partiel.est_partiel():
            return partiel.refuser("Utilisateur introuvable.", 404)
        flash("Utilisateur introuvable.", "error")
        return redirect(url_for("utilisateurs.liste"))
    if _cible_protegee(cible):
        flash("Seul un Admin peut agir sur le compte d’un Admin.", "error")
    elif not cible["actif"]:
        flash(
            "Ce compte est désactivé\u00a0: réactivez-le avant d’envoyer un lien "
            "(un compte désactivé ne peut pas définir de mot de passe).", "error",
        )
    elif not mailer.est_configure() or not mailer.destinataire_autorise(cible["email"]):
        # Aucun jeton généré : il remplacerait pour rien un lien encore
        # valable (celui de la création du compte, par exemple). Mode test
        # (MAIL_DESTINATAIRES_AUTORISES) : adresse hors liste, rien ne part.
        if mailer.est_configure():
            current_app.logger.warning("Lien de réinitialisation non envoyé à %s (mode test des e-mails).",
                                       mailer.masquer(cible["email"]))
        flash(
            f"L’e-mail de réinitialisation n’a pas pu être envoyé "
            f"({_motif_echec_email(cible['email'])})\u00a0: "
            f"aucun lien n’a été transmis à {cible['email']}.", "error",
        )
    elif _envoyer_lien_mot_de_passe(user_id, cible["email"], creation=False):
        flash(
            f"Lien de réinitialisation envoyé à {cible['email']} (valable 1 heure). "
            "Son mot de passe actuel reste valable jusqu’à ce qu’il en choisisse un nouveau.",
            "success",
        )
    else:
        flash(
            f"L’e-mail de réinitialisation n’a pas pu être envoyé ({_motif_echec_email(cible['email'])})\u00a0: "
            f"aucun lien n’a été transmis à {cible['email']}. Réessayez plus tard.", "error",
        )
    if partiel.est_partiel():
        # Lot 13 : la carte reste en place, le résultat en toast.
        if _cible_protegee(cible):
            partiel.lire_flash()
            return partiel.refuser("Seul un Admin peut agir sur le compte d’un Admin.", 403)
        return partiel.repondre("partials/utilisateur_reinit.html", utilisateur=cible)
    return redirect(url_for("utilisateurs.fiche", user_id=user_id))


@bp.route("/<int:user_id>/toggle-actif", methods=["POST"])
@role_required("admin", "rh")
def toggle_actif(user_id: int):
    cible = utilisateurs_repo.get_utilisateur(user_id)
    if cible is None:
        flash("Utilisateur introuvable.", "error")
    elif user_id == g.user["id"]:
        flash("Vous ne pouvez pas désactiver votre propre compte.", "error")
    elif _cible_protegee(cible):
        flash("Seul un Admin peut activer ou désactiver le compte d’un Admin.", "error")
    elif request.form.get("actif_cible") not in ("0", "1"):
        # État VOULU envoyé par le formulaire (utilisateurs_liste.html) :
        # un double clic ne fait plus revenir à l'état d'avant.
        flash("Requête invalide\u00a0: rechargez la page et réessayez.", "error")
    else:
        try:
            utilisateurs_repo.set_actif(user_id, request.form["actif_cible"] == "1", g.user["id"])
        except Exception as exc:
            # Réactivation d'un compte RH alors qu'un autre est déjà actif
            # (PROMPT_CORRECTIONS.md P1 #11) : idx_utilisateur_rh_singleton
            # remontait auparavant telle quelle jusqu'à une erreur 500, au
            # lieu du message clair déjà utilisé ailleurs (creer(), fiche()).
            if "idx_utilisateur_rh_singleton" in str(exc):
                flash(
                    "Il y a déjà un compte RH actif. Désactivez-le d’abord "
                    "pour en réactiver un autre.", "error",
                )
            elif message := _message_garde_admin(exc):
                flash(message, "error")
            else:
                flash("Impossible de mettre à jour le statut de ce compte.", "error")
        else:
            flash("Statut du compte mis à jour.", "success")
    # Filtres de la liste à conserver après l'action — liste explicite :
    # renvoyer tout request.form recopiait aussi le jeton csrf_token dans
    # l'URL (historique, journaux, Referer), voir audit n°2.
    filtres = {
        cle: request.form[cle]
        for cle in ("q", "equipe_code", "role", "actif")
        if request.form.get(cle)
    }
    # Lot 13 : interrupteur « Compte actif » de la fiche (retour=fiche).
    depuis_fiche = request.form.get("retour") == "fiche" and cible is not None
    if partiel.est_partiel():
        return _toggle_actif_partiel(user_id, cible, filtres, depuis_fiche)
    if depuis_fiche:
        return redirect(url_for("utilisateurs.fiche", user_id=user_id))
    return redirect(url_for("utilisateurs.liste", **filtres))


def _toggle_actif_partiel(user_id: int, cible: dict | None, filtres: dict, depuis_fiche: bool = False):
    """Lot 13 (pilote du socle partiel) : réponse de l'interrupteur « Actif »
    à kairos-partiel.js — la ligne re-rendue (et le compteur), un toast avec
    « Annuler » ; un refus (message déjà posé par flash()) annule l'état
    optimiste côté navigateur."""
    erreurs = [m for c, m in partiel.lire_flash() if c == "error"]
    if erreurs:
        if cible is None:
            statut = 404
        elif user_id == g.user["id"] or _cible_protegee(cible):
            statut = 403
        elif request.form.get("actif_cible") not in ("0", "1"):
            statut = 400
        else:
            statut = 409
        return partiel.refuser(erreurs[0], statut)
    u = utilisateurs_repo.get_utilisateur(user_id)
    if depuis_fiche:
        action = None
        if not request.form.get("annulation"):
            action = {
                "libelle": "Annuler", "url": url_for("utilisateurs.toggle_actif", user_id=user_id), "methode": "POST",
                "donnees": {"retour": "fiche", "actif_cible": "0" if u["actif"] else "1", "annulation": "1"},
                "cible": "#utilisateur-actif", "focus": "#fiche-actif",
            }
        # Revue produit (§ 3) : pas d'élision ratée (« de Interv »).
        texte = f"Compte {'réactivé' if u['actif'] else 'désactivé'}\u00a0: {u['prenom']} {u['nom']}."
        return partiel.repondre("partials/utilisateur_actif.html", toasts=[partiel.toast(texte, action=action)],
                                utilisateur=u, oob_reinit=True)
    q = filtres.get("q") or None
    equipe_code = filtres.get("equipe_code") or None
    role = filtres.get("role") if filtres.get("role") in ("admin", "chef_de_projet", "intervenant", "rh", "client") else None
    actif_param = filtres.get("actif") or ""
    nom = f"{u['prenom']} {u['nom']}"
    action = None
    if not request.form.get("annulation"):
        action = {
            "libelle": "Annuler",
            "url": url_for("utilisateurs.toggle_actif", user_id=user_id),
            "methode": "POST",
            "donnees": {"q": q or "", "equipe_code": equipe_code or "", "role": role or "", "actif": actif_param,
                        "actif_cible": "0" if u["actif"] else "1", "annulation": "1"},
            "cible": f"#u-{user_id}",
            "focus": f"#actif-{user_id}",
        }
    texte = f"Compte {'réactivé' if u['actif'] else 'désactivé'}\u00a0: {nom}."
    return partiel.repondre(
        "partials/utilisateur_ligne.html", toasts=[partiel.toast(texte, action=action)], oob_compte=True,
        u=u, peut_gerer=True, compte=utilisateurs_repo.compter(),
        utilisateurs=utilisateurs_repo.list_tous(
            q=q, equipe_code=equipe_code, role=role, actif={"actifs": True, "inactifs": False}.get(actif_param)),
        q=q or "", equipe_code=equipe_code, role=role, actif_param=actif_param,
    )

"""Pages Utilisateurs (liste + création), réservées à l'admin et au RH —
pour que le RH puisse gérer les comptes sans passer par la commande CLI
`flask create-user` (voir app/__init__.py). La page "Infos perso" (`/moi`)
est différente : accessible à tout utilisateur connecté, uniquement sur
son propre compte (voir demande de Fadhel, 2026-09-19 : cliquer sur son
propre nom/avatar affiche ses infos, modifiables, avec le Daily log de la
semaine dernière)."""
import datetime
import secrets

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .. import mailer
from ..auth import (
    MOT_DE_PASSE_MIN_LEN, generer_lien_reset, hash_password, login_required,
    role_required, verify_password,
)
from ..repositories import dailylog as dailylog_repo
from ..repositories import utilisateurs as utilisateurs_repo
from ..storage import is_image_filename, save_upload
from ..utils import EQUIPE_CHOICES

bp = Blueprint("utilisateurs", __name__, url_prefix="/utilisateurs")

# RH et Client ne sont pas proposables depuis ce formulaire : RH est un
# rôle unique (voir idx_utilisateur_rh_singleton) affiché mais désactivé
# quand déjà attribué, et Client arrive à l'étape 2 (voir spec) — on ne
# l'affiche pas du tout pour l'instant, comme dans la maquette.
ROLES_CREABLES = ["intervenant", "chef_de_projet", "admin", "rh"]


def _enregistrer_avatar_si_fourni(user_id: int, current_user_id: int) -> None:
    """Photo de profil optionnelle (retour Fadhel, 2026-09-20) — n'importe
    quel formulaire de création/modification d'utilisateur qui accepte un
    champ fichier `avatar` passe par ici. Ignore silencieusement l'absence
    de fichier (soumission sans nouvelle photo) ; avertit sur un format
    non pris en charge sans faire échouer le reste du formulaire."""
    fichier = request.files.get("avatar")
    if not fichier or not fichier.filename:
        return
    if not is_image_filename(fichier.filename):
        flash("Photo de profil ignorée : formats acceptés — jpg, png, gif, webp.", "error")
        return
    _, chemin = save_upload(fichier, f"avatars/{user_id}")
    utilisateurs_repo.set_avatar(user_id, chemin, current_user_id)


def _semaine_derniere(user_id: int) -> list[dict]:
    """Daily log en lecture seule de la semaine dernière — lundi à vendredi
    uniquement (retour Fadhel, 2026-09-21 : "ne pas afficher samedi et
    dimanche"), partagé par /moi (mon_profil, où c'est le propre DailyLog
    de l'utilisateur) et par la fiche en lecture seule d'un chef de projet
    (fiche(), où c'est celui d'un autre utilisateur)."""
    aujourdhui = datetime.date.today()
    lundi_cette_semaine = aujourdhui - datetime.timedelta(days=aujourdhui.weekday())
    lundi_semaine_derniere = lundi_cette_semaine - datetime.timedelta(days=7)
    jours = []
    for i in range(5):  # lundi (0) à vendredi (4)
        jour = lundi_semaine_derniere + datetime.timedelta(days=i)
        entrees = dailylog_repo.list_entrees_jour(user_id, jour)
        jours.append({
            "date": jour,
            "entrees": entrees,
            "total_heures": sum(float(e["heures"]) for e in entrees),
        })
    return jours


@bp.route("")
@role_required("admin", "rh", "chef_de_projet")
def liste():
    q = request.args.get("q") or None
    equipe_code = request.args.get("equipe_code") or None
    role = request.args.get("role") or None
    actif_param = request.args.get("actif") or None
    actif = {"actifs": True, "inactifs": False}.get(actif_param)

    tous = utilisateurs_repo.list_tous(q=q, equipe_code=equipe_code, role=role, actif=actif)
    compte = utilisateurs_repo.compter()

    return render_template(
        "utilisateurs_liste.html",
        utilisateurs=tous, compte=compte,
        q=q or "", equipe_code=equipe_code, role=role, actif_param=actif_param or "",
        equipe_choices=EQUIPE_CHOICES,
    )


@bp.route("/nouveau", methods=["GET", "POST"])
@role_required("admin", "rh")
def creer():
    if request.method == "POST":
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

        noms_champs = request.form.getlist("champ_perso_nom")
        valeurs_champs = request.form.getlist("champ_perso_valeur")
        champs_perso = {
            n.strip(): v.strip()
            for n, v in zip(noms_champs, valeurs_champs)
            if n.strip()
        }

        if not prenom or not nom or not email:
            flash("Prénom, nom et email sont obligatoires.", "error")
        elif role not in ROLES_CREABLES:
            flash("Rôle invalide.", "error")
        else:
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
                    poste=poste, adresse=adresse, date_embauche=date_embauche,
                    equipe_code=equipe_code, verifie=False, champs_perso=champs_perso,
                    current_user_id=g.user["id"],
                )
                if not actif_compte:
                    utilisateurs_repo.toggle_actif(user_id, g.user["id"])
                _enregistrer_avatar_si_fourni(user_id, g.user["id"])
                email_envoye = False
                if actif_compte:
                    lien = generer_lien_reset(user_id)
                    email_envoye = mailer.envoyer(
                        email,
                        "Kairos — création de votre compte",
                        "Bonjour,\n\n"
                        "Un compte Kairos vient d'être créé pour vous.\n\n"
                        f"Adresse e-mail : {email}\n\n"
                        "Pour définir votre mot de passe et activer votre "
                        f"compte, utilisez ce lien (valable 1 heure) : {lien}\n\n"
                        "Si ce lien a expiré, utilisez \"Mot de passe "
                        "oublié ?\" sur la page de connexion avec cette même "
                        "adresse email pour en recevoir un nouveau.",
                    )
            except Exception as exc:
                if "idx_utilisateur_rh_singleton" in str(exc):
                    flash(
                        "Il y a déjà un compte RH actif. Désactivez-le d'abord "
                        "pour en créer un nouveau.", "error",
                    )
                elif "idx_utilisateur_email_lower" in str(exc):
                    flash(f"Un compte existe déjà avec l'email {email}.", "error")
                else:
                    flash("Impossible de créer ce compte.", "error")
            else:
                if not actif_compte:
                    flash(
                        f"Compte créé pour {prenom} {nom} (inactif) — aucun "
                        "email envoyé. Réactivez le compte pour qu'il puisse "
                        "définir son mot de passe.", "success",
                    )
                elif email_envoye:
                    flash(
                        f"Compte créé pour {prenom} {nom}. Un email lui a été "
                        "envoyé pour qu'il définisse son mot de passe.", "success",
                    )
                else:
                    flash(
                        f"Compte créé pour {prenom} {nom}, mais l'email n'a "
                        "pas pu être envoyé (SMTP non configuré ou "
                        "indisponible) — il ne pourra pas se connecter tant "
                        "qu'un mot de passe n'est pas défini. Réessayez via "
                        "\"Mot de passe oublié ?\" une fois SMTP opérationnel, "
                        "ou définissez-lui un mot de passe depuis sa fiche.", "error",
                    )
                return redirect(url_for("utilisateurs.liste"))

    rh_titulaire = utilisateurs_repo.rh_deja_attribue()
    return render_template(
        "utilisateur_creer.html", equipe_choices=EQUIPE_CHOICES, rh_titulaire=rh_titulaire,
    )


@bp.route("/moi", methods=["GET", "POST"])
@login_required
def mon_profil():
    user_id = g.user["id"]

    if request.method == "POST":
        telephone = request.form.get("telephone", "").strip() or None
        poste = request.form.get("poste", "").strip() or None
        adresse = request.form.get("adresse", "").strip() or None
        utilisateurs_repo.update_profil(
            user_id, telephone=telephone, poste=poste, adresse=adresse,
            current_user_id=user_id,
        )
        _enregistrer_avatar_si_fourni(user_id, user_id)
        flash("Vos informations ont été mises à jour.", "success")
        return redirect(url_for("utilisateurs.mon_profil"))

    utilisateur = utilisateurs_repo.get_utilisateur(user_id)

    # Daily log de la semaine dernière (lundi → vendredi — voir
    # _semaine_derniere), demandé par Fadhel (2026-09-19), affiché en
    # lecture seule ici (la saisie reste sur /dailylog ; chaque ligne y
    # renvoie directement, voir utilisateur_profil.html).
    return render_template(
        "utilisateur_profil.html",
        utilisateur=utilisateur,
        semaine_derniere=_semaine_derniere(user_id),
    )


@bp.route("/moi/mot-de-passe", methods=["POST"])
@login_required
def mon_mot_de_passe():
    """Changement de son propre mot de passe, depuis "Infos perso" (retour
    Fadhel, 2026-09-21 : "donner la possibilité dans son espace de modifier
    son mot de passe") — formulaire séparé de mon_profil() (pas le même
    enctype, et une erreur ici ne doit pas faire perdre les autres champs).
    L'ancien mot de passe est exigé, comme tout changement de mot de passe
    volontaire par son titulaire."""
    user_id = g.user["id"]
    actuel = request.form.get("mot_de_passe_actuel", "")
    nouveau = request.form.get("nouveau_mot_de_passe", "")
    confirmation = request.form.get("confirmation", "")

    hash_actuel = utilisateurs_repo.get_mot_de_passe_hash(user_id)

    if hash_actuel is None or not verify_password(actuel, hash_actuel):
        flash("Mot de passe actuel incorrect.", "error")
    elif nouveau != confirmation:
        flash("Les deux nouveaux mots de passe ne correspondent pas.", "error")
    elif len(nouveau) < MOT_DE_PASSE_MIN_LEN:
        flash(f"Le nouveau mot de passe doit faire au moins {MOT_DE_PASSE_MIN_LEN} caractères.", "error")
    else:
        utilisateurs_repo.set_password(user_id, hash_password(nouveau), user_id)
        flash("Mot de passe changé.", "success")

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

    if g.user["role"] == "chef_de_projet":
        return render_template(
            "utilisateur_voir.html",
            utilisateur=utilisateur,
            semaine_derniere=_semaine_derniere(user_id),
        )

    if request.method == "POST":
        prenom = request.form.get("prenom", "").strip()
        nom = request.form.get("nom", "").strip()
        email = request.form.get("email", "").strip()
        telephone = request.form.get("telephone", "").strip() or None
        poste = request.form.get("poste", "").strip() or None
        adresse = request.form.get("adresse", "").strip() or None
        date_embauche = request.form.get("date_embauche") or None
        equipe_code = request.form.get("equipe_code") or None
        role = request.form.get("role", utilisateur["role"])

        noms_champs = request.form.getlist("champ_perso_nom")
        valeurs_champs = request.form.getlist("champ_perso_valeur")
        champs_perso = {
            n.strip(): v.strip()
            for n, v in zip(noms_champs, valeurs_champs)
            if n.strip()
        }

        if user_id == g.user["id"] and role != utilisateur["role"]:
            flash("Vous ne pouvez pas changer votre propre rôle depuis cet écran.", "error")
        elif not prenom or not nom or not email:
            flash("Prénom, nom et email sont obligatoires.", "error")
        else:
            try:
                utilisateurs_repo.update_utilisateur_complet(
                    user_id, prenom=prenom, nom=nom, email=email, telephone=telephone,
                    poste=poste, adresse=adresse, date_embauche=date_embauche,
                    equipe_code=equipe_code, role=role, champs_perso=champs_perso,
                    current_user_id=g.user["id"],
                )
                _enregistrer_avatar_si_fourni(user_id, g.user["id"])
                nouveau_mot_de_passe = request.form.get("nouveau_mot_de_passe", "")
                if nouveau_mot_de_passe:
                    if len(nouveau_mot_de_passe) < MOT_DE_PASSE_MIN_LEN:
                        flash(
                            f"Fiche mise à jour, mais le mot de passe doit faire au "
                            f"moins {MOT_DE_PASSE_MIN_LEN} caractères — il n'a pas été "
                            "changé.", "error",
                        )
                        return redirect(url_for("utilisateurs.fiche", user_id=user_id))
                    utilisateurs_repo.set_password(
                        user_id, hash_password(nouveau_mot_de_passe), g.user["id"]
                    )
            except Exception as exc:
                if "idx_utilisateur_rh_singleton" in str(exc):
                    flash(
                        "Il y a déjà un compte RH actif. Désactivez-le d'abord "
                        "pour en attribuer ce rôle.", "error",
                    )
                elif "idx_utilisateur_email_lower" in str(exc):
                    flash(f"Un compte existe déjà avec l'email {email}.", "error")
                else:
                    flash("Impossible de mettre à jour ce compte.", "error")
            else:
                flash("Fiche mise à jour.", "success")
                return redirect(url_for("utilisateurs.fiche", user_id=user_id))

        utilisateur = utilisateurs_repo.get_utilisateur(user_id)

    return render_template(
        "utilisateur_fiche.html",
        utilisateur=utilisateur, equipe_choices=EQUIPE_CHOICES,
        roles_creables=ROLES_CREABLES,
    )


@bp.route("/<int:user_id>/toggle-actif", methods=["POST"])
@role_required("admin", "rh")
def toggle_actif(user_id: int):
    if user_id == g.user["id"]:
        flash("Vous ne pouvez pas désactiver votre propre compte.", "error")
    else:
        utilisateurs_repo.toggle_actif(user_id, g.user["id"])
        flash("Statut du compte mis à jour.", "success")
    return redirect(url_for("utilisateurs.liste", **request.form.to_dict(flat=True)))

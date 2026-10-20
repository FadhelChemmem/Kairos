"""Daily log v9 (lot 10, maquette validée par Fadhel le 2026-10-06).

La page (`dailylog.formulaire`, endpoint inchangé : base.html et les
profils y renvoient) ne fait que poser l'amorce JSON ; tout le reste passe
par une petite API JSON, toujours en JSON, y compris pour les erreurs
(401 au lieu d'une redirection : `fetch` suivrait le 302 et prendrait la
page de connexion pour un succès) :

    GET  /dailylog/api/jour/<AAAA-MM-JJ>            état d'un jour
    PUT  /dailylog/api/jour/<AAAA-MM-JJ>            enregistrer les heures
    POST /dailylog/api/jour/<AAAA-MM-JJ>/absence    marquer / annuler l'absence
    GET  /dailylog/api/mois/<AAAA-MM>               pastilles du calendrier
    PUT  /dailylog/api/objectif                     objectif de journée (préférence)
    GET  /dailylog/api/taches?projet=&date=         tâches d'un projet
    GET  /dailylog/recherche-projets?q=&date=       recherche du catalogue

`?utilisateur=<id>` : correction du Daily log d'un employé par un chef de
projet (lignes de SES projets) ou l'Admin (tout). Saisie libre :
aujourd'hui et les 14 jours précédents, au fuseau de la personne. Toutes
les écritures sont tracées au nom de l'acteur (updated_by, audit_log).
CSRF : en-tête X-CSRFToken posé par base.html sur tout fetch non-GET.
"""
import datetime
import functools
import re

from flask import Blueprint, abort, current_app, g, jsonify, redirect, render_template, request, url_for

from ..auth import role_required
from ..repositories import dailylog as dl
from ..repositories import notifications as notifications_repo
from ..repositories import utilisateurs as utilisateurs_repo
from .. import partiel, utils
from ..validation import DATE_MAX, DATE_MIN

bp = Blueprint("dailylog", __name__, url_prefix="/dailylog")

# Ni le RH (aucun accès aux projets) ni un Client n'ont de Daily log
# (décisions Fadhel, lot 7).
ROLES_DAILYLOG = ("admin", "chef_de_projet", "intervenant")
# Qui peut ouvrir le Daily log d'un autre (gérant, lot 10).
ROLES_CORRECTION = ("admin", "chef_de_projet")

MAX_LIGNES = 40
MAX_ID = 2 ** 63 - 1
MAX_VERSION = 2 ** 31 - 1
MAX_RECHERCHE = 100
_RE_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_RE_MOIS = re.compile(r"^[0-9]{4}-[0-9]{2}$")
_RE_ID = re.compile(r"^[0-9]{1,18}$")

# Textes de l'écran (hors du JS : i18n côté gabarit). {x} est remplacé par
# le JS ; les dates sont formatées côté client avec les listes ci-dessous.
TEXTES_DAILYLOG = {
    "jours_courts": utils.JOURS_ABREGES,
    "jours_longs": [j.lower() for j in utils.JOURS_COMPLETS],
    "mois": utils.MOIS_COMPLETS,
    "mois_courts": utils.MOIS_ABREGES,
    "unite_h": "h",
    "unite_min": "min",
    "titre_jour": "Journée du {x}",
    "statut": {
        "nouveau": "Nouvelle saisie", "modifie": "Modifié · non enregistré", "envoi": "Enregistrement…",
        "enregistre": "Enregistré", "erreur": "Non enregistré", "absent": "Jour absent",
        "lecture": "Lecture seule",
    },
    "enregistrer": "Enregistrer",
    "enregistre_ok": "Enregistré ✓",
    "enregistrement": "Enregistrement…",
    "absent_bouton": "Absent",
    "vider_journee": "Vider la journée",
    "confirmer_vider": "Vider toute la journée du {x}\u202f? Les heures enregistrées seront supprimées.",
    "journee_videe": "Journée vidée",
    "journee_enregistree": "Journée enregistrée ✓",
    "auto_enregistre": "{x} enregistré automatiquement ({y})",
    "vide_ignoree": "{x}\u00a0: saisie vide ignorée, dernière version conservée",
    "max_ligne": "Maximum {x} sur cette ligne (10 h par jour)",
    "journee_pleine": "Journée pleine (10 h)",
    "arrondi": "Arrondi à {x} (pas de 30 min)",
    "saisie_vide": "Saisie vide — touchez le nom du projet pour le désactiver",
    "format_inconnu": "Format non reconnu — exemples\u00a0: 2,5 · 2h30 · 45min",
    "max_10h_nombre": "Maximum 10 h — pour des minutes, ajoutez «\u00a0min\u00a0» (ex. 45min)",
    "minimum_30": "Minimum 30 min (la saisie va par pas de 30 min)",
    "ajoute": "{x} ajouté — {y}",
    "copier_le": "Copier le {x}",
    "copier_aucun": "Copier la veille",
    "copier_aucun_titre": "Aucune journée précédente avec des heures",
    "copier_rien_titre": "Rien à copier du {x}\u00a0: ses heures portent sur des tâches ou des projets clos depuis",
    "copie_depuis": "Copié depuis le {x}",
    "copie_exclues": " — {x} ligne non reprise\u00a0: tâche ou projet clos, pas encore commencé ou plus ouvert",
    "copie_exclues_pl": " — {x} lignes non reprises\u00a0: tâche ou projet clos, pas encore commencé ou plus ouverts",
    "annuler": "Annuler",
    "annuler_dispo": " — bouton Annuler disponible",
    "marquer_absent": "Marquer absent",
    "annuler_absence": "Annuler l’absence",
    "absent_marque": "Jour marqué absent",
    "absent_conserve": " — les heures saisies sont rendues si vous annulez",
    "absence_annulee": "Absence annulée",
    "absent_carte_titre": "Jour marqué absent",
    "absent_carte_texte": "Congé, férié ou récupération — aucune heure à saisir.",
    "aucun_projet": "Aucun projet pour ce jour — ajoutez-en un ou copiez une journée précédente.",
    "aucun_projet_futur": "Jour à venir\u00a0: consultation seulement.",
    "aucun_projet_lecture": "Aucune heure saisie ce jour.",
    "ajouter_projet": "+ Ajouter un projet",
    "recherche_placeholder": "Code ou nom du projet…",
    "recherche_label": "Rechercher un projet",
    "vos_projets": "Vos projets",
    "vos_taches": "Vos tâches",
    "recents": "Récemment travaillés",
    "resultats": "Résultats",
    "recherche_en_cours": "Recherche…",
    "aucun_trouve": "Aucun projet trouvé.",
    "tous_dans_liste": "Tous vos projets sont déjà dans la liste.",
    "deja_dans_liste": "déjà dans la liste",
    "taches_du_projet": "Tâches",
    "taches_titre": "Tâches de {x}",
    "projet_seul": "Projet seul (sans tâche)",
    "sans_tache": "sans tâche",
    "sans_tache_titre": "Sans tâche",
    "retirer": "Retirer la ligne {x} (non enregistrée)",
    "retirer_titre": "Retirer cette ligne (non enregistrée)",
    "ligne_retiree": "Ligne retirée\u00a0: {x}",
    "astuce_saisie": "Tapez 2,5 ou 2h30",
    "propositions_annonce": "{x} tâches ou projets proposés à 0 h",
    "propositions_annonce_1": "1 tâche ou projet proposé à 0 h",
    "afficher_plus": "+ Afficher {x} de plus",
    "afficher_plus_reste": "({x} restants)",
    "aucune_tache": "Aucune tâche en cours.",
    "total": "Total",
    "jauge": "Total de la journée",
    "sur": "{x} sur {y}",
    "aucune_heure": "Aucune heure saisie",
    "journee_complete": "Journée complète ({x}) ✓",
    "sous_journee": "{x} sous la journée de {y}",
    "au_dessus": "+{x} au-dessus de {y}",
    "annonce_total_ok": "Total {x}\u00a0: journée complète",
    "annonce_total_sous": "Total {x}\u00a0: sous la journée",
    "annonce_total_dessus": "Total {x}\u00a0: au-dessus de la journée",
    "objectif": "Journée",
    "objectif_moins": "Diminuer la journée type de 30 minutes",
    "objectif_plus": "Augmenter la journée type de 30 minutes",
    "objectif_erreur": "Objectif non enregistré",
    "jour_precedent": "Jour ouvré précédent",
    "jour_suivant": "Jour ouvré suivant",
    "choisir_date": "Choisir une date",
    "mois_precedent": "Mois précédent",
    "mois_suivant": "Mois suivant",
    "aujourdhui": "aujourd’hui",
    "week_end": "week-end",
    "legende": {"rempli": "Rempli", "absent": "Absent", "vide": "Non renseigné",
                "verrouille": "Non renseigné, verrouillé (au-delà de 14 jours)"},
    "statut_jour": {"rempli": "rempli", "absent": "absent", "vide": "non renseigné",
                    "verrouille": "non renseigné, verrouillé au-delà de 14 jours"},
    # Lot 15 : bande de la semaine et « Ne plus proposer ».
    "aujourdhui_maj": "Aujourd’hui",
    "a_venir": "À venir",
    "etat_semaine": {"rempli": "Rempli", "absent": "Absent", "vide": "Manquant", "verrouille": "Verrouillé"},
    "propositions_coupees": "Vos tâches en cours ne seront plus proposées (réglage dans «\u00a0Mes informations\u00a0»).",
    "banniere": "{x} sans saisie",
    "banniere_jour": "jour",
    "banniere_jours": "jours",
    "banniere_suite": " à compléter\u00a0: ",
    "banniere_plus": "+ {x} plus ancien",
    "banniere_plus_pl": "+ {x} plus anciens",
    "banniere_cal": " (voir le calendrier)",
    # Recette du lot 14, n° 15 : la bannière garde sa place une fois le
    # dernier jour manqué rempli.
    "banniere_faite": "Journée du {x} enregistrée.",
    "banniere_faite_suite": "Plus aucun jour à compléter.",
    "heures_sur": "Heures sur {x} (pas de 30 minutes)",
    "moins_30": "Moins 30 minutes sur {x}",
    "plus_30": "Plus 30 minutes sur {x}",
    "activer": "Activer ou désactiver {x}",
    "ligne_verrouillee": "Projet géré par un autre chef\u00a0: lecture seule",
    "ligne_verrouillee_fenetre": "Au-delà de 14 jours\u00a0: correction par le chef de projet ou l’Admin",
    "ligne_masquee": "Projet non visible pour vous",
    "lecture_seule": "Au-delà de 14 jours, seule une correction par votre chef de projet ou l’Admin est possible.",
    "futur_reel": "Date simulée\u00a0: ce jour est après la vraie date du jour — affichage seulement, aucune saisie (mode test).",
    "ligne_futur_reel": "Jour après la vraie date du jour\u00a0: lecture seule (mode test)",
    "lecture_seule_chef": "Au-delà de 14 jours, vous ne pouvez modifier que les lignes de vos projets.",
    "correction": "Correction du Daily log\u00a0: {x}. Vos modifications sont tracées à votre nom.",
    "correction_chef": " Seules les lignes de vos projets sont modifiables.",
    "modifie_par": "Dernière modification par {x}",
    "conflit": "Cette journée a été modifiée ailleurs (autre onglet, appareil ou correction du chef).",
    "garder_ma_saisie": "Garder ma saisie",
    "reprendre": "Reprendre la version enregistrée",
    "session_expiree": "Session expirée\u00a0: reconnectez-vous\u202f; votre saisie est gardée sur cet appareil.",
    "se_reconnecter": "Se reconnecter",
    "brouillon_trouve": "Une saisie non enregistrée du {x} a été retrouvée sur cet appareil.",
    "restaurer": "Restaurer",
    "reseau": "Non enregistré\u00a0: connexion impossible. Nouvel essai au prochain enregistrement.",
    "erreur_serveur": "Non enregistré\u00a0: erreur du serveur.",
    "non_enregistre_autre_jour": "{x} non enregistré ({y}).",
    "cause_reseau": "connexion impossible",
    "cause_serveur": "erreur du serveur",
    "brouillon_garde": " Votre saisie est gardée sur cet appareil\u00a0: revenez sur ce jour pour la restaurer.",
    "revenir": "Revenir à ce jour",
    "chargement_impossible": "Impossible de charger ce jour.",
    "valeurs_arrondies": "Anciennes valeurs hors grille arrondies au pas de 30 min.",
    "quitter": "Le dernier enregistrement a échoué\u00a0: quitter quand même\u202f?",
    "erreurs": {
        "minutes_invalides": "Durée invalide (de 30 min à 10 h par ligne).",
        "pas_30_min": "Les heures vont par pas de 30 minutes.",
        "max_journee": "10 h au plus par jour.",
        "journee_vide": "La journée enregistrée ne peut pas être vidée ainsi\u00a0: utilisez «\u00a0Vider la journée\u00a0» ou «\u00a0Marquer absent\u00a0».",
        "ligne_en_double": "Le même projet (ou la même tâche) apparaît deux fois.",
        "absent_avec_heures": "Un jour absent ne porte pas d’heures.",
        "projet_invisible": "Projet introuvable ou plus accessible.",
        "projet_clos": "Projet clos à cette date\u00a0: plus d’heures après sa clôture.",
        "projet_pas_commence": "Projet pas encore commencé à cette date.",
        "tache_hors_projet": "Cette tâche n’appartient pas au projet de la ligne.",
        "tache_close": "Cette tâche était déjà terminée à cette date\u00a0: imputez le projet sans tâche.",
        "projet_lecture_seule": "Vous n’êtes plus rattaché(e) à ce projet\u00a0: plus d’heures nouvelles.",
        "ligne_non_modifiable": "Ligne non modifiable\u00a0: au-delà de 14 jours, seuls le chef du projet ou l’Admin corrigent.",
        "absence_non_autorisee": "Absence non modifiable pour ce jour.",
        "date_future": "Pas de saisie pour un jour futur.",
        "futur_reel": "Pas de saisie après la vraie date du jour, même sous date simulée (mode test\u00a0: la date simulée sert à voir le futur, pas à y écrire).",
        "date_invalide": "Date invalide.",
        "refus_base": "Saisie refusée.",
        "interdit": "Action non autorisée.",
        "json_invalide": "Requête invalide.",
        "csrf": "Session expirée\u00a0: rechargez la page.",
        "non_connecte": "Session expirée\u00a0: reconnectez-vous.",
    },
}


# ---------------------------------------------------------------------
# Outils : erreurs JSON, contrôles d'entrée
# ---------------------------------------------------------------------
class ErreurApi(Exception):
    def __init__(self, status: int, code: str, message: str | None = None, **extra):
        super().__init__(code)
        self.status, self.code, self.extra = status, code, extra
        self.message = message or TEXTES_DAILYLOG["erreurs"].get(code, "Requête refusée.")


def _erreur(status: int, code: str, message: str | None = None, **extra):
    corps = {"erreur": code, "message": message or TEXTES_DAILYLOG["erreurs"].get(code, "Requête refusée.")}
    corps.update(extra)
    return jsonify(corps), status


def api(view):
    """Comme role_required, mais toujours en JSON (jamais de 302) ; une
    ErreurApi levée par la vue devient une réponse JSON."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return _erreur(401, "non_connecte")
        if not g.user["actif"] or g.user["role"] not in ROLES_DAILYLOG:
            return _erreur(403, "interdit")
        try:
            return view(*args, **kwargs)
        except ErreurApi as e:
            return _erreur(e.status, e.code, e.message, **e.extra)
    return wrapped


def _date_ou_none(texte):
    """Date stricte AAAA-MM-JJ (chiffres ASCII), entre DATE_MIN et DATE_MAX ;
    None sinon."""
    if not isinstance(texte, str) or not _RE_DATE.match(texte):
        return None
    try:
        d = datetime.date.fromisoformat(texte)
    except ValueError:
        return None
    return d if DATE_MIN <= d <= DATE_MAX else None


def _date_api(texte) -> datetime.date:
    d = _date_ou_none(texte)
    if d is None:
        raise ErreurApi(400, "date_invalide")
    return d


def _entier(valeur, mini: int, maxi: int):
    """Entier JSON strict (ni booléen, ni flottant, ni chaîne), borné."""
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        return None
    return valeur if mini <= valeur <= maxi else None


def _proprietaire(pour_api: bool = True) -> dict:
    """Personne dont on lit / écrit le Daily log : soi-même, ou
    `?utilisateur=<id>` pour un chef de projet ou l'Admin."""
    brut = request.args.get("utilisateur")
    if brut is None or brut == "":
        return g.user
    if not _RE_ID.match(brut):
        if pour_api:
            raise ErreurApi(400, "utilisateur_invalide", "Utilisateur invalide.")
        abort(404)
    uid = int(brut)
    if uid == g.user["id"]:
        return g.user
    if g.user["role"] not in ROLES_CORRECTION:
        if pour_api:
            raise ErreurApi(403, "interdit")
        abort(403)
    personne = utilisateurs_repo.get_utilisateur(uid)
    if personne is None or personne["role"] not in ROLES_DAILYLOG:
        if pour_api:
            raise ErreurApi(404, "utilisateur_introuvable", "Utilisateur introuvable (ou sans Daily log).")
        abort(404)
    return personne


def _suffixe(proprio: dict) -> str:
    return "" if proprio["id"] == g.user["id"] else f"?utilisateur={proprio['id']}"


def _nom(personne: dict) -> str:
    return f"{personne.get('prenom') or ''} {personne.get('nom') or ''}".strip()


# ---------------------------------------------------------------------
# Droits (gérant, lot 10)
# ---------------------------------------------------------------------
def droits_jour(acteur: dict, proprio: dict, date, aujourdhui, reel=None) -> dict:
    """Matrice de la spécification §5.1 :
    - le titulaire : tout, aujourd'hui et les 14 jours précédents ;
    - l'Admin : tout, toujours (absence comprise) ;
    - un chef de projet (titulaire ou co-chef) : les lignes de SES projets,
      à toute date, pour les AUTRES employés (lot 20, décision du gérant :
      au-delà de 14 jours, ses propres heures ne sont corrigées que par
      l'Admin, comme pour tout le monde) ; jamais l'absence d'un autre ;
    - sinon : lecture seule.
    Lot 13 (décision 5) : un jour postérieur à la vraie date de la personne
    (`reel`, vu sous date simulée) est en lecture seule pour tout le monde."""
    soi = acteur["id"] == proprio["id"]
    admin = acteur["role"] == "admin"
    debut = aujourdhui - datetime.timedelta(days=dl.FENETRE_LIBRE_JOURS)
    futur_reel = date > (reel or dl.aujourdhui_reel_pour(proprio))
    libre = not futur_reel and (admin or (soi and date >= debut))
    chef = acteur["role"] == "chef_de_projet" and not futur_reel and not soi
    return {
        "mode": "saisie" if soi else "correction",
        "saisie_libre": libre,
        "absence": libre,
        "copie": libre,
        "lignes_de_ses_projets": (not libre) and chef,
        "lecture_seule": (not libre) and not chef,
        "futur_reel": futur_reel,
        "fenetre_debut": debut.isoformat(),
    }


def _modifiable(droits: dict, projet: dict | None) -> bool:
    if droits["saisie_libre"]:
        return True
    return bool(droits["lignes_de_ses_projets"] and projet and projet.get("gere"))


# ---------------------------------------------------------------------
# État d'un jour (format `Jour` de la spécification §3.2)
# ---------------------------------------------------------------------
def _arrondi_grille(minutes: int) -> int:
    return max(dl.PAS_MINUTES, (minutes + dl.PAS_MINUTES // 2) // dl.PAS_MINUTES * dl.PAS_MINUTES)


def _copie(proprio: dict, date, droits: dict) -> dict | None:
    """Dernier jour rempli avant `date` (62 jours au plus), lignes déjà
    filtrées pour `date` (projet visible, ni clos ni pas commencé) et
    remises sur la grille (30 min au moins), total plafonné à 10 h."""
    if not droits["copie"]:
        return None
    source = dl.dernier_jour_rempli(proprio["id"], date, date - datetime.timedelta(days=dl.FENETRE_COPIE_JOURS))
    if source is None:
        return None
    jour = dl.lire_jour(proprio["id"], source)
    infos = dl.projets_info([l["projet_id"] for l in jour["lignes"]], proprio["id"], g.user["id"])
    taches_info = dl.taches_infos([l["tache_id"] for l in jour["lignes"] if l.get("tache_id")], proprio["id"])
    lignes, exclues, total = [], 0, 0
    for ligne in jour["lignes"]:
        projet = infos.get(ligne["projet_id"])
        info_tache = taches_info.get(ligne["tache_id"]) if ligne.get("tache_id") else None
        sienne = bool(info_tache and info_tache.get("intervenant") and dl.tache_saisissable(info_tache, date))
        if (projet is None or not projet["visible"] or not (projet.get("peut_agir", True) or sienne)
                or dl.projet_saisissable(projet, date)
                or (ligne.get("tache_id") and not dl.tache_saisissable(taches_info.get(ligne["tache_id"]), date))):
            exclues += 1
            continue
        minutes = min(_arrondi_grille(ligne["minutes"]), dl.MAX_MINUTES_JOUR - total)
        if minutes < dl.PAS_MINUTES:
            exclues += 1
            continue
        total += minutes
        lignes.append({**ligne, "minutes": minutes, "hors_grille": False, "modifiable": True})
    # Lot 21 (test Chrome) : rien à reprendre — le jour source est quand même
    # donné, l'écran explique pourquoi « Copier » est inactif.
    return {"date": source.isoformat(), "lignes": lignes, "exclues": exclues}


def jour_json(proprio: dict, date, aujourdhui, contexte: bool = True) -> dict:
    acteur = g.user
    jour = dl.lire_jour(proprio["id"], date)
    droits = droits_jour(acteur, proprio, date, aujourdhui)
    infos = dl.projets_info([l["projet_id"] for l in jour["lignes"]], proprio["id"], acteur["id"])
    voit_tout = droits["mode"] == "saisie" or acteur["role"] == "admin"
    # Lot 23 (test Chrome) : ligne d'un projet où la personne n'agit plus
    # (retirée) et hors de SA tâche encore ouverte à cette date : lecture
    # seule à l'écran, comme au serveur (plus d'heures nouvelles).
    infos_taches = dl.taches_infos([l["tache_id"] for l in jour["lignes"] if l.get("tache_id")], proprio["id"])

    def figee(ligne, projet) -> bool:
        if projet.get("peut_agir", True):
            return False
        info = infos_taches.get(ligne["tache_id"]) if ligne.get("tache_id") else None
        return not (info and info.get("intervenant") and dl.tache_saisissable(info, date))

    lignes = []
    for ligne in jour["lignes"]:
        projet = infos.get(ligne["projet_id"]) or {}
        if not voit_tout and not projet.get("visible_acteur"):
            # Projet qu'un chef d'une autre équipe ne voit pas : la durée
            # compte dans les 10 h, rien d'autre n'est dévoilé.
            lignes.append({"masquee": True, "minutes": ligne["minutes"], "modifiable": False,
                           "hors_grille": ligne["hors_grille"]})
            continue
        lignes.append({**ligne, "modifiable": _modifiable(droits, projet) and not figee(ligne, projet),
                       "masquee": False})
    statut = "absent" if jour["absent"] else ("rempli" if lignes else "vide")
    modifie_le = jour["modifie_le"]
    out = {
        "date": date.isoformat(),
        "aujourdhui": aujourdhui.isoformat(),
        # Vraie date de la personne (lot 13, verif-temps N5) : sous date
        # simulée, les jours après elle ne sont pas « à compléter ».
        "aujourdhui_reel": dl.aujourdhui_reel_pour(proprio).isoformat(),
        "statut": statut,
        "version": jour["version"],
        "total_minutes": sum(l["minutes"] for l in lignes),
        "lignes": lignes,
        "droits": droits,
        "modifie_par": jour["modifie_par"],
        "modifie_par_autre": jour["modifie_par_id"] not in (None, proprio["id"]),
        "modifie_le": modifie_le.isoformat() if hasattr(modifie_le, "isoformat") else modifie_le,
    }
    if contexte:
        out["copie"] = None if jour["absent"] else _copie(proprio, date, droits)
        out["manques"] = ([d.isoformat() for d in dl.jours_manques_recents(proprio, aujourdhui=aujourdhui)]
                          if droits["mode"] == "saisie" else [])
        # Lot 14 (revue produit P0-4) : journée vierge de SON Daily log, ses
        # tâches en cours proposées à 0 h (affichées si la personne ne l'a
        # pas désactivé, voir dailylog.js) ; jamais en correction.
        out["proposees"] = (dl.lignes_proposees(proprio, date)
                            if statut == "vide" and droits["mode"] == "saisie" and droits["saisie_libre"]
                            and date.weekday() < 5 else [])
    return out


def _mois_json(proprio: dict, annee: int, mois: int, aujourdhui) -> dict:
    premier = datetime.date(annee, mois, 1)
    dernier = (premier + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
    jours = {}
    if premier <= aujourdhui:
        manques = dl.jours_manques_recents(proprio, aujourdhui=aujourdhui)
        jours = dl.etats_mois(proprio, premier, min(dernier, aujourdhui), manques, aujourdhui=aujourdhui)
    return {"mois": f"{annee:04d}-{mois:02d}", "aujourdhui": aujourdhui.isoformat(), "jours": jours}


# ---------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------
@bp.route("", methods=["GET"])
@role_required(*ROLES_DAILYLOG)
def formulaire():
    proprio = _proprietaire(pour_api=False)
    aujourdhui = dl.aujourdhui_pour(proprio)
    # Lot 16 : le week-end, la page s'ouvre sur le dernier jour ouvré (le
    # vendredi manquant), pas sur le samedi ; le samedi reste accessible.
    defaut = aujourdhui if aujourdhui.weekday() < 5 else dl.jour_ouvre_precedent(aujourdhui)
    date = _date_ou_none(request.args.get("date")) or defaut
    if date > aujourdhui:
        params = {"date": aujourdhui.isoformat()}
        if proprio["id"] != g.user["id"]:
            params["utilisateur"] = proprio["id"]
        return redirect(url_for("dailylog.formulaire", **params))
    soi = proprio["id"] == g.user["id"]
    if soi or g.user["role"] == "admin":
        catalogue = dl.list_lignes_suggerees(proprio["id"])
    else:
        catalogue = dl.list_lignes_suggerees(proprio["id"], gere_par=g.user["id"])
    suffixe = _suffixe(proprio)
    amorce = {
        "jour": jour_json(proprio, date, aujourdhui),
        "mois": _mois_json(proprio, date.year, date.month, aujourdhui),
        "objectifMinutes": dl.get_objectif(proprio["id"]),
        "objectifModifiable": soi,
        "catalogue": catalogue,
        "proprietaire": {"id": proprio["id"], "nom": _nom(proprio), "soi": soi},
        "acteur": {"id": g.user["id"], "role": g.user["role"]},
        "constantes": {
            "pas": dl.PAS_MINUTES, "maxJour": dl.MAX_MINUTES_JOUR, "objMin": dl.OBJECTIF_MIN,
            "objMax": dl.OBJECTIF_MAX, "fenetre": dl.FENETRE_LIBRE_JOURS, "maxLignes": MAX_LIGNES,
        },
        "urls": {
            "page": url_for("dailylog.formulaire"),
            "jour": url_for("dailylog.api_jour", date_iso="AAAA-MM-JJ") + suffixe,
            "absence": url_for("dailylog.api_absence", date_iso="AAAA-MM-JJ") + suffixe,
            "mois": url_for("dailylog.api_mois", mois_iso="AAAA-MM") + suffixe,
            "objectif": url_for("dailylog.api_objectif"),
            "recherche": url_for("dailylog.api_recherche_projets"),
            "taches": url_for("dailylog.api_taches"),
            "connexion": url_for("auth.login"),
            "preference": url_for("main.preference"),
        },
        # Lot 15 : réglage du compte de la personne dont c'est le Daily log.
        "proposer": utilisateurs_repo.get_preferences(proprio["id"])["dailylog_proposer"],
        "suffixe": suffixe,
    }
    personnes = []
    if g.user["role"] in ROLES_CORRECTION:
        personnes = [
            {"id": u["id"], "nom": _nom(u)}
            for u in utilisateurs_repo.list_actifs()
            if u.get("role", "intervenant") in ROLES_DAILYLOG and u["id"] != g.user["id"]
        ]
    contexte = dict(amorce=amorce, textes=TEXTES_DAILYLOG, proprio=proprio, soi=soi, date=date, personnes=personnes)
    # Lot 13 (correctifs, verif-ux) : « Daily log de » charge la page d'une
    # autre personne sans recharger (fragment #dl9, amorce comprise).
    if partiel.est_partiel():
        return partiel.repondre("partials/dailylog_page.html", **contexte)
    return render_template("dailylog.html", **contexte)


# ---------------------------------------------------------------------
# API
# ---------------------------------------------------------------------
def _contexte_jour(date_iso, ecriture: bool = False):
    proprio = _proprietaire()
    aujourdhui = dl.aujourdhui_pour(proprio)
    date = _date_api(date_iso)
    if date > aujourdhui:
        raise ErreurApi(422, "date_future", aujourdhui=aujourdhui.isoformat())
    # Lot 13 (décision 5, audit temps T-I1) : sous date simulée, le futur
    # réel se consulte mais ne s'écrit pas (garde en base : 0019).
    reel = dl.aujourdhui_reel_pour(proprio)
    if ecriture and date > reel:
        raise ErreurApi(422, "futur_reel", aujourdhui_reel=reel.isoformat())
    return proprio, date, aujourdhui


@bp.route("/api/jour/<date_iso>", methods=["GET"])
@api
def api_jour(date_iso):
    proprio, date, aujourdhui = _contexte_jour(date_iso)
    return jsonify(jour_json(proprio, date, aujourdhui))


def _corps() -> dict:
    corps = request.get_json(silent=True)
    if not isinstance(corps, dict) or _entier(corps.get("version"), 0, MAX_VERSION) is None:
        raise ErreurApi(400, "json_invalide")
    return corps


def _lignes_demandees(brutes) -> tuple[list[dict], list[dict]]:
    """Lignes d'une requête : forme stricte (400 sinon) ; doublons signalés."""
    if brutes is None:
        brutes = []
    if not isinstance(brutes, list) or len(brutes) > MAX_LIGNES:
        raise ErreurApi(400, "json_invalide")
    lignes, erreurs, vues = [], [], set()
    for i, brute in enumerate(brutes):
        if not isinstance(brute, dict):
            raise ErreurApi(400, "json_invalide")
        projet_id = _entier(brute.get("projet_id"), 1, MAX_ID)
        tache_brute = brute.get("tache_id")
        tache_id = None if tache_brute is None else _entier(tache_brute, 1, MAX_ID)
        minutes = _entier(brute.get("minutes"), -100000, 100000)
        if projet_id is None or minutes is None or (tache_brute is not None and tache_id is None):
            raise ErreurApi(400, "json_invalide")
        cle = (projet_id, tache_id or 0)
        if cle in vues:
            erreurs.append({"code": "ligne_en_double", "ligne": i, "projet_id": projet_id})
        vues.add(cle)
        lignes.append({"projet_id": projet_id, "tache_id": tache_id, "minutes": minutes, "i": i, "cle": cle})
    return lignes, erreurs


def _ecrire(proprio: dict, date, aujourdhui, corps: dict, absent: bool, lignes_brutes, vider: bool = False):
    acteur = g.user
    droits = droits_jour(acteur, proprio, date, aujourdhui)
    lignes, erreurs = _lignes_demandees(lignes_brutes)
    if absent and lignes:
        erreurs.append({"code": "absent_avec_heures"})
    if erreurs:
        raise ErreurApi(422, "validation", "Saisie refusée.", erreurs=erreurs)
    taches_info = dl.taches_infos([l["tache_id"] for l in lignes if l["tache_id"]], proprio["id"])
    taches = {i: t["projet_id"] for i, t in taches_info.items()}
    demandees = {l["cle"]: l["minutes"] for l in lignes}

    def _tache_encore_sienne(ligne: dict, jour) -> bool:
        """Lot 21 (revue R9) : une personne d'une autre équipe garde ses
        heures sur SA tâche jusqu'à la date de fin de celle-ci, même si le
        projet ne lui est plus ouvert qu'en lecture."""
        info = taches_info.get(ligne["tache_id"]) if ligne["tache_id"] else None
        return bool(info and info.get("intervenant") and dl.tache_saisissable(info, jour))

    def preparer(existantes: dict, absent_actuel: bool):
        infos = dl.projets_info({l["projet_id"] for l in lignes} | {cle[0] for cle in existantes},
                                proprio["id"], acteur["id"])
        errs = []
        hausse = False
        for l in lignes:
            ancien = existantes.get(l["cle"])
            if ancien == l["minutes"]:
                continue  # inchangée : valeur ancienne, projet clos ou invisible depuis… acceptée telle quelle
            # Baisse d'une ligne EXISTANTE (revue 1 du lot 10) : les règles
            # d'imputation (projet visible par la personne, ouvert à cette
            # date) visent l'ajout d'heures et ne jouent pas ici. Sans ça,
            # une ligne ancienne d'un projet clos depuis (ou plus visible)
            # pouvait être supprimée mais pas corrigée à la baisse, même par
            # l'Admin. Le droit de modifier (_modifiable) reste exigé.
            baisse = ancien is not None and l["minutes"] < ancien
            if not baisse:
                hausse = True
            projet = infos.get(l["projet_id"])
            if l["minutes"] <= 0 or l["minutes"] > dl.MAX_MINUTES_JOUR:
                errs.append({"code": "minutes_invalides", "ligne": l["i"]})
            elif l["minutes"] % dl.PAS_MINUTES:
                errs.append({"code": "pas_30_min", "ligne": l["i"]})
            if projet is None or (not projet["visible"] and not baisse):
                errs.append({"code": "projet_invisible", "ligne": l["i"]})
                continue
            if not _modifiable(droits, projet):
                errs.append({"code": "ligne_non_modifiable", "ligne": l["i"]})
                continue
            refus = None if baisse else dl.projet_saisissable(projet, date)
            if refus:
                errs.append({"code": refus, "ligne": l["i"]})
            elif not baisse and not projet.get("peut_agir", True) and not _tache_encore_sienne(l, date):
                errs.append({"code": "projet_lecture_seule", "ligne": l["i"]})
            if l["tache_id"] and taches.get(l["tache_id"]) != l["projet_id"]:
                errs.append({"code": "tache_hors_projet", "ligne": l["i"]})
            elif l["tache_id"] and not baisse and not dl.tache_saisissable(taches_info.get(l["tache_id"]), date):
                errs.append({"code": "tache_close", "ligne": l["i"]})
        voulues = {} if absent else dict(demandees)
        for cle, minutes in existantes.items():
            if cle in demandees or _modifiable(droits, infos.get(cle[0])):
                continue
            if absent:
                errs.append({"code": "ligne_non_modifiable", "projet_id": cle[0]})
            else:
                # Ligne qu'un chef ne gère pas (ou masquée) : gardée telle
                # quelle — elle ne peut être ni modifiée ni supprimée.
                voulues[cle] = minutes
        if absent != absent_actuel and not droits["absence"]:
            errs.append({"code": "absence_non_autorisee"})
        total = sum(voulues.values())
        if total > dl.MAX_MINUTES_JOUR and hausse:
            errs.append({"code": "max_journee", "total_minutes": total})
        if not absent and not voulues and existantes and not vider:
            errs.append({"code": "journee_vide"})
        if errs:
            raise dl.SaisieRefusee(errs)
        return absent, voulues

    try:
        resultat = dl.enregistrer_jour(proprio["id"], date, corps["version"], acteur["id"], preparer)
    except dl.VersionPerimee:
        raise ErreurApi(409, "version_perimee", TEXTES_DAILYLOG["conflit"],
                        jour=jour_json(proprio, date, aujourdhui))
    except dl.SaisieRefusee as e:
        raise ErreurApi(422, "validation", "Saisie refusée.", erreurs=e.erreurs)
    except Exception as exc:
        code = getattr(exc, "pgcode", None)
        if code in ("23514", "23503", "23505"):  # garde-fous de la base (0014), clé étrangère
            current_app.logger.warning("Daily log refusé par la base : %s", exc)
            contrainte = str(getattr(getattr(exc, "diag", None), "constraint_name", "") or "")
            if "dailylog_futur_reel" in contrainte or "vraie date du jour" in str(exc):
                raise ErreurApi(422, "futur_reel")
            if "dailylog_tache_close" in contrainte:
                # Lot 21 (revue R8) : tâche close pendant la saisie.
                raise ErreurApi(422, "validation", "Saisie refusée.", erreurs=[{"code": "tache_close"}])
            raise ErreurApi(422, "refus_base")
        if code == "42501":
            current_app.logger.warning("Daily log refusé par la base (droits) : %s", exc)
            raise ErreurApi(403, "interdit")
        raise
    if resultat["change"] and proprio["id"] != acteur["id"]:
        _notifier_correction(proprio, date)
    out = jour_json(proprio, date, aujourdhui)
    out["enregistre"] = resultat["change"]
    return jsonify(out)


def _notifier_correction(proprio: dict, date) -> None:
    """La personne corrigée est prévenue (une fois par jour corrigé, par
    acteur et par jour). Jamais bloquant."""
    message = f"Daily log du {date.strftime('%d/%m/%Y')} corrigé par {_nom(g.user)}."
    try:
        if not notifications_repo.a_deja_la_notification(proprio["id"], message):
            notifications_repo.creer(proprio["id"], "rh_info", message)
    except Exception:
        current_app.logger.exception("Notification de correction du Daily log impossible")


@bp.route("/api/jour/<date_iso>", methods=["PUT"])
@api
def api_jour_enregistrer(date_iso):
    proprio, date, aujourdhui = _contexte_jour(date_iso, ecriture=True)
    corps = _corps()
    vider = corps.get("vider", False)
    if not isinstance(vider, bool):
        raise ErreurApi(400, "json_invalide")
    return _ecrire(proprio, date, aujourdhui, corps, False, corps.get("lignes"), vider=vider)


@bp.route("/api/jour/<date_iso>/absence", methods=["POST"])
@api
def api_absence(date_iso):
    proprio, date, aujourdhui = _contexte_jour(date_iso, ecriture=True)
    corps = _corps()
    absent = corps.get("absent")
    if not isinstance(absent, bool):
        raise ErreurApi(400, "json_invalide")
    # Annuler l'absence peut rendre les lignes d'avant (bouton « Annuler »).
    return _ecrire(proprio, date, aujourdhui, corps, absent, corps.get("lignes"))


@bp.route("/api/mois/<mois_iso>", methods=["GET"])
@api
def api_mois(mois_iso):
    proprio = _proprietaire()
    if not _RE_MOIS.match(mois_iso):
        raise ErreurApi(400, "mois_invalide", "Mois invalide.")
    annee, mois = int(mois_iso[:4]), int(mois_iso[5:])
    if not 1 <= mois <= 12 or annee < DATE_MIN.year or annee > DATE_MAX.year:
        raise ErreurApi(400, "mois_invalide", "Mois invalide.")
    return jsonify(_mois_json(proprio, annee, mois, dl.aujourdhui_pour(proprio)))


@bp.route("/api/objectif", methods=["PUT"])
@api
def api_objectif():
    corps = request.get_json(silent=True)
    if not isinstance(corps, dict):
        raise ErreurApi(400, "json_invalide")
    minutes = _entier(corps.get("objectif_minutes"), dl.OBJECTIF_MIN, dl.OBJECTIF_MAX)
    if minutes is None or minutes % dl.PAS_MINUTES:
        raise ErreurApi(422, "objectif_invalide", "Objectif\u00a0: de 4 h à 10 h par pas de 30 min.")
    dl.set_objectif(g.user["id"], minutes)
    return jsonify({"objectif_minutes": minutes})


def _date_de_recherche(proprio: dict):
    brute = request.args.get("date")
    if brute in (None, ""):
        return dl.aujourdhui_pour(proprio)
    return _date_api(brute)


@bp.route("/recherche-projets")
@api
def api_recherche_projets():
    """Recherche du catalogue « + Ajouter un projet » (≥ 2 caractères)."""
    proprio = _proprietaire()
    date = _date_de_recherche(proprio)
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"resultats": []})
    if len(q) > MAX_RECHERCHE:
        raise ErreurApi(400, "recherche_trop_longue", "Recherche trop longue.")
    gere_par = None
    if proprio["id"] != g.user["id"] and g.user["role"] != "admin":
        gere_par = g.user["id"]
    return jsonify({"resultats": dl.rechercher_projets(q, proprio["id"], date, gere_par=gere_par)})


@bp.route("/api/taches")
@api
def api_taches():
    """Tâches en cours d'un projet, pour imputer une ligne à une tâche."""
    proprio = _proprietaire()
    date = _date_de_recherche(proprio)
    brut = request.args.get("projet") or ""
    if not _RE_ID.match(brut):
        raise ErreurApi(400, "projet_invalide", "Projet invalide.")
    projet_id = int(brut)
    infos = dl.projets_info([projet_id], proprio["id"], g.user["id"])
    projet = infos.get(projet_id)
    droits = droits_jour(g.user, proprio, date, dl.aujourdhui_pour(proprio))
    if projet is None or not projet["visible"] or not _modifiable(droits, projet):
        raise ErreurApi(404, "projet_introuvable", "Projet introuvable.")
    return jsonify({"projet_id": projet_id, "taches": dl.taches_ouvertes(projet_id)})


# ---------------------------------------------------------------------
# Daily log de l'équipe (lot 14, revue produit P1-9)
# ---------------------------------------------------------------------
LIBELLES_CASE = {
    "rempli": "rempli",
    "absent": "absent",
    "manquant": "non renseigné",
    "attente": "aujourd’hui, pas encore saisi",
    "verrouille": "non renseigné, au-delà de 14 jours",
    "futur": "à venir",
    "avant": "avant son arrivée",
    "week_end": "week-end",
}


def _lundi(jour: datetime.date) -> datetime.date:
    return jour - datetime.timedelta(days=jour.weekday())


def _titre_semaine(lundi: datetime.date) -> str:
    vendredi = lundi + datetime.timedelta(days=4)
    debut = "1er" if lundi.day == 1 else str(lundi.day)
    fin = "1er" if vendredi.day == 1 else str(vendredi.day)
    mois = utils.MOIS_COMPLETS
    if lundi.year != vendredi.year:
        return f"Semaine du {debut} {mois[lundi.month - 1]} {lundi.year} au {fin} {mois[vendredi.month - 1]} {vendredi.year}"
    if lundi.month != vendredi.month:
        return f"Semaine du {debut} {mois[lundi.month - 1]} au {fin} {mois[vendredi.month - 1]} {vendredi.year}"
    return f"Semaine du {debut} au {fin} {mois[vendredi.month - 1]} {vendredi.year}"


def _lien_jour(personne: dict, date: datetime.date) -> str:
    if personne["id"] == g.user["id"]:
        return url_for("dailylog.formulaire", date=date.isoformat())
    return url_for("dailylog.formulaire", date=date.isoformat(), utilisateur=personne["id"])


def contexte_equipe(lundi: datetime.date) -> dict:
    """Tableau personnes × jours ouvrés d'une semaine. L'Admin voit tout le
    bureau, un chef de projet les personnes de ses projets en cours (lui
    compris). Une case = l'état du jour au fuseau de la personne (mêmes
    règles que le rappel) ; le total d'une personne compte aussi le
    week-end. Les heures ne disent rien des projets : la correction ouverte
    depuis une case garde ses propres règles (lignes masquées…)."""
    jours = [lundi + datetime.timedelta(days=i) for i in range(5)]
    dimanche = lundi + datetime.timedelta(days=6)
    gere_par = None if g.user["role"] == "admin" else g.user["id"]
    personnes = dl.membres_equipe(gere_par)
    synthese = dl.synthese_periode([p["id"] for p in personnes], lundi, dimanche)
    totaux = [{"minutes": 0, "manquants": 0} for _ in jours]
    lignes, manquants, personnes_en_manque = [], 0, 0
    for p in personnes:
        cases, total_semaine, manque = [], 0, False
        for i in range(7):
            date = lundi + datetime.timedelta(days=i)
            case = synthese.get((p["id"], date)) or {"minutes": 0, "absent": False}
            total_semaine += case["minutes"]
            if i >= 5:
                continue
            etat = dl.etat_case(p, date, case)
            if etat == "manquant":
                manquants += 1
                manque = True
                totaux[i]["manquants"] += 1
            totaux[i]["minutes"] += case["minutes"]
            cases.append({
                "date": date, "etat": etat, "minutes": case["minutes"], "libelle": LIBELLES_CASE[etat],
                "lien": None if etat in ("futur", "week_end") else _lien_jour(p, date),
            })
        personnes_en_manque += manque
        week_end = sum((synthese.get((p["id"], lundi + datetime.timedelta(days=i))) or {}).get("minutes", 0)
                       for i in (5, 6))
        lignes.append({"personne": p, "nom": _nom(p), "soi": p["id"] == g.user["id"], "cases": cases,
                       "total_minutes": total_semaine, "week_end_minutes": week_end})
    aujourdhui = dl.aujourdhui_pour(g.user)
    courant = _lundi(aujourdhui)
    return {
        "lundi": lundi, "jours": jours, "lignes": lignes, "totaux": totaux,
        "total_minutes": sum(l["total_minutes"] for l in lignes),
        "manquants": manquants, "personnes_en_manque": personnes_en_manque,
        "titre_semaine": _titre_semaine(lundi),
        "precedente": lundi - datetime.timedelta(days=7) if lundi - datetime.timedelta(days=7) >= _lundi(DATE_MIN) else None,
        "suivante": lundi + datetime.timedelta(days=7) if lundi < courant else None,
        "courante": courant, "est_courante": lundi == courant, "admin": gere_par is None,
    }


@bp.route("/equipe", methods=["GET"])
@role_required(*ROLES_CORRECTION)
def equipe():
    """Daily log de l'équipe : qui a rempli, qui manque, semaine par semaine
    (navigation en partiel, #dlq). Lecture seule : un clic sur une case
    ouvre le Daily log de la personne à ce jour, avec les droits de
    correction habituels."""
    aujourdhui = dl.aujourdhui_pour(g.user)
    demande = _date_ou_none(request.args.get("semaine"))
    lundi = _lundi(min(demande or aujourdhui, aujourdhui))
    contexte = contexte_equipe(lundi)
    if partiel.est_partiel():
        return partiel.repondre("partials/dailylog_equipe.html", **contexte)
    return render_template("dailylog_equipe.html", **contexte)

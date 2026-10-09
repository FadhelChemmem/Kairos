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
    "confirmer_vider": "Vider toute la journée du {x} ? Les heures enregistrées seront supprimées.",
    "journee_videe": "Journée vidée",
    "journee_enregistree": "Journée enregistrée ✓",
    "auto_enregistre": "{x} enregistré automatiquement ({y})",
    "vide_ignoree": "{x} : saisie vide ignorée, dernière version conservée",
    "max_ligne": "Maximum {x} sur cette ligne (10 h par jour)",
    "journee_pleine": "Journée pleine (10 h)",
    "arrondi": "Arrondi à {x} (pas de 30 min)",
    "saisie_vide": "Saisie vide — touchez le nom du projet pour le désactiver",
    "format_inconnu": "Format non reconnu — exemples : 2,5 · 2h30 · 45min",
    "max_10h_nombre": "Maximum 10 h — pour des minutes, ajoutez « min » (ex. 45min)",
    "minimum_30": "Minimum 30 min (la saisie va par pas de 30 min)",
    "ajoute": "{x} ajouté — {y}",
    "copier_le": "Copier le {x}",
    "copier_aucun": "Copier la veille",
    "copier_aucun_titre": "Aucune journée précédente avec des heures",
    "copie_depuis": "Copié depuis le {x}",
    "copie_exclues": " — {x} ligne non reprise : projet clos, pas encore commencé ou plus visible",
    "copie_exclues_pl": " — {x} lignes non reprises : projet clos, pas encore commencé ou plus visible",
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
    "aucun_projet_futur": "Jour à venir : consultation seulement.",
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
    "aucune_tache": "Aucune tâche en cours.",
    "total": "Total",
    "jauge": "Total de la journée",
    "sur": "{x} sur {y}",
    "aucune_heure": "Aucune heure saisie",
    "journee_complete": "Journée complète ({x}) ✓",
    "sous_journee": "{x} sous la journée de {y}",
    "au_dessus": "+{x} au-dessus de {y}",
    "annonce_total_ok": "Total {x} : journée complète",
    "annonce_total_sous": "Total {x} : sous la journée",
    "annonce_total_dessus": "Total {x} : au-dessus de la journée",
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
    "banniere": "{x} sans saisie",
    "banniere_jour": "jour",
    "banniere_jours": "jours",
    "banniere_suite": " — à compléter : ",
    "banniere_plus": "+ {x} plus ancien",
    "banniere_plus_pl": "+ {x} plus anciens",
    "banniere_cal": " (voir le calendrier)",
    "heures_sur": "Heures sur {x} (pas de 30 minutes)",
    "moins_30": "Moins 30 minutes sur {x}",
    "plus_30": "Plus 30 minutes sur {x}",
    "activer": "Activer ou désactiver {x}",
    "ligne_verrouillee": "Projet géré par un autre chef : lecture seule",
    "ligne_verrouillee_fenetre": "Au-delà de 14 jours : correction par le chef de projet ou l’Admin",
    "ligne_masquee": "Projet non visible pour vous",
    "lecture_seule": "Au-delà de 14 jours, seule une correction par votre chef de projet ou l’Admin est possible.",
    "futur_reel": "Date simulée : ce jour est après la vraie date du jour — affichage seulement, aucune saisie (mode test).",
    "ligne_futur_reel": "Jour après la vraie date du jour : lecture seule (mode test)",
    "lecture_seule_chef": "Au-delà de 14 jours, vous ne pouvez modifier que les lignes de vos projets.",
    "correction": "Correction du Daily log de {x} — vos modifications seront tracées à votre nom.",
    "correction_chef": " Seules les lignes de vos projets sont modifiables.",
    "modifie_par": "Dernière modification par {x}",
    "conflit": "Cette journée a été modifiée ailleurs (autre onglet, appareil ou correction du chef).",
    "garder_ma_saisie": "Garder ma saisie",
    "reprendre": "Reprendre la version enregistrée",
    "session_expiree": "Session expirée : reconnectez-vous ; votre saisie est gardée sur cet appareil.",
    "se_reconnecter": "Se reconnecter",
    "brouillon_trouve": "Une saisie non enregistrée du {x} a été retrouvée sur cet appareil.",
    "restaurer": "Restaurer",
    "reseau": "Non enregistré : connexion impossible. Nouvel essai au prochain enregistrement.",
    "erreur_serveur": "Non enregistré : erreur du serveur.",
    "non_enregistre_autre_jour": "{x} non enregistré ({y}).",
    "cause_reseau": "connexion impossible",
    "cause_serveur": "erreur du serveur",
    "brouillon_garde": " Votre saisie est gardée sur cet appareil : revenez sur ce jour pour la restaurer.",
    "revenir": "Revenir à ce jour",
    "chargement_impossible": "Impossible de charger ce jour.",
    "valeurs_arrondies": "Anciennes valeurs hors grille arrondies au pas de 30 min.",
    "quitter": "Le dernier enregistrement a échoué : quitter quand même ?",
    "erreurs": {
        "minutes_invalides": "Durée invalide (de 30 min à 10 h par ligne).",
        "pas_30_min": "Les heures vont par pas de 30 minutes.",
        "max_journee": "10 h au plus par jour.",
        "journee_vide": "La journée enregistrée ne peut pas être vidée ainsi : utilisez « Vider la journée » ou « Marquer absent ».",
        "ligne_en_double": "Le même projet (ou la même tâche) apparaît deux fois.",
        "absent_avec_heures": "Un jour absent ne porte pas d’heures.",
        "projet_invisible": "Projet introuvable ou plus accessible.",
        "projet_clos": "Projet clos à cette date : plus d’heures après sa clôture.",
        "projet_pas_commence": "Projet pas encore commencé à cette date.",
        "tache_hors_projet": "Cette tâche n’appartient pas au projet de la ligne.",
        "ligne_non_modifiable": "Ligne non modifiable : au-delà de 14 jours, seuls le chef du projet ou l’Admin corrigent.",
        "absence_non_autorisee": "Absence non modifiable pour ce jour.",
        "date_future": "Pas de saisie pour un jour futur.",
        "futur_reel": "Pas de saisie après la vraie date du jour, même sous date simulée (mode test : la date simulée sert à voir le futur, pas à y écrire).",
        "date_invalide": "Date invalide.",
        "refus_base": "Saisie refusée.",
        "interdit": "Action non autorisée.",
        "json_invalide": "Requête invalide.",
        "csrf": "Session expirée : rechargez la page.",
        "non_connecte": "Session expirée : reconnectez-vous.",
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
      à toute date et pour n'importe quel employé ; jamais l'absence d'un
      autre ;
    - sinon : lecture seule.
    Lot 13 (décision 5) : un jour postérieur à la vraie date de la personne
    (`reel`, vu sous date simulée) est en lecture seule pour tout le monde."""
    soi = acteur["id"] == proprio["id"]
    admin = acteur["role"] == "admin"
    debut = aujourdhui - datetime.timedelta(days=dl.FENETRE_LIBRE_JOURS)
    futur_reel = date > (reel or dl.aujourdhui_reel_pour(proprio))
    libre = not futur_reel and (admin or (soi and date >= debut))
    chef = acteur["role"] == "chef_de_projet" and not futur_reel
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
    lignes, exclues, total = [], 0, 0
    for ligne in jour["lignes"]:
        projet = infos.get(ligne["projet_id"])
        if projet is None or not projet["visible"] or dl.projet_saisissable(projet, date):
            exclues += 1
            continue
        minutes = min(_arrondi_grille(ligne["minutes"]), dl.MAX_MINUTES_JOUR - total)
        if minutes < dl.PAS_MINUTES:
            exclues += 1
            continue
        total += minutes
        lignes.append({**ligne, "minutes": minutes, "hors_grille": False, "modifiable": True})
    if not lignes:
        return None
    return {"date": source.isoformat(), "lignes": lignes, "exclues": exclues}


def jour_json(proprio: dict, date, aujourdhui, contexte: bool = True) -> dict:
    acteur = g.user
    jour = dl.lire_jour(proprio["id"], date)
    droits = droits_jour(acteur, proprio, date, aujourdhui)
    infos = dl.projets_info([l["projet_id"] for l in jour["lignes"]], proprio["id"], acteur["id"])
    voit_tout = droits["mode"] == "saisie" or acteur["role"] == "admin"
    lignes = []
    for ligne in jour["lignes"]:
        projet = infos.get(ligne["projet_id"]) or {}
        if not voit_tout and not projet.get("visible_acteur"):
            # Projet qu'un chef d'une autre équipe ne voit pas : la durée
            # compte dans les 10 h, rien d'autre n'est dévoilé.
            lignes.append({"masquee": True, "minutes": ligne["minutes"], "modifiable": False,
                           "hors_grille": ligne["hors_grille"]})
            continue
        lignes.append({**ligne, "modifiable": _modifiable(droits, projet), "masquee": False})
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
    date = _date_ou_none(request.args.get("date")) or aujourdhui
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
        },
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
    taches = dl.taches_projet([l["tache_id"] for l in lignes if l["tache_id"]])
    demandees = {l["cle"]: l["minutes"] for l in lignes}

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
            if l["tache_id"] and taches.get(l["tache_id"]) != l["projet_id"]:
                errs.append({"code": "tache_hors_projet", "ligne": l["i"]})
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
            if "dailylog_futur_reel" in str(getattr(getattr(exc, "diag", None), "constraint_name", "") or "") \
                    or "vraie date du jour" in str(exc):
                raise ErreurApi(422, "futur_reel")
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
        raise ErreurApi(422, "objectif_invalide", "Objectif : de 4 h à 10 h par pas de 30 min.")
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

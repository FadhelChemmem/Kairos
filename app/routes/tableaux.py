"""Tableaux de bord de l'accueil (lot 14) : contexte et fragments.

- **Vue d'ensemble** (Admin, revue produit P0-3) : 4 tuiles (tâches en
  retard, bloquées, projets sans tâche ouverte, Daily log manquants du
  dernier jour ouvré) ; une tuile déplie sa liste sous les tuiles
  (`?voir=<clé>`, fragment `#vue-ensemble`, sans recharger la page) ;
  tableau « Par chef de projet ».
- **À traiter** (chef de projet et co-chef, P1-2) : mêmes compteurs sur
  ses projets, plus les tâches sans intervenant et sans échéance ; chaque
  ligne déplie sa liste (fragment `#a-traiter`).
- **Tâches de mes projets** : « Les miennes | Toutes » (`?taches=miennes`,
  fragment `#accueil-taches`).

Le périmètre vient toujours du compte (g.user) : aucun paramètre ne
permet de voir les projets d'un autre.
"""
import datetime

from flask import g, request, url_for

from .. import partiel
from ..repositories import dailylog as dl
from ..repositories import tableaux as tb
from ..utils import JOURS_COMPLETS, MOIS_COMPLETS

CIBLE_VUE = "#vue-ensemble"
CIBLE_A_TRAITER = "#a-traiter"
CIBLE_TACHES = "#accueil-taches"
NB_TACHES_CARTE = 5

# Ordre et libellés des compteurs (singulier, pluriel).
LIBELLES = {
    "retard": ("tâche en retard", "tâches en retard"),
    "bloquees": ("tâche bloquée", "tâches bloquées"),
    "sans_intervenant": ("tâche sans intervenant", "tâches sans intervenant"),
    "sans_echeance": ("tâche sans échéance", "tâches sans échéance"),
    "projets_sans_tache": ("projet sans tâche ouverte", "projets sans tâche ouverte"),
    "dailylog": ("Daily log manquant", "Daily log manquants"),
}
TUILES_ADMIN = ("retard", "bloquees", "projets_sans_tache", "dailylog")
# Mêmes rôles que routes/dailylog.py:ROLES_CORRECTION (Daily log d'une autre
# personne, page « Daily log de l'équipe »).
ROLES_CORRECTION_DAILYLOG = ("admin", "chef_de_projet")
LIGNES_CHEF = ("retard", "bloquees", "sans_intervenant", "sans_echeance", "projets_sans_tache", "dailylog")


def jour_dailylog(aujourdhui: datetime.date) -> datetime.date:
    """Dernier jour ouvré avant aujourd'hui (le lundi : le vendredi)."""
    return dl.jour_ouvre_precedent(aujourdhui)


def libelle_jour(jour: datetime.date, aujourdhui: datetime.date) -> str:
    """« hier », sinon le jour de la semaine (« vendredi » vu un lundi)."""
    if jour == aujourdhui - datetime.timedelta(days=1):
        return "hier"
    return JOURS_COMPLETS[jour.weekday()].lower()


def lire_voir(cles=tb.CLES) -> str | None:
    v = request.args.get("voir")
    return v if v in cles else None


def lire_mode_taches() -> str:
    return "miennes" if request.args.get("taches") == "miennes" else "toutes"


def url_accueil(voir: str | None = None, taches: str | None = None) -> str:
    """Adresse de l'accueil qui garde l'autre réglage (liste dépliée, mode
    des tâches) : chaque lien ne change que le sien."""
    params = {}
    if voir:
        params["voir"] = voir
    if taches == "miennes":
        params["taches"] = "miennes"
    return url_for("main.accueil", **params)


def peut_vue_ensemble(user: dict) -> bool:
    return user["role"] == "admin"


def peut_a_traiter(user: dict, gere: bool | None = None) -> bool:
    """Chef de projet, ou intervenant co-chef d'un projet ouvert."""
    if user["role"] == "chef_de_projet":
        return True
    if user["role"] != "intervenant":
        return False
    return tb.gere_des_projets(user["id"]) if gere is None else gere


def lignes_a_traiter(user: dict) -> tuple[str, ...]:
    """Lignes de « À traiter » : « Daily log manquants » seulement pour qui
    peut ouvrir le Daily log des autres (chef de projet ; recette du lot
    14, n° 8 — un intervenant co-chef n'y a pas droit, ses liens
    menaient à un 403)."""
    if user["role"] in ROLES_CORRECTION_DAILYLOG:
        return LIGNES_CHEF
    return tuple(c for c in LIGNES_CHEF if c != "dailylog")


def _bloc(user: dict, tous: bool, aujourdhui: datetime.date, voir: str | None, cles) -> dict:
    jour = jour_dailylog(aujourdhui)
    compte = tb.compteurs(user["id"], tous, aujourdhui, jour)
    detail = None
    if "dailylog" in cles:
        # Même périmètre et mêmes règles que la page « Daily log de
        # l'équipe » (recette du lot 14, n° 9).
        manquants = dl.manquants_du_jour(None if tous else user["id"], jour)
        compte["dailylog"] = len(manquants)
        if voir == "dailylog":
            detail = manquants
    if voir in cles and voir != "dailylog":
        detail = tb.liste(voir, user["id"], tous, aujourdhui, jour)
    mode = lire_mode_taches()
    return {
        "compte": compte,
        "cles": cles,
        "voir": voir if voir in cles else None,
        "detail": detail,
        "jour": jour,
        "jour_libelle": libelle_jour(jour, aujourdhui),
        "jour_texte": f"{JOURS_COMPLETS[jour.weekday()].lower()} {jour.day} {MOIS_COMPLETS[jour.month - 1]}",
        "aujourdhui": aujourdhui,
        "liens": {c: url_accueil(None if voir == c else c, mode) for c in cles},
        "lien_fermer": url_accueil(None, mode),
        "libelles": LIBELLES,
        "total": sum(compte[c] for c in cles),
    }


def contexte_vue_ensemble(user: dict, aujourdhui: datetime.date, voir: str | None = None) -> dict:
    return _bloc(user, True, aujourdhui, voir, TUILES_ADMIN)


def contexte_a_traiter(user: dict, aujourdhui: datetime.date, voir: str | None = None) -> dict:
    return _bloc(user, False, aujourdhui, voir, lignes_a_traiter(user))


def contexte_par_chef(aujourdhui: datetime.date) -> dict:
    lundi = aujourdhui - datetime.timedelta(days=aujourdhui.weekday())
    lignes = tb.par_chef(aujourdhui, lundi)
    total = {
        "projets": sum(int(r["projets"] or 0) for r in lignes),
        "retard": sum(int(r["retard"] or 0) for r in lignes),
        "bloquees": sum(int(r["bloquees"] or 0) for r in lignes),
        "heures": sum(float(r["heures"] or 0) for r in lignes),
    }
    return {"lignes": lignes, "total": total, "lundi": lundi}


def contexte_taches(user: dict, mode: str, voir: str | None = None) -> dict:
    """Carte « Tâches de mes projets » : les 5 premières de chaque mode."""
    lignes = tb.taches_de_mes_projets(user["id"])
    miennes = [t for t in lignes if t["mienne"]]
    choisies = miennes if mode == "miennes" else lignes
    return {
        "mode": mode,
        "taches": choisies[:NB_TACHES_CARTE],
        "nb": len(choisies),
        "nb_toutes": len(lignes),
        "nb_miennes": len(miennes),
        "liens": {"toutes": url_accueil(voir, "toutes"), "miennes": url_accueil(voir, "miennes")},
    }


def fragment(cible: str | None):
    """Réponse partielle de l'accueil pour une de nos cibles, None sinon.
    Une cible demandée sans en avoir le droit est refusée (403 JSON)."""
    if cible not in (CIBLE_VUE, CIBLE_A_TRAITER, CIBLE_TACHES):
        return None
    user = g.user
    aujourdhui = dl.aujourdhui_pour(user)
    if cible == CIBLE_VUE:
        if not peut_vue_ensemble(user):
            return partiel.refuser("Vue d’ensemble réservée à l’Admin.", 403)
        return partiel.repondre("partials/vue_ensemble.html",
                                ve=contexte_vue_ensemble(user, aujourdhui, lire_voir(TUILES_ADMIN)))
    if cible == CIBLE_A_TRAITER:
        if not peut_a_traiter(user):
            return partiel.refuser("Carte «\u00a0À traiter\u00a0» réservée aux chefs de projet.", 403)
        return partiel.repondre("partials/a_traiter.html",
                                at=contexte_a_traiter(user, aujourdhui, lire_voir(lignes_a_traiter(user))))
    if not (user["role"] in ("admin", "chef_de_projet") or peut_a_traiter(user)):
        return partiel.refuser("Ces tâches sont réservées aux chefs de projet.", 403)
    return partiel.repondre("partials/accueil_taches.html", aujourdhui=aujourdhui,
                            tdp=contexte_taches(user, lire_mode_taches(), lire_voir()))


def contexte_page(user: dict, aujourdhui: datetime.date, mes_projets: list[dict]) -> dict:
    """Ajouts du lot 14 au contexte de la page d'accueil complète."""
    role = user["role"]
    ctx = {"ve": None, "at": None, "par_chef": None, "tdp": None, "masquer_dailylog": False,
           "pastilles": tb.pastilles_projets([p["id"] for p in mes_projets], aujourdhui) if role != "client" else {}}
    if role in ("rh", "client"):
        return ctx
    voir = lire_voir()
    gere = role == "chef_de_projet" or (role == "intervenant" and tb.gere_des_projets(user["id"]))
    if peut_vue_ensemble(user):
        ctx["ve"] = contexte_vue_ensemble(user, aujourdhui, voir)
        ctx["par_chef"] = contexte_par_chef(aujourdhui)
        ctx["masquer_dailylog"] = not tb.saisit_des_heures(user["id"])
    elif peut_a_traiter(user, gere):
        ctx["at"] = contexte_a_traiter(user, aujourdhui, voir)
    if role == "admin" or gere:
        ctx["tdp"] = contexte_taches(user, lire_mode_taches(), voir)
    return ctx

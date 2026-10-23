"""Page d'accueil — porte Main.dc.html en template Jinja2 réel."""

from flask import Blueprint, current_app, g, render_template, request, url_for

from .. import fil as film
from .. import horloge, partiel
from ..auth import login_required
from ..repositories import dailylog as dailylog_repo
from ..repositories import posts, projets, taches, utilisateurs
from ..utils import build_gantt
from . import tableaux

bp = Blueprint("main", __name__)


# Posts par page du fil de l'accueil (lot 14 : « Afficher plus » au-delà).
TAILLE_FIL_ACCUEIL = 20


def contexte_fil_accueil(user_id: int) -> dict:
    """Fil de l'accueil (lot 14, revue produit P1-3) : catégorie demandée
    (Tout · Échanges · Activité), page à partir du curseur `avant`,
    évènements automatiques regroupés, adresse de la page suivante."""
    categorie = film.categorie_demandee("accueil")
    instant = _instant_lecture()
    taille = film.taille_jusqua(TAILLE_FIL_ACCUEIL,
                                lambda post_id: posts.rang_dans_fil_mes_projets(user_id, categorie, post_id))
    lus = posts.list_feed_mes_projets(user_id, limit=taille + 1, categorie=categorie,
                                      avant=film.curseur_demande())
    fil, curseur = film.page(lus, taille)
    non_vus = marquer_nouveaux(user_id, categorie, fil, instant, suite=bool(curseur))
    return dict(fil=fil, fil_entrees=film.regrouper(fil), fil_categorie=categorie, fil_non_vus=non_vus,
                fil_suite_id="fil-suite", fil_suite_cible="#fil-liste",
                fil_suite_url=url_for("main.accueil", fil=categorie, avant=curseur) if curseur else None)


def _instant_lecture():
    """Horloge de la base avant la lecture du fil (posts arrivés pendant la
    lecture : ils restent « nouveaux »)."""
    if film.curseur_demande():
        return None
    try:
        return posts.instant_base()
    except Exception:
        current_app.logger.exception("Posts non vus\u00a0: horloge illisible")
        return None


def marquer_nouveaux(user_id: int, categorie: str, fil: list[dict], instant=None, suite: bool = False) -> dict:
    """Lot 17 (demande du gérant) : posts arrivés depuis la dernière visite
    de leur catégorie (hors les siens) marqués « nouveau » ; nombre de
    nouveautés des AUTRES catégories pour leurs onglets ; la catégorie
    affichée (les deux pour « Tout ») devient vue. Première page seulement."""
    if film.curseur_demande():
        return {}
    try:
        vus = posts.fil_vu(user_id)
        non_vus = posts.compter_non_vus(user_id, vus)
    except Exception:
        current_app.logger.exception("Posts non vus : lecture impossible")
        return {}
    for p in fil:
        seuil = vus.get("activite" if p.get("est_activite") else "echanges")
        p["nouveau"] = bool(seuil and p.get("created_at") and p["created_at"] > seuil
                            and p.get("auteur_id") != user_id)
    vues = ("echanges", "activite") if categorie == "tout" else (categorie,)
    # Lot 20 (revue QA, 12c) : chaque catégorie est vue jusqu'à son post le
    # plus récent AFFICHÉ (les dates suivent la date simulée en mode test) ;
    # sans post affiché, jusqu'à l'instant relevé avant la lecture.
    affiches = {}
    for p in fil:
        c = "activite" if p.get("est_activite") else "echanges"
        if p.get("created_at") and (c not in affiches or p["created_at"] > affiches[c]):
            affiches[c] = p["created_at"]
    # Lot 25 (FL-03) : sur « Tout », une catégorie absente d'une première
    # page suivie d'autres (`suite`) n'est pas marquée vue (ses nouveautés
    # sont peut-être plus bas) ; sans suite, tout le fil est là : vue.
    incomplet = categorie == "tout" and suite
    instants = {c: affiches.get(c, None if incomplet else instant) for c in vues}
    instants = {c: v for c, v in instants.items() if v is not None}
    # Ni en « Voir comme » ni en « Agir comme » : l'Admin qui teste ne
    # consomme pas les nouveautés de la personne.
    if not g.get("lecture_seule") and not g.get("mode_admin"):
        try:
            if instants:
                posts.marquer_fil_vu(user_id, tuple(instants), instants)
        except Exception:
            current_app.logger.exception("Posts non vus\u00a0: enregistrement impossible")
    return {c: n for c, n in non_vus.items() if c not in instants and n}


def _fil_partiel(user_id: int):
    """Lot 14 : changement de catégorie (liste remplacée) ou « Afficher
    plus » (page suivante ajoutée), en partiel sur #fil-liste."""
    ctx = contexte_fil_accueil(user_id)
    if film.curseur_demande():
        return partiel.repondre("partials/fil_page.html", show_projet=True,
                                next_url=url_for("main.accueil", fil=ctx["fil_categorie"]), **ctx)
    return partiel.repondre("partials/fil_maj.html", fil_gabarit="partials/fil_accueil.html", **ctx)


@bp.route("/sante")
def sante():
    """Lot 20 (revue QA n° 7) : contrôle de santé de Docker et de deploy.sh.
    /connexion répondait 200 base arrêtée ; ici la base est interrogée.
    Sans connexion ni session, rien de personnel."""
    from .. import db

    try:
        db.query_one("SELECT 1 AS ok")
    except Exception:
        current_app.logger.warning("Santé\u00a0: base de données injoignable")
        return "base indisponible\n", 503, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}
    return "ok\n", 200, {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"}


@bp.route("/accueil")
@login_required
def accueil():
    user_id = g.user["id"]
    role = g.user["role"]
    if partiel.est_partiel() == "#fil-liste":
        return _fil_partiel(user_id)
    # RH : aucun accès aux projets ni Daily log ; Client : les projets de son
    # équipe, sans Daily log ni tâches (décisions Fadhel, lot 7).
    # Lot 14 : tuiles, carte « À traiter », « Les miennes | Toutes » en
    # mise à jour partielle (routes/tableaux.py).
    fragment = tableaux.fragment(partiel.est_partiel())
    if fragment is not None:
        return fragment
    if role == "rh":
        return _accueil_rh(user_id)
    if role == "client":
        # Lot 18 : les échéances de tous les projets de son équipe.
        toutes_echeances = taches.list_deadlines_equipe(user_id, limit=500)
    elif role == "admin":
        # Vue d'ensemble (revue produit P0-3) : les échéances du bureau.
        toutes_echeances = taches.list_deadlines_tous(limit=500)
    else:
        toutes_echeances = taches.list_deadlines(user_id, limit=500)
    deadlines = toutes_echeances[:12 if role in ("admin", "client") else 6]
    # « Aujourd'hui » au fuseau de la personne (lot 10 pour le Daily log,
    # lot 11 pour les échéances : Guyane / Tunis).
    aujourdhui_local = dailylog_repo.aujourdhui_pour(g.user)
    # Bannière d'accueil (retour Fadhel, 2026-09-19) : mini-Gantt simplifié
    # (jours + barres, sans les filtres/légende de la page Deadlines).
    # Lot 15 : repliée par défaut en une ligne (résumé), dépliée selon le
    # choix mémorisé du compte (utilisateur_preference.accueil_deadlines).
    deadlines_gantt = build_gantt(deadlines, aujourdhui_local, window_days=14)
    deadlines_resume = resume_echeances(toutes_echeances, aujourdhui_local)
    # Lot 14 (revue produit P0-1) : section « Bloquées (n) » sous Mes tâches
    # — celles de mes projets ; pour l'Admin, celles du bureau.
    taches_bloquees = [] if role == "client" else taches.list_bloquees(user_id, tous=role == "admin")
    fil = contexte_fil_accueil(user_id)
    # Daily log (lot 10) : jours oubliés au fuseau de la personne, bornés
    # par sa date d'arrivée ; et la journée du jour, pour le texte de la carte.
    # Revue produit P1-10 : la carte dit où en est la journée (« 3 h 30
    # saisies sur 8 h »), et non « renseignée » dès la première ligne.
    dailylog_minutes, dailylog_objectif = 0, None
    if role == "client":
        dailylog_jours_manques, dailylog_aujourdhui = [], None
    else:
        reel = dailylog_repo.aujourdhui_reel_pour(g.user)
        if aujourdhui_local > reel:
            # Lot 24 (HD-10) : date simulée future — les oublis se comptent
            # au jour et à l'heure RÉELS (le jour réel avant 16 h n'en est pas un).
            dailylog_jours_manques = dailylog_repo.jours_manques_recents(
                g.user, aujourdhui=reel, maintenant=horloge.maintenant_reel())
        else:
            dailylog_jours_manques = dailylog_repo.jours_manques_recents(g.user, aujourdhui=aujourdhui_local)
        dailylog_aujourdhui = dailylog_repo.jour_renseigne(user_id, aujourdhui_local)
        if dailylog_aujourdhui:
            dailylog_minutes = sum(dailylog_repo.heures_en_minutes(e["heures"])
                                   for e in dailylog_repo.list_entrees_jour(user_id, aujourdhui_local))
            dailylog_objectif = dailylog_repo.get_objectif(user_id)

    # Fenêtre "+ Nouveau post" de l'accueil (audit n°2) : seulement les
    # projets actifs (pas ceux terminés/abandonnés), la liste des personnes
    # à affecter/taguer (elle n'était pas transmise : listes vides), et
    # l'onglet ouvert par défaut adapté — "Tâche" seulement pour qui gère au
    # moins un projet (sinon le formulaire était refusé à l'envoi).
    #
    # Sélecteur de projet (retour Fadhel, 2026-09-29, N2/N6) : seulement MES
    # projets (chef, co-chef, intervenant) en cours ou bloqués, triés par
    # MA dernière action — le premier, présélectionné, est donc celui sur
    # lequel j'ai travaillé le plus récemment (avant : l'échéance la plus
    # proche). La carte "Mes projets" en affiche les 5 premiers.
    if role == "client":
        # Jamais rattaché à un projet : ses projets sont ceux de son équipe.
        projets_recents = [
            {**p, "mon_role": None}
            for p in projets.list_projets(user_id=user_id, etats=["en_cours", "bloque"], limit=500)
        ]
    else:
        projets_recents = projets.list_mes_projets_recents(user_id, limit=500)
    projets_postables = [p for p in projets_recents if p["etat"] in ("en_cours", "bloque")]
    mes_projets_recents = projets_recents[:5]
    lot14 = tableaux.contexte_page(g.user, aujourdhui_local, mes_projets_recents)
    # Limité à 5 (retour Fadhel, 2026-09-28) : pour ne pas encombrer la colonne.
    # Chef, co-chef, Admin : « Tâches de mes projets » (lot14["tdp"]).
    mes_taches = [] if role == "client" or lot14["tdp"] else taches.list_mes_taches(user_id, limit=5)
    # Onglet ouvert par défaut : "Tâche" si je gère le projet présélectionné
    # (post-dialog.js masque ensuite l'onglet selon le projet choisi).
    gere_un_projet = bool(projets_postables) and projets_postables[0]["mon_role"] in ("chef_de_projet", "co_chef")
    if gere_un_projet:
        intent = "tache"
    elif projets_postables:
        intent = "requete"
    else:
        intent = "information"  # Information d'équipe, sans projet

    preferences = utilisateurs.get_preferences(user_id)
    if role == "client" and "accueil_deadlines" not in preferences.get("choisies", ()):
        # Le client « commence » par ses deadlines : dépliées tant qu'il n'a
        # pas choisi de les replier (lot 18).
        preferences = {**preferences, "accueil_deadlines": True}
    return render_template(
        "accueil.html",
        preferences=preferences,
        deadlines_resume=deadlines_resume,
        nb_projets_ouverts=len(projets_postables),
        mes_projets=mes_projets_recents,
        projets_postables=projets_postables,
        voient_par_projet=projets.ids_voient_projets(projets_postables),
        intent_par_defaut=intent,
        # "+ Nouveau post" : un projet où publier, ou une Information
        # d'équipe (pas pour un Client, ni sans équipe) — voir post_dialog.html.
        peut_publier=bool(projets_postables) or (role != "client" and bool(g.user.get("equipe_code"))) or role == "admin",
        utilisateurs_actifs=utilisateurs.list_actifs(),
        collaborateurs_recents=utilisateurs.list_collaborateurs_recents(user_id),
        deadlines=deadlines,
        deadlines_gantt=deadlines_gantt,
        mes_taches=mes_taches,
        taches_bloquees=taches_bloquees,
        bloquees_chef=role == "admin",
        **fil,
        dailylog_jours_manques=dailylog_jours_manques,
        dailylog_aujourdhui=dailylog_aujourdhui,
        # Lot 23 (demande du gérant) : jour ouvré pas encore rempli → carte en
        # rouge. Lot 24 (HD-11, HD-12) : jamais le week-end ni avant l'arrivée.
        dailylog_jour_ouvre=(aujourdhui_local.weekday() < 5
                             and aujourdhui_local >= (dailylog_repo.debut_daily_log(g.user) or aujourdhui_local)),
        dailylog_week_end=aujourdhui_local.weekday() >= 5,
        dailylog_minutes=dailylog_minutes,
        dailylog_objectif=dailylog_objectif,
        aujourdhui=aujourdhui_local,
        **lot14,
    )


def resume_echeances(echeances: list[dict], aujourdhui) -> dict:
    """Ligne repliée « Deadlines » de l'accueil (lot 15) : en retard, dans
    les 14 jours, et la prochaine échéance (aujourd'hui ou après)."""
    import datetime

    fin = aujourdhui + datetime.timedelta(days=14)
    retard = [t for t in echeances if t["date_echeance"] < aujourdhui]
    a_venir = [t for t in echeances if aujourdhui <= t["date_echeance"] < fin]
    return {"retard": len(retard), "a_venir": len(a_venir),
            "prochaine": a_venir[0]["date_echeance"] if a_venir else None}


@bp.route("/preferences", methods=["POST"])
@login_required
def preference():
    """Réglage d'affichage du compte (lot 15) : `cle` parmi
    utilisateurs.PREFERENCES, `valeur` 1/0. Réponse vide (204)."""
    cle = request.form.get("cle", "")
    permises = utilisateurs.PREFERENCES_PAR_ROLE.get(g.user["role"], set(utilisateurs.PREFERENCES))
    if cle not in utilisateurs.PREFERENCES or cle not in permises:
        return {"erreur": "invalide", "message": "Réglage inconnu."}, 400
    utilisateurs.set_preference(g.user["id"], cle, request.form.get("valeur") == "1")
    return "", 204


def _accueil_rh(user_id: int):
    """Accueil du RH (lot 7) : pas de projets, de tâches, d'échéances ni de
    Daily log — le fil de ses Informations d'équipe, et de quoi en publier
    (à n'importe quelle équipe)."""
    return render_template(
        "accueil.html",
        sans_projets=True, preferences=utilisateurs.get_preferences(user_id),
        mes_projets=[], projets_postables=[], intent_par_defaut="information", peut_publier=True,
        utilisateurs_actifs=utilisateurs.list_actifs(),
        collaborateurs_recents=utilisateurs.list_collaborateurs_recents(user_id),
        deadlines=[], deadlines_gantt=None, mes_taches=[],
        **contexte_fil_accueil(user_id),
        dailylog_jours_manques=[], dailylog_aujourdhui=None,
    )


@bp.route("/recherche/api")
@login_required
def recherche_api():
    """Petite API JSON interne pour la recherche de la topbar (voir
    base.html) — projets ET personnes (Lot 5, retour Fadhel, 2026-09-28 :
    la recherche de personnes était différée jusqu'ici faute de page de
    profil, voir utilisateurs.profil_personne, qui vient de la combler).

    Lot 11 : sans accents ni casse (« residence », « Fadhel Chem »), tâches
    comprises (titre, lien vers leur projet), comptes désactivés trouvés et
    signalés comme tels ; sous-titre pour distinguer projets, tâches et
    personnes homonymes. Lot 11 b : le lien d'une tâche ouvre sa fenêtre
    sur la fiche projet (?tache=<id>)."""
    from ..utils import projet_etat_style, tache_etat_style

    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return {"resultats": []}
    projets_trouves = projets.search(g.user["id"], q, limit=6)
    # Comptes désactivés : jamais pour un Client (extérieur à l'entreprise).
    personnes_trouvees = utilisateurs.search(q, limit=6, inclure_inactifs=g.user["role"] != "client")
    # Le RH ne voit aucun projet, donc aucune tâche (v_projet_visibilite).
    taches_trouvees = taches.search(g.user["id"], q, limit=6)
    resultats = [
        {"label": f"{p['code']}_{p['nom']}",
         "sous_titre": f"Projet · {projet_etat_style(p.get('etat'))['label']}" if p.get("etat") else "Projet",
         "url": url_for("projets.detail", projet_id=p["id"])}
        for p in projets_trouves
    ] + [
        {"label": t["titre"],
         "sous_titre": f"Tâche {tache_etat_style(t['etat'])['libelle'].lower()} · {t['projet_code']}_{t['projet_nom']}",
         # Lot 11 b : la fiche ouvre la fenêtre de la tâche (tache-dialog.js).
         "url": url_for("projets.detail", projet_id=t["projet_id"], tache=t["id"])}
        for t in taches_trouvees
    ] + [
        {"label": f"{u['prenom']} {u['nom']}" + ("" if u.get("actif", True) else " (inactif)"),
         "sous_titre": " · ".join(x for x in (u.get("poste"), None if u.get("actif", True) else "compte désactivé") if x)
                       or None,
         "url": url_for("utilisateurs.profil_personne", user_id=u["id"])}
        for u in personnes_trouvees
    ]
    return {"resultats": resultats}

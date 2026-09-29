"""Petits helpers d'affichage partagés par les templates (avatars, pills),
plus quelques fonctions utilitaires pures (voir is_safe_next ci-dessous).

Rien ici ne touche à la base de données — uniquement de la présentation
et de la logique de validation, pour éviter de dupliquer ces règles dans
chaque template Jinja2 ou chaque route."""
import datetime
from urllib.parse import urlparse

from .storage import is_image_filename


# Schémas autorisés pour le champ "lien" du composeur de post (panneau
# Requête) — voir is_lien_valide() ci-dessous.
LIENS_SCHEMES_VALIDES = ("http://", "https://", "file:", "smb:")


def is_lien_valide(lien: str | None) -> bool:
    """Vrai si `lien` (champ optionnel du composeur "Nouveau post", panneau
    Requête — voir routes/posts.py:creer) utilise un schéma autorisé.

    PROMPT_CORRECTIONS.md P0 #4 : post_card.html rend ce lien tel quel
    dans un `href="{{ post.lien }}"` — l'échappement automatique de Jinja2
    protège le TEXTE affiché (contre l'injection de balises), mais
    n'empêche absolument pas un schéma "javascript:..." de s'exécuter au
    clic. On n'autorise donc que http(s), les URI file:/smb: (partages
    réseau) et les chemins UNC Windows ("\\\\serveur\\partage\\...", déjà
    utilisés dans l'appli pour pointer vers les dossiers projet sur le
    NAS). Utilisée à la fois à la création du post (on rejette le lien
    plutôt que de l'enregistrer) et au rendu (post_card.html revérifie
    avant d'afficher un <a href=...>, au cas où une donnée invalide
    existerait déjà en base — défense en profondeur)."""
    if not lien:
        return False
    lien = lien.strip()
    if lien.startswith("\\\\"):
        return True
    return lien.lower().startswith(LIENS_SCHEMES_VALIDES)


def is_safe_next(url: str | None) -> bool:
    """Vrai si `url` est un chemin interne sûr pour une redirection
    post-action (paramètre ?next= de la connexion, formulaires "next" de
    routes/posts.py et routes/fichiers.py) — PROMPT_CORRECTIONS.md P0 #5.

    Le contrôle `url.startswith("/")` utilisé auparavant accepte encore
    "//evil.tld" et "/\\evil.tld" : la plupart des navigateurs traitent
    ces deux formes comme des URLs ABSOLUES (respectivement "URL relative
    au protocole" et un antislash interprété comme un slash), donc une
    redirection a bien lieu hors du site — un lien "connexion" envoyé par
    un attaquant avec ?next=//evil.tld renverrait la victime, une fois
    connectée, vers son site. On exige donc un chemin qui commence par un
    seul "/" (jamais "//" ni "/\\") ET dont l'analyse par urlparse ne
    révèle ni schéma ni netloc (protège aussi contre des variantes moins
    connues, ex. "/\t/evil.tld" selon le navigateur)."""
    if not url or not url.startswith("/") or url.startswith("//") or url.startswith("/\\"):
        return False
    parsed = urlparse(url)
    return not parsed.scheme and not parsed.netloc

def redirect_vers_next(default_endpoint: str = "main.accueil"):
    """Redirige vers le champ caché "next" du formulaire s'il désigne une
    page interne sûre (voir is_safe_next), sinon vers `default_endpoint`.
    Factorisé ici (audit n°2) : la même fonction était copiée dans
    routes/posts.py et routes/fichiers.py."""
    from flask import redirect, request, url_for

    next_url = request.form.get("next")
    if is_safe_next(next_url):
        return redirect(next_url)
    return redirect(url_for(default_endpoint))


# Palette reprise telle quelle des maquettes (Main.dc.html / Projet.dc.html).
# Teintes assombries (audit n°2) pour que les initiales blanches restent
# lisibles (contraste ≥ 4,5:1, contre 3,0 à 4,0 auparavant).
_AVATAR_PALETTE = ["#4a7c59", "#b8520f", "#2f65b8", "#5f52d1", "#c0401d", "#1f7a55"]

_TACHE_ETAT_STYLE = {
    "en_cours": {"bg": "#eaf1fd", "fg": "#3b7de0", "label": "En cours"},
    "bloque": {"bg": "#fdeae4", "fg": "#e3512c", "label": "Bloqué"},
    "verifie": {"bg": "#efecfd", "fg": "#7c6ff0", "label": "Vérifié"},
    "termine": {"bg": "#eaf3ee", "fg": "#4a7c59", "label": "Terminé"},
    "arret": {"bg": "#f2f4f0", "fg": "#55605a", "label": "Arrêt"},
    "abandonne": {"bg": "#f2f4f0", "fg": "#6c766f", "label": "Abandonné"},
}

_PROJET_ETAT_STYLE = {
    "en_cours": {"dot": "#2fa876", "bg": "#eaf3ee", "fg": "#4a7c59", "label": "En cours"},
    "bloque": {"dot": "#e3512c", "bg": "#fdeae4", "fg": "#e3512c", "label": "Bloqué"},
    "termine": {"dot": "#c7cdc4", "bg": "#f2f4f0", "fg": "#55605a", "label": "Terminé"},
    "abandonne": {"dot": "#c7cdc4", "bg": "#f2f4f0", "fg": "#6c766f", "label": "Abandonné"},
}

_POST_TYPE_STYLE = {
    "envoi": {"bg": "#eaf3ee", "fg": "#4a7c59", "label": "Envoi"},
    "reponse": {"bg": "#eaf1fd", "fg": "#3b7de0", "label": "Réponse"},
    "question": {"bg": "#f2f4f0", "fg": "#55605a", "label": "Question"},
    "requete": {"bg": "#fdeee4", "fg": "#a3480d", "label": "Requête"},
    # Teinte propre (2026-09-29) : Information est publiable depuis la
    # migration 0009 et ne doit plus se confondre avec "Question".
    "information": {"bg": "#efecfd", "fg": "#5f52d1", "label": "Information"},
}

# Pill "Tâche" utilisée pour les posts système de création de tâche
# (voir partials/post_card.html) ; ne correspond à aucun type_code,
# c'est une présentation dédiée aux événements liés à une tâche.
POST_TACHE_PILL = {"bg": "#efecfd", "fg": "#7c6ff0", "label": "Tâche"}

# Couleurs/labels de rôle (page Utilisateurs), reprises de Utilisateurs.dc.html.
_ROLE_STYLE = {
    "admin": {"bg": "#efecfd", "fg": "#7c6ff0", "label": "Admin"},
    "chef_de_projet": {"bg": "#eaf1fd", "fg": "#3b7de0", "label": "Chef de projet"},
    "intervenant": {"bg": "#f2f4f0", "fg": "#55605a", "label": "Intervenant"},
    "rh": {"bg": "#f2f4f0", "fg": "#6c766f", "label": "RH"},
    "client": {"bg": "#f2f4f0", "fg": "#6c766f", "label": "Client"},
}

# Équipes de référence (table `equipe`, schema.sql) — codes stockés en
# base, non requêtés ici (liste fixe et stable, comme ailleurs dans
# l'appli, voir partials/post_dialog.html). ISBG renommé en URBS + ajout d'IPCO
# (retour Fadhel, 2026-09-20).
EQUIPE_CHOICES = [
    ("MIDGARD", "Midgard"),
    ("URBS", "URBS"),
    ("SS", "SS"),
    ("Q", "Q"),
    ("IPCO", "IPCO"),
]


def role_style(role: str) -> dict:
    return _ROLE_STYLE.get(role, {"bg": "#f2f4f0", "fg": "#55605a", "label": role or ""})


def equipe_libelle(code: str) -> str:
    for c, lib in EQUIPE_CHOICES:
        if c == code:
            return lib
    return code or "—"


def initials(prenom: str, nom: str) -> str:
    p = (prenom or "").strip()
    n = (nom or "").strip()
    return f"{p[:1]}{n[:1]}".upper() or "?"


def avatar_color(user_id: int) -> str:
    if not user_id:
        return _AVATAR_PALETTE[0]
    return _AVATAR_PALETTE[user_id % len(_AVATAR_PALETTE)]


def tache_etat_style(etat: str) -> dict:
    return _TACHE_ETAT_STYLE.get(etat, {"bg": "#f2f4f0", "fg": "#55605a", "label": etat or ""})


def projet_etat_style(etat: str) -> dict:
    return _PROJET_ETAT_STYLE.get(etat, {"dot": "#c7cdc4", "bg": "#f2f4f0", "fg": "#55605a", "label": etat or ""})


def post_type_style(type_code: str) -> dict:
    return _POST_TYPE_STYLE.get(type_code, {"bg": "#f2f4f0", "fg": "#55605a", "label": type_code or ""})


# Deux catégories de notification (voir spec : "un seul mécanisme... avec
# une différenciation par catégorie : Projet/Travail vs Info/RH").
_NOTIF_CATEGORIE_STYLE = {
    "projet": {"bg": "#eaf1fd", "fg": "#3b7de0", "label": "Projet"},
    "rh_info": {"bg": "#f2f4f0", "fg": "#55605a", "label": "RH & Infos"},
}


def notif_categorie_style(categorie: str) -> dict:
    return _NOTIF_CATEGORIE_STYLE.get(categorie, {"bg": "#f2f4f0", "fg": "#55605a", "label": categorie or ""})


def il_y_a(dt) -> str:
    """Formatage relatif façon réseau social ("il y a 1 h", "hier"),
    comme dans les maquettes."""
    import datetime

    if dt is None:
        return ""
    now = datetime.datetime.now(dt.tzinfo) if dt.tzinfo else datetime.datetime.now()
    delta = now - dt
    secondes = delta.total_seconds()

    if secondes < 60:
        return "à l'instant"
    if secondes < 3600:
        return f"il y a {int(secondes // 60)} min"
    if secondes < 24 * 3600:
        return f"il y a {int(secondes // 3600)} h"
    if secondes < 2 * 24 * 3600:
        return "hier"
    if secondes < 7 * 24 * 3600:
        return f"il y a {int(secondes // (24 * 3600))} j"
    return dt.strftime("%d/%m/%Y")


_JOURS_LETTRE = ["L", "M", "M", "J", "V", "S", "D"]
_MOIS_ABBR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
_JOURS_COMPLETS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
_MOIS_COMPLETS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def date_fr(d) -> str:
    """Date complète en français ("Mardi 16 septembre 2026"), sans dépendre
    du paramètre régional du système (`strftime('%A')` ne donnerait pas du
    français sur un serveur sans la locale fr_FR installée)."""
    if d is None:
        return ""
    return f"{_JOURS_COMPLETS[d.weekday()]} {d.day} {_MOIS_COMPLETS[d.month - 1]} {d.year}"


def date_courte(d, avec_annee: bool = False) -> str:
    """Date courte en français ("20 sept.", "20 sept. 2026") — remplace
    strftime('%d %b'), qui donnait des mois en anglais ("20 Sep") sur un
    serveur sans locale française (audit n°2)."""
    if d is None:
        return ""
    texte = f"{d.day:02d} {_MOIS_ABBR[d.month - 1]}"
    return f"{texte} {d.year}" if avec_annee else texte


def build_gantt(taches: list[dict], today, window_days: int = 21) -> dict:
    """Construit les données d'affichage de la vue Deadlines (calendrier
    horizontal à la Deadlines.dc.html) à partir d'une liste de tâches ayant
    une date_echeance. Pure logique de présentation — aucun accès base de
    données ici, donc testable directement (voir tests/test_utils.py).

    Chaque barre représente le temps restant entre aujourd'hui et
    l'échéance (comme dans la maquette) : rouge si échéance imminente/
    dépassée, orange si dans la semaine, vert au-delà.
    """
    import datetime

    days = []
    for i in range(window_days):
        d = today + datetime.timedelta(days=i)
        label = str(d.day) if d.day != 1 else f"{d.day} {_MOIS_ABBR[d.month - 1]}"
        days.append({
            "date": d,
            "label": label,
            "lettre": _JOURS_LETTRE[d.weekday()],
            "est_weekend": d.weekday() >= 5,
        })

    rows = []
    for t in taches:
        echeance = t.get("date_echeance")
        if echeance is None:
            continue
        offset = (echeance - today).days
        if offset < 0:
            span, couleur, label_barre = 1, "#e3512c", "◀ en retard"
        else:
            span = min(offset + 1, window_days)
            if offset <= 1:
                couleur = "#e3512c"
            elif offset <= 6:
                couleur = "#ea6c1a"
            else:
                couleur = "#4a7c59"
            label_barre = echeance.strftime("%d/%m")
        rows.append({**t, "span": span, "couleur": couleur, "label_barre": label_barre})

    return {"days": days, "rows": rows, "window_days": window_days}


def personnes_recentes_d_abord(personnes: list[dict], recents_ids: list[int] | None) -> list[dict]:
    """Liste des personnes pour les sélecteurs du composeur (retour Fadhel,
    2026-09-29, N4) : les collaborateurs récents d'abord, dans leur ordre,
    marqués `recent` (chip-select.js n'affiche qu'eux tant qu'on ne
    cherche pas), puis tous les autres."""
    recents_ids = list(recents_ids or [])
    par_id = {p["id"]: p for p in personnes}
    devant = [{**par_id[i], "recent": True} for i in recents_ids if i in par_id]
    deja = {p["id"] for p in devant}
    return devant + [{**p, "recent": False} for p in personnes if p["id"] not in deja]


def texte_avec_mentions(contenu: str | None, mentions: list[dict] | None):
    """Texte d'un commentaire, échappé, où chaque "@Prénom Nom" d'une
    personne réellement taguée (post_commentaire_mention, migration 0009)
    est mis en évidence — le tag s'écrit directement dans le texte (retour
    Fadhel, 2026-09-29). Les noms les plus longs d'abord, pour qu'un
    "@Ali Ben Salah" ne soit pas coupé par un "@Ali Ben"."""
    from markupsafe import Markup, escape

    html = str(escape(contenu or ""))
    noms = sorted(
        {f"@{m.get('prenom', '')} {m.get('nom', '')}".strip() for m in (mentions or [])},
        key=len, reverse=True,
    )
    for i, nom in enumerate(noms):
        html = html.replace(str(escape(nom)), f"\x00{i}\x00")
    for i, nom in enumerate(noms):
        html = html.replace(f"\x00{i}\x00", f'<span class="post-comment-mention">{escape(nom)}</span>')
    return Markup(html)


def register(app):
    """Rend ces helpers disponibles directement dans les templates Jinja2."""
    app.jinja_env.globals.update(
        initials=initials,
        avatar_color=avatar_color,
        tache_etat_style=tache_etat_style,
        projet_etat_style=projet_etat_style,
        post_type_style=post_type_style,
        post_tache_pill=POST_TACHE_PILL,
        role_style=role_style,
        equipe_libelle=equipe_libelle,
        equipe_choices=EQUIPE_CHOICES,
        date_fr=date_fr,
        notif_categorie_style=notif_categorie_style,
        is_lien_valide=is_lien_valide,
        is_image_filename=is_image_filename,
        personnes_recentes_d_abord=personnes_recentes_d_abord,
        texte_avec_mentions=texte_avec_mentions,
        zip=zip,
        # Date du jour côté serveur (retour Fadhel, 2026-09-28) — appelée
        # dans les templates comme today() pour préremplir l'échéance de
        # "nouveau poste" ; une fonction (pas une valeur figée au démarrage
        # de l'appli) pour rester juste après minuit.
        today=datetime.date.today,
    )
    app.jinja_env.filters["il_y_a"] = il_y_a
    app.jinja_env.filters["date_courte"] = date_courte

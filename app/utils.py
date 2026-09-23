"""Petits helpers d'affichage partagés par les templates (avatars, pills).

Rien ici ne touche à la base de données — uniquement de la présentation,
pour éviter de dupliquer ces règles dans chaque template Jinja2.
"""

# Palette reprise telle quelle des maquettes (Main.dc.html / Projet.dc.html).
_AVATAR_PALETTE = ["#4a7c59", "#ea6c1a", "#3b7de0", "#7c6ff0", "#e3512c", "#2fa876"]

_TACHE_ETAT_STYLE = {
    "en_cours": {"bg": "#eaf1fd", "fg": "#3b7de0", "label": "En cours"},
    "bloque": {"bg": "#fdeae4", "fg": "#e3512c", "label": "Bloqué"},
    "verifie": {"bg": "#efecfd", "fg": "#7c6ff0", "label": "Vérifié"},
    "termine": {"bg": "#eaf3ee", "fg": "#4a7c59", "label": "Terminé"},
    "arret": {"bg": "#f2f4f0", "fg": "#55605a", "label": "Arrêt"},
    "abandonne": {"bg": "#f2f4f0", "fg": "#9aa39c", "label": "Abandonné"},
}

_PROJET_ETAT_STYLE = {
    "en_cours": {"dot": "#2fa876", "bg": "#eaf3ee", "fg": "#4a7c59", "label": "En cours"},
    "bloque": {"dot": "#e3512c", "bg": "#fdeae4", "fg": "#e3512c", "label": "Bloqué"},
    "termine": {"dot": "#c7cdc4", "bg": "#f2f4f0", "fg": "#55605a", "label": "Terminé"},
    "abandonne": {"dot": "#c7cdc4", "bg": "#f2f4f0", "fg": "#9aa39c", "label": "Abandonné"},
}

_POST_TYPE_STYLE = {
    "envoi": {"bg": "#eaf3ee", "fg": "#4a7c59", "label": "Envoi"},
    "reponse": {"bg": "#eaf1fd", "fg": "#3b7de0", "label": "Réponse"},
    "question": {"bg": "#f2f4f0", "fg": "#55605a", "label": "Question"},
    "requete": {"bg": "#fdeee4", "fg": "#ea6c1a", "label": "Requête"},
    "information": {"bg": "#f2f4f0", "fg": "#55605a", "label": "Information"},
}

# Pill "Tâche" utilisée pour les posts système de création de tâche
# (voir posts.py — POST_TACHE_PILL) ; ne correspond à aucun type_code,
# c'est une présentation dédiée aux événements liés à une tâche.
POST_TACHE_PILL = {"bg": "#efecfd", "fg": "#7c6ff0", "label": "Tâche"}

# Couleurs/labels de rôle (page Utilisateurs), reprises de Utilisateurs.dc.html
# — RH garde une pill grisée "réservée" tant que le rôle n'est pas actif à
# l'étape 1 (voir spec).
_ROLE_STYLE = {
    "admin": {"bg": "#efecfd", "fg": "#7c6ff0", "label": "Admin"},
    "chef_de_projet": {"bg": "#eaf1fd", "fg": "#3b7de0", "label": "Chef de projet"},
    "intervenant": {"bg": "#f2f4f0", "fg": "#55605a", "label": "Intervenant"},
    "rh": {"bg": "#f2f4f0", "fg": "#9aa39c", "label": "RH"},
    "client": {"bg": "#f2f4f0", "fg": "#9aa39c", "label": "Client"},
}

# Équipes de référence (table `equipe`, schema.sql) — codes stockés en
# base, non requêtés ici (liste fixe et stable, comme ailleurs dans
# l'appli, voir nouveau_post.html). ISBG renommé en URBS + ajout d'IPCO
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
    )
    app.jinja_env.filters["il_y_a"] = il_y_a

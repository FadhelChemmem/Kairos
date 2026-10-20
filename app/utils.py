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
    if any(ord(c) < 32 or ord(c) == 127 for c in lien):
        return False  # lot 18 : ni saut de ligne ni caractère de contrôle
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
    # Lot 18 : ni caractère de contrôle (un saut de ligne faisait lever une
    # ValueError à Werkzeug : erreur 500 après connexion) ni « \\ ».
    if "\\" in url or any(ord(c) < 32 or ord(c) == 127 for c in url):
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

# Lot 13 (audit UX §4.4, M3) : les pastilles portent une CLASSE de teinte
# (pill-bleu, pill-rouge, pill-vert, pill-violet, pill-orange, pill-neutre)
# au lieu de couleurs en dur : fond et texte viennent des jetons --etat-*
# de app.css, thémés en clair et en sombre (≥ 4,5:1 dans les deux thèmes,
# tests/test_lot13_front.py). Gabarits : class="pill {{ st.classe }}".
# « libelle » : état de TÂCHE accordé au féminin pour l'affichage (« Tâche
# bloquée ») ; « label » reste inchangé, il sert aussi au texte des posts
# automatiques enregistrés en base (repositories/taches.py).
_TACHE_ETAT_STYLE = {
    "en_cours": {"classe": "pill-bleu", "label": "En cours", "libelle": "En cours"},
    "bloque": {"classe": "pill-rouge", "label": "Bloqué", "libelle": "Bloquée"},
    "verifie": {"classe": "pill-violet", "label": "Vérifié", "libelle": "Vérifiée"},
    "termine": {"classe": "pill-vert", "label": "Terminé", "libelle": "Terminée"},
    "arret": {"classe": "pill-neutre", "label": "Arrêt", "libelle": "Arrêtée"},
    "abandonne": {"classe": "pill-neutre", "label": "Abandonné", "libelle": "Abandonnée"},
}

_PROJET_ETAT_STYLE = {
    "en_cours": {"dot": "#2fa876", "classe": "pill-vert", "label": "En cours"},
    "bloque": {"dot": "#e3512c", "classe": "pill-rouge", "label": "Bloqué"},
    "termine": {"dot": "#c7cdc4", "classe": "pill-neutre", "label": "Terminé"},
    "abandonne": {"dot": "#c7cdc4", "classe": "pill-neutre", "label": "Abandonné"},
}

_POST_TYPE_STYLE = {
    "envoi": {"classe": "pill-vert", "label": "Envoi"},
    "reponse": {"classe": "pill-bleu", "label": "Réponse"},
    "question": {"classe": "pill-neutre", "label": "Question"},
    "requete": {"classe": "pill-orange", "label": "Requête"},
    # Teinte propre (2026-09-29) : Information est publiable depuis la
    # migration 0009 et ne doit plus se confondre avec "Question".
    "information": {"classe": "pill-violet", "label": "Information"},
}

# Pill "Tâche" utilisée pour les posts système de création de tâche
# (voir partials/post_card.html) ; ne correspond à aucun type_code,
# c'est une présentation dédiée aux événements liés à une tâche.
POST_TACHE_PILL = {"classe": "pill-violet", "label": "Tâche"}

# Couleurs/labels de rôle (page Utilisateurs), reprises de Utilisateurs.dc.html.
_ROLE_STYLE = {
    "admin": {"classe": "pill-violet", "label": "Administrateur"},
    "chef_de_projet": {"classe": "pill-bleu", "label": "Chef de projet"},
    "intervenant": {"classe": "pill-neutre", "label": "Intervenant"},
    "rh": {"classe": "pill-neutre", "label": "RH"},
    "client": {"classe": "pill-neutre", "label": "Client"},
}

# Équipes de référence (table `equipe`, schema.sql) — codes stockés en
# base, non requêtés ici (liste fixe et stable, comme ailleurs dans
# l'appli, voir partials/post_dialog.html). ISBG renommé en URBS (2026-09-20) ;
# IPCO retirée et VD ajoutée (lot 18, migration 0023).
EQUIPE_CHOICES = [
    ("MIDGARD", "Midgard"),
    ("URBS", "URBS"),
    ("VD", "VD"),
    ("SS", "SS"),
    ("Q", "Q"),
]


def role_style(role: str) -> dict:
    return _ROLE_STYLE.get(role, {"classe": "pill-neutre", "label": role or ""})


def equipe_libelle(code: str) -> str:
    for c, lib in EQUIPE_CHOICES:
        if c == code:
            return lib
    return code or "—"


def initials(prenom: str, nom: str) -> str:
    p = (prenom or "").strip()
    n = (nom or "").strip()
    return f"{p[:1]}{n[:1]}".upper() or "?"


def avatar_version(avatar_chemin: str | None) -> str:
    """Empreinte courte du fichier de photo (lot 11) : mise dans l'URL de
    l'avatar (« ?v=… »), elle change à chaque nouvelle photo (nouveau
    chemin) — la réponse peut alors rester une heure dans le cache PRIVÉ du
    navigateur (voir fichiers.avatar) sans jamais montrer l'ancienne."""
    import hashlib

    return hashlib.sha256((avatar_chemin or "").encode("utf-8")).hexdigest()[:12]


def avatar_url(user_id: int, avatar_chemin: str | None) -> str:
    from flask import url_for

    return url_for("fichiers.avatar", user_id=user_id, v=avatar_version(avatar_chemin))


def avatar_color(user_id: int) -> str:
    if not user_id:
        return _AVATAR_PALETTE[0]
    return _AVATAR_PALETTE[user_id % len(_AVATAR_PALETTE)]


def tache_etat_style(etat: str) -> dict:
    return _TACHE_ETAT_STYLE.get(etat, {"classe": "pill-neutre", "label": etat or "", "libelle": etat or ""})


def projet_etat_style(etat: str) -> dict:
    return _PROJET_ETAT_STYLE.get(etat, {"dot": "#c7cdc4", "classe": "pill-neutre", "label": etat or ""})


def post_type_style(type_code: str) -> dict:
    return _POST_TYPE_STYLE.get(type_code, {"classe": "pill-neutre", "label": type_code or ""})


# Deux catégories de notification (voir spec : "un seul mécanisme... avec
# une différenciation par catégorie : Projet/Travail vs Info/RH").
_NOTIF_CATEGORIE_STYLE = {
    "projet": {"classe": "pill-bleu", "label": "Projet"},
    "rh_info": {"classe": "pill-neutre", "label": "RH & Infos"},
}


def notif_categorie_style(categorie: str) -> dict:
    return _NOTIF_CATEGORIE_STYLE.get(categorie, {"classe": "pill-neutre", "label": categorie or ""})


def il_y_a(dt) -> str:
    """Formatage relatif façon réseau social ("il y a 1 h", "hier"),
    comme dans les maquettes.

    Lot 20 (décision du gérant) : sous date simulée (mode test), les
    horodatages sont SIMULÉS eux aussi (fn_maintenant) ; « il y a … » se lit
    alors par rapport à l'instant simulé. Un horodatage dans le futur
    (postérieur à l'instant simulé, ou écrit sous une date simulée future
    avant le lot 21) s'affiche en date absolue (« 9 oct. à 13 h 08 »)."""
    from . import horloge

    if dt is None:
        return ""
    maintenant = horloge.maintenant()
    # Lot 21 (test Chrome V4) : un horodatage dans le futur (écrit sous une
    # date simulée, ou postérieur à l'instant simulé) s'affiche toujours en
    # date absolue, jamais « à l'instant ».
    if dt.tzinfo and dt > maintenant + datetime.timedelta(minutes=1):
        local = dt.astimezone(maintenant.tzinfo)
        jour = date_courte(local.date(), avec_annee=local.year != maintenant.year)
        return f"{jour} à {local.hour}\u00a0h\u00a0{local.minute:02d}"
    if horloge.date_simulee() is not None:
        now = maintenant if dt.tzinfo else maintenant.replace(tzinfo=None)
    else:
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
    # Au-delà d'une semaine : « le 5 oct. » (« le 5 oct. 2025 » une autre
    # année) — même format que le reste de l'appli (lot 10, audit front §7).
    return "le " + date_courte(dt, avec_annee=dt.year != now.year)


_JOURS_LETTRE = ["L", "M", "M", "J", "V", "S", "D"]
_MOIS_ABBR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
_JOURS_COMPLETS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
_MOIS_COMPLETS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
# Noms publics (Daily log v9 : listes transmises au JS, qui formate les
# dates côté client sans dépendre de la locale du navigateur).
MOIS_COMPLETS = _MOIS_COMPLETS
MOIS_ABREGES = _MOIS_ABBR
JOURS_COMPLETS = _JOURS_COMPLETS
JOURS_ABREGES = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def date_fr(d) -> str:
    """Date complète en français ("Mardi 16 septembre 2026"), sans dépendre
    du paramètre régional du système (`strftime('%A')` ne donnerait pas du
    français sur un serveur sans la locale fr_FR installée)."""
    if d is None:
        return ""
    jour = "1er" if d.day == 1 else str(d.day)
    return f"{_JOURS_COMPLETS[d.weekday()]} {jour} {_MOIS_COMPLETS[d.month - 1]} {d.year}"


def date_longue(d) -> str:
    """« jeudi 15 octobre 2026 » (date_fr sans majuscule, au fil d'une
    phrase : bandeau de la date simulée, lot 12)."""
    texte = date_fr(d)
    return texte[:1].lower() + texte[1:]


def date_courte(d, avec_annee: bool | None = None) -> str:
    """Date courte en français ("20 sept.", "20 sept. 2026") — remplace
    strftime('%d %b'), qui donnait des mois en anglais ("20 Sep") sur un
    serveur sans locale française (audit n°2).

    Lot 11 : par défaut (`avec_annee=None`), l'année est écrite dès qu'elle
    n'est pas l'année en cours — « 17 nov. » pour 2022 faisait croire à une
    échéance à venir (liste des projets, Mes tâches, Deadlines, fiche
    projet). True / False forcent l'un ou l'autre."""
    if d is None:
        return ""
    if avec_annee is None:
        from .horloge import aujourdhui
        avec_annee = d.year != aujourdhui().year
    # « 5 oct. », « 1er juin » : jour sans zéro initial, « 1er » pour le
    # premier du mois (lot 10, audit front §7 — c'était « 05 oct. »).
    jour = "1er" if d.day == 1 else str(d.day)
    texte = f"{jour} {_MOIS_ABBR[d.month - 1]}"
    return f"{texte} {d.year}" if avec_annee else texte


RAPPEL_JOURS_DETAILLES = 5


def texte_rappel_daily_log(jours, aujourdhui) -> str:
    """Message du rappel Daily log (lot 11 b, demande du gérant : « Rappel
    DailyLog : vous n'avez pas rempli votre journée du 07/10/2026. » n'était
    pas clair) :
      « Daily log du mardi 7 octobre non rempli »
      « 3 jours de Daily log non remplis : lundi 5, mardi 6 et mercredi 7 octobre »
      « 10 jours de Daily log non remplis, du jeudi 24 septembre au mercredi 7 octobre »
    Le mois n'est écrit qu'à la fin de chaque série du même mois ; l'année
    seulement si ce n'est pas celle d'`aujourdhui` (fuseau de la personne).
    Au-delà de RAPPEL_JOURS_DETAILLES jours, seulement le premier et le
    dernier (après un rechargement Chronos, qui vide le Daily log, tout le
    monde a deux semaines à remplir)."""
    jours = sorted(set(jours))
    if len(jours) > RAPPEL_JOURS_DETAILLES:
        def complet(d):
            texte = f"{_JOURS_COMPLETS[d.weekday()].lower()} {'1er' if d.day == 1 else d.day} {_MOIS_COMPLETS[d.month - 1]}"
            return texte + (f" {d.year}" if d.year != aujourdhui.year else "")
        return f"{len(jours)} jours de Daily log non remplis, du {complet(jours[0])} au {complet(jours[-1])}"

    def libelle(i):
        d = jours[i]
        texte = f"{_JOURS_COMPLETS[d.weekday()].lower()} {'1er' if d.day == 1 else d.day}"
        suivant = jours[i + 1] if i + 1 < len(jours) else None
        if suivant is None or (suivant.year, suivant.month) != (d.year, d.month):
            texte += f" {_MOIS_COMPLETS[d.month - 1]}"
            if d.year != aujourdhui.year:
                texte += f" {d.year}"
        return texte

    morceaux = [libelle(i) for i in range(len(jours))]
    if len(morceaux) == 1:
        return f"Daily log du {morceaux[0]} non rempli"
    liste = ", ".join(morceaux[:-1]) + " et " + morceaux[-1]
    return f"{len(morceaux)} jours de Daily log non remplis\u00a0: {liste}"


def en_retard_de(echeance, aujourdhui) -> str:
    """« en retard de 3 j » (lot 11 : « ◀ en retard » seul ne disait ni
    l'échéance ni l'ampleur du retard) ; "" si l'échéance n'est pas passée."""
    if echeance is None or aujourdhui is None or echeance >= aujourdhui:
        return ""
    return f"en retard de {(aujourdhui - echeance).days} j"


def jours_blocage(bloque_le) -> int | None:
    """Jours depuis le début du blocage d'une tâche (lot 14, P0-1), au
    fuseau de la personne et à sa date du jour (simulée comprise) ; jamais
    négatif. None si la date est inconnue."""
    if bloque_le is None:
        return None
    from . import horloge

    maintenant = horloge.maintenant()
    jour = bloque_le.astimezone(maintenant.tzinfo).date() if getattr(bloque_le, "tzinfo", None) else bloque_le
    if hasattr(jour, "date"):
        jour = jour.date()
    return max(0, (maintenant.date() - jour).days)


def jour_local(instant):
    """Date d'un horodatage au fuseau de la personne connectée (Tunis à
    défaut) — lot 24 : dates de début, de blocage d'une tâche. Une date
    simple est rendue telle quelle ; None reste None."""
    import datetime as _dt

    if not isinstance(instant, _dt.date):
        return None
    if not isinstance(instant, _dt.datetime):
        return instant
    if instant.tzinfo is None:
        return instant.date()
    from . import horloge

    return instant.astimezone(horloge._zone(None)).date()


def depuis_blocage(bloque_le) -> str:
    """« depuis 3 j », « depuis aujourd’hui » ; "" si la date est inconnue."""
    jours = jours_blocage(bloque_le)
    if jours is None:
        return ""
    return "depuis aujourd’hui" if jours == 0 else f"depuis {jours}\u00a0j"


GANTT_COULEURS = {"urgent": "#c2401f", "semaine": "#a16207", "tard": "#4a7c59"}


def build_gantt(taches: list[dict], today, window_days: int = 21) -> dict:
    """Construit les données d'affichage de la vue Deadlines (calendrier
    horizontal à la Deadlines.dc.html) à partir d'une liste de tâches ayant
    une date_echeance. Pure logique de présentation — aucun accès base de
    données ici, donc testable directement (voir tests/test_utils.py).

    Chaque barre représente le temps restant entre aujourd'hui et
    l'échéance (comme dans la maquette) : rouge si échéance imminente/
    dépassée, orange si dans la semaine, vert au-delà.
    """
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
        # Teintes assombries (lot 10, audit front §3.6) : texte blanc sur la
        # barre à 5,19:1 et 4,94:1 (contre 3,83 et 3,15 avant).
        # Revue visuelle P1-6 : « cette semaine » en ambre (#a16207, ΔE 31,6
        # avec le rouge du retard, blanc dessus 4,92:1) ; les gabarits
        # passent par la classe g-bar-<niveau> (jetons --gantt-*).
        if offset < 0:
            span, niveau, label_barre = 1, "urgent", f"◀ {en_retard_de(echeance, today)}"
        else:
            span = min(offset + 1, window_days)
            if offset <= 1:
                niveau = "urgent"
            elif offset <= 6:
                niveau = "semaine"
            else:
                niveau = "tard"
            # « 7 oct. » comme partout ailleurs (c'était « 07/10 »).
            label_barre = date_courte(echeance)
        couleur = GANTT_COULEURS[niveau]
        rows.append({**t, "span": span, "couleur": couleur, "niveau": niveau, "label_barre": label_barre,
                     "en_retard": offset < 0, "retard": en_retard_de(echeance, today)})

    return {"days": days, "rows": rows, "window_days": window_days}


def jours_utiles_gantt(taches: list[dict], today, minimum: int = 14, maximum: int = 90) -> int:
    """Nombre de jours à afficher dans la vue Deadlines (retour Fadhel,
    2026-09-29 : « n'afficher la barre [de défilement] que si besoin, des
    tâches qui se terminent en dehors du champ visible ») : juste de quoi
    montrer l'échéance la plus lointaine, au moins `minimum` jours — les
    colonnes s'élargissent alors pour remplir la carte, et la barre de
    défilement n'apparaît que si elles deviendraient trop étroites."""
    derniers = [(t["date_echeance"] - today).days + 1 for t in taches if t.get("date_echeance")]
    return max(minimum, min(maximum, max(derniers, default=0)))


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


_URL_TEXTE = None


def avec_liens(contenu: str | None):
    """Texte d'un post ou d'un commentaire, échappé, où chaque adresse web
    (http:// ou https://) devient un lien cliquable, ouvert dans un nouvel
    onglet (lot 23, test Chrome). La ponctuation finale (point, virgule,
    parenthèse fermante sans ouvrante…) reste hors du lien."""
    import re

    from markupsafe import Markup, escape

    global _URL_TEXTE
    if _URL_TEXTE is None:
        _URL_TEXTE = re.compile(r"https?://[^\s<>\"'«»]+", re.IGNORECASE)
    texte = contenu or ""
    morceaux, pos = [], 0
    for m in _URL_TEXTE.finditer(texte):
        url = m.group(0)
        # Lot 24 (N-ES01) : épluchage linéaire — le solde des parenthèses
        # est calculé une fois puis tenu à jour (plus de count() par tour).
        fin = len(url)
        solde = url.count("(") - url.count(")")
        while fin:
            c = url[fin - 1]
            if c in ".,;:!?]}":
                fin -= 1
            elif c == ")" and solde < 0:
                fin -= 1
                solde += 1
            else:
                break
        url = url[:fin]
        if len(url) <= len("https://"):
            continue
        morceaux.append(escape(texte[pos:m.start()]))
        morceaux.append(Markup('<a href="{0}" class="lien-texte" target="_blank" rel="noopener noreferrer">{0}</a>')
                        .format(url))
        pos = m.start() + len(url)
    morceaux.append(escape(texte[pos:]))
    return Markup("").join(morceaux)


def texte_avec_mentions(contenu: str | None, mentions: list[dict] | None):
    """Texte d'un commentaire, échappé, où chaque "@Prénom Nom" d'une
    personne réellement taguée (post_commentaire_mention, migration 0009)
    est mis en évidence — le tag s'écrit directement dans le texte (retour
    Fadhel, 2026-09-29). Les noms les plus longs d'abord, pour qu'un
    "@Ali Ben Salah" ne soit pas coupé par un "@Ali Ben"."""
    import re

    from markupsafe import Markup, escape

    # Lot 23 : adresses web cliquables ; les mentions ne sont cherchées
    # qu'en dehors des liens.
    html = str(avec_liens(contenu))
    noms = sorted(
        {f"@{m.get('prenom', '')} {m.get('nom', '')}".strip() for m in (mentions or [])},
        key=len, reverse=True,
    )
    if noms:
        motif = re.compile(
            "(" + "|".join(re.escape(str(escape(n))) for n in noms) + r")(?!\w)", re.IGNORECASE,
        )
        morceaux = re.split(r"(<a [^>]*>.*?</a>)", html)
        html = "".join(m if m.startswith("<a ") else
                       motif.sub(lambda x: f'<span class="post-comment-mention">{x.group(1)}</span>', m)
                       for m in morceaux)
    return Markup(html)


def parser_montant(texte: str | None):
    """Montant saisi à la française ("12 500,50", "12500.5", "12 500 €")
    → Decimal arrondi au centime, None si vide. ValueError si invalide ou
    négatif (honoraires du projet, migration 0010)."""
    from decimal import Decimal, InvalidOperation

    brut = (texte or "").strip()
    if not brut:
        return None
    nettoye = "".join(c for c in brut if c not in " \u00a0\u202f€").replace(",", ".")
    try:
        valeur = Decimal(nettoye)
    except InvalidOperation:
        raise ValueError(texte) from None
    if not valeur.is_finite() or valeur < 0 or valeur >= Decimal("10000000000"):
        raise ValueError(texte)
    return valeur.quantize(Decimal("0.01"))


def montant_fr(valeur) -> str:
    """12500.5 → "12 500,50" (espace fine insécable pour les milliers)."""
    if valeur is None or valeur == "":
        return ""
    texte = f"{float(valeur):,.2f}".replace(",", "\u202f").replace(".", ",")
    return texte[:-3] if texte.endswith(",00") else texte


def heures(valeur) -> str:
    """Durée en heures et minutes, unité comprise (lot 11) : 1.75 → « 1 h 45 »,
    8 → « 8 h », 0.5 → « 0 h 30 », None → « 0 h ». Remplace l'affichage
    décimal arrondi au dixième (« 1,8 h » pour 1 h 45 : les totaux ne
    tombaient plus juste). Arrondi à la minute. Filtre unique : `|heures`
    dans les gabarits."""
    minutes = int(round(float(valeur or 0) * 60))
    signe = "-" if minutes < 0 else ""
    h, m = divmod(abs(minutes), 60)
    return f"{signe}{h}\u00a0h" + (f"\u00a0{m:02d}" if m else "")


def heures_interv_chef(interv, chef) -> str:
    """« 8 h / 5 h 30 » = heures intervenants / heures chef de projet
    (retour Fadhel, J.docx : « 8/5 h pour 8 heure intervenant et 5 heure
    chef de projet ») — projets, tâches et panneau Informations ; en heures
    et minutes depuis le lot 11. Revue produit P1-5 : « 8 h · 5 h » (le
    sens des deux nombres est donné par l'en-tête ou le libellé voisin)."""
    return f"{heures(interv)} · {heures(chef)}"


def _aujourdhui():
    from .horloge import aujourdhui

    return aujourdhui()


def register(app):
    """Rend ces helpers disponibles directement dans les templates Jinja2."""
    app.jinja_env.globals.update(
        initials=initials,
        avatar_color=avatar_color,
        avatar_url=avatar_url,
        tache_etat_style=tache_etat_style,
        projet_etat_style=projet_etat_style,
        post_type_style=post_type_style,
        post_tache_pill=POST_TACHE_PILL,
        role_style=role_style,
        equipe_libelle=equipe_libelle,
        equipe_choices=EQUIPE_CHOICES,
        date_fr=date_fr,
        en_retard_de=en_retard_de,
        notif_categorie_style=notif_categorie_style,
        is_lien_valide=is_lien_valide,
        is_image_filename=is_image_filename,
        personnes_recentes_d_abord=personnes_recentes_d_abord,
        texte_avec_mentions=texte_avec_mentions,
        heures_interv_chef=heures_interv_chef,
        jours_blocage=jours_blocage,
        depuis_blocage=depuis_blocage,
        montant_fr=montant_fr,
        zip=zip,
        # Date du jour côté serveur (retour Fadhel, 2026-09-28) — appelée
        # dans les templates comme today() pour préremplir l'échéance de
        # "nouveau poste" ; une fonction (pas une valeur figée au démarrage
        # de l'appli) pour rester juste après minuit. Lot 12 : app/horloge.py
        # (date simulée de l'Admin en mode test).
        today=_aujourdhui,
    )
    app.jinja_env.filters["personne_mentionnable"] = lambda u: {"id": u["id"], "prenom": u["prenom"], "nom": u["nom"]}
    app.jinja_env.filters["il_y_a"] = il_y_a
    app.jinja_env.filters["avec_liens"] = avec_liens
    app.jinja_env.filters["date_courte"] = date_courte
    app.jinja_env.filters["jour_local"] = jour_local
    app.jinja_env.filters["date_longue"] = date_longue
    app.jinja_env.filters["heures"] = heures

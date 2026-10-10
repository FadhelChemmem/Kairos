"""Fil filtrable (lot 14, revue produit P1-3) : catégorie affichée
(« Tout · Échanges · Activité »), regroupement des posts automatiques et
curseur de pagination « Afficher plus ».

- **Échanges** : ce que des personnes ont écrit — Information, Requête,
  Question, Envoi, Réponse, « Donner suite », et la clôture d'une tâche
  accompagnée d'un message (son tag est choisi et son texte écrit par la
  personne).
- **Activité** : les posts automatiques (création, état, titre, échéance,
  intervenants, clôture sans message d'une tâche ; création, état, chef et
  intervenants d'un projet), et tout nouvel évènement automatique.

Par défaut : Échanges (voir CATEGORIE_DEFAUT).
"""
import datetime
from urllib.parse import parse_qs, urlsplit

from flask import request

CATEGORIES = ("tout", "echanges", "activite")
# Revue produit P1-3 : à l'accueil d'un chef, 15 posts sur 20 sont
# automatiques ; les questions et requêtes, qui attendent une réponse, y
# sont noyées. Les évènements automatiques sont déjà visibles ailleurs (carte
# des tâches, Deadlines, notifications) : le fil montre d'abord les échanges.
CATEGORIE_DEFAUT = "echanges"
LIBELLES = {"tout": "Tout", "echanges": "Échanges", "activite": "Activité"}
FENETRE_GROUPE = datetime.timedelta(hours=1)
TAILLE_PAGE = 30


# Lien vers un post ancien (notification, recette du lot 14 n° 13) : le fil
# s'ouvre jusqu'à lui (`?jusqua=<id>`), dans cette limite.
MAX_POSTS_JUSQUA = 500


def categorie_demandee() -> str:
    """Catégorie de l'adresse (`?fil=`) ; pour une action en partiel (POST
    d'une tâche, publication…), celle de la page d'où elle part (Referer
    interne, tenu à jour par l'History API) ; sinon la valeur par défaut.
    Jamais le Referer pour une page complète (recette du lot 14, n° 6) :
    l'accueil ouvert depuis une fiche en « Activité » s'ouvre sur sa propre
    catégorie (défaut, ou choix mémorisé pour cette page)."""
    from . import partiel

    valeur = request.args.get("fil")
    if valeur is None and request.referrer and (partiel.est_partiel() or request.method == "POST"):
        parts = urlsplit(request.referrer)
        if not parts.netloc or parts.netloc == request.host:
            valeur = (parse_qs(parts.query).get("fil") or [None])[0]
    return valeur if valeur in CATEGORIES else CATEGORIE_DEFAUT


def taille_jusqua(taille: int, rang) -> int:
    """Taille de la première page pour qu'elle contienne le post demandé
    par `?jusqua=<id>` : `rang(post_id)` donne sa position dans le fil (0 :
    absent)."""
    brut = request.args.get("jusqua") or ""
    if not brut.isdigit() or len(brut) > 18 or request.args.get("avant"):
        return taille
    return max(taille, min(rang(int(brut)), MAX_POSTS_JUSQUA))


def curseur_demande():
    """`?avant=<horodatage ISO>_<id>` → (datetime, id), ou None."""
    brut = request.args.get("avant") or ""
    date, _, ident = brut.rpartition("_")
    try:
        return datetime.datetime.fromisoformat(date), int(ident)
    except ValueError:
        return None


def curseur_de(post: dict) -> str:
    return f"{post['created_at'].isoformat()}_{post['id']}"


def page(posts: list[dict], taille: int):
    """(posts de la page, curseur de la suivante ou None) — la requête a
    demandé `taille + 1` posts pour savoir s'il en reste."""
    if len(posts) > taille:
        posts = posts[:taille]
        return posts, curseur_de(posts[-1])
    return posts, None


# Phrase d'un évènement : (participe et objet au singulier, au pluriel) —
# accolée à « a » (« a créé 3 tâches »), ou jointe aux autres dans un
# regroupement (« a créé 2 tâches et changé l’état d’une tâche »).
_PHRASES = {
    "creation_tache": ("créé une tâche", "créé {n} tâches"),
    "cloture_tache": ("terminé une tâche", "terminé {n} tâches"),
    "etat_tache": ("changé l’état d’une tâche", "changé l’état de {n} tâches"),
    "titre_tache": ("renommé une tâche", "renommé {n} tâches"),
    "intervenant_tache": ("changé les intervenants d’une tâche", "changé les intervenants de {n} tâches"),
    "echeance_tache": ("changé l’échéance d’une tâche", "changé l’échéance de {n} tâches"),
    "creation_projet": ("créé le projet", "créé le projet"),
    "etat_projet": ("changé l’état du projet", "changé {n} fois l’état du projet"),
    "chef_projet": ("changé le chef de projet", "changé {n} fois le chef de projet"),
    "intervenant_projet": ("retiré un intervenant du projet", "retiré {n} intervenants du projet"),
}
_AUTRE = ("fait une modification", "fait {n} modifications")
_PAR_TACHE = {"creation_tache", "cloture_tache", "etat_tache", "titre_tache", "intervenant_tache", "echeance_tache"}


def resume(posts: list[dict]) -> str:
    """« a créé 3 tâches et changé l’état d’une tâche » — dans l'ordre où
    les évènements sont arrivés ; les évènements d'une tâche comptent les
    tâches distinctes (trois changements d'état de la même tâche : « a
    changé l’état d’une tâche »)."""
    ordre, comptes = [], {}
    for p in sorted(posts, key=lambda x: (x["created_at"], x["id"])):
        ev = p.get("evenement") if p.get("evenement") in _PHRASES else "_autre"
        if ev not in comptes:
            ordre.append(ev)
            comptes[ev] = set() if ev in _PAR_TACHE else []
        if ev in _PAR_TACHE:
            comptes[ev].add(p.get("tache_id") or -p["id"])
        else:
            comptes[ev].append(p["id"])
    parties = []
    for ev in ordre:
        n = len(comptes[ev])
        un, plusieurs = _PHRASES.get(ev, _AUTRE)
        parties.append(un if n == 1 else plusieurs.format(n=n))
    if len(parties) > 1:
        return "a " + ", ".join(parties[:-1]) + " et " + parties[-1]
    return "a " + parties[0]


def objets(posts: list[dict], maximum: int = 3) -> tuple[list[str], int]:
    """Titres des tâches concernées, sans doublon, du plus récent au plus
    ancien : les `maximum` premiers et le nombre restant (les évènements du
    projet lui-même n'en ont pas : leur texte est dans le détail)."""
    vus = []
    for p in posts:
        texte = (p.get("tache_titre") or "").strip() if p.get("tache_id") else ""
        if texte and texte not in vus:
            vus.append(texte)
    return vus[:maximum], max(0, len(vus) - maximum)


def regrouper(posts: list[dict], fenetre: datetime.timedelta = FENETRE_GROUPE) -> list[dict]:
    """Entrées du fil : `{"post": p}` ou `{"groupe": [...posts], ...}`.
    Les posts automatiques d'un même projet par la même personne, publiés à
    moins d'une heure du plus récent d'entre eux, forment un groupe placé à
    la position de ce plus récent ; un groupe d'un seul post reste un post.
    `posts` est trié du plus récent au plus ancien."""
    entrees, ouverts = [], {}
    for p in posts:
        if not p.get("est_activite") or p.get("projet_id") is None or p.get("created_at") is None:
            entrees.append({"posts": [p]})
            continue
        cle = (p["projet_id"], p["auteur_id"])
        groupe = ouverts.get(cle)
        if groupe is not None and groupe["posts"][0]["created_at"] - p["created_at"] <= fenetre:
            groupe["posts"].append(p)
        else:
            groupe = {"posts": [p]}
            ouverts[cle] = groupe
            entrees.append(groupe)
    resultat = []
    for e in entrees:
        if len(e["posts"]) == 1:
            resultat.append({"post": e["posts"][0]})
        else:
            premiers, reste = objets(e["posts"])
            resultat.append({"groupe": e["posts"], "tete": e["posts"][0], "phrase": resume(e["posts"]),
                             "objets": premiers, "objets_reste": reste})
    return resultat

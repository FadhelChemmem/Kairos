"""Requêtes SQL liées aux utilisateurs (hors authentification, voir auth.py)."""
import json

from .. import db


def list_actifs() -> list[dict]:
    """Utilisateurs actifs pouvant être choisis comme chef de projet ou
    intervenant (projet_creer.html, projet_detail.html). Exclut le RH
    (2026-09-16) : le RH ne peut être ni chef de projet ni intervenant —
    déjà garanti en base par les triggers trg_check_*_role (schema.sql),
    mais on évite de le proposer dans les listes pour ne pas faire
    échouer l'action après coup avec une erreur peu lisible."""
    return db.query_all(
        """
        SELECT id, prenom, nom, poste
        FROM utilisateur
        WHERE actif = true AND role != 'rh'
        ORDER BY nom, prenom
        """
    )


def search(q: str, limit: int = 6) -> list[dict]:
    """Recherche de personnes pour la barre de recherche topbar (Lot 5,
    retour Fadhel, 2026-09-28 — jusqu'ici différée, voir l'ancien
    commentaire de main.recherche_api : "pas de page de profil publique").
    Ouverte à toute l'entreprise (pas filtrée par équipe, contrairement
    aux projets) : seul le nom/poste est exposé ici, jamais l'email/le
    téléphone — c'est le PROFIL (utilisateurs.profil_personne) qui décide
    ensuite de ce qu'il montre, avec ses propres filtres de visibilité."""
    like = f"%{q.strip().lower()}%"
    return db.query_all(
        """
        SELECT id, prenom, nom, poste
        FROM utilisateur
        WHERE actif = true AND (lower(prenom) LIKE %s OR lower(nom) LIKE %s)
        ORDER BY nom, prenom
        LIMIT %s
        """,
        (like, like, limit),
    )


def list_tous(q: str | None = None, equipe_code: str | None = None,
              role: str | None = None, actif: bool | None = None) -> list[dict]:
    """Liste complète pour la page Utilisateurs (admin/RH, et chef de projet
    en lecture seule), avec filtres
    optionnels — voir routes/utilisateurs.py. Les comptes inactifs restent
    listés (grisés côté template) : on ne masque jamais l'historique."""
    conditions = []
    params: list = []

    if q:
        like = f"%{q.strip().lower()}%"
        conditions.append(
            "(lower(prenom) LIKE %s OR lower(nom) LIKE %s OR lower(email) LIKE %s "
            "OR lower(coalesce(poste, '')) LIKE %s)"
        )
        params.extend([like, like, like, like])
    if equipe_code:
        conditions.append("equipe_code = %s")
        params.append(equipe_code)
    if role:
        conditions.append("role = %s")
        params.append(role)
    if actif is not None:
        conditions.append("actif = %s")
        params.append(actif)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return db.query_all(
        f"""
        SELECT id, prenom, nom, email, telephone, poste, equipe_code, role,
               verifie, actif, date_embauche, avatar_chemin
        FROM utilisateur
        {where}
        ORDER BY actif DESC, nom, prenom
        """,
        tuple(params),
    )


def compter() -> dict:
    """Compte total / actifs, pour le bandeau de la page Utilisateurs."""
    return db.query_one(
        "SELECT count(*) AS total, count(*) FILTER (WHERE actif) AS actifs FROM utilisateur"
    )


def get_utilisateur(user_id: int) -> dict | None:
    return db.query_one(
        """
        SELECT id, prenom, nom, email, telephone, poste, adresse, date_embauche,
               equipe_code, role, verifie, actif, champs_perso, avatar_chemin
        FROM utilisateur
        WHERE id = %s
        """,
        (user_id,),
    )


def rh_deja_attribue() -> dict | None:
    """Retourne le titulaire actuel du rôle RH (actif), ou None — pour
    proposer l'option "RH" désactivée dans le formulaire de création,
    comme dans la maquette (idx_utilisateur_rh_singleton, schema.sql)."""
    return db.query_one(
        "SELECT id, prenom, nom FROM utilisateur WHERE role = 'rh' AND actif = true"
    )


def create_utilisateur(
    *, email: str, mot_de_passe_hash: str, prenom: str, nom: str, role: str,
    telephone: str | None = None, poste: str | None = None, adresse: str | None = None,
    date_embauche=None, equipe_code: str | None = None, verifie: bool = False,
    actif: bool = True, champs_perso: dict | None = None, avatar_chemin: str | None = None,
    current_user_id: int | None = None,
) -> int:
    """Crée un compte utilisateur depuis la page Utilisateurs. Mêmes
    contraintes que la commande CLI `flask create-user` (idx_utilisateur_
    rh_singleton, idx_utilisateur_email_lower) — laissées remonter en
    exception, gérées côté route pour un message clair.

    `actif` (PROMPT_CORRECTIONS.md P1 #11) : réglé directement à l'INSERT,
    plutôt que de toujours insérer `actif=true` puis appeler toggle_actif()
    juste après pour un compte censé naître inactif. L'ancienne façon de
    faire laissait exister, entre les deux requêtes (deux transactions
    séparées), un compte réellement actif en base — une fenêtre de
    "course" inutile — et pouvait déclencher à tort la contrainte
    idx_utilisateur_rh_singleton pour un compte RH qu'on voulait justement
    créer inactif (l'INSERT le voyait actif, même brièvement).

    avatar_chemin : photo de profil optionnelle, déjà enregistrée sur
    disque par app/storage.py avant l'appel (retour Fadhel, 2026-09-20 :
    "mettre une image au lieu du diminutif du nom prénom")."""
    row = db.query_one(
        """
        INSERT INTO utilisateur
            (email, mot_de_passe_hash, prenom, nom, telephone, poste, adresse,
             date_embauche, equipe_code, role, verifie, actif, champs_perso,
             avatar_chemin, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
        RETURNING id
        """,
        (email, mot_de_passe_hash, prenom, nom, telephone, poste, adresse,
         date_embauche, equipe_code, role, verifie, actif,
         json.dumps(champs_perso or {}), avatar_chemin, current_user_id),
        user_id=current_user_id,
    )
    return row["id"]


def update_profil(
    user_id: int, *, telephone: str | None, poste: str | None, adresse: str | None,
    current_user_id: int,
) -> None:
    """Modification de ses propres informations depuis la page "Infos
    perso" (demandé par Fadhel, 2026-09-19) — volontairement limité à
    téléphone/poste/adresse : l'identité (prénom, nom, email) et le rôle
    restent gérés par l'admin/RH via la page Utilisateurs. La photo de
    profil se change séparément (set_avatar) : on ne veut jamais l'effacer
    juste parce que ce formulaire-ci a été soumis sans nouveau fichier."""
    db.execute(
        """
        UPDATE utilisateur
        SET telephone = %s, poste = %s, adresse = %s
        WHERE id = %s
        """,
        (telephone, poste, adresse, user_id),
        user_id=current_user_id,
    )


def set_avatar(user_id: int, avatar_chemin: str, current_user_id: int) -> None:
    """Change la photo de profil (retour Fadhel, 2026-09-20). Fonction à
    part de update_profil pour ne jamais toucher à cette colonne quand
    aucun nouveau fichier n'a été envoyé."""
    db.execute(
        "UPDATE utilisateur SET avatar_chemin = %s WHERE id = %s",
        (avatar_chemin, user_id),
        user_id=current_user_id,
    )


def toggle_actif(user_id: int, current_user_id: int) -> None:
    """Active/désactive un compte (ne supprime jamais rien — voir la note
    de la maquette : l'historique projets/tâches/posts reste intact)."""
    db.execute(
        "UPDATE utilisateur SET actif = NOT actif WHERE id = %s",
        (user_id,),
        user_id=current_user_id,
    )


def update_utilisateur_complet(
    user_id: int, *, prenom: str, nom: str, email: str, telephone: str | None,
    poste: str | None, adresse: str | None, date_embauche, equipe_code: str | None,
    role: str, champs_perso: dict | None, current_user_id: int,
) -> None:
    """Édition complète d'un compte par un admin/RH (retour Fadhel,
    2026-09-20 : "voir et modifier les infos de n'importe quel
    utilisateur") — contrairement à update_profil (libre-service, limité
    à téléphone/poste/adresse), ici tout est modifiable, y compris le
    rôle. La règle "on ne peut pas changer son propre rôle depuis cet
    écran" est appliquée côté route (routes/utilisateurs.py), pas ici :
    cette fonction fait ce qu'on lui demande, la garde-fou est une
    décision d'écran. Les contraintes DB existantes (email unique, RH
    singleton) remontent en exception comme ailleurs."""
    db.execute(
        """
        UPDATE utilisateur
        SET prenom = %s, nom = %s, email = %s, telephone = %s, poste = %s,
            adresse = %s, date_embauche = %s, equipe_code = %s, role = %s,
            champs_perso = %s::jsonb
        WHERE id = %s
        """,
        (prenom, nom, email, telephone, poste, adresse, date_embauche,
         equipe_code, role, json.dumps(champs_perso or {}), user_id),
        user_id=current_user_id,
    )


def set_password(user_id: int, mot_de_passe_hash: str, current_user_id: int | None = None) -> None:
    """Change le mot de passe (réinitialisation, création sans mot de passe
    initial, changement en libre-service, ou changement par un admin) —
    n'importe quel jeton de réinitialisation en cours est effacé au
    passage, il ne doit plus être réutilisable une fois le mot de passe
    changé. Marque aussi le compte comme vérifié (retour Fadhel,
    2026-09-21) : dans tous ces cas, définir un mot de passe est la
    preuve qu'on a accès au compte (par email, ou parce qu'un admin/RH
    l'a fait volontairement depuis la fiche)."""
    db.execute(
        """
        UPDATE utilisateur
        SET mot_de_passe_hash = %s, reset_token_hash = NULL, reset_token_expires_at = NULL,
            verifie = true
        WHERE id = %s
        """,
        (mot_de_passe_hash, user_id),
        user_id=current_user_id or user_id,
    )


def get_mot_de_passe_hash(user_id: int) -> str | None:
    """Récupère uniquement le hash du mot de passe actuel — utilisé par le
    changement de mot de passe en libre-service (routes/utilisateurs.py:
    mon_mot_de_passe), qui doit vérifier l'ancien mot de passe avant
    d'accepter le nouveau."""
    row = db.query_one("SELECT mot_de_passe_hash FROM utilisateur WHERE id = %s", (user_id,))
    return row["mot_de_passe_hash"] if row else None


def set_reset_token(user_id: int, token_hash: str, expires_at) -> None:
    """Enregistre le jeton "mot de passe oublié" (son empreinte SHA-256,
    jamais le jeton en clair — voir app/auth.py)."""
    db.execute(
        "UPDATE utilisateur SET reset_token_hash = %s, reset_token_expires_at = %s WHERE id = %s",
        (token_hash, expires_at, user_id),
    )


def consommer_reset_token(token_hash: str, mot_de_passe_hash: str) -> dict | None:
    """Version ATOMIQUE de set_password(), réservée à la réinitialisation
    par jeton (PROMPT_CORRECTIONS.md P0 #3) : la vérification de validité
    du jeton ET son invalidation se font dans la MÊME requête UPDATE,
    contrairement au couple get_par_reset_token_hash() + set_password()
    utilisé auparavant (deux requêtes séparées). Sans ça, deux requêtes
    concurrentes avec le même jeton valide (onglet dupliqué, lien cliqué
    deux fois, ou un attaquant qui a intercepté le lien et tente de
    "gagner de vitesse" l'utilisateur légitime) passeraient toutes les
    deux la vérification avant qu'aucune n'ait eu le temps d'invalider le
    jeton — chacune changerait le mot de passe sans le savoir.

    Retourne le compte modifié (id, email, prenom, nom) si le jeton était
    encore valide et vient d'être consommé, sinon None (jeton inconnu,
    expiré, ou déjà utilisé)."""
    return db.query_one(
        """
        UPDATE utilisateur
        SET mot_de_passe_hash = %s, reset_token_hash = NULL, reset_token_expires_at = NULL,
            verifie = true
        WHERE reset_token_hash = %s AND reset_token_expires_at > now()
          AND actif = true  -- compte désactivé entre l'ouverture du lien et l'envoi
        RETURNING id, email, prenom, nom
        """,
        (mot_de_passe_hash, token_hash),
    )


def get_par_reset_token_hash(token_hash: str) -> dict | None:
    """Retrouve le compte visé par un jeton de réinitialisation encore
    valable (pas expiré). Un jeton expiré ou inconnu renvoie None, sans
    distinction — on ne veut pas donner d'indice à qui tâtonne."""
    return db.query_one(
        """
        SELECT id, email, prenom, nom, actif
        FROM utilisateur
        WHERE reset_token_hash = %s AND reset_token_expires_at > now()
        """,
        (token_hash,),
    )

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


def list_tous(q: str | None = None, equipe_code: str | None = None,
              role: str | None = None, actif: bool | None = None) -> list[dict]:
    """Liste complète pour la page Utilisateurs (admin/RH), avec filtres
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


def email_deja_utilise(email: str) -> bool:
    return db.query_one(
        "SELECT 1 AS x FROM utilisateur WHERE lower(email) = lower(%s)", (email,)
    ) is not None


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
    champs_perso: dict | None = None, avatar_chemin: str | None = None,
    current_user_id: int | None = None,
) -> int:
    """Crée un compte utilisateur depuis la page Utilisateurs. Mêmes
    contraintes que la commande CLI `flask create-user` (idx_utilisateur_
    rh_singleton, idx_utilisateur_email_lower) — laissées remonter en
    exception, gérées côté route pour un message clair.

    avatar_chemin : photo de profil optionnelle, déjà enregistrée sur
    disque par app/storage.py avant l'appel (retour Fadhel, 2026-09-20 :
    "mettre une image au lieu du diminutif du nom prénom")."""
    row = db.query_one(
        """
        INSERT INTO utilisateur
            (email, mot_de_passe_hash, prenom, nom, telephone, poste, adresse,
             date_embauche, equipe_code, role, verifie, actif, champs_perso,
             avatar_chemin, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, %s::jsonb, %s, %s)
        RETURNING id
        """,
        (email, mot_de_passe_hash, prenom, nom, telephone, poste, adresse,
         date_embauche, equipe_code, role, verifie,
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

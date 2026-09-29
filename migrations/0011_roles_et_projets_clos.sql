-- Rôles et projets clos (décisions de Fadhel, lot 7, 2026-09-29) :
--
-- 1. Visibilité des projets (v_projet_visibilite) :
--    - RH : plus aucun accès aux projets (il garde les Informations
--      d'équipe, voir repositories/posts.py) ;
--    - Client : les projets de SON équipe seulement (jamais rattaché à un
--      projet ou une tâche, voir 2.) ;
--    - Admin : tout ; autres rôles : inchangé (équipe + rattachements).
-- 2. Un Client ne peut être ni chef, ni co-chef, ni intervenant (projet ou
--    tâche) — même garde-fou en base que pour le RH (fn_check_role_non_rh,
--    appelée par les triggers trg_check_*_role), y compris quand un compte
--    rattaché passe au rôle Client (fn_check_passage_role_rh, migration
--    0005, étendue). Les rattachements d'un Client antérieurs à cette
--    migration ne sont pas supprimés, mais l'appli ne leur donne plus aucun
--    droit (projets.user_can_manage, taches.user_est_intervenant).
-- 3. Date de clôture (projet.date_cloture) : posée automatiquement quand
--    le projet passe à Terminé ou Abandonné, effacée s'il est rouvert
--    (voir projets.update_projet). Après cette date, plus d'heures de
--    Daily log sur le projet. Colonne à part de `date_fin`, qui reste la
--    date de fin prévue saisie par le chef (affichée "Échéance") : la
--    remplir/l'effacer automatiquement aurait écrasé cette échéance.
--    Projets déjà clos : date du dernier changement d'état enregistré dans
--    le fil (post automatique "etat_projet"), sinon de leur dernière
--    modification.
--
-- Rejouable : IF NOT EXISTS, CREATE OR REPLACE, UPDATE limité aux dates
-- vides.

-- 1.
CREATE OR REPLACE VIEW v_projet_visibilite AS
SELECT p.id AS projet_id, u.id AS utilisateur_id
FROM projet p
CROSS JOIN utilisateur u
WHERE u.actif = true
  AND u.role <> 'rh'
  AND (
    u.role = 'admin'
    OR u.equipe_code = p.equipe_code
    OR (u.role <> 'client' AND (
      u.id = p.chef_projet_id
      OR EXISTS (SELECT 1 FROM projet_co_chef pc WHERE pc.projet_id = p.id AND pc.utilisateur_id = u.id)
      OR EXISTS (SELECT 1 FROM projet_intervenant pi WHERE pi.projet_id = p.id AND pi.utilisateur_id = u.id)
      OR EXISTS (
        SELECT 1 FROM tache t
        JOIN tache_intervenant ti ON ti.tache_id = t.id
        WHERE t.projet_id = p.id AND ti.utilisateur_id = u.id
      )
    ))
  );

-- 2.
CREATE OR REPLACE FUNCTION fn_check_role_non_rh(p_utilisateur_id BIGINT, p_contexte TEXT)
RETURNS VOID AS $$
DECLARE
  v_role role_enum;
BEGIN
  SELECT role INTO v_role FROM utilisateur WHERE id = p_utilisateur_id;
  IF v_role = 'rh' THEN
    RAISE EXCEPTION 'Un utilisateur avec le rôle RH ne peut pas être % (utilisateur id=%).', p_contexte, p_utilisateur_id;
  END IF;
  -- Client : jamais rattaché à un projet ou une tâche (migration 0011).
  IF v_role = 'client' THEN
    RAISE EXCEPTION 'Un utilisateur avec le rôle Client ne peut pas être % (utilisateur id=%).', p_contexte, p_utilisateur_id;
  END IF;
END;
$$ LANGUAGE plpgsql;

-- 2 bis.
CREATE OR REPLACE FUNCTION fn_check_passage_role_rh()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.role IN ('rh', 'client') AND OLD.role IS DISTINCT FROM NEW.role AND (
       EXISTS (SELECT 1 FROM projet WHERE chef_projet_id = NEW.id)
    OR EXISTS (SELECT 1 FROM projet_co_chef WHERE utilisateur_id = NEW.id)
    OR EXISTS (SELECT 1 FROM projet_intervenant WHERE utilisateur_id = NEW.id)
    OR EXISTS (SELECT 1 FROM tache_intervenant WHERE utilisateur_id = NEW.id)
  ) THEN
    RAISE EXCEPTION 'Un utilisateur avec le rôle % ne peut pas être chef de projet, co-chef ou intervenant (utilisateur id=%) : retirez-le d''abord de ses projets et tâches.',
      CASE NEW.role WHEN 'rh' THEN 'RH' ELSE 'Client' END, NEW.id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 3.
ALTER TABLE projet ADD COLUMN IF NOT EXISTS date_cloture DATE;
UPDATE projet p SET date_cloture = COALESCE(
    (SELECT max(po.created_at)::date FROM post po
      WHERE po.projet_id = p.id AND po.evenement = 'etat_projet'),
    p.updated_at::date)
WHERE p.etat IN ('termine', 'abandonne') AND p.date_cloture IS NULL;

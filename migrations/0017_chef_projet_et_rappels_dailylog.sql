-- 0017 — Lot 11 b (demandes du gérant après le lot 11).
--
-- 1. Changement du chef de projet depuis la fenêtre « Informations » de la
--    fiche projet (routes/projets.py, repositories/projets.py) :
--    - post.evenement accepte 'chef_projet' : post automatique « X a confié
--      le projet à Y » dans le fil du projet ;
--    - trg_garde_chef_projet, dernier rempart quand chef_projet_id CHANGE
--      (jamais à la création ni sur une autre colonne) :
--        * le nouveau chef a un compte actif et le rôle Chef de projet ou
--          Admin ;
--        * l'acteur est un Admin, le chef titulaire ou un co-chef du projet
--          (compte actif, ni RH ni Client) ;
--        * projet clos (Terminé, Abandonné) : Admin seulement — les autres
--          le rouvrent d'abord.
--      Sans app.current_user_id (scripts, migrations, psql) ou pendant la
--      reprise Chronos (kairos.reprise_historique = 'on') : aucune
--      restriction, comme trg_garde_etat_tache (0015). Les projets existants
--      ne sont ni relus ni réécrits (un chef déjà désactivé reste en place
--      jusqu'à ce qu'on le remplace).
--
-- 2. Rappels Daily log : notification.rappel_jours, les jours oubliés que
--    cite le rappel (un ou plusieurs : un seul rappel regroupe les jours
--    manquants). C'est la clé du dédoublonnage (un jour déjà rappelé ne
--    l'est plus) et du marquage « lu » quand ces jours sont remplis — au
--    lieu du texte (LIKE 'Rappel DailyLog%'). Les rappels déjà envoyés (texte
--    « Rappel DailyLog : vous n'avez pas rempli votre journée du
--    JJ/MM/AAAA. ») reçoivent leur jour ici : ils restent reconnus, sans
--    changer leur texte.
--
-- Rejouable : DROP … IF EXISTS / ADD, IF NOT EXISTS, CREATE OR REPLACE ; le
-- rattrapage ne vise que les rappels sans rappel_jours.

SELECT set_config('lock_timeout', '15s', true);

-- 1. Changement de chef ------------------------------------------------
ALTER TABLE post DROP CONSTRAINT IF EXISTS post_evenement_check;
ALTER TABLE post ADD CONSTRAINT post_evenement_check
  CHECK (evenement IS NULL OR evenement IN (
    'creation_tache', 'cloture_tache', 'repost',
    'creation_projet', 'etat_tache', 'etat_projet', 'titre_tache', 'chef_projet'));

CREATE OR REPLACE FUNCTION fn_garde_chef_projet()
RETURNS TRIGGER AS $$
DECLARE
  v_acteur BIGINT := fn_app_user_id();
BEGIN
  IF NEW.chef_projet_id IS NOT DISTINCT FROM OLD.chef_projet_id
     OR v_acteur IS NULL
     OR current_setting('kairos.reprise_historique', true) = 'on' THEN
    RETURN NEW;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM utilisateur u
    WHERE u.id = NEW.chef_projet_id AND u.actif AND u.role IN ('chef_de_projet', 'admin')
  ) THEN
    RAISE EXCEPTION 'Projet % : le nouveau chef de projet (utilisateur %) doit avoir un compte actif et le rôle Chef de projet ou Admin.',
      NEW.id, NEW.chef_projet_id
      USING ERRCODE = 'check_violation', CONSTRAINT = 'projet_chef_valide';
  END IF;
  IF EXISTS (SELECT 1 FROM utilisateur u WHERE u.id = v_acteur AND u.actif AND u.role = 'admin') THEN
    RETURN NEW;
  END IF;
  IF OLD.etat IN ('termine', 'abandonne') THEN
    RAISE EXCEPTION 'Projet % clos : rouvrez-le avant de changer de chef de projet (un Admin peut toujours le réaffecter).',
      NEW.id
      USING ERRCODE = 'insufficient_privilege', CONSTRAINT = 'projet_chef_change';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM utilisateur u
    WHERE u.id = v_acteur AND u.actif AND u.role NOT IN ('client', 'rh')
      AND (OLD.chef_projet_id = u.id
           OR EXISTS (SELECT 1 FROM projet_co_chef cc
                      WHERE cc.projet_id = OLD.id AND cc.utilisateur_id = u.id))
  ) THEN
    RAISE EXCEPTION 'Projet % : seuls le chef de projet, un co-chef ou un Admin peuvent changer de chef de projet.',
      NEW.id
      USING ERRCODE = 'insufficient_privilege', CONSTRAINT = 'projet_chef_change';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_garde_chef_projet ON projet;
CREATE TRIGGER trg_garde_chef_projet
  BEFORE UPDATE OF chef_projet_id ON projet
  FOR EACH ROW EXECUTE FUNCTION fn_garde_chef_projet();

-- 2. Rappels Daily log -------------------------------------------------
ALTER TABLE notification ADD COLUMN IF NOT EXISTS rappel_jours DATE[];
ALTER TABLE notification DROP CONSTRAINT IF EXISTS notification_rappel_jours_check;
ALTER TABLE notification ADD CONSTRAINT notification_rappel_jours_check
  CHECK (rappel_jours IS NULL OR cardinality(rappel_jours) BETWEEN 1 AND 31);

UPDATE notification
   SET rappel_jours = ARRAY[to_date(substring(message from '([0-9]{2}/[0-9]{2}/[0-9]{4})'), 'DD/MM/YYYY')]
 WHERE rappel_jours IS NULL
   AND categorie = 'rh_info'
   AND message LIKE 'Rappel DailyLog%'
   AND message ~ '[0-9]{2}/[0-9]{2}/[0-9]{4}';

CREATE INDEX IF NOT EXISTS idx_notification_rappel_jours
  ON notification (utilisateur_id) WHERE rappel_jours IS NOT NULL;

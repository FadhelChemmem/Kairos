-- 0015 — États de tâche réservés (décision du gérant, lot 10) : seuls le
-- chef de projet titulaire, les co-chefs du projet et l'Admin (co-chef
-- partout) peuvent passer une tâche en Vérifiée, Arrêtée ou Abandonnée, ET
-- la faire sortir de ces états (la rouvrir, la clôturer…). Les
-- intervenants gardent En cours / Terminée / Bloquée.
--
-- L'appli donne le message clair avant (routes/projets.py,
-- repositories/taches.py) ; ce trigger est le dernier rempart, quel que
-- soit le chemin (route oubliée, SQL à la main avec app.current_user_id).
-- Sans app.current_user_id (scripts, migrations, psql) ou pendant la
-- reprise Chronos (kairos.reprise_historique = 'on') : aucune restriction.
-- Les données existantes ne sont ni relues ni réécrites : seul un état qui
-- CHANGE est contrôlé.
--
-- Rejouable : CREATE OR REPLACE, DROP TRIGGER IF EXISTS.

SELECT set_config('lock_timeout', '15s', true);

CREATE OR REPLACE FUNCTION fn_garde_etat_tache()
RETURNS TRIGGER AS $$
DECLARE
  v_acteur BIGINT := fn_app_user_id();
BEGIN
  IF v_acteur IS NULL OR current_setting('kairos.reprise_historique', true) = 'on' THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF OLD.etat = NEW.etat THEN
      RETURN NEW;
    END IF;
    IF OLD.etat NOT IN ('verifie', 'arret', 'abandonne')
       AND NEW.etat NOT IN ('verifie', 'arret', 'abandonne') THEN
      RETURN NEW;
    END IF;
  ELSIF NEW.etat NOT IN ('verifie', 'arret', 'abandonne') THEN
    RETURN NEW;
  END IF;
  IF EXISTS (
    SELECT 1
    FROM utilisateur u
    JOIN projet p ON p.id = NEW.projet_id
    WHERE u.id = v_acteur
      AND u.actif AND u.role NOT IN ('client', 'rh')
      AND (u.role = 'admin'
           OR p.chef_projet_id = u.id
           OR EXISTS (SELECT 1 FROM projet_co_chef cc
                      WHERE cc.projet_id = p.id AND cc.utilisateur_id = u.id))
  ) THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'Tâche % : seuls le chef de projet, un co-chef ou un Admin peuvent la passer en Vérifiée, Arrêtée ou Abandonnée, ou la faire sortir de ces états.',
    NEW.id
    USING ERRCODE = 'insufficient_privilege', CONSTRAINT = 'tache_etat_reserve';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_garde_etat_tache ON tache;
CREATE TRIGGER trg_garde_etat_tache
  BEFORE INSERT OR UPDATE OF etat ON tache
  FOR EACH ROW EXECUTE FUNCTION fn_garde_etat_tache();

-- Contrôle des saisies en base (retour Fadhel, lot 8 : « on ne peut pas
-- créer une tâche antérieure au projet, une date de fin avant la date de
-- début… vérifier toutes les saisies ») — en plus des contrôles de
-- l'appli (app/validation.py, routes), la base refuse désormais :
--   - un projet dont la date de fin précède la date de début, ou avec des
--     honoraires négatifs ;
--   - une tâche dont l'échéance précède sa date de début.
-- Triggers déclenchés seulement quand ces valeurs CHANGENT, plutôt que
-- des CHECK : une donnée ancienne incohérente (ex. reprise de Chronos) ne
-- doit bloquer ni la mise à jour, ni un changement d'état, ni un
-- renommage (un CHECK, même NOT VALID, revérifie toute la ligne à chaque
-- UPDATE ; la fenêtre Informations réécrit les dates à chaque envoi).
--
-- Rejouable : CREATE OR REPLACE, DROP TRIGGER IF EXISTS.
CREATE OR REPLACE FUNCTION fn_check_dates_projet()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.date_fin IS NOT NULL AND NEW.date_debut IS NOT NULL AND NEW.date_fin < NEW.date_debut THEN
    RAISE EXCEPTION 'Date de fin du projet (%) antérieure à sa date de début (%).', NEW.date_fin, NEW.date_debut;
  END IF;
  IF NEW.honoraires IS NOT NULL AND NEW.honoraires < 0 THEN
    RAISE EXCEPTION 'Honoraires négatifs refusés.';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_check_dates_projet ON projet;
CREATE TRIGGER trg_check_dates_projet
  BEFORE INSERT ON projet
  FOR EACH ROW EXECUTE FUNCTION fn_check_dates_projet();
DROP TRIGGER IF EXISTS trg_check_dates_projet_maj ON projet;
CREATE TRIGGER trg_check_dates_projet_maj
  BEFORE UPDATE OF date_debut, date_fin, honoraires ON projet
  FOR EACH ROW
  WHEN (OLD.date_debut IS DISTINCT FROM NEW.date_debut
        OR OLD.date_fin IS DISTINCT FROM NEW.date_fin
        OR OLD.honoraires IS DISTINCT FROM NEW.honoraires)
  EXECUTE FUNCTION fn_check_dates_projet();

CREATE OR REPLACE FUNCTION fn_check_dates_tache()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.date_echeance IS NOT NULL AND NEW.date_debut IS NOT NULL AND NEW.date_echeance < NEW.date_debut THEN
    RAISE EXCEPTION 'Échéance de la tâche (%) antérieure à sa date de début (%).', NEW.date_echeance, NEW.date_debut;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_check_dates_tache ON tache;
CREATE TRIGGER trg_check_dates_tache
  BEFORE INSERT ON tache
  FOR EACH ROW EXECUTE FUNCTION fn_check_dates_tache();
DROP TRIGGER IF EXISTS trg_check_dates_tache_maj ON tache;
CREATE TRIGGER trg_check_dates_tache_maj
  BEFORE UPDATE OF date_debut, date_echeance ON tache
  FOR EACH ROW
  WHEN (OLD.date_debut IS DISTINCT FROM NEW.date_debut
        OR OLD.date_echeance IS DISTINCT FROM NEW.date_echeance)
  EXECUTE FUNCTION fn_check_dates_tache();

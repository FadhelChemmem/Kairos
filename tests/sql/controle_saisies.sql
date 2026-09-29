-- Contrôle des saisies en base (migration 0012, lot 8) : dates ordonnées
-- et honoraires positifs refusés ; une ancienne ligne incohérente reste
-- modifiable pour tout le reste (changement d'état). Tout est annulé.
BEGIN;

INSERT INTO utilisateur (email, mot_de_passe_hash, prenom, nom, role, equipe_code)
VALUES ('t-chef-dates@test.tn', 'x', 'T', 'Chef', 'chef_de_projet', 'MIDGARD');
INSERT INTO projet (code, nom, phase, chef_projet_id, equipe_code, date_debut)
SELECT 'T0100X', 'Projet dates', 'EXE', id, 'MIDGARD', DATE '2026-03-01'
FROM utilisateur WHERE email = 't-chef-dates@test.tn';

DO $$
DECLARE
  v_projet BIGINT := (SELECT id FROM projet WHERE code = 'T0100X');
  v_chef   BIGINT := (SELECT chef_projet_id FROM projet WHERE code = 'T0100X');
  v_tache  BIGINT;
  v_refus  INT := 0;
BEGIN
  BEGIN
    UPDATE projet SET date_fin = DATE '2026-02-01' WHERE id = v_projet;
  EXCEPTION WHEN raise_exception THEN v_refus := v_refus + 1;
  END;
  BEGIN
    UPDATE projet SET honoraires = -1 WHERE id = v_projet;
  EXCEPTION WHEN raise_exception THEN v_refus := v_refus + 1;
  END;
  BEGIN
    INSERT INTO tache (projet_id, titre, created_by, date_debut, date_echeance)
    VALUES (v_projet, 'Échéance avant début', v_chef, DATE '2026-04-10', DATE '2026-04-01');
  EXCEPTION WHEN raise_exception THEN v_refus := v_refus + 1;
  END;
  IF v_refus <> 3 THEN
    RAISE EXCEPTION 'Saisies incohérentes acceptées : % refus sur 3 attendus', v_refus;
  END IF;

  -- Une tâche cohérente passe.
  INSERT INTO tache (projet_id, titre, created_by, date_debut, date_echeance)
  VALUES (v_projet, 'Tâche normale', v_chef, DATE '2026-04-01', DATE '2026-04-10')
  RETURNING id INTO v_tache;
END $$;

-- Ancienne donnée incohérente (d'avant la migration) : son état reste
-- modifiable.
ALTER TABLE tache DISABLE TRIGGER trg_check_dates_tache_maj;
UPDATE tache SET date_echeance = DATE '2026-03-15' WHERE titre = 'Tâche normale';
ALTER TABLE tache ENABLE TRIGGER trg_check_dates_tache_maj;
UPDATE tache SET etat = 'bloque' WHERE titre = 'Tâche normale';
-- Même chose pour un projet : la fenêtre Informations réécrit les dates
-- telles quelles en renommant ou en clôturant.
ALTER TABLE projet DISABLE TRIGGER trg_check_dates_projet_maj;
UPDATE projet SET date_fin = DATE '2026-02-01' WHERE code = 'T0100X';
ALTER TABLE projet ENABLE TRIGGER trg_check_dates_projet_maj;
UPDATE projet SET nom = 'Renommé', etat = 'termine', date_debut = date_debut, date_fin = date_fin,
                  honoraires = honoraires WHERE code = 'T0100X';

ROLLBACK;

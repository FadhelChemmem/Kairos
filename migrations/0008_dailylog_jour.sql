-- Daily log v2 (retour Fadhel, 2026-09-29, maquette validée — voir
-- claude/kairos-dailylog-v2.md dans le projet) : la durée de la journée
-- se règle jour par jour (double-clic sur « 8 h » : de 4 h à 10 h, ou
-- « Absent »). Une ligne par utilisateur et par jour, créée seulement
-- quand la journée est enregistrée ; sans ligne, la journée vaut la
-- durée type (8 h), ou pour une journée déjà saisie avant cette
-- migration, le total de ses heures (option B : les heures déjà
-- enregistrées ne sont jamais modifiées).
--
-- duree_heures : 4 h à 10 h depuis l'écran ; la contrainte en base
-- accepte au-delà de 0 et jusqu'à 24 h pour ne pas refuser une ancienne
-- journée (option B) dont le total sortirait de cette plage.
-- absent : journée marquée absente (pastille bleue du calendrier) — ses
-- lignes d'heures sont supprimées à l'enregistrement.
--
-- Rejouable : IF NOT EXISTS partout, trigger créé seulement s'il manque.

CREATE TABLE IF NOT EXISTS dailylog_jour (
  id             BIGSERIAL PRIMARY KEY,
  utilisateur_id BIGINT NOT NULL REFERENCES utilisateur(id),
  date           DATE NOT NULL,
  duree_heures   NUMERIC(4,2) NOT NULL DEFAULT 8,
  absent         BOOLEAN NOT NULL DEFAULT false,
  updated_by     BIGINT REFERENCES utilisateur(id),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT dailylog_jour_duree_valide CHECK (duree_heures > 0 AND duree_heures <= 24),
  CONSTRAINT dailylog_jour_unique UNIQUE (utilisateur_id, date)
);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_dailylog_jour_updated_at') THEN
    CREATE TRIGGER trg_dailylog_jour_updated_at
      BEFORE UPDATE ON dailylog_jour
      FOR EACH ROW EXECUTE FUNCTION set_updated_at_and_by();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_audit_dailylog_jour') THEN
    CREATE TRIGGER trg_audit_dailylog_jour
      AFTER INSERT OR UPDATE OR DELETE ON dailylog_jour
      FOR EACH ROW EXECUTE FUNCTION fn_audit_log();
  END IF;
END $$;

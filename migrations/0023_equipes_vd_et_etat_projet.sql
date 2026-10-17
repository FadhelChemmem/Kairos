-- 0023 — Lot 18 (décisions du gérant, 17/10/2026).
--
-- 1. Équipes : IPCO est retirée, VD est ajoutée. Équipes en vigueur :
--    MIDGARD, URBS, VD, SS, Q. IPCO est supprimée si plus personne ni aucun
--    projet ou post n'y est rattaché ; sinon elle est seulement marquée
--    inactive (les lignes existantes gardent leur équipe, rien n'est perdu).
--
-- 2. État du projet : « une tâche bloquée bloque le projet, et la création
--    d'une autre tâche, En cours, après le blocage change l'état du projet ».
--    Un projet OUVERT est Bloqué si une de ses tâches bloquées n'a été suivie
--    d'aucune tâche En cours CRÉÉE après son blocage ; En cours sinon. Même
--    fonction qu'avant (fn_etat_projet_recalcule), nouvelle règle ; l'appli
--    l'applique après chaque écriture de tâche ou de projet. Les projets
--    existants sont recalculés à leur prochaine écriture (aucun changement
--    d'état en masse au déploiement).
--
-- Rejouable : INSERT … ON CONFLICT, UPDATE / DELETE idempotents, CREATE OR
-- REPLACE. Mêmes définitions dans schema.sql.

SELECT set_config('lock_timeout', '15s', true);

-- 1. Équipes -------------------------------------------------------------
INSERT INTO equipe (code, libelle) VALUES ('VD', 'VD') ON CONFLICT (code) DO UPDATE SET actif = true;

UPDATE equipe SET actif = false WHERE code = 'IPCO';
DELETE FROM equipe e
WHERE e.code = 'IPCO'
  AND NOT EXISTS (SELECT 1 FROM utilisateur u WHERE u.equipe_code = e.code)
  AND NOT EXISTS (SELECT 1 FROM projet p WHERE p.equipe_code = e.code)
  AND NOT EXISTS (SELECT 1 FROM post_equipe pe WHERE pe.equipe_code = e.code);

-- 2. État du projet ------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_etat_projet_recalcule(p_etat projet_etat_enum, p_projet BIGINT)
RETURNS projet_etat_enum AS $$
  SELECT CASE
    WHEN p_etat NOT IN ('en_cours', 'bloque') THEN p_etat
    WHEN EXISTS (
      SELECT 1 FROM tache b
      WHERE b.projet_id = p_projet AND b.etat = 'bloque'
        AND NOT EXISTS (SELECT 1 FROM tache c
                        WHERE c.projet_id = p_projet AND c.etat = 'en_cours'
                          AND c.created_at > COALESCE(b.bloque_le, b.updated_at))
    ) THEN 'bloque'::projet_etat_enum
    ELSE 'en_cours'::projet_etat_enum
  END
$$ LANGUAGE sql STABLE;

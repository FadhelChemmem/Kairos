-- Projet : client et honoraires (retour Fadhel, Remarques du 2026-09-28 :
-- « Sur les projets, rajouter la section honoraire et client. Mettre
-- « IPCO » comme client par défaut. »). La colonne `honoraires` existait
-- déjà (réservée, jamais utilisée) ; `client` est nouvelle — les projets
-- existants reçoivent la valeur par défaut « IPCO ».
--
-- Rejouable : IF NOT EXISTS.

ALTER TABLE projet ADD COLUMN IF NOT EXISTS client VARCHAR(150) NOT NULL DEFAULT 'IPCO';

-- Renomme l'équipe ISBG en URBS et ajoute IPCO (retour Fadhel, 2026-09-20).
-- Écrit pour être rejouable sans risque (ON CONFLICT / conditions sur
-- l'existant) même si elle finit lancée deux fois.
INSERT INTO equipe (code, libelle) VALUES ('URBS', 'URBS') ON CONFLICT (code) DO NOTHING;
UPDATE utilisateur SET equipe_code = 'URBS' WHERE equipe_code = 'ISBG';
UPDATE projet SET equipe_code = 'URBS' WHERE equipe_code = 'ISBG';
DELETE FROM equipe WHERE code = 'ISBG';
INSERT INTO equipe (code, libelle) VALUES ('IPCO', 'IPCO') ON CONFLICT (code) DO NOTHING;

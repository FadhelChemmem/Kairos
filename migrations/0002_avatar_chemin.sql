-- Photo de profil optionnelle (retour Fadhel, 2026-09-20) : "mettre une
-- image au lieu du diminutif du nom prénom" à la création et à la
-- modification d'un compte.
ALTER TABLE utilisateur ADD COLUMN IF NOT EXISTS avatar_chemin TEXT;

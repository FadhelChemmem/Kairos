-- Mot de passe oublié fonctionnel + limite anti-bourrinage (retour
-- Fadhel, 2026-09-20). Voir aussi migrations/0002 (avatar_chemin, même
-- table utilisateur).

ALTER TABLE utilisateur ADD COLUMN IF NOT EXISTS reset_token_hash VARCHAR(64);
ALTER TABLE utilisateur ADD COLUMN IF NOT EXISTS reset_token_expires_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS tentative_securite (
  id          BIGSERIAL PRIMARY KEY,
  type        VARCHAR(30) NOT NULL,
  cle         VARCHAR(255) NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tentative_securite_lookup ON tentative_securite (type, cle, created_at);

-- Remplace la fonction d'audit générique pour qu'elle retire aussi
-- reset_token_hash (comme mot_de_passe_hash) des instantanés JSON
-- enregistrés dans audit_log. CREATE OR REPLACE : sans danger à rejouer.
CREATE OR REPLACE FUNCTION fn_audit_log()
RETURNS TRIGGER AS $$
DECLARE
  v_user_id BIGINT;
BEGIN
  BEGIN
    v_user_id := current_setting('app.current_user_id', true)::BIGINT;
  EXCEPTION WHEN OTHERS THEN
    v_user_id := NULL;
  END;

  IF (TG_OP = 'DELETE') THEN
    INSERT INTO audit_log(table_cible, ligne_id, action, utilisateur_id, donnees_avant)
    VALUES (TG_TABLE_NAME, (to_jsonb(OLD)->>'id')::BIGINT, TG_OP, v_user_id, to_jsonb(OLD) - 'mot_de_passe_hash' - 'reset_token_hash');
    RETURN OLD;
  ELSIF (TG_OP = 'UPDATE') THEN
    INSERT INTO audit_log(table_cible, ligne_id, action, utilisateur_id, donnees_avant, donnees_apres)
    VALUES (TG_TABLE_NAME, (to_jsonb(NEW)->>'id')::BIGINT, TG_OP, v_user_id, to_jsonb(OLD) - 'mot_de_passe_hash' - 'reset_token_hash', to_jsonb(NEW) - 'mot_de_passe_hash' - 'reset_token_hash');
    RETURN NEW;
  ELSIF (TG_OP = 'INSERT') THEN
    INSERT INTO audit_log(table_cible, ligne_id, action, utilisateur_id, donnees_apres)
    VALUES (TG_TABLE_NAME, (to_jsonb(NEW)->>'id')::BIGINT, TG_OP, v_user_id, to_jsonb(NEW) - 'mot_de_passe_hash' - 'reset_token_hash');
    RETURN NEW;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

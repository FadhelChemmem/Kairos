-- 0027 — Lot 24 (contre-expertise des lots 21 à 23 et décisions du gérant
-- du 20/10) :
--   1. Anciens participants : la lecture n'est gardée que par ceux qui ont
--      VRAIMENT participé (tâche, post, commentaire, heures, ancien chef ou
--      co-chef) — y compris quand la personne change d'équipe (MX-02).
--      Ajoutée puis retirée sans rien faire : plus de lecture (Q2 matrice).
--      Reprise des anciens chefs remplacés hors de l'appli (MD-3).
--   2. Un chef de projet intervenant d'une tâche rouverte redevient co-chef
--      (MX-01).
--   3. Toute tâche close a une date de fin, même chargée par un script
--      (NB7, SB-02, HD-09).
--   4. Filtres mémorisés : toujours un objet JSON (FI-07).
--   5. Notifications Windows (Web Push) : abonnements par appareil.
--
-- Rejouable : CREATE OR REPLACE, IF NOT EXISTS, DROP … IF EXISTS,
-- ON CONFLICT DO NOTHING, contraintes posées seulement si absentes.

SELECT set_config('lock_timeout', '15s', true);

-- 1. Anciens participants ----------------------------------------------------
CREATE OR REPLACE FUNCTION fn_a_participe(p_projet BIGINT, p_user BIGINT)
RETURNS BOOLEAN AS $$
  SELECT EXISTS (SELECT 1 FROM post WHERE projet_id = p_projet AND auteur_id = p_user AND supprime_le IS NULL)
      OR EXISTS (SELECT 1 FROM post_commentaire c JOIN post p ON p.id = c.post_id
                 WHERE p.projet_id = p_projet AND c.auteur_id = p_user AND c.supprime_le IS NULL)
      OR EXISTS (SELECT 1 FROM dailylog_entree WHERE projet_id = p_projet AND utilisateur_id = p_user)
      OR EXISTS (SELECT 1 FROM tache_intervenant ti JOIN tache t ON t.id = ti.tache_id
                 WHERE t.projet_id = p_projet AND ti.utilisateur_id = p_user)
      OR EXISTS (SELECT 1 FROM audit_log a
                 WHERE a.action = 'DELETE' AND a.table_cible = 'projet_co_chef'
                   AND (a.donnees_avant->>'projet_id')::BIGINT = p_projet
                   AND (a.donnees_avant->>'utilisateur_id')::BIGINT = p_user)
      OR EXISTS (SELECT 1 FROM audit_log a
                 WHERE a.action = 'UPDATE' AND a.table_cible = 'projet' AND a.ligne_id = p_projet
                   AND (a.donnees_avant->>'chef_projet_id')::BIGINT = p_user
                   AND a.donnees_apres->>'chef_projet_id' IS DISTINCT FROM a.donnees_avant->>'chef_projet_id')
$$ LANGUAGE sql STABLE;
COMMENT ON FUNCTION fn_a_participe(BIGINT, BIGINT) IS
  'A participé au projet (0027) : post ou commentaire non supprimé, heures, intervenant d''une tâche, ancien chef ou co-chef.';

CREATE OR REPLACE FUNCTION fn_garder_ancien_membre()
RETURNS TRIGGER AS $$
DECLARE
  v_projet BIGINT;
  v_user   BIGINT;
  v_toujours BOOLEAN := false;
BEGIN
  IF TG_TABLE_NAME = 'tache_intervenant' THEN
    SELECT projet_id INTO v_projet FROM tache WHERE id = OLD.tache_id;
    v_user := OLD.utilisateur_id;
  ELSIF TG_TABLE_NAME = 'projet' THEN
    IF NEW.chef_projet_id IS NOT DISTINCT FROM OLD.chef_projet_id THEN
      RETURN NULL;
    END IF;
    v_projet := OLD.id;
    v_user := OLD.chef_projet_id;
    v_toujours := true;
  ELSE
    v_projet := OLD.projet_id;
    v_user := OLD.utilisateur_id;
    -- Ancien co-chef : garde toujours la lecture (0027).
    v_toujours := TG_TABLE_NAME = 'projet_co_chef';
  END IF;
  -- Projet en cours de suppression (cascade) : rien à garder. 0027 :
  -- retiré sans avoir participé, rien non plus.
  IF v_projet IS NOT NULL AND v_user IS NOT NULL
     AND EXISTS (SELECT 1 FROM projet WHERE id = v_projet)
     AND (v_toujours OR fn_a_participe(v_projet, v_user)) THEN
    INSERT INTO projet_ancien_membre (projet_id, utilisateur_id)
    VALUES (v_projet, v_user)
    ON CONFLICT DO NOTHING;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Changement d'équipe : les projets de l'ancienne équipe où la personne a
-- participé restent lisibles (MX-02).
CREATE OR REPLACE FUNCTION fn_ancien_membre_changement_equipe()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO projet_ancien_membre (projet_id, utilisateur_id)
  SELECT p.id, NEW.id
  FROM projet p
  WHERE p.equipe_code = OLD.equipe_code
    AND fn_a_participe(p.id, NEW.id)
  ON CONFLICT DO NOTHING;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_ancien_membre_equipe ON utilisateur;
CREATE TRIGGER trg_ancien_membre_equipe AFTER UPDATE OF equipe_code ON utilisateur
  FOR EACH ROW
  WHEN (OLD.equipe_code IS DISTINCT FROM NEW.equipe_code AND OLD.equipe_code IS NOT NULL)
  EXECUTE FUNCTION fn_ancien_membre_changement_equipe();

-- Reprise : participants d'une équipe quittée (depuis le lot 21) et anciens
-- chefs remplacés hors de l'appli (MD-3) ; puis retrait des lignes de
-- personnes qui n'ont jamais participé.
INSERT INTO projet_ancien_membre (projet_id, utilisateur_id)
SELECT p.id, u.id
FROM projet p
JOIN utilisateur u ON u.equipe_code IS DISTINCT FROM p.equipe_code
WHERE u.role NOT IN ('client', 'rh', 'admin')
  AND (EXISTS (SELECT 1 FROM post po WHERE po.projet_id = p.id AND po.auteur_id = u.id AND po.supprime_le IS NULL)
       OR EXISTS (SELECT 1 FROM post_commentaire c JOIN post po ON po.id = c.post_id
                  WHERE po.projet_id = p.id AND c.auteur_id = u.id AND c.supprime_le IS NULL)
       OR EXISTS (SELECT 1 FROM dailylog_entree d WHERE d.projet_id = p.id AND d.utilisateur_id = u.id))
ON CONFLICT DO NOTHING;

INSERT INTO projet_ancien_membre (projet_id, utilisateur_id)
SELECT DISTINCT a.ligne_id, (a.donnees_avant->>'chef_projet_id')::BIGINT
FROM audit_log a
JOIN projet p ON p.id = a.ligne_id
JOIN utilisateur u ON u.id = (a.donnees_avant->>'chef_projet_id')::BIGINT
WHERE a.action = 'UPDATE' AND a.table_cible = 'projet'
  AND a.donnees_avant ? 'chef_projet_id'
  AND a.donnees_apres->>'chef_projet_id' IS DISTINCT FROM a.donnees_avant->>'chef_projet_id'
  AND u.role NOT IN ('client', 'rh')
ON CONFLICT DO NOTHING;

DELETE FROM projet_ancien_membre am
WHERE NOT fn_a_participe(am.projet_id, am.utilisateur_id);

-- 2. Chef de projet intervenant d'une tâche rouverte : co-chef (MX-01) -------
CREATE OR REPLACE FUNCTION fn_tache_rouverte_co_chef()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO projet_co_chef (projet_id, utilisateur_id)
  SELECT NEW.projet_id, ti.utilisateur_id
  FROM tache_intervenant ti
  JOIN utilisateur u ON u.id = ti.utilisateur_id
  JOIN projet p ON p.id = NEW.projet_id
  WHERE ti.tache_id = NEW.id
    AND u.role = 'chef_de_projet'
    AND u.actif
    AND p.chef_projet_id IS DISTINCT FROM u.id
  ON CONFLICT DO NOTHING;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_tache_rouverte_co_chef ON tache;
CREATE TRIGGER trg_tache_rouverte_co_chef AFTER UPDATE OF etat ON tache
  FOR EACH ROW
  WHEN (OLD.etat NOT IN ('en_cours', 'bloque') AND NEW.etat IN ('en_cours', 'bloque'))
  EXECUTE FUNCTION fn_tache_rouverte_co_chef();

-- 3. Tâche close : toujours une date de fin (NB7, SB-02, HD-09) --------------
CREATE OR REPLACE FUNCTION fn_tache_close_date_fin()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.etat NOT IN ('en_cours', 'bloque') AND NEW.date_fin IS NULL THEN
    NEW.date_fin := COALESCE((NEW.updated_at AT TIME ZONE 'Africa/Tunis')::date,
                             (NEW.created_at AT TIME ZONE 'Africa/Tunis')::date,
                             fn_date_ecriture());
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_tache_close_date_fin ON tache;
CREATE TRIGGER trg_tache_close_date_fin BEFORE INSERT OR UPDATE OF etat, date_fin ON tache
  FOR EACH ROW EXECUTE FUNCTION fn_tache_close_date_fin();

ALTER TABLE tache DISABLE TRIGGER trg_tache_updated_at;
UPDATE tache
SET date_fin = COALESCE((updated_at AT TIME ZONE 'Africa/Tunis')::date, (created_at AT TIME ZONE 'Africa/Tunis')::date)
WHERE etat NOT IN ('en_cours', 'bloque') AND date_fin IS NULL;
ALTER TABLE tache ENABLE TRIGGER trg_tache_updated_at;

-- 4. Filtres mémorisés : un objet (FI-07) -------------------------------------
UPDATE utilisateur_preference SET filtres = '{}'::jsonb WHERE jsonb_typeof(filtres) <> 'object';
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'utilisateur_preference_filtres_objet') THEN
    ALTER TABLE utilisateur_preference
      ADD CONSTRAINT utilisateur_preference_filtres_objet CHECK (jsonb_typeof(filtres) = 'object');
  END IF;
END $$;

-- 5. Notifications Windows (Web Push) -----------------------------------------
CREATE TABLE IF NOT EXISTS push_abonnement (
  id             BIGSERIAL PRIMARY KEY,
  utilisateur_id BIGINT NOT NULL REFERENCES utilisateur(id) ON DELETE CASCADE,
  endpoint       TEXT NOT NULL UNIQUE CHECK (length(endpoint) <= 1000 AND endpoint LIKE 'https://%'),
  cle_p256dh     TEXT NOT NULL CHECK (length(cle_p256dh) <= 200),
  cle_auth       TEXT NOT NULL CHECK (length(cle_auth) <= 100),
  navigateur     TEXT CHECK (length(navigateur) <= 200),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  vu_le          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_push_abonnement_user ON push_abonnement(utilisateur_id);
COMMENT ON TABLE push_abonnement IS
  'Abonnements Web Push (0027) : un par appareil et navigateur ; supprimé quand le service push répond 404 ou 410.';

ALTER TABLE utilisateur_preference ADD COLUMN IF NOT EXISTS push_categories TEXT[];
COMMENT ON COLUMN utilisateur_preference.push_categories IS
  'Catégories de notifications envoyées en push (0027) ; NULL = toutes.';

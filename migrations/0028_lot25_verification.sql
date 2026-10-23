-- 0028 — Lot 25 (vérification complète du 22-23/10/2026 après le lot 24 et
-- décisions du gérant du 23/10).
--
-- Rejouable : CREATE OR REPLACE, IF NOT EXISTS, DROP … IF EXISTS,
-- contraintes posées seulement si absentes.

SELECT set_config('lock_timeout', '15s', true);

-- 1. Notifications Windows ---------------------------------------------------
-- PU-10 : notification à pousser, retenue en base pour être reprise si le
-- worker s'arrête avant l'envoi (et jamais poussée deux fois).
ALTER TABLE notification ADD COLUMN IF NOT EXISTS push_attente BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_notification_push_attente ON notification(created_at) WHERE push_attente;
COMMENT ON COLUMN notification.push_attente IS
  'Notification Windows planifiée, pas encore envoyée (0028) : reprise au redémarrage d''un worker.';

-- PU-12 : clé VAPID publique du serveur au moment de l'abonnement.
ALTER TABLE push_abonnement ADD COLUMN IF NOT EXISTS cle_serveur TEXT;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'push_abonnement_cle_serveur_check') THEN
    ALTER TABLE push_abonnement ADD CONSTRAINT push_abonnement_cle_serveur_check CHECK (length(cle_serveur) <= 200);
  END IF;
END $$;
COMMENT ON COLUMN push_abonnement.cle_serveur IS
  'Clé VAPID publique du serveur lors de l''abonnement (0028) ; NULL = abonnement d''avant 0028.';

-- Décision du gérant du 23/10 (PU-05, PC partagé) : déconnexion, révocation
-- des sessions (déconnexion, désactivation), changement de mot de passe →
-- plus aucune notification Windows pour ce compte, sur aucun appareil
-- (la désactivation d'un compte révoque ses sessions : trigger 0013).
CREATE OR REPLACE FUNCTION fn_push_retirer_abonnements() RETURNS TRIGGER AS $$
BEGIN
  IF TG_TABLE_NAME = 'utilisateur' THEN
    DELETE FROM push_abonnement WHERE utilisateur_id = NEW.id;
  ELSE
    DELETE FROM push_abonnement WHERE utilisateur_id = NEW.utilisateur_id;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_push_session_revoquee ON utilisateur_session;
CREATE TRIGGER trg_push_session_revoquee
  AFTER INSERT OR UPDATE OF generation ON utilisateur_session
  FOR EACH ROW EXECUTE FUNCTION fn_push_retirer_abonnements();

DROP TRIGGER IF EXISTS trg_push_mot_de_passe ON utilisateur;
CREATE TRIGGER trg_push_mot_de_passe
  AFTER UPDATE OF mot_de_passe_hash ON utilisateur
  FOR EACH ROW WHEN (OLD.mot_de_passe_hash IS DISTINCT FROM NEW.mot_de_passe_hash)
  EXECUTE FUNCTION fn_push_retirer_abonnements();

-- 2. Mode test : jamais un objet daté avant ce qu'il suit -----------------
-- SB-03, SA-L25-05 (reste de HD-06) : sous une date simulée passée, un post
-- (y compris automatique : blocage, clôture) n'est jamais daté avant son
-- projet, sa tâche ou le post auquel il répond ; une réaction jamais avant
-- son post ; une tâche jamais avant son projet ni avant le dernier blocage
-- d'une tâche du projet (règle « une tâche créée APRÈS le blocage débloque
-- le projet » : l'ordre des gestes est gardé). Hors simulation
-- (fn_instant_simule() NULL) : rien ne change, imports compris.
CREATE OR REPLACE FUNCTION fn_jamais_avant_en_simulation() RETURNS TRIGGER AS $$
BEGIN
  IF fn_instant_simule() IS NULL THEN
    RETURN NEW;
  END IF;
  IF TG_TABLE_NAME = 'post' THEN
    NEW.created_at := GREATEST(NEW.created_at,
      (SELECT created_at FROM projet WHERE id = NEW.projet_id),
      (SELECT created_at FROM tache WHERE id = NEW.tache_id),
      (SELECT created_at FROM post WHERE id = NEW.parent_post_id));
  ELSIF TG_TABLE_NAME = 'post_reaction' THEN
    NEW.created_at := GREATEST(NEW.created_at, (SELECT created_at FROM post WHERE id = NEW.post_id));
  ELSIF TG_TABLE_NAME = 'tache' THEN
    NEW.created_at := GREATEST(NEW.created_at,
      (SELECT created_at FROM projet WHERE id = NEW.projet_id),
      (SELECT max(bloque_le) + interval '1 microsecond' FROM tache WHERE projet_id = NEW.projet_id AND etat = 'bloque'));
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_post_jamais_avant ON post;
CREATE TRIGGER trg_post_jamais_avant BEFORE INSERT ON post
  FOR EACH ROW EXECUTE FUNCTION fn_jamais_avant_en_simulation();
DROP TRIGGER IF EXISTS trg_reaction_jamais_avant ON post_reaction;
CREATE TRIGGER trg_reaction_jamais_avant BEFORE INSERT ON post_reaction
  FOR EACH ROW EXECUTE FUNCTION fn_jamais_avant_en_simulation();
DROP TRIGGER IF EXISTS trg_tache_jamais_avant ON tache;
CREATE TRIGGER trg_tache_jamais_avant BEFORE INSERT ON tache
  FOR EACH ROW EXECUTE FUNCTION fn_jamais_avant_en_simulation();

-- 3. Date de fin d'une tâche close (TA-09, SA-L25-04) --------------------
-- Clôture par un UPDATE (script) : la date du jour, et non l'ancienne date
-- de modification (le trigger passe avant trg_tache_updated_at) ; insertion
-- close sans date : jamais avant sa création.
CREATE OR REPLACE FUNCTION fn_tache_close_date_fin()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.etat NOT IN ('en_cours', 'bloque') AND NEW.date_fin IS NULL THEN
    IF TG_OP = 'UPDATE' AND OLD.etat IN ('en_cours', 'bloque') THEN
      NEW.date_fin := fn_date_ecriture();
    ELSE
      NEW.date_fin := COALESCE((GREATEST(NEW.updated_at, NEW.created_at) AT TIME ZONE 'Africa/Tunis')::date,
                               fn_date_ecriture());
    END IF;
  -- DL-05 : rouverte par script, la tâche perd sa date de fin (comme dans
  -- l'appli), sauf si la même requête en pose une autre.
  ELSIF TG_OP = 'UPDATE' AND NEW.etat IN ('en_cours', 'bloque') AND OLD.etat NOT IN ('en_cours', 'bloque')
        AND NEW.date_fin IS NOT DISTINCT FROM OLD.date_fin THEN
    NEW.date_fin := NULL;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 4. Chef de projet affecté à une tâche : co-chef seulement s'il est actif
--    (base-déploiement, observation du 23/10 ; comme fn_tache_rouverte_co_chef).
CREATE OR REPLACE FUNCTION fn_chef_intervenant_tache_co_chef()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO projet_co_chef (projet_id, utilisateur_id)
  SELECT t.projet_id, NEW.utilisateur_id
  FROM tache t
  JOIN projet p ON p.id = t.projet_id
  JOIN utilisateur u ON u.id = NEW.utilisateur_id
  WHERE t.id = NEW.tache_id
    AND u.role = 'chef_de_projet'
    AND u.actif
    AND p.chef_projet_id <> u.id
  ON CONFLICT DO NOTHING;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- 5. fn_a_participe : anciens co-chefs cherchés dans le journal par index
--    (revue sécurité C.2-2 : parcours de toutes les lignes projet_co_chef du
--    journal à chaque appel).
CREATE INDEX IF NOT EXISTS idx_audit_co_chef_retire ON audit_log (
  ((donnees_avant->>'projet_id')::BIGINT), ((donnees_avant->>'utilisateur_id')::BIGINT)
) WHERE action = 'DELETE' AND table_cible = 'projet_co_chef';

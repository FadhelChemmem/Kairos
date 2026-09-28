-- Lot 5 (retour Fadhel, 2026-09-28) : "répartition des heures par rôle
-- (8h intervenant/5h chef) affichée dans Informations/liste projets/
-- lignes de tâches" — voir le commentaire détaillé dans schema.sql,
-- juste au-dessus des vues créées ici. CREATE OR REPLACE VIEW : rejouable
-- sans erreur sur une base qui a déjà cette migration (comme les
-- précédentes).

CREATE OR REPLACE VIEW v_projet_heures_par_role AS
SELECT
  de.projet_id,
  SUM(CASE WHEN de.utilisateur_id = p.chef_projet_id
             OR EXISTS (SELECT 1 FROM projet_co_chef pc
                        WHERE pc.projet_id = de.projet_id AND pc.utilisateur_id = de.utilisateur_id)
           THEN de.heures ELSE 0 END) AS heures_chef,
  SUM(CASE WHEN de.utilisateur_id = p.chef_projet_id
             OR EXISTS (SELECT 1 FROM projet_co_chef pc
                        WHERE pc.projet_id = de.projet_id AND pc.utilisateur_id = de.utilisateur_id)
           THEN 0 ELSE de.heures END) AS heures_intervenant
FROM dailylog_entree de
JOIN projet p ON p.id = de.projet_id
GROUP BY de.projet_id;

CREATE OR REPLACE VIEW v_tache_heures_par_role AS
SELECT
  de.tache_id,
  SUM(CASE WHEN de.utilisateur_id = p.chef_projet_id
             OR EXISTS (SELECT 1 FROM projet_co_chef pc
                        WHERE pc.projet_id = t.projet_id AND pc.utilisateur_id = de.utilisateur_id)
           THEN de.heures ELSE 0 END) AS heures_chef,
  SUM(CASE WHEN de.utilisateur_id = p.chef_projet_id
             OR EXISTS (SELECT 1 FROM projet_co_chef pc
                        WHERE pc.projet_id = t.projet_id AND pc.utilisateur_id = de.utilisateur_id)
           THEN 0 ELSE de.heures END) AS heures_intervenant
FROM dailylog_entree de
JOIN tache t ON t.id = de.tache_id
JOIN projet p ON p.id = t.projet_id
WHERE de.tache_id IS NOT NULL
GROUP BY de.tache_id;

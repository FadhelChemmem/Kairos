-- Empreinte du schéma indépendante de l'ordre des colonnes et de NOT VALID.
-- Lot 20 (revue QA n° 17a) : commentaires (COMMENT ON) des tables, vues,
-- colonnes et fonctions compris.
SELECT 'col' AS k, table_name || '.' || column_name || ' ' || data_type || ' ' || is_nullable || ' ' || coalesce(column_default, '') AS v
FROM information_schema.columns WHERE table_schema = 'public'
UNION ALL
SELECT 'con', conrelid::regclass || ' ' || conname || ' ' || replace(pg_get_constraintdef(oid), ' NOT VALID', '')
FROM pg_constraint WHERE connamespace = 'public'::regnamespace
UNION ALL
SELECT 'idx', indexdef FROM pg_indexes WHERE schemaname = 'public'
UNION ALL
SELECT 'trg', tgrelid::regclass || ' ' || pg_get_triggerdef(oid) FROM pg_trigger WHERE NOT tgisinternal
UNION ALL
SELECT 'fn', p.proname || ' ' || md5(pg_get_functiondef(p.oid)) FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace
UNION ALL
SELECT 'vue', viewname || ' ' || md5(definition) FROM pg_views WHERE schemaname = 'public'
UNION ALL
SELECT 'enum', t.typname || ' ' || string_agg(e.enumlabel, ',' ORDER BY e.enumsortorder)
FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid GROUP BY t.typname
UNION ALL
SELECT 'cmt', c.relname || ' ' || md5(d.description)
FROM pg_class c JOIN pg_description d ON d.objoid = c.oid AND d.classoid = 'pg_class'::regclass AND d.objsubid = 0
WHERE c.relnamespace = 'public'::regnamespace
UNION ALL
SELECT 'cmt', c.relname || '.' || a.attname || ' ' || md5(d.description)
FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid
JOIN pg_description d ON d.objoid = c.oid AND d.classoid = 'pg_class'::regclass AND d.objsubid = a.attnum
WHERE c.relnamespace = 'public'::regnamespace
UNION ALL
SELECT 'cmt', p.proname || '() ' || md5(d.description)
FROM pg_proc p JOIN pg_description d ON d.objoid = p.oid AND d.classoid = 'pg_proc'::regclass
WHERE p.pronamespace = 'public'::regnamespace
ORDER BY 1, 2;

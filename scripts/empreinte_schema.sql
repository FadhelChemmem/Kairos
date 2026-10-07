-- Empreinte du schéma indépendante de l'ordre des colonnes et de NOT VALID.
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
ORDER BY 1, 2;

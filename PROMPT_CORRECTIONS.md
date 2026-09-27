# Prompt: fix the bugs found in Kairos

Copy everything below the line and give it to the AI that will make the fixes.

---

You are working on **Kairos**: Flask + PostgreSQL (raw SQL through psycopg2, no ORM) + Jinja2, deployed with Docker Compose. A code review found the bugs listed below. Every one was confirmed by reading the code, and several were reproduced against a real PostgreSQL 16 database.

## Working rules
1. Fix the bugs **in the priority order below** (P0 → P3). Make one commit per group, with a clear message.
2. **Don't break anything:** run `python -m unittest discover -s tests -v` after each group. All 113 tests must stay green. Add a test for each fixed bug when that's reasonable. Note that `tests/test_smoke.py` stubs out psycopg2 and patches the repositories.
3. Match the existing style: raw SQL, parameterized queries (`%s`), user-facing messages in French, code comments like the existing ones.
4. Any schema change goes in a **new migration** `migrations/0004_*.sql`, which must be idempotent (`IF NOT EXISTS`, etc.), **and** in `schema.sql` so the two stay in sync.
5. Line numbers are approximate. Search for the function names given.
6. Don't change the visual design or the features. Only fix the bugs.

---

## P0 — Critical security (fix first)

### 1. Project access checks missing (IDOR)
Visibility is filtered only in the lists (`v_projet_visibilite`, used in `app/repositories/projets.py`). Any logged-in user who knows an ID can see or change anything.
- Add a helper `projets.user_can_view(projet_id, user_id)` based on `v_projet_visibilite`. If the check fails, return **404**.
- Apply it in:
  - `app/routes/projets.py`: `detail` (~l.90), `nouveau_post` (~l.121), `creer_tache` (~l.151).
  - `app/routes/fichiers.py`:
    - `download_tache` (~l.34) and `download_post` (~l.60): resolve attachment → task/post → project, then check visibility. Right now `/fichiers/taches/1..N` downloads every document in the company.
    - `upload_tache` (~l.20) and `upload_post` (~l.46): check that the task/post exists and is visible **before** `save_upload`. Today the file is written to disk first, and if the INSERT then fails it is left orphaned.
  - `app/routes/posts.py`: `creer` (~l.27) for `projet_id`; `reagir`, `retirer_reaction`, `commenter` (~l.80-116) for the post's project.
  - `parent_post_id` in `posts.creer` and `projets.creer_tache`: the parent must belong to the **same project**. Otherwise the feed shows another project's `parent.contenu`, which leaks data.
  - `mentions` / `mentionne_user_id`: only accept existing users who can see the project.

### 2. Anyone can change or close any task
`app/routes/projets.py` `changer_etat_tache` (~l.191) and `cloturer_tache` (~l.207). In `app/repositories/taches.py`, `set_etat` (~l.153) and `close_tache` (~l.184) update with `WHERE id = %s` only.
- Require `user_can_manage` (chef / co-chef), or that the user is an intervenant on the task, depending on the business rule already used elsewhere.
- Add `AND projet_id = %s` to the UPDATEs, and return 404 if no row was updated.
- `close_tache`: add `AND etat <> 'termine'` so a task can't be closed twice (which currently creates a duplicate closing post).
- Check `etat` and `type_code` against the allowed values. A bad `type_code` currently hits a foreign-key error → 500.
- If the task doesn't exist, show a flash message, not a `ValueError` → 500.

### 3. Password-reset link poisoning (account takeover)
`app/auth.py` ~l.130 builds the link with `url_for(..., _external=True)`, which uses the request's `Host` header. An attacker who sends `Host: evil.tld` makes the admin receive a genuine email whose link points to their own site.
- Add an `APP_BASE_URL` setting (`.env.example`, `app/config.py`, `docker-compose.yml`) and build the link from it, **or** set `SERVER_NAME`.
- **Consume the token atomically:** `UPDATE ... SET mot_de_passe_hash=..., reset_token_hash=NULL WHERE id=%s AND reset_token_hash=%s AND reset_token_expires_at > now()` and check `rowcount`. Today two concurrent requests can use the same token.

### 4. Stored XSS through `innerHTML`
- `app/templates/dailylog.html`, in `render()` (~l.249) and the suggestions list (~l.354): `l.nom`, `l.tacheTitre`, `item.nom` and `item.tache_titre` are inserted as raw HTML. A project named `<img src=x onerror=...>` runs code for **every** user, admins included, because the "other projects" suggestions list is company-wide.
- `app/templates/base.html` ~l.79: top-bar search, `it.label` and `it.url` inserted through `innerHTML`.
- Fix: build these elements with `createElement` + `textContent`, or add an `escapeHtml()` helper and apply it to every dynamic value.
- `app/templates/partials/post_card.html` ~l.44: `href="{{ post.lien }}"` accepts `javascript:...`. In `app/routes/posts.py` (`creer`), allow only `http://`, `https://`, `file:`, `smb:` and UNC paths `\\...`, and check again when rendering.

### 5. Open redirects
- `app/auth.py` ~l.183: `redirect(request.args.get("next"))` is not validated.
- `_safe_redirect` in `app/routes/posts.py` ~l.20 and `app/routes/fichiers.py` ~l.13 accepts `//evil.tld` and `/\evil.tld`.
- Write one shared `is_safe_next(url)` in `app/utils.py`: the URL must start with a single `/`, must not start with `//` or `/\`, and `urlparse` must return no scheme and no netloc.

### 6. Secrets and exposure
- `app/config.py` ~l.11: remove the `"dev-secret-key-change-me"` fallback. Refuse to start when `SECRET_KEY` is missing, is shorter than 32 characters, or is a known placeholder (`change-moi-aussi`, etc.). A known key lets anyone forge a session as admin.
- `docker-compose.yml` ~l.21: `"5432:5432"` exposes Postgres to the whole network. Change it to `"127.0.0.1:5432:5432"` or remove the mapping.
- **Add a `.dockerignore`** (none exists). `COPY . .` currently puts `.env`, `backups/*.sql.gz` (full dumps), `migration_sorties/` (plaintext temporary passwords), `.git`, `uploads/`, `chronos_*.sql`, `tests/` and `__pycache__` into the image.

---

## P1 — Major functional bugs

### 7. DailyLog: slider drag is broken
`app/templates/dailylog.html`, `pctFromEvent` / `startDragThumb` (~l.274-300). During a drag, `redistribute()` calls `render()`, which rebuilds the whole list. The `track` held by the closure is no longer on the page, so `getBoundingClientRect().width === 0`, `x/0 = Infinity`, and the value jumps to 100%.
- Fix: store `rect` once on `pointerdown` and reuse it, **or** update only the fill and thumb styles during the drag and call `render()` once on `pointerup`.

### 8. DailyLog: a long press never stops
`attachTapAndHold` (~l.190). After the first `onHold()`, the element is re-rendered and removed from the page, so its `pointerup`/`pointerleave` never fire and `setInterval(onHold, 450)` runs forever. On "Autres projets" rows this keeps adding duplicate lines.
- Fix: listen for `pointerup` / `pointercancel` on `document` (or use `setPointerCapture`), keep track of active timers, and clear them all at the start of `render()`. `addLine` must refuse duplicates.

### 9. The "task finished" marker disappears
`app/repositories/posts.py` ~l.11: `est_cloture_tache` relies on `p.created_at = t.updated_at`, but the trigger `trg_tache_updated_at` (`schema.sql` ~l.326) rewrites `updated_at` on **every** UPDATE. For example, close then set to "vérifié", and the closing post becomes an ordinary post.
- Fix: add a column `post.evenement VARCHAR(20) CHECK (evenement IN ('creation_tache','cloture_tache'))` in migration 0004 + `schema.sql`, set it in `create_tache` / `close_tache`, and read it in the queries. Backfill existing data as well as possible.
- Also reset `date_fin` to NULL when a task leaves the `termine` state.

### 10. DailyLog: unvalidated input and inconsistent data
`app/routes/dailylog.py` `enregistrer` (~l.99) and `app/repositories/dailylog.py` `remplacer_jour` (~l.183):
- Validate `date` (valid ISO format, **not in the future**). Currently `date=foo` → 500.
- Reject non-numeric ids and hours outside 0–24. The column is `NUMERIC(4,2)`, so ≥ 100 → 500.
- Check that `tache_id` belongs to `projet_id`. Otherwise `v_tache_heures` and `v_projet_heures` diverge. Ideally also add a composite FK: `UNIQUE (id, projet_id)` on `tache` + `FOREIGN KEY (tache_id, projet_id) REFERENCES tache(id, projet_id)` on `dailylog_entree` (migration 0004).
- Check that the project is visible to the user.
- `list_lignes_suggerees` (~l.79): don't expose projects the user can't see.

### 11. Other 500s that should be flash messages
- `app/routes/projets.py` `creer_tache`: invalid `type_deadline`, malformed `date_echeance`, or an RH user in `intervenants` (DB trigger).
- `app/routes/utilisateurs.py` `toggle_actif` (~l.347): reactivating a second RH account violates `idx_utilisateur_rh_singleton`. Catch `UniqueViolation` and show a clear message.
- `utilisateurs.creer` (~l.91): the user is inserted as `actif=true` and then toggled off in a second transaction. Pass `actif` directly into the `create_utilisateur` INSERT.
- `utilisateurs.fiche` (~l.251): check the submitted role against `ROLES_CREABLES`.

### 12. User edit page silently changes team and role
`app/templates/utilisateur_fiche.html` ~l.57: the `equipe_code` `<select>` has no empty option, so a user with no team gets the first team saved on any edit, which changes their project visibility. Same for `role`: a `client` user has no matching option and becomes `intervenant`.
- Add `<option value="">—</option>`, add the missing role options, and convert `""` → NULL on the server side.

### 13. Migration script `scripts/migrate_from_chronos.py`
- ~l.145: remove `.replace("\\", "\\\\")`. With `standard_conforming_strings=on`, it doubles every backslash (`C:\docs` → `C:\\docs`). Only double `'`.
- `mysql_dt_to_pg` (~l.158): convert `0000-00-00…` to NULL (or `now()` when the column is NOT NULL).
- `projet_lot`: ignore lot codes that don't exist in the reference data (only `CM`, `GO`) and list them in the report.
- Fix the documented command (~l.35 and ~l.675). It must be: `docker compose exec -T db psql -v ON_ERROR_STOP=1 -U kairos -d kairos < migration_sorties/.../migration.sql`. Without `ON_ERROR_STOP` the migration can roll back silently and still exit with code 0.
- Write the credentials CSV with `os.umask(0o077)` (mode 0600).

### 14. `scripts/mysqldump_parser.py` ~l.123
The regex doesn't handle `INSERT INTO \`t\` (\`col\`, ...) VALUES` (dumps made with `--complete-insert`), so tables come out silently empty. Accept an optional column list and **fail loudly** if a table has INSERTs but no parsed rows.

### 15. `scripts/backup_db.sh`
- Write to a `.tmp` file, check it with `gzip -t`, then `mv`. Add `trap 'rm -f "$TMP"' ERR`. Today a failed dump leaves a 20-byte `.sql.gz` that pushes good backups out of the 30-file rotation.
- Don't `source .env`: it crashes on `SMTP_FROM=Kairos <noreply@x.tn>`. Read only `POSTGRES_USER`/`POSTGRES_DB` with `grep`.
- `umask 077`: dumps contain password hashes.
- Also back up the `kairos_uploads` volume (attachments and avatars), e.g. with `docker run --rm -v kairos_uploads:/u -v "$PWD/backups":/b alpine tar czf ...`.

---

## P2 — Medium bugs
16. **Timezone:** everything is computed in UTC (`date.today()`, `CURRENT_DATE`). Between 00:00 and 01:00 in Tunisia, "today" is still yesterday. Add `TZ=Africa/Tunis` to the `web` service and `PGTZ`/`TZ` to `db` in `docker-compose.yml`, or use `zoneinfo`.
17. **Sessions are not invalidated** after a password change. Store a `session_version` (or a password-hash fingerprint) in the session and check it in `load_logged_in_user` (`app/auth.py`). Add the column in migration 0004 if needed.
18. **CI:** `.github/workflows/tests.yml` ~l.9 uses `branches: [main]`, but the default branch is **`master`**, so pushes never trigger CI. Also add a `postgres:16` service job that applies `schema.sql` + `migrations/*.sql` to catch real SQL errors.
19. **Dependencies** (`requirements.txt`): Flask 3.0.3 → ≥ 3.1.3, gunicorn 22.0.0 → ≥ 23.0.0 (CVE-2024-6827, request smuggling), python-dotenv → ≥ 1.2.2. Pin Werkzeug and Jinja2.
20. **Reactions can't be removed:** in `app/templates/partials/post_card.html` ~l.78 the form always posts to `posts.reagir`. When `post.ma_reaction` is set, point it at `posts.retirer_reaction`.
21. **Non-ASCII filenames lose their extension** (`app/storage.py` ~l.29): `secure_filename("مخطط.pdf")` → `"pdf"`. Take the extension from the raw name (lowercased, checked against an allowlist) and keep the original name for display.
22. **Proposed project code** (`app/templates/projet_creer.html` + `app/repositories/projets.py` `propose_code` ~l.208): the code doesn't update when the phase changes. The text sort breaks after 999 (use `max()` over the digits extracted with a regex). `phase` isn't validated.
23. **Deadlines** (`app/repositories/taches.py` `list_deadlines` ~l.84): exclude tasks from projects in `termine`/`abandonne` (`AND p.etat IN ('en_cours','bloque')`).
24. **Login lockout DoS:** 5 attempts per email only, so anyone can lock the admin out repeatedly. Add a per-IP limit, and run a dummy `check_password_hash` when the email doesn't exist so timing doesn't reveal which accounts exist.
25. **CSRF:** there are no tokens. Add `Flask-WTF` `CSRFProtect` (with `{{ csrf_token() }}` in every POST form and the header for `fetch` calls), and make `/deconnexion` a POST.

## P3 — Minor
26. The "+ Nouveau post" button on the home page (`accueil.html`) and the "+ Tâche" button (`post_card.html`) offer projects where the user can't create a task. Filter to chef / co-chef.
27. The "Utilisateurs" link in `base.html` ~l.42 only shows for `admin`/`rh`, but the route also allows `chef_de_projet`.
28. The DailyLog reminder on Mondays checks Sunday. It should check the last working day.
29. `list_feed_mes_projets` / `list_mes_projets` ignore `tache_intervenant`, and `list_projets_pour_dailylog` ignores `projet_intervenant`. Align them with `v_projet_visibilite`.
30. `app/db.py`: after a Postgres restart, the pool returns dead connections. Wrap `conn.rollback()` in try/except and call `putconn(conn, close=True)` if `conn.closed`.
31. Business decision to confirm: RH can currently create `admin` accounts and change admin passwords and emails, so RH is effectively admin. Ask before changing this.
32. `docker-compose.yml`: add a healthcheck to `web` and remove the obsolete `version: "3.9"`.

---

## Expected at the end
- All tests green, plus new tests for P0 and P1 (permissions, redirects, date validation, backslash handling in the migration script, dump parser).
- `migrations/0004_*.sql` created and `schema.sql` kept in sync.
- A short summary of what was fixed, what wasn't (and why), and anything that needs manual action in production (applying migration 0004, generating a new `SECRET_KEY`, checking whether the production database has the columns `post.lien`, `post_mention` and `projet.equipe_code`, and the RH triggers, which no migration creates).

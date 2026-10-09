/* Scénario Playwright de bout en bout du lot 12 : « Voir comme »,
 * « Agir comme » et date simulée (mode test), liens vers les tâches,
 * Deadlines de l'Admin.
 *
 * Lancement : KAIROS_E2E_SCENARIO=modes bash tests_e2e/lancer.sh [dossier_captures]
 * (base jetable + tests_e2e/seed_modes.py + serveur Flask avec
 * KAIROS_MODE_TEST=true). Variables : KAIROS_E2E_URL, KAIROS_E2E_DB,
 * KAIROS_E2E_CAPTURES (facultatif), PLAYWRIGHT_MODULE.
 *
 * Vérifie l'écran ET la base : sélecteur (recherche, clavier, ni Admin ni
 * compte inactif), voir comme une intervenante (menus, Mes tâches et
 * Deadlines qui ouvrent la fenêtre de la tâche, refus d'écriture — Daily
 * log, API keepalive, formulaire —, bandeau role=status, retour au
 * compte, journal d'audit), agir comme (post et ligne de Daily log au nom
 * de l'intervenante, Admin réel dans le journal), date simulée (Daily log
 * à J+3, fenêtre de 14 jours décalée, retard des échéances, retour à
 * aujourd'hui), vue Admin des Deadlines, 1280 / 375 px, clair / sombre,
 * contraste du bandeau, aucune erreur JavaScript.
 */
'use strict';
const { execFileSync } = require('child_process');
const path = require('path');
let playwright;
try { playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright'); }
catch (e) { playwright = require('/home/claude/.npm-global/lib/node_modules/playwright'); }
const { chromium } = playwright;

const BASE = process.env.KAIROS_E2E_URL || 'http://127.0.0.1:8798';
const DB = process.env.KAIROS_E2E_DB || 'kairos_e2e_modes';
const CAPTURES = process.env.KAIROS_E2E_CAPTURES || '';
const MDP = 'Kairos2026!';
const RIM = 3, ADMIN = 1;

let ok = 0, ko = 0;
const erreursJs = [];
function etape(nom, cond, detail) {
  if (cond) { ok++; console.log('OK  ' + nom); }
  else { ko++; console.log('KO  ' + nom + (detail !== undefined ? ' — ' + JSON.stringify(detail) : '')); }
}
function sql(requete) {
  return execFileSync('psql', ['-X', '-At', '-d', DB, '-c', requete], { encoding: 'utf8' }).trim();
}
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
async function attendre(fn, delai = 5000) {
  const fin = Date.now() + delai;
  for (;;) { const v = await fn(); if (v) return v; if (Date.now() > fin) return v; await pause(100); }
}
function isoTunis(decalage) {
  const d = new Date(Date.now() + (decalage || 0) * 86400000);
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Tunis' }).format(d);
}
const T = isoTunis(0);
const heures = (uid, date) => sql(`SELECT coalesce(sum(heures),0) FROM dailylog_entree WHERE utilisateur_id=${uid} AND date='${date}'`);

async function contexte(navigateur, email, opts = {}) {
  const ctx = await navigateur.newContext({ viewport: { width: opts.largeur || 1280, height: opts.hauteur || 900 },
    colorScheme: opts.theme || 'light' });
  await ctx.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  const p = await ctx.newPage();
  await p.goto(BASE + '/connexion');
  await p.fill('#email', email);
  await p.fill('#password', MDP);
  await Promise.all([p.waitForNavigation(), p.click('button[type=submit]')]);
  await p.close();
  return ctx;
}
async function ouvrir(ctx, chemin) {
  const p = await ctx.newPage();
  p.on('pageerror', (e) => erreursJs.push(e.message));
  // Les 403 du mode lecture seule sont attendus (journal réseau du navigateur).
  p.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|net::/.test(m.text())) erreursJs.push(m.text()); });
  p.on('dialog', (d) => d.accept());
  await p.goto(BASE + chemin);
  return p;
}
async function capture(p, nom) { if (CAPTURES) await p.screenshot({ path: path.join(CAPTURES, nom), fullPage: false }); }
const debordement = (p) => p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const texteBandeau = (p) => p.evaluate(() => {
  const b = document.getElementById('bandeau-admin');
  return b ? b.innerText.replace(/\s+/g, ' ').trim() : '';
});
const actif = (p) => p.evaluate(() => {
  const a = document.activeElement;
  return { tag: a.tagName, id: a.id, cls: a.className, texte: (a.textContent || a.value || '').trim().slice(0, 60) };
});
/** POST de formulaire depuis la page (jeton CSRF ajouté par base.html). */
async function poster(p, url, champs) {
  return p.evaluate(async ({ url, champs }) => {
    const fd = new FormData();
    Object.keys(champs).forEach((k) => fd.append(k, champs[k]));
    const r = await fetch(url, { method: 'POST', body: fd, credentials: 'same-origin' });
    return { status: r.status, url: r.url };
  }, { url, champs });
}
async function entrer(p, cible, mode) {
  return poster(p, mode === 'agir' ? '/admin/agir-comme' : '/admin/voir-comme', { utilisateur_id: String(cible) });
}
async function pretDailyLog(p) {
  await p.waitForFunction(() => window.KairosDailyLogPage && !window.KairosDailyLogPage.etat().chargement, null, { timeout: 8000 });
}
/** Contraste texte / fond d'un élément (fond opaque le plus proche). */
const contraste = (p, selecteur) => p.evaluate((sel) => {
  function rgb(c) { const m = c.match(/rgba?\(([^)]+)\)/); const v = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return { r: v[0], g: v[1], b: v[2], a: v.length > 3 ? v[3] : 1 }; }
  function lum(c) { const f = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); }
  const el = document.querySelector(sel);
  let e = el, fond = null;
  while (e && !fond) { const c = rgb(getComputedStyle(e).backgroundColor); if (c.a >= 1) fond = c; e = e.parentElement; }
  const t = rgb(getComputedStyle(el).color);
  const [a, b] = [lum(t), lum(fond || { r: 255, g: 255, b: 255 })].sort((x, y) => y - x);
  return Math.round(((a + 0.05) / (b + 0.05)) * 100) / 100;
}, selecteur);

(async () => {
  const navigateur = await chromium.launch();
  try {
    // --- 1. Sélecteur « Voir Kairos comme… » ------------------------------
    const adm = await contexte(navigateur, 'admin@x.tn');
    let p = await ouvrir(adm, '/utilisateurs');
    await p.click('a:has-text("Voir Kairos comme…")');
    await p.waitForURL(/\/admin\/voir-comme$/);
    const champ = p.locator('#voir-comme-compte ~ .search-combobox-wrap .search-combobox-input');
    etape('bandeau « Mode test » pour l’Admin (KAIROS_MODE_TEST=true)', /^mode test/i.test(await texteBandeau(p)), await texteBandeau(p));
    await champ.focus();
    await p.keyboard.type('i');
    const noms = await p.$$eval('#voir-comme-compte ~ .search-combobox-wrap [role=option] .search-combobox-nom', (els) => els.map((e) => e.textContent.trim()));
    etape('liste : comptes actifs non admin seulement', noms.includes('Rim Inter — Intervenant') && noms.includes('Rania RH — RH')
      && !noms.some((n) => /Admin|Ancien/.test(n)), noms);
    await p.keyboard.type('nter');
    await capture(p, 'e2e-12-selecteur.png');
    await p.keyboard.press('Enter');
    etape('Entrée choisit « Rim Inter »', await p.inputValue('#voir-comme-compte') === String(RIM));
    etape('« Agir comme (mode test) » proposé', await p.locator('button:has-text("Agir comme (mode test)")').count() === 1);
    await p.locator('button:has-text("Voir comme")').first().focus();
    await Promise.all([p.waitForNavigation(), p.keyboard.press('Enter')]);

    // --- 2. Voir comme l'intervenante -------------------------------------
    etape('arrivée sur l’accueil', new URL(p.url()).pathname === '/accueil');
    const bandeau = p.locator('#bandeau-admin');
    etape('bandeau orange role=status', await bandeau.getAttribute('role') === 'status'
      && (await bandeau.getAttribute('class')).includes('bandeau-admin-voir'));
    etape('texte du bandeau', (await texteBandeau(p)).startsWith('Vous voyez Kairos comme Rim Inter (Intervenant) — Revenir à mon compte'), await texteBandeau(p));
    etape('menus de l’intervenante (ni Utilisateurs ni Journal)', await p.locator('nav.topbar-actions a[aria-label="Utilisateurs"]').count() === 0
      && await p.locator('nav.topbar-actions a[aria-label="Journal d\'audit"]').count() === 0
      && await p.locator('nav.topbar-actions a[aria-label="Daily log"]').count() === 1);
    etape('onglet du navigateur', (await p.title()).startsWith('[Vu comme Rim Inter]'), await p.title());
    const ctr = await contraste(p, '#bandeau-admin .bandeau-admin-ligne span');
    etape('contraste du bandeau ≥ 4,5:1', ctr >= 4.5, ctr);
    await capture(p, 'e2e-12-voir-comme.png');
    // Mes tâches -> fenêtre de la tâche.
    const lienTache = p.locator('a[href="/projets/1?tache=1"]').first();
    etape('Mes tâches : lien vers la fenêtre de la tâche', await lienTache.count() === 1);
    await Promise.all([p.waitForNavigation(), lienTache.click()]);
    await p.waitForSelector('#dialog-tache [data-tache-fenetre="1"]');
    etape('fiche projet : fenêtre de la tâche ouverte', await p.evaluate(() => document.getElementById('dialog-tache').open));
    // Deadlines -> fenêtre de la tâche.
    await p.goto(BASE + '/deadlines');
    const barre = p.locator('a.g-bar[href="/projets/1?tache=2"]');
    etape('Deadlines : barre vers la fenêtre de la tâche', await barre.count() === 1
      && (await barre.getAttribute('aria-label')).endsWith('— ouvrir la tâche'));
    etape('Deadlines : pas de bascule Admin', await p.locator('.bascule-vue').count() === 0);
    await Promise.all([p.waitForNavigation(), barre.click()]);
    await p.waitForSelector('#dialog-tache [data-tache-fenetre="2"]');
    etape('Deadlines → fenêtre de la tâche 2', await p.evaluate(() => document.getElementById('dialog-tache').open));
    // Projet d'une autre équipe : invisible, comme pour elle.
    const r404 = await p.goto(BASE + '/projets/2');
    etape('projet URBS : 404 comme pour l’intervenante', r404.status() === 404);
    // Refus d'écriture : Daily log (bouton), API keepalive, formulaire.
    const avantDl = sql('SELECT count(*) FROM dailylog_entree') + '/' + sql('SELECT count(*) FROM dailylog_jour');
    p = await ouvrir(adm, '/dailylog');
    await pretDailyLog(p);
    await p.click('#dl-liste .dl-row[data-cle="1:0"] .dl-plus');
    await p.click('#dl-enregistrer');
    await attendre(async () => /lecture seule/.test(await p.textContent('#dl-toast')));
    etape('Daily log : refus affiché (lecture seule)', /Vous voyez Kairos comme Rim Inter : lecture seule/.test(await p.textContent('#dl-toast')),
      await p.textContent('#dl-toast'));
    const keep = await p.evaluate(async (jour) => {
      const r = await fetch('/dailylog/api/jour/' + jour, { method: 'PUT', keepalive: true, credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ version: 0, lignes: [{ projet_id: 1, tache_id: null, minutes: 60 }] }) });
      return { status: r.status, corps: await r.json() };
    }, T);
    etape('API keepalive : 403 JSON lecture_seule', keep.status === 403 && keep.corps.erreur === 'lecture_seule', keep);
    etape('rien en base (Daily log)', sql('SELECT count(*) FROM dailylog_entree') + '/' + sql('SELECT count(*) FROM dailylog_jour') === avantDl);
    p = await ouvrir(adm, '/notifications');
    const nonLues = sql(`SELECT count(*) FROM notification WHERE utilisateur_id=${RIM} AND NOT lu`);
    await Promise.all([p.waitForNavigation(), p.click('button:has-text("Tout marquer comme lu")')]);
    etape('formulaire : page 403 « Lecture seule »', (await p.textContent('h1')).trim() === 'Lecture seule'
      && /Erreur 403/.test(await p.textContent('main')));
    etape('notifications toujours non lues', sql(`SELECT count(*) FROM notification WHERE utilisateur_id=${RIM} AND NOT lu`) === nonLues && nonLues !== '0');
    etape('aucun rappel Daily log créé pour l’intervenante', sql(`SELECT count(*) FROM notification WHERE utilisateur_id=${RIM} AND rappel_jours IS NOT NULL`) === '0');
    // Revenir à mon compte (clavier).
    await p.locator('#bandeau-admin button:has-text("Revenir à mon compte")').focus();
    await Promise.all([p.waitForNavigation(), p.keyboard.press('Enter')]);
    etape('retour au compte de l’Admin', /^mode test/i.test(await texteBandeau(p))
      && await p.locator('nav.topbar-actions a[aria-label="Journal d\'audit"]').count() === 1, await texteBandeau(p));
    etape('journal : entrée et sortie (Admin réel, compte vu)',
      sql("SELECT string_agg(action || ':' || utilisateur_id || ':' || ligne_id, ',' ORDER BY id) FROM audit_log WHERE table_cible='mode_voir_comme'")
        === `ENTREE:${ADMIN}:${RIM},SORTIE:${ADMIN}:${RIM}`);

    // --- 3. Agir comme (mode test) ----------------------------------------
    p = await ouvrir(adm, '/admin/voir-comme');
    await p.locator('#voir-comme-compte ~ .search-combobox-wrap .search-combobox-input').fill('rim');
    await p.keyboard.press('Enter');
    await Promise.all([p.waitForNavigation(), p.click('button:has-text("Agir comme (mode test)")')]);
    etape('bandeau rouge « Vous agissez comme … (mode test) »',
      (await texteBandeau(p)).startsWith('Vous agissez comme Rim Inter (Intervenant) (mode test) — Revenir à mon compte')
      && (await p.getAttribute('#bandeau-admin', 'class')).includes('bandeau-admin-agir'), await texteBandeau(p));
    await capture(p, 'e2e-12-agir-comme.png');
    // Post au nom de l'intervenante.
    p = await ouvrir(adm, '/projets/1');
    await p.click('button[data-open-post-dialog]:has-text("Nouveau post")');
    await p.waitForSelector('#dialog-contenu-information', { state: 'visible' });
    await p.fill('#dialog-contenu-information', 'Post e2e au nom de Rim');
    await Promise.all([p.waitForNavigation(), p.click('button:has-text("Publier l\'information")')]);
    const post = sql("SELECT id || ':' || auteur_id FROM post WHERE contenu = 'Post e2e au nom de Rim'");
    etape('post créé au nom de l’intervenante', post.endsWith(':' + RIM), post);
    etape('journal : post (auteur Rim, Admin réel)', sql(`SELECT utilisateur_id || ':' || admin_reel_id FROM audit_log WHERE table_cible='post' AND action='INSERT' AND ligne_id=${post.split(':')[0]}`) === `${RIM}:${ADMIN}`);
    // Ligne de Daily log au nom de l'intervenante.
    p = await ouvrir(adm, '/dailylog');
    await pretDailyLog(p);
    await p.click('#dl-liste .dl-row[data-cle="1:0"] .dl-plus');
    await p.click('#dl-enregistrer');
    await attendre(async () => (await p.textContent('#dl-status-texte')) === 'Enregistré');
    etape('Daily log enregistré au nom de l’intervenante', heures(RIM, T) === '0.50'
      && sql(`SELECT updated_by FROM dailylog_entree WHERE utilisateur_id=${RIM} AND date='${T}'`) === String(RIM), heures(RIM, T));
    etape('journal : Daily log (auteur Rim, Admin réel)',
      sql(`SELECT count(*) FROM audit_log WHERE table_cible LIKE 'dailylog%' AND utilisateur_id=${RIM} AND admin_reel_id=${ADMIN}`) === '2');
    await p.locator('#bandeau-admin button:has-text("Revenir à mon compte")').click();
    await p.waitForURL(/\/dailylog/);
    p = await ouvrir(adm, '/admin/journal?table=post');
    etape('Journal d’audit : « Rim Inter (par l’Admin Fadhel Admin) »', /Rim Inter\s*\(par l’Admin Fadhel Admin\)/.test(await p.innerText('main')));

    // --- 4. Date simulée --------------------------------------------------
    const J3 = isoTunis(3), J11 = isoTunis(-11), J12 = isoTunis(-12);
    p = await ouvrir(adm, '/accueil');
    await p.fill('#bandeau-date-simulee', J3);
    await Promise.all([p.waitForNavigation(), p.click('#bandeau-admin button:has-text("Appliquer")')]);
    etape('bandeau « Date simulée : … — Revenir à aujourd’hui »', /^Date simulée : \S+ \S+ \S+ \d{4} — Revenir à aujourd’hui/.test(await texteBandeau(p)), await texteBandeau(p));
    await capture(p, 'e2e-12-date-simulee.png');
    await entrer(p, RIM, 'agir');
    p = await ouvrir(adm, '/dailylog?date=' + J3);
    await pretDailyLog(p);
    etape('Daily log de l’intervenante à J+3 (date simulée)', (await p.evaluate(() => window.KairosDailyLogPage.etat().sel)) === J3);
    await capture(p, 'e2e-12-agir-et-date.png');
    await p.click('#dl-liste .dl-row[data-cle="1:0"] .dl-plus');
    await p.click('#dl-enregistrer');
    await attendre(async () => (await p.textContent('#dl-status-texte')) === 'Enregistré');
    etape('ligne à J+3 enregistrée (garde en base comprise)', heures(RIM, J3) === '0.50', heures(RIM, J3));
    etape('horodatage réel (créée aujourd’hui)', sql(`SELECT (created_at AT TIME ZONE 'Africa/Tunis')::date FROM dailylog_entree WHERE utilisateur_id=${RIM} AND date='${J3}'`) === T);
    p = await ouvrir(adm, '/dailylog?date=' + J11);
    await pretDailyLog(p);
    etape('fenêtre décalée : J−11 (= date simulée − 14) modifiable', await p.isHidden('#dl-lecture'));
    p = await ouvrir(adm, '/dailylog?date=' + J12);
    await pretDailyLog(p);
    etape('fenêtre décalée : J−12 en lecture seule', await p.isVisible('#dl-lecture'), await p.textContent('#dl-lecture'));
    // Échéances : J+10 simulé -> la tâche à J+7 est en retard de 3 j.
    await p.fill('#bandeau-date-simulee', isoTunis(10));
    await Promise.all([p.waitForNavigation(), p.click('#bandeau-admin button:has-text("Appliquer")')]);
    p = await ouvrir(adm, '/deadlines');
    etape('Deadlines : « en retard de 3 j » à la date simulée', /en retard de 3 j/.test(await p.innerText('main')));
    p = await ouvrir(adm, '/accueil');
    etape('Mes tâches : « en retard de 3 j »', /en retard de 3 j/.test(await p.innerText('main')));
    await p.click('#bandeau-admin button:has-text("Revenir à mon compte")');
    await p.waitForLoadState();
    p = await ouvrir(adm, '/accueil');
    await Promise.all([p.waitForNavigation(), p.click('#bandeau-admin button:has-text("Revenir à aujourd’hui")')]);
    etape('retour à aujourd’hui', /^mode test/i.test(await texteBandeau(p)), await texteBandeau(p));
    const r = await p.goto(BASE + '/dailylog?date=' + J3);
    etape('J+3 de nouveau refusé (redirigé vers aujourd’hui)', new URL(r.url()).searchParams.get('date') === T, r.url());
    etape('aucun rappel Daily log créé pendant les modes', sql(`SELECT count(*) FROM notification WHERE utilisateur_id=${RIM} AND rappel_jours IS NOT NULL`) === '0');

    // --- 5. Deadlines : vue Admin -------------------------------------------
    p = await ouvrir(adm, '/deadlines');
    etape('Mes projets : aucune tâche de l’Admin', /0 tâche avec échéance/.test(await p.textContent('.subbar')));
    await Promise.all([p.waitForNavigation(), p.click('.bascule-vue a:has-text("Tous les projets")')]);
    etape('Tous les projets : 3 tâches avec échéance', /3 tâches avec échéance — tous les projets/.test(await p.textContent('.subbar')));
    etape('tâche de l’équipe URBS, lien vers sa fenêtre', await p.locator('a.g-bar[href="/projets/2?tache=4"]').count() === 1);
    etape('tâches sans échéance listées', await p.locator('.g-row-sans-echeance a[href="/projets/1?tache=3"]').count() === 1
      && await p.locator('.g-row-sans-echeance a[href="/projets/2?tache=5"]').count() === 1);
    await p.selectOption('select[name=equipe]', 'URBS');
    await Promise.all([p.waitForNavigation(), p.click('button:has-text("Filtrer")')]);
    etape('filtre équipe URBS : 1 tâche', /1 tâche avec échéance/.test(await p.textContent('.subbar')) && p.url().includes('equipe=URBS'));
    await capture(p, 'e2e-12-deadlines-admin.png');

    // --- 6. Non-Admin : rien ------------------------------------------------
    const rim = await contexte(navigateur, 'rim@x.tn');
    p = await ouvrir(rim, '/accueil');
    etape('intervenante : pas de bandeau', await p.locator('#bandeau-admin').count() === 0);
    const refus = await poster(p, '/admin/voir-comme', { utilisateur_id: '2' });
    const refusAgir = await poster(p, '/admin/agir-comme', { utilisateur_id: '2' });
    const refusDate = await poster(p, '/admin/date-simulee', { date: J3 });
    etape('intervenante : routes des modes refusées (403)', refus.status === 403 && refusAgir.status === 403 && refusDate.status === 403,
      [refus, refusAgir, refusDate]);
    await rim.close();

    // --- 7. 1280 / 375 px, clair / sombre ------------------------------------
    for (const [largeur, theme] of [[1280, 'light'], [1280, 'dark'], [375, 'light'], [375, 'dark']]) {
      const ctx = await contexte(navigateur, 'admin@x.tn', { largeur, hauteur: 860, theme });
      const pv = await ouvrir(ctx, '/admin/voir-comme');
      etape(`${largeur} px ${theme} : page « Voir comme » sans débordement`, await debordement(pv) === 0, await debordement(pv));
      await capture(pv, `e2e-12-selecteur-${largeur}-${theme}.png`);
      await poster(pv, '/admin/date-simulee', { date: '2026-10-15' });
      await entrer(pv, RIM, 'voir');
      await pv.goto(BASE + '/accueil');
      const bb = await pv.locator('#bandeau-admin').boundingBox();
      etape(`${largeur} px ${theme} : bandeau voir + date dans l’écran, sans débordement`,
        bb.x >= 0 && bb.x + bb.width <= largeur && await debordement(pv) === 0
        && /jeudi 15 octobre 2026/.test(await texteBandeau(pv)), [bb, await debordement(pv)]);
      const c1 = await contraste(pv, '#bandeau-admin .bandeau-admin-ligne span');
      const c2 = await contraste(pv, '#bandeau-admin .bandeau-admin-bouton');
      etape(`${largeur} px ${theme} : contrastes du bandeau ≥ 4,5:1`, c1 >= 4.5 && c2 >= 4.5, [c1, c2]);
      await capture(pv, `e2e-12-bandeau-${largeur}-${theme}.png`);
      // Clavier : le bouton « Revenir à mon compte » est atteint par Tab.
      await pv.evaluate(() => document.activeElement && document.activeElement.blur());
      let trouve = false;
      for (let i = 0; i < 30 && !trouve; i++) {
        await pv.keyboard.press('Tab');
        trouve = (await actif(pv)).texte === 'Revenir à mon compte';
      }
      etape(`${largeur} px ${theme} : « Revenir à mon compte » atteint au clavier`, trouve);
      const anneau = await pv.evaluate(() => getComputedStyle(document.activeElement).outlineStyle);
      etape(`${largeur} px ${theme} : focus visible`, anneau !== 'none', anneau);
      await poster(pv, '/admin/revenir', {});
      await poster(pv, '/admin/agir-comme', { utilisateur_id: String(RIM) });
      await pv.goto(BASE + '/accueil');
      etape(`${largeur} px ${theme} : bandeau agir sans débordement`, await debordement(pv) === 0);
      await capture(pv, `e2e-12-agir-${largeur}-${theme}.png`);
      await poster(pv, '/admin/revenir', {});
      await poster(pv, '/admin/date-simulee/effacer', {});
      await pv.goto(BASE + '/deadlines?vue=tous');
      etape(`${largeur} px ${theme} : Deadlines tous les projets sans débordement`, await debordement(pv) === 0, await debordement(pv));
      await capture(pv, `e2e-12-deadlines-${largeur}-${theme}.png`);
      await ctx.close();
    }
    await adm.close();

    etape('aucune erreur JavaScript', erreursJs.length === 0, erreursJs);
  } catch (e) {
    ko++;
    console.log('KO  exception : ' + (e && e.stack || e));
  } finally {
    await navigateur.close();
  }
  console.log(`\n${ok} OK, ${ko} KO`);
  process.exit(ko ? 1 : 0);
})();

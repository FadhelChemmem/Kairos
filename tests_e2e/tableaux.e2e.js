/* Scénario Playwright « tableaux » (lot 14, A2) : Vue d'ensemble de l'Admin
 * (revue produit P0-3), carte « À traiter » du chef et « Tâches de mes
 * projets » (P1-2), Deadlines de l'Admin sur « Tous les projets ».
 * Critères de l'audit UX §4.8 pour chaque interaction : aucune navigation
 * de document, |Δy| ≤ 40 px, focus attendu (jamais <body>), première
 * mutation ≤ 100 ms avec 800 ms de latence (état déplié optimiste), Retour
 * sans rechargement ; chiffres conformes à la base ; droits (cibles
 * refusées hors rôle, « Voir comme » en lecture) ; 1440 / 1024 / 768 /
 * 375 px en clair et sombre sans débordement ; aucune erreur JavaScript ni
 * boîte native.
 *
 * Lancement : KAIROS_E2E_SCENARIO=tableaux bash tests_e2e/lancer.sh [dossier_captures]
 * (base jetable + tests_e2e/seed_tableaux.py, mode test).
 */
'use strict';
const { execFileSync } = require('child_process');
const path = require('path');
let playwright;
try { playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright'); }
catch (e) { playwright = require('/opt/node-tools/node_modules/playwright'); }
const { chromium } = playwright;

const BASE = process.env.KAIROS_E2E_URL || 'http://127.0.0.1:8798';
const DB = process.env.KAIROS_E2E_DB || 'kairos_e2e_tableaux';
const CAPTURES = process.env.KAIROS_E2E_CAPTURES || '';
const MDP = 'Kairos2026!';
const ALI = 2;

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
async function attendre(fn, delai = 6000) {
  const fin = Date.now() + delai;
  for (;;) { let v; try { v = await fn(); } catch (e) { v = false; } if (v) return v; if (Date.now() > fin) return v; await pause(40); }
}
async function contexte(navigateur, email, opts = {}) {
  const ctx = await navigateur.newContext({ viewport: { width: opts.largeur || 1440, height: opts.hauteur || 900 },
    colorScheme: opts.theme || 'light', reducedMotion: opts.reducedMotion || 'no-preference', locale: 'fr-FR', timezoneId: 'Africa/Tunis' });
  const p = await ctx.newPage();
  await p.goto(BASE + '/connexion');
  await p.fill('#email', email);
  await p.fill('#password', MDP);
  await Promise.all([p.waitForNavigation(), p.click('button[type=submit]')]);
  await p.close();
  return ctx;
}
const docs = new WeakMap();
async function ouvrir(ctx, chemin) {
  const p = await ctx.newPage();
  docs.set(p, 0);
  p.on('pageerror', (e) => erreursJs.push(chemin + ' : ' + e.message));
  p.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) erreursJs.push(chemin + ' : ' + m.text()); });
  p.on('dialog', (d) => { erreursJs.push('boîte native : ' + d.message()); d.dismiss(); });
  p.on('request', (r) => { if (r.isNavigationRequest() && r.frame() === p.mainFrame()) docs.set(p, docs.get(p) + 1); });
  await p.goto(BASE + chemin);
  return p;
}
async function capture(p, nom) { if (CAPTURES) await p.screenshot({ path: path.join(CAPTURES, nom) }); }
async function latence(p, ms) {
  const cdp = await p.context().newCDPSession(p);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: ms, downloadThroughput: -1, uploadThroughput: -1 });
}
const etat = (p) => p.evaluate(() => ({
  marque: window.__marque === 1, mutation: window.__mutation, y: Math.round(window.scrollY),
  focus: document.activeElement === document.body ? 'body' : (document.activeElement.id || document.activeElement.tagName),
  url: location.pathname + location.search,
}));
// Délai mesuré dans la page, depuis le clic (pas depuis l'appel de
// Playwright, dont les vérifications avant clic prennent 30 à 150 ms) ;
// mutations visibles seulement (la réécriture de l'adresse d'un lien au
// clic, invisible, ne compte pas).
async function marquer(p) {
  await p.evaluate(() => {
    window.__marque = 1;
    if (window.__obs) window.__obs.disconnect();
    window.__mutation = null;
    window.__t0 = null;
    if (!window.__ecouteClic) {
      window.__ecouteClic = true;
      document.addEventListener('pointerdown', () => { if (window.__t0 === null) window.__t0 = performance.now(); }, true);
      document.addEventListener('keydown', () => { if (window.__t0 === null) window.__t0 = performance.now(); }, true);
    }
    window.__obs = new MutationObserver(() => {
      if (window.__mutation === null && window.__t0 !== null) window.__mutation = performance.now() - window.__t0;
    });
    window.__obs.observe(document.documentElement, { subtree: true, childList: true, characterData: true,
      attributes: true, attributeFilter: ['aria-expanded', 'aria-current', 'aria-busy', 'class', 'hidden'] });
  });
}
async function interaction(p, nom, action, fini, opts = {}) {
  await marquer(p);
  const avant = await etat(p);
  const d0 = docs.get(p);
  await action();
  const termine = await attendre(fini, 8000);
  await pause(120);
  const apres = await etat(p);
  const r = { docs: docs.get(p) - d0, dy: apres.y - avant.y, focus: apres.focus, mutation: apres.mutation && Math.round(apres.mutation), url: apres.url };
  etape(`${nom} : terminé`, !!termine, r);
  etape(`${nom} : aucune navigation de document`, apres.marque && r.docs === 0, r);
  etape(`${nom} : |Δy| ≤ 40 px`, Math.abs(r.dy) <= 40, r);
  if (opts.focus) {
    const bon = await p.evaluate((s) => !!document.activeElement && document.activeElement.matches(s), opts.focus);
    etape(`${nom} : focus sur ${opts.focus}`, bon, r);
  } else etape(`${nom} : focus jamais sur <body>`, r.focus !== 'body', r);
  if (!opts.sansLatence) etape(`${nom} : 1re mutation ≤ 100 ms (latence 800 ms)`, r.mutation !== null && r.mutation <= 100, r);
  return apres;
}
async function retour(p, nom, fini) {
  const d0 = docs.get(p);
  await marquer(p);
  await p.goBack();
  const termine = await attendre(fini, 8000);
  const e = await etat(p);
  etape(`${nom} : Retour = état précédent, sans rechargement`, !!termine && e.marque && docs.get(p) === d0, e);
}
const nombre = (p, sel) => p.textContent(sel).then((t) => parseInt(t, 10));
const deplie = (p, sel) => p.getAttribute(sel, 'aria-expanded');
const debordement = (p) => p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

(async () => {
  const navigateur = await chromium.launch();
  try {
    // --- 1. Vue d'ensemble de l'Admin ---------------------------------------
    const adm = await contexte(navigateur, 'admin@x.tn');
    let p = await ouvrir(adm, '/accueil');
    etape('Admin : 4 tuiles', await p.locator('.ve-tuile').count() === 4);
    const chiffres = {
      retard: await nombre(p, '#tuile-retard .ve-tuile-nombre'), bloquees: await nombre(p, '#tuile-bloquees .ve-tuile-nombre'),
      projets: await nombre(p, '#tuile-projets_sans_tache .ve-tuile-nombre'), dailylog: await nombre(p, '#tuile-dailylog .ve-tuile-nombre'),
    };
    etape('Admin : chiffres des tuiles (1 en retard, 1 bloquée, 1 projet sans tâche, 2 Daily log manquants)',
      chiffres.retard === 1 && chiffres.bloquees === 1 && chiffres.projets === 1 && chiffres.dailylog === 2, chiffres);
    etape('Admin : chiffres tabulaires', await p.evaluate(() => getComputedStyle(document.querySelector('.ve-tuile-nombre')).fontVariantNumeric === 'tabular-nums'));
    // Lot 15 : ligne « Échéances du bureau » repliée, Gantt dans le <details>.
    etape('Admin : échéances du bureau (Gantt)', /Échéances du bureau/.test(await p.textContent('#acc-deadlines'))
      && await p.locator('#acc-deadlines a[href="/projets/2?tache=4"]').count() === 1);
    etape('Admin : « Par chef de projet » (Ali, Omar)', await p.locator('.pc-table tbody tr').count() === 2
      && /Ali Chef/.test(await p.textContent('.pc-table')));
    etape('Admin : rappel Daily log masqué (aucune heure saisie)', await p.locator('.acc-dl').count() === 0);
    await capture(p, 'e2e-14-admin-vue-ensemble.png');

    await latence(p, 800);
    await interaction(p, 'Tuile « Tâches en retard » : liste dépliée',
      () => p.click('#tuile-retard'),
      async () => (await etat(p)).url === '/accueil?voir=retard' && await p.locator('#ve-detail .tb-ligne').count() === 1
        && /Plans de coffrage en retard/.test(await p.textContent('#ve-detail')),
      { focus: '#tuile-retard' });
    etape('Tuile dépliée : aria-expanded, lien vers la tâche', await deplie(p, '#tuile-retard') === 'true'
      && await p.locator('#ve-detail a[href="/projets/1?tache=6"]').count() === 1);
    etape('Liste dépliée annoncée', /Tâches en retard : 1, liste dépliée\./.test(await p.textContent('#k-annonce')), await p.textContent('#k-annonce'));
    await interaction(p, 'Tuile « Tâches bloquées » : la liste change',
      () => p.click('#tuile-bloquees'),
      async () => (await etat(p)).url === '/accueil?voir=bloquees' && /Note de calcul bloquée/.test(await p.textContent('#ve-detail')),
      { focus: '#tuile-bloquees' });
    etape('Une seule tuile dépliée', await deplie(p, '#tuile-retard') === 'false' && await deplie(p, '#tuile-bloquees') === 'true');
    await retour(p, 'Tuiles', async () => (await etat(p)).url === '/accueil?voir=retard' && await deplie(p, '#tuile-retard') === 'true');
    await interaction(p, 'Bouton « Fermer la liste »',
      () => p.click('#ve-detail-fermer'),
      async () => (await etat(p)).url === '/accueil' && await p.locator('#ve-detail .tb-ligne').count() === 0,
      { focus: '#tuile-retard' });
    await interaction(p, 'Tuile « Daily log manquants » : les personnes',
      () => p.click('#tuile-dailylog'),
      async () => await p.locator('#ve-detail .tb-ligne').count() === 2 && /Omar Urbs/.test(await p.textContent('#ve-detail')),
      { focus: '#tuile-dailylog' });
    etape('Daily log manquant : lien vers la journée de la personne', await p.locator(`#ve-detail a[href^="/dailylog?utilisateur=${ALI}&date="]`).count() === 1);
    await interaction(p, 'Tuile dépliée cliquée de nouveau : repliée',
      () => p.click('#tuile-dailylog'),
      async () => (await etat(p)).url === '/accueil' && await deplie(p, '#tuile-dailylog') === 'false',
      { focus: '#tuile-dailylog' });
    await latence(p, 0);
    // Repli sans JavaScript : la même adresse rend la liste dépliée.
    const sansJs = await navigateur.newContext({ javaScriptEnabled: false, storageState: await adm.storageState() });
    const ps = await sansJs.newPage();
    await ps.goto(BASE + '/accueil?voir=projets_sans_tache');
    etape('Sans JavaScript : ?voir= rend la liste dépliée', /21116X_Passerelle/.test(await ps.textContent('#ve-detail')));
    await sansJs.close();
    // Deadlines : l'Admin arrive sur « Tous les projets ».
    await p.goto(BASE + '/deadlines');
    etape('Deadlines (Admin) : « Tous les projets » par défaut', await p.getAttribute('[data-deadlines-bascule] a[data-vue="tous"]', 'aria-current') === 'page'
      && await p.locator('a.g-bar[href="/projets/2?tache=4"]').count() === 1);
    await p.close();

    // --- 2. Carte « À traiter » du chef -------------------------------------
    const ali = await contexte(navigateur, 'ali@x.tn');
    p = await ouvrir(ali, '/accueil');
    const lignes = await p.$$eval('.at-ligne', (els) => els.map((a) => a.id + ':' + parseInt(a.querySelector('.at-nombre').textContent, 10)));
    etape('Chef : lignes non nulles seulement', JSON.stringify(lignes) === JSON.stringify(
      ['at-retard:1', 'at-bloquees:1', 'at-sans_intervenant:2', 'at-sans_echeance:1', 'at-projets_sans_tache:1',
        'at-dailylog:1']), lignes);
    // Lot 15 : une pastille par projet — « Bloqué » l'emporte sur le retard.
    etape('Chef : pas de Vue d’ensemble, « Mes projets » avec pastilles', await p.locator('#vue-ensemble').count() === 0
      && await p.locator('.acc-projet .pill:has-text("Bloqué")').count() === 1);
    await capture(p, 'e2e-14-chef-a-traiter.png');
    await latence(p, 800);
    // Lot 15 : « À traiter » en bas de la colonne de droite — amenée à l'écran
    // avant la mesure (le défilement automatique du clic n'est pas un saut).
    await p.locator('#at-sans_intervenant').scrollIntoViewIfNeeded();
    await interaction(p, 'Ligne « sans intervenant » : liste dépliée',
      () => p.click('#at-sans_intervenant'),
      async () => (await etat(p)).url === '/accueil?voir=sans_intervenant' && await p.locator('#at-detail .tb-ligne').count() === 2,
      { focus: '#at-sans_intervenant' });
    // Lot 17 : plus de bascule « Les miennes | Toutes » (toujours toutes).
    etape('« Tâches de mes projets » : toutes les tâches, sans bascule',
      await p.locator('#tdp-miennes, #tdp-toutes').count() === 0 && await p.locator('#accueil-taches .acc-tache').count() === 4);
    await latence(p, 0);
    // Droits : une cible forgée n'est pas servie.
    const forge = await p.evaluate(async () => (await fetch('/accueil?voir=retard', { headers: { 'X-Kairos-Partiel': '#vue-ensemble' } })).status);
    etape('Chef : cible « Vue d’ensemble » forgée refusée (403)', forge === 403, forge);
    await p.close();

    // --- 3. Intervenante, puis « Voir comme » (lecture seule) ----------------
    const rim = await contexte(navigateur, 'rim@x.tn');
    p = await ouvrir(rim, '/accueil?voir=retard');
    etape('Intervenante : ni tuiles ni « À traiter », « Mes tâches »', await p.locator('#vue-ensemble, #a-traiter, [data-tdp-bascule]').count() === 0
      && /Mes tâches/.test(await p.textContent('main')));
    const refus = await p.evaluate(async () => Promise.all(['#vue-ensemble', '#a-traiter', '#accueil-taches'].map(
      (c) => fetch('/accueil?voir=retard', { headers: { 'X-Kairos-Partiel': c } }).then((r) => r.status))));
    etape('Intervenante : cibles forgées refusées (403)', refus.every((s) => s === 403), refus);
    await p.close();
    p = await ouvrir(adm, '/accueil');
    const entree = await p.evaluate(async (id) => {
      const fd = new FormData(); fd.append('utilisateur_id', String(id));
      return (await fetch('/admin/voir-comme', { method: 'POST', body: fd, credentials: 'same-origin' })).status;
    }, ALI);
    await p.goto(BASE + '/accueil');
    etape('Voir comme Ali : carte « À traiter »', entree < 400 && await p.locator('#a-traiter').count() === 1, entree);
    await interaction(p, 'Voir comme : une ligne se déplie (lecture)',
      () => p.click('#at-retard'),
      async () => await p.locator('#at-detail .tb-ligne').count() === 1, { focus: '#at-retard', sansLatence: true });
    await Promise.all([p.waitForNavigation(), p.click('#bandeau-admin button:has-text("Revenir à mon compte")')]);
    await p.close();

    // --- 4. Largeurs et thèmes : ni débordement ni chevauchement des tuiles ---
    for (const theme of ['light', 'dark']) {
      for (const largeur of [1440, 1024, 768, 375]) {
        for (const [email, nom] of [['admin@x.tn', 'admin'], ['ali@x.tn', 'chef']]) {
          const ctx = await contexte(navigateur, email, { largeur, hauteur: largeur < 600 ? 812 : 900, theme });
          const pv = await ouvrir(ctx, nom === 'admin' ? '/accueil?voir=retard' : '/accueil?voir=sans_intervenant');
          const d = await debordement(pv);
          const chevauche = await pv.evaluate(() => {
            const r = [...document.querySelectorAll('.ve-tuile, .at-ligne')].map((e) => e.getBoundingClientRect());
            return r.some((a, i) => r.some((b, j) => i < j && a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1));
          });
          etape(`${nom} ${largeur} px ${theme} : sans débordement ni chevauchement`, d <= 0 && !chevauche, { d, chevauche });
          if (largeur === 1440 || largeur === 375) await capture(pv, `e2e-14-${nom}-${largeur}-${theme}.png`);
          await ctx.close();
        }
      }
    }
    // Mouvement réduit : pas d'animation du chevron.
    const calme = await contexte(navigateur, 'admin@x.tn', { reducedMotion: 'reduce' });
    p = await ouvrir(calme, '/accueil');
    await p.click('#tuile-retard');
    await p.waitForSelector('#ve-detail .tb-ligne');
    const anim = await p.evaluate(() => Math.max(0, ...document.getAnimations().map((a) => Number(a.effect.getTiming().duration) || 0)));
    const transition = await p.evaluate(() => getComputedStyle(document.querySelector('.ve-tuile-chevron')).transitionDuration);
    etape('mouvement réduit : aucune animation > 1 ms', anim <= 1 && /^0s|1e-05s|0\.001s$/.test(transition), { anim, transition });
    await calme.close();
  } finally {
    await navigateur.close();
  }
  etape('aucune erreur JavaScript ni boîte native', erreursJs.length === 0, erreursJs.slice(0, 5));
  console.log(`\n${ok} OK, ${ko} KO`);
  process.exit(ko ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });

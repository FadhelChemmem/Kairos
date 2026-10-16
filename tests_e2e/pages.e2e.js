/* Scénario Playwright du lot 13, phase 2 (D) : pages converties au socle
 * partiel — Deadlines, Notifications (aperçu de la cloche, page), Journal
 * d'audit, Utilisateurs (fiche, création, « Mes informations », profil),
 * Daily log (focus) et bandeau des modes. Critères de l'audit UX §4.8 pour
 * CHAQUE interaction convertie : aucune navigation de document, |Δy| ≤
 * 40 px, focus attendu (jamais <body>), première mutation ≤ 100 ms avec
 * 800 ms de latence, Retour sans rechargement, mouvement réduit sans
 * animation, 1440 / 1024 / 768 / 375 px en clair et sombre sans
 * débordement, « Voir comme » sans écriture, aucune erreur JavaScript ni
 * boîte native.
 *
 * Lancement : KAIROS_E2E_SCENARIO=pages bash tests_e2e/lancer.sh [dossier_captures]
 * (base jetable + tests_e2e/seed_pages.py). Variables : KAIROS_E2E_URL,
 * KAIROS_E2E_DB, KAIROS_E2E_CAPTURES (facultatif), PLAYWRIGHT_MODULE.
 */
'use strict';
const { execFileSync } = require('child_process');
const path = require('path');
let playwright;
try { playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright'); }
catch (e) { playwright = require('/opt/node-tools/node_modules/playwright'); }
const { chromium } = playwright;

const BASE = process.env.KAIROS_E2E_URL || 'http://127.0.0.1:8798';
const DB = process.env.KAIROS_E2E_DB || 'kairos_e2e_pages';
const CAPTURES = process.env.KAIROS_E2E_CAPTURES || '';
const MDP = 'Kairos2026!';
const ADMIN = 1, RIM = 3, ANCIEN = 6;

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
  const ctx = await navigateur.newContext({ viewport: { width: opts.largeur || 1280, height: opts.hauteur || 860 },
    colorScheme: opts.theme || 'light', reducedMotion: opts.reducedMotion || 'no-preference' });
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
  // Les 4xx voulus (422 d'un formulaire, 403 de la lecture seule) sont
  // journalisés par Chromium comme « Failed to load resource ».
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
async function marquer(p) {
  await p.evaluate(() => {
    window.__marque = 1;
    if (window.__obs) window.__obs.disconnect();
    window.__mutation = null;
    window.__obs = new MutationObserver(() => { if (window.__mutation === null) window.__mutation = performance.now() - window.__t0; });
    window.__obs.observe(document.documentElement, { subtree: true, childList: true, attributes: true, characterData: true });
    window.__t0 = performance.now();
  });
}
/**
 * Une interaction convertie, mesurée selon l'audit UX §4.8.
 * opts : { focus: sélecteur attendu, defilementLibre, sansLatence }
 */
async function interaction(p, nom, action, fini, opts = {}) {
  await marquer(p);
  const avant = await etat(p);
  const d0 = docs.get(p);
  await action();
  const termine = await attendre(fini, 8000);
  await pause(opts.pause || 120);
  const apres = await etat(p);
  const r = { docs: docs.get(p) - d0, dy: apres.y - avant.y, focus: apres.focus, mutation: apres.mutation && Math.round(apres.mutation), url: apres.url };
  etape(`${nom} : terminé`, !!termine, r);
  etape(`${nom} : aucune navigation de document`, apres.marque && r.docs === 0, r);
  if (!opts.defilementLibre) etape(`${nom} : |Δy| ≤ 40 px`, Math.abs(r.dy) <= 40, r);
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
async function maxAnimation(p, ms = 600) {
  let max = 0;
  for (let i = 0; i < ms / 60; i++) {
    max = Math.max(max, await p.evaluate(() => Math.max(0, ...document.getAnimations()
      .filter((a) => !(a.effect && a.effect.target && a.effect.target.classList && a.effect.target.classList.contains('roue-chargement')))
      .map((a) => Number(a.effect.getTiming().duration) || 0))));
    await pause(60);
  }
  return max;
}

(async () => {
  const navigateur = await chromium.launch();
  try {
    const adm = await contexte(navigateur, 'admin@x.tn');

    // --- 1. Deadlines -------------------------------------------------------
    // Tâches en cours avec échéance sur les projets ouverts (le jeu de
    // données du socle s'enrichit d'une phase à l'autre : compté en base).
    const nbTous = Number(sql("SELECT count(*) FROM tache t JOIN projet p ON p.id = t.projet_id WHERE t.etat = 'en_cours' AND p.etat IN ('en_cours', 'bloque') AND t.date_echeance IS NOT NULL"));
    // Lot 14 : l'Admin arrive sur « Tous les projets » ; « Mes projets » = ?vue=mes.
    let p = await ouvrir(adm, '/deadlines');
    etape('Deadlines : l’Admin arrive sur « Tous les projets »', await p.locator('.g-row').count() === nbTous
      && await p.getAttribute('[data-deadlines-bascule] a[data-vue="tous"]', 'aria-current') === 'page');
    p = await ouvrir(adm, '/deadlines?vue=mes');
    await latence(p, 800);
    etape('Deadlines : Admin sans projet, état vide avec « Voir tous les projets »',
      await p.locator('#deadlines-contenu .k-vide a:has-text("Voir tous les projets")').count() === 1);
    await interaction(p, 'Deadlines : « Voir tous les projets » (état vide)',
      () => p.click('#deadlines-contenu .k-vide a'),
      async () => (await etat(p)).url === '/deadlines?vue=tous' && await p.locator('.g-row').count() === nbTous,
      { focus: '#deadlines-contenu, #deadlines-contenu *, [data-deadlines-bascule] a' });
    etape('Deadlines : contrôle segmenté sur « Tous les projets »',
      await p.getAttribute('[data-deadlines-bascule] a[data-vue="tous"]', 'aria-current') === 'page');
    etape('Deadlines : ligne « aujourd’hui »', await p.locator('.g-daycell.g-aujourdhui').count() === 1);
    await p.focus('#deadlines-equipe');
    await interaction(p, 'Deadlines : filtre Équipe (au changement)',
      () => p.selectOption('#deadlines-equipe', 'URBS'),
      async () => (await etat(p)).url === '/deadlines?vue=tous&equipe=URBS' && /1 tâche avec échéance/.test(await p.textContent('#deadlines-compte')),
      { focus: '#deadlines-equipe' });
    await retour(p, 'Deadlines : filtre', async () => (await etat(p)).url === '/deadlines?vue=tous' && await p.locator('.g-row').count() === nbTous
      && await p.inputValue('#deadlines-equipe') === '');
    await p.focus('[data-deadlines-bascule] a[data-vue=""]');
    await interaction(p, 'Deadlines : bascule « Mes projets »',
      () => p.keyboard.press('Enter'),
      async () => (await etat(p)).url === '/deadlines?vue=mes' && await p.locator('#deadlines-contenu .k-vide').count() === 1,
      { focus: '[data-deadlines-bascule] a[data-vue=""]' });
    await retour(p, 'Deadlines : bascule', async () => (await etat(p)).url === '/deadlines?vue=tous' && await p.locator('.g-row').count() === nbTous
      && await p.getAttribute('[data-deadlines-bascule] a[data-vue="tous"]', 'aria-current') === 'page');
    await p.fill('#filtre-deadlines', 'urbs');
    await attendre(async () => (await etat(p)).url === '/deadlines?vue=tous&q=urbs');
    etape('Deadlines : filtre texte tenu dans l’adresse (?q=)', (await etat(p)).url === '/deadlines?vue=tous&q=urbs'
      && await p.locator('.g-row:not([hidden])').count() === 1);
    etape('Deadlines : barre = lien vers la fenêtre de la tâche', await p.locator('a.g-bar[href="/projets/2?tache=4"]').count() === 1);
    await capture(p, 'e2e-13d-deadlines.png');
    await p.close();

    // --- 2. Notifications : aperçu de la cloche, page ---------------------
    p = await ouvrir(adm, '/accueil');
    await latence(p, 800);
    const badge = () => p.evaluate(() => { const b = document.querySelector('#notifs-cloche .iconbtn-badge'); return b.hidden ? '' : b.textContent.trim(); });
    // Le rappel du Daily log de l'Admin (créé à la connexion) s'ajoute aux 3 du jeu de données.
    const nonLues = () => Number(sql('SELECT count(*) FROM notification WHERE utilisateur_id=1 AND NOT lu'));
    const n0 = nonLues();
    etape('cloche : badge = notifications non lues', await badge() === String(n0) && n0 >= 3, [await badge(), n0]);
    await interaction(p, 'Notifications : ouvrir l’aperçu de la cloche',
      () => p.click('#notifs-cloche'),
      async () => await p.locator('#notifs-apercu .notif-ligne').count() === n0 + 1,
      { focus: '#notifs-apercu-titre' });
    etape('aperçu : notifications chargées, aria-expanded', await p.getAttribute('#notifs-cloche', 'aria-expanded') === 'true');
    await capture(p, 'e2e-13d-cloche.png');
    const premiere = p.locator('#notifs-apercu .notif-lire-btn').first();
    await premiere.focus();
    let immediat = null;
    await interaction(p, 'Notifications : « Marquer comme lue » (aperçu, optimiste)',
      async () => { await p.keyboard.press('Enter'); immediat = await badge(); },
      async () => await p.locator('#notifs-apercu .notif-lire').count() === n0 - 1 && !(await p.evaluate(() => document.querySelector('#notifs-apercu [aria-busy]'))),
      { focus: '#notifs-apercu [id^="notif-ouvrir-"]' });
    etape('« Marquer comme lue » : badge diminué tout de suite (optimiste)', immediat === String(n0 - 1), [immediat, n0]);
    etape('« Marquer comme lue » : en base', nonLues() === n0 - 1);
    await interaction(p, 'Notifications : « Tout marquer comme lu » (aperçu, optimiste)',
      () => p.click('#notifs-apercu form[data-optimiste="notifs-toutes-lues"] button'),
      async () => await p.locator('#notifs-apercu .notif-ligne.non-lu').count() === 0 && await badge() === ''
        && await p.locator('#notifs-apercu form[data-optimiste] button:disabled').count() === 1,
      { focus: '#notifs-apercu-titre' });
    etape('« Tout marquer comme lu » : badge masqué, nom de la cloche à jour, base',
      await p.getAttribute('#notifs-cloche', 'aria-label') === 'Notifications'
      && sql('SELECT count(*) FROM notification WHERE utilisateur_id=1 AND NOT lu') === '0');
    await p.keyboard.press('Escape');
    etape('aperçu : Échap ferme, focus rendu à la cloche', await p.evaluate(() => document.getElementById('notifs-popover').hidden
      && document.activeElement.id === 'notifs-cloche'));
    sql("UPDATE notification SET lu = false WHERE utilisateur_id = 1 AND message <> 'Ancienne notification déjà lue.'");
    await p.close();
    p = await ouvrir(adm, '/notifications');
    await latence(p, 800);
    etape('page Notifications : groupée par jour', (await p.locator('.notif-jour').allInnerTexts()).slice(0, 2).join('|') === 'Aujourd’hui|Hier',
      await p.locator('.notif-jour').allInnerTexts());
    await p.focus('#notifs-toutes-lues');
    await interaction(p, 'Notifications : « Tout marquer comme lu » (page)',
      () => p.keyboard.press('Enter'),
      async () => await p.locator('#notifications-liste .notif-ligne.non-lu').count() === 0 && /0 non lue/.test(await p.textContent('#notifications-compte'))
        && !(await p.evaluate(() => document.querySelector('#notifications-liste[aria-busy]'))),
      { focus: '#notifs-toutes-lues' });
    etape('page : toast de confirmation', /marquées comme lues/.test(await p.locator('#k-toasts').innerText()));
    await p.close();

    // --- 3. Journal d'audit ------------------------------------------------
    p = await ouvrir(adm, '/admin/journal');
    await latence(p, 800);
    etape('Journal : vrai tableau, 100 lignes, groupes par jour', await p.locator('table.journal-table caption').count() === 1
      && await p.locator('.journal-ligne').count() === 100 && await p.locator('th[scope="rowgroup"]').count() >= 1);
    const taille = await p.evaluate(() => document.documentElement.outerHTML.length);
    etape('Journal : page de moins de 150 Ko', taille < 150000, taille);
    await p.locator('#journal-suite a').scrollIntoViewIfNeeded();
    await p.locator('#journal-suite a').focus();
    await interaction(p, 'Journal : « Charger 100 de plus »',
      () => p.keyboard.press('Enter'),
      async () => await p.locator('.journal-ligne').count() > 100 && !(await p.evaluate(() => document.querySelector('#journal-table[aria-busy]'))),
      { focus: '[id^="journal-apres-"]' });
    etape('Journal : lignes ajoutées, compteur à jour', /affichées/.test(await p.textContent('#journal-compte'))
      && await p.locator('.journal-ligne').count() > 100);
    await p.evaluate(() => window.scrollTo(0, 0));
    const details = p.locator('.journal-details summary').first();
    await details.focus();
    await interaction(p, 'Journal : « Voir les données » (à la demande)',
      () => p.keyboard.press('Enter'),
      async () => await p.locator('.journal-details[open] .journal-diff').count() > 0,
      { focus: '.journal-details summary' });
    await p.focus('#journal-action-filtre');
    await interaction(p, 'Journal : filtre Action (au changement)',
      () => p.selectOption('#journal-action-filtre', 'INSERT'),
      async () => (await etat(p)).url === '/admin/journal?action=INSERT' && !(await p.evaluate(() => document.querySelector('#journal-resultats[aria-busy]'))),
      { focus: '#journal-action-filtre' });
    etape('Journal : « Réinitialiser » visible avec un filtre', await p.isVisible('.journal-reinit'));
    await retour(p, 'Journal : filtre', async () => (await etat(p)).url === '/admin/journal' && await p.locator('.journal-ligne').count() === 100
      && await p.inputValue('#journal-action-filtre') === '');
    await capture(p, 'e2e-13d-journal.png');
    await p.close();

    // --- 4. Utilisateurs : fiche, création, Mes informations, profil ------
    p = await ouvrir(adm, '/utilisateurs/' + RIM);
    await latence(p, 800);
    await p.fill('#telephone', 'abc!!');
    await p.focus('#utilisateur-enregistrer');
    await interaction(p, 'Fiche : Enregistrer avec une erreur (422)',
      () => p.keyboard.press('Enter'),
      async () => await p.locator('#err-telephone').count() === 1,
      { focus: '#telephone', defilementLibre: true });
    etape('Fiche : erreur reliée au champ', await p.getAttribute('#telephone', 'aria-invalid') === 'true'
      && (await p.getAttribute('#telephone', 'aria-describedby')).includes('err-telephone'));
    await p.fill('#telephone', '55 123 456');
    await p.focus('#utilisateur-enregistrer');
    await interaction(p, 'Fiche : Enregistrer',
      () => p.keyboard.press('Enter'),
      async () => await p.locator('#err-telephone').count() === 0 && await p.locator('#k-toasts .k-toast:has-text("Fiche mise à jour")').count() === 1,
      { focus: '#utilisateur-enregistrer' });
    etape('Fiche : enregistrée en base', sql(`SELECT telephone FROM utilisateur WHERE id=${RIM}`) === '55 123 456');
    await p.locator('#fiche-actif').scrollIntoViewIfNeeded();
    await p.focus('#fiche-actif');
    await marquer(p);
    await p.keyboard.press('Enter');
    const bascule = await p.getAttribute('#fiche-actif', 'aria-checked');
    await interaction(p, 'Fiche : « Compte actif » (optimiste)', async () => {},
      async () => await p.locator('#k-toasts .k-toast:has-text("désactivé")').count() === 1 && sql(`SELECT actif FROM utilisateur WHERE id=${RIM}`) === 'f',
      { focus: '#fiche-actif', sansLatence: true });
    etape('« Compte actif » : état changé tout de suite', bascule === 'false', bascule);
    etape('« Compte actif » : carte de réinitialisation suivie (compte désactivé)', await p.locator('#utilisateur-reinit-envoyer').count() === 0);
    await interaction(p, 'Fiche : « Annuler » du toast',
      () => p.click('#k-toasts .k-toast-action:has-text("Annuler")'),
      async () => sql(`SELECT actif FROM utilisateur WHERE id=${RIM}`) === 't' && await p.getAttribute('#fiche-actif', 'aria-checked') === 'true',
      { focus: '#fiche-actif', sansLatence: true });
    await p.locator('#utilisateur-reinit-envoyer').scrollIntoViewIfNeeded();
    await p.focus('#utilisateur-reinit-envoyer');
    await interaction(p, 'Fiche : « Envoyer un lien de réinitialisation »',
      () => p.keyboard.press('Enter'),
      async () => await p.locator('#k-toasts .k-toast-erreur:has-text("réinitialisation")').count() === 1,
      { focus: '#utilisateur-reinit-envoyer' });
    await capture(p, 'e2e-13d-fiche.png');
    await p.close();

    p = await ouvrir(adm, '/utilisateurs/nouveau');
    await latence(p, 800);
    await p.fill('#prenom', 'Neo');
    await p.fill('#email', 'rim@x.tn');
    await p.focus('#utilisateur-creer-envoyer');
    await interaction(p, 'Création : erreurs (422), focus sur le premier champ en erreur',
      () => p.keyboard.press('Enter'),
      async () => await p.locator('#err-nom').count() === 1,
      { focus: '#nom', defilementLibre: true });
    etape('Création : toutes les erreurs sous leur champ', await p.locator('.champ-erreur').count() === 2
      && await p.inputValue('#prenom') === 'Neo');
    await p.fill('#nom', 'Phyte');
    await p.selectOption('#equipe_code', 'MIDGARD');
    await p.focus('#utilisateur-creer-envoyer');
    await interaction(p, 'Création : e-mail déjà pris (422)',
      () => p.keyboard.press('Enter'),
      async () => await p.locator('#err-email').count() === 1,
      { focus: '#email', defilementLibre: true });
    await p.fill('#email', 'neo@x.tn');
    await Promise.all([p.waitForURL(/\/utilisateurs$/), p.click('#utilisateur-creer-envoyer')]);
    await attendre(async () => await p.locator('#k-toasts .k-toast').count() > 0, 3000);
    etape('Création réussie : liste et message (vraie navigation voulue)', sql("SELECT count(*) FROM utilisateur WHERE email='neo@x.tn'") === '1'
      && /Compte créé pour Neo Phyte/.test(await p.locator('#k-toasts').innerText()));
    await p.close();

    p = await ouvrir(adm, '/utilisateurs/moi');
    await latence(p, 800);
    await p.fill('#mot_de_passe_actuel', 'faux');
    await p.fill('#nouveau_mot_de_passe', 'abcdefghij');
    await p.fill('#confirmation', 'abcdefghij');
    await p.focus('#mot-de-passe-envoyer');
    await interaction(p, 'Mes informations : mot de passe actuel faux (422)',
      () => p.keyboard.press('Enter'),
      async () => await p.locator('#err-mot_de_passe_actuel').count() === 1,
      { focus: '#mot_de_passe_actuel', defilementLibre: true });
    await p.fill('#adresse', 'Rue de Marseille, Tunis');
    await p.focus('#mes-infos-enregistrer');
    await interaction(p, 'Mes informations : Enregistrer',
      () => p.keyboard.press('Enter'),
      async () => await p.locator('#k-toasts .k-toast:has-text("Vos informations")').count() === 1,
      { focus: '#mes-infos-enregistrer' });
    etape('Mes informations : en base', sql(`SELECT adresse FROM utilisateur WHERE id=${ADMIN}`) === 'Rue de Marseille, Tunis');
    await p.close();

    p = await ouvrir(adm, `/utilisateurs/${RIM}/profil`);
    await latence(p, 800);
    const lien = p.locator('#profil-activite a:has-text("Voir la semaine précédente")');
    await lien.scrollIntoViewIfNeeded();
    await lien.focus();
    // Lot 15 : samedis et dimanches sans heures non listés (5 à 7 jours par semaine).
    const jours1 = await p.locator('#profil-activite .dl-semaine-jour').count();
    await interaction(p, 'Profil : « Voir la semaine précédente »',
      () => p.keyboard.press('Enter'),
      async () => (await etat(p)).url === `/utilisateurs/${RIM}/profil?semaines=2` && await p.locator('#profil-activite .dl-semaine-jour').count() >= jours1 + 5,
      { focus: '[id^="profil-jour-"]' });
    await retour(p, 'Profil : semaine précédente', async () => (await etat(p)).url === `/utilisateurs/${RIM}/profil`
      && await p.locator('#profil-activite .dl-semaine-jour').count() === jours1);
    await p.close();

    // --- 5. Daily log : le focus reste après Enregistrer et Marquer absent ---
    const rim = await contexte(navigateur, 'rim@x.tn');
    p = await ouvrir(rim, '/dailylog');
    await p.waitForFunction(() => window.KairosDailyLogPage && !window.KairosDailyLogPage.etat().chargement);
    // Lot 14 : sa tâche 1 proposée (pas le projet 1 seul : elle y a des tâches).
    await p.click('#dl-liste .dl-row[data-cle="1:1"] .dl-plus');
    await p.focus('#dl-enregistrer');
    await p.keyboard.press('Enter');
    await attendre(async () => (await p.evaluate(() => window.KairosDailyLogPage.etat().saved)) === 'enregistre');
    etape('Daily log : focus resté sur « Enregistrer » (bug UX I3)', await p.evaluate(() => document.activeElement.id) === 'dl-enregistrer');
    await p.focus('#dl-absent');
    await p.keyboard.press('Enter');
    await attendre(async () => /Annuler l|absent/i.test(await p.textContent('#dl-absent')) && await p.getAttribute('#dl-absent', 'aria-pressed') === 'true');
    etape('Daily log : focus resté sur « Marquer absent »', await p.evaluate(() => document.activeElement.id) === 'dl-absent');
    await p.keyboard.press('Enter');
    await attendre(async () => await p.getAttribute('#dl-absent', 'aria-pressed') === 'false');
    etape('Daily log : absence annulée, focus toujours sur le bouton', await p.evaluate(() => document.activeElement.id) === 'dl-absent');
    await p.click('#dl-ajouter');
    await p.fill('#dl-recherche', 'Sie');
    await attendre(async () => /trouvé/.test(await p.textContent('#dl-catalogue-statut')));
    etape('Daily log : catalogue sans région live, annonce courte (a11y I8)',
      !(await p.getAttribute('#dl-catalogue-corps', 'role')) && /^\d+ projets? ou tâches? trouvés?$/.test((await p.textContent('#dl-catalogue-statut')).trim()),
      await p.textContent('#dl-catalogue-statut'));
    await p.keyboard.press('Escape');
    await rim.close();

    // --- 6. « Voir comme » : aucune écriture proposée --------------------------
    p = await ouvrir(adm, '/admin/voir-comme');
    await p.evaluate((id) => { document.getElementById('voir-comme-compte').value = String(id); }, RIM);
    await Promise.all([p.waitForNavigation(), p.click('button:has-text("Voir comme")')]);
    sql(`INSERT INTO notification (utilisateur_id, categorie, message) VALUES (${RIM}, 'projet', 'Notification de Rim pour la lecture seule.')`);
    await p.goto(BASE + '/notifications');
    const actifsNotif = await p.evaluate(() => Array.from(document.querySelectorAll('main form[method=post] button')).filter((b) => !b.disabled).length);
    etape('Voir comme : Notifications sans écriture active', actifsNotif === 0, actifsNotif);
    await p.click('#notifs-cloche');
    await attendre(async () => await p.locator('#notifs-apercu .notifs-apercu-tete').count() === 1);
    const actifsApercu = await p.evaluate(() => Array.from(document.querySelectorAll('#notifs-apercu form[method=post] button')).filter((b) => !b.disabled).length);
    etape('Voir comme : aperçu de la cloche sans écriture active', actifsApercu === 0, actifsApercu);
    await p.keyboard.press('Escape');
    await p.goto(BASE + '/utilisateurs/moi');
    const actifsMoi = await p.evaluate(() => Array.from(document.querySelectorAll('main form[method=post] button, main form[method=post] input:not([type=hidden])')).filter((b) => !b.disabled).length);
    etape('Voir comme : « Mes informations » sans écriture active', actifsMoi === 0, actifsMoi);
    const bandeau = await p.evaluate(() => document.getElementById('bandeau-admin').getBoundingClientRect().height);
    etape('bandeau « Voir comme » : une ligne (≤ 41 px)', bandeau <= 41, bandeau);
    etape('bandeau : repère nommé', await p.getAttribute('#bandeau-admin', 'role') === 'region');
    await p.click('#bandeau-admin button:has-text("Revenir à mon compte")');
    await p.waitForLoadState();
    await p.close();

    // --- 7. RH : fiche d'un Admin protégée, même en partiel --------------------
    const rh = await contexte(navigateur, 'rh@x.tn');
    p = await ouvrir(rh, '/utilisateurs/' + ADMIN);
    etape('RH : fiche d’un Admin en lecture seule', await p.locator('fieldset[disabled]').count() === 1
      && await p.locator('#fiche-actif').count() === 0 && await p.locator('#utilisateur-reinit').count() === 0);
    const refus = await p.evaluate(async () => {
      const fd = new FormData(); fd.append('prenom', 'X'); fd.append('nom', 'Y'); fd.append('email', 'admin@x.tn');
      const r = await fetch('/utilisateurs/1', { method: 'POST', body: fd, headers: { 'X-Kairos-Partiel': '#utilisateur-form', 'X-Requested-With': 'XMLHttpRequest' } });
      return r.status;
    });
    etape('RH : enregistrement partiel de la fiche d’un Admin refusé (403)', refus === 403, refus);
    await rh.close();

    // --- 8. Mouvement réduit : aucune animation --------------------------------
    const calme = await contexte(navigateur, 'admin@x.tn', { reducedMotion: 'reduce' });
    p = await ouvrir(calme, '/deadlines?vue=tous');
    await p.click('[data-deadlines-bascule] a[data-vue=""]');
    let m1 = await maxAnimation(p);
    await p.click('#notifs-cloche');
    m1 = Math.max(m1, await maxAnimation(p));
    await p.goto(BASE + '/utilisateurs/' + RIM);
    await p.click('#fiche-actif');
    m1 = Math.max(m1, await maxAnimation(p));
    await attendre(async () => sql(`SELECT actif FROM utilisateur WHERE id=${RIM}`) === 'f');
    sql(`UPDATE utilisateur SET actif=true WHERE id=${RIM}`);
    etape('mouvement réduit : aucune animation > 1 ms (bascule, cloche, interrupteur)', m1 <= 1, m1);
    await calme.close();

    // --- 10. Correctifs après contre-expertise (F3) ---------------------------
    // Deadlines : une barre ouvre le panneau de la tâche sur place (verif-ux).
    const ali = await contexte(navigateur, 'ali@x.tn', { largeur: 1440 });
    p = await ouvrir(ali, '/deadlines');
    await latence(p, 800);
    await interaction(p, 'Deadlines : barre du Gantt → panneau de la tâche sur place',
      () => p.click('.g-row[data-open-tache="1"] a.g-bar'),
      async () => (await etat(p)).url === '/deadlines?tache=1' && await p.locator('#tache-titre-1').count() === 1,
      { focus: '#tache-fenetre-1 [data-tache-entete]', sansLatence: true });
    // Lot 14 (P0-1) : « Bloquée » demande d'abord « Qu’est-ce qui bloque ? ».
    await p.click('#tache-1-etat-bloque');
    await p.fill('#tache-1-motif', 'Attente des plans archi indice B');
    await interaction(p, 'Deadlines (panneau) : état « Bloquée » avec son motif',
      () => p.click('#tache-1-blocage-valider'),
      async () => sql('SELECT etat FROM tache WHERE id=1') === 'bloque' && await p.locator('#k-toasts .k-toast-action:has-text("Annuler")').count() === 1,
      { focus: '#tache-1-etat-bloque' });
    await interaction(p, 'Deadlines (panneau) : « Annuler » du toast (sans ligne de tableau)',
      () => p.click('#k-toasts .k-toast-action:has-text("Annuler")'),
      async () => sql('SELECT etat FROM tache WHERE id=1') === 'en_cours' && await p.getAttribute('#tache-1-etat-en_cours', 'aria-pressed') === 'true',
      { sansLatence: true });
    await p.keyboard.press('Escape');
    await attendre(async () => !(await p.evaluate(() => document.getElementById('dialog-tache').open)) && (await etat(p)).url === '/deadlines');
    etape('Deadlines : Échap ferme le panneau, focus rendu à la barre (contenu rafraîchi compris)',
      !!(await attendre(() => p.evaluate(() => document.activeElement.matches('.g-row[data-open-tache="1"] a.g-bar')))),
      await p.evaluate(() => document.activeElement.outerHTML.slice(0, 80)));
    await p.close();

    // Fiche projet : un seul GET à l'ouverture à la souris (N8), un seul POST
    // en renommant avec Entrée (N4), ↑ / ↓ annoncés (a11y N7).
    p = await ouvrir(ali, '/projets/1');
    const requetes = [];
    p.on('request', (r) => requetes.push(r.method() + ' ' + new URL(r.url()).pathname));
    await p.hover('#tache-ligne-1 [data-ouvrir-tache]');
    await pause(40);
    await p.click('#tache-ligne-1 [data-ouvrir-tache]');
    await p.waitForSelector('#tache-titre-1');
    await pause(500);
    etape('Panneau : ouverture à la souris = 1 seul GET (N8)', requetes.filter((r) => r === 'GET /projets/1/taches/1/fenetre').length === 1, requetes);
    requetes.length = 0;
    const titre1 = await p.inputValue('#tache-titre-1');
    await p.fill('#tache-titre-1', titre1 + ' (rév.)');
    await p.press('#tache-titre-1', 'Enter');
    await attendre(async () => sql('SELECT titre FROM tache WHERE id=1') === titre1 + ' (rév.)');
    await pause(800);
    etape('Panneau : renommer avec Entrée = 1 POST, 1 toast (N4)',
      requetes.filter((r) => r === 'POST /projets/1/taches/1/titre').length === 1
      && await p.locator('#k-toasts .k-toast:has-text("Tâche renommée")').count() === 1, requetes);
    await p.focus('[data-tache-voisine="1"]');
    await p.keyboard.press('ArrowDown');
    const annonce = await attendre(async () => {
      const t = await p.evaluate(() => [document.getElementById('k-annonce'), document.getElementById('tache-dialog-annonce')]
        .map((a) => (a ? a.textContent : '')).join('|'));
      return /Tâche \d+ sur \d+ : \S/.test(t) ? t : false;
    });
    etape('Panneau : ↓ annonce « Tâche n sur N : titre » (a11y N7)', !!annonce, annonce);
    sql(`UPDATE tache SET titre = '${titre1.replace(/'/g, "''")}' WHERE id = 1`);
    await p.close();
    await ali.close();

    // Réaction hors ligne : « Réessayer » (N7) ; cloche de la barre basse :
    // aperçu en feuille sur téléphone.
    const rimTel = await contexte(navigateur, 'rim@x.tn', { largeur: 375, hauteur: 800 });
    p = await ouvrir(rimTel, '/accueil');
    const reactions = () => sql('SELECT count(*) FROM post_reaction');
    const r0 = reactions();
    await p.context().setOffline(true);
    await p.locator('.post-reaction-form button[type=submit]').first().click();
    const toastHl = await attendre(async () => (await p.locator('#k-toasts .k-toast-erreur .k-toast-action:has-text("Réessayer")').count()) === 1);
    await p.context().setOffline(false);
    etape('Réaction hors ligne : toast avec « Réessayer » (N7)', !!toastHl);
    if (toastHl) await p.click('#k-toasts .k-toast-erreur .k-toast-action:has-text("Réessayer")');
    etape('Réaction : « Réessayer » enregistre', !!(await attendre(() => reactions() !== r0)), [r0, reactions()]);
    await p.locator('.post-reaction-form button[type=submit]').first().click();
    await attendre(() => reactions() === r0);
    await interaction(p, 'Cloche de la barre basse : aperçu en feuille (téléphone)',
      () => p.click('.k-nav-basse a[data-notifs-lien]'),
      async () => !(await p.evaluate(() => document.getElementById('notifs-popover').hidden)) && await p.locator('#notifs-apercu .notif-ligne').count() > 0,
      { focus: '#notifs-apercu-titre', sansLatence: true });
    const feuille = await p.evaluate(() => { const b = document.getElementById('notifs-popover').getBoundingClientRect(); return [Math.round(b.left), Math.round(b.right), innerWidth, Math.round(b.bottom), innerHeight]; });
    etape('Cloche : feuille pleine largeur, au-dessus de la barre basse', feuille[0] === 0 && feuille[1] === feuille[2] && feuille[3] < feuille[4], feuille);
    await p.keyboard.press('Escape');
    etape('Cloche : Échap ferme, focus rendu à la barre basse', await p.evaluate(() => document.getElementById('notifs-popover').hidden && document.activeElement.hasAttribute('data-notifs-lien')));
    await rimTel.close();

    // « Daily log de » : champ à recherche, sans rechargement ; Retour.
    p = await ouvrir(adm, '/dailylog');
    await p.waitForFunction(() => window.KairosDailyLogPage && !window.KairosDailyLogPage.etat().chargement);
    await latence(p, 800);
    await p.click('.dl-qui .search-combobox-input');
    await p.fill('.dl-qui .search-combobox-input', 'Rim');
    await p.keyboard.press('ArrowDown');
    await interaction(p, '« Daily log de » : choix au champ à recherche',
      () => p.keyboard.press('Enter'),
      async () => /utilisateur=3\b/.test((await etat(p)).url) && /Rim Inter/.test(await p.textContent('#dl-correction').catch(() => ''))
        && await p.evaluate(() => window.KairosDailyLogPage && !window.KairosDailyLogPage.etat().chargement),
      { focus: '.dl-qui .search-combobox-input', sansLatence: true });
    // Recette finale F4 : focus rendu au champ, sa liste reste fermée.
    await pause(300);
    etape('« Daily log de » : liste des personnes fermée sur la nouvelle page',
      await p.evaluate(() => { const l = document.querySelector('.dl-qui .search-combobox-list'); return !!l && l.hidden; }));
    await retour(p, '« Daily log de »', async () => await p.locator('#dl-correction').count() === 0 && !/utilisateur=/.test((await etat(p)).url));
    await p.close();

    // Recette finale F2 : la page précédente ne retient plus de « saisie »
    // (enregistrement échoué) après « Daily log de ».
    p = await ouvrir(adm, `/dailylog?utilisateur=${RIM}`);
    await p.waitForFunction(() => window.KairosDailyLogPage && !window.KairosDailyLogPage.etat().chargement);
    await p.route(/\/dailylog\/api\/jour\//, (r) => (r.request().method() === 'PUT' ? r.abort() : r.continue()));
    await p.locator('#dl-liste .dl-row .dl-plus:not([disabled])').first().click();
    await p.click('#dl-enregistrer');
    await attendre(() => p.evaluate(() => window.KairosDailyLogPage.etat().saved === 'erreur'));
    const avantQui = await p.evaluate(() => window.KairosModes.saisieEnCours());
    // Retour à « Moi » (option sans valeur, choisie comme le fait la liste).
    await p.evaluate(() => { const s = document.getElementById('dl-qui-select'); s.value = ''; s.dispatchEvent(new Event('change', { bubbles: true })); });
    await attendre(async () => await p.locator('#dl-correction').count() === 0
      && await p.evaluate(() => !window.KairosDailyLogPage.etat().chargement));
    const apresQui = await p.evaluate(() => [window.KairosDailyLogPage.etat().saved, window.KairosModes.saisieEnCours()]);
    etape('« Daily log de » après un échec : plus de saisie retenue par la page quittée (F2)',
      avantQui === true && apresQui[1] === false, [avantQui, apresQui]);
    await p.unroute(/\/dailylog\/api\/jour\//);
    await p.close();

    // Date simulée : rechargement voulu (toute la page dépend de la date),
    // mais focus et toast rendus.
    p = await ouvrir(adm, '/admin/journal');
    await p.fill('#bandeau-date-simulee', new Date(Date.now() - 2 * 86400000).toISOString().slice(0, 10));
    await Promise.all([p.waitForNavigation(), p.click('#bandeau-admin button:has-text("Appliquer")')]);
    await attendre(async () => await p.locator('#k-toasts .k-toast:has-text("Date simulée appliquée")').count() === 1);
    const apresDate = await p.evaluate(() => document.activeElement.id);
    etape('Date simulée : toast et focus rendus après le rechargement', apresDate === 'bandeau-date-simulee'
      && await p.locator('#k-toasts .k-toast:has-text("Date simulée appliquée")').count() === 1, apresDate);
    await Promise.all([p.waitForNavigation(), p.click('#bandeau-admin button:has-text("Revenir à aujourd’hui")')]);
    await p.close();

    // --- Recette finale du lot 13 : NF2, NF3, NF4, finitions, M15 ------------
    {
      // Plus Jakarta Sans : mots moins collés (O2).
      p = await ouvrir(adm, '/accueil');
      etape('Texte courant : espacement des mots ajouté (O2)', await p.evaluate(() => parseFloat(getComputedStyle(document.body).wordSpacing) > 0),
        await p.evaluate(() => getComputedStyle(document.body).wordSpacing));
      await p.close();

      // NF2 : zoom 400 % (320 × 225), aucune page ne défile horizontalement.
      const zoom = await contexte(navigateur, 'admin@x.tn', { largeur: 320, hauteur: 225 });
      const pz = await zoom.newPage();
      const debordZoom = [];
      for (const chemin of ['/accueil', '/projets', '/deadlines?vue=tous', '/notifications', '/admin/journal', '/utilisateurs', '/dailylog']) {
        await pz.goto(BASE + chemin);
        const d = await pz.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        if (d > 0) debordZoom.push([chemin, d]);
      }
      etape('NF2 : zoom 400 % (320 × 225), aucun défilement horizontal', debordZoom.length === 0, debordZoom);
      await zoom.close();

      // NF3 : 320 px, « Corriger le Daily log de <nom long> » dans sa carte.
      const nomRim = sql(`SELECT prenom || '|' || nom FROM utilisateur WHERE id=${RIM}`).split('|');
      sql(`UPDATE utilisateur SET prenom='Marie-Christine', nom='Ben Abdallah-Fontainebleau' WHERE id=${RIM}`);
      const etroit = await contexte(navigateur, 'admin@x.tn', { largeur: 320, hauteur: 800 });
      const pe = await etroit.newPage();
      await pe.goto(BASE + '/utilisateurs/' + RIM);
      const nf3 = await pe.evaluate(() => {
        const b = Array.from(document.querySelectorAll('main a.btn')).find((a) => /Corriger (le|son) Daily log/.test(a.textContent));
        const c = b.closest('.card').getBoundingClientRect(), r = b.getBoundingClientRect();
        return [document.documentElement.scrollWidth - document.documentElement.clientWidth, Math.round(r.right), Math.round(c.right)];
      });
      etape('NF3 : 320 px, bouton « Corriger le Daily log de … » dans sa carte, page sans débordement', nf3[0] <= 0 && nf3[1] <= nf3[2], nf3);
      sql(`UPDATE utilisateur SET prenom='${nomRim[0].replace(/'/g, "''")}', nom='${nomRim[1].replace(/'/g, "''")}' WHERE id=${RIM}`);

      // NF4 : 360 px, Tous les projets — les groupes de filtres ne bougent
      // pas quand chip-select.js remplace les listes.
      const tel = await contexte(navigateur, 'admin@x.tn', { largeur: 360, hauteur: 800 });
      const pt = await tel.newPage();
      let lacher;
      const attente = new Promise((r) => { lacher = r; });
      await pt.route(/chip-select\.[^/]*js/, async (route) => { await attente; route.continue(); });
      await pt.goto(BASE + '/projets', { waitUntil: 'commit' });
      await pt.waitForSelector('.projets-filtres .filtre-groupe:nth-child(4)', { state: 'attached' });
      // Revue visuelle P1-17 : sur téléphone, les filtres sont repliés dès le
      // premier rendu ; on les déplie (comme « Filtres · n ») pour mesurer
      // les places réservées pendant la construction des puces.
      await pt.evaluate(() => document.querySelector('.projets-filtres').classList.add('filtres-ouverts'));
      await pause(300);
      const positions = () => pt.evaluate(() => Array.from(document.querySelectorAll('.projets-filtres .filtre-groupe'))
        .map((g) => { const r = g.getBoundingClientRect(); return Math.round(r.left) + ',' + Math.round(r.top); }).join(' ')
        + ' | ' + Math.round(document.querySelector('.filtres-une-ligne').getBoundingClientRect().height));
      const avantPuces = await positions();
      lacher();
      await pt.waitForSelector('select[data-chip-init]', { state: 'attached' });
      await pause(200);
      const apresPuces = await positions();
      etape('NF4 : 360 px, filtres de Tous les projets immobiles à la construction des puces', avantPuces === apresPuces, [avantPuces, apresPuces]);
      // Revue visuelle P1-17 : sur téléphone, filtres repliés dès le premier
      // rendu derrière « Filtres · n » ; le bouton les déplie (puces prêtes).
      await pt.evaluate(() => document.querySelector('.projets-filtres').classList.remove('filtres-ouverts'));
      const replie = await pt.evaluate(() => document.querySelector('.projets-filtres-groupes').getBoundingClientRect().height);
      await pt.click('[data-filtres-bascule]');
      const deplie = await pt.evaluate(() => ({ h: Math.round(document.querySelector('.projets-filtres-groupes').getBoundingClientRect().height),
        expanded: document.querySelector('[data-filtres-bascule]').getAttribute('aria-expanded'),
        texte: document.querySelector('[data-filtres-bascule]').textContent.replace(/\s+/g, ' ').trim(),
        puces: document.querySelectorAll('.projets-filtres .chip-opt').length }));
      etape('P1-17 : 360 px, filtres repliés derrière « Filtres · n », dépliés au clic', replie === 0 && deplie.h > 100
        && deplie.expanded === 'true' && /^Filtres · \d+$/.test(deplie.texte) && deplie.puces > 0, [replie, deplie]);

      // M15 : cibles ≥ 24 px à 375 px (lien du nom des cartes Projets, Journal).
      await pt.setViewportSize({ width: 375, height: 812 });
      await pt.unroute(/chip-select\.[^/]*js/);
      await pt.goto(BASE + '/projets');
      const liens = await pt.evaluate(() => Array.from(document.querySelectorAll('.ptable-lien')).map((a) => Math.round(a.getBoundingClientRect().height)));
      await pt.goto(BASE + '/admin/journal');
      const journal = await pt.evaluate(() => Array.from(document.querySelectorAll('main a, main summary'))
        .map((a) => a.getBoundingClientRect()).filter((r) => r.width && r.height).map((r) => Math.round(r.height)));
      etape('M15 : 375 px, lien du nom des cartes Projets ≥ 24 px', liens.length > 0 && Math.min(...liens) >= 24, liens.slice(0, 5));
      etape('M15 : 375 px, Journal : liens et « Voir les données » ≥ 24 px', journal.length > 0 && Math.min(...journal) >= 24, Math.min(...journal));

      // « MODE TEST » entier à 375 px (Agir comme).
      await pt.goto(BASE + '/admin/voir-comme');
      await pt.evaluate((id) => { document.getElementById('voir-comme-compte').value = String(id); }, RIM);
      await Promise.all([pt.waitForNavigation(), pt.click('button:has-text("Agir comme (mode test)")')]);
      const etiquette = await pt.evaluate(() => {
        const e = document.querySelector('#bandeau-admin .bandeau-admin-etiquette'), r = e.getBoundingClientRect();
        return [getComputedStyle(e).fontSize, e.innerText.trim(), getComputedStyle(e, '::after').content, e.scrollWidth <= e.clientWidth + 1, r.right <= innerWidth];
      });
      etape('375 px, Agir comme : « Mode test » écrit en entier dans le bandeau', etiquette[0] !== '0px' && /^mode test$/i.test(etiquette[1])
        && (etiquette[2] === 'none' || etiquette[2] === 'normal') && etiquette[3] && etiquette[4], etiquette);
      await Promise.all([pt.waitForNavigation(), pt.click('#bandeau-admin button:has-text("Revenir à mon compte")')]);
      await tel.close();
      await etroit.close();

      // Gantt rogné par le panneau ouvert : ombre au bord droit.
      const aliG = await contexte(navigateur, 'ali@x.tn', { largeur: 1024, hauteur: 800 });
      p = await ouvrir(aliG, '/deadlines');
      await p.click('.g-row[data-open-tache="1"] a.g-bar');
      await p.waitForSelector('#tache-titre-1');
      const ombre = await attendre(() => p.evaluate(() => {
        const c = document.getElementById('gantt-carte'), o = c && c.querySelector('.gantt-ombre');
        return !!c && c.scrollWidth > c.clientWidth && c.classList.contains('k-defile-droite') && !!o && getComputedStyle(o, '::after').opacity === '1';
      }));
      etape('Gantt rogné par le panneau : ombre au bord droit', !!ombre,
        await p.evaluate(() => { const c = document.getElementById('gantt-carte'); return [c.scrollWidth, c.clientWidth, c.className]; }));
      await p.evaluate(() => { const c = document.getElementById('gantt-carte'); c.scrollLeft = c.scrollWidth; });
      etape('Gantt défilé jusqu’au bout : plus d’ombre',
        !!(await attendre(() => p.evaluate(() => !document.getElementById('gantt-carte').classList.contains('k-defile-droite')))));
      await p.close();
      await aliG.close();

      // Téléphone : le toast passe au-dessus de la feuille de tâche.
      const aliTel = await contexte(navigateur, 'ali@x.tn', { largeur: 375, hauteur: 812 });
      p = await ouvrir(aliTel, '/projets/1?tache=1');
      await p.waitForSelector('#tache-1-etat-bloque');
      await p.click('#tache-1-etat-bloque');
      await p.fill('#tache-1-motif', 'Attente des plans');
      await p.click('#tache-1-blocage-valider');
      await attendre(async () => await p.locator('#k-toasts .k-toast-action:has-text("Annuler")').count() === 1);
      const place = await p.evaluate(() => {
        const t = document.querySelector('#k-toasts .k-toast').getBoundingClientRect(), d = document.getElementById('dialog-tache').getBoundingClientRect();
        return [Math.round(t.top), Math.round(t.bottom), Math.round(d.top), innerHeight];
      });
      etape('Téléphone : toast au-dessus de la feuille de tâche (actions du bas dégagées)', place[1] <= place[2] + 24, place);
      await p.click('#k-toasts .k-toast-action:has-text("Annuler")');
      await attendre(() => sql('SELECT etat FROM tache WHERE id=1') === 'en_cours');
      await p.close();
      await aliTel.close();
    }

    // --- 9. Largeurs et thèmes : ni débordement ni bandeau de plus d'une ligne ---
    const pages = ['/deadlines?vue=tous', '/notifications', '/admin/journal', '/utilisateurs', `/utilisateurs/${RIM}`, '/utilisateurs/moi', `/utilisateurs/${RIM}/profil`];
    for (const theme of ['light', 'dark']) {
      for (const largeur of [1440, 1024, 768, 375]) {
        const ctx = await contexte(navigateur, 'admin@x.tn', { largeur, hauteur: 900, theme });
        const pv = await ctx.newPage();
        pv.on('pageerror', (e) => erreursJs.push(largeur + ' : ' + e.message));
        const debord = [];
        for (const chemin of pages) {
          await pv.goto(BASE + chemin);
          const d = await pv.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
          if (d > 0) debord.push([chemin, d]);
          if (chemin === '/deadlines?vue=tous') {
            const mobile = await pv.isVisible('.deadlines-semaines');
            if (largeur <= 600 !== mobile) debord.push(['liste par semaine attendue', largeur]);
          }
          if (chemin === '/utilisateurs' && largeur === 375) {
            const cartes = await pv.evaluate(() => getComputedStyle(document.querySelector('.uhead') || document.body).display);
            if (cartes !== 'none') debord.push(['cartes Utilisateurs', cartes]);
          }
          if (CAPTURES && (largeur === 1440 || largeur === 375)) await pv.screenshot({ path: path.join(CAPTURES, `e2e-13d-${chemin.replace(/[/?=]+/g, '_')}-${largeur}-${theme}.png`) });
        }
        const hb = await pv.evaluate(() => { const b = document.getElementById('bandeau-admin'); return b ? Math.round(b.getBoundingClientRect().height) : 0; });
        etape(`${largeur} px ${theme} : aucun débordement horizontal (${pages.length} pages)`, debord.length === 0, debord);
        etape(`${largeur} px ${theme} : bandeau du mode test sur une ligne (≤ 41 px)`, hb > 0 && hb <= 41, hb);
        await ctx.close();
      }
    }
    await adm.close();
    etape('aucune erreur JavaScript ni boîte native', erreursJs.length === 0, erreursJs);
  } catch (err) {
    ko++;
    console.log('KO  exception : ' + (err && err.stack ? err.stack.split('\n').slice(0, 4).join('\n    ') : err));
  } finally {
    await navigateur.close();
  }
  console.log(`\n${ok} OK, ${ko} KO`);
  process.exit(ko ? 1 : 0);
})();

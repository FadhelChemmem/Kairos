/* Scénario Playwright « stabilité » (lot 13, H1 — demande du gérant :
 * « je veux pas qu'il y ait des trucs où les boutons de filtres bougent ») :
 * test GÉNÉRIQUE de mise en page. Sur chaque page (accueil, projets, fiche
 * et panneau de tâche, deadlines, Daily log, notifications et cloche,
 * utilisateurs et fiche, journal, profil, mes informations, bandeau des
 * modes), à 1440 / 1024 / 768 / 375 px, en clair et en sombre :
 * - chaque contrôle à bascule (puces, segments, interrupteurs, états,
 *   détails, outils du Daily log…) est activé puis désactivé ; avant et
 *   après chaque clic, getBoundingClientRect de TOUS les contrôles visibles :
 *   aucun ne bouge de plus de 1 px (défilement déduit) et le contrôle
 *   actionné garde sa largeur (± 1 px). Un « détail » qui se déplie (résumé
 *   <summary>, « + Ajouter ») ne doit déplacer que ce qui est sous lui ;
 * - survol de chaque contrôle visible : rien ne bouge ;
 * - focus clavier (Tab depuis le haut de la page) : rien ne bouge.
 * Les zones de contenu rechargé par un filtre (résultats, fil, liste du
 * jour) sont exclues : c'est le contenu qui change, pas les contrôles.
 *
 * Lancement : KAIROS_E2E_SCENARIO=stabilite bash tests_e2e/lancer.sh
 * (base jetable + tests_e2e/seed_stabilite.py). Variables : KAIROS_E2E_URL,
 * KAIROS_E2E_DB, PLAYWRIGHT_MODULE ; KAIROS_STABILITE_LARGEURS (« 1440,375 »)
 * et KAIROS_STABILITE_THEMES (« light ») pour restreindre ;
 * KAIROS_STABILITE_PAGES (« projets,dailylog ») ; KAIROS_STABILITE_JSON :
 * fichier où écrire les mesures (déplacement maximal par page).
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
let playwright;
try { playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright'); }
catch (e) { playwright = require('/opt/node-tools/node_modules/playwright'); }
const { chromium } = playwright;

const BASE = process.env.KAIROS_E2E_URL || 'http://127.0.0.1:8798';
const DB = process.env.KAIROS_E2E_DB || 'kairos_e2e_stabilite';
const MDP = 'Kairos2026!';
const LARGEURS = (process.env.KAIROS_STABILITE_LARGEURS || '1440,1024,768,375').split(',').map(Number);
const THEMES = (process.env.KAIROS_STABILITE_THEMES || 'light,dark').split(',');
const FILTRE_PAGES = process.env.KAIROS_STABILITE_PAGES ? process.env.KAIROS_STABILITE_PAGES.split(',') : null;
const SEUIL = 1;
const NB_TAB = 30;
const NB_SURVOL = 30;

let ok = 0, ko = 0;
const erreursJs = [];
const mesures = {};   // page -> largeur/theme -> déplacement max
function etape(nom, cond, detail) {
  if (cond) { ok++; console.log('OK  ' + nom); }
  else { ko++; console.log('KO  ' + nom + (detail !== undefined ? ' — ' + JSON.stringify(detail).slice(0, 600) : '')); }
}
function sql(requete) {
  return execFileSync('psql', ['-X', '-At', '-d', DB, '-c', requete], { encoding: 'utf8' }).trim();
}
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
function noter(page, cle, valeur) {
  mesures[page] = mesures[page] || {};
  mesures[page][cle] = Math.max(mesures[page][cle] || 0, Math.round(valeur * 10) / 10);
}

// Sonde injectée dans chaque page : relevé des contrôles visibles.
const SONDE = `
(() => {
  const INTER = 'button, a[href], input:not([type=hidden]), select, textarea, summary, [role=button], [role=switch], [role=tab], [role=option], [tabindex]:not([tabindex="-1"])';
  let seq = 0;
  function visible(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    if (getComputedStyle(el).visibility === 'hidden') return false;
    if (el.closest('[hidden], dialog:not([open]), .sr-only')) return false;
    // Contenu d'un <details> replié (content-visibility: hidden : la boîte
    // garde sa dernière position).
    if (el.checkVisibility && !el.checkVisibility({ visibilityProperty: true })) return false;
    return true;
  }
  // Position « dans le document » : défilement de la page et des conteneurs
  // qui défilent (fenêtre, panneau) déduit ; un élément fixe ou collant
  // (ou dans une fenêtre ouverte) reste en coordonnées de l'écran.
  // Un élément collant (sticky) non encore « collé » suit le document : il
  // n'a bougé que si ses coordonnées ont changé dans le document ET à l'écran.
  function position(el) {
    const r = el.getBoundingClientRect();
    let x = r.left, y = r.top;
    if (getComputedStyle(el).position === 'fixed') return { x, y, f: true };
    for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (n !== el && /(auto|scroll)/.test(cs.overflowY + cs.overflowX) && n !== document.body) { x += n.scrollLeft; y += n.scrollTop; }
      if (cs.position === 'fixed' || (n.tagName === 'DIALOG' && n.open)) return { x, y, f: true };
      if (cs.position === 'sticky') return { x, y, f: true, xd: r.left + scrollX, yd: r.top + scrollY };
    }
    return { x: x + scrollX, y: y + scrollY };
  }
  function sig(el) {
    return [el.tagName, el.id || '', (el.getAttribute('aria-label') || '').slice(0, 40), el.getAttribute('name') || '',
      (el.getAttribute('href') || '').slice(0, 60), (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 40)].join('|');
  }
  function cle(el) { if (el.id) return '#' + el.id; if (!el.dataset.st) el.dataset.st = 's' + (++seq); return el.dataset.st; }
  window.__st = {
    releve(exclure, sansFocus) {
      const out = {};
      const ex = (exclure || []).join(', ');
      // Zones exclues (contenu rechargé) : ce qui est SOUS elles, dans la
      // même colonne, suit leur hauteur — pas un contrôle qui bouge.
      const zones = ex ? [...document.querySelectorAll(ex)].filter(visible).map((z) => {
        const p = position(z), r = z.getBoundingClientRect();
        return { x: p.x, y: p.y, w: r.width, f: !!p.f };
      }) : [];
      document.querySelectorAll(INTER).forEach((el) => {
        if (!visible(el) || (ex && el.closest(ex))) return;
        if (sansFocus && el === document.activeElement) return;
        const r = el.getBoundingClientRect();
        const p = position(el);
        const sous = zones.some((z) => !z.f && !p.f && p.y >= z.y && p.x < z.x + z.w && p.x + r.width > z.x);
        out[cle(el)] = { sig: sig(el), x: p.x, y: p.y, xd: p.xd, yd: p.yd, w: r.width, h: r.height, sous };
      });
      return out;
    },
    rect(el) {
      if (!el || !visible(el)) return null;
      const r = el.getBoundingClientRect();
      const p = position(el);
      return { x: p.x, y: p.y, w: r.width, h: r.height };
    },
    animations() {
      return document.getAnimations().some((a) => a.playState === 'running'
        && a.effect && a.effect.getComputedTiming().iterations !== Infinity
        && Number(a.effect.getComputedTiming().endTime) < 3000);
    },
  };
})();
`;

function comparer(a, b, ref) {
  const bougent = [];
  const parSig = {};
  for (const k in b) (parSig[b[k].sig] = parSig[b[k].sig] || []).push(b[k]);
  const nbA = {};
  for (const k in a) nbA[a[k].sig] = (nbA[a[k].sig] || 0) + 1;
  for (const k in a) {
    const x = a[k];
    if (ref && x.y >= ref.y + ref.h - SEUIL) continue;   // sous un détail qui se déplie
    if (x.sous) continue;                                // sous une zone de contenu rechargé
    let y = b[k];
    // Élément remplacé (fragment partiel) : retrouvé par sa signature, si
    // elle est unique avant comme après.
    if (!y) { const c = parSig[x.sig]; y = c && c.length === 1 && nbA[x.sig] === 1 ? c[0] : null; }
    if (!y) continue;
    let d = Math.max(Math.abs(y.x - x.x), Math.abs(y.y - x.y), Math.abs(y.w - x.w), Math.abs(y.h - x.h));
    if (x.yd !== undefined && y.yd !== undefined && d > SEUIL) {
      const dDoc = Math.max(Math.abs(y.xd - x.xd), Math.abs(y.yd - x.yd), Math.abs(y.w - x.w), Math.abs(y.h - x.h));
      d = Math.min(d, dDoc);
    }
    if (d > SEUIL) bougent.push({ c: x.sig.split('|').filter(Boolean).slice(0, 3).join('|').slice(0, 50), dx: +(y.x - x.x).toFixed(1), dy: +(y.y - x.y).toFixed(1), dw: +(y.w - x.w).toFixed(1), dh: +(y.h - x.h).toFixed(1) });
  }
  return bougent;
}
const ampleur = (l) => l.reduce((m, x) => Math.max(m, Math.abs(x.dx), Math.abs(x.dy), Math.abs(x.dw), Math.abs(x.dh)), 0);

const EXCLURE = ['#k-toasts', '.k-progression', '#recherche-globale-resultats', '.k-confirmation'];

async function contexte(navigateur, largeur, theme, compte) {
  const ctx = await navigateur.newContext({ viewport: { width: largeur, height: largeur < 600 ? 812 : 900 }, colorScheme: theme,
    locale: 'fr-FR', timezoneId: 'Africa/Tunis' });
  await ctx.addInitScript(SONDE);
  const p = await ctx.newPage();
  p.on('pageerror', (e) => erreursJs.push(e.message));
  p.on('dialog', (d) => { erreursJs.push('boîte native : ' + d.message()); d.dismiss(); });
  let enVol = 0;
  p.on('request', () => { enVol++; });
  p.on('requestfinished', () => { enVol--; });
  p.on('requestfailed', () => { enVol--; });
  p.enVol = () => enVol;
  await p.goto(BASE + '/connexion');
  await p.fill('#email', compte || 'admin@x.tn');
  await p.fill('#password', MDP);
  await Promise.all([p.waitForNavigation(), p.click('button[type=submit]')]);
  return { ctx, p };
}

async function apaiser(p) {
  const fin = Date.now() + 8000;
  let calme = 0;
  while (Date.now() < fin) {
    if (p.enVol() <= 0) { calme += 40; if (calme >= 160) break; } else calme = 0;
    await pause(40);
  }
  const fin2 = Date.now() + 1500;
  while (Date.now() < fin2 && await p.evaluate(() => window.__st.animations()).catch(() => false)) await pause(40);
  await pause(60);
}
const neutre = (p) => p.mouse.move(2, 300);

/** Une suite de clics (bascule aller-retour) mesurée clic par clic. */
async function bascule(p, page, largeur, b) {
  const suite = b.suite || [b.sel, b.sel];
  const exclure = EXCLURE.concat(b.exclure || []);
  const ecarts = [];
  for (let i = 0; i < suite.length; i++) {
    const sel = suite[i];
    const loc = p.locator(sel).first();
    if (!(await loc.count()) || !(await loc.isVisible()) || await loc.isDisabled()) { console.log('    (absent ou désactivé : ' + b.nom + ', clic ' + (i + 1) + ')'); break; }
    await loc.scrollIntoViewIfNeeded();
    await neutre(p);
    await apaiser(p);
    const avant = await p.evaluate((e) => window.__st.releve(e), exclure);
    const r0 = await loc.evaluate((el) => window.__st.rect(el));
    await loc.click();
    await apaiser(p);
    await neutre(p);
    await pause(150);
    const apres = await p.evaluate((e) => window.__st.releve(e), exclure);
    // Contrôle retiré par l'action (ex. « Signaler le blocage ») : pas d'attente.
    const r1 = (await p.locator(sel).count()) ? await p.locator(sel).first().evaluate((el) => window.__st.rect(el)).catch(() => null) : null;
    const bougent = comparer(avant, apres, b.divulgation ? r0 : null);
    const dLarg = r0 && r1 ? Math.abs(r1.w - r0.w) : 0;
    ecarts.push({ clic: i + 1, bougent: bougent.slice(0, 6), largeur: +dLarg.toFixed(1) });
    noter(page, `${largeur}`, Math.max(ampleur(bougent), dLarg));
    if (b.apres) await b.apres(p);
  }
  const mauvais = ecarts.filter((e) => e.bougent.length || e.largeur > SEUIL);
  etape(`${page} ${largeur} : « ${b.nom} » — rien ne bouge, largeur gardée`, mauvais.length === 0, mauvais);
}

async function survols(p, page, largeur, exclure) {
  await neutre(p);
  await apaiser(p);
  const ex = EXCLURE.concat(exclure || []);
  const base = await p.evaluate((e) => window.__st.releve(e), ex);
  const cibles = await p.evaluate(() => {
    const vus = [];
    for (const el of document.querySelectorAll('button, a[href], summary, [role=switch], .chip-opt, input, select')) {
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.top < 0 || r.bottom > innerHeight || r.left < 0 || r.right > innerWidth) continue;
      if (el.closest('[hidden], dialog:not([open]), .sr-only, #k-toasts')) continue;
      if (el.checkVisibility && !el.checkVisibility({ visibilityProperty: true })) continue;
      vus.push({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
    }
    return vus;
  });
  const pas = Math.max(1, Math.ceil(cibles.length / NB_SURVOL));
  const mauvais = [];
  for (let i = 0; i < cibles.length; i += pas) {
    await p.mouse.move(cibles[i].x, cibles[i].y);
    await pause(150);
    const r = comparer(base, await p.evaluate((e) => window.__st.releve(e), ex));
    if (r.length) mauvais.push(r.slice(0, 3));
    noter(page, `${largeur}`, ampleur(r));
  }
  await neutre(p);
  etape(`${page} ${largeur} : survol — rien ne bouge`, mauvais.length === 0, mauvais.slice(0, 3));
}

async function focus(p, page, largeur, exclure) {
  await p.evaluate(() => { window.scrollTo(0, 0); if (document.activeElement) document.activeElement.blur(); });
  await apaiser(p);
  const ex = EXCLURE.concat(exclure || []);
  const base = await p.evaluate((e) => window.__st.releve(e), ex);
  const mauvais = [];
  for (let i = 0; i < NB_TAB; i++) {
    await p.keyboard.press('Tab');
    await pause(60);
    // Page ramenée en haut : un élément collant (sous-barre) reprend sa
    // place naturelle, comme dans le relevé de départ.
    await p.evaluate(() => window.scrollTo(0, 0));
    const r = comparer(base, await p.evaluate((e) => window.__st.releve(e, true), ex));
    if (r.length) {
      const qui = await p.evaluate(() => { const a = document.activeElement; return a ? a.tagName + (a.id ? '#' + a.id : '') + ' ' + (a.textContent || '').trim().slice(0, 30) : ''; });
      mauvais.push({ focus: qui, bougent: r.slice(0, 3) });
    }
    noter(page, `${largeur}`, ampleur(r));
  }
  await p.evaluate(() => { if (document.activeElement) document.activeElement.blur(); });
  etape(`${page} ${largeur} : focus clavier (Tab ×${NB_TAB}) — rien ne bouge`, mauvais.length === 0, mauvais.slice(0, 3));
}

/** Un jour ouvré vierge de l'Admin (le jeu de données remplit les 3
 *  derniers jours) : 7 jours en arrière, ramené au vendredi si besoin. */
function jourOuvreVierge(recul = 7) {
  const d = new Date(Date.now() - recul * 86400000);
  while (d.getUTCDay() === 0 || d.getUTCDay() === 6) d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

// Bascules par page (sélecteurs stables du jeu de données).
const PAGES = [
  { nom: 'accueil', chemin: '/accueil', bascules: [
    { nom: 'Thème', sel: '#theme-toggle' },
    { nom: 'Mode test (bandeau)', sel: '#bandeau-admin-outils > summary', divulgation: true },
    // Lot 14 (P0-1) : section repliable « Bloquées (n) » sous Mes tâches.
    { nom: 'Bloquées (détail)', sel: '#taches-bloquees > summary', divulgation: true },
    // Lot 14 : tuiles de la Vue d'ensemble (la liste se déplie sous les
    // tuiles) et bascule « Les miennes | Toutes ».
    { nom: 'Tuile « Tâches en retard » (dépliée / repliée)', sel: '#tuile-retard', divulgation: true },
    { nom: 'Tuile « Projets sans tâche ouverte » puis « Tâches bloquées »', suite: ['#tuile-projets_sans_tache', '#tuile-bloquees', '#tuile-bloquees'], divulgation: true },
    { nom: 'Les miennes / Toutes', suite: ['#tdp-miennes', '#tdp-toutes'], exclure: ['#accueil-taches'] },
    // Lot 14 (revue produit P1-3) : fil filtrable, « Commenter » replié.
    { nom: 'Fil : Tout · Échanges · Activité', suite: ['#fil-filtre-accueil-activite', '#fil-filtre-accueil-tout', '#fil-filtre-accueil-echanges'],
      exclure: ['#fil-liste', '#fil-suite'] },
    { nom: 'Fil : « Commenter » (déplier / replier)', sel: '#fil-liste .post-action-commenter', divulgation: true },
  ] },
  { nom: 'accueil-activite', chemin: '/accueil?fil=activite', bascules: [
    { nom: 'Fil : regroupement (détail)', sel: '#fil-liste .fil-groupe-details > summary', divulgation: true },
  ] },
  // Lot 14 : carte « À traiter » du chef de projet (ali, chef du projet 1).
  { nom: 'accueil-chef', chemin: '/accueil', compte: 'ali@x.tn', bascules: [
    { nom: 'Ligne « À traiter » (dépliée / repliée)', sel: '.at-lignes .at-ligne >> nth=0', divulgation: true },
    { nom: 'Les miennes / Toutes (chef)', suite: ['#tdp-miennes', '#tdp-toutes'], exclure: ['#accueil-taches'] },
  ] },
  { nom: 'projets', chemin: '/projets', exclure: ['#projets-resultats'], bascules: [
    { nom: 'puce État « Terminé »', sel: '.projets-filtres .chip-opt:has-text("Terminé")' },
    { nom: 'puce État « En cours »', sel: '.projets-filtres .chip-opt:has-text("En cours")' },
    { nom: 'puce Phase « APS »', sel: '.projets-filtres .chip-opt:has-text("APS")' },
    { nom: 'puce Lots « GO » (3 états)', sel: '.projets-filtres .chip-tristate:has-text("GO")', suite: Array(3).fill('.projets-filtres .chip-tristate:has-text("GO")') },
    { nom: 'puce Chef (avatar)', sel: '.projets-filtres .chip-avatar >> nth=0' },
  ] },
  { nom: 'fiche', chemin: '/projets/1', exclure: ['#fil-posts .fil-liste', '#fil-posts > .fil-liste'], bascules: [
    { nom: 'Tâches closes (détail)', sel: '#taches-closes > summary', divulgation: true },
    { nom: 'Réaction ✓ d’un post', sel: '#fil-posts .post-action[aria-pressed]' },
    { nom: 'Fil : Tout · Échanges · Activité', suite: ['#fil-filtre-projet-activite', '#fil-filtre-projet-tout', '#fil-filtre-projet-echanges'],
      exclure: ['#fil-posts', '#fil-suite'] },
    { nom: 'Fil : « Commenter » (déplier / replier)', sel: '#fil-posts .post-action-commenter', divulgation: true },
  ] },
  { nom: 'panneau', chemin: '/projets/1', exclure: ['#fil-posts'], ouvrir: async (p) => {
    await p.click('[data-open-tache="20"] [data-ouvrir-tache]');
    await p.waitForSelector('#tache-fenetre-20');
  }, bascules: [
    // Lot 14 (P0-1) : « Bloquée » ouvre « Qu’est-ce qui bloque ? » par-dessus
    // le panneau, « Signaler le blocage » l’enregistre (motif sous les états,
    // ligne réservée), « En cours » le lève : rien ne bouge à aucun clic.
    { nom: 'États de la tâche (Bloquée + motif ↔ En cours)',
      suite: ['#tache-20-etat-bloque', '#tache-20-blocage-valider', '#tache-20-etat-en_cours'],
      apres: async (p) => {
        const champ = p.locator('#tache-20-motif');
        if (await champ.count() && await champ.isVisible()) await champ.fill('Attente des plans archi indice B');
      } },
    { nom: 'Question du blocage ouverte puis « Annuler »', suite: ['#tache-20-etat-bloque', '#tache-20-blocage [data-blocage-annuler]'] },
  ] },
  { nom: 'deadlines', chemin: '/deadlines', exclure: ['#deadlines-contenu'], bascules: [
    { nom: 'Mes projets / Tous les projets', suite: ['[data-deadlines-bascule] a[data-vue="tous"]', '[data-deadlines-bascule] a[data-vue=""]'] },
  ] },
  // Lot 14 (P0-1) : section « Bloquées (n) » sous le Gantt (sans exclure le contenu).
  { nom: 'deadlines-bloquees', chemin: '/deadlines', bascules: [
    { nom: 'Bloquées (détail)', sel: '#deadlines-bloquees > summary', divulgation: true },
  ] },
  { nom: 'dailylog', chemin: '/dailylog', bascules: [
    { nom: 'Marquer absent / Annuler l’absence', sel: '#dl-absent', exclure: ['#dl-liste', '#dl-ajout'] },
    { nom: 'Ligne désactivée / réactivée', sel: '#dl-liste .dl-pinfo' },
    { nom: 'Jour précédent (‹ ×2)', suite: ['#dl-prec', '#dl-prec'], exclure: ['#dl-liste', '#dl-ajout'] },
    { nom: 'Calendrier', sel: '#dl-date' },
    { nom: 'Journée type − / +', suite: ['#dl-obj-moins', '#dl-obj-plus'] },
    // Lot 14 : le catalogue reste ouvert après un ajout ; « Terminé » le ferme.
    { nom: '+ Ajouter un projet / Terminé', suite: ['#dl-ajouter', '#dl-catalogue-fini'], divulgation: true },
  ] },
  // Lot 14 (revue produit P0-4) : journée vierge, lignes proposées à 0 h.
  { nom: 'dailylog-vierge', chemin: '/dailylog?date=' + jourOuvreVierge(), bascules: [
    { nom: 'Ligne proposée + / −', suite: ['#dl-liste .dl-row .dl-plus', '#dl-liste .dl-row .dl-minus'] },
    { nom: 'Ligne proposée activée / désactivée (nom)', sel: '#dl-liste .dl-pinfo' },
    { nom: 'Catalogue : ajout (resté ouvert) puis Terminé', suite: ['#dl-ajouter', '#dl-catalogue-corps [data-add]', '#dl-catalogue-fini'], divulgation: true,
      exclure: ['#dl-liste', '#dl-propositions'] },
    { nom: '× retire une ligne proposée', suite: ['#dl-liste .dl-retirer:not(.dl-retirer-cache)'], divulgation: true },
  ] },
  // Lot 14 (revue produit P1-9) : Daily log de l'équipe, semaine en partiel.
  { nom: 'dailylog-equipe', chemin: '/dailylog/equipe', exclure: ['.dlq-defile', '.dlq-resume', '.dlq-legende'], bascules: [
    { nom: 'Semaine précédente / suivante', suite: ['#dlq-prec', '#dlq-suiv'] },
    { nom: 'Semaine précédente / Cette semaine', suite: ['#dlq-prec', '#dlq-courante'] },
  ] },
  { nom: 'notifications', chemin: '/notifications', avant: () => sql("UPDATE notification SET lu = false WHERE utilisateur_id = 1 AND message <> 'Ancienne notification déjà lue.'"),
    bascules: [
      { nom: 'Cloche (aperçu)', sel: '#notifs-cloche', exclure: ['#notifs-popover'] },
      { nom: 'Marquer comme lue', suite: ['#notifications-liste .notif-lire-btn'] },
      { nom: 'Tout marquer comme lu', suite: ['#notifs-toutes-lues'] },
    ] },
  { nom: 'utilisateurs', chemin: '/utilisateurs', bascules: [
    { nom: 'Interrupteur Compte actif (liste)', sel: '#actif-3' },
  ] },
  { nom: 'fiche-utilisateur', chemin: '/utilisateurs/3', bascules: [
    { nom: 'Interrupteur Compte actif (fiche)', sel: '#fiche-actif' },
  ] },
  { nom: 'journal', chemin: '/admin/journal', bascules: [
    { nom: 'Voir les données (détail)', sel: '.journal-details > summary', divulgation: true },
  ] },
  { nom: 'profil', chemin: '/utilisateurs/3/profil', bascules: [
    { nom: 'Réaction ✓ d’un post', sel: '.post-action[aria-pressed]' },
    { nom: 'Fil : Tout · Échanges · Activité', suite: ['#fil-filtre-profil-tout', '#fil-filtre-profil-activite', '#fil-filtre-profil-echanges'],
      exclure: ['#profil-posts'] },
  ] },
  { nom: 'mes-informations', chemin: '/utilisateurs/moi', bascules: [
    // Lot 14 : « Proposer mes tâches en cours dans le Daily log ».
    { nom: 'Réglage « Proposer mes tâches en cours »', sel: '#pref-dl-proposer' },
  ] },
];

// --- Interactions de la revue (P0 / P1) : un test par correctif ----------
async function latence(p, ms) {
  const cdp = await p.context().newCDPSession(p);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: ms, downloadThroughput: -1, uploadThroughput: -1 });
}
const rect = (p, sel) => p.locator(sel).first().evaluate((el) => { const r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; });
const proche = (a, b) => !!a && !!b && Math.abs(a.x - b.x) <= SEUIL && Math.abs(a.y - b.y) <= SEUIL;

async function interactions(navigateur) {
  console.log('\n=== Interactions (revue P0 / P1)');
  // Chaque cas dans son contexte : un échec n'arrête pas les suivants.
  async function cas(nom, largeur, fn) {
    const { ctx, p } = await contexte(navigateur, largeur, 'light');
    try { await fn(p, ctx); }
    catch (e) { etape(nom, false, String(e.message).split('\n')[0]); }
    finally { await ctx.close(); }
  }
  async function clicRapide(p, sel) {
    const b = await p.locator(sel).boundingBox();
    await p.mouse.click(b.x + b.width / 2, b.y + b.height / 2);
  }

  await cas('P0-1 : clics pris à la suite pendant une mise à jour', 1440, async (p) => {
    // Réseau du bureau en Guyane (+200 ms) : 4 interrupteurs à 220 ms d'écart.
    await p.goto(BASE + '/utilisateurs?q=compte0');
    await apaiser(p);
    await latence(p, 200);
    const ids = ['#actif-100', '#actif-101', '#actif-102', '#actif-103'];
    for (const id of ids) { await clicRapide(p, id); await pause(220); }
    await pause(1500);
    await apaiser(p);
    await latence(p, 0);
    const etats = await Promise.all(ids.map((id) => p.getAttribute(id, 'aria-checked')));
    const enBase = sql("SELECT string_agg(actif::text, ',' ORDER BY id) FROM utilisateur WHERE id BETWEEN 100 AND 103");
    etape('P0-1 : 4 interrupteurs cliqués à la suite → 4 bascules (écran et base)', etats.every((e) => e === 'false') && enBase === 'false,false,false,false', [etats, enBase]);
    sql('UPDATE utilisateur SET actif = true WHERE id BETWEEN 100 AND 103');
  });

  await cas('P1-5 : focus après « Annuler »', 768, async (p) => {
    // Feuille de tâche (768 px, modale) : état changé puis « Annuler » au
    // clavier ; le focus revient au bouton d'état (jamais sur <body>).
    await p.goto(BASE + '/projets/1?tache=22');
    await p.waitForSelector('#tache-22-etat-bloque');
    await apaiser(p);
    await p.focus('#tache-22-etat-bloque');
    // Lot 14 : Entrée ouvre « Qu’est-ce qui bloque ? », le motif part par Entrée.
    await p.keyboard.press('Enter');
    await p.waitForSelector('#tache-22-motif:focus');
    await p.keyboard.type('Attente des plans');
    await p.keyboard.press('Enter');
    await p.waitForSelector('#k-toasts .k-toast-action');
    await apaiser(p);
    await p.focus('#k-toasts .k-toast-action');
    await p.keyboard.press('Enter');
    await attendreQue(() => sql('SELECT etat FROM tache WHERE id=22') === 'en_cours');
    await apaiser(p);
    await pause(300);
    const f = await p.evaluate(() => { const a = document.activeElement; return { id: a.id, dansFenetre: !!a.closest('#dialog-tache') }; });
    etape('P1-5 : après « Annuler », focus sur le contrôle d’origine (dans la fenêtre)', f.id === 'tache-22-etat-bloque' && f.dansFenetre, f);
  });

  // Recette du lot 14, n° 1 : sur téléphone, la tâche touchée dans le
  // catalogue du Daily log (resté ouvert) ne bouge pas, même quand la même
  // clé est affichée plus haut (« projet seul » sous « Tâches ▸ » et ligne
  // du projet) ou que la liste du catalogue a défilé.
  await cas('Recette lot 14 n° 1 : catalogue du Daily log à 375 px', 375, async (p) => {
    // Un autre jour vierge que celui de la page « dailylog-vierge » (mesurée ensuite).
    await p.goto(BASE + '/dailylog?date=' + jourOuvreVierge(10));
    await p.waitForSelector('.dl9.dl-pret');
    await apaiser(p);
    await p.click('#dl-ajouter');
    await p.fill('#dl-recherche', '21114');
    await p.waitForSelector('#dl-catalogue-corps [data-taches]');
    await p.click('#dl-catalogue-corps [data-taches]');
    await p.waitForSelector('#dl-catalogue-corps .dl-catsous [data-add]:nth-child(8)');
    await apaiser(p);
    await p.evaluate(() => {
      window.__annonces = [];
      const a = window.Kairos.annoncer;
      window.Kairos.annoncer = function (t, o) { window.__annonces.push(String(t)); return a.call(this, t, o); };
      window.__marques = [];
      new MutationObserver((ms) => ms.forEach((m) => {
        if (m.target.classList && m.target.classList.contains('dl-catrow-ajoute')) window.__marques.push(m.target.dataset.add);
      })).observe(document.getElementById('dl-catalogue-corps'), { subtree: true, attributes: true, attributeFilter: ['class'] });
    });
    const mesuresCat = [];
    for (const sel of ['.dl-catsous [data-add="1:0"]', '.dl-catsous [data-add]:nth-child(6)', '.dl-catsous [data-add]:nth-child(9)']) {
      const loc = p.locator('#dl-catalogue-corps ' + sel).first();
      const cle = await loc.getAttribute('data-add');
      // La liste du catalogue défile : le choix au milieu de la liste.
      await loc.evaluate((el) => {
        const l = el.closest('.dl-catlist');
        l.scrollTop += el.getBoundingClientRect().top - l.getBoundingClientRect().top - l.clientHeight / 2;
      });
      await apaiser(p);
      const b0 = await loc.boundingBox();
      const pt = { x: b0.x + b0.width / 2, y: b0.y + b0.height / 2 };
      await p.mouse.click(pt.x, pt.y);
      await apaiser(p);
      await pause(150);
      const b1 = await p.locator(`#dl-catalogue-corps .dl-catsous [data-add="${cle}"]`).first().boundingBox();
      const sous = await p.evaluate((q) => {
        const e = document.elementFromPoint(q.x, q.y);
        const r = e && e.closest('[data-add]');
        return r ? r.dataset.add + (r.closest('.dl-catsous') ? ' (tâches)' : '') : null;
      }, pt);
      mesuresCat.push({ cle, dy: +(b1.y - b0.y).toFixed(1), dh: +(b1.height - b0.height).toFixed(1), sous });
    }
    etape('Recette lot 14 n° 1 : catalogue à 375 px — le choix touché reste sous le doigt (même place, même hauteur)',
      mesuresCat.every((m) => Math.abs(m.dy) <= SEUIL && Math.abs(m.dh) <= SEUIL && m.sous === m.cle + ' (tâches)'), mesuresCat);
    // Catalogue ouvert : l'ajout ne lance pas de toast (il couvrait le bas
    // du catalogue), il est annoncé et marqué sur le choix touché.
    const retour = await p.evaluate(() => ({
      toasts: [...document.querySelectorAll('#k-toasts .k-toast')].filter((t) => t.getBoundingClientRect().height > 0).length,
      annonces: window.__annonces.filter((t) => /ajouté/.test(t)).length,
      marque: new Set(window.__marques).size,
    }));
    etape('Catalogue ouvert (375 px) : ajout sans toast, annoncé, retour visuel sur le choix',
      retour.toasts === 0 && retour.annonces === 3 && retour.marque === 3, retour);
    // Un toast (avertissement) par-dessus le catalogue : le toucher ne ferme pas le catalogue.
    await p.evaluate(() => window.Kairos.toast('Journée pleine (essai)', { type: 'avertissement', duree: 0 }));
    const t = await p.locator('#k-toasts .k-toast').last().boundingBox();
    await p.mouse.click(t.x + 20, t.y + t.height / 2);
    await p.locator('#k-toasts .k-toast').last().locator('.k-toast-fermer').click();
    await apaiser(p);
    etape('Toucher un toast (texte, ×) ne ferme pas le catalogue', await p.isVisible('#dl-catalogue'));
  });

  // Recette du lot 14, n° 15 : au premier « Enregistrer » d'un jour manqué
  // (le dernier), la bannière garde sa place (« Journée du … enregistrée. »,
  // même hauteur) : aucun contrôle ne remonte.
  for (const largeur of [1440, 375]) {
    await cas(`Recette lot 14 n° 15 : bannière du jour manqué (${largeur} px)`, largeur, async (p, ctx) => {
      const jour = jourOuvreVierge();
      sql(`DELETE FROM dailylog_entree WHERE utilisateur_id = 3; DELETE FROM dailylog_jour WHERE utilisateur_id = 3;
           INSERT INTO dailylog_entree (utilisateur_id, date, projet_id, tache_id, heures, updated_by)
           SELECT 3, d::date, 1, NULL, 7, 3 FROM generate_series(CURRENT_DATE - 30, CURRENT_DATE, interval '1 day') AS d
           WHERE extract(isodow FROM d) < 6 AND d::date <> '${jour}'`);
      await ctx.clearCookies();
      await p.goto(BASE + '/connexion');
      await p.fill('#email', 'rim@x.tn');
      await p.fill('#password', MDP);
      await Promise.all([p.waitForNavigation(), p.click('button[type=submit]')]);
      await p.goto(BASE + '/dailylog?date=' + jour);
      await p.waitForSelector('.dl9.dl-pret');
      await p.waitForSelector('#dl-banniere:not([hidden]) .dl-chip');
      await p.click('#dl-liste .dl-row .dl-plus');
      await apaiser(p);
      await neutre(p);
      const avant = await p.evaluate((e) => window.__st.releve(e), EXCLURE);
      const h0 = (await rect(p, '#dl-banniere')).h;
      await p.click('#dl-enregistrer');
      await p.waitForSelector('#dl-banniere.dl-banner-ok');
      await apaiser(p);
      await neutre(p);
      await pause(300);
      const apres = await p.evaluate((e) => window.__st.releve(e), EXCLURE);
      const bougent = comparer(avant, apres);
      const ban = await p.evaluate(() => { const b = document.getElementById('dl-banniere'); return { cache: b.hidden, h: b.getBoundingClientRect().height, texte: b.innerText.trim() }; });
      etape(`Recette lot 14 n° 15 (${largeur}) : premier « Enregistrer » du jour manqué — rien ne bouge, la bannière garde sa place`,
        !bougent.length && !ban.cache && Math.abs(ban.h - h0) <= SEUIL && /^Journée du .+ enregistrée\./.test(ban.texte),
        { bougent: bougent.slice(0, 4), h0, ban });
    });
  }

  await cas('P1-9 : surbrillance au toucher', 375, async (p) => {
    await p.goto(BASE + '/accueil');
    etape('P1-9 : -webkit-tap-highlight-color transparent', await p.evaluate(() => getComputedStyle(document.documentElement).webkitTapHighlightColor) === 'rgba(0, 0, 0, 0)');
  });

  await cas('P0-8 / P1-1 / P1-2 : fenêtre « Nouveau post »', 1440, async (p) => {
    await p.goto(BASE + '/projets/1');
    await apaiser(p);
    await p.click('#nouveau-post');
    await p.waitForSelector('#dialog-titre-tache', { state: 'visible' });
    await apaiser(p);
    let posts = 0;
    p.on('request', (r) => { if (r.method() === 'POST' && /\/taches$/.test(r.url())) posts++; });
    await p.fill('#dialog-titre-tache', 'Titre tapé puis Entrée');
    await p.press('#dialog-titre-tache', 'Enter');
    await apaiser(p);
    etape('P0-8 : Entrée dans le titre ne publie pas, passe au champ suivant', posts === 0
      && await p.evaluate(() => document.getElementById('dialog-nouveau-post').open && document.activeElement.id === 'dialog-echeance-tache'),
      { posts, focus: await p.evaluate(() => document.activeElement.id) });
    if (!(await p.evaluate(() => document.getElementById('dialog-nouveau-post').open))) {
      await p.click('#nouveau-post');
      await p.fill('#dialog-titre-tache', 'Titre tapé puis Entrée');
    }
    const xAvant = await rect(p, '#dialog-nouveau-post .dialog-fermer');
    const titreAvant = await rect(p, '#dialog-titre-tache');
    await p.keyboard.press('Escape');
    await p.waitForSelector('#dialog-nouveau-post .k-confirmation');
    await apaiser(p);
    const xApres = await rect(p, '#dialog-nouveau-post .dialog-fermer');
    const titreApres = await rect(p, '#dialog-titre-tache');
    etape('P1-1 : la question « Abandonner ? » ne pousse pas la fenêtre', proche(xAvant, xApres) && proche(titreAvant, titreApres), [xAvant, xApres, titreAvant, titreApres]);
    await p.click('#dialog-nouveau-post .k-confirmation .btn');
    await apaiser(p);
    const publier = {};
    for (const [onglet, bouton] of [['tache', '#publier-tache'], ['information', '#publier-information'], ['requete', '#publier-requete']]) {
      await p.click(`label[for="intent-${onglet}"]`);
      await apaiser(p);
      publier[onglet] = await rect(p, bouton);
    }
    const memeLigne = (a, b) => Math.abs(a.y - b.y) <= SEUIL && Math.abs(a.x + a.w - b.x - b.w) <= SEUIL;
    etape('P1-2 : « Publier » à la même place d’un onglet à l’autre (hauteur, bord droit)', memeLigne(publier.tache, publier.information) && memeLigne(publier.tache, publier.requete), publier);
    await p.click('label[for="intent-tache"]');
    const nbAvant = Number(sql("SELECT count(*) FROM tache WHERE titre = 'Titre tapé puis Entrée'"));
    posts = 0;
    await p.focus('#dialog-titre-tache');
    await p.keyboard.press('Control+Enter');
    await attendreQue(() => posts === 1);
    await apaiser(p);
    etape('P0-8 : Ctrl+Entrée publie', posts === 1 && Number(sql("SELECT count(*) FROM tache WHERE titre = 'Titre tapé puis Entrée'")) === nbAvant + 1, posts);
  });

  await cas('P1-6 / P1-3 : ouverture du panneau', 1440, async (p) => {
    await p.goto(BASE + '/projets/1');
    await apaiser(p);
    await p.locator('#tache-ligne-21').scrollIntoViewIfNeeded();
    await apaiser(p);
    const bandeauAvant = await rect(p, '#bandeau-admin');
    const ligneAvant = await rect(p, '#tache-ligne-21 [data-ouvrir-tache]');
    await p.click('#tache-ligne-21 [data-ouvrir-tache]');
    await p.waitForSelector('#tache-fenetre-21');
    await apaiser(p);
    etape('P1-6 : panneau ouvert, focus sur l’en-tête (pas dans le titre)', await p.evaluate(() => !document.activeElement.matches('input, textarea') && !!document.activeElement.closest('#dialog-tache')),
      await p.evaluate(() => document.activeElement.id || document.activeElement.className));
    const ligneApres = await rect(p, '#tache-ligne-21 [data-ouvrir-tache]');
    // Le bandeau des modes (Admin en mode test) se resserre aussi et peut
    // passer sur deux lignes : sa hauteur est déduite.
    const dBandeau = (await rect(p, '#bandeau-admin')).h - bandeauAvant.h;
    etape('P1-3 : la ligne cliquée reste sous le pointeur à l’ouverture du panneau (bandeau déduit)',
      proche(ligneAvant, { x: ligneApres.x, y: ligneApres.y - dBandeau }), [ligneAvant, ligneApres, dBandeau]);
  });

  await cas('P1-4 : fenêtre de tâche à 768 px', 768, async (p) => {
    // Tâche 22 (une intervenante) puis la suivante (aucune) : hauteurs différentes.
    await p.goto(BASE + '/projets/1?tache=22');
    await p.waitForSelector('#tache-fenetre-22');
    await apaiser(p);
    const xa = await rect(p, '#dialog-tache .tache-dialog-fermer');
    const fa = await rect(p, '#dialog-tache [data-tache-voisine="1"]');
    await p.click('#dialog-tache [data-tache-voisine="1"]');
    await p.waitForSelector('#dialog-tache [data-tache-fenetre]:not([data-tache-fenetre="22"])');
    await apaiser(p);
    const xb = await rect(p, '#dialog-tache .tache-dialog-fermer');
    const fb = await rect(p, '#dialog-tache [data-tache-voisine="1"]');
    etape('P1-4 : tâche suivante (768 px) : X et flèche ne bougent pas', proche(xa, xb) && proche(fa, fb), [xa, xb, fa, fb]);
  });

  await cas('P0-7 : Deadlines en réseau lent', 1440, async (p) => {
    await p.goto(BASE + '/deadlines?vue=tous');
    await apaiser(p);
    const erreurs404 = [];
    p.on('response', (r) => { if (r.status() === 404) erreurs404.push(r.url()); });
    await latence(p, 800);
    const barre = p.locator('.g-row[data-open-tache] a.g-bar').first();
    await barre.hover();
    await pause(300);
    await barre.click();
    await p.waitForSelector('#dialog-tache [data-tache-fenetre], #dialog-tache .tache-dialog-erreur', { timeout: 15000 });
    await apaiser(p);
    etape('P0-7 : Deadlines, survol puis clic en réseau lent : panneau chargé, aucun 404',
      erreurs404.length === 0 && await p.locator('#dialog-tache .tache-dialog-erreur').count() === 0, erreurs404);
    await latence(p, 0);
  });

  // P1-10 : feuille (375 px, tactile) : glisser vers le bas ferme, avec une sortie animée.
  const ctx = await navigateur.newContext({ viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true, locale: 'fr-FR', timezoneId: 'Africa/Tunis' });
  try {
    await ctx.addInitScript(SONDE);
    const p = await ctx.newPage();
    await p.goto(BASE + '/connexion');
    await p.fill('#email', 'admin@x.tn');
    await p.fill('#password', MDP);
    await Promise.all([p.waitForNavigation(), p.click('button[type=submit]')]);
    await p.goto(BASE + '/projets/1');
    await p.locator('#nouveau-post').tap();
    await p.waitForSelector('#dialog-nouveau-post[open]');
    await pause(400);
    const d = await rect(p, '#dialog-nouveau-post');
    const cdp = await ctx.newCDPSession(p);
    const x = d.x + d.w / 2, y0 = d.y + 8;
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y: y0 }] });
    for (let i = 1; i <= 8; i++) { await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y: y0 + i * 45 }] }); await pause(16); }
    const sortie = await p.evaluate(() => getComputedStyle(document.getElementById('dialog-nouveau-post')).transform);
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    const anime = await p.evaluate(() => document.getElementById('dialog-nouveau-post').classList.contains('k-sortie'));
    await pause(400);
    etape('P1-10 : la feuille suit le doigt, se ferme en glissant (sortie animée)',
      sortie !== 'none' && anime && await p.evaluate(() => !document.getElementById('dialog-nouveau-post').open), { sortie, anime });
  } catch (e) {
    etape('P1-10 : la feuille suit le doigt, se ferme en glissant (sortie animée)', false, String(e.message).split('\n')[0]);
  } finally {
    await ctx.close();
  }
}
async function attendreQue(fn, delai = 8000) {
  const fin = Date.now() + delai;
  while (!fn() && Date.now() < fin) await pause(40);
}

(async () => {
  const navigateur = await chromium.launch();
  try {
    if (!FILTRE_PAGES || FILTRE_PAGES.includes('interactions')) await interactions(navigateur);
    for (const theme of THEMES) {
      for (const largeur of LARGEURS) {
        console.log(`\n=== ${largeur} px, thème ${theme}`);
        const { ctx, p: pAdmin } = await contexte(navigateur, largeur, theme);
        for (const page of PAGES) {
          if (FILTRE_PAGES && !FILTRE_PAGES.includes(page.nom)) continue;
          // Page vue par un autre compte (lot 14) : son propre contexte.
          const autre = page.compte ? await contexte(navigateur, largeur, theme, page.compte) : null;
          const p = autre ? autre.p : pAdmin;
          try {
            if (page.avant) page.avant();
            await p.goto(BASE + page.chemin);
            await apaiser(p);
            if (page.ouvrir) { await page.ouvrir(p); await apaiser(p); }
            await focus(p, page.nom, largeur, page.exclure);
            await survols(p, page.nom, largeur, page.exclure);
            for (const b of page.bascules) {
              await bascule(p, page.nom, largeur, Object.assign({}, b, { exclure: (page.exclure || []).concat(b.exclure || []) }));
            }
          } catch (e) {
            etape(`${page.nom} ${largeur} : page mesurée jusqu’au bout`, false, String(e.message).split('\n')[0]);
          } finally {
            if (autre) await autre.ctx.close();
          }
        }
        await ctx.close();
      }
    }
  } finally {
    await navigateur.close();
  }
  etape('aucune erreur JavaScript ni boîte native', erreursJs.length === 0, erreursJs.slice(0, 5));
  console.log('\nDéplacement maximal (px) par page et largeur :');
  for (const page in mesures) console.log('  ' + page.padEnd(18) + Object.entries(mesures[page]).map(([k, v]) => `${k}: ${v}`).join('  '));
  if (process.env.KAIROS_STABILITE_JSON) fs.writeFileSync(process.env.KAIROS_STABILITE_JSON, JSON.stringify(mesures, null, 1));
  console.log(`\n${ok} OK, ${ko} KO`);
  process.exit(ko ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });

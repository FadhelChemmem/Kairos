/* Scénario Playwright « fil » (lot 14, revue produit P1-3 : fil filtrable),
 * sur l'accueil, la fiche projet et le profil :
 * - contrôle segmenté « Tout · Échanges · Activité » en partiel : aucune
 *   navigation de document, adresse tenue (?fil=, Retour sans
 *   rechargement), choix mémorisé par page (localStorage), segments
 *   immobiles, focus gardé, 1re mutation ≤ 100 ms sous 800 ms de latence ;
 * - « Échanges » par défaut (aucun post automatique), « Activité » :
 *   évènements regroupés (« Ali Chef a créé 3 tâches sur 21114X »),
 *   dépliables ;
 * - « Commenter » replié : déplié au clic avec le focus, les autres
 *   boutons du post ne bougent pas, brouillon gardé (champ ouvert, et
 *   rétabli après un changement de catégorie), Échap replie un champ vide ;
 * - « Afficher plus » de la fiche (au-delà de 30 posts) en partiel, focus
 *   jamais sur <body> ;
 * - ancre #post-<id> d'un post automatique (notification) : bascule sur
 *   « Tout », regroupement déplié ; post plus ancien que la première page :
 *   fil chargé jusqu'à lui (recette du lot 14, n° 13) ;
 * - catégorie d'une page complète jamais reprise de la page précédente
 *   (recette du lot 14, n° 6) ;
 * - « Voir comme » : on filtre, on n'écrit pas ; 1440 / 1024 / 768 / 375 px
 *   en clair et sombre sans débordement ; aucune erreur JavaScript ni
 *   boîte native.
 *
 * Lancement : KAIROS_E2E_SCENARIO=fil bash tests_e2e/lancer.sh [dossier_captures]
 * (base jetable + tests_e2e/seed_fil.py).
 */
'use strict';
const { execFileSync } = require('child_process');
const path = require('path');
let playwright;
try { playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright'); }
catch (e) { playwright = require('/opt/node-tools/node_modules/playwright'); }
const { chromium } = playwright;

const BASE = process.env.KAIROS_E2E_URL || 'http://127.0.0.1:8798';
const DB = process.env.KAIROS_E2E_DB || 'kairos_e2e_fil';
const CAPTURES = process.env.KAIROS_E2E_CAPTURES || '';
const MDP = 'Kairos2026!';

let ok = 0, ko = 0;
const erreursJs = [];
function etape(nom, cond, detail) {
  if (cond) { ok++; console.log('OK  ' + nom); }
  else { ko++; console.log('KO  ' + nom + (detail !== undefined ? ' — ' + JSON.stringify(detail).slice(0, 600) : '')); }
}
function sql(requete) {
  return execFileSync('psql', ['-X', '-At', '-d', DB, '-c', requete], { encoding: 'utf8' }).trim();
}
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
async function attendre(fn, delai = 8000) {
  const fin = Date.now() + delai;
  for (;;) { let v; try { v = await fn(); } catch (e) { v = false; } if (v) return v; if (Date.now() > fin) return v; await pause(40); }
}
async function contexte(navigateur, email, opts = {}) {
  const ctx = await navigateur.newContext({ viewport: { width: opts.largeur || 1440, height: opts.hauteur || 900 },
    colorScheme: opts.theme || 'light', locale: 'fr-FR', timezoneId: 'Africa/Tunis' });
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
  p.docs = 0;
  p.on('pageerror', (e) => erreursJs.push(chemin + ' : ' + e.message));
  p.on('dialog', (d) => { erreursJs.push('boîte native : ' + d.message()); d.dismiss(); });
  p.on('request', (r) => { if (r.isNavigationRequest() && r.frame() === p.mainFrame()) p.docs++; });
  await p.goto(BASE + chemin);
  await p.waitForLoadState('networkidle');
  await p.evaluate(() => { window.__marque = 1; });
  p.docs = 0;
  return p;
}
async function capture(p, nom) {
  if (CAPTURES) await p.screenshot({ path: path.join(CAPTURES, nom), fullPage: false });
}
async function latence(p, ms) {
  const cdp = await p.context().newCDPSession(p);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: ms, downloadThroughput: -1, uploadThroughput: -1 });
}
const rect = (p, sel) => p.locator(sel).first().evaluate((el) => { const r = el.getBoundingClientRect(); return { x: r.left, y: r.top + scrollY, w: r.width, h: r.height }; });
const pareil = (a, b) => !!a && !!b && Math.abs(a.x - b.x) <= 1 && Math.abs(a.y - b.y) <= 1 && Math.abs(a.w - b.w) <= 1;
const focus = (p) => p.evaluate(() => { const a = document.activeElement; return a && a !== document.body ? (a.id || a.className || a.tagName) : 'BODY'; });
const categorie = (p, liste) => p.evaluate((l) => { const e = document.querySelector(l); return e && e.getAttribute('data-fil-categorie'); }, liste);
const courante = (p, page) => p.evaluate((pg) => { const a = document.querySelector(`[data-fil-filtres="${pg}"] a[aria-current="page"]`); return a && a.getAttribute('data-fil'); }, page);

/** Clic sur un segment : partiel, adresse, segments immobiles, focus gardé. */
async function segment(p, page, liste, fil, nom, opts = {}) {
  const segs = ['tout', 'echanges', 'activite'].map((c) => `#fil-filtre-${page}-${c}`);
  const avant = await Promise.all(segs.map((s) => rect(p, s)));
  if (opts.latence) {
    await latence(p, opts.latence);
    await p.evaluate((l) => {
      window.__t0 = 0; window.__mutation = null;
      const cible = document.querySelector(`[data-fil-filtres] a[aria-current]`).parentNode;
      new MutationObserver(() => { if (window.__t0 && window.__mutation === null) window.__mutation = performance.now() - window.__t0; })
        .observe(cible, { subtree: true, attributes: true });
      document.addEventListener('pointerdown', () => { window.__t0 = performance.now(); }, { capture: true, once: true });
    }, liste);
  }
  p.docs = 0;
  await p.click(`#fil-filtre-${page}-${fil}`);
  const fini = await attendre(async () => (await categorie(p, liste)) === fil && !(await p.locator(`${liste}[aria-busy="true"]`).count()), 10000);
  if (opts.latence) {
    await latence(p, 0);
    const m = await p.evaluate(() => window.__mutation);
    etape(`${nom} : segment marqué ≤ 100 ms sous ${opts.latence} ms de latence (optimiste)`, m !== null && m <= 100, m);
  }
  const apres = await Promise.all(segs.map((s) => rect(p, s)));
  const e = await p.evaluate(() => ({ marque: window.__marque === 1, url: location.pathname + location.search }));
  etape(`${nom} : liste « ${fil} » sans navigation de document`, fini && e.marque && p.docs === 0, { ...e, docs: p.docs });
  etape(`${nom} : adresse ?fil=${fil}, segment courant`, new RegExp(`fil=${fil}`).test(e.url) && (await courante(p, page)) === fil, e.url);
  etape(`${nom} : les trois segments n’ont pas bougé`, avant.every((r, i) => pareil(r, apres[i])), [avant, apres]);
  etape(`${nom} : focus sur le segment`, (await focus(p)) === `fil-filtre-${page}-${fil}`, await focus(p));
}

(async () => {
  const navigateur = await chromium.launch();
  try {
    // ==================================================================
    // 1. Accueil d'Ali (chef du projet 1), 1 440 px
    // ==================================================================
    const ali = await contexte(navigateur, 'ali@x.tn');
    let p = await ouvrir(ali, '/accueil');
    etape('accueil : « Échanges » par défaut', (await courante(p, 'accueil')) === 'echanges' && (await categorie(p, '#fil-liste')) === 'echanges');
    etape('Échanges : aucun post automatique, clôture avec message gardée',
      await p.locator('#fil-liste .fil-item[data-categorie="activite"]').count() === 0
      && await p.locator('#fil-liste #post-205').count() === 1 && await p.locator('#fil-liste #post-200').count() === 0);
    etape('Échanges : aucun champ de commentaire déplié',
      await p.locator('#fil-liste .post-commenter:visible').count() === 0
      && await p.locator('#fil-liste [data-commenter][aria-expanded="false"]').count() > 0);
    await capture(p, 'fil-accueil-echanges-1440.png');

    await segment(p, 'accueil', '#fil-liste', 'activite', 'Activité', { latence: 800 });
    const groupe = p.locator('#fil-liste .fil-groupe').first();
    etape('Activité : « Ali Chef a créé 3 tâches sur 21114X »', /Ali Chef a créé 3 tâches sur 21114X/.test(await groupe.innerText()),
      await groupe.innerText().catch(() => ''));
    etape('Activité : aperçu des tâches, détail replié', /Note de calcul fondations · Plans de ferraillage · Descente de charges/.test(await groupe.innerText())
      && !(await groupe.locator('details').evaluate((d) => d.open)));
    etape('Activité : deux changements d’état de la même tâche regroupés',
      /a changé l’état d’une tâche/.test(await p.locator('#fil-liste').innerText()));
    etape('Activité : clôture sans message, pas d’échange', await p.locator('#fil-liste #post-206').count() === 1
      && await p.locator('#fil-liste .fil-item[data-categorie="echanges"]').count() === 0);
    const sommaire = groupe.locator('summary');
    const s0 = await rect(p, '#fil-liste .fil-groupe summary');
    await sommaire.click();
    await pause(200);
    etape('regroupement déplié : 3 posts, le bouton n’a pas bougé',
      await groupe.locator('.fil-groupe-post .post-card').count() === 3 && pareil(s0, await rect(p, '#fil-liste .fil-groupe summary')));
    await capture(p, 'fil-accueil-activite-1440.png');

    await segment(p, 'accueil', '#fil-liste', 'tout', 'Tout');
    etape('Tout : échanges et activité', await p.locator('#fil-liste .fil-item[data-categorie="activite"]').count() > 0
      && await p.locator('#fil-liste .fil-item[data-categorie="echanges"]').count() > 0);
    // Retour : catégorie précédente, sans rechargement.
    p.docs = 0;
    await p.goBack();
    await attendre(async () => (await categorie(p, '#fil-liste')) === 'activite');
    etape('Retour : « Activité » revenue, segment synchronisé, sans rechargement',
      (await courante(p, 'accueil')) === 'activite' && await p.evaluate(() => window.__marque === 1) && p.docs === 0
      && await p.evaluate(() => /fil=activite/.test(location.search)));
    await p.close();

    // Choix mémorisé pour la page (le dernier cliqué, « Tout » ; Retour ne
    // change pas le choix) : rouverte sans ?fil=, la catégorie revient.
    p = await ouvrir(ali, '/accueil');
    await attendre(async () => (await categorie(p, '#fil-liste')) === 'tout');
    // Lot 20 (revue 12d) : le serveur lit le choix (cookie) — la page
    // s'ouvre directement sur « Tout », sans bascule ni adresse réécrite.
    etape('choix mémorisé (cookie lu par le serveur) : accueil rouvert directement sur « Tout »',
      (await categorie(p, '#fil-liste')) === 'tout' && (await courante(p, 'accueil')) === 'tout'
      && await p.evaluate(() => !/fil=/.test(location.search) && localStorage.getItem('kairos-fil-accueil') === 'tout'
        && /kairos_fil_accueil=tout/.test(document.cookie)));
    // localStorage inaccessible : la page marche (défaut du serveur).
    const bloque = await navigateur.newContext({ viewport: { width: 1440, height: 900 } });
    await bloque.addInitScript(() => { Object.defineProperty(window, 'localStorage', { get() { throw new Error('bloqué'); } }); });
    {
      const q = await bloque.newPage();
      q.on('pageerror', (e) => erreursJs.push('localStorage bloqué : ' + e.message));
      await q.goto(BASE + '/connexion');
      await q.fill('#email', 'ali@x.tn'); await q.fill('#password', MDP);
      await Promise.all([q.waitForNavigation(), q.click('button[type=submit]')]);
      await q.click('#fil-filtre-accueil-tout');
      await attendre(async () => (await categorie(q, '#fil-liste')) === 'tout');
      etape('localStorage bloqué : le filtre marche quand même', (await categorie(q, '#fil-liste')) === 'tout');
    }
    await bloque.close();

    // --- « Commenter » replié -------------------------------------------
    await p.click('#fil-filtre-accueil-echanges');
    await attendre(async () => (await categorie(p, '#fil-liste')) === 'echanges');
    await p.locator('#post-100').scrollIntoViewIfNeeded();
    const actions = ['#post-100 .post-reaction-form button', '#post-100-commenter', '#post-100 .post-action-reposter'];
    const a0 = await Promise.all(actions.map((s) => rect(p, s)));
    await p.click('#post-100-commenter');
    etape('« Commenter » : champ déplié, focus dedans, aria-expanded=true',
      await p.locator('#commentaire-post-100').isVisible() && (await focus(p)) === 'commentaire-post-100'
      && await p.getAttribute('#post-100-commenter', 'aria-expanded') === 'true');
    const a1 = await Promise.all(actions.map((s) => rect(p, s)));
    etape('« Commenter » : Vu, Commenter et Donner suite n’ont pas bougé', a0.every((r, i) => pareil(r, a1[i])), [a0, a1]);
    await p.keyboard.type('Brouillon à garder');
    await p.click('#post-100-commenter');
    etape('brouillon : un second clic garde le champ ouvert et y rend le focus',
      await p.locator('#commentaire-post-100').isVisible() && (await focus(p)) === 'commentaire-post-100');
    await p.keyboard.press('Escape');
    etape('brouillon : Échap ne replie pas un champ rempli', await p.locator('#commentaire-post-100').isVisible());
    await p.click('#fil-filtre-accueil-tout');
    await attendre(async () => (await categorie(p, '#fil-liste')) === 'tout');
    etape('brouillon rétabli après un changement de catégorie (champ ouvert)',
      (await p.inputValue('#commentaire-post-100')) === 'Brouillon à garder' && await p.locator('#commentaire-post-100').isVisible()
      && await p.getAttribute('#post-100-commenter', 'aria-expanded') === 'true');
    await p.fill('#commentaire-post-100', '');
    await p.focus('#commentaire-post-100');
    await p.keyboard.press('Escape');
    etape('champ vide : Échap le replie, focus sur « Commenter »',
      !(await p.locator('#commentaire-post-100').isVisible()) && (await focus(p)) === 'post-100-commenter'
      && await p.getAttribute('#post-100-commenter', 'aria-expanded') === 'false');
    await p.click('#post-100-commenter');
    await p.keyboard.type('Commentaire envoyé en partiel');
    p.docs = 0;
    await p.keyboard.press('Enter');
    await attendre(() => sql("SELECT count(*) FROM post_commentaire WHERE contenu = 'Commentaire envoyé en partiel'") === '1'
      && p.evaluate(() => /Commentaire envoyé en partiel/.test(document.getElementById('post-100-commentaires').innerText)));
    await pause(300);
    etape('envoi : champ vidé et ouvert, focus dedans, compteur à jour, sans navigation',
      (await p.inputValue('#commentaire-post-100')) === '' && await p.locator('#commentaire-post-100').isVisible()
      && (await focus(p)) === 'commentaire-post-100' && /2\s*commentaires/.test(await p.textContent('#post-100-compteur')) && p.docs === 0,
      [await focus(p), await p.textContent('#post-100-compteur')]);
    await capture(p, 'fil-commenter-1440.png');
    await p.close();

    // --- Ancre d'un post automatique (notification) ----------------------
    p = await ouvrir(ali, '/accueil?x=1#post-201');
    await attendre(async () => (await categorie(p, '#fil-liste')) === 'tout');
    await pause(200);
    etape('ancre #post-201 hors « Échanges » : bascule sur « Tout », regroupement déplié, post à l’écran',
      await p.locator('#post-201').isVisible() && await p.evaluate(() => {
        const r = document.getElementById('post-201').getBoundingClientRect();
        return r.top < innerHeight && r.bottom > 0;
      }));
    await p.close();

    // ==================================================================
    // 2. Fiche projet : catégories, « Afficher plus »
    // ==================================================================
    p = await ouvrir(ali, '/projets/1');
    etape('fiche : « Échanges » par défaut (choix de l’accueil non repris)', (await courante(p, 'projet')) === 'echanges');
    const n0 = await p.locator('#fil-posts .fil-item').count();
    etape('fiche : 30 posts puis « Afficher plus »', n0 === 30 && await p.locator('#fil-suite-lien.fil-plus').count() === 1, n0);
    await p.locator('#fil-suite-lien').scrollIntoViewIfNeeded();
    await p.focus('#fil-suite-lien');
    p.docs = 0;
    const y0 = await p.evaluate(() => scrollY);
    await p.keyboard.press('Enter');
    await attendre(async () => (await p.locator('#fil-posts .fil-item').count()) > n0);
    await pause(300);
    const n1 = await p.locator('#fil-posts .fil-item').count();
    etape('« Afficher plus » : 11 posts ajoutés à la suite, sans navigation, défilement gardé',
      n1 === 41 && p.docs === 0 && Math.abs((await p.evaluate(() => scrollY)) - y0) <= 40, [n1, p.docs]);
    etape('« Afficher plus » : plus de bouton, focus sur la fin du fil (jamais <body>)',
      await p.locator('a#fil-suite-lien').count() === 0 && (await focus(p)) === 'fil-suite-lien', await focus(p));
    etape('« Afficher plus » : aucun post en double', await p.evaluate(() => {
      const ids = [...document.querySelectorAll('#fil-posts [id^="post-"].post-card')].map((e) => e.id);
      return ids.length === new Set(ids).size;
    }));
    await p.evaluate(() => window.scrollTo(0, 0));
    await segment(p, 'projet', '#fil-posts', 'activite', 'fiche, Activité');
    etape('fiche, Activité : regroupement sans le code du projet', /Ali Chef a créé 3 tâches$/m.test(await p.locator('#fil-posts .fil-groupe .post-entete-ligne').first().innerText()),
      await p.locator('#fil-posts .fil-groupe .post-entete-ligne').first().innerText().catch(() => ''));
    etape('fiche, Activité : pas de « Afficher plus » (moins de 30)', await p.locator('#fil-suite-lien').count() === 0);
    // Texte filtré dans la catégorie affichée.
    await p.fill('#filtre-posts', 'ferraillage');
    etape('filtre texte dans « Activité » : le regroupement qui contient la tâche reste',
      await p.locator('#fil-posts .fil-groupe:visible').count() === 1);
    await p.fill('#filtre-posts', '');
    // Recette du lot 14, n° 6 : l'accueil ouvert depuis la fiche en
    // « Activité » s'ouvre sur SA catégorie (défaut « Échanges »), jamais
    // celle de la page précédente ; aucune requête de rattrapage.
    await p.evaluate(() => {
      try { localStorage.removeItem('kairos-fil-accueil'); } catch (e) { /* */ }
      document.cookie = 'kairos_fil_accueil=; path=/; max-age=0';
    });
    const partielsAccueil = [];
    p.on('request', (r) => { if (r.headers()['x-kairos-partiel']) partielsAccueil.push(r.url()); });
    await Promise.all([p.waitForNavigation(), p.click('a[href="/accueil"]')]);
    await p.waitForLoadState('networkidle');
    await pause(300);
    etape('accueil ouvert depuis la fiche en « Activité » : « Échanges » (défaut de la page), sans requête de plus',
      (await courante(p, 'accueil')) === 'echanges' && (await categorie(p, '#fil-liste')) === 'echanges'
      && !partielsAccueil.some((u) => /fil=/.test(u)), [await courante(p, 'accueil'), partielsAccueil]);
    await p.close();

    // Lot 20 (revue QA n° 8) : fermer le panneau d'une tâche après un
    // changement d'onglet du fil ne revient pas en arrière (ni adresse, ni
    // onglet, ni requête) ; un rechargement ne rouvre pas le panneau.
    p = await ouvrir(ali, '/projets/1');
    const partielsFiche = [];
    p.on('request', (r) => { if (r.headers()['x-kairos-partiel']) partielsFiche.push(r.url()); });
    await p.locator('[data-open-tache] [data-ouvrir-tache]').first().click();
    await attendre(() => p.evaluate(() => document.getElementById('dialog-tache').open && /tache=/.test(location.search)));
    const cible = (await courante(p, 'projet')) === 'tout' ? 'echanges' : 'tout';
    await p.click(`#fil-filtre-projet-${cible}`);
    await attendre(async () => (await categorie(p, '#fil-posts')) === cible);
    partielsFiche.length = 0;
    await p.locator('#dialog-tache [data-close-tache]').first().click();
    await pause(600);
    const apresFermeture = await p.evaluate(() => location.search);
    etape('panneau fermé après un changement d’onglet : onglet et adresse gardés, aucune requête',
      !/tache=/.test(apresFermeture) && new RegExp(`fil=${cible}`).test(apresFermeture)
      && (await courante(p, 'projet')) === cible && partielsFiche.length === 0, [apresFermeture, partielsFiche]);
    await p.reload();
    await p.waitForLoadState('networkidle');
    etape('rechargement après fermeture : panneau resté fermé', !(await p.evaluate(() => document.getElementById('dialog-tache').open)));
    // Ouvrir puis fermer sans rien changer : aucune requête (défilement et
    // pages « Afficher plus » gardés).
    partielsFiche.length = 0;
    await p.locator('[data-open-tache] [data-ouvrir-tache]').first().click();
    await attendre(() => p.evaluate(() => document.getElementById('dialog-tache').open));
    await pause(300);
    const avantFermeture = partielsFiche.filter((u) => !/\/taches\/\d+\/fenetre|fenetre/.test(u)).length;
    await p.locator('#dialog-tache [data-close-tache]').first().click();
    await pause(600);
    etape('ouvrir puis fermer une tâche : le fil n’est pas rechargé',
      partielsFiche.filter((u) => /\/projets\/1(\?|$)/.test(u)).length === 0 && avantFermeture === 0, partielsFiche);
    await p.close();

    // Recette du lot 14, n° 13 : ancre d'une notification vers un post plus
    // ancien que la première page — le fil est chargé jusqu'à lui.
    p = await ouvrir(ali, '/projets/1?x=2#post-138');
    await attendre(async () => (await p.locator('#post-138').count()) === 1);
    await pause(400);
    etape('ancre #post-138 au-delà de la première page : fil chargé jusqu’à lui, post à l’écran',
      await p.locator('#post-138').count() === 1 && await p.evaluate(() => {
        const r = document.getElementById('post-138').getBoundingClientRect();
        return r.top < innerHeight && r.bottom > 0;
      }) && p.docs === 0, [await p.locator('#post-138').count(), p.docs]);
    await p.close();

    // ==================================================================
    // 3. Profil de Rim (posts de Rim)
    // ==================================================================
    p = await ouvrir(ali, '/utilisateurs/3/profil');
    etape('profil : « Échanges » par défaut', (await courante(p, 'profil')) === 'echanges');
    await segment(p, 'profil', '#profil-posts', 'activite', 'profil, Activité');
    etape('profil, Activité : la clôture sans message de Rim seule', await p.locator('#profil-posts #post-206').count() === 1
      && await p.locator('#profil-posts #post-205').count() === 0);
    await p.close();
    await ali.close();

    // ==================================================================
    // 4. « Voir comme » Ali : on filtre, rien ne s'écrit
    // ==================================================================
    const adm = await contexte(navigateur, 'admin@x.tn');
    p = await ouvrir(adm, '/admin/voir-comme');
    await p.evaluate(() => { document.getElementById('voir-comme-compte').value = '2'; });
    await Promise.all([p.waitForNavigation(), p.click('button:has-text("Voir comme")')]);
    await p.goto(BASE + '/accueil');
    await p.click('#fil-filtre-accueil-activite');
    await attendre(async () => (await categorie(p, '#fil-liste')) === 'activite');
    etape('Voir comme : le fil se filtre', (await categorie(p, '#fil-liste')) === 'activite');
    const nbCom = sql('SELECT count(*) FROM post_commentaire');
    await p.click('#fil-filtre-accueil-echanges');
    await attendre(async () => (await categorie(p, '#fil-liste')) === 'echanges');
    await p.click('#post-100-commenter');
    await pause(200);
    const desactive = await p.evaluate(() => document.documentElement.hasAttribute('data-lecture-seule')
      && !!document.querySelector('#commentaire-post-100:disabled'));
    await p.keyboard.press('Enter');
    await pause(500);
    etape('Voir comme : champ déplié mais désactivé, aucune écriture', desactive && sql('SELECT count(*) FROM post_commentaire') === nbCom,
      desactive);
    await adm.close();

    // ==================================================================
    // 5. Largeurs et thèmes : ni débordement, segments sur une ligne
    // ==================================================================
    for (const theme of ['light', 'dark']) {
      for (const largeur of [1440, 1024, 768, 375]) {
        const ctx = await contexte(navigateur, 'ali@x.tn', { largeur, hauteur: largeur < 600 ? 812 : 900, theme });
        for (const [page, chemin] of [['accueil', '/accueil?fil=activite'], ['projet', '/projets/1?fil=tout']]) {
          const q = await ouvrir(ctx, chemin);
          const m = await q.evaluate((pg) => {
            const nav = document.querySelector(`[data-fil-filtres="${pg}"]`);
            const segs = [...nav.querySelectorAll('a')].map((a) => a.getBoundingClientRect());
            return { deborde: document.documentElement.scrollWidth > innerWidth + 1,
              uneLigne: segs.every((r) => Math.abs(r.top - segs[0].top) < 1), h: Math.round(segs[0].height) };
          }, page);
          etape(`${page} ${largeur} ${theme} : pas de débordement, segments sur une ligne (≥ 24 px)`, !m.deborde && m.uneLigne && m.h >= 24, m);
          if (largeur === 375 || largeur === 1440) await capture(q, `fil-${page}-${largeur}-${theme}.png`);
          await q.close();
        }
        await ctx.close();
      }
    }
  } catch (e) {
    etape('scénario mené jusqu’au bout', false, String(e && e.stack || e).split('\n').slice(0, 3).join(' | '));
  } finally {
    await navigateur.close();
  }
  etape('aucune erreur JavaScript ni boîte native', erreursJs.length === 0, erreursJs.slice(0, 5));
  console.log(`\n${ok} OK, ${ko} KO`);
  process.exit(ko ? 1 : 0);
})();

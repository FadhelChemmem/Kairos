/* Scénario Playwright du lot 13 : socle des mises à jour partielles
 * (kairos-partiel.js + app/partiel.py), prouvé sur les pilotes de la page
 * Utilisateurs — critères d'acceptation de l'audit UX §4.8.
 *
 * Lancement : KAIROS_E2E_SCENARIO=partiel bash tests_e2e/lancer.sh [dossier_captures]
 * (base jetable + tests_e2e/seed_partiel.py). Variables : KAIROS_E2E_URL,
 * KAIROS_E2E_DB, KAIROS_E2E_CAPTURES (facultatif), PLAYWRIGHT_MODULE.
 *
 * Vérifie l'écran ET la base : aucune navigation de document, défilement
 * conservé (|Δy| ≤ 40 px), focus jamais sur <body>, première mutation
 * ≤ 100 ms sous 800 ms de latence (optimiste), indicateur aria-busy,
 * « Annuler » du toast, refus 409 qui annule l'état optimiste, filtres
 * automatiques et Retour du navigateur, session expirée (401), mouvement
 * réduit, « Voir comme » sans écriture proposée, 375 px sans débordement,
 * aucune erreur JavaScript.
 */
'use strict';
const { execFileSync } = require('child_process');
const path = require('path');
let playwright;
try { playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright'); }
catch (e) { playwright = require('/home/claude/.npm-global/lib/node_modules/playwright'); }
const { chromium } = playwright;

const BASE = process.env.KAIROS_E2E_URL || 'http://127.0.0.1:8798';
const DB = process.env.KAIROS_E2E_DB || 'kairos_e2e_partiel';
const CAPTURES = process.env.KAIROS_E2E_CAPTURES || '';
const MDP = 'Kairos2026!';
const ANCIEN = 6, RH2 = 140;

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
  for (;;) { const v = await fn(); if (v) return v; if (Date.now() > fin) return v; await pause(50); }
}
async function contexte(navigateur, email, opts = {}) {
  const ctx = await navigateur.newContext({ viewport: { width: opts.largeur || 1280, height: opts.hauteur || 800 },
    colorScheme: opts.theme || 'light', reducedMotion: opts.reducedMotion || 'no-preference' });
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
  p.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) erreursJs.push(m.text()); });
  p.on('dialog', (d) => { erreursJs.push('boîte native : ' + d.message()); d.accept(); });
  await p.goto(BASE + chemin);
  return p;
}
async function capture(p, nom) { if (CAPTURES) await p.screenshot({ path: path.join(CAPTURES, nom) }); }
/** Marqueur de page (disparaît si le document est rechargé) + navigations de document comptées. */
async function instrumenter(p) {
  await p.evaluate(() => {
    window.__marque = 1;
    window.__mutation = null;
    window.__t0 = performance.now();
    new MutationObserver(() => { if (window.__mutation === null) window.__mutation = performance.now() - window.__t0; })
      .observe(document.documentElement, { subtree: true, childList: true, attributes: true });
  });
}
const etat = (p) => p.evaluate(() => ({
  marque: window.__marque === 1, mutation: window.__mutation, y: Math.round(window.scrollY),
  focus: document.activeElement === document.body ? 'body' : (document.activeElement.id || document.activeElement.tagName),
  url: location.pathname + location.search,
}));
async function latence(p, ms) {
  const cdp = await p.context().newCDPSession(p);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: ms, downloadThroughput: -1, uploadThroughput: -1 });
}
const interrupteur = (id) => `#actif-${id}`;

(async () => {
  const navigateur = await chromium.launch();
  try {
    const adm = await contexte(navigateur, 'admin@x.tn');
    let p = await ouvrir(adm, '/utilisateurs');
    let docs = 0;
    p.on('request', (r) => { if (r.isNavigationRequest() && r.frame() === p.mainFrame()) docs++; });

    // --- 1. Interrupteur « Actif » : optimiste, sans rechargement ---------
    await p.locator(interrupteur(ANCIEN)).scrollIntoViewIfNeeded();
    await p.evaluate((s) => { const b = document.querySelector(s); window.scrollBy(0, b.getBoundingClientRect().top - innerHeight / 2); }, interrupteur(ANCIEN));
    await latence(p, 800);
    await instrumenter(p);
    const avant = await etat(p);
    etape('liste qui défile (ligne en bas de page)', avant.y > 300, avant);
    await p.click(interrupteur(ANCIEN));
    const immediat = await p.getAttribute(interrupteur(ANCIEN), 'aria-checked');
    await attendre(async () => await p.locator('#u-' + ANCIEN + '[aria-busy="true"]').count() === 1, 700);
    etape('indicateur aria-busy pendant la requête lente', await p.locator('#u-' + ANCIEN + '.k-en-cours').count() === 1);
    await attendre(async () => (await p.locator('#k-toasts .k-toast').count()) > 0, 5000);
    let apres = await etat(p);
    etape('état optimiste immédiat (aria-checked)', immediat === 'true');
    etape('première mutation ≤ 100 ms sous 800 ms de latence', apres.mutation !== null && apres.mutation <= 100, apres.mutation);
    etape('aucun rechargement de document', apres.marque && docs === 0, { docs });
    etape('défilement conservé (|Δy| ≤ 40 px)', Math.abs(apres.y - avant.y) <= 40, [avant.y, apres.y]);
    etape('focus rendu à l’interrupteur', apres.focus === 'actif-' + ANCIEN, apres.focus);
    etape('compte réactivé en base', sql(`SELECT actif FROM utilisateur WHERE id=${ANCIEN}`) === 't');
    etape('toast « Compte de Ancien Compte réactivé. » avec « Annuler »',
      /Compte de Ancien Compte réactivé/.test(await p.locator('#k-toasts .k-toast').first().innerText())
      && await p.locator('#k-toasts .k-toast-action:has-text("Annuler")').count() === 1);
    etape('compteur mis à jour hors cible', /33 actifs|actifs/.test(await p.textContent('#utilisateurs-compte'))
      && (await p.textContent('#utilisateurs-compte')).includes(sql('SELECT count(*) FROM utilisateur WHERE actif') + ' actifs'));
    await capture(p, 'e2e-13-interrupteur-toast.png');
    await latence(p, 0);
    // « Annuler » : retour à l'état d'avant, focus sur l'interrupteur.
    await p.click('#k-toasts .k-toast-action:has-text("Annuler")');
    await attendre(async () => sql(`SELECT actif FROM utilisateur WHERE id=${ANCIEN}`) === 'f', 4000);
    await pause(300);
    apres = await etat(p);
    etape('« Annuler » : compte de nouveau désactivé en base', sql(`SELECT actif FROM utilisateur WHERE id=${ANCIEN}`) === 'f');
    etape('« Annuler » : interrupteur à l’état d’avant, focus dessus', await p.getAttribute(interrupteur(ANCIEN), 'aria-checked') === 'false'
      && apres.focus === 'actif-' + ANCIEN, apres.focus);
    etape('toujours aucun rechargement', apres.marque && docs === 0);

    // --- 2. Refus (un seul RH actif) : état optimiste annulé, message -----
    await p.locator(interrupteur(RH2)).scrollIntoViewIfNeeded();
    await p.click(interrupteur(RH2));
    await attendre(async () => (await p.locator('#k-toasts .k-toast-erreur').count()) > 0, 4000);
    etape('refus 409 : interrupteur revenu à « inactif »', await p.getAttribute(interrupteur(RH2), 'aria-checked') === 'false');
    // Contre-expertise a11y R2 : le toast n'est plus une région live créée
    // déjà remplie ; son texte passe par la région persistante #k-alerte.
    await attendre(async () => /compte RH actif/.test(await p.textContent('#k-alerte')), 2000);
    etape('refus 409 : message du serveur en toast, annoncé par la région persistante (role=alert)',
      /compte RH actif/.test(await p.locator('#k-toasts .k-toast-erreur').innerText())
      && /compte RH actif/.test(await p.textContent('#k-alerte'))
      && await p.getAttribute('#k-alerte', 'role') === 'alert'
      && await p.locator('#k-toasts .k-toast-erreur').getAttribute('role') === null);
    etape('refus : rien en base, pas de rechargement', sql(`SELECT actif FROM utilisateur WHERE id=${RH2}`) === 'f' && docs === 0);
    await p.click('#k-toasts .k-toast-erreur .k-toast-fermer');

    // --- 2 b. « Annuler » au clavier : Ctrl+Z (contre-expertise a11y N4) ---
    await p.focus(interrupteur(ANCIEN));
    await p.keyboard.press('Space');
    await attendre(async () => sql(`SELECT actif FROM utilisateur WHERE id=${ANCIEN}`) === 't', 4000);
    await attendre(async () => /Ctrl\+Z/.test(await p.textContent('#k-annonce')), 2000);
    etape('succès annoncé par #k-annonce (role=status), avec le raccourci d’« Annuler »',
      /Compte de Ancien Compte réactivé\. « Annuler » : Ctrl\+Z\./.test(await p.textContent('#k-annonce')), await p.textContent('#k-annonce'));
    await p.keyboard.press('Control+z');
    await attendre(async () => sql(`SELECT actif FROM utilisateur WHERE id=${ANCIEN}`) === 'f', 4000);
    apres = await etat(p);
    etape('Ctrl+Z hors d’un champ : « Annuler » rejoué, compte de nouveau désactivé, focus gardé',
      sql(`SELECT actif FROM utilisateur WHERE id=${ANCIEN}`) === 'f' && apres.focus === 'actif-' + ANCIEN, apres.focus);
    await p.focus('#filtre-utilisateurs-q');
    await p.keyboard.press('Control+z');
    await pause(400);
    etape('Ctrl+Z dans un champ de saisie : rien n’est rejoué', sql(`SELECT actif FROM utilisateur WHERE id=${ANCIEN}`) === 'f');

    // --- 2 c. Toasts au-dessus d'une fenêtre modale (contre-expertise UX N1) ---
    for (const largeur of [375, 768, 1440]) {
      await p.setViewportSize({ width: largeur, height: 800 });
      await p.keyboard.press('Escape');
      await p.locator('main').focus();
      await p.keyboard.press('?');
      await p.waitForSelector('dialog.k-aide-raccourcis[open]');
      await p.evaluate(() => { window.__annule = 0; window.Kairos.toast('Essai au-dessus de la fenêtre', { action: { libelle: 'Annuler', surClic: () => { window.__annule = 1; } } }); });
      await pause(300);
      const vu = await p.evaluate(() => {
        const b = document.querySelector('#k-toasts .k-toast:last-child .k-toast-action');
        const r = b.getBoundingClientRect();
        const h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return { dansFenetre: !!document.querySelector('dialog.k-aide-raccourcis #k-toasts'), visible: h === b || b.contains(h),
                 annonce: document.getElementById('k-annonce').textContent };
      });
      await capture(p, `e2e-13-toast-fenetre-${largeur}.png`);
      await p.click('#k-toasts .k-toast-action:has-text("Annuler")', { timeout: 3000 }).catch(() => {});
      etape(`${largeur} px : toast au-dessus de la fenêtre modale, « Annuler » cliquable, annoncé`,
        vu.dansFenetre && vu.visible && /Essai au-dessus/.test(vu.annonce) && await p.evaluate(() => window.__annule) === 1, vu);
      await p.keyboard.press('Escape');
      await attendre(async () => (await p.locator('dialog.k-aide-raccourcis[open]').count()) === 0, 2000);
      etape(`${largeur} px : fenêtre fermée, zone des toasts revenue dans la page`,
        await p.evaluate(() => document.getElementById('k-toasts').parentElement === document.body));
    }
    await p.setViewportSize({ width: 1280, height: 800 });

    // --- 3. Filtres automatiques et Retour ------------------------------------
    p = await ouvrir(adm, '/utilisateurs');
    docs = 0;
    p.on('request', (r) => { if (r.isNavigationRequest() && r.frame() === p.mainFrame()) docs++; });
    await instrumenter(p);
    etape('bouton « Filtrer » masqué (filtres automatiques)', !(await p.locator('form.filtres-utilisateurs button[type=submit]').isVisible()));
    await p.click('#filtre-utilisateurs-q');
    await p.keyboard.type('compte0', { delay: 40 });
    await attendre(async () => (await etat(p)).url === '/utilisateurs?q=compte0', 3000);
    let e = await etat(p);
    etape('frappe : adresse ?q=compte0, focus gardé dans le champ', e.url === '/utilisateurs?q=compte0' && e.focus === 'filtre-utilisateurs-q', e);
    etape('frappe : 10 lignes', await p.locator('.urow').count() === 10);
    etape('frappe : compteur « 10 résultats sur … »', /^10 résultats sur \d+ comptes$/.test((await p.textContent('#utilisateurs-compte')).trim()));
    await p.selectOption('select[name=role]', 'rh');
    await attendre(async () => (await etat(p)).url === '/utilisateurs?q=compte0&role=rh', 3000);
    etape('liste Rôle : appliquée sans bouton', await p.locator('.urow').count() === 0
      && await p.locator('#utilisateurs-resultats .k-vide').count() === 1);
    await capture(p, 'e2e-13-filtres-vide.png');
    await p.goBack();
    await attendre(async () => (await etat(p)).url === '/utilisateurs?q=compte0' && await p.locator('.urow').count() === 10, 3000);
    e = await etat(p);
    etape('Retour 1 : filtre précédent, sans rechargement', e.marque && await p.inputValue('select[name=role]') === ''
      && await p.inputValue('#filtre-utilisateurs-q') === 'compte0', e);
    await p.goBack();
    await attendre(async () => (await etat(p)).url === '/utilisateurs' && await p.locator('.urow').count() > 30, 3000);
    e = await etat(p);
    etape('Retour 2 : liste complète, champ vidé, sans rechargement', e.marque && docs === 0
      && await p.inputValue('#filtre-utilisateurs-q') === '' && await p.locator('.urow').count() > 30,
      { ...e, docs, champ: await p.inputValue('#filtre-utilisateurs-q'), lignes: await p.locator('.urow').count() });
    // « Effacer les filtres » de l'état vide.
    await p.goto(BASE + '/utilisateurs?q=zzzz');
    await instrumenter(p);
    await p.click('#utilisateurs-resultats .k-vide a');
    await attendre(async () => (await etat(p)).url === '/utilisateurs', 3000);
    e = await etat(p);
    etape('« Effacer les filtres » : liste et champ remis à zéro, focus dans le champ', e.marque && e.focus === 'filtre-utilisateurs-q'
      && await p.inputValue('#filtre-utilisateurs-q') === '', e);

    // --- 4. Session expirée (401) : la page reste, fenêtre de reconnexion ---
    await adm.clearCookies();
    await p.locator(interrupteur(ANCIEN)).scrollIntoViewIfNeeded();
    await instrumenter(p);
    await p.click(interrupteur(ANCIEN));
    await attendre(async () => await p.locator('#k-session-expiree[open]').count() === 1, 4000);
    e = await etat(p);
    etape('401 : fenêtre « Session expirée », page conservée', e.marque && await p.locator('#k-session-expiree[open]').count() === 1, e);
    etape('401 : interrupteur revenu à son état', await p.getAttribute(interrupteur(ANCIEN), 'aria-checked') === 'false');
    etape('401 : lien de reconnexion avec retour', /\/connexion\?next=%2Futilisateurs/.test(await p.getAttribute('#k-session-expiree [data-k-reconnexion]', 'href')));
    await adm.close();

    // --- 5. Mouvement réduit : aucune animation --------------------------------
    const calme = await contexte(navigateur, 'admin@x.tn', { reducedMotion: 'reduce' });
    p = await ouvrir(calme, '/utilisateurs');
    await p.locator(interrupteur(ANCIEN)).scrollIntoViewIfNeeded();
    await p.click(interrupteur(ANCIEN));
    let maxAnim = 0;
    for (let i = 0; i < 6; i++) {
      maxAnim = Math.max(maxAnim, await p.evaluate(() => Math.max(0, ...document.getAnimations()
        .filter((a) => !(a.effect && a.effect.target && a.effect.target.classList && a.effect.target.classList.contains('roue-chargement')))
        .map((a) => Number(a.effect.getTiming().duration) || 0))));
      await pause(80);
    }
    etape('mouvement réduit : aucune animation > 1 ms', maxAnim <= 1, maxAnim);
    await attendre(async () => sql(`SELECT actif FROM utilisateur WHERE id=${ANCIEN}`) === 't', 3000);
    sql(`UPDATE utilisateur SET actif=false WHERE id=${ANCIEN}`);
    // Sans mouvement réduit, l'interrupteur et le toast s'animent bien.
    await calme.close();
    const anime = await contexte(navigateur, 'admin@x.tn');
    p = await ouvrir(anime, '/utilisateurs');
    await p.locator(interrupteur(ANCIEN)).scrollIntoViewIfNeeded();
    await p.click(interrupteur(ANCIEN));
    const nbAnim = await p.evaluate(() => document.getAnimations().length);
    etape('sans mouvement réduit : transitions actives', nbAnim > 0, nbAnim);
    await attendre(async () => sql(`SELECT actif FROM utilisateur WHERE id=${ANCIEN}`) === 't', 3000);
    sql(`UPDATE utilisateur SET actif=false WHERE id=${ANCIEN}`);

    // --- 6. « Voir comme » : aucune écriture proposée --------------------------
    const voir = await anime.newPage();
    voir.on('pageerror', (er) => erreursJs.push(er.message));
    await voir.goto(BASE + '/admin/voir-comme');
    await voir.evaluate(() => { document.getElementById('voir-comme-compte').value = '3'; });
    await Promise.all([voir.waitForNavigation(), voir.click('button:has-text("Voir comme")')]);
    await voir.goto(BASE + '/accueil');
    const actifs = await voir.evaluate(() => {
      const n = (s) => Array.from(document.querySelectorAll(s)).filter((x) => x.offsetParent !== null && !x.disabled).length;
      return { reaction: n('.post-reaction-form button'), commentaire: n('.comment-composer textarea'), reposter: n('[data-open-post-dialog]'),
               revenir: n('#bandeau-admin form[data-permis-lecture] button') };
    });
    etape('Voir comme : réaction, commentaire, reposter désactivés ; « Revenir » actif',
      actifs.reaction === 0 && actifs.commentaire === 0 && actifs.reposter === 0 && actifs.revenir >= 1, actifs);
    etape('Voir comme : <html data-lecture-seule>', await voir.evaluate(() => document.documentElement.hasAttribute('data-lecture-seule')));
    await voir.close();

    // --- 7. Téléphone : barre basse, recherche plein écran, pas de débordement
    for (const theme of ['light', 'dark']) {
      const tel = await contexte(navigateur, 'ali@x.tn', { largeur: 375, hauteur: 760, theme });
      const pt = await ouvrir(tel, '/accueil');
      const deb = await pt.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      etape(`375 px ${theme} : aucun débordement, barre basse visible`, deb === 0 && await pt.locator('.k-nav-basse').isVisible(), deb);
      await pt.click('[data-recherche-ouvrir]');
      etape(`375 px ${theme} : recherche plein écran, focus dans le champ`,
        await pt.evaluate(() => document.body.classList.contains('k-recherche-ouverte') && document.activeElement.id === 'recherche-globale'));
      await pt.keyboard.press('Escape');
      etape(`375 px ${theme} : Échap ferme, focus rendu à la loupe`,
        await pt.evaluate(() => !document.body.classList.contains('k-recherche-ouverte') && document.activeElement.hasAttribute('data-recherche-ouvrir')));
      await capture(pt, `e2e-13-accueil-375-${theme}.png`);
      await tel.close();
    }
    await anime.close();

    // --- 8. Lot 13, phase 2 C : fiche projet, panneau de tâche, fil, projets
    await require('./partiel_fiche.e2e.js')({ navigateur, contexte, ouvrir, etape, sql, attendre, pause, latence,
      instrumenter, etat, capture, BASE });
    etape('aucune erreur JavaScript ni boîte native', erreursJs.length === 0, erreursJs);
  } catch (err) {
    ko++;
    console.log('KO  exception : ' + (err && err.stack ? err.stack.split('\n').slice(0, 3).join('\n    ') : err));
  } finally {
    await navigateur.close();
  }
  console.log(`\n${ok} OK, ${ko} KO`);
  process.exit(ko ? 1 : 0);
})();

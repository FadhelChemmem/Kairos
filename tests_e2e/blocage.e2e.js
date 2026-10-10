/* Scénario Playwright du lot 14 (revue produit P0-1 et P0-2, validées par
 * le gérant) : tâche bloquée avec raison et message de clôture.
 *
 * Lancement : KAIROS_E2E_SCENARIO=blocage bash tests_e2e/lancer.sh [dossier_captures]
 * (base jetable + tests_e2e/seed_blocage.py). Variables : KAIROS_E2E_URL,
 * KAIROS_E2E_DB, KAIROS_E2E_CAPTURES (facultatif), PLAYWRIGHT_MODULE.
 *
 * Vérifie l'écran ET la base, sans rechargement de document :
 * - « Bloquée » ouvre « Qu’est-ce qui bloque ? » par-dessus le panneau
 *   (aucun bouton ne bouge), motif obligatoire, Échap / Annuler ferment ;
 * - le motif est enregistré, affiché sous les états et sur la ligne, porté
 *   par le post « a signalé un blocage » (inséré dans le fil) et par la
 *   notification du chef et du co-chef ; « Annuler » du toast défait tout ;
 * - sections « Bloquées (n) » de l'accueil et des Deadlines (panneau sur
 *   place, « En cours » lève le blocage : post « a levé le blocage ») ;
 * - clôture avec message : post et notification du chef ;
 * - « Voir comme » : aucune écriture ; 375 px et sombre : la question tient
 *   dans l'écran ; aucune erreur JavaScript ni boîte native.
 */
'use strict';
const { execFileSync } = require('child_process');
const path = require('path');
let playwright;
try { playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright'); }
catch (e) { playwright = require('/opt/node-tools/node_modules/playwright'); }
const { chromium } = playwright;

const BASE = process.env.KAIROS_E2E_URL || 'http://127.0.0.1:8798';
const DB = process.env.KAIROS_E2E_DB || 'kairos_e2e_blocage';
const CAPTURES = process.env.KAIROS_E2E_CAPTURES || '';
const MDP = 'Kairos2026!';
const MOTIF = 'Attente des plans archi indice B';
const ALI = 2, RIM = 3, SAMI = 150;

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
async function attendre(fn, delai = 6000) {
  const fin = Date.now() + delai;
  for (;;) { const v = await fn(); if (v) return v; if (Date.now() > fin) return v; await pause(50); }
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
  p.on('pageerror', (e) => erreursJs.push(e.message));
  p.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) erreursJs.push(m.text()); });
  p.on('dialog', (d) => { erreursJs.push('boîte native : ' + d.message()); d.dismiss(); });
  p.docs = 0;
  p.on('request', (r) => { if (r.isNavigationRequest() && r.frame() === p.mainFrame()) p.docs++; });
  await p.goto(BASE + chemin);
  await p.evaluate(() => { window.__marque = 1; });
  p.docs = 0;
  return p;
}
async function capture(p, nom) { if (CAPTURES) await p.screenshot({ path: path.join(CAPTURES, nom) }); }
const sansRechargement = (p) => p.evaluate(() => window.__marque === 1).then((m) => m && p.docs === 0);
const rect = (p, sel) => p.locator(sel).first().evaluate((el) => {
  const r = el.getBoundingClientRect(); return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
});
const memes = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const focusSur = (p, sel) => p.evaluate((s) => !!document.activeElement && document.activeElement.matches(s), sel);
const focusDecrit = (p) => p.evaluate(() => { const a = document.activeElement; return a.tagName + '#' + a.id; });
const toastTexte = (p) => p.locator('#k-toasts .k-toast .k-toast-texte').last().innerText().catch(() => '');

(async () => {
  const navigateur = await chromium.launch();
  try {
    // ==================================================================
    // 1. Rim (intervenante) bloque la tâche 1, panneau latéral (1 440 px)
    // ==================================================================
    const rim = await contexte(navigateur, 'rim@x.tn');
    let p = await ouvrir(rim, '/projets/1?tache=1');
    await p.waitForSelector('#tache-fenetre-1');
    await pause(400);
    const temoins = ['#tache-1-etat-en_cours', '#tache-1-etat-bloque', '#tache-1-cloturer', '#cloture-message-1',
      '#dialog-tache .tache-dialog-fermer', '#tache-1-fichier'];
    const positions = async () => Promise.all(temoins.map((s) => rect(p, s).catch(() => null)));
    const avant = await positions();
    await p.click('#tache-1-etat-bloque');
    await p.waitForSelector('#tache-1-blocage:not([hidden])');
    etape('« Bloquée » ouvre « Qu’est-ce qui bloque ? », focus dans le champ',
      await focusSur(p, '#tache-1-motif') && await p.getAttribute('#tache-1-etat-bloque', 'aria-expanded') === 'true',
      await focusDecrit(p));
    etape('question par-dessus le panneau : aucun bouton ne bouge', memes(avant, await positions()), [avant, await positions()]);
    etape('exemple et aide affichés', await p.getAttribute('#tache-1-motif', 'placeholder') === 'Ex. attente des plans archi indice B'
      && /prévenus/.test(await p.innerText('#tache-1-blocage-aide')));
    etape('rien n’est encore enregistré', sql('SELECT etat FROM tache WHERE id = 1') === 'en_cours');
    await capture(p, 'blocage-question-1440.png');
    // Échap : la question se ferme, le panneau reste, focus sur « Bloquée ».
    await p.fill('#tache-1-motif', 'brouillon');
    await p.keyboard.press('Escape');
    await pause(200);
    etape('Échap ferme la question (saisie vidée), le panneau reste ouvert, focus rendu à « Bloquée »',
      await p.locator('#tache-1-blocage[hidden]').count() === 1 && await p.evaluate(() => document.getElementById('dialog-tache').open)
      && await focusSur(p, '#tache-1-etat-bloque') && await p.inputValue('#tache-1-motif') === '', await focusDecrit(p));
    // Motif vide : refusé sans requête (champ obligatoire).
    let posts = 0;
    p.on('request', (r) => { if (r.method() === 'POST' && /\/taches\/1\/etat$/.test(r.url())) posts++; });
    await p.click('#tache-1-etat-bloque');
    await p.click('#tache-1-blocage-valider');
    await pause(300);
    etape('motif vide : aucun envoi, la question reste ouverte', posts === 0 && await p.locator('#tache-1-blocage:not([hidden])').count() === 1);
    // Espaces seuls : refus du serveur (422), message sous le champ.
    await p.fill('#tache-1-motif', '   ');
    await p.click('#tache-1-blocage-valider');
    await attendre(() => p.evaluate(() => document.getElementById('tache-1-motif').getAttribute('aria-invalid') === 'true'));
    etape('espaces seuls : refus serveur relié au champ (aria-invalid, message)',
      await p.getAttribute('#tache-1-motif', 'aria-invalid') === 'true' && sql('SELECT etat FROM tache WHERE id = 1') === 'en_cours'
      && /Indiquez ce qui bloque/.test(await p.innerText('#tache-1-blocage')));
    // Motif tapé, Entrée : enregistré.
    await p.fill('#tache-1-motif', MOTIF);
    const t0 = Date.now();
    await p.press('#tache-1-motif', 'Enter');
    await attendre(() => p.locator('#tache-1-etat-bloque[aria-pressed="true"]').count());
    const presse = Date.now() - t0;
    await attendre(async () => /Blocage signalé/.test(await toastTexte(p)));
    await pause(250);
    etape('Entrée enregistre : tâche bloquée en base avec son motif, son auteur',
      sql('SELECT etat || \'|\' || bloque_motif || \'|\' || bloque_par FROM tache WHERE id = 1') === `bloque|${MOTIF}|${RIM}`);
    etape('« Bloquée » pressé tout de suite (optimiste)', presse < 1500, presse);
    etape('toast : chef et co-chef prévenus, avec « Annuler »',
      await toastTexte(p) === 'Blocage signalé à Ali Chef et Sami Cochef.'
      && await p.locator('#k-toasts .k-toast-action').count() >= 1, await toastTexte(p));
    etape('aucun rechargement de la page', await sansRechargement(p), p.docs);
    etape('focus sur « Bloquée » après l’envoi', await focusSur(p, '#tache-1-etat-bloque'), await focusDecrit(p));
    etape('motif affiché sous les états du panneau, avec l’auteur',
      (await p.innerText('#tache-1-blocage-detail')).includes(MOTIF)
      && /par Rim Inter/.test(await p.innerText('#tache-1-blocage-detail')), await p.innerText('#tache-1-blocage-detail'));
    etape('états : aucun bouton n’a bougé après l’enregistrement', memes(avant, await positions()), [avant, await positions()]);
    etape('ligne du tableau : motif en infobulle de la pastille',
      (await p.getAttribute('#tache-ligne-1 [data-tache-pastille]', 'title') || '').includes(MOTIF));
    etape('fil : post « a signalé un blocage » inséré sans rechargement',
      await attendre(async () => /a signalé un blocage/.test(await p.innerText('#fil-posts')) && (await p.innerText('#fil-posts')).includes(MOTIF)));
    etape('notifications du chef et du co-chef (vers la tâche), jamais de Rim',
      sql(`SELECT string_agg(utilisateur_id::text, ',' ORDER BY utilisateur_id) FROM notification WHERE tache_id = 1`) === `${ALI},${SAMI}`
      && sql(`SELECT count(*) FROM notification WHERE tache_id = 1 AND translate(message, E'\\u00a0\\u202f', '  ') = 'Rim Inter a bloqué « Note de calcul fondations » (21114X) : ${MOTIF}.'`) === '2');
    await capture(p, 'blocage-enregistre-1440.png');
    // « Annuler » du toast : tout est défait.
    await p.click('#k-toasts .k-toast-action');
    await attendre(() => sql('SELECT etat FROM tache WHERE id = 1') === 'en_cours');
    await pause(400);
    etape('« Annuler » : tâche En cours, post et notifications retirés',
      sql("SELECT count(*) FROM post WHERE evenement IN ('blocage_tache', 'deblocage_tache')") === '0'
      && sql('SELECT count(*) FROM notification WHERE tache_id = 1') === '0'
      && sql('SELECT etat FROM projet WHERE id = 1') === 'en_cours');
    etape('« Annuler » : le panneau suit, focus sur « Bloquée »',
      await p.locator('#tache-1-etat-en_cours[aria-pressed="true"]').count() === 1 && await focusSur(p, '#tache-1-etat-bloque'),
      await focusDecrit(p));
    // Nouveau blocage, gardé.
    await p.click('#tache-1-etat-bloque');
    await p.fill('#tache-1-motif', MOTIF);
    await p.click('#tache-1-blocage-valider');
    await attendre(() => sql('SELECT etat FROM tache WHERE id = 1') === 'bloque');
    await pause(300);

    // ==================================================================
    // 2. Rim termine la tâche 2 avec un message (P0-2)
    // ==================================================================
    await p.click('#tache-ligne-2 [data-ouvrir-tache]');
    await p.waitForSelector('#tache-fenetre-2');
    await pause(300);
    await p.fill('#cloture-message-2', 'Dossier EXE indice B envoyé au BET');
    await p.selectOption('#cloture-tag-2', 'reponse');
    await p.click('#tache-2-cloturer');
    await attendre(() => sql('SELECT etat FROM tache WHERE id = 2') === 'termine');
    await attendre(async () => /Tâche terminée/.test(await toastTexte(p)));
    etape('clôture : post avec le message et le type choisis',
      sql("SELECT type_code || '|' || contenu FROM post WHERE evenement = 'cloture_tache' AND tache_id = 2") === 'reponse|Dossier EXE indice B envoyé au BET');
    etape('clôture : chef et co-chef prévenus (toast et notification)',
      /Ali Chef et Sami Cochef prévenus/.test(await toastTexte(p))
      && sql("SELECT count(*) FROM notification WHERE tache_id = 2 AND translate(message, E'\\u00a0\\u202f', '  ') = 'Rim Inter a terminé « Plans de ferraillage » (21114X) — Réponse : Dossier EXE indice B envoyé au BET.'") === '2',
      await toastTexte(p));
    etape('clôture : aucun rechargement', await sansRechargement(p), p.docs);
    await p.close();

    // ==================================================================
    // 3. Ali (chef) : notification, accueil, Deadlines
    // ==================================================================
    const ali = await contexte(navigateur, 'ali@x.tn');
    p = await ouvrir(ali, '/accueil');
    etape('accueil du chef : section « Bloquées (1) » repliée',
      await p.locator('#taches-bloquees:not([open])').count() === 1 && /Bloquées\s*\(1\)/.test(await p.innerText('#taches-bloquees > summary')));
    await p.click('#taches-bloquees > summary');
    etape('dépliée : motif, jours de blocage et auteur',
      /Attente des plans archi indice B/.test(await p.innerText('#taches-bloquees'))
      && /Depuis aujourd’hui/.test(await p.innerText('#taches-bloquees')) && /par Rim Inter/.test(await p.innerText('#taches-bloquees')));
    await capture(p, 'blocage-accueil-chef-1440.png');
    p = await ouvrir(ali, '/notifications');
    const texteNotifs = (await p.innerText('main')).replace(/[\u00a0\u202f]/g, ' ');
    etape('notification du chef : blocage avec le motif, clôture avec le message',
      texteNotifs.includes(`Rim Inter a bloqué « Note de calcul fondations » (21114X) : ${MOTIF}.`)
      && texteNotifs.includes('Rim Inter a terminé « Plans de ferraillage » (21114X) — Réponse'));
    p = await ouvrir(ali, '/deadlines');
    etape('Deadlines : la tâche bloquée est hors du Gantt', await p.locator('.g-row[data-open-tache="1"]').count() === 0);
    etape('Deadlines : section « Bloquées (1) » sous le Gantt', await p.evaluate(() => {
      const s = document.getElementById('deadlines-bloquees');
      const g = document.getElementById('gantt-carte');
      return !!s && (!g || g.getBoundingClientRect().bottom <= s.getBoundingClientRect().top);
    }));
    await p.click('#deadlines-bloquees > summary');
    await p.click('#deadlines-bloquees [data-open-tache="1"] [data-ouvrir-tache]');
    await p.waitForSelector('#dialog-tache #tache-fenetre-1');
    etape('Deadlines : la tâche s’ouvre sur place (panneau, ?tache=1, sans rechargement)',
      await sansRechargement(p) && await p.evaluate(() => location.search === '?tache=1'));
    await pause(300);
    await p.click('#tache-1-etat-en_cours');
    await attendre(() => sql('SELECT etat FROM tache WHERE id = 1') === 'en_cours');
    await attendre(async () => /Blocage levé/.test(await toastTexte(p)));
    await attendre(() => p.evaluate(() => !document.getElementById('deadlines-bloquees')));
    etape('« En cours » lève le blocage : post « a levé le blocage », section retirée, tâche de retour dans le Gantt',
      sql("SELECT contenu FROM post WHERE evenement = 'deblocage_tache'") === 'Bloqué → En cours'
      && await p.locator('#deadlines-bloquees').count() === 0 && await p.locator('.g-row[data-open-tache="1"]').count() === 1);
    await capture(p, 'blocage-deadlines-leve-1440.png');
    await p.close();

    // ==================================================================
    // 4. « Voir comme » Rim : aucune écriture
    // ==================================================================
    const adm = await contexte(navigateur, 'admin@x.tn');
    p = await ouvrir(adm, '/accueil');
    await p.evaluate(async () => {
      const fd = new FormData(); fd.append('utilisateur_id', '3');
      await fetch('/admin/voir-comme', { method: 'POST', body: fd, credentials: 'same-origin' });
    });
    p = await ouvrir(adm, '/projets/1?tache=1');
    await p.waitForSelector('#tache-fenetre-1');
    await pause(300);
    const desactive = await p.locator('#tache-1-etat-bloque').isDisabled().catch(() => true);
    if (!desactive) await p.click('#tache-1-etat-bloque').catch(() => {});
    await pause(400);
    etape('« Voir comme » : « Bloquée » sans effet (lecture seule), rien en base',
      sql('SELECT etat FROM tache WHERE id = 1') === 'en_cours'
      && await p.locator('#tache-1-blocage:not([hidden])').count() === 0);
    await p.close();

    // ==================================================================
    // 5. 375 px, thème sombre : la question tient dans l'écran
    // ==================================================================
    const mobile = await contexte(navigateur, 'rim@x.tn', { largeur: 375, hauteur: 812, theme: 'dark' });
    p = await ouvrir(mobile, '/projets/1?tache=1');
    await p.waitForSelector('#tache-fenetre-1');
    await pause(500);
    await p.click('#tache-1-etat-bloque');
    await p.waitForSelector('#tache-1-blocage:not([hidden])');
    const boite = await rect(p, '#tache-1-blocage');
    etape('375 px : la question tient dans la largeur, sans débordement horizontal',
      boite.x >= 0 && boite.x + boite.w <= 375 && await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), boite);
    etape('375 px, sombre : texte de la question contrasté', await p.evaluate(() => {
      const lum = (c) => { const v = c.match(/\d+(\.\d+)?/g).slice(0, 3).map(Number).map((x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
      const t = getComputedStyle(document.querySelector('.tache-blocage-titre')).color;
      const f = getComputedStyle(document.getElementById('tache-1-blocage')).backgroundColor;
      const [a, b] = [lum(t), lum(f)].sort((x, y) => y - x);
      return (a + 0.05) / (b + 0.05) >= 4.5;
    }));
    await capture(p, 'blocage-question-375-sombre.png');
    await p.click('#tache-1-blocage [data-blocage-annuler]');
    etape('« Annuler » de la question : fermée, focus sur « Bloquée »',
      await p.locator('#tache-1-blocage[hidden]').count() === 1 && await focusSur(p, '#tache-1-etat-bloque'), await focusDecrit(p));
    await p.close();
  } finally {
    await navigateur.close();
  }
  etape('aucune erreur JavaScript ni boîte native', erreursJs.length === 0, erreursJs.slice(0, 5));
  console.log(`\n${ok} OK, ${ko} KO`);
  process.exit(ko ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });

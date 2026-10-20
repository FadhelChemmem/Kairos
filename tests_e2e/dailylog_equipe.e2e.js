/* Scénario Playwright « Daily log de l'équipe » (lot 14, A3 — revue
 * produit P1-9) et fiche d'une personne (10 derniers jours ouvrés).
 *
 * Lancement : KAIROS_E2E_SCENARIO=dailylog_equipe bash tests_e2e/lancer.sh [dossier_captures]
 * (base jetable + tests_e2e/seed_dailylog_equipe.py).
 *
 * Vérifie : accès (Admin : le bureau ; chef : les personnes de ses projets ;
 * intervenant, RH, client : refusé ; « Voir comme » un chef), lien depuis le
 * Daily log, cases rempli / absent / manquant / grisées avec texte, total
 * de la semaine (week-end compris), ligne de totaux ; semaine précédente /
 * suivante en partiel (aucun rechargement, adresse, Retour, focus, aucun
 * bouton ne bouge, « Semaine suivante » indisponible sur la semaine en
 * cours) ; clic sur une case = Daily log de la personne à ce jour (bandeau
 * de correction) ; page de la personne (jours ouvrés, « Corriger ») ; 1440 / 1024 /
 * 768 / 375 px, clair et sombre (débordement, contrastes, liste par
 * personne sur téléphone) ; aucune erreur JavaScript.
 */
'use strict';
const { execFileSync } = require('child_process');
const path = require('path');
let playwright;
try { playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright'); }
catch (e) { playwright = require(path.join(execFileSync('npm', ['root', '-g']).toString().trim(), 'playwright')); }  // lot 24 (R34) : sans chemin propre à une machine
const { chromium } = playwright;

const BASE = process.env.KAIROS_E2E_URL || 'http://127.0.0.1:8798';
const DB = process.env.KAIROS_E2E_DB || 'kairos_e2e_dailylog_equipe';
const CAPTURES = process.env.KAIROS_E2E_CAPTURES || '';
const MDP = 'Kairos2026!';
const RIM = 3, SAMI = 4, LINA = 7, OMAR = 6, ALI = 2, NADIA = 5;

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
  for (;;) { const v = await fn(); if (v) return v; if (Date.now() > fin) return v; await pause(80); }
}

async function contexte(navigateur, email, opts = {}) {
  const ctx = await navigateur.newContext({ viewport: { width: opts.largeur || 1440, height: opts.largeur < 600 ? 812 : 900 },
    colorScheme: opts.theme || 'light', locale: 'fr-FR', timezoneId: 'Africa/Tunis', hasTouch: !!opts.tactile, isMobile: !!opts.tactile });
  await ctx.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  if (opts.theme === 'dark') await ctx.addInitScript(() => { try { localStorage.setItem('kairos-theme', 'dark'); } catch (e) { /* rien */ } });
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
  p.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|net::/.test(m.text())) erreursJs.push(m.text()); });
  p.on('dialog', (d) => { erreursJs.push('boîte native : ' + d.message()); d.dismiss(); });
  await p.goto(BASE + chemin);
  return p;
}
async function capture(p, nom) { if (CAPTURES) await p.screenshot({ path: path.join(CAPTURES, nom), fullPage: true }); }
const idsPersonnes = (p) => p.$$eval('#dlq tbody .dlq-personne', (a) => a.map((x) => Number(x.getAttribute('href').split('/').pop())));
const ligne = (p, uid) => p.locator(`#dlq tbody tr:has(a.dlq-personne[href="/utilisateurs/${uid}"])`);
const rect = (p, sel) => p.locator(sel).first().evaluate((el) => { const r = el.getBoundingClientRect(); return { x: Math.round(r.left), y: Math.round(r.top + scrollY), w: Math.round(r.width) }; });

/** Contraste des textes de la page (≥ 4,5:1 ; 3:1 pour le gros texte). */
async function contrastes(p, racine) {
  return p.evaluate((sel) => {
    function rgb(c) { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const v = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return { r: v[0], g: v[1], b: v[2], a: v.length > 3 ? v[3] : 1 }; }
    function lum(c) { const f = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); }
    function fond(el) {
      let e = el; const couches = [];
      while (e && e.nodeType === 1) { const c = rgb(getComputedStyle(e).backgroundColor); if (c && c.a > 0) { couches.push(c); if (c.a >= 1) break; } e = e.parentElement; }
      let b = rgb(getComputedStyle(document.body).backgroundColor) || { r: 255, g: 255, b: 255, a: 1 };
      for (let i = couches.length - 1; i >= 0; i--) { const c = couches[i]; b = { r: c.r * c.a + b.r * (1 - c.a), g: c.g * c.a + b.g * (1 - c.a), b: c.b * c.a + b.b * (1 - c.a), a: 1 }; }
      return b;
    }
    const mauvais = [];
    document.querySelectorAll(sel + ' *').forEach((el) => {
      const texte = Array.from(el.childNodes).filter((n) => n.nodeType === 3 && n.textContent.trim()).map((n) => n.textContent.trim()).join(' ');
      if (!texte) return;
      const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
      if (!r.width || !r.height || cs.visibility === 'hidden' || el.closest('[hidden], .sr-only, [aria-disabled="true"]')) return;
      let op = 1, e = el; while (e && e.nodeType === 1) { op *= parseFloat(getComputedStyle(e).opacity); e = e.parentElement; }
      const b = fond(el), c = rgb(cs.color); const f = { r: c.r * op + b.r * (1 - op), g: c.g * op + b.g * (1 - op), b: c.b * op + b.b * (1 - op) };
      const L1 = lum(f), L2 = lum(b), ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
      const gros = parseFloat(cs.fontSize) >= 24 || (parseInt(cs.fontWeight, 10) >= 700 && parseFloat(cs.fontSize) >= 18.66);
      if (ratio < (gros ? 3 : 4.5)) mauvais.push(texte.slice(0, 30) + ' ' + ratio.toFixed(2));
    });
    return mauvais;
  }, racine);
}

(async () => {
  const navigateur = await chromium.launch();
  const lundiPrec = sql("SELECT (date_trunc('week', CURRENT_DATE)::date - 7)");
  const vendrediPrec = sql("SELECT (date_trunc('week', CURRENT_DATE)::date - 3)");
  try {
    // --- 1. Chef : lien depuis le Daily log, personnes de ses projets -------
    const ali = await contexte(navigateur, 'ali@x.tn');
    let p = await ouvrir(ali, '/dailylog');
    etape('chef : lien « Daily log de l’équipe » dans le Daily log', await p.isVisible('#dl-equipe'));
    await Promise.all([p.waitForNavigation(), p.click('#dl-equipe')]);
    etape('page « Daily log de l’équipe » (semaine en cours)', p.url().endsWith('/dailylog/equipe') &&
      (await p.textContent('h1')).includes('Daily log de l’équipe'));
    let ids = await idsPersonnes(p);
    etape('chef : lui, sa co-cheffe et les intervenants de ses projets — ni l’équipe URBS, ni un compte désactivé',
      JSON.stringify([...ids].sort()) === JSON.stringify([ALI, RIM, SAMI, NADIA].sort()), ids);
    etape('semaine en cours : « Semaine suivante » et « Cette semaine » indisponibles',
      await p.getAttribute('#dlq-suiv', 'aria-disabled') === 'true' && await p.getAttribute('#dlq-courante', 'aria-disabled') === 'true');

    // --- 2. Semaine précédente en partiel -----------------------------------
    await p.evaluate(() => { window.__marque = 1; });
    const positions = { prec: await rect(p, '#dlq-prec'), suiv: await rect(p, '#dlq-suiv'), courante: await rect(p, '#dlq-courante') };
    const scrollAvant = await p.evaluate(() => scrollY);
    await p.focus('#dlq-prec');
    await p.keyboard.press('Enter');
    await attendre(async () => p.url().includes('semaine=' + lundiPrec));
    await attendre(async () => (await p.textContent('#dlq-titre')) !== '' && (await p.getAttribute('#dlq-suiv', 'aria-disabled')) === null);
    etape('semaine précédente : sans rechargement, adresse ?semaine=', await p.evaluate(() => window.__marque === 1) && p.url().includes('semaine=' + lundiPrec), p.url());
    etape('focus gardé sur « Semaine précédente » (jamais sur <body>)', await p.evaluate(() => document.activeElement && document.activeElement.id) === 'dlq-prec');
    const apres = { prec: await rect(p, '#dlq-prec'), suiv: await rect(p, '#dlq-suiv'), courante: await rect(p, '#dlq-courante') };
    etape('aucun bouton de navigation ne bouge (position et largeur)', JSON.stringify(positions) === JSON.stringify(apres), [positions, apres]);
    etape('défilement gardé', Math.abs((await p.evaluate(() => scrollY)) - scrollAvant) <= 40);
    const rim = ligne(p, RIM);
    const cases = await rim.locator('td.dlq-case').evaluateAll((tds) => tds.map((td) => td.className.replace('dlq-case ', '') + ':' + td.textContent.replace(/\s+/g, ' ').trim()));
    etape('Rim : 3 jours remplis (7 h 30), absente jeudi, vendredi manquant',
      JSON.stringify(cases) === JSON.stringify(['dlq-rempli:7 h 30', 'dlq-rempli:7 h 30', 'dlq-rempli:7 h 30', 'dlq-absent:Absent', 'dlq-manquant:!Manquant']), cases);
    const totalRim = (await rim.locator('td.dlq-total').textContent()).replace(/\s+/g, ' ').trim();
    etape('Rim : total de la semaine samedi compris (25 h 30), signalé', totalRim.startsWith('25 h 30') && totalRim.includes('le week-end'), totalRim);
    const resume = (await p.textContent('.dlq-resume')).replace(/\s+/g, ' ');
    etape('résumé : 15 jours non renseignés (4 personnes)', resume.includes('15 jours non renseignés') && resume.includes('4 personnes'), resume);
    const pied = await p.$$eval('#dlq tfoot td.dlq-pied', (tds) => tds.map((td) => td.textContent.replace(/\s+/g, ' ').trim()));
    etape('ligne de totaux : lundi 15 h 30, 2 manquants', pied[0].startsWith('15 h 30') && pied[0].includes('2 manquants'), pied);
    etape('couleur jamais seule : chaque case porte un texte ou un libellé', await p.$$eval('#dlq td.dlq-case .dlq-lien', (l) => l.every((x) => x.textContent.trim() && x.getAttribute('aria-label'))));
    await capture(p, 'dlq-chef-1440-clair.png');

    // Retour : semaine en cours, en partiel.
    await p.goBack();
    await attendre(async () => (await p.getAttribute('#dlq-suiv', 'aria-disabled')) === 'true');
    etape('Retour : semaine en cours, sans rechargement', await p.evaluate(() => window.__marque === 1) && !p.url().includes('semaine='));
    await p.goForward();
    await attendre(async () => (await p.getAttribute('#dlq-suiv', 'aria-disabled')) === null);

    // --- 3. Clic sur une case = Daily log de la personne à ce jour ---------
    await Promise.all([p.waitForNavigation(), ligne(p, RIM).locator('td.dlq-manquant a').click()]);
    etape('case manquante → Daily log de Rim à ce jour (correction)', p.url().includes(`date=${vendrediPrec}`) && p.url().includes(`utilisateur=${RIM}`) &&
      (await p.textContent('#dl-correction')).includes('Rim Inter'), p.url());
    await p.waitForFunction(() => window.KairosDailyLogPage && !window.KairosDailyLogPage.etat().chargement);
    etape('correction : aucune tâche proposée (Daily log d’une autre personne)', (await p.evaluate(() => window.KairosDailyLogPage.etat().rows.length)) === 0);
    await p.goBack();
    await p.waitForSelector('#dlq');
    etape('Retour du navigateur : Daily log de l’équipe', p.url().includes('/dailylog/equipe'));
    await p.close();

    // --- 4. Fiche d'une personne : 10 derniers jours ouvrés ----------------
    // Lot 15 : une seule page par personne (le chef y arrive depuis la fiche),
    // deux semaines : jours ouvrés avec leur état réel, « Corriger ».
    p = await ouvrir(ali, `/utilisateurs/${RIM}`);
    etape('fiche du chef : page de la personne', p.url().endsWith(`/utilisateurs/${RIM}/profil`), p.url());
    await p.goto(BASE + `/utilisateurs/${RIM}/profil?semaines=2`);
    const jours = await p.$$eval('#profil-activite .dl-semaine-jour', (j) => j.length);
    etape('page de la personne : Daily log de deux semaines (jours ouvrés au moins)', jours >= 10 && (await p.textContent('#dailylog')).includes('2 dernières semaines'), jours);
    const vendredi = p.locator(`#profil-activite .dl-semaine-jour:has(a[href*="date=${vendrediPrec}"])`);
    etape('fiche : vendredi « Non renseigné » avec « Corriger »', (await vendredi.textContent()).includes('Non renseigné') && await vendredi.locator('a:has-text("Corriger")').count() === 1);
    await Promise.all([p.waitForNavigation(), vendredi.locator('a:has-text("Corriger")').click()]);
    etape('« Corriger » ouvre le Daily log de la personne à ce jour', p.url().includes(`date=${vendrediPrec}`) && p.url().includes(`utilisateur=${RIM}`));
    await p.close();
    await ali.close();

    // --- 5. Admin : tout le bureau ------------------------------------------
    const adm = await contexte(navigateur, 'admin@x.tn');
    p = await ouvrir(adm, '/dailylog/equipe?semaine=' + lundiPrec);
    ids = await idsPersonnes(p);
    etape('Admin : tout le bureau (chefs, intervenants des deux équipes), sans RH, client ni compte désactivé',
      JSON.stringify([...ids].sort()) === JSON.stringify([ALI, RIM, SAMI, NADIA, OMAR, LINA].sort()), ids);
    etape('Admin : portée « Tout le bureau »', (await p.textContent('.dlq-portee')).includes('Tout le bureau'));
    await capture(p, 'dlq-admin-1440-clair.png');
    // « Voir comme » le chef : sa vue, en lecture.
    await p.goto(BASE + '/admin/voir-comme');
    await p.evaluate((id) => { document.getElementById('voir-comme-compte').value = String(id); }, ALI);
    await Promise.all([p.waitForNavigation(), p.click('button:has-text("Voir comme")')]);
    await p.goto(BASE + '/dailylog/equipe');
    ids = await idsPersonnes(p);
    etape('« Voir comme » le chef : sa vue d’équipe', JSON.stringify([...ids].sort()) === JSON.stringify([ALI, RIM, SAMI, NADIA].sort()), ids);
    await p.click('#bandeau-admin button:has-text("Revenir à mon compte")');
    await p.waitForLoadState();
    await p.close();
    await adm.close();

    // --- 6. Refus : intervenant, RH, client ---------------------------------
    for (const [email, nom] of [['rim@x.tn', 'intervenant'], ['rh@x.tn', 'RH'], ['client@x.tn', 'client']]) {
      const ctx = await contexte(navigateur, email);
      const q = await ouvrir(ctx, '/dailylog/equipe');
      etape(`${nom} : page refusée (retour à l’accueil, aucune donnée)`, !q.url().includes('/dailylog/equipe') && await q.locator('#dlq').count() === 0, q.url());
      if (nom === 'intervenant') {
        await q.goto(BASE + '/dailylog');
        etape('intervenant : pas de lien « Daily log de l’équipe »', await q.locator('#dl-equipe').count() === 0);
        const r = await q.evaluate(async () => (await fetch('/dailylog/equipe', { headers: { 'X-Kairos-Partiel': '#dlq', 'X-Requested-With': 'XMLHttpRequest' } })).status);
        etape('intervenant : requête partielle forgée refusée', r !== 200, r);
      }
      await ctx.close();
    }

    // --- 7. Largeurs et thèmes ----------------------------------------------
    for (const theme of ['light', 'dark']) {
      for (const largeur of [1440, 1024, 768, 375]) {
        const ctx = await contexte(navigateur, 'ali@x.tn', { largeur, theme, tactile: largeur < 600 });
        const q = await ouvrir(ctx, '/dailylog/equipe?semaine=' + lundiPrec);
        const m = await q.evaluate(() => {
          const lien = document.querySelector('#dlq td.dlq-case .dlq-lien').getBoundingClientRect();
          const tr = document.querySelector('#dlq tbody tr');
          return { deborde: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                   hauteur: lien.height, affichage: getComputedStyle(tr).display };
        });
        etape(`${largeur} px ${theme} : pas de défilement horizontal, cases ≥ 36 px`, !m.deborde && m.hauteur >= 36, m);
        if (largeur < 600) etape(`${largeur} px : liste par personne (une carte par personne)`, m.affichage === 'grid', m);
        const c = await contrastes(q, '#dlq');
        etape(`${largeur} px ${theme} : contrastes ≥ 4,5:1`, c.length === 0, c);
        await capture(q, `dlq-chef-${largeur}-${theme === 'dark' ? 'sombre' : 'clair'}.png`);
        await ctx.close();
      }
    }
  } finally {
    await navigateur.close();
  }
  etape('aucune erreur JavaScript ni boîte native', erreursJs.length === 0, erreursJs.slice(0, 5));
  console.log(`\n${ok} étapes OK, ${ko} KO`);
  process.exit(ko ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });

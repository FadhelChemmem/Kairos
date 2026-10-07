/* Scénario Playwright de bout en bout du Daily log v9 (lot 10).
 *
 * Lancement : bash tests_e2e/lancer.sh [dossier_captures]
 * (base jetable + jeu de données tests_e2e/seed_dailylog.py + serveur Flask).
 * Variables : KAIROS_E2E_URL, KAIROS_E2E_DB (base PostgreSQL, lue avec psql),
 * KAIROS_E2E_CAPTURES (facultatif), PLAYWRIGHT_MODULE (chemin du module).
 *
 * Chaque étape vérifie l'écran ET la base : saisie −/+, saisie texte,
 * plafond de 10 h, enregistrement, clavier, changement de jour avec
 * enregistrement automatique, copie + annuler, absent + annuler,
 * calendrier, flèches qui sautent le week-end, ancienne valeur au quart
 * d'heure, réponse lente périmée, bannière, keepalive à la fermeture,
 * conflit 409 (deux choix), fenêtre de 14 jours, session expirée et
 * brouillon, correction par le chef (ligne masquée, audit), recherche sans
 * accents et tâches, téléphone 375 px, thème sombre (contrastes).
 */
'use strict';
const { execFileSync } = require('child_process');
const path = require('path');
let playwright;
try { playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright'); }
catch (e) { playwright = require('/home/claude/.npm-global/lib/node_modules/playwright'); }
const { chromium } = playwright;

const BASE = process.env.KAIROS_E2E_URL || 'http://127.0.0.1:8798';
const DB = process.env.KAIROS_E2E_DB || 'kairos_e2e_dailylog';
const CAPTURES = process.env.KAIROS_E2E_CAPTURES || '';
const MDP = 'Kairos2026!';
const RIM = 3, ALI = 2;

let ok = 0, ko = 0;
const erreursJs = [];
function etape(nom, cond, detail) {
  if (cond) { ok++; console.log('OK  ' + nom); }
  else { ko++; console.log('KO  ' + nom + (detail !== undefined ? ' — ' + JSON.stringify(detail) : '')); }
}
function sql(requete) {
  return execFileSync('psql', ['-X', '-At', '-d', DB, '-c', requete], { encoding: 'utf8' }).trim();
}
function isoTunis(decalage) {
  const d = new Date(Date.now() + (decalage || 0) * 86400000);
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Tunis' }).format(d);
}
function ajouter(k, n) {
  const p = k.split('-'), d = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2] + n));
  return d.toISOString().slice(0, 10);
}
function jourSemaine(k) { const p = k.split('-'); return (new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])).getUTCDay() + 6) % 7; }
function ouvre(k, sens) { let d = ajouter(k, sens); while (jourSemaine(d) >= 5) d = ajouter(d, sens); return d; }
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
async function attendre(fn, delai = 5000) {
  const fin = Date.now() + delai;
  for (;;) { const v = await fn(); if (v) return v; if (Date.now() > fin) return v; await pause(100); }
}
function heures(uid, date) { return sql(`SELECT coalesce(sum(heures),0) FROM dailylog_entree WHERE utilisateur_id=${uid} AND date='${date}'`); }

async function contexte(navigateur, email, opts = {}) {
  const ctx = await navigateur.newContext({ viewport: { width: opts.largeur || 1280, height: opts.hauteur || 900 },
    hasTouch: !!opts.tactile, isMobile: !!opts.tactile });
  await ctx.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  if (email) {
    const p = await ctx.newPage();
    await p.goto(BASE + '/connexion');
    await p.fill('#email', email);
    await p.fill('#password', MDP);
    await Promise.all([p.waitForNavigation(), p.click('button[type=submit]')]);
    await p.close();
  }
  return ctx;
}
async function ouvrir(ctx, chemin) {
  const p = await ctx.newPage();
  p.on('pageerror', (e) => erreursJs.push(e.message));
  // « Failed to load resource » : réponses 409 / 400 / 401 attendues du scénario (journal réseau du navigateur).
  p.on('console', (m) => { if (m.type() === 'error' && !/ERR_FAILED|net::|Failed to load resource/.test(m.text())) erreursJs.push(m.text()); });
  p.on('dialog', (d) => d.accept());
  await p.goto(BASE + chemin);
  await pret(p);
  return p;
}
async function pret(p) {
  await p.waitForFunction(() => window.KairosDailyLogPage && !window.KairosDailyLogPage.etat().chargement, null, { timeout: 8000 });
}
const etat = (p) => p.evaluate(() => window.KairosDailyLogPage.etat());
const valeur = (p, cle) => p.inputValue(`#dl-liste .dl-row[data-cle="${cle}"] .dl-val`);
const statut = (p) => p.textContent('#dl-status-texte');
const toast = (p) => p.textContent('#dl-toast');
async function saisir(p, cle, texte) {
  const v = `#dl-liste .dl-row[data-cle="${cle}"] .dl-val`;
  await p.click(v);
  await p.fill(v, texte);
  await p.press(v, 'Enter');
}
async function plus(p, cle, n = 1) { for (let i = 0; i < n; i++) await p.click(`#dl-liste .dl-row[data-cle="${cle}"] .dl-plus`); }
async function moins(p, cle, n = 1) { for (let i = 0; i < n; i++) await p.click(`#dl-liste .dl-row[data-cle="${cle}"] .dl-minus`); }
async function capture(p, nom) { if (CAPTURES) await p.screenshot({ path: path.join(CAPTURES, nom), fullPage: true }); }
async function theme(p, t) {
  await p.evaluate((x) => { document.documentElement.dataset.theme = x; }, t);
  await pause(400);  // fin des transitions de couleur (.dl-pname : 0,15 s)
}

/** Contraste des textes de la page Daily log (≥ 4,5:1, 3:1 pour le gros texte). */
async function contrastes(p) {
  return p.evaluate(() => {
    function rgb(c) { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const v = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return { r: v[0], g: v[1], b: v[2], a: v.length > 3 ? v[3] : 1 }; }
    function lum(c) { const f = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); }
    function fond(el) {
      let e = el, couches = [];
      while (e && e.nodeType === 1) { const c = rgb(getComputedStyle(e).backgroundColor); if (c && c.a > 0) { couches.push(c); if (c.a >= 1) break; } e = e.parentElement; }
      let b = rgb(getComputedStyle(document.body).backgroundColor) || { r: 255, g: 255, b: 255, a: 1 };
      for (let i = couches.length - 1; i >= 0; i--) { const c = couches[i]; b = { r: c.r * c.a + b.r * (1 - c.a), g: c.g * c.a + b.g * (1 - c.a), b: c.b * c.a + b.b * (1 - c.a), a: 1 }; }
      return b;
    }
    const mauvais = [];
    document.querySelectorAll('#dl9 *').forEach((el) => {
      const texte = Array.from(el.childNodes).filter((n) => n.nodeType === 3 && n.textContent.trim()).map((n) => n.textContent.trim()).join(' ');
      if (!texte) return;
      const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
      if (!r.width || !r.height || cs.visibility === 'hidden' || cs.display === 'none' || el.closest('[hidden]') || el.closest('.dl-toast:not(.dl-show)')) return;
      if (el.closest('[disabled]') || el.closest('.dl-off') || el.closest('.dl-full')) return; // inactifs : hors critère (WCAG 1.4.3)
      let op = 1, e = el; while (e && e.nodeType === 1) { op *= parseFloat(getComputedStyle(e).opacity); e = e.parentElement; }
      const b = fond(el), c = rgb(cs.color); const f = { r: c.r * op + b.r * (1 - op), g: c.g * op + b.g * (1 - op), b: c.b * op + b.b * (1 - op) };
      const L1 = lum(f), L2 = lum(b), ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
      const gros = parseFloat(cs.fontSize) >= 24 || (parseInt(cs.fontWeight, 10) >= 700 && parseFloat(cs.fontSize) >= 18.66);
      if (ratio < (gros ? 3 : 4.5)) mauvais.push(texte.slice(0, 30) + ' ' + ratio.toFixed(2));
    });
    return mauvais;
  });
}

(async () => {
  const T = isoTunis(0);
  const navigateur = await chromium.launch();
  const rim = await contexte(navigateur, 'rim@x.tn');
  let p = await ouvrir(rim, '/dailylog');

  // 1. Page, proposition des projets à 0 h
  let e = await etat(p);
  etape('page chargée sur aujourd\'hui (fuseau de Tunis)', e.sel === T, e.sel);
  etape('mes projets proposés à 0 h (Bloqué compris)', ['1:0', '2:0', '3:0'].every((k) => e.rows.some((r) => r.cle === k && r.m === 0)), e.rows.map((r) => r.cle));
  etape('statut « Nouvelle saisie »', (await statut(p)) === 'Nouvelle saisie');
  await capture(p, 'dailylog-1280-clair-nouveau.png');

  // 2. −/+
  await plus(p, '1:0', 3);
  etape('+ ×3 → 1 h 30', (await valeur(p, '1:0')) === '1 h 30');
  await moins(p, '1:0');
  etape('− → 1 h', (await valeur(p, '1:0')) === '1 h');
  etape('statut « Modifié · non enregistré »', (await statut(p)) === 'Modifié · non enregistré');

  // 3. Saisie texte
  await saisir(p, '2:0', '2,25');
  etape('« 2,25 » arrondi à 2 h 30', (await valeur(p, '2:0')) === '2 h 30');
  etape('toast « Arrondi à 2 h 30 »', (await toast(p)).includes('Arrondi à 2 h 30'), await toast(p));
  await saisir(p, '3:0', '45min');
  etape('« 45min » → 1 h (arrondi)', (await valeur(p, '3:0')) === '1 h');
  await saisir(p, '3:0', 'abc');
  etape('format refusé, valeur conservée', (await valeur(p, '3:0')) === '1 h' && (await toast(p)).includes('Format non reconnu'));
  await saisir(p, '3:0', '2h30');
  await saisir(p, '3:0', '1:00');
  etape('« 2h30 » puis « 1:00 »', (await valeur(p, '3:0')) === '1 h');

  // 4. Plafond de 10 h
  await saisir(p, '1:0', '9');
  etape('10 h : ligne plafonnée à 6 h 30', (await valeur(p, '1:0')) === '6 h 30', await valeur(p, '1:0'));
  etape('toast « Maximum 6 h 30 sur cette ligne »', (await toast(p)).includes('Maximum 6 h 30'), await toast(p));
  etape('+ désactivé à 10 h', await p.isDisabled('#dl-liste .dl-row[data-cle="2:0"] .dl-plus'));
  etape('total 10 h, jauge role=meter', (await p.textContent('#dl-total')) === '10 h' && (await p.getAttribute('#dl-jauge', 'aria-valuenow')) === '10');

  // 5. Enregistrer
  await p.click('#dl-enregistrer');
  await attendre(async () => (await statut(p)) === 'Enregistré');
  etape('enregistré (statut)', (await statut(p)) === 'Enregistré');
  etape('en base : 10 h, version 1, projet Bloqué compris', heures(RIM, T) === '10.00' &&
    sql(`SELECT version FROM dailylog_jour WHERE utilisateur_id=${RIM} AND date='${T}'`) === '1' &&
    sql(`SELECT heures FROM dailylog_entree WHERE utilisateur_id=${RIM} AND date='${T}' AND projet_id=3`) === '1.00');

  // 6. Clavier
  const v3 = '#dl-liste .dl-row[data-cle="3:0"] .dl-val';
  await p.focus(v3);
  await p.keyboard.press('ArrowDown');
  etape('↓ → 30 min', (await valeur(p, '3:0')) === '30 min');
  await p.keyboard.press('ArrowUp');
  etape('↑ → 1 h', (await valeur(p, '3:0')) === '1 h');
  await p.keyboard.type('5');
  await p.keyboard.press('Escape');
  etape('Échap rend la valeur', (await valeur(p, '3:0')) === '1 h');
  etape('le focus reste dans le champ', await p.evaluate(() => document.activeElement && document.activeElement.classList.contains('dl-val')));
  await p.keyboard.press('ArrowDown');

  // 7. Changement de jour : enregistrement automatique
  const jPrec = ouvre(T, -1);
  await p.click('#dl-prec');
  await pret(p);
  etape('‹ → jour ouvré précédent', (await etat(p)).sel === jPrec, (await etat(p)).sel);
  await attendre(async () => heures(RIM, T) === '9.50');
  etape('autosave au changement de jour (9,5 h en base)', heures(RIM, T) === '9.50', heures(RIM, T));
  etape('toast « enregistré automatiquement »', (await toast(p)).includes('enregistré automatiquement'), await toast(p));
  etape('URL suit le jour (replaceState)', p.url().includes('date=' + jPrec));

  // 8. Copier + Annuler (jour sans saisie)
  const libelleCopie = await p.textContent('#dl-copier');
  etape('bouton « Copier le … »', /^Copier le /.test(libelleCopie.trim()), libelleCopie);
  await p.click('#dl-copier');
  e = await etat(p);
  etape('copie : lignes remises sur la grille', e.rows.filter((r) => r.m > 0).every((r) => r.m % 30 === 0) && e.total > 0, e.rows);
  etape('toast « Copié depuis le … » avec Annuler', (await toast(p)).includes('Copié depuis le') && await p.isVisible('#dl-toast .dl-undo'));
  await p.click('#dl-toast .dl-undo');
  etape('Annuler la copie', (await etat(p)).total === 0);

  // 9. Absent + Annuler
  await saisir(p, '1:0', '2');
  await p.click('#dl-absent');
  await attendre(async () => (await p.isVisible('.dl-absentcard')));
  etape('jour absent : carte affichée', await p.isVisible('.dl-absentcard'));
  etape('en base : absent, aucune heure', sql(`SELECT absent FROM dailylog_jour WHERE utilisateur_id=${RIM} AND date='${jPrec}'`) === 't' && heures(RIM, jPrec) === '0');
  await p.click('#dl-toast .dl-undo');
  await attendre(async () => heures(RIM, jPrec) === '2.00');
  etape('Annuler l\'absence rend les heures', heures(RIM, jPrec) === '2.00' &&
    sql(`SELECT absent FROM dailylog_jour WHERE utilisateur_id=${RIM} AND date='${jPrec}'`) === 'f');

  // 10. Calendrier (non modal, flèches, pastilles)
  await p.click('#dl-date');
  await p.waitForSelector('#dl-cal:not([hidden]) .dl-cal-day');
  etape('calendrier : focus sur le jour choisi', await p.evaluate(() => document.activeElement.classList.contains('dl-sel')));
  etape('calendrier : 3 pastilles (rempli / absent / non renseigné)', await p.evaluate(() =>
    !!document.querySelector('.dl-cal-day.dl-rempli .dl-pip') && !!document.querySelector('.dl-cal-day.dl-vide .dl-pip')));
  await p.keyboard.press('ArrowLeft');
  const cible = await p.evaluate(() => document.activeElement.dataset.d);
  await p.keyboard.press('Enter');
  await pret(p);
  etape('flèche ← puis Entrée : jour choisi', (await etat(p)).sel === cible, cible);
  await p.click('#dl-date');
  await p.keyboard.press('Escape');
  etape('Échap ferme le calendrier', await p.isHidden('#dl-cal'));

  // 11. Week-end : les flèches le sautent, le calendrier le permet
  let lundi = T; while (jourSemaine(lundi) !== 0) lundi = ajouter(lundi, -1);
  await p.goto(BASE + '/dailylog?date=' + lundi); await pret(p);
  await p.click('#dl-prec'); await pret(p);
  etape('‹ depuis un lundi → vendredi', (await etat(p)).sel === ajouter(lundi, -3), (await etat(p)).sel);
  const samedi = ajouter(lundi, -2);
  if (samedi.slice(0, 7) === (await etat(p)).sel.slice(0, 7)) {
    await p.click('#dl-date');
    await p.click(`.dl-cal-day[data-d="${samedi}"]`);
    await pret(p);
    etape('samedi choisi dans le calendrier', (await etat(p)).sel === samedi);
    await p.click('#dl-suiv'); await pret(p);
    etape('› depuis un samedi → lundi', (await etat(p)).sel === lundi);
  }

  // 12. Ancienne ligne au quart d'heure (J-5 : 2,25 h sur la tâche) : − → 2 h, + → 2 h 30
  const j5 = isoTunis(-5);
  await p.goto(BASE + '/dailylog?date=' + j5); await pret(p);
  etape('2 h 15 affichée telle quelle', (await valeur(p, '1:1')) === '2 h 15', await valeur(p, '1:1'));
  await plus(p, '1:1');
  etape('+ sur 2 h 15 → 2 h 30', (await valeur(p, '1:1')) === '2 h 30');
  await moins(p, '1:1', 2);
  etape('− ×2 → 1 h 30 (2 h puis 1 h 30)', (await valeur(p, '1:1')) === '1 h 30');
  await saisir(p, '1:1', '2,5');
  await p.click('#dl-enregistrer');
  await attendre(async () => (await statut(p)) === 'Enregistré');
  etape('ancienne ligne 5,75 h gardée, la modifiée sur la grille', sql(`SELECT string_agg(heures::text, ',' ORDER BY projet_id) FROM dailylog_entree WHERE utilisateur_id=${RIM} AND date='${j5}'`) === '2.50,5.75');

  // 13. Réponse lente périmée (jeton de séquence)
  await p.goto(BASE + '/dailylog?date=' + T); await pret(p);
  const lent = ouvre(T, -1), lent2 = ouvre(lent, -1);
  await p.route(`**/dailylog/api/jour/${lent}`, async (r) => { await pause(1500); await r.continue(); });
  await p.click('#dl-prec');
  await p.click('#dl-prec');
  await pause(2200);
  await p.unroute(`**/dailylog/api/jour/${lent}`);
  etape('réponse lente de J-1 ignorée : l\'écran montre J-2', (await etat(p)).sel === lent2 && (await p.textContent('#dl-date-label')).length > 0, (await etat(p)).sel);

  // 14. Bannière des jours manqués
  const puces = await p.$$eval('#dl-banniere .dl-chip', (b) => b.map((x) => x.dataset.g));
  etape('bannière : jours manqués (jamais un week-end)', puces.length > 0 && puces.every((k) => jourSemaine(k) < 5), puces);
  await p.click(`#dl-banniere .dl-chip[data-g="${puces[0]}"]`); await pret(p);
  etape('puce de la bannière → ce jour', (await etat(p)).sel === puces[0]);

  // 15. keepalive à la fermeture
  const jKeep = puces[0];
  await plus(p, '1:0', 2);
  await p.close({ runBeforeUnload: true });
  await attendre(() => heures(RIM, jKeep) === '1.00', 4000);
  etape('fermeture : PUT keepalive enregistré en base', heures(RIM, jKeep) === '1.00', heures(RIM, jKeep));
  p = await ouvrir(rim, '/dailylog?date=' + jKeep);
  await plus(p, '1:0');
  // Navigation par un lien (comme l'utilisateur) : un page.goto() du pilote
  // coupe le document avant que ses requêtes de pagehide ne partent (mesuré :
  // 2 sur 10 délivrées, même avec sendBeacon), un clic : 10 sur 10.
  await Promise.all([p.waitForNavigation(), p.click('a[aria-label="Accueil"]')]);
  await attendre(() => heures(RIM, jKeep) === '1.50', 4000);
  etape('navigation vers une autre page : enregistré (pagehide)', heures(RIM, jKeep) === '1.50', heures(RIM, jKeep));

  // 16. Conflit 409 : deux onglets
  const a = await ouvrir(rim, '/dailylog?date=' + T);
  const b = await ouvrir(rim, '/dailylog?date=' + T);
  await plus(a, '2:0'); await a.click('#dl-enregistrer'); await attendre(async () => (await statut(a)) === 'Enregistré');
  await plus(b, '3:0'); await b.click('#dl-enregistrer');
  await attendre(async () => (await toast(b)).includes('modifiée ailleurs'));
  etape('409 : toast « modifiée ailleurs » avec deux choix', (await b.$$('#dl-toast .dl-undo')).length === 2, await toast(b));
  await b.click('#dl-toast .dl-undo >> text=Garder ma saisie');
  await attendre(async () => (await statut(b)) === 'Enregistré');
  etape('« Garder ma saisie » : réenregistré avec la nouvelle version', heures(RIM, T) === '10.00' &&
    sql(`SELECT heures FROM dailylog_entree WHERE utilisateur_id=${RIM} AND date='${T}' AND projet_id=2`) === '2.50', heures(RIM, T));
  await moins(a, '1:0'); await a.click('#dl-enregistrer');
  await attendre(async () => (await toast(a)).includes('modifiée ailleurs'));
  await a.click('#dl-toast .dl-undo >> text=Reprendre la version enregistrée');
  etape('« Reprendre la version enregistrée »', (await statut(a)) === 'Enregistré' && (await etat(a)).total === 600, (await etat(a)).total);
  await a.close(); await b.close();

  // 17. Au-delà de 14 jours : lecture seule
  const j20 = isoTunis(-20);
  await p.goto(BASE + '/dailylog?date=' + j20); await pret(p);
  etape('J-20 : lecture seule (aucun champ, bandeau)', (await p.$$('#dl-liste .dl-val')).length === 0 &&
    (await p.$$('#dl-liste .dl-fixe')).length === 2 && (await p.textContent('#dl-lecture')).includes('Au-delà de 14 jours') &&
    await p.isHidden('#dl-enregistrer') && await p.isHidden('#dl-ajout'));
  const j14 = isoTunis(-14);
  await p.goto(BASE + '/dailylog?date=' + j14); await pret(p);
  etape('J-14 : saisie libre', (await etat(p)).rows.length === 0 || (await p.$$('#dl-liste .dl-val')).length > 0);

  // 18. Recherche sans accents, tâche d'un projet
  await p.goto(BASE + '/dailylog?date=' + T); await pret(p);
  await moins(p, '1:0', 4);
  await p.click('#dl-ajouter');
  await p.fill('#dl-recherche', 'ete');
  await attendre(async () => (await p.$$('#dl-catalogue-corps [data-add="4:0"]')).length > 0);
  etape('recherche « ete » → Résidence Été', (await p.$$('#dl-catalogue-corps [data-add="4:0"]')).length === 1);
  await p.click('#dl-catalogue-corps [data-add="4:0"]');
  etape('projet ajouté à 30 min', (await valeur(p, '4:0')) === '30 min');
  await p.click('#dl-ajouter');
  await p.click('#dl-catalogue-corps [data-taches="1"]');
  await attendre(async () => (await p.$$('#dl-catalogue-corps [data-add="1:2"]')).length > 0);
  await p.click('#dl-catalogue-corps [data-add="1:2"]');
  etape('imputation à une tâche du projet', (await p.textContent('#dl-liste .dl-row[data-cle="1:2"] .dl-pcode')).includes('Plans de ferraillage'));
  await p.click('#dl-enregistrer');
  await attendre(async () => (await statut(p)) === 'Enregistré');
  etape('ligne de tâche en base', sql(`SELECT heures FROM dailylog_entree WHERE utilisateur_id=${RIM} AND date='${T}' AND tache_id=2`) === '0.50');

  // 19. Session expirée : brouillon gardé sur l'appareil
  await rim.clearCookies();
  await plus(p, '4:0');
  await p.click('#dl-enregistrer');
  await attendre(async () => (await toast(p)).includes('Session expirée'));
  etape('session expirée : message', (await toast(p)).includes('Session expirée'), await toast(p));
  etape('brouillon en sessionStorage', await p.evaluate((d) => Object.keys(sessionStorage).some((k) => k.endsWith('-' + d)), T));
  await p.goto(BASE + '/connexion');
  await p.fill('#email', 'rim@x.tn'); await p.fill('#password', MDP);
  await Promise.all([p.waitForNavigation(), p.click('button[type=submit]')]);
  await p.goto(BASE + '/dailylog?date=' + T); await pret(p);
  await attendre(async () => (await toast(p)).includes('non enregistrée'));
  etape('brouillon retrouvé après reconnexion', (await toast(p)).includes('non enregistrée'), await toast(p));
  await p.click('#dl-toast .dl-undo');
  await p.click('#dl-enregistrer');
  await attendre(async () => (await statut(p)) === 'Enregistré');
  etape('brouillon restauré et enregistré', sql(`SELECT heures FROM dailylog_entree WHERE utilisateur_id=${RIM} AND date='${T}' AND projet_id=4`) === '1.00');

  // 19 bis. Objectif de journée (préférence personnelle) et « Vider la journée »
  await p.click('#dl-obj-moins');
  await attendre(() => sql(`SELECT objectif_minutes FROM dailylog_preference WHERE utilisateur_id=${RIM}`) === '450', 3000);
  etape('objectif 7 h 30 enregistré (préférence, jour non modifié)', (await p.textContent('#dl-obj-val')) === '7 h 30' &&
    sql(`SELECT objectif_minutes FROM dailylog_preference WHERE utilisateur_id=${RIM}`) === '450' && (await statut(p)) === 'Enregistré');
  await p.click('#dl-obj-plus');
  await Promise.all([p.waitForNavigation(), p.click('a[aria-label="Daily log"]')]);   // clic juste avant de quitter la page
  await pret(p);
  await p.goto(BASE + '/dailylog?date=' + jPrec); await pret(p);
  await attendre(() => sql(`SELECT objectif_minutes FROM dailylog_preference WHERE utilisateur_id=${RIM}`) === '480', 3000);
  etape('objectif réglé juste avant de quitter la page : enregistré', sql(`SELECT objectif_minutes FROM dailylog_preference WHERE utilisateur_id=${RIM}`) === '480');
  await p.click('#dl-liste .dl-row[data-cle="1:0"] .dl-pinfo');
  etape('nom du projet : ligne désactivée (0 h)', (await valeur(p, '1:0')) === '0 h');
  etape('total à 0 : bouton « Vider la journée »', (await p.textContent('#dl-enregistrer')) === 'Vider la journée');
  await p.click('#dl-enregistrer');   // confirmation acceptée (dialog)
  await attendre(() => heures(RIM, jPrec) === '0', 3000);
  etape('journée vidée après confirmation', heures(RIM, jPrec) === '0' && (await toast(p)).includes('Journée vidée'));
  await p.goto(BASE + '/dailylog?date=' + T); await pret(p);

  // 20. Téléphone 375 px, clair et sombre
  const tel = await contexte(navigateur, 'rim@x.tn', { largeur: 375, hauteur: 812, tactile: true });
  const m = await ouvrir(tel, '/dailylog?date=' + T);
  const mesure = await m.evaluate(() => {
    const row = document.querySelector('#dl-liste .dl-row'), info = row.querySelector('.dl-pinfo').getBoundingClientRect();
    const st = row.querySelector('.dl-stepper').getBoundingClientRect(), step = row.querySelector('.dl-step').getBoundingClientRect();
    return { deborde: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
             dessous: st.top >= info.bottom - 1, cible: Math.min(step.height, step.width),
             nav: document.getElementById('dl-prec').getBoundingClientRect().height };
  });
  etape('375 px : pas de défilement horizontal', !mesure.deborde);
  etape('375 px : stepper sous le nom, cibles ≥ 40 px', mesure.dessous && mesure.cible >= 40 && mesure.nav >= 40, mesure);
  etape('375 px clair : contrastes', (await contrastes(m)).length === 0, await contrastes(m));
  await capture(m, 'dailylog-375-clair.png');
  await theme(m, 'dark');
  etape('375 px sombre : contrastes', (await contrastes(m)).length === 0, await contrastes(m));
  await capture(m, 'dailylog-375-sombre.png');
  await m.click('#dl-date');
  await capture(m, 'dailylog-375-sombre-calendrier.png');
  await tel.close();

  await theme(p, 'light');
  etape('1280 px clair : contrastes', (await contrastes(p)).length === 0, await contrastes(p));
  await capture(p, 'dailylog-1280-clair.png');
  await theme(p, 'dark');
  etape('1280 px sombre : contrastes', (await contrastes(p)).length === 0, await contrastes(p));
  await capture(p, 'dailylog-1280-sombre.png');
  await p.click('#dl-ajouter');
  await capture(p, 'dailylog-1280-sombre-catalogue.png');

  // 21. Correction par le chef au-delà de 14 jours
  const ali = await contexte(navigateur, 'ali@x.tn');
  const c = await ouvrir(ali, `/dailylog?utilisateur=${RIM}&date=${j20}`);
  etape('correction : bandeau et sélection de l\'employé', (await c.textContent('#dl-correction')).includes('Rim Inter') && await c.isVisible('#dl-qui-select'));
  etape('ligne d\'un projet invisible pour le chef : masquée', (await c.textContent('#dl-liste')).includes('Projet non visible') &&
    !(await c.textContent('#dl-liste')).includes('Passerelle'));
  await moins(c, '1:0', 2);
  await c.click('#dl-enregistrer');
  await attendre(async () => (await statut(c)) === 'Enregistré');
  etape('correction enregistrée, ligne masquée gardée', sql(`SELECT string_agg(projet_id || ':' || heures, ',' ORDER BY projet_id) FROM dailylog_entree WHERE utilisateur_id=${RIM} AND date='${j20}'`) === '1:3.00,5:4.00');
  etape('tracée au nom du chef (updated_by, audit_log)', sql(`SELECT updated_by FROM dailylog_entree WHERE utilisateur_id=${RIM} AND date='${j20}' AND projet_id=1`) === String(ALI) &&
    sql(`SELECT count(*) FROM audit_log WHERE table_cible='dailylog_entree' AND utilisateur_id=${ALI} AND ligne_id = (SELECT id FROM dailylog_entree WHERE utilisateur_id=${RIM} AND date='${j20}' AND projet_id=1)`) === '1');
  etape('la personne est prévenue', sql(`SELECT count(*) FROM notification WHERE utilisateur_id=${RIM} AND message LIKE 'Daily log du %corrigé par Ali Chef.'`) === '1');
  await capture(c, 'dailylog-1280-clair-correction.png');
  await ali.close();

  etape('aucune erreur JavaScript', erreursJs.length === 0, erreursJs);
  await navigateur.close();
  console.log(`\n${ok} étapes OK, ${ko} KO`);
  process.exit(ko ? 1 : 0);
})().catch((err) => { console.error(err); process.exit(2); });

/* Scénario Playwright de bout en bout de la fiche projet (lot 11).
 *
 * Lancement : KAIROS_E2E_SCENARIO=projet bash tests_e2e/lancer.sh [dossier_captures]
 * (base jetable + jeu de données tests_e2e/seed_projet.py + serveur Flask).
 * Variables : KAIROS_E2E_URL, KAIROS_E2E_DB (base PostgreSQL, lue avec psql),
 * KAIROS_E2E_CAPTURES (facultatif), PLAYWRIGHT_MODULE (chemin du module).
 *
 * Vérifie l'écran ET la base : une seule fenêtre de tâche chargée à la
 * demande (chargement, focus, Échap, retour du focus, erreur réseau,
 * session expirée), tâches closes repliées, une tabulation par ligne,
 * « Rejoindre » absent des tâches closes, sélecteur d'intervenant (clic,
 * recherche sans accents, ↑/↓/Entrée/Échap, combobox ARIA, ajout sans
 * rechargement, co-chef), gzip et cache des statiques, téléphone 375 px
 * en thème sombre, aucune erreur JavaScript.
 */
'use strict';
const { execFileSync } = require('child_process');
const path = require('path');
let playwright;
try { playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright'); }
catch (e) { playwright = require('/home/claude/.npm-global/lib/node_modules/playwright'); }
const { chromium } = playwright;

const BASE = process.env.KAIROS_E2E_URL || 'http://127.0.0.1:8798';
const DB = process.env.KAIROS_E2E_DB || 'kairos_e2e_projet';
const CAPTURES = process.env.KAIROS_E2E_CAPTURES || '';
const MDP = 'Kairos2026!';
const FICHE = '/projets/1';

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
  // Les 500 et la « session expirée » simulées par le scénario sont attendues.
  p.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|net::/.test(m.text())) erreursJs.push(m.text()); });
  await p.goto(BASE + chemin);
  return p;
}
async function capture(p, nom) { if (CAPTURES) await p.screenshot({ path: path.join(CAPTURES, nom), fullPage: false }); }
const actif = (p) => p.evaluate(() => {
  const a = document.activeElement;
  return { tag: a.tagName, id: a.id, cls: a.className, texte: (a.textContent || a.value || '').trim().slice(0, 60) };
});
const debordement = (p) => p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
const options = (p) => p.$$eval('#carte-intervenants [role=option] .search-combobox-nom', (els) => els.map((e) => e.textContent.trim()));

(async () => {
  const navigateur = await chromium.launch();
  try {
    // --- 1. Fiche : une seule fenêtre, tâches closes repliées ------------
    const ali = await contexte(navigateur, 'ali@x.tn');
    let p = await ouvrir(ali, FICHE);
    etape('une seule <dialog> de tâche dans la page', await p.locator('dialog.tache-dialog').count() === 1);
    etape('fenêtre vide tant qu’on ne l’ouvre pas', (await p.locator('#dialog-tache [data-tache-corps]').innerHTML()).trim() === '');
    etape('7 tâches ouvertes visibles', await p.locator('[aria-label="Tâches du projet"] [data-open-tache]').count() === 7);
    const bascule = p.locator('.taches-closes-bascule');
    etape('« Afficher les 5 tâches closes »', (await bascule.innerText()).trim() === 'Afficher les 5 tâches closes');
    etape('tâches closes masquées', !(await p.locator('[data-open-tache="8"]').isVisible()));
    etape('« Rejoindre » absent des tâches closes', await p.locator('.taches-closes .task-join-btn').count() === 0);
    etape('« Rejoindre » sur les tâches ouvertes hors tabulation',
      await p.locator('[aria-label="Tâches du projet"] .task-join-btn[tabindex="-1"]').count() === 7);
    const gz = await p.evaluate(async () => (await fetch(location.href)).headers.get('content-encoding'));
    etape('page compressée en gzip', gz === 'gzip', gz);
    const css = await p.evaluate(async () => {
      const href = document.querySelector('link[href*="app.css"]').getAttribute('href');
      const r = await fetch(href);
      return { href, cc: r.headers.get('cache-control') };
    });
    etape('app.css versionné et en cache immuable', /\?v=[0-9a-f]{12}$/.test(css.href) && /immutable/.test(css.cc), css);
    await capture(p, 'e2e-projet-fiche.png');

    // --- 2. Clavier : une tabulation par ligne, ouverture, Échap ---------
    await p.focus('[data-open-tache="1"] [data-ouvrir-tache]');
    await p.keyboard.press('Tab');
    let a = await actif(p);
    etape('Tab passe directement au titre de la tâche suivante', a.cls.includes('taskrow-titre') && a.texte === 'Plans de ferraillage', a);
    let requetes = 0;
    p.on('request', (r) => { if (/\/taches\/\d+\/fenetre$/.test(r.url())) requetes++; });
    await p.keyboard.press('Enter');
    await p.waitForSelector('#dialog-tache [data-tache-fenetre="2"]');
    etape('une requête de fragment à l’ouverture', requetes === 1, requetes);
    etape('fenêtre modale nommée par la tâche', await p.evaluate(() => {
      const d = document.getElementById('dialog-tache');
      return d.open && d.matches(':modal') && d.getAttribute('aria-label') === 'Tâche « Plans de ferraillage »';
    }));
    a = await actif(p);
    etape('focus sur le premier champ (titre)', a.id === 'tache-titre-2', a);
    etape('« Rejoindre cette tâche » proposé dans la fenêtre', await p.locator('#dialog-tache button:has-text("Rejoindre cette tâche")').count() === 1);
    await capture(p, 'e2e-projet-fenetre.png');
    await p.keyboard.press('Escape');
    await pause(150);
    a = await actif(p);
    etape('Échap ferme, focus rendu au titre de la tâche',
      !(await p.evaluate(() => document.getElementById('dialog-tache').open)) && a.texte === 'Plans de ferraillage', a);

    // --- 3. Souris : clic sur la ligne, bouton Fermer --------------------
    await p.click('[data-open-tache="3"] .taskrow-date');
    await p.waitForSelector('#dialog-tache [data-tache-fenetre="3"]');
    etape('clic sur la ligne ouvre la bonne tâche', true);
    await p.click('#dialog-tache [data-close-tache]');
    await pause(150);
    a = await actif(p);
    etape('Fermer rend le focus au titre', a.texte === 'Descente de charges', a);

    // --- 4. Erreurs : serveur, puis session expirée ----------------------
    await p.route(/\/taches\/4\/fenetre$/, (r) => r.fulfill({ status: 500, body: 'erreur' }));
    await p.click('[data-open-tache="4"] [data-ouvrir-tache]');
    await p.waitForSelector('#dialog-tache .tache-dialog-erreur');
    a = await actif(p);
    etape('erreur annoncée (role=alert), focus sur « Réessayer »',
      await p.locator('#dialog-tache [role=alert]').count() === 1 && a.texte === 'Réessayer', a);
    await p.unroute(/\/taches\/4\/fenetre$/);
    await p.click('#dialog-tache button:has-text("Réessayer")');
    await p.waitForSelector('#dialog-tache [data-tache-fenetre="4"]');
    etape('« Réessayer » charge la tâche', true);
    await p.keyboard.press('Escape');
    await p.route(/\/taches\/5\/fenetre$/, (r) => r.fulfill({ status: 200, contentType: 'text/html', body: '<html><body>Connexion</body></html>' }));
    await p.click('[data-open-tache="5"] [data-ouvrir-tache]');
    await p.waitForSelector('#dialog-tache .tache-dialog-erreur');
    etape('session expirée : « Recharger la page »',
      (await p.locator('#dialog-tache .tache-dialog-erreur').innerText()).includes('session a expiré'));
    await p.keyboard.press('Escape');
    await p.unroute(/\/taches\/5\/fenetre$/);
    // Chargement lent : état « Chargement… » visible, réponse ignorée si fermée.
    await p.route(/\/taches\/6\/fenetre$/, async (r) => { await pause(600); await r.continue(); });
    await p.click('[data-open-tache="6"] [data-ouvrir-tache]');
    etape('état « Chargement de la tâche… »', (await p.locator('#dialog-tache .tache-dialog-chargement').innerText()).includes('Chargement de la tâche'));
    await p.keyboard.press('Escape');
    await pause(800);
    etape('réponse tardive ignorée après fermeture', (await p.locator('#dialog-tache [data-tache-corps]').innerHTML()).trim() === '');
    await p.unroute(/\/taches\/6\/fenetre$/);

    // --- 5. Tâche close : dépliée, fenêtre sans « Rejoindre » ------------
    await bascule.click();
    etape('tâches closes dépliées', await p.locator('[data-open-tache="8"]').isVisible()
      && (await bascule.innerText()).trim() === 'Masquer les tâches closes');
    await p.click('[data-open-tache="10"] [data-ouvrir-tache]');
    await p.waitForSelector('#dialog-tache [data-tache-fenetre="10"]');
    etape('tâche arrêtée : pas de « Rejoindre »', await p.locator('#dialog-tache :text("Rejoindre")').count() === 0);
    await p.keyboard.press('Escape');

    // --- 6. Sélecteur d'intervenant --------------------------------------
    await p.evaluate(() => { window.__sansRechargement = 1; });
    const champ = p.locator('#carte-intervenants .search-combobox-input');
    etape('un seul champ « + Ajouter un intervenant… » (plus de liste ni de bouton)',
      await champ.getAttribute('placeholder') === '+ Ajouter un intervenant…'
      && await p.locator('#carte-intervenants summary').count() === 0
      && !(await p.locator('#ajout-intervenant-choix').isVisible()));
    etape('combobox ARIA nommée', await champ.getAttribute('role') === 'combobox'
      && await p.evaluate(() => document.querySelector('#carte-intervenants .search-combobox-input').getAttribute('aria-labelledby')
        && document.getElementById(document.querySelector('#carte-intervenants .search-combobox-input').getAttribute('aria-labelledby')).textContent.trim() === 'Ajouter un intervenant'));
    await champ.click();
    let noms = await options(p);
    etape('clic : la liste s’affiche', await champ.getAttribute('aria-expanded') === 'true' && noms.length > 0, noms);
    etape('ni membres, ni RH, ni client, ni compte désactivé',
      JSON.stringify(noms.slice().sort()) === JSON.stringify(['Hélène Bénard', 'Omar Mahjoub', 'Sami Chérif', 'Fadhel Admin'].sort()), noms);
    etape('avatar et rôle affichés', await p.locator('#carte-intervenants [role=option]:has-text("Hélène") .search-combobox-avatar').count() === 1
      && (await p.locator('#carte-intervenants [role=option]:has-text("Hélène") .search-combobox-sous').innerText()) === 'Intervenant · Dessinatrice');
    await champ.fill('helene');
    noms = await options(p);
    etape('« helene » (sans accent) trouve « Hélène Bénard »', noms.length === 1 && noms[0] === 'Hélène Bénard', noms);
    await champ.fill('cherif sami');
    noms = await options(p);
    etape('mots dans le désordre : « cherif sami »', noms.length === 1 && noms[0] === 'Sami Chérif', noms);
    await champ.fill('zzz');
    etape('« Aucune personne trouvée »', (await p.locator('#carte-intervenants .search-combobox-empty').innerText()) === 'Aucune personne trouvée');
    await champ.press('Escape');
    etape('Échap referme la liste, focus gardé', await champ.getAttribute('aria-expanded') === 'false'
      && (await actif(p)).cls.includes('search-combobox-input'));
    await champ.fill('h');
    await champ.press('ArrowDown');
    const ad = await champ.getAttribute('aria-activedescendant');
    etape('↓ : option active annoncée (aria-activedescendant)', !!ad && await p.locator('#' + ad).getAttribute('aria-selected') === 'true', ad);
    await champ.fill('helene');
    await champ.press('Enter');
    await p.waitForFunction(() => /ajouté/.test((document.querySelector('#carte-intervenants .ajout-intervenant-statut') || {}).textContent || ''));
    etape('Entrée : Hélène ajoutée en base', sql('SELECT count(*) FROM projet_intervenant WHERE projet_id=1 AND utilisateur_id=4') === '1');
    etape('liste des intervenants mise à jour sans rechargement',
      await p.evaluate(() => window.__sansRechargement === 1)
      && (await p.locator('#carte-intervenants .nom-personne').allInnerTexts()).includes('Hélène Bénard'));
    etape('message « Intervenant ajouté. » annoncé (role=status)',
      (await p.locator('#carte-intervenants [data-ajout-statut]').innerText()) === 'Intervenant ajouté.'
      && await p.locator('#carte-intervenants [data-ajout-statut]').getAttribute('role') === 'status');
    a = await actif(p);
    etape('focus rendu au champ, liste fermée', a.cls.includes('search-combobox-input')
      && await p.locator('#carte-intervenants .search-combobox-input').getAttribute('aria-expanded') === 'false', a);
    await capture(p, 'e2e-projet-intervenant-ajoute.png');
    await p.keyboard.press('ArrowDown');
    noms = await options(p);
    etape('Hélène n’est plus proposée', !noms.includes('Hélène Bénard') && noms.length === 3, noms);
    // Souris : un chef de projet ajouté devient co-chef.
    await p.locator('#carte-intervenants [role=option]:has-text("Sami Chérif")').click();
    await p.waitForFunction(() => /co-chef/.test((document.querySelector('#carte-intervenants .ajout-intervenant-statut') || {}).textContent || ''));
    etape('clic : Sami ajouté comme co-chef', sql('SELECT count(*) FROM projet_co_chef WHERE projet_id=1 AND utilisateur_id=5') === '1');
    etape('toujours sans rechargement', await p.evaluate(() => window.__sansRechargement === 1));
    etape('aucun message flash en attente au rechargement suivant', await (async () => {
      await p.reload();
      await pause(400);
      return await p.locator('.flash').count() === 0;
    })());

    // --- 7. Rejoindre une tâche (survol) ---------------------------------
    const rim = await contexte(navigateur, 'rim@x.tn');
    const pr = await ouvrir(rim, FICHE);
    await pr.hover('[data-open-tache="2"]');
    await Promise.all([pr.waitForNavigation(), pr.click('[data-open-tache="2"] .task-join-btn')]);
    etape('« Rejoindre » au survol : Rim intervenante de la tâche 2',
      sql('SELECT count(*) FROM tache_intervenant WHERE tache_id=2 AND utilisateur_id=3') === '1');
    etape('le sélecteur n’est pas proposé à un simple intervenant', await pr.locator('#ajout-intervenant-choix').count() === 0);
    await rim.close();

    // --- 8. Téléphone 375 px, thème sombre --------------------------------
    const tel = await contexte(navigateur, 'ali@x.tn', { largeur: 375, hauteur: 800, theme: 'dark' });
    const pt = await ouvrir(tel, FICHE);
    etape('375 px sombre : aucun débordement', await debordement(pt) === 0, await debordement(pt));
    await pt.click('[data-open-tache="1"] [data-ouvrir-tache]');
    await pt.waitForSelector('#dialog-tache [data-tache-fenetre="1"]');
    const boite = await pt.locator('#dialog-tache').boundingBox();
    etape('375 px : la fenêtre tient dans l’écran', boite.x >= 0 && boite.x + boite.width <= 375, boite);
    await capture(pt, 'e2e-projet-375-sombre-fenetre.png');
    await pt.keyboard.press('Escape');
    const champTel = pt.locator('#carte-intervenants .search-combobox-input');
    await champTel.scrollIntoViewIfNeeded();
    await champTel.click();
    const liste = await pt.locator('#carte-intervenants .search-combobox-list').boundingBox();
    etape('375 px : la liste tient dans la largeur', liste && liste.x >= 0 && liste.x + liste.width <= 375, liste);
    etape('375 px : toujours aucun débordement', await debordement(pt) === 0);
    const fond = await pt.evaluate(() => getComputedStyle(document.querySelector('#carte-intervenants .search-combobox-list')).backgroundColor);
    etape('thème sombre : liste sur fond sombre', /rgb\((\d+), (\d+), (\d+)\)/.test(fond) && fond.match(/\d+/g).slice(0, 3).every((v) => +v < 80), fond);
    await capture(pt, 'e2e-projet-375-sombre-selecteur.png');
    await tel.close();
    await ali.close();

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

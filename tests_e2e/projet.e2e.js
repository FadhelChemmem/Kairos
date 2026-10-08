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
 *
 * Lot 11 b : résultat « tâche » de la recherche globale et notification
 * d'affectation -> fenêtre de la tâche ouverte (tâche close dépliée, focus,
 * retour du focus, adresse nettoyée, 404 sans droit) ; rappel Daily log
 * (texte, lien vers le jour) ; changement du chef de projet dans la fenêtre
 * Informations (clavier, base, post, notification, projet clos) et lien
 * « Changer le chef » de l'encart Admin ; 1280 / 375 px, clair / sombre.
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

    // --- 9. Lot 11 b : recherche globale -> fenêtre de la tâche ----------
    const rim2 = await contexte(navigateur, 'rim@x.tn');
    let pg = await ouvrir(rim2, '/accueil');
    await pg.fill('#recherche-globale', 'ferraillage');
    await pg.waitForSelector('#recherche-globale-resultats a[href$="/projets/1?tache=2"]');
    etape('recherche : la tâche pointe vers ?tache=<id> (projet invisible exclu)',
      await pg.locator('#recherche-globale-resultats a').count() === 1);
    await pg.keyboard.press('ArrowDown');
    await Promise.all([pg.waitForNavigation(), pg.keyboard.press('Enter')]);
    await pg.waitForSelector('#dialog-tache [data-tache-fenetre="2"]');
    etape('clavier ↓ Entrée : fiche ouverte, fenêtre de la tâche affichée',
      await pg.evaluate(() => document.getElementById('dialog-tache').matches(':modal')));
    etape('focus dans la fenêtre', await pg.evaluate(() => document.getElementById('dialog-tache').contains(document.activeElement)));
    await capture(pg, 'e2e-11b-recherche-tache-1280-clair.png');
    await pg.keyboard.press('Escape');
    await pause(150);
    a = await actif(pg);
    etape('Échap : focus rendu à la ligne de la tâche', a.cls.includes('taskrow-titre') && a.texte === 'Plans de ferraillage', a);
    etape('adresse nettoyée à la fermeture', await pg.evaluate(() => location.search === '' && location.pathname === '/projets/1'));
    await pg.fill('#recherche-globale', 'dossier doe');
    await pg.waitForSelector('#recherche-globale-resultats a[href$="/projets/1?tache=8"]');
    await Promise.all([pg.waitForNavigation(), pg.click('#recherche-globale-resultats a[href$="/projets/1?tache=8"]')]);
    await pg.waitForSelector('#dialog-tache [data-tache-fenetre="8"]');
    etape('tâche close : tâches closes dépliées, fenêtre ouverte',
      await pg.evaluate(() => document.getElementById('taches-closes').open));
    await pg.click('#dialog-tache [data-close-tache]');
    await pause(150);
    a = await actif(pg);
    etape('Fermer : focus sur la ligne de la tâche close', a.texte === 'Dossier DOE', a);
    await pg.goto(BASE + '/projets/1#tache-3');
    await pg.waitForSelector('#dialog-tache [data-tache-fenetre="3"]');
    etape('ancre #tache-3 : fenêtre ouverte', true);
    await pg.keyboard.press('Escape');
    const r404 = await pg.goto(BASE + '/projets/2?tache=13');
    etape('sans droit sur le projet : 404 (comme avant)', r404.status() === 404, r404.status());

    // --- 10. Notification d'affectation -> fenêtre de la tâche -----------
    sql("INSERT INTO notification (utilisateur_id, categorie, message, tache_id) VALUES (3, 'projet', 'Vous avez été affecté à la tâche « Coffrage dalle R+1 ».', 4)");
    pg = await ouvrir(rim2, '/notifications');
    await Promise.all([pg.waitForNavigation(), pg.click('button.notif-item:has-text("Coffrage dalle R+1")')]);
    await pg.waitForSelector('#dialog-tache [data-tache-fenetre="4"]');
    etape('notification d’affectation : fenêtre de la tâche ouverte', pg.url().endsWith('/projets/1?tache=4'), pg.url());

    // --- 11. Rappel Daily log : texte clair, une notification, lien -------
    pg = await ouvrir(rim2, '/notifications');
    const rappels = await pg.locator('button.notif-item:has-text("Daily log")').allInnerTexts();
    etape('rappel Daily log regroupé en une notification au texte clair',
      rappels.length === 1 && /(\d+ jours de Daily log non remplis(, du | : )|Daily log du )/.test(rappels[0]) && !/Rappel DailyLog/.test(rappels[0]), rappels);
    const premierJour = sql("SELECT rappel_jours[1] FROM notification WHERE utilisateur_id = 3 AND rappel_jours IS NOT NULL");
    await Promise.all([pg.waitForNavigation(), pg.click('button.notif-item:has-text("Daily log")')]);
    etape('lien du rappel : /dailylog?date=AAAA-MM-JJ du premier jour', pg.url().endsWith('/dailylog?date=' + premierJour), [pg.url(), premierJour]);
    await rim2.close();

    // --- 12. Changement de chef (chef titulaire, clavier) ----------------
    const ali2 = await contexte(navigateur, 'ali@x.tn');
    pg = await ouvrir(ali2, FICHE);
    await pg.focus('button.bouton-texte[data-open-informations-dialog]');
    await pg.keyboard.press('Enter');
    await pg.waitForSelector('#dialog-informations-projet[open]');
    const champChef = pg.locator('#dialog-info-chef ~ .search-combobox-wrap .search-combobox-input');
    etape('champ « Chef de projet » : combobox nommée et décrite',
      await champChef.getAttribute('role') === 'combobox'
      && await pg.evaluate(() => {
        const c = document.querySelector('#dialog-info-chef ~ .search-combobox-wrap .search-combobox-input');
        return document.getElementById(c.getAttribute('aria-labelledby')).textContent.trim() === 'Chef de projet'
          && /ancien chef devient co-chef/.test(document.getElementById(c.getAttribute('aria-describedby')).textContent);
      }));
    etape('champ prérempli avec le chef actuel', await champChef.inputValue() === 'Ali Chef');
    await champChef.focus();
    const nomsChefs = await pg.$$eval('#dialog-info-chef ~ .search-combobox-wrap [role=option] .search-combobox-nom', (els) => els.map((e) => e.textContent.trim()));
    etape('candidats : chefs de projet et Admin actifs seulement',
      JSON.stringify(nomsChefs.slice().sort()) === JSON.stringify(['Ali Chef', 'Fadhel Admin', 'Sami Chérif'].sort()), nomsChefs);
    etape('avatar et sous-titre dans la liste', await pg.locator('#dialog-info-chef ~ .search-combobox-wrap [role=option]:has-text("Sami") .search-combobox-avatar').count() === 1
      && (await pg.locator('#dialog-info-chef ~ .search-combobox-wrap [role=option]:has-text("Ali") .search-combobox-sous').innerText()).startsWith('Chef actuel'));
    await champChef.fill('cherif');
    await capture(pg, 'e2e-11b-chef-liste-1280-clair.png');
    await champChef.press('Enter');
    etape('Entrée : Sami Chérif choisi', await champChef.inputValue() === 'Sami Chérif'
      && await pg.evaluate(() => document.getElementById('dialog-info-chef').value) === '5');
    await pg.focus('#dialog-informations-projet button[type=submit]');
    await Promise.all([pg.waitForNavigation(), pg.keyboard.press('Enter')]);
    await pg.waitForSelector('#flash-wrap .flash');
    etape('message : projet confié, l’ancien chef devient co-chef',
      (await pg.locator('#flash-wrap .flash').allInnerTexts()).join(' ').includes('projet confié à Sami Chérif (Ali Chef devient co-chef)'));
    etape('base : Sami chef, Ali co-chef, Sami ni co-chef ni intervenant',
      sql('SELECT chef_projet_id FROM projet WHERE id=1') === '5'
      && sql('SELECT string_agg(utilisateur_id::text, \',\' ORDER BY utilisateur_id) FROM projet_co_chef WHERE projet_id=1') === '2'
      && sql('SELECT count(*) FROM projet_intervenant WHERE projet_id=1 AND utilisateur_id=5') === '0');
    etape('équipe du projet inchangée', sql('SELECT equipe_code FROM projet WHERE id=1') === 'MIDGARD');
    etape('post « Ali Chef a confié le projet à Sami Chérif » dans le fil',
      (await pg.locator('#fil-posts').innerText()).includes('Ali Chef a confié le projet à Sami Chérif.'));
    etape('notification au nouveau chef, journal d’audit',
      sql("SELECT count(*) FROM notification WHERE utilisateur_id=5 AND message LIKE 'Ali Chef vous a confié le projet « 21114X_Siemens »%' AND post_id IS NOT NULL") === '1'
      && sql("SELECT count(*) FROM audit_log WHERE table_cible='projet' AND ligne_id=1 AND utilisateur_id=2 AND donnees_avant->>'chef_projet_id'='2' AND donnees_apres->>'chef_projet_id'='5'") === '1');
    etape('en-tête et carte Intervenants à jour', (await pg.locator('.lien-personne .nom-personne').first().innerText()) === 'Sami Chérif'
      && (await pg.locator('#carte-intervenants').innerText()).includes('Co-chef'));
    await capture(pg, 'e2e-11b-chef-change-1280-clair.png');

    // --- 13. Projet clos : rouvrir d'abord (non-Admin) -------------------
    sql("UPDATE projet SET etat='termine' WHERE id=1");
    await pg.reload();
    await pg.click('button.bouton-texte[data-open-informations-dialog]');
    etape('projet clos : chef en lecture seule pour un co-chef',
      await pg.locator('#dialog-info-chef').count() === 0
      && (await pg.locator('#dialog-informations-projet').innerText()).includes('Projet clos : rouvrez-le d’abord'.replace('’', "'")));
    await pg.keyboard.press('Escape');
    sql("UPDATE projet SET etat='en_cours' WHERE id=1");
    await ali2.close();

    // --- 14. Encart Admin -> fenêtre Informations, champ prêt (375 sombre)
    sql('UPDATE utilisateur SET actif=false WHERE id=5');
    const adm = await contexte(navigateur, 'admin@x.tn', { largeur: 375, hauteur: 800, theme: 'dark' });
    pg = await ouvrir(adm, '/utilisateurs');
    etape('encart Admin : lien « Changer le chef »', await pg.locator('a.lien-changer-chef[href="/projets/1?informations=chef"]').count() === 1);
    await Promise.all([pg.waitForNavigation(), pg.click('a.lien-changer-chef')]);
    await pg.waitForSelector('#dialog-informations-projet[open]');
    await pause(150);
    a = await actif(pg);
    etape('fenêtre Informations ouverte, focus dans le champ chef, liste ouverte',
      a.cls.includes('search-combobox-input') && await pg.locator('#dialog-info-chef ~ .search-combobox-wrap .search-combobox-input').getAttribute('aria-expanded') === 'true', a);
    etape('adresse nettoyée (?informations retiré)', await pg.evaluate(() => location.search === ''));
    etape('chef désactivé affiché, signalé et sélectionné (la frappe le remplace)',
      (await pg.locator('#dialog-info-chef ~ .search-combobox-wrap .search-combobox-input').inputValue()) === 'Sami Chérif (désactivé)'
      && await pg.evaluate(() => { const c = document.activeElement; return c.selectionStart === 0 && c.selectionEnd === c.value.length; }));
    etape('375 px sombre : aucun débordement, fenêtre dans l’écran', await debordement(pg) === 0
      && await pg.evaluate(() => { const r = document.getElementById('dialog-informations-projet').getBoundingClientRect(); return r.left >= 0 && r.right <= 375; }));
    const listeChef = await pg.locator('#dialog-info-chef ~ .search-combobox-wrap .search-combobox-list').boundingBox();
    etape('375 px : la liste des chefs tient dans la largeur', listeChef && listeChef.x >= 0 && listeChef.x + listeChef.width <= 375, listeChef);
    await capture(pg, 'e2e-11b-encart-chef-375-sombre.png');
    await pg.keyboard.type('ali');
    await pg.keyboard.press('Enter');
    await Promise.all([pg.waitForNavigation(), pg.click('#dialog-informations-projet button[type=submit]')]);
    etape('Admin : projet du chef désactivé confié à Ali, Sami devient co-chef',
      sql('SELECT chef_projet_id FROM projet WHERE id=1') === '2'
      && sql('SELECT count(*) FROM projet_co_chef WHERE projet_id=1 AND utilisateur_id=5') === '1'
      && sql('SELECT count(*) FROM projet_co_chef WHERE projet_id=1 AND utilisateur_id=2') === '0');
    pg = await ouvrir(adm, '/utilisateurs');
    etape('encart vidé', await pg.locator('a.lien-changer-chef').count() === 0);
    await adm.close();

    // --- 15. 1280 / 375 px, clair / sombre : fenêtres de tâche et Informations
    for (const [largeur, theme] of [[1280, 'light'], [1280, 'dark'], [375, 'light'], [375, 'dark']]) {
      const ctx = await contexte(navigateur, 'ali@x.tn', { largeur, hauteur: 860, theme });
      const pv = await ouvrir(ctx, '/projets/1?tache=9');
      await pv.waitForSelector('#dialog-tache [data-tache-fenetre="9"]');
      const bt = await pv.locator('#dialog-tache').boundingBox();
      etape(`${largeur} px ${theme} : tâche close ouverte par ?tache, dans l’écran`, bt.x >= 0 && bt.x + bt.width <= largeur
        && await debordement(pv) === 0, bt);
      await capture(pv, `e2e-11b-tache-${largeur}-${theme}.png`);
      await pv.keyboard.press('Escape');
      await pv.click('button.bouton-texte[data-open-informations-dialog]');
      await pv.locator('#dialog-info-chef ~ .search-combobox-wrap .search-combobox-input').focus();
      const bi = await pv.locator('#dialog-informations-projet').boundingBox();
      const bl = await pv.locator('#dialog-info-chef ~ .search-combobox-wrap .search-combobox-list').boundingBox();
      etape(`${largeur} px ${theme} : Informations et liste des chefs dans l’écran`,
        bi.x >= 0 && bi.x + bi.width <= largeur && bl && bl.x + bl.width <= largeur && await debordement(pv) === 0, [bi, bl]);
      if (theme === 'dark') {
        const fondListe = await pv.evaluate(() => getComputedStyle(document.querySelector('#dialog-info-chef ~ .search-combobox-wrap .search-combobox-list')).backgroundColor);
        etape(`${largeur} px sombre : liste des chefs sur fond sombre`, fondListe.match(/\d+/g).slice(0, 3).every((v) => +v < 80), fondListe);
      }
      await capture(pv, `e2e-11b-informations-${largeur}-${theme}.png`);
      await ctx.close();
    }

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

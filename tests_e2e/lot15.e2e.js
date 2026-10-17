/* Scénario Playwright « lot15 » (sobriété, maquettes validées le 16/10/2026) :
 * - accueil en deux colonnes : fil, colonne de droite ; un seul « + Nouveau
 *   post » ; « À traiter » du chef en bas à droite ; Deadlines repliées par
 *   défaut, dépliées gardées pour le compte (après rechargement) ;
 * - post : menu ⋯, modifier sur place (partiel), supprimer avec
 *   confirmation, « Annuler » par Ctrl+Z ; pièce jointe retirée puis
 *   rétablie ; menu absent sur le post d'un autre (intervenant) ;
 * - Requête : tâche concernée choisie dans la fenêtre, puis citée dans le
 *   fil ;
 * - fiche projet : plus de « + Tâche » ; panneau d'une tâche ouvert, les
 *   tâches et le fil gardent leur bord gauche (aucune réorganisation) ;
 * - Daily log : bande de la semaine (jour cliqué ouvert), tableau Tâche |
 *   Projet | Heures, colonne de droite ;
 * - page d'une personne : tâches et projets en cours ; poste en lecture
 *   seule dans « Mes informations » ;
 * - recherche : Entrée ouvre le premier résultat ;
 * - 1440 et 375 px, clair et sombre : aucun débordement horizontal ; aucune
 *   erreur JavaScript ni boîte native.
 *
 * Lancement : KAIROS_E2E_SCENARIO=lot15 bash tests_e2e/lancer.sh [dossier_captures]
 * (base jetable + tests_e2e/seed_lot15.py).
 */
'use strict';
const { execFileSync } = require('child_process');
const path = require('path');
let playwright;
try { playwright = require(process.env.PLAYWRIGHT_MODULE || 'playwright'); }
catch (e) { playwright = require('/opt/node-tools/node_modules/playwright'); }
const { chromium } = playwright;

const BASE = process.env.KAIROS_E2E_URL || 'http://127.0.0.1:8798';
const DB = process.env.KAIROS_E2E_DB || 'kairos_e2e_lot15';
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
  p.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) erreursJs.push(chemin + ' : ' + m.text()); });
  p.on('dialog', (d) => { erreursJs.push('boîte native : ' + d.message()); d.dismiss(); });
  p.on('request', (r) => { if (r.isNavigationRequest() && r.frame() === p.mainFrame()) p.docs++; });
  await p.goto(BASE + chemin);
  await p.waitForLoadState('networkidle');
  p.docs = 0;
  return p;
}
async function capture(p, nom, pleine = false) {
  if (CAPTURES) await p.screenshot({ path: path.join(CAPTURES, nom), fullPage: pleine });
}
const toasts = (p) => p.$$eval('.k-toast', (l) => l.map((x) => x.textContent.trim()));
const deborde = (p) => p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);

(async () => {
  const navigateur = await chromium.launch();
  try {
    // --- 1. Accueil du chef : deux colonnes, un seul « + Nouveau post » ---
    const ali = await contexte(navigateur, 'ali@x.tn');
    let p = await ouvrir(ali, '/accueil');
    const geo = await p.evaluate(() => {
      const r = (s) => { const e = document.querySelector(s); return e ? e.getBoundingClientRect() : null; };
      return { fil: r('.acc-fil'), cote: r('.acc-cote'), at: r('#a-traiter'), projets: r('#acc-projets-titre'),
               nouveaux: Array.from(document.querySelectorAll('button')).filter((b) => /Nouveau post/.test(b.textContent)).length };
    });
    etape('accueil : fil à gauche, colonne à droite', geo.fil && geo.cote && geo.fil.right <= geo.cote.left && Math.abs(geo.fil.top - geo.cote.top) < 60, geo);
    etape('accueil : « À traiter » sous « Mes projets », dans la colonne de droite', geo.at && geo.at.left >= geo.cote.left && geo.at.top > geo.projets.top);
    etape('accueil : un seul « + Nouveau post »', geo.nouveaux === 1, geo.nouveaux);
    etape('Deadlines repliées par défaut', !(await p.evaluate(() => document.getElementById('acc-deadlines').open)));
    await capture(p, 'lot15-accueil-chef-1440.png', true);
    await p.click('#acc-deadlines summary');
    await attendre(() => sql("SELECT accueil_deadlines FROM utilisateur_preference WHERE utilisateur_id = 2") === 't');
    etape('Deadlines dépliées : réglage gardé pour le compte', sql("SELECT accueil_deadlines FROM utilisateur_preference WHERE utilisateur_id = 2") === 't');
    await p.reload(); await p.waitForLoadState('networkidle');
    etape('après rechargement : Deadlines toujours dépliées', await p.evaluate(() => document.getElementById('acc-deadlines').open)
      && await p.locator('#acc-deadlines .mini-gantt').isVisible());
    await p.click('#acc-deadlines summary');
    await attendre(() => sql("SELECT accueil_deadlines FROM utilisateur_preference WHERE utilisateur_id = 2") === 'f');

    // Lot 17 (gérant, 17/10) : bascule « Les miennes | Toutes » retirée,
    // toutes les tâches des projets du chef.
    etape('« Tâches de mes projets » : plus de bascule « Les miennes | Toutes »',
      await p.locator('[data-tdp-bascule], #tdp-miennes').count() === 0
      && await p.evaluate(() => document.getElementById('accueil-taches').dataset.mode) === 'toutes');

    // Lot 17 : « + Nouveau post » — projet entièrement sélectionné au clic,
    // sélection glissée hors de la fenêtre sans la fermer, capture jointe.
    await p.click('#nouveau-post');
    await p.waitForSelector('#dialog-nouveau-post[open]');
    await p.click('label[for="intent-information"]');
    const champProjet = '[data-post-dialog-projet-row] .search-combobox-input';
    await p.click(champProjet); await pause(150);
    const sel = await p.evaluate((s) => { const i = document.querySelector(s); return [i.selectionStart, i.selectionEnd, i.value.length]; }, champProjet);
    etape('« + Nouveau post » : nom du projet entièrement sélectionné au clic, bouton ×',
      sel[0] === 0 && sel[1] === sel[2] && sel[2] > 0 && await p.locator('[data-post-dialog-projet-row] .search-combobox-effacer').count() === 1, sel);
    await p.keyboard.press('Escape');
    await p.fill('#dialog-contenu-information', 'Texte à sélectionner');
    const zone = await p.locator('#dialog-contenu-information').boundingBox();
    await p.mouse.move(zone.x + 20, zone.y + 12); await p.mouse.down();
    await p.mouse.move(4, 4, { steps: 6 }); await p.mouse.up(); await pause(300);
    etape('sélection glissée et relâchée hors de la fenêtre : la fenêtre reste ouverte',
      await p.evaluate(() => document.getElementById('dialog-nouveau-post').open));
    await p.setInputFiles('.panel-information [data-pj-choix]', [
      { name: 'image.png', mimeType: 'image/png', buffer: Buffer.from('89504e470d0a1a0a', 'hex') },
      { name: 'note.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4') }]);
    const noms = await p.$$eval('.panel-information .pj-puce .pj-nom', (l) => l.map((x) => x.textContent));
    etape('« Joindre » : deux pièces en puces, capture renommée, envoyées avec le formulaire',
      noms.length === 2 && /^Capture \d{4}-\d\d-\d\d \d\dh\d\d\.png$/.test(noms[0]) && noms[1] === 'note.pdf'
      && await p.evaluate(() => document.querySelector('.panel-information [data-pj-input]').files.length) === 2, noms);
    etape('champ « Lien » masqué', await p.locator('#dialog-lien-information').isVisible() === false);
    await p.reload(); await p.waitForLoadState('networkidle');

    // --- 2. Post : modifier, supprimer, Annuler -------------------------------
    await p.click('#fil-filtre-accueil-tout');
    await attendre(() => p.evaluate(() => !!document.querySelector('#fil-liste[data-fil-categorie="tout"]')));
    await p.locator('#post-402').scrollIntoViewIfNeeded();
    const avantMenu = await p.evaluate(() => document.querySelector('#post-402 .post-actions').getBoundingClientRect().top);
    await p.click('#post-402 .post-menu-bouton');
    const apresMenu = await p.evaluate(() => document.querySelector('#post-402 .post-actions').getBoundingClientRect().top);
    etape('menu ⋯ ouvert sans rien déplacer', Math.abs(avantMenu - apresMenu) < 1, [avantMenu, apresMenu]);
    await p.click('#post-402 [data-post-modifier]');
    etape('« Modifier » : formulaire sur place, focus dans l’objet', await p.isVisible('#post-402-edition')
      && await p.evaluate(() => document.activeElement && document.activeElement.id === 'post-402-objet'));
    await p.fill('#post-402-objet', 'Plans de réservation CVC, indice B');
    p.docs = 0;
    await p.click('#post-402-edition button[type=submit]');
    await attendre(async () => (await p.textContent('#post-402')).includes('indice B'));
    etape('modification enregistrée en partiel (aucune navigation)', p.docs === 0
      && sql("SELECT split_part(contenu, E'\\n', 1) FROM post WHERE id = 402") === 'Plans de réservation CVC, indice B');
    etape('« modifié » affiché, toast « Post modifié. »', (await p.textContent('#post-402 .post-meta')).includes('modifié')
      && (await toasts(p)).some((t) => t.startsWith('Post modifié.')));
    await p.click('#post-403 .post-menu-bouton');
    await p.click('#post-403 .post-menu-item.danger');
    await p.click('.k-confirmation-actions button >> text=Supprimer');
    await attendre(async () => (await p.textContent('#post-403')).includes('Post supprimé.'));
    etape('suppression confirmée : « Post supprimé. » à la place, base mise à jour',
      sql('SELECT supprime_par FROM post WHERE id = 403') === '2');
    await p.keyboard.press('Control+z');
    await attendre(async () => (await p.textContent('#post-403')).includes('Réunion de chantier'));
    etape('Ctrl+Z (« Annuler ») : post rétabli', sql('SELECT supprime_le IS NULL FROM post WHERE id = 403') === 't');
    await capture(p, 'lot15-post-menu.png');
    await p.close();

    // L'intervenante ne voit pas le menu sur le post d'un autre.
    const rim = await contexte(navigateur, 'rim@x.tn');
    p = await ouvrir(rim, '/accueil?fil=tout');
    etape('intervenante : pas de menu sur le post d’Ali', await p.locator('#post-402 .post-menu').count() === 0);
    etape('intervenante : rien à traiter ni Vue d’ensemble', await p.locator('#a-traiter, #vue-ensemble').count() === 0);

    // --- 3. Requête : tâche concernée --------------------------------------
    await p.click('#nouveau-post');
    await p.click('label[for="intent-requete"]');
    await p.evaluate(() => { const s = document.getElementById('dialog-post-projet'); s.value = '3'; s.dispatchEvent(new Event('change')); });
    await attendre(() => p.evaluate(() => !document.querySelector('[data-requete-tache-row]').hidden));
    etape('Requête : tâches ouvertes du projet proposées', await p.locator('#dialog-tache-requete option').count() >= 3);
    await p.fill('#dialog-objet-requete', 'Visa du coffrage ?');
    await p.selectOption('#dialog-tache-requete', '20');
    await p.click('#publier-requete');
    await attendre(() => sql("SELECT tache_id FROM post WHERE contenu = 'Visa du coffrage ?'") === '20');
    etape('Requête publiée avec la tâche citée', sql("SELECT tache_id FROM post WHERE contenu = 'Visa du coffrage ?'") === '20');
    await attendre(() => p.locator('#fil-liste .post-tache-citee').count().then((n) => n >= 1));
    etape('fil : la tâche citée mène à sa fenêtre', await p.locator('#fil-liste a.post-tache-citee[href="/projets/3?tache=20"]').count() >= 1);

    // --- 4. Daily log : bande de la semaine ----------------------------------
    await p.goto(BASE + '/dailylog'); await p.waitForFunction(() => window.KairosDailyLogPage && !window.KairosDailyLogPage.etat().chargement);
    const jours = await p.locator('#dl-bande-jours .dl-jour').count();
    etape('Daily log : cinq jours dans la bande', jours === 5, jours);
    etape('Daily log : en-têtes Tâche · Projet · Heures', (await p.textContent('.dl-thead')).replace(/\s+/g, '') === 'TâcheProjetHeures');
    const cible = await p.evaluate(() => { const b = Array.from(document.querySelectorAll('#dl-bande-jours .dl-jour:not([disabled])')).find((x) => x.getAttribute('aria-pressed') !== 'true'); return b && b.dataset.jour; });
    await p.click(`#dl-bande-jours [data-jour="${cible}"]`);
    await p.waitForFunction((k) => window.KairosDailyLogPage.etat().sel === k && !window.KairosDailyLogPage.etat().chargement, cible);
    etape('clic sur un jour de la bande : jour ouvert', (await p.evaluate(() => window.KairosDailyLogPage.etat().sel)) === cible);
    etape('Daily log : colonne de droite (journée, enregistrer, copier)', await p.locator('.dl-cote #dl-enregistrer, .dl-cote #dl-copier').count() === 2);
    await capture(p, 'lot15-dailylog-1440.png', true);

    // --- 5. Poste en lecture seule -----------------------------------------
    await p.goto(BASE + '/utilisateurs/moi');
    etape('Mes informations : poste lu, pas de champ', await p.locator('input[name="poste"]').count() === 0
      && (await p.textContent('#mes-infos')).includes('Technicienne supérieure'));
    await p.close();

    // --- 6. Fiche projet : un seul bouton, panneau sans réorganisation -------
    p = await ouvrir(ali, '/projets/3');
    etape('fiche : plus de « + Tâche »', await p.locator('#nouvelle-tache').count() === 0 && await p.locator('#nouveau-post').count() === 1);
    const avant = await p.evaluate(() => ({ t: document.getElementById('carte-taches').getBoundingClientRect().left,
                                            f: document.getElementById('posts-projet').getBoundingClientRect().left }));
    await p.click('#taches-ouvertes .taskrow >> nth=0');
    await p.waitForSelector('#dialog-tache [data-tache-fenetre]');
    await pause(500);
    const apres = await p.evaluate(() => ({ t: document.getElementById('carte-taches').getBoundingClientRect().left,
                                            f: document.getElementById('posts-projet').getBoundingClientRect().left,
                                            cote: getComputedStyle(document.querySelector('.fiche-cote')).display }));
    etape('panneau ouvert : tâches et fil gardent leur bord gauche', Math.abs(avant.t - apres.t) < 1 && Math.abs(avant.f - apres.f) < 1, [avant, apres]);
    etape('panneau ouvert : colonne de droite effacée (pas sous le fil)', apres.cote === 'none', apres);
    await capture(p, 'lot15-fiche-panneau.png');
    await p.close();

    // --- 7. Page d'une personne ------------------------------------------------
    p = await ouvrir(ali, '/utilisateurs/3/profil');
    etape('page de Rim : tâches en cours (retards d’abord)', (await p.locator('#personne-taches-titre').count()) === 1
      && (await p.locator('.acc-tache').first().textContent()).includes('Coffrage (pour validation)'));
    etape('page de Rim : projets en cours', await p.locator('.page-personne .acc-projet').count() >= 4);
    etape('fiche du chef : renvoie à la page de la personne', (await (await p.request.get(BASE + '/utilisateurs/3', { maxRedirects: 0 })).status()) === 302);
    await p.close();

    // --- 8. Recherche : Entrée -------------------------------------------------
    p = await ouvrir(ali, '/accueil');
    await p.fill('#recherche-globale', 'Horizon');
    await p.keyboard.press('Enter');
    await attendre(() => /\/projets\/8/.test(p.url()));
    etape('recherche : Entrée ouvre le premier résultat', /\/projets\/8/.test(p.url()), p.url());
    await p.close();

    // --- 9. Largeurs et thèmes -------------------------------------------------
    for (const [largeur, theme] of [[1440, 'dark'], [375, 'light'], [375, 'dark']]) {
      const ctx = await contexte(navigateur, 'ali@x.tn', { largeur, hauteur: largeur < 500 ? 812 : 900, theme });
      const fautes = [];
      for (const chemin of ['/accueil', '/dailylog', '/projets/3', '/utilisateurs/3/profil']) {
        const q = await ouvrir(ctx, chemin);
        if (await deborde(q)) fautes.push(chemin);
        if (chemin === '/accueil') await capture(q, `lot15-accueil-${largeur}-${theme}.png`, true);
        await q.close();
      }
      etape(`${largeur} px ${theme} : aucun débordement horizontal`, fautes.length === 0, fautes);
      await ctx.close();
    }

    etape('aucune erreur JavaScript ni boîte native', erreursJs.length === 0, erreursJs);
  } catch (e) {
    etape('exception : ' + e.message.split('\n')[0], false, e.stack && e.stack.split('\n').slice(0, 3));
  } finally {
    await navigateur.close();
    console.log(`\n${ok} OK, ${ko} KO`);
    process.exit(ko ? 1 : 0);
  }
})();

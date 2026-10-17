/* Scénario Playwright du lot 13, phase 2 C : fiche projet (panneau de
 * tâche, Informations, intervenants, « + Tâche »), fil (accueil : commentaire,
 * réponse, modification, suppression, réaction, publication), « Tous les
 * projets » (filtres, pagination, Retour, export), fenêtre « Nouveau
 * projet » (erreur reliée au champ), « Voir comme », mouvement réduit,
 * 375 px. Appelé par partiel.e2e.js (même base, seed_partiel_fiche.py).
 *
 * Pour CHAQUE interaction convertie, critères de l'audit UX §4.8 : aucune
 * navigation de document, |Δy| ≤ 40 px (sauf pagination : haut de la liste
 * à l'écran), focus attendu (jamais <body>), première mutation ≤ 100 ms
 * sous 800 ms de latence, résultat vérifié à l'écran ET en base.
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');

module.exports = async function scenarioFiche(h) {
  const { navigateur, contexte, ouvrir, etape, sql, attendre, pause, latence, instrumenter, etat, capture, BASE } = h;

  /** Compteur de navigations de document par page. */
  function compter(p) {
    const c = { docs: 0 };
    p.on('request', (r) => { if (r.isNavigationRequest() && r.frame() === p.mainFrame()) c.docs++; });
    return c;
  }
  const focusSur = (p, sel) => p.evaluate((s) => !!document.activeElement && document.activeElement !== document.body
    && document.activeElement.matches(s), sel);
  const focusDecrit = (p) => p.evaluate(() => {
    const a = document.activeElement;
    return a === document.body ? 'body' : a.tagName + '#' + a.id + '.' + String(a.className).slice(0, 40);
  });

  /**
   * Une interaction mesurée : `action` sous 800 ms de latence, puis attente
   * de `fini` ; critères §4.8 vérifiés (focus : sélecteur CSS attendu).
   */
  /** Marqueur de page et première mutation APRÈS le geste (pointeur ou
   *  clavier) : les délais d'attente de Playwright (élément stable…) ne
   *  comptent pas. */
  async function instrumenterGeste(p) {
    await instrumenter(p);
    await p.evaluate(() => {
      window.__geste = null;
      window.__mutationGeste = null;
      const geste = () => { if (window.__geste === null) window.__geste = performance.now(); };
      ['pointerdown', 'keydown'].forEach((t) => document.addEventListener(t, geste, { capture: true, once: true }));
      new MutationObserver(() => {
        if (window.__geste !== null && window.__mutationGeste === null) window.__mutationGeste = performance.now() - window.__geste;
      }).observe(document.documentElement, { subtree: true, childList: true, attributes: true });
    });
  }

  async function mesurer(p, compteur, nom, action, fini, focus, opts = {}) {
    await latence(p, opts.latence === undefined ? 800 : opts.latence);
    await instrumenterGeste(p);
    const avant = await etat(p);
    compteur.docs = 0;
    await action();
    const ok = await attendre(fini, opts.delai || 8000);
    await pause(opts.apres === undefined ? 150 : opts.apres);
    await latence(p, 0);
    const apres = await etat(p);
    apres.mutation = await p.evaluate(() => window.__mutationGeste);
    etape(`${nom} : résultat à l’écran`, !!ok, ok ? undefined : await p.evaluate(() => ({
      occupes: Array.from(document.querySelectorAll('[aria-busy="true"]')).map((x) => x.id || x.className),
      toasts: Array.from(document.querySelectorAll('#k-toasts .k-toast')).map((t) => t.textContent.trim().slice(0, 60)) })));
    etape(`${nom} : aucune navigation de document`, apres.marque && compteur.docs === 0, { docs: compteur.docs });
    if (opts.latence !== 0) {
      etape(`${nom} : 1re mutation ≤ 100 ms sous 800 ms de latence`, apres.mutation !== null && apres.mutation <= 100, apres.mutation);
    }
    if (opts.dy !== false) etape(`${nom} : |Δy| ≤ 40 px`, Math.abs(apres.y - avant.y) <= 40, [avant.y, apres.y]);
    if (focus) etape(`${nom} : focus attendu (${focus})`, await focusSur(p, focus), await focusDecrit(p));
    return { avant, apres };
  }

  // ======================================================================
  // 1. Fiche projet, panneau de tâche (Ali, chef du projet 1), 1 440 px
  // ======================================================================
  const ali = await contexte(navigateur, 'ali@x.tn', { largeur: 1440, hauteur: 900 });
  let p = await ouvrir(ali, '/projets/1');
  let c = compter(p);
  // La fiche défile : le tableau des tâches est au milieu de l'écran.
  await p.evaluate(() => { const l = document.getElementById('tache-ligne-20'); window.scrollBy(0, l.getBoundingClientRect().top - 260); });
  etape('fiche : tâche en retard signalée dans la ligne (audit UX I7)',
    await p.locator('#tache-ligne-20 .taskrow-retard .texte-retard').count() === 1
    && /4\s+j de retard/.test(await p.locator('#tache-ligne-20 .taskrow-retard-jours').innerText()));

  // --- Ouverture : panneau latéral, ?tache=, Retour ferme -----------------
  await mesurer(p, c, 'ouvrir le panneau (pushState ?tache=20)',
    () => p.click('#tache-ligne-20 [data-ouvrir-tache]'),
    () => p.evaluate(() => !!document.querySelector('#dialog-tache #tache-fenetre-20') && location.search === '?tache=20'),
    '#tache-fenetre-20 [data-tache-entete]', { latence: 0 });
  await pause(350);   // fin du glissement (240 ms)
  etape('panneau latéral non modal de 480 px, à droite', await p.evaluate(() => {
    const d = document.getElementById('dialog-tache');
    const r = d.getBoundingClientRect();
    return d.open && !d.matches(':modal') && d.classList.contains('tache-panneau') && Math.round(r.width) === 480
      && Math.abs(r.right - document.documentElement.clientWidth) <= 1;
  }));
  etape('ligne de la tâche ouverte marquée', await p.locator('#tache-ligne-20.taskrow-ouverte').count() === 1);
  await capture(p, 'c-panneau-1440-clair.png');
  // ↓ : tâche suivante (adresse remplacée, pas d'entrée d'historique en plus).
  await p.evaluate(() => document.activeElement.blur());
  await p.keyboard.press('ArrowDown');
  await attendre(() => p.evaluate(() => !!document.querySelector('#tache-fenetre-21')));
  etape('↓ : tâche suivante dans le panneau, ?tache=21', await p.evaluate(() => location.search === '?tache=21'));
  await p.keyboard.press('ArrowUp');
  await attendre(() => p.evaluate(() => !!document.querySelector('#tache-fenetre-20')));
  etape('↑ : retour à la tâche précédente', await p.evaluate(() => location.search === '?tache=20'));
  await p.goBack();
  await attendre(() => p.evaluate(() => !document.getElementById('dialog-tache').open));
  let e = await etat(p);
  etape('Retour du navigateur : panneau fermé, adresse de la fiche, sans rechargement',
    e.marque && c.docs === 0 && e.url === '/projets/1', { ...e, docs: c.docs });
  etape('Retour : focus rendu au titre de la ligne', await focusSur(p, '#tache-ligne-20 [data-ouvrir-tache]'), await focusDecrit(p));
  await p.goForward();
  await attendre(() => p.evaluate(() => !!document.querySelector('#dialog-tache[open] #tache-fenetre-20')));
  etape('Avancer : panneau rouvert sur la tâche', true);
  // Échap puis réouverture pendant l'animation de sortie : une entrée
  // d'historique est poussée de nouveau (avant : Retour quittait la fiche).
  await pause(350);
  await p.keyboard.press('Escape');
  await pause(60);
  await p.focus('#tache-ligne-20 [data-ouvrir-tache]');
  await p.keyboard.press('Enter');
  await attendre(() => p.evaluate(() => !!document.querySelector('#dialog-tache[open] #tache-fenetre-20')));
  await pause(350);
  etape('réouverture pendant la sortie : panneau ouvert, ?tache=20', await p.evaluate(() =>
    document.getElementById('dialog-tache').open && location.search === '?tache=20'));
  await p.goBack();
  await attendre(() => p.evaluate(() => !document.getElementById('dialog-tache').open));
  e = await etat(p);
  etape('… puis Retour : panneau fermé, toujours sur la fiche, sans rechargement',
    e.marque && c.docs === 0 && e.url === '/projets/1', { ...e, docs: c.docs });
  await p.goForward();
  await attendre(() => p.evaluate(() => !!document.querySelector('#dialog-tache[open] #tache-fenetre-20')));

  // --- État : optimiste, ligne, compteur, état du projet, fil ------------
  // Lot 14 : le fil montre les Échanges par défaut ; les posts automatiques
  // sont dans « Tout » (contrôle segmenté, en partiel, ?tache= gardé).
  await p.click('#fil-filtre-projet-tout');
  await attendre(() => p.evaluate(() => !!document.querySelector('#fil-posts[data-fil-categorie="tout"]')
    && /fil=tout/.test(location.search) && /tache=20/.test(location.search)));
  const postsAvant = await p.locator('#fil-posts .fil-item').count();
  // Lot 14 (P0-1) : « Bloquée » demande d'abord « Qu’est-ce qui bloque ? ».
  await p.click('#tache-20-etat-bloque');
  await p.fill('#tache-20-motif', 'Attente des plans archi indice B');
  await mesurer(p, c, 'état « Bloquée » avec son motif (optimiste)',
    () => p.click('#tache-20-blocage-valider'),
    async () => sql('SELECT etat FROM tache WHERE id=20') === 'bloque'
      && await p.locator('#fil-posts .fil-item').count() > postsAvant
      && !(await p.locator('[aria-busy="true"]').count()),
    '#tache-20-etat-bloque');
  etape('état : bouton pressé et pastille du panneau à jour',
    await p.getAttribute('#tache-20-etat-bloque', 'aria-pressed') === 'true'
    && (await p.innerText('#tache-fenetre-20 [data-tache-pastille]')) === 'Bloquée');
  etape('état : ligne du tableau à jour (hors cible)', (await p.innerText('#tache-ligne-20 [data-tache-pastille]')) === 'Bloquée');
  etape('état : projet recalculé « Bloqué » (en-tête, topbar, Informations)',
    (await p.innerText('#projet-etat-pastille')) === 'Bloqué' && sql('SELECT etat FROM projet WHERE id=1') === 'bloque'
    && await p.locator('#topbar-projet .point-etat-bloque').count() === 1);
  etape('état : post automatique « a signalé un blocage » inséré en tête du fil',
    /a signalé un blocage[\s\S]*Attente des plans archi indice B/.test((await p.locator('#fil-posts .fil-item').allInnerTexts()).slice(0, 2).join('\n')));
  etape('état : toast « Blocage signalé. » avec « Annuler »',
    await p.locator('#k-toasts .k-toast:has-text("Blocage signalé.") .k-toast-action').count() === 1);
  await p.click('#k-toasts .k-toast:has-text("Blocage signalé.") .k-toast-action');
  await attendre(() => sql('SELECT etat FROM tache WHERE id=20') === 'en_cours');
  await attendre(async () => (await p.innerText('#tache-ligne-20 [data-tache-pastille]')) === 'En cours');
  etape('« Annuler » : tâche et projet revenus à En cours, sans rechargement',
    sql('SELECT etat FROM projet WHERE id=1') === 'en_cours' && (await etat(p)).marque && c.docs === 0);

  // Refus serveur : l'état optimiste est annulé.
  await p.route(/\/taches\/20\/etat$/, (r) => r.fulfill({ status: 403, contentType: 'application/json',
    body: JSON.stringify({ erreur: 'interdit', message: 'Refus simulé.' }) }));
  await p.click('#tache-20-etat-bloque');
  await p.fill('#tache-20-motif', 'Attente des plans');
  await p.click('#tache-20-blocage-valider');
  await attendre(() => p.locator('#k-toasts .k-toast-erreur:has-text("Refus simulé.")').count());
  etape('refus : état optimiste annulé (bouton et ligne), message en toast',
    await p.getAttribute('#tache-20-etat-en_cours', 'aria-pressed') === 'true'
    && (await p.innerText('#tache-ligne-20 [data-tache-pastille]')) === 'En cours');
  await p.unroute(/\/taches\/20\/etat$/);
  await p.click('#tache-20-blocage [data-blocage-annuler]');
  await p.click('#k-toasts .k-toast-erreur .k-toast-fermer');
  await pause(250);   // le focus quitte le toast fermé

  // --- Renommer en place ---------------------------------------------------
  await p.fill('#tache-titre-20', 'Tâche de liste 00 renommée');
  await mesurer(p, c, 'renommer en place (Entrée)',
    () => p.press('#tache-titre-20', 'Enter'),
    async () => sql('SELECT titre FROM tache WHERE id=20') === 'Tâche de liste 00 renommée'
      && await p.locator('#tache-fenetre-20 .tache-enregistre').count() === 1,
    '#tache-titre-20');
  etape('renommer : ligne du tableau à jour', (await p.innerText('#tache-ligne-20 [data-ouvrir-tache]')) === 'Tâche de liste 00 renommée');

  // --- Échéance ------------------------------------------------------------
  const demain = sql("SELECT to_char(CURRENT_DATE + 30, 'YYYY-MM-DD')");
  await p.fill('#tache-20-date-echeance', demain);
  await mesurer(p, c, 'échéance (panneau)',
    () => p.click('#tache-20-echeance-enregistrer'),
    async () => sql('SELECT date_echeance::text FROM tache WHERE id=20') === demain
      && await p.locator('#tache-ligne-20 .taskrow-retard').count() === 0,
    '#tache-20-echeance-enregistrer');
  // Erreur reliée au champ : échéance hors bornes.
  await p.evaluate(() => { document.getElementById('tache-20-date-echeance').value = '1990-01-01'; });
  await p.click('#tache-20-echeance-enregistrer');
  await attendre(() => p.evaluate(() => document.getElementById('tache-20-date-echeance').getAttribute('aria-invalid') === 'true'));
  etape('échéance refusée : champ aria-invalid, message relié (aria-describedby), focus dessus (a11y I5)', await p.evaluate(() => {
    const c = document.getElementById('tache-20-date-echeance');
    const id = (c.getAttribute('aria-describedby') || '').split(' ')[0];
    const m = document.getElementById(id);
    return document.activeElement === c && !!m && m.classList.contains('champ-erreur') && m.textContent.length > 5;
  }));

  // --- Intervenants : affecter, retirer ------------------------------------
  const champAffecter = p.locator('#tache-fenetre-20 .tache-ajout-intervenant .search-combobox-input');
  await champAffecter.click();
  await champAffecter.fill('helene');
  await mesurer(p, c, 'affecter quelqu’un (sélecteur à recherche)',
    () => champAffecter.press('Enter'),
    async () => sql('SELECT count(*) FROM tache_intervenant WHERE tache_id=20 AND utilisateur_id=151') === '1'
      && await p.locator('#tache-20-intervenant-151').count() === 1,
    '.tache-ajout-intervenant .search-combobox-input');
  etape('affecter : avatar ajouté à la ligne (hors cible)', /Hélène/.test(await p.getAttribute('#tache-ligne-20 .avatar-stack', 'aria-label')));
  await mesurer(p, c, 'retirer de la tâche',
    () => p.click('#tache-20-retirer-151'),
    async () => sql('SELECT count(*) FROM tache_intervenant WHERE tache_id=20 AND utilisateur_id=151') === '0'
      && await p.locator('#tache-20-intervenant-151').count() === 0,
    '.tache-ajout-intervenant .search-combobox-input');

  // --- Rejoindre (panneau) -------------------------------------------------
  await mesurer(p, c, 'rejoindre la tâche (panneau)',
    () => p.click('#tache-20-rejoindre'),
    async () => sql('SELECT count(*) FROM tache_intervenant WHERE tache_id=20 AND utilisateur_id=2') === '1'
      && await p.locator('#tache-20-rejoindre').count() === 0,
    '#tache-fenetre-20 [data-tache-entete]');

  // --- Pièce jointe : progression, liste à jour ----------------------------
  const fichier = path.join(os.tmpdir(), 'kairos-e2e-pj-' + process.pid + '.txt');
  fs.writeFileSync(fichier, 'x'.repeat(400000));
  await latence(p, 800);
  await instrumenter(p);
  c.docs = 0;
  await p.setInputFiles('#tache-20-fichier', fichier);
  const progressionVue = await attendre(() => p.evaluate(() => {
    const b = document.querySelector('#tache-fenetre-20 [data-progression]');
    return !!b && !b.hidden;
  }), 3000);
  await attendre(() => p.locator('#tache-fenetre-20 .tache-pj-lien:has-text("kairos-e2e-pj")').count(), 10000);
  await latence(p, 0);
  e = await etat(p);
  etape('pièce jointe : barre de progression pendant l’envoi', !!progressionVue);
  etape('pièce jointe : liste à jour sans rechargement, en base',
    e.marque && c.docs === 0 && sql("SELECT count(*) FROM tache_piece_jointe WHERE tache_id=20") === '1');
  etape('pièce jointe : focus sur le champ fichier', await focusSur(p, '#tache-20-fichier'), await focusDecrit(p));
  fs.unlinkSync(fichier);

  // --- Clôturer : la ligne passe dans les tâches closes --------------------
  const compteurAvant = await p.innerText('#taches-compteur');
  await mesurer(p, c, 'clôturer (Marquer comme terminée)',
    () => p.click('#tache-20-cloturer'),
    async () => sql('SELECT etat FROM tache WHERE id=20') === 'termine'
      && await p.locator('#taches-closes [data-open-tache="20"]').count() === 1,
    '#tache-fenetre-20 [data-tache-entete]', { dy: false });
  etape('clôturer : compteur à jour', (await p.innerText('#taches-compteur')) !== compteurAvant, [compteurAvant, await p.innerText('#taches-compteur')]);
  etape('clôturer : bouton « Rouvrir » proposé', await p.locator('#tache-20-etat-en_cours:has-text("Rouvrir")').count() === 1);
  await capture(p, 'c-panneau-cloture-1440-clair.png');
  await p.keyboard.press('Escape');
  await attendre(() => p.evaluate(() => !document.getElementById('dialog-tache').open));
  etape('Échap : panneau fermé', true);

  // --- « + Tâche » : ligne insérée et surlignée, post dans le fil ----------
  // Lot 14 : fermer le panneau (Échap = Retour) a ramené l'adresse d'avant
  // le choix « Tout » (Échanges, sans les posts automatiques) : on y revient.
  if (await p.evaluate(() => !/fil=tout/.test(location.search))) {
    await p.click('#fil-filtre-projet-tout');
    await attendre(() => p.evaluate(() => !!document.querySelector('#fil-posts[data-fil-categorie="tout"]')));
  }
  // Lot 15 : « + Tâche » retiré (doublon) : « + Nouveau post », onglet Tâche.
  await p.click('#nouveau-post');
  await p.fill('#dialog-titre-tache', 'Tâche créée en partiel');
  await mesurer(p, c, '« + Tâche » publiée',
    () => p.click('#publier-tache'),
    async () => sql("SELECT count(*) FROM tache WHERE titre='Tâche créée en partiel'") === '1'
      && !(await p.evaluate(() => document.getElementById('dialog-nouveau-post').open))
      && await p.locator('#carte-taches .taskrow.k-surligne:has-text("Tâche créée en partiel")').count() === 1,
    '#nouveau-post', { dy: false });
  etape('« + Tâche » : post de création en tête du fil, surligné',
    await p.locator('#fil-posts .fil-item').first().locator(':text("Tâche créée en partiel")').count() >= 1);
  // Titre manquant : champ signalé, fenêtre ouverte.
  await p.click('#nouveau-post');
  await p.evaluate(() => { const t = document.getElementById('dialog-titre-tache'); t.removeAttribute('required'); t.value = '  '; });
  await p.click('#publier-tache');
  await attendre(() => p.evaluate(() => document.getElementById('dialog-titre-tache').getAttribute('aria-invalid') === 'true'));
  etape('« + Tâche » refusée (422) : fenêtre ouverte, champ signalé et focalisé',
    await p.evaluate(() => document.getElementById('dialog-nouveau-post').open && document.activeElement.id === 'dialog-titre-tache'));
  await p.click('#dialog-nouveau-post [data-close-post-dialog] >> nth=0');

  // --- Intervenants du projet : ajouter, retirer ---------------------------
  await p.evaluate(() => document.getElementById('carte-intervenants').scrollIntoView({ block: 'center' }));
  const champProjet = p.locator('#carte-intervenants .search-combobox-input');
  await champProjet.click();
  await champProjet.fill('sami');
  await mesurer(p, c, 'ajouter un intervenant au projet',
    () => champProjet.press('Enter'),
    async () => sql('SELECT count(*) FROM projet_intervenant WHERE projet_id=1 AND utilisateur_id=150') === '1'
      && await p.locator('#projet-intervenant-150').count() === 1,
    '#carte-intervenants .search-combobox-input');
  await p.click('#retirer-intervenant-150');
  await mesurer(p, c, 'retirer un intervenant du projet (confirmation en ligne)',
    // Clic à la souris (le clic de Playwright fait défiler la page vers
    // la bulle de confirmation, positionnée en absolu).
    async () => { const bb = await p.locator('.k-confirmation button:has-text("Retirer")').boundingBox();
      await p.mouse.click(bb.x + bb.width / 2, bb.y + bb.height / 2); },
    async () => sql('SELECT count(*) FROM projet_intervenant WHERE projet_id=1 AND utilisateur_id=150') === '0'
      && await p.locator('#projet-intervenant-150').count() === 0,
    '#carte-intervenants [data-partiel-titre]');

  // --- Informations : enregistrer, clore avec confirmation, rouvrir --------
  await p.evaluate(() => window.scrollTo(0, 0));
  await p.click('#carte-informations button[data-open-informations-dialog]');
  await p.fill('#dialog-info-nom', 'Siemens modifié');
  await mesurer(p, c, 'Informations : enregistrer',
    () => p.click('#informations-enregistrer'),
    async () => sql('SELECT nom FROM projet WHERE id=1') === 'Siemens modifié'
      && !(await p.evaluate(() => document.getElementById('dialog-informations-projet').open))
      && /Siemens modifié/.test(await p.innerText('#projet-entete')),
    '#carte-informations button[data-open-informations-dialog]');
  etape('Informations : sous-barre et titre de la fiche à jour', /Siemens modifié/.test(await p.innerText('#projet-subbar')));
  await p.click('#carte-informations button[data-open-informations-dialog]');
  await p.fill('#dialog-info-honoraires', 'abc');
  await p.click('#informations-enregistrer');
  await attendre(() => p.evaluate(() => document.activeElement.id === 'dialog-info-honoraires'));
  etape('Informations refusées (422) : champ « Honoraires » signalé, focalisé, saisie gardée',
    await p.evaluate(() => { const c = document.getElementById('dialog-info-honoraires');
      return c.getAttribute('aria-invalid') === 'true' && c.value === 'abc' && document.getElementById('dialog-informations-projet').open; }));
  await p.fill('#dialog-info-honoraires', '');
  await p.fill('#dialog-info-nom', 'Siemens clos');
  await p.selectOption('#dialog-info-etat', 'termine');
  await p.click('#informations-enregistrer');
  await attendre(() => p.evaluate(() => { const f = document.getElementById('informations-form'); return f && f.tagName === 'SECTION'; }));
  // Recette finale NF1 : « Revenir au formulaire » garde la saisie.
  await p.click('#informations-form [data-informations-retour]');
  await attendre(() => p.evaluate(() => { const f = document.getElementById('informations-form'); return f && f.tagName === 'FORM'; }));
  const retourSaisie = await p.evaluate(() => [document.getElementById('dialog-info-nom').value, document.getElementById('dialog-info-etat').value,
    document.getElementById('dialog-informations-projet').open, !!document.activeElement.closest('#informations-form')]);
  etape('clôture : « Revenir au formulaire » garde la saisie (nom, état), fenêtre ouverte, focus dans le formulaire',
    retourSaisie[0] === 'Siemens clos' && retourSaisie[1] === 'termine' && retourSaisie[2] && retourSaisie[3], retourSaisie);
  await p.click('#informations-enregistrer');
  await attendre(() => p.evaluate(() => { const f = document.getElementById('informations-form'); return f && f.tagName === 'SECTION'; }));
  etape('clôture : confirmation dans la fenêtre, focus sur la question', await focusSur(p, '#informations-form [data-partiel-titre]'), await focusDecrit(p));
  await capture(p, 'c-cloture-confirmation-1440-clair.png');
  const ouvertes = sql("SELECT count(*) FROM tache WHERE projet_id=1 AND etat IN ('en_cours','bloque')");
  await mesurer(p, c, 'clôture du projet confirmée',
    () => p.click('#cloture-confirmer'),
    async () => sql("SELECT etat || ':' || nom FROM projet WHERE id=1") === 'termine:Siemens clos'
      && !(await p.evaluate(() => document.getElementById('dialog-informations-projet').open))
      && (await p.innerText('#projet-etat-pastille')) === 'Terminé',
    '#carte-informations button[data-open-informations-dialog]');
  etape(`clôture : ${ouvertes} tâches ouvertes closes, publication et commentaires fermés`,
    sql("SELECT count(*) FROM tache WHERE projet_id=1 AND etat IN ('en_cours','bloque')") === '0'
    && await p.locator('#nouveau-post').count() === 0 && await p.locator('#fil-posts .comment-composer').count() === 0
    && await p.locator('#carte-taches [data-open-post-dialog]').count() === 0);
  await p.click('#carte-informations button[data-open-informations-dialog]');
  await p.selectOption('#dialog-info-etat', 'en_cours');
  await mesurer(p, c, 'réouverture du projet',
    () => p.click('#informations-enregistrer'),
    async () => sql('SELECT etat FROM projet WHERE id=1') === 'en_cours' && await p.locator('#nouveau-post').count() === 1,
    '#carte-informations button[data-open-informations-dialog]');
  await ali.close();
  // Tâches closes avec le projet : quelques-unes rouvertes pour la suite.
  sql("UPDATE tache SET etat='en_cours', date_fin=NULL WHERE id IN (21, 22, 23, 24)");

  // --- « Rejoindre » : ligne (Rim) et projet (Sami) ------------------------
  const rim = await contexte(navigateur, 'rim@x.tn', { largeur: 1440, hauteur: 900 });
  p = await ouvrir(rim, '/projets/1');
  c = compter(p);
  await p.reload();
  await p.evaluate(() => { const l = document.getElementById('tache-ligne-23'); window.scrollBy(0, l.getBoundingClientRect().top - 300); });
  await p.hover('#tache-ligne-23');
  await mesurer(p, c, 'rejoindre au survol de la ligne',
    () => p.click('#tache-ligne-23 .task-join-btn'),
    async () => sql('SELECT count(*) FROM tache_intervenant WHERE tache_id=23 AND utilisateur_id=3') === '1'
      && await p.locator('#tache-ligne-23 .task-join-btn').count() === 0,
    '#tache-ligne-23 [data-ouvrir-tache]');
  await rim.close();
  const sami = await contexte(navigateur, 'sami@x.tn', { largeur: 1440, hauteur: 900 });
  p = await ouvrir(sami, '/projets/1');
  c = compter(p);
  await p.evaluate(() => document.getElementById('rejoindre-projet').scrollIntoView({ block: 'center' }));
  await mesurer(p, c, 'rejoindre le projet',
    () => p.click('#rejoindre-projet'),
    async () => sql('SELECT count(*) FROM projet_intervenant WHERE projet_id=1 AND utilisateur_id=150') === '1'
      && await p.locator('#rejoindre-projet').count() === 0,
    '#carte-intervenants [data-partiel-titre]');
  await sami.close();

  // ======================================================================
  // 2. Fil de l'accueil (Ali)
  // ======================================================================
  const ali2 = await contexte(navigateur, 'ali@x.tn', { largeur: 1440, hauteur: 900 });
  p = await ouvrir(ali2, '/accueil');
  c = compter(p);
  await p.evaluate(() => document.getElementById('post-50').scrollIntoView({ block: 'center' }));
  // Lot 14 : « Commenter » déplie le champ et y place le focus.
  await p.click('#post-50-commenter');
  etape('« Commenter » : champ déplié, focus dedans, aria-expanded', await focusSur(p, '#commentaire-post-50')
    && await p.getAttribute('#post-50-commenter', 'aria-expanded') === 'true');
  await p.keyboard.type('Commentaire en partiel');
  await mesurer(p, c, 'commentaire (Entrée)',
    () => p.keyboard.press('Enter'),
    async () => sql("SELECT count(*) FROM post_commentaire WHERE contenu='Commentaire en partiel'") === '1'
      && /Commentaire en partiel/.test(await p.innerText('#post-50-commentaires')),
    '#commentaire-post-50');
  etape('commentaire : champ vidé, compteur à jour (hors cible)', (await p.inputValue('#commentaire-post-50')) === ''
    && /3\s*commentaires/.test(await p.textContent('#post-50-compteur')));
  await p.click('#post-50 [data-repondre] >> nth=0');
  await p.keyboard.type('Réponse en partiel');
  await mesurer(p, c, 'réponse à un commentaire',
    () => p.keyboard.press('Enter'),
    async () => sql("SELECT count(*) FROM post_commentaire WHERE contenu='Réponse en partiel' AND parent_commentaire_id IS NOT NULL") === '1'
      && /Réponse en partiel/.test(await p.innerText('#post-50-commentaires')),
    '#post-50 .post-comment[data-partiel-titre]');
  const idModif = sql("SELECT id FROM post_commentaire WHERE contenu='Commentaire en partiel'");
  await p.click(`#commentaire-${idModif}-modifier`);
  await p.keyboard.type(' (modifié)');
  await mesurer(p, c, 'modification d’un commentaire',
    () => p.keyboard.press('Enter'),
    async () => sql(`SELECT contenu FROM post_commentaire WHERE id=${idModif}`) === 'Commentaire en partiel (modifié)'
      && /\(modifié\)/.test(await p.innerText(`#commentaire-${idModif} .post-comment-texte`))
      && await p.locator(`#commentaire-${idModif} [data-comment-edit]:not([hidden])`).count() === 0,
    `#commentaire-${idModif}-modifier`);
  // Réaction ✓ : optimiste, JSON (plus de rendu de toute la page).
  const reaction = p.locator('#post-51 .post-reaction-form button');
  let reponseReaction = null;
  p.on('response', (r) => { if (/\/posts\/51\/reagir$/.test(r.url())) reponseReaction = r; });
  await p.evaluate(() => document.querySelector('#post-51 .post-reaction-form').scrollIntoView({ block: 'center' }));
  await mesurer(p, c, 'réaction ✓ (optimiste)',
    () => reaction.click(),
    async () => sql('SELECT count(*) FROM post_reaction WHERE post_id=51') === '2' && await reaction.getAttribute('aria-disabled') === null,
    '#post-51 .post-reaction-form button');
  etape('réaction : compteur, état pressé et infobulle des personnes à jour',
    (await p.innerText('#post-51 .post-reaction-count')) === '2' && await reaction.getAttribute('aria-pressed') === 'true'
    && /Ali Chef/.test(await reaction.getAttribute('title')) && /Rim Inter/.test(await reaction.getAttribute('title')));
  etape('réaction : réponse JSON (200), pas de page rendue', !!reponseReaction && reponseReaction.status() === 200
    && /json/.test(reponseReaction.headers()['content-type'] || ''));
  // Publication : post en tête du fil, fenêtre fermée.
  await p.evaluate(() => window.scrollTo(0, 0));
  await p.click('#nouveau-post');
  await p.click('label[for="intent-information"]');
  await p.fill('#dialog-contenu-information', 'Information publiée sans recharger');
  await mesurer(p, c, 'publication d’un post (en tête du fil)',
    () => p.click('#publier-information'),
    async () => !(await p.evaluate(() => document.getElementById('dialog-nouveau-post').open))
      && /Information publiée sans recharger/.test(await p.locator('#fil-liste .fil-item').first().innerText()),
    '#nouveau-post');
  etape('publication : post surligné à son arrivée', await p.locator('#fil-liste .fil-item.k-nouveau').count() >= 1);
  await capture(p, 'c-accueil-publication-1440-clair.png');
  await ali2.close();

  // Suppression d'un commentaire (Admin) : confirmation, bloc remplacé.
  const adm = await contexte(navigateur, 'admin@x.tn', { largeur: 1440, hauteur: 900 });
  p = await ouvrir(adm, '/projets/1');
  c = compter(p);
  await p.evaluate(() => document.getElementById('post-50').scrollIntoView({ block: 'center' }));
  const premier = sql("SELECT min(id) FROM post_commentaire WHERE post_id=50");
  await p.click(`#commentaire-${premier} .post-comment-supprimer summary`);
  await mesurer(p, c, 'suppression d’un commentaire (Admin)',
    () => p.click(`#commentaire-${premier} [data-confirmer-suppression]`),
    // Lot 15 : suppression logique (« Annuler » dans le toast).
    async () => sql(`SELECT count(*) FROM post_commentaire WHERE id=${premier} AND supprime_le IS NOT NULL`) === '1'
      && await p.locator(`#commentaire-${premier}`).count() === 0,
    '#post-50-commenter');
  await p.keyboard.press('Control+z');
  await attendre(async () => await p.locator(`#commentaire-${premier}`).count() === 1);
  etape('suppression d’un commentaire : Ctrl+Z le rétablit', await p.locator(`#commentaire-${premier}`).count() === 1
    && sql(`SELECT count(*) FROM post_commentaire WHERE id=${premier} AND supprime_le IS NULL`) === '1');

  // --- « Voir comme » : aucune écriture active sur la fiche ----------------
  const voir = await adm.newPage();
  await voir.goto(BASE + '/admin/voir-comme');
  await voir.evaluate(() => { document.getElementById('voir-comme-compte').value = '2'; });
  await Promise.all([voir.waitForNavigation(), voir.click('button:has-text("Voir comme")')]);
  await voir.goto(BASE + '/projets/1?tache=21');
  await voir.waitForSelector('#dialog-tache #tache-fenetre-21');
  await pause(300);
  const actifs = await voir.evaluate(() => {
    const visibles = (s) => Array.from(document.querySelectorAll(s)).filter((x) => x.offsetParent !== null && !x.disabled);
    const ecritures = Array.from(document.querySelectorAll('form[method=post]:not([data-permis-lecture])'))
      .flatMap((f) => Array.from(f.querySelectorAll('button, input:not([type=hidden]), select, textarea')))
      .filter((x) => x.offsetParent !== null && !x.disabled);
    return { ecritures: ecritures.length, rejoindre: visibles('.task-join-btn').length,
      nouveau: visibles('[data-open-post-dialog]').length, reaction: visibles('.post-reaction-form button').length };
  });
  etape('Voir comme (fiche + panneau) : aucune commande d’écriture active', actifs.ecritures === 0 && actifs.rejoindre === 0
    && actifs.nouveau === 0 && actifs.reaction === 0, actifs);
  await voir.close();
  await adm.close();

  // ======================================================================
  // 3. Tous les projets (Ali) : filtres, pagination, Retour, export
  // ======================================================================
  const ali3 = await contexte(navigateur, 'ali@x.tn', { largeur: 1440, hauteur: 900 });
  p = await ouvrir(ali3, '/projets');
  c = compter(p);
  etape('Tous les projets : vrai tableau (rôles table/row/columnheader/cell), lien sur le nom (a11y I6)', await p.evaluate(() =>
    !!document.querySelector('#projets-resultats [role=table][aria-label="Projets"]')
    && document.querySelectorAll('#projets-resultats [role=columnheader]').length === 7
    && document.querySelectorAll('#projets-resultats [role=row] [role=cell] a.ptable-lien').length > 0));
  etape('adresse initiale : filtres par défaut écrits', /filtres_actifs=1/.test(await p.evaluate(() => location.search)));
  // Pagination : haut de la liste à l'écran, focus sur le compteur.
  await p.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  const r1 = await mesurer(p, c, 'pagination « Suivant »',
    () => p.click('#projets-resultats a[rel=next]'),
    async () => /page=2/.test(await p.evaluate(() => location.search)) && /51–/.test(await p.innerText('#projets-compte')),
    '#projets-compte', { dy: false });
  etape('pagination : haut de la liste à l’écran', await p.evaluate(() => {
    const r = document.getElementById('projets-resultats').getBoundingClientRect();
    return r.top >= 0 && r.top < innerHeight / 2;
  }), r1.apres.y);
  etape('pagination : titre de l’onglet « — page 2 » (a11y M9)', /page 2/.test(await p.title()));
  // Puce de filtre : pushState, indicateur, focus gardé.
  await latence(p, 800);
  await instrumenter(p);
  await p.click('.filtre-groupe:has(#filtre-titre-etat) .chip-opt:has-text("Terminé")');
  await pause(200);
  const indicateur = await p.evaluate(() => document.getElementById('projets-resultats').getAttribute('aria-busy') === 'true'
    && document.getElementById('projets-resultats').classList.contains('k-en-cours'));
  await attendre(async () => /etat=termine/.test(await p.evaluate(() => location.search)), 8000);
  await pause(300);
  await latence(p, 0);
  e = await etat(p);
  etape('puce « Terminé » : indicateur aria-busy après 150 ms (réseau lent)', indicateur);
  etape('puce « Terminé » : adresse en pushState, sans rechargement, 1re mutation ≤ 100 ms',
    e.marque && c.docs === 0 && e.mutation !== null && e.mutation <= 100, { ...e, docs: c.docs });
  etape('puce « Terminé » : focus gardé sur la puce', await focusSur(p, '.chip-opt'), await focusDecrit(p));
  await p.click('#filtre-projets-q');
  await p.keyboard.type('liste 1', { delay: 40 });
  await attendre(async () => /q=liste\+1/.test(await p.evaluate(() => location.search)), 4000);
  etape('recherche : ?q= dans l’adresse, focus gardé dans le champ', await focusSur(p, '#filtre-projets-q'));
  await p.goBack();
  await attendre(async () => !/q=/.test(await p.evaluate(() => location.search)) && (await p.inputValue('#filtre-projets-q')) === '', 4000);
  etape('Retour 1 : recherche défaite, champ vidé, sans rechargement', (await etat(p)).marque && c.docs === 0);
  await p.goBack();
  await attendre(async () => /page=2/.test(await p.evaluate(() => location.search)), 4000);
  await pause(300);
  etape('Retour 2 : page 2 retrouvée, puce « Terminé » désélectionnée', (await etat(p)).marque && c.docs === 0
    && await p.locator('.filtre-groupe:has(#filtre-titre-etat) .chip-opt.chip-selected:has-text("Terminé")').count() === 0
    && await p.locator('.filtre-groupe:has(#filtre-titre-etat) .chip-opt.chip-selected:has-text("En cours")').count() === 1);
  await p.goBack();
  await attendre(async () => !/page=2/.test(await p.evaluate(() => location.search)), 4000);
  etape('Retour 3 : page 1, toujours sans rechargement', (await etat(p)).marque && c.docs === 0);
  // Export avec retour.
  const telechargement = p.waitForEvent('download', { timeout: 8000 }).catch(() => null);
  await p.click('#export-excel');
  const dl = await telechargement;
  await attendre(() => p.locator('#k-toasts .k-toast:has-text("téléchargé")').count(), 5000);
  etape('export Excel : fichier reçu, toast de confirmation', !!dl && /\.xlsx$/.test(dl.suggestedFilename()));
  // « Nouveau projet » : code en double signalé dans la fenêtre.
  await p.click('[data-open-projet-dialog]');
  await p.fill('#dialog-projet-nom', 'Doublon');
  await p.fill('#dialog-projet-code', '21114X');
  await p.click('#dialog-projet-lots + .chip-select-wrap .chip-opt >> nth=0');
  await p.click('#nouveau-projet-creer');
  await attendre(() => p.evaluate(() => document.activeElement.id === 'dialog-projet-code'));
  etape('Nouveau projet : code en double signalé (aria-invalid, message relié, focus), fenêtre ouverte (a11y I5)',
    await p.evaluate(() => { const c = document.getElementById('dialog-projet-code');
      const m = document.getElementById((c.getAttribute('aria-describedby') || '').split(' ')[0]);
      return c.getAttribute('aria-invalid') === 'true' && !!m && /déjà utilisé/.test(m.textContent)
        && document.getElementById('dialog-nouveau-projet').open; }));
  await ali3.close();

  // ======================================================================
  // 4. Mouvement réduit, 375 / 768 / 1024 px, clair et sombre
  // ======================================================================
  const calme = await contexte(navigateur, 'ali@x.tn', { largeur: 1440, hauteur: 900, reducedMotion: 'reduce' });
  p = await ouvrir(calme, '/projets/1?tache=21');
  await p.waitForSelector('#dialog-tache #tache-fenetre-21');
  await p.click('#tache-21-etat-bloque');
  await p.fill('#tache-21-motif', 'Attente des plans');
  await p.click('#tache-21-blocage-valider');
  let maxAnim = 0;
  for (let i = 0; i < 6; i++) {
    maxAnim = Math.max(maxAnim, await p.evaluate(() => Math.max(0, ...document.getAnimations()
      .filter((a) => !(a.effect && a.effect.target && a.effect.target.classList && a.effect.target.classList.contains('roue-chargement')))
      .map((a) => Number(a.effect.getTiming().duration) || 0))));
    await pause(80);
  }
  etape('mouvement réduit : panneau et mises à jour sans animation > 1 ms', maxAnim <= 1, maxAnim);
  await attendre(() => sql('SELECT etat FROM tache WHERE id=21') === 'bloque');
  sql("UPDATE tache SET etat='en_cours' WHERE id=21");
  await calme.close();

  for (const [largeur, theme] of [[375, 'light'], [375, 'dark'], [768, 'light'], [1024, 'dark']]) {
    const ctx = await contexte(navigateur, 'ali@x.tn', { largeur, hauteur: 800, theme });
    p = await ouvrir(ctx, '/projets');
    const debP = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    const cartes = largeur < 600 ? await p.evaluate(() => getComputedStyle(document.querySelector('.ptable-row')).gridTemplateAreas.includes('projet')) : true;
    await capture(p, `c-projets-${largeur}-${theme}.png`);
    p = await ouvrir(ctx, '/projets/1?tache=21');
    await p.waitForSelector('#dialog-tache #tache-fenetre-21');
    await pause(400);
    const deb = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    const bt = await p.locator('#dialog-tache').boundingBox();
    etape(`${largeur} px ${theme} : aucun débordement (projets, fiche), panneau dans l’écran${largeur < 600 ? ', cartes' : ''}`,
      debP === 0 && deb === 0 && cartes && bt.x >= 0 && bt.x + bt.width <= largeur + 1, { debP, deb, bt, cartes });
    if (largeur < 600) {
      etape(`${largeur} px ${theme} : feuille en bas de l’écran`, Math.abs(bt.y + bt.height - 800) <= 2, bt);
    }
    await capture(p, `c-panneau-${largeur}-${theme}.png`);
    await ctx.close();
  }
};

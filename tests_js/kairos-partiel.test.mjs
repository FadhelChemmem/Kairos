// Lot 13 — socle des mises à jour partielles (app/static/js/kairos-partiel.js).
// DOM minimal fait main (pas de jsdom hors ligne) : éléments à attributs et
// classes, horloge simulée, fetch simulé. Le remplacement HTML lui-même
// (K.remplacer, <template>) et les toasts sont observés par des espions ;
// le rendu réel est vérifié par Playwright (docs/partiel.md, « Tests »).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { creer } = require('../app/static/js/kairos-partiel.js');

class ClassList {
  constructor() { this.s = new Set(); }
  add(...c) { c.forEach((x) => this.s.add(x)); }
  remove(...c) { c.forEach((x) => this.s.delete(x)); }
  contains(c) { return this.s.has(c); }
  toggle(c, v) { if (v === undefined ? !this.s.has(c) : v) this.s.add(c); else this.s.delete(c); }
}

class El {
  constructor(doc, tag, attrs = {}) {
    this.doc = doc; this.tagName = tag.toUpperCase(); this.attrs = { ...attrs }; this.classList = new ClassList();
    this.top = 100; this.focusCount = 0; this.tabIndex = /^(BUTTON|A|INPUT)$/.test(this.tagName) ? 0 : -1;
    this.enfants = []; this.nodeType = 1; this.dataset = {};
  }
  contains(e) { return e === this || this.enfants.some((x) => x === e || x.contains(e)); }
  get id() { return this.attrs.id || ''; }
  setAttribute(n, v) { this.attrs[n] = String(v); }
  getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; }
  hasAttribute(n) { return n in this.attrs; }
  removeAttribute(n) { delete this.attrs[n]; }
  matches(sel) { return sel.split(',').some((s) => { const m = /\[([\w-]+)/.exec(s); return m && this.hasAttribute(m[1]); }); }
  querySelector(sel) { return this.enfants.find((e) => e.matches(sel)) || null; }
  getBoundingClientRect() { return { top: this.top }; }
  focus() { this.focusCount++; this.doc.activeElement = this; }
}

function environnement({ reponses }) {
  const minuteurs = [];
  let horloge = 0;
  const appels = [];
  const doc = {
    readyState: 'complete', activeElement: null, elements: [],
    documentElement: { hasAttribute: () => false },
    body: null,
    contains(e) { return this.elements.includes(e); },
    getElementById(id) { return this.elements.find((e) => e.id === id) || null; },
    querySelector(sel) { const m = /^#([\w-]+)$/.exec(sel); return m ? this.getElementById(m[1]) : null; },
    dispatchEvent(ev) { this.evenements.push(ev); },
    evenements: [],
    ajouter(e) { this.elements.push(e); return e; },
    retirer(e) { this.elements = this.elements.filter((x) => x !== e); },
  };
  doc.body = new El(doc, 'body');
  doc.activeElement = doc.body;
  const historique = [];
  const win = {
    location: { pathname: '/utilisateurs', search: '', href: 'http://k/utilisateurs', assign(u) { win.assigne = u; } },
    history: {
      state: null,
      pushState(st, t, u) { historique.push(['push', u, st]); this.state = st; },
      replaceState(st, t, u) { historique.push(['replace', u, st]); this.state = st; },
    },
    scrollBy(x, y) { win.defile = (win.defile || 0) + y; },
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail; } },
    AbortController: class { constructor() { this.signal = { aborted: false }; } abort() { this.signal.aborted = true; } },
    addEventListener() {},
  };
  const env = {
    window: win, document: doc,
    maintenant: () => horloge,
    setTimeout(f, d) { const t = { f, a: horloge + (d || 0) }; minuteurs.push(t); return t; },
    clearTimeout(t) { const i = minuteurs.indexOf(t); if (i >= 0) minuteurs.splice(i, 1); },
    fetch(url, options) {
      appels.push({ url, options });
      const r = reponses.shift();
      if (r instanceof Error) return Promise.reject(r);
      const entetes = r.entetes || {};
      return (r.delai ? new Promise((ok) => env.setTimeout(ok, r.delai)) : Promise.resolve()).then(() => ({
        status: r.statut || 200,
        headers: { get: (n) => entetes[n] || null },
        text: () => Promise.resolve(r.corps || ''),
      }));
    },
  };
  const K = creer(env);
  const toasts = [];
  K.toast = (texte, opts) => { toasts.push({ texte, ...(opts || {}) }); };
  const remplacements = [];
  K.remplacer = (cible, html, mode) => {
    remplacements.push({ cible, html, mode });
    const nouvelle = new El(doc, 'div', { id: cible.id });
    nouvelle.top = cible.top + (K._decalage || 0);
    doc.retirer(cible);
    doc.ajouter(nouvelle);
    if (K._ajouter) K._ajouter.forEach((e) => doc.ajouter(e));
    return { racine: nouvelle, autres: [] };
  };
  async function avancer(ms) {
    const fin = horloge + ms;
    for (;;) {
      await new Promise((r) => setImmediate(r));
      minuteurs.sort((a, b) => a.a - b.a);
      const t = minuteurs[0];
      if (!t || t.a > fin) break;
      minuteurs.shift();
      horloge = t.a;
      t.f();
    }
    horloge = fin;
    for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
  }
  return { K, doc, win, appels, toasts, remplacements, historique, avancer, El };
}

test('outils : délai des filtres, toasts encodés, historique, messages', () => {
  const { K } = environnement({ reponses: [] });
  assert.deepEqual(K.lireAuto('input:250 change'), { input: 250, change: 0 });
  assert.deepEqual(K.lireAuto('input'), { input: 250 });
  assert.deepEqual(K.lireAuto('change:x'), { change: 0 });
  const enc = encodeURIComponent(JSON.stringify([{ type: 'succes', texte: 'Compte réactivé.' }, { type: 'erreur' }]));
  assert.deepEqual(K.lireToasts(enc), [{ type: 'succes', texte: 'Compte réactivé.' }]);
  assert.deepEqual(K.lireToasts('%E0%A4%A'), []);
  assert.deepEqual(K.lireToasts(null), []);
  assert.equal(K.historiqueParDefaut('GET'), 'push');
  assert.equal(K.historiqueParDefaut('post'), 'aucun');
  assert.equal(K.historiqueParDefaut('GET', 'replace'), 'replace');
  assert.equal(K.messageErreur(403, '{"message":"Seul un Admin."}'), 'Seul un Admin.');
  assert.match(K.messageErreur(409, '<html>'), /Conflit/);
  assert.match(K.messageErreur(503, ''), /serveur/);
});

test('réponse rapide : aucun indicateur, remplacement, focus rendu par id, historique', async () => {
  const e = environnement({ reponses: [{ corps: '<div id="res">x</div>', entetes: { 'X-Kairos-Toasts': encodeURIComponent('[{"type":"succes","texte":"OK"}]') } }] });
  const cible = e.doc.ajouter(new e.El(e.doc, 'div', { id: 'res' }));
  const champ = e.doc.ajouter(new e.El(e.doc, 'input', { id: 'q' }));
  champ.focus();
  const p = e.K.requete({ url: '/utilisateurs?q=a', cible: '#res', historique: 'push' });
  await e.avancer(100);
  await p;
  assert.equal(cible.hasAttribute('aria-busy'), false);
  assert.equal(e.remplacements.length, 1);
  assert.equal(e.appels[0].options.headers['X-Kairos-Partiel'], '#res');
  assert.equal(e.appels[0].options.headers['X-Requested-With'], 'XMLHttpRequest');
  assert.deepEqual(e.toasts.map((t) => t.texte), ['OK']);
  // L'entrée de départ (non marquée) l'est d'abord : Retour y revient en partiel.
  assert.equal(e.historique[0][0], 'replace');
  assert.equal(e.historique[0][2].kairosPartiel.cible, '#res');
  assert.equal(e.historique[1][0], 'push');
  assert.equal(e.historique[1][1], '/utilisateurs?q=a');
  assert.equal(e.historique[1][2].kairosPartiel.cible, '#res');
  // Le champ (hors cible) garde le focus, sans re-focus inutile.
  assert.equal(e.doc.activeElement, champ);
  assert.equal(champ.focusCount, 1);
  assert.equal(e.doc.evenements[0].type, 'kairos:fragment');
});

test('réponse lente : indicateur après 150 ms, gardé au moins 300 ms', async () => {
  const e = environnement({ reponses: [{ corps: 'x', delai: 200 }] });
  const cible = e.doc.ajouter(new e.El(e.doc, 'div', { id: 'res' }));
  const p = e.K.requete({ url: '/u', cible: '#res', historique: 'aucun' });
  await e.avancer(149);
  assert.equal(cible.getAttribute('aria-busy'), null);
  await e.avancer(2);
  assert.equal(cible.getAttribute('aria-busy'), 'true');
  assert.ok(cible.classList.contains('k-en-cours'));
  await e.avancer(100);            // réponse à 200 ms : l'indicateur reste jusqu'à 450 ms
  assert.equal(e.remplacements.length, 0);
  await e.avancer(250);
  await p;
  assert.equal(e.remplacements.length, 1);
  assert.equal(cible.getAttribute('aria-busy'), null);
  assert.ok(!cible.classList.contains('k-en-cours'));
});

test('optimiste : état immédiat, annulé sur refus 403 avec le message du serveur', async () => {
  const e = environnement({ reponses: [{ statut: 403, corps: '{"erreur":"lecture_seule","message":"Lecture seule."}' }] });
  e.doc.ajouter(new e.El(e.doc, 'div', { id: 'u-5' }));
  const bouton = new e.El(e.doc, 'button', { role: 'switch', 'aria-checked': 'true', id: 'actif-5' });
  e.doc.ajouter(bouton);
  const p = e.K.requete({ url: '/utilisateurs/5/toggle-actif', methode: 'POST', cible: '#u-5', optimiste: 'bascule', declencheur: bouton });
  assert.equal(bouton.getAttribute('aria-checked'), 'false');          // t = 0
  assert.equal(bouton.getAttribute('aria-disabled'), 'true');
  await e.avancer(10);
  await p;
  assert.equal(bouton.getAttribute('aria-checked'), 'true');           // annulé
  assert.equal(bouton.getAttribute('aria-disabled'), null);
  assert.equal(e.remplacements.length, 0);
  assert.deepEqual(e.toasts, [{ texte: 'Lecture seule.', type: 'erreur', action: null }]);
  assert.equal(e.historique.length, 0);
});

test('erreur réseau ou 5xx : toast « Réessayer » qui relance la même requête', async () => {
  const e = environnement({ reponses: [new TypeError('réseau'), { statut: 502, corps: '' }, { corps: 'ok' }] });
  e.doc.ajouter(new e.El(e.doc, 'div', { id: 'res' }));
  await e.K.requete({ url: '/u', cible: '#res', historique: 'aucun' });
  await e.avancer(5);
  assert.equal(e.toasts[0].type, 'erreur');
  assert.equal(e.toasts[0].action.libelle, 'Réessayer');
  e.toasts[0].action.surClic();
  await e.avancer(5);
  assert.equal(e.appels.length, 2);
  assert.equal(e.toasts[1].action.libelle, 'Réessayer');
  e.toasts[1].action.surClic();
  await e.avancer(5);
  assert.equal(e.remplacements.length, 1);
});

test('401 : fenêtre « Session expirée », saisie conservée ; 204 + redirection : vraie navigation', async () => {
  const e = environnement({ reponses: [{ statut: 401, corps: '{}', entetes: { 'X-Kairos-Connexion': '/connexion?next=/u' } },
                                       { statut: 204, entetes: { 'X-Kairos-Redirection': '/accueil' } }] });
  e.doc.ajouter(new e.El(e.doc, 'div', { id: 'res' }));
  let session = null;
  e.K.sessionExpiree = (url) => { session = url; };
  e.K.progressionDebut = () => {};
  const r1 = await e.K.requete({ url: '/u', methode: 'POST', cible: '#res' });
  assert.equal(r1.statut, 401);
  assert.equal(session, '/connexion?next=/u');
  assert.equal(e.remplacements.length, 0);
  const r2 = await e.K.requete({ url: '/u', methode: 'POST', cible: '#res' });
  assert.equal(r2.redirection, '/accueil');
  assert.equal(e.win.assigne, '/accueil');
});

test('requête suivante sur la même cible : la précédente est abandonnée et ignorée', async () => {
  const e = environnement({ reponses: [{ corps: 'ancienne', delai: 500 }, { corps: 'nouvelle', delai: 50 }] });
  e.doc.ajouter(new e.El(e.doc, 'div', { id: 'res' }));
  const p1 = e.K.requete({ url: '/u?q=a', cible: '#res', historique: 'replace' });
  await e.avancer(10);
  const signal1 = e.appels[0].options.signal;
  const p2 = e.K.requete({ url: '/u?q=ab', cible: '#res', historique: 'replace' });
  assert.equal(signal1.aborted, true);
  await e.avancer(600);
  await Promise.all([p1, p2]);
  assert.deepEqual(e.remplacements.map((r) => r.html), ['nouvelle']);
  assert.deepEqual(e.historique.map((h) => h[1]), ['/u?q=ab']);
});

test('focus perdu dans la cible remplacée : rendu à l’élément de même id, défilement compensé', async () => {
  const e = environnement({ reponses: [{ corps: '<div id="u-5">…</div>' }] });
  const ligne = e.doc.ajouter(new e.El(e.doc, 'div', { id: 'u-5' }));
  const bouton = e.doc.ajouter(new e.El(e.doc, 'button', { id: 'actif-5', role: 'switch', 'aria-checked': 'false' }));
  ligne.enfants.push(bouton);  // geste fait dans la ligne : position gardée
  bouton.focus();
  const nouveauBouton = new e.El(e.doc, 'button', { id: 'actif-5' });
  e.K._ajouter = [nouveauBouton];
  e.K._decalage = 37;          // du contenu au-dessus a changé de hauteur
  e.doc.retirer(bouton);       // le bouton était dans la ligne remplacée
  await e.K.requete({ url: '/x', methode: 'POST', cible: '#u-5', declencheur: bouton });
  await e.avancer(5);
  assert.equal(e.doc.activeElement, nouveauBouton);
  assert.equal(e.win.defile, 37);
  assert.ok(ligne);
});

test('focus rendu à un champ à recherche : sa liste reste fermée (data-sans-ouverture, verif-final F4)', async () => {
  const e = environnement({ reponses: [{ corps: '<div id="dl9">…</div>' }] });
  e.doc.ajouter(new e.El(e.doc, 'div', { id: 'dl9' }));
  const champ = e.doc.ajouter(new e.El(e.doc, 'input', { id: 'dl-qui-champ' }));
  champ.focus();
  const nouveau = new e.El(e.doc, 'input', { id: 'dl-qui-champ' });
  nouveau.classList.add('search-combobox-input');
  let auFocus = null;
  nouveau.focus = function () { auFocus = this.dataset.sansOuverture; this.doc.activeElement = this; };
  e.K._ajouter = [nouveau];
  e.doc.retirer(champ);        // le champ était dans la page remplacée
  await e.K.requete({ url: '/dailylog?utilisateur=3', methode: 'GET', cible: '#dl9', historique: 'aucun' });
  await e.avancer(5);
  assert.equal(e.doc.activeElement, nouveau);
  assert.equal(auFocus, '1');
  assert.equal(nouveau.dataset.sansOuverture, undefined);
});

test('geste hors de la cible, cible visible ou plus bas : la page ne défile pas', async () => {
  const e = environnement({ reponses: [{ corps: '<div id="fil">…</div>' }] });
  e.doc.ajouter(new e.El(e.doc, 'div', { id: 'fil' }));
  const bouton = e.doc.ajouter(new e.El(e.doc, 'button', { id: 'publier' }));
  e.K._decalage = 43;          // une ligne ajoutée au tableau au-dessus du fil
  await e.K.requete({ url: '/x', methode: 'POST', cible: '#fil', mode: 'avant', declencheur: bouton });
  await e.avancer(5);
  assert.ok(!e.win.defile);
});

test('422 : fragment re-rendu, focus sur le premier champ invalide', async () => {
  const e = environnement({ reponses: [{ statut: 422, corps: '<form id="f"></form>' }] });
  e.doc.ajouter(new e.El(e.doc, 'form', { id: 'f' }));
  const invalide = new e.El(e.doc, 'input', { 'aria-invalid': 'true' });
  const remplacer = e.K.remplacer;
  e.K.remplacer = (c, h, m) => { const r = remplacer(c, h, m); r.racine.enfants.push(invalide); return r; };
  const r = await e.K.requete({ url: '/f', methode: 'POST', cible: '#f' });
  await e.avancer(5);
  assert.equal(r.statut, 422);
  assert.equal(e.doc.activeElement, invalide);
});

test('cible absente : un GET devient une vraie navigation', async () => {
  const e = environnement({ reponses: [] });
  await e.K.requete({ url: '/projets?page=2', cible: '#nulle-part' });
  assert.equal(e.win.assigne, '/projets?page=2');
  assert.equal(e.appels.length, 0);
});

test('action d’un toast (« Annuler ») rejouée en POST partiel vers la bonne cible', async () => {
  const e = environnement({ reponses: [{ corps: '<div id="u-5"></div>' }] });
  e.doc.ajouter(new e.El(e.doc, 'div', { id: 'u-5' }));
  e.win.FormData = class { constructor() { this.v = []; } append(k, v) { this.v.push([k, v]); } };
  await e.K.rejouerAction({ libelle: 'Annuler', url: '/utilisateurs/5/toggle-actif', methode: 'POST',
                            donnees: { actif_cible: '1', annulation: '1' }, cible: '#u-5', focus: '#actif-5' });
  await e.avancer(5);
  assert.equal(e.appels[0].options.method, 'POST');
  assert.deepEqual(e.appels[0].options.body.v, [['actif_cible', '1'], ['annulation', '1']]);
  assert.equal(e.appels[0].options.headers['X-Kairos-Partiel'], '#u-5');
  assert.equal(e.remplacements.length, 1);
});

test('422 en JSON {champs} : saisie gardée, champs signalés, pas de remplacement (lot 13, a11y I5)', async () => {
  const e = environnement({ reponses: [{ statut: 422, corps: '{"erreur":"invalide","message":"Titre obligatoire.","champs":{"titre":"Titre obligatoire."}}',
                                         entetes: { 'Content-Type': 'application/json' } }] });
  e.doc.ajouter(new e.El(e.doc, 'div', { id: 'fil' }));
  const form = new e.El(e.doc, 'form', { id: 'f' });
  const bouton = new e.El(e.doc, 'button', { id: 'publier' });
  bouton.form = form;
  let marques = null;
  e.K.marquerErreurs = (f, champs) => { marques = { f, champs }; return 1; };
  const r = await e.K.requete({ url: '/projets/1/taches', methode: 'POST', cible: '#fil', mode: 'avant', declencheur: bouton });
  await e.avancer(5);
  assert.equal(r.statut, 422);
  assert.deepEqual(r.donnees.champs, { titre: 'Titre obligatoire.' });
  assert.equal(e.remplacements.length, 0);
  assert.equal(marques.f, form);
  assert.deepEqual(marques.champs, { titre: 'Titre obligatoire.' });
  assert.equal(e.toasts.length, 0);                 // message sous le champ, pas en double
  assert.equal(bouton.getAttribute('aria-disabled'), null);
});

test('2xx en JSON : données rendues à l’appelant, rien de remplacé', async () => {
  const e = environnement({ reponses: [{ corps: '{"nb":2}', entetes: { 'Content-Type': 'application/json' } }] });
  e.doc.ajouter(new e.El(e.doc, 'div', { id: 'res' }));
  const r = await e.K.requete({ url: '/posts/1/reagir', methode: 'POST', cible: '#res' });
  await e.avancer(5);
  assert.deepEqual(r.donnees, { nb: 2 });
  assert.equal(e.remplacements.length, 0);
});

test('pagination (defiler: haut) : le haut de la liste revient à l’écran au lieu de compenser', async () => {
  const e = environnement({ reponses: [{ corps: '<div id="res"></div>' }] });
  e.doc.ajouter(new e.El(e.doc, 'div', { id: 'res' }));
  const remplacer = e.K.remplacer;
  let vu = 0;
  e.K.remplacer = (c, h, m) => { const r = remplacer(c, h, m); r.racine.top = -900; r.racine.scrollIntoView = () => { vu++; }; return r; };
  await e.K.requete({ url: '/projets?page=2', cible: '#res', defiler: 'haut' });
  await e.avancer(5);
  assert.equal(vu, 1);
  assert.equal(e.win.defile, undefined);
});

// --- Lot 13, correctifs (contre-expertise UX N6, a11y R2 / N4) ---------------

test('cible dans une <dialog> : la page derrière ne défile jamais (UX N6)', async () => {
  const e = environnement({ reponses: [{ corps: '<form id="infos"></form>' }] });
  const cible = e.doc.ajouter(new e.El(e.doc, 'form', { id: 'infos' }));
  cible.closest = (sel) => (sel === 'dialog' ? { tagName: 'DIALOG' } : null);
  const bouton = e.doc.ajouter(new e.El(e.doc, 'button', { id: 'enregistrer' }));
  cible.enfants.push(bouton);  // geste fait dans la cible : d'ordinaire, position gardée
  e.K._decalage = 196;         // la fenêtre recentrée « bouge »
  await e.K.requete({ url: '/x', methode: 'POST', cible: '#infos', declencheur: bouton });
  await e.avancer(5);
  assert.ok(!e.win.defile);
});

function regions(e) {
  const r = { annonce: { id: 'k-annonce', textContent: 'ancien' }, alerte: { id: 'k-alerte', textContent: '' } };
  const avant = e.doc.getElementById.bind(e.doc);
  e.doc.getElementById = (id) => (id === 'k-annonce' ? r.annonce : id === 'k-alerte' ? r.alerte : avant(id));
  return r;
}

test('Kairos.annoncer : région persistante vidée puis remplie, rafale lue ensemble, urgent en alerte (a11y R2)', async () => {
  const e = environnement({ reponses: [] });
  const r = regions(e);
  e.K.annoncer('Journée enregistrée.');
  e.K.annoncer('Total 8 h.');
  assert.equal(r.annonce.textContent, '', 'vidée d’abord : un texte répété est relu');
  await e.avancer(30);
  assert.equal(r.annonce.textContent, 'Journée enregistrée. Total 8 h.');
  e.K.annoncer('Connexion impossible.', { urgent: true });
  await e.avancer(30);
  assert.equal(r.alerte.textContent, 'Connexion impossible.');
  assert.equal(r.annonce.textContent, 'Journée enregistrée. Total 8 h.');
  await e.avancer(10000);
  assert.equal(r.annonce.textContent, '', 'rien de périmé ensuite');
  e.K.annoncer('   ');
  await e.avancer(30);
  assert.equal(r.annonce.textContent, '');
});

test('texte annoncé d’un toast : « Annuler » indique Ctrl+Z, autre action nommée (a11y N4)', () => {
  const { K } = environnement({ reponses: [] });
  assert.equal(K.texteAnnonce('Compte désactivé.', { libelle: 'Annuler' }), 'Compte désactivé. « Annuler » : Ctrl+Z.');
  assert.equal(K.texteAnnonce('Connexion impossible.', { libelle: 'Réessayer' }), 'Connexion impossible. Bouton « Réessayer » dans le message.');
  assert.equal(K.texteAnnonce('Enregistré.'), 'Enregistré.');
});

test('Ctrl+Z : « Annuler » du toast le plus récent encore affiché (a11y N4)', () => {
  const e = environnement({ reponses: [] });
  const clics = [];
  const bouton = (texte, attrs = {}) => ({ textContent: texte, hasAttribute: (n) => n in attrs, click: () => clics.push(texte) });
  const toast = (...b) => ({ querySelectorAll: () => b });
  const zone = { id: 'k-toasts', querySelectorAll: () => [toast(bouton('Annuler', { 'data-k-annuler': '' })), toast(bouton('Réessayer')), toast(bouton('Annuler l’absence'))] };
  e.doc.ajouter(zone);
  assert.equal(e.K.annulerDernier(), true);
  assert.deepEqual(clics, ['Annuler l’absence']);
  e.doc.retirer(zone);
  e.doc.ajouter({ id: 'k-toasts', querySelectorAll: () => [toast(bouton('Réessayer'))] });
  assert.equal(e.K.annulerDernier(), false);
});

// Lot 13, correctifs (verif-ux N3) — bandeau des modes (app/static/js/bandeau-admin.js) :
// seule une ouverture ou une fermeture faite par l'Admin est mémorisée
// (jamais l'évènement « toggle » d'un <details open> analysé ni la
// fermeture d'office) ; repliés par défaut sous 1 280 px ; une préférence
// par largeur (écran large / étroit). DOM minimal fait main, script joué
// dans un contexte vm.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const SOURCE = readFileSync(new URL('../app/static/js/bandeau-admin.js', import.meta.url), 'utf8');

function cible() {
  const ecouteurs = {};
  return {
    ecouteurs,
    addEventListener(type, fn) { (ecouteurs[type] = ecouteurs[type] || []).push(fn); },
    emettre(type, ev = {}) { (ecouteurs[type] || []).forEach((fn) => fn({ target: this, ...ev })); },
  };
}

function charger({ largeur, stockage = {} }) {
  const resume = cible();
  const outils = Object.assign(cible(), { open: true, querySelector: (s) => (s === 'summary' ? resume : null) });
  const magasin = { ...stockage };
  const env = {
    largeur,
    document: {
      readyState: 'complete',
      querySelector: (s) => (s === '[data-bandeau-outils]' ? outils : null),
      getElementById: () => null,
    },
    localStorage: { getItem: (k) => (k in magasin ? magasin[k] : null), setItem: (k, v) => { magasin[k] = String(v); } },
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  };
  env.window = {
    matchMedia: (q) => ({ matches: /min-width: 1280px/.test(q) ? env.largeur >= 1280 : false }),
    location: { pathname: '/accueil', search: '' },
    addEventListener() {},
  };
  vm.runInNewContext(SOURCE, { ...env, URL });
  return { outils, resume, magasin, env };
}

test('aucun geste : le toggle initial (details open analysé) n’est pas mémorisé', () => {
  const { outils, magasin } = charger({ largeur: 1440 });
  assert.equal(outils.open, true);
  outils.emettre('toggle');
  assert.deepEqual(magasin, {});
});

test('sous 1 280 px : replié par défaut, la fermeture d’office n’est pas mémorisée', () => {
  const { outils, magasin } = charger({ largeur: 375 });
  assert.equal(outils.open, false);
  outils.emettre('toggle');
  assert.deepEqual(magasin, {});
});

test('un geste est mémorisé pour la largeur où il a été fait', () => {
  const b = charger({ largeur: 375 });
  b.resume.emettre('click');
  b.env.largeur = 1440;          // fenêtre agrandie avant l'évènement « toggle »
  b.outils.open = true;
  b.outils.emettre('toggle');
  assert.deepEqual(b.magasin, { 'kairos-bandeau-outils-etroit': 'ouvert' });
  // Sur un écran large, la préférence de l'écran étroit est sans effet.
  assert.equal(charger({ largeur: 1440, stockage: { 'kairos-bandeau-outils-etroit': 'replie' } }).outils.open, true);
  assert.equal(charger({ largeur: 375, stockage: { 'kairos-bandeau-outils-etroit': 'ouvert' } }).outils.open, true);
  assert.equal(charger({ largeur: 1440, stockage: { 'kairos-bandeau-outils-large': 'replie' } }).outils.open, false);
});

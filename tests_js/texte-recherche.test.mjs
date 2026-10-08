// Intégration lot 11 — app/static/js/texte-recherche.js : mêmes règles que
// fn_recherche() (lower(unaccent(...)), migration 0016) pour les filtres
// faits dans la page (sélecteur d'intervenant, puces, Daily log). Valeurs
// attendues relevées sur PostgreSQL 16 ; la comparaison directe avec la
// base est faite par tests_integration/test_lot11_integration.py.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const kt = require('../app/static/js/texte-recherche.js');
const dl = require('../app/static/js/dailylog.js');

const ATTENDU = {
  'Hélène Chérif': 'helene cherif',
  'ÉCOLE Ça': 'ecole ca',
  'Œuvre Æther': 'oeuvre aether',
  'Straße Łódź Ørsted': 'strasse lodz orsted',
  'l’équipe « x »': "l'equipe << x >>",
  'R+2 – voile — B': 'r+2 - voile - b',
  'Naïve façade': 'naive facade',
};

test('sansAccents : comme fn_recherche (unaccent)', () => {
  for (const [entree, attendu] of Object.entries(ATTENDU)) {
    assert.equal(kt.sansAccents(entree), attendu, entree);
    assert.equal(dl.norm(entree), attendu, 'dailylog.norm : ' + entree);
  }
  assert.equal(kt.sansAccents(null), '');
  assert.equal(kt.sansAccents(undefined), '');
});

test('contientTousLesMots : mots dans le désordre, sans accents', () => {
  assert.ok(kt.contientTousLesMots('Sami Chérif', 'cherif sami'));
  assert.ok(kt.contientTousLesMots('Hélène Ben Œil', '  helene   oeil '));
  assert.ok(kt.contientTousLesMots('Hélène', ''));
  assert.ok(!kt.contientTousLesMots('Sami Chérif', 'cherif helene'));
});

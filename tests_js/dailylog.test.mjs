// Daily log v9 (lot 10) — noyau pur de app/static/js/dailylog.js :
// formatage, saisie libre, grille de 30 min, dates ISO. Lancé par la CI
// (job « scripts ») : node --test tests_js/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const dl = require('../app/static/js/dailylog.js');

test('fmt : heures et minutes à la française', () => {
  assert.equal(dl.fmt(0), '0 h');
  assert.equal(dl.fmt(-30), '0 h');
  assert.equal(dl.fmt(30), '30 min');
  assert.equal(dl.fmt(45), '45 min');
  assert.equal(dl.fmt(60), '1 h');
  assert.equal(dl.fmt(135), '2 h 15');
  assert.equal(dl.fmt(150), '2 h 30');
  assert.equal(dl.fmt(600), '10 h');
  assert.equal(dl.fmt(160), '2 h 40');          // ancienne valeur Chronos (2,67 h)
  assert.equal(dl.fmt(90, { h: 'h', min: 'mn' }), '1 h 30');
});

test('parse : 2,5 · 2.5h · 2h30 · 2h30min · 2:30 · 45min · 90 min · nombre nu = heures', () => {
  const cas = { '2,5': 150, '2.5': 150, '2.5h': 150, '2h30': 150, '2h30min': 150, '2 h 30': 150, '2:30': 150,
                '45min': 45, '90 min': 90, '8': 480, ',5': 30, '0': 0, '': 0, '  3h ': 180, '2H05': 125 };
  for (const [entree, attendu] of Object.entries(cas)) assert.equal(dl.parse(entree), attendu, entree);
  for (const illisible of ['abc', '2h75', '1:60', '-1', '2,5,5', '²', '1e2', '½']) assert.ok(Number.isNaN(dl.parse(illisible)), illisible);
  assert.ok(dl.estNombreNu('12'));
  assert.ok(dl.estNombreNu('2,5'));
  assert.ok(!dl.estNombreNu('12min'));
});

test('grille : arrondi au plus proche, −/+ dans le sens du bouton (2 h 15 → 2 h / 2 h 30)', () => {
  assert.equal(dl.q(135), 150);
  assert.equal(dl.q(134), 120);
  assert.equal(dl.versLeBas(135), 120);
  assert.equal(dl.versLeHaut(135), 150);
  assert.equal(dl.versLeBas(120), 90);
  assert.equal(dl.versLeHaut(120), 150);
  assert.equal(dl.versLeBas(30), 0);
  assert.equal(dl.versLeBas(0), 0);
  assert.equal(dl.versLeHaut(0), 30);
  assert.equal(dl.versLeHaut(160), 180);
  assert.equal(dl.surGrille(20), 30);
  assert.equal(dl.surGrille(135), 150);
});

test('surGrilleEtPlafond : copie et annulation d’absence sur la grille, 10 h au plus', () => {
  const r = dl.surGrilleEtPlafond([{ projet_id: 1, minutes: 135 }, { projet_id: 2, minutes: 420 }, { projet_id: 3, minutes: 60 }], 600);
  assert.deepEqual(r.lignes.map((l) => l.minutes), [150, 420, 30]);
  assert.equal(r.modifiees, true);
  const net = dl.surGrilleEtPlafond([{ projet_id: 1, minutes: 240 }], 600);
  assert.equal(net.modifiees, false);
  const plein = dl.surGrilleEtPlafond([{ projet_id: 1, minutes: 600 }, { projet_id: 2, minutes: 60 }], 600);
  assert.deepEqual(plein.lignes.map((l) => l.minutes), [600]);
});

test('dates : jours ouvrés (les flèches sautent le week-end), mois voisins', () => {
  assert.equal(dl.jourSemaine('2026-10-05'), 0);       // lundi
  assert.equal(dl.jourSemaine('2026-10-04'), 6);       // dimanche
  assert.equal(dl.jourOuvre('2026-10-05', -1), '2026-10-02');
  assert.equal(dl.jourOuvre('2026-10-02', 1), '2026-10-05');
  assert.equal(dl.jourOuvre('2026-10-03', 1), '2026-10-05');
  assert.equal(dl.ajouterJours('2026-03-28', 2), '2026-03-30');   // changement d'heure : sans effet
  assert.equal(dl.ajouterMois('2026-01', -1), '2025-12');
  assert.equal(dl.ajouterMois('2026-12', 1), '2027-01');
  assert.ok(dl.estWeekEnd('2026-10-03'));
  assert.ok(!dl.estWeekEnd('2026-10-02'));
});

test('recherche sans accents (comme fn_recherche, lot 11 : unaccent)', () => {
  assert.equal(dl.norm('Résidence ÉTÉ'), 'residence ete');
  assert.equal(dl.norm('Œuvre Ça'), 'oeuvre ca');
  assert.equal(dl.cle(3, null), '3:0');
  assert.equal(dl.cle(3, 7), '3:7');
  assert.match(dl.couleur('26069D'), /^#[0-9a-f]{6}$/);
});

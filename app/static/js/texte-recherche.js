/* Recherche sans accents ni casse côté navigateur (intégration lot 11).
 *
 * Mêmes règles que fn_recherche() côté serveur (migration 0016 :
 * lower(unaccent(...))) pour que les filtres faits dans la page — sélecteur
 * d'intervenant de la fiche projet (search-combobox.js), puces de la
 * fenêtre « Nouvelle tâche » et des filtres (chip-select.js), catalogue du
 * Daily log (dailylog.js) — trouvent la même chose que la recherche du
 * serveur : « helene » → « Hélène », « oeuvre » → « Œuvre », apostrophe
 * typographique ’ = apostrophe droite ', tirets – — = trait d'union.
 * La correspondance est vérifiée contre la vraie fonction PostgreSQL par
 * tests_integration/test_lot11_integration.py.
 *
 * Exporté pour les tests node (tests_js/) ; dans la page :
 * window.KairosTexte.{sansAccents, contientTousLesMots}. */
(function (racine, fabrique) {
  var noyau = fabrique();
  if (typeof module === 'object' && module.exports) module.exports = noyau;
  else racine.KairosTexte = noyau;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Lettres que la décomposition NFD ne sépare pas de leur « accent »
  // (règles du dictionnaire unaccent de PostgreSQL).
  var SPECIAUX = {
    '\u0153': 'oe', '\u0152': 'oe', '\u00e6': 'ae', '\u00c6': 'ae', '\u00df': 'ss', '\u00f8': 'o', '\u00d8': 'o',
    '\u0142': 'l', '\u0141': 'l', '\u0111': 'd', '\u0110': 'd', '\u00f0': 'd', '\u00d0': 'd', '\u00fe': 'th', '\u00de': 'th',
    '\u0131': 'i', '\u0138': 'q', '\u0140': 'l', '\u013f': 'l', '\u0149': "'n",
    '\u2018': "'", '\u2019': "'", '\u201a': ',', '\u201b': "'", '\u02bc': "'", '\u2032': "'",
    '\u201c': '"', '\u201d': '"', '\u201e': ',,',
    '\u2010': '-', '\u2011': '-', '\u2012': '-', '\u2013': '-', '\u2014': '-', '\u2015': '-',
    '\u00ab': '<<', '\u00bb': '>>', '\u00a0': ' ', '\u202f': ' '
  };
  var MOTIF_SPECIAUX = new RegExp('[' + Object.keys(SPECIAUX).join('') + ']', 'g');

  /** Texte sans accents ni casse, comme fn_recherche(). */
  function sansAccents(texte) {
    return String(texte == null ? '' : texte)
      .replace(MOTIF_SPECIAUX, function (c) { return SPECIAUX[c]; })
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .toLowerCase();
  }

  /** Vrai si chaque mot de `requete` figure dans `texte` (dans n'importe
   *  quel ordre : « cherif sami » trouve « Sami Chérif »). */
  function contientTousLesMots(texte, requete) {
    var t = sansAccents(texte);
    var mots = sansAccents(requete).trim().split(/\s+/).filter(Boolean);
    return mots.every(function (mot) { return t.indexOf(mot) !== -1; });
  }

  return { sansAccents: sansAccents, contientTousLesMots: contientTousLesMots };
});

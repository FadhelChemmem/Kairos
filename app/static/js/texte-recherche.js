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
    'œ': 'oe', 'Œ': 'oe', 'æ': 'ae', 'Æ': 'ae', 'ß': 'ss', 'ø': 'o', 'Ø': 'o',
    'ł': 'l', 'Ł': 'l', 'đ': 'd', 'Đ': 'd', 'ð': 'd', 'Ð': 'd', 'þ': 'th', 'Þ': 'th',
    'ı': 'i', 'ĸ': 'q', 'ŀ': 'l', 'Ŀ': 'l', 'ŉ': "'n",
    '‘': "'", '’': "'", '‚': ',', '‛': "'", 'ʼ': "'", '′': "'",
    '“': '"', '”': '"', '„': ',,',
    '‐': '-', '‑': '-', '‒': '-', '–': '-', '—': '-', '―': '-',
    '«': '<<', '»': '>>', ' ': ' ', ' ': ' '
  };
  var MOTIF_SPECIAUX = new RegExp('[' + Object.keys(SPECIAUX).join('') + ']', 'g');

  /** Texte sans accents ni casse, comme fn_recherche(). */
  function sansAccents(texte) {
    return String(texte == null ? '' : texte)
      .replace(MOTIF_SPECIAUX, function (c) { return SPECIAUX[c]; })
      .normalize('NFD').replace(/[̀-ͯ]/g, '')
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

// Bandeau des modes de l'Admin (lot 13, audit UX M14) : les outils du mode
// test (date simulée, rappel) se replient.
//
// Correctifs du lot 13 (verif-ux N3, verif-temps) :
// - seul un geste de l'Admin (clic ou clavier sur « Mode test ») est
//   mémorisé — jamais l'évènement « toggle » que le navigateur émet pour un
//   <details open> analysé, ni la fermeture d'office ;
// - deux préférences : écran large (≥ 1 280 px, ouvert par défaut) et écran
//   étroit (replié par défaut) : un choix fait sur ordinateur ne déplie
//   plus les outils sur téléphone, et inversement ;
// - date simulée « Appliquer » / « Revenir à aujourd'hui » : la page est
//   rechargée (toute la page dépend de la date : contenus, retards, Daily
//   log, empreinte du mode), la barre de progression part au clic
//   (kairos-partiel.js), le toast arrive avec la page et le focus revient
//   au champ de date (le bandeau est en haut de page : pas de défilement à
//   rendre).
(function () {
  var outils = document.querySelector('[data-bandeau-outils]');
  var LARGE = '(min-width: 1280px)';
  function cle() {
    var large = !!(window.matchMedia && window.matchMedia(LARGE).matches);
    return 'kairos-bandeau-outils-' + (large ? 'large' : 'etroit');
  }
  function lire(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function ecrire(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* préférence non gardée */ } }

  if (outils) {
    var k = cle();
    var pref = lire(k);
    var ouvert = pref ? pref === 'ouvert' : /large$/.test(k);
    if (outils.open !== ouvert) outils.open = ouvert;
    // État posé : la marque de kairos-amorce.js (repli avant le premier
    // rendu) n'a plus lieu d'être.
    var racineDoc = document.documentElement;
    if (racineDoc && racineDoc.dataset) delete racineDoc.dataset.kOutilsReplies;
    // Clé lue au moment du geste (l'évènement « toggle » arrive après coup).
    var geste = null;
    var resume = outils.querySelector('summary');
    if (resume) resume.addEventListener('click', function () { geste = cle(); });
    outils.addEventListener('toggle', function () {
      if (!geste) return;
      ecrire(geste, outils.open ? 'ouvert' : 'replie');
      geste = null;
    });
  }

  // Focus rendu après le rechargement de la date simulée.
  var CLE_RETOUR = 'kairos-bandeau-retour';
  var bandeau = document.getElementById('bandeau-admin');
  if (!bandeau) return;
  function ici() { return window.location.pathname + window.location.search; }
  bandeau.addEventListener('submit', function (e) {
    var form = e.target;
    var chemin = '';
    try { chemin = new URL(form.action, window.location.href).pathname; } catch (x) { return; }
    if (!/\/admin\/date-simulee(\/effacer)?$/.test(chemin)) return;
    try {
      sessionStorage.setItem(CLE_RETOUR, JSON.stringify({ url: ici() }));
    } catch (x) { /* rien */ }
  });
  var retour = null;
  try {
    retour = JSON.parse(sessionStorage.getItem(CLE_RETOUR) || 'null');
    sessionStorage.removeItem(CLE_RETOUR);
  } catch (x) { retour = null; }
  if (!retour || retour.url !== ici()) return;
  function rendre() {
    var el = document.getElementById('bandeau-date-simulee');
    // Outils repliés : le focus va sur « Mode test » (le champ est caché).
    if ((!el || !el.offsetParent) && outils) el = outils.querySelector('summary');
    if (el && el.focus) el.focus({ preventScroll: true });
  }
  if (document.readyState === 'complete') rendre();
  else window.addEventListener('load', rendre);
})();

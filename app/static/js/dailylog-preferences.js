// Réglage « Proposer mes tâches en cours dans le Daily log » (lot 14,
// revue produit P0-4) : activé par défaut, préférence de ce navigateur
// (comme les raccourcis d'une touche), lue par dailylog.js. Clé par
// personne : kairos-dl-proposer-<id> = « non » quand c'est désactivé.
(function () {
  'use strict';
  var ATTR = 'data-pref-dl-proposer';
  function cle(el) { return 'kairos-dl-proposer-' + el.getAttribute(ATTR); }
  function lire(el) {
    try { return localStorage.getItem(cle(el)) !== 'non'; } catch (e) { return true; }
  }
  function init(racine) {
    var lecture = document.documentElement.hasAttribute('data-lecture-seule');
    (racine && racine.querySelectorAll ? racine : document).querySelectorAll('[' + ATTR + ']').forEach(function (c) {
      c.checked = lire(c);
      if (lecture) c.disabled = true;
    });
  }
  document.addEventListener('change', function (e) {
    var c = e.target;
    if (!c || !c.hasAttribute || !c.hasAttribute(ATTR)) return;
    var K = window.Kairos, ok = true;
    try { localStorage.setItem(cle(c), c.checked ? 'oui' : 'non'); } catch (err) { ok = false; }
    if (!K || !K.toast) return;
    if (!ok) K.toast('Réglage non mémorisé : le stockage de ce navigateur est indisponible.', { type: 'avertissement' });
    else K.toast(c.checked ? 'Vos tâches en cours seront proposées dans le Daily log.' : 'Vos tâches en cours ne seront plus proposées dans le Daily log.', { type: 'succes' });
  });
  document.addEventListener('kairos:fragment', function (e) { init(e.detail && e.detail.racine); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { init(); });
  else init();
})();

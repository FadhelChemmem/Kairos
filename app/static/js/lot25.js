// Lot 25 — demandes du gérant du 23/10/2026.
//  - Fiche projet : la ligne du haut ramène à la liste (« ← Retour aux
//    projets ») ; le nom du projet n'y apparaît que lorsque l'en-tête de la
//    fiche (où il est écrit) a défilé hors de l'écran.
(function () {
  'use strict';
  if (!('IntersectionObserver' in window)) return;
  var entete = null, cache = true, obs = null;
  function appliquer() {
    var nom = document.querySelector('[data-subbar-nom]');
    if (!nom) return;
    nom.classList.toggle('subbar-nom-cache', cache);
    nom.setAttribute('aria-hidden', cache ? 'true' : 'false');
  }
  function observer() {
    var nouveau = document.getElementById('projet-entete');
    if (!nouveau || !document.querySelector('[data-subbar-nom]')) return;
    if (!obs) {
      obs = new IntersectionObserver(function (entrees) {
        entrees.forEach(function (e) { cache = e.isIntersecting; });
        appliquer();
      }, { rootMargin: '-60px 0px 0px 0px' });
    }
    if (nouveau !== entete) {
      if (entete) obs.unobserve(entete);
      entete = nouveau;
      obs.observe(entete);
    }
    appliquer();
  }
  observer();
  document.addEventListener('kairos:fragment', observer);
})();

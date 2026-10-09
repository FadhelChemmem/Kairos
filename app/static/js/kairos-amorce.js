// Amorce (lot 13 : sortie du <head> de base.html, CSP sans 'unsafe-inline').
// Chargé SANS defer en tête de page : s'exécute avant le premier rendu.
//
// 1. Thème clair/sombre (demande Fadhel, 2026-09-27) appliqué avant tout
//    rendu (pas de flash du mauvais thème). Mémorisé par navigateur dans
//    localStorage ; à défaut, suit la préférence système, lue HORS du try
//    (lot 10, audit front M4) ; tant qu'aucun choix n'est mémorisé, un
//    changement de thème du système est suivi en direct.
// 2. Protection CSRF (PROMPT_CORRECTIONS.md P2 #25) : tout fetch() qui écrit
//    (POST/PUT/PATCH/DELETE) vers l'appli reçoit l'en-tête X-CSRFToken.
// 3. Classe « k-js » sur <html> : les éléments réservés au repli sans
//    JavaScript (.k-sans-js, ex. bouton « Filtrer ») sont masqués.
(function () {
  var racine = document.documentElement;
  racine.classList.add('k-js');

  var enregistre = null;
  try { enregistre = localStorage.getItem('kairos-theme'); } catch (e) { /* stockage indisponible */ }
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  racine.dataset.theme = enregistre || (mq && mq.matches ? 'dark' : 'light');
  if (mq && !enregistre && mq.addEventListener) {
    mq.addEventListener('change', function (e) {
      if (window.kairosThemeChoisi) return;
      racine.dataset.theme = e.matches ? 'dark' : 'light';
      var b = document.getElementById('theme-toggle');
      if (b) b.setAttribute('aria-pressed', e.matches ? 'true' : 'false');
    });
  }

  var meta = document.querySelector('meta[name="csrf-token"]');
  var jeton = meta ? meta.content : '';
  var fetchOrigine = window.fetch;
  if (!fetchOrigine) return;
  window.fetch = function (ressource, options) {
    options = options || {};
    var methode = (options.method || (ressource && ressource.method) || 'GET').toUpperCase();
    // Request -> son .url ; chaîne ou objet URL -> String(...) (audit n°2 :
    // avec un objet URL, le jeton partait vers n'importe quel site). Une URL
    // invalide laisse le fetch d'origine renvoyer sa promesse rejetée.
    var url;
    try {
      url = new URL(ressource instanceof Request ? ressource.url : String(ressource), window.location.href);
    } catch (e) {
      return fetchOrigine.call(this, ressource, options);
    }
    if (['GET', 'HEAD', 'OPTIONS', 'TRACE'].indexOf(methode) === -1 && url.origin === window.location.origin) {
      var entetes = new Headers(options.headers || (ressource && ressource.headers) || {});
      if (!entetes.has('X-CSRFToken')) entetes.set('X-CSRFToken', jeton);
      options = Object.assign({}, options, { headers: entetes });
    }
    return fetchOrigine.call(this, ressource, options);
  };
})();

// Accueil (lot 14) : tuiles de la Vue d'ensemble (Admin), lignes de la
// carte « À traiter » (chef de projet) et bascule « Les miennes | Toutes ».
// Les liens marchent sans JavaScript (GET de /accueil) ; avec, ils passent
// par le socle partiel (data-partiel) :
// - le lien garde les autres réglages de l'adresse courante (liste
//   dépliée, mode des tâches) : seul son paramètre change ;
// - état appliqué au clic (optimistes « deplier » et « courant »), annulé
//   si la réponse échoue ; la liste dépliée ou repliée est annoncée.
(function () {
  var K = window.Kairos;
  if (!K || !K.optimistes) return;

  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[data-tableau-param]');
    if (!a || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    try {
      var adresse = new URL(window.location.href);
      var param = a.getAttribute('data-tableau-param');
      var valeur = new URL(a.getAttribute('href'), window.location.href).searchParams.get(param);
      if (valeur) adresse.searchParams.set(param, valeur); else adresse.searchParams.delete(param);
      a.setAttribute('href', adresse.pathname + adresse.search);
    } catch (x) { /* lien inchangé */ }
  }, true);

  function memoriser(liens, attr) {
    var avant = liens.map(function (l) { return l.getAttribute(attr); });
    return function () {
      liens.forEach(function (l, i) {
        if (!document.contains(l)) return;
        if (avant[i] === null) l.removeAttribute(attr); else l.setAttribute(attr, avant[i]);
      });
    };
  }

  // Tuile ou ligne : elle se déplie (les autres se replient), ou se replie.
  K.optimistes.deplier = function (el) {
    var groupe = el.closest('.ve-tuiles, .at-lignes');
    var liens = groupe ? Array.prototype.slice.call(groupe.querySelectorAll('[aria-expanded]')) : [el];
    var annuler = memoriser(liens, 'aria-expanded');
    var ouvrir = el.getAttribute('aria-expanded') !== 'true';
    liens.forEach(function (l) { l.setAttribute('aria-expanded', l === el && ouvrir ? 'true' : 'false'); });
    return annuler;
  };

  // Contrôle segmenté : le segment cliqué devient le courant.
  K.optimistes.courant = function (el) {
    var liens = Array.prototype.slice.call(el.parentNode.children);
    var annuler = memoriser(liens, 'aria-current');
    liens.forEach(function (l) { if (l === el) l.setAttribute('aria-current', 'page'); else l.removeAttribute('aria-current'); });
    return annuler;
  };

  function synchroniserBascule(racine) {
    var mode = racine.getAttribute('data-mode');
    document.querySelectorAll('[data-tdp-bascule] > a').forEach(function (a) {
      var v = a.getAttribute('data-tableau-valeur') || 'toutes';
      if (v === mode) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
  }

  document.addEventListener('kairos:fragment', function (e) {
    var r = e.detail && e.detail.racine;
    if (!r || !r.id) return;
    if (r.id === 'accueil-taches') { synchroniserBascule(r); return; }
    if (r.id !== 'vue-ensemble' && r.id !== 'a-traiter') return;
    var titre = r.querySelector('.tb-detail-titre');
    if (titre) {
      var libelle = titre.querySelector('.tb-detail-libelle');
      var nombre = titre.querySelector('.tb-detail-nombre');
      K.annoncer((libelle ? libelle.textContent.trim() : '') + ' : ' + (nombre ? nombre.textContent.trim() : '0') + ', liste dépliée.');
    } else {
      K.annoncer('Liste repliée.');
    }
  });
})();

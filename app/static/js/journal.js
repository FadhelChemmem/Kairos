// Journal d'audit (lot 13, audit a11y I10 et UX §2.7) :
//  - « Voir les données » : les données avant / après d'une entrée sont
//    chargées au premier dépliage (fragment en différences lisibles), au
//    lieu d'être rendues pour chaque ligne (545 Ko de page avant) ;
//  - « Réinitialiser » visible seulement quand un filtre est actif.
// Filtres et « Charger 100 de plus » : kairos-partiel.js (data-partiel).
(function () {
  var K = window.Kairos;

  document.addEventListener('toggle', function (e) {
    var d = e.target;
    if (!d || !d.classList || !d.classList.contains('journal-details') || !d.open || d.dataset.charge) return;
    if (!K || !K.requete) return;
    d.dataset.charge = '1';
    var cible = d.getAttribute('data-cible');
    K.requete({ url: d.getAttribute('data-url'), methode: 'GET', cible: cible, mode: 'inner', historique: 'aucun', transition: false })
      .then(function (res) { if (!res || res.statut >= 300 || res.statut === 0) delete d.dataset.charge; });
  }, true);

  function majReinit() {
    var lien = document.querySelector('.journal-reinit');
    if (!lien) return;
    var params = new URLSearchParams(window.location.search);
    lien.hidden = !['table', 'action', 'utilisateur_id', 'date_debut', 'date_fin'].some(function (k) { return params.get(k); });
  }
  document.addEventListener('kairos:fragment', majReinit);
  window.addEventListener('popstate', function () { setTimeout(majReinit, 0); });
})();

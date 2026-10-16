// Réglage « Proposer mes tâches en cours dans le Daily log » (lot 14,
// revue produit P0-4) : réglage du compte depuis le lot 15
// (utilisateur_preference, POST /preferences), lu par le Daily log.
(function () {
  'use strict';
  document.addEventListener('change', function (e) {
    var c = e.target;
    if (!c || !c.hasAttribute || !c.hasAttribute('data-pref-dl-proposer')) return;
    var K = window.Kairos;
    if (!K || !K.enregistrerPreference || (K.lectureSeuleUI && K.lectureSeuleUI())) return;
    K.enregistrerPreference(c.getAttribute('data-preference-url'), 'dailylog_proposer', c.checked).then(function (r) {
      if (!K.toast) return;
      if (!r || !r.ok) K.toast('Réglage non enregistré\u00a0: réessayez.', { type: 'avertissement' });
      else K.toast(c.checked ? 'Vos tâches en cours seront proposées dans le Daily log.' : 'Vos tâches en cours ne seront plus proposées dans le Daily log.', { type: 'succes' });
    });
  });
})();

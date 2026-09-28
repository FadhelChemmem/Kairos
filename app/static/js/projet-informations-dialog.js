// Fenêtre flottante "Informations" du projet (retour Fadhel, 2026-09-28,
// Lot 5) — voir partials/projet_informations_dialog.html. Même principe
// d'ouverture/fermeture que projet-dialog.js/post-dialog.js : un seul
// formulaire, ouvert par [data-open-informations-dialog].
//
// Ne réutilise PAS floating-window.js/attacherFermetureAuFond : cette
// règle commune considère qu'un champ texte non vide = saisie à protéger,
// ce qui est vrai pour "Nouveau post"/"Nouveau projet" (vides au départ)
// mais faux ici — le formulaire est TOUJOURS prérempli avec les valeurs
// actuelles du projet, donc le champ "Nom" ne serait jamais vide et le
// clic sur le fond ne fermerait plus jamais la fenêtre. Ici on protège
// seulement les vraies MODIFICATIONS (comparaison à l'état capturé à
// l'ouverture), pas la présence de texte.
(function () {
  var dialog = document.getElementById('dialog-informations-projet');
  if (!dialog) return;

  var instantane = null;

  function capturer() {
    var valeurs = {};
    dialog.querySelectorAll('form input, form select').forEach(function (el) {
      if (!el.name) return;
      valeurs[el.name] = el.multiple
        ? Array.prototype.map.call(el.selectedOptions, function (o) { return o.value; }).sort().join(',')
        : el.value;
    });
    return valeurs;
  }

  function modifie() {
    if (!instantane) return false;
    var actuel = capturer();
    return Object.keys(actuel).some(function (k) { return actuel[k] !== instantane[k]; });
  }

  document.querySelectorAll('[data-open-informations-dialog]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (typeof dialog.showModal === 'function') {
        dialog.showModal();
      } else {
        dialog.setAttribute('open', 'open');
      }
      // Capturé après un court délai : laisse chip-select.js/
      // search-combobox.js finir d'initialiser leurs <select> masqués
      // (valeurs déjà correctes de toute façon, mais on attend le même
      // tick pour rester simple).
      setTimeout(function () { instantane = capturer(); }, 0);
    });
  });

  dialog.querySelectorAll('[data-close-informations-dialog]').forEach(function (b) {
    b.addEventListener('click', function () {
      dialog.close();
    });
  });

  dialog.addEventListener('click', function (e) {
    if (e.target !== dialog) return;
    if (modifie()) return;
    dialog.close();
  });
})();

// Fenêtre flottante "Informations" du projet (retour Fadhel, 2026-09-28,
// Lot 5) — voir partials/projet_informations_dialog.html. Même principe
// d'ouverture/fermeture que projet-dialog.js/post-dialog.js : un seul
// formulaire, ouvert par [data-open-informations-dialog].
//
// Clic sur le fond : règle commune (floating-window.js) — ferme sauf si un
// champ a été modifié depuis l'ouverture. Cette fenêtre avait sa propre
// copie de la règle "comparée à l'ouverture" (formulaire toujours
// prérempli) ; depuis le 2026-09-29 la règle commune fait exactement ça.
(function () {
  var dialog = document.getElementById('dialog-informations-projet');
  if (!dialog) return;

  document.querySelectorAll('[data-open-informations-dialog]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (typeof dialog.showModal === 'function') {
        dialog.showModal();
      } else {
        dialog.setAttribute('open', 'open');
      }
    });
  });

  dialog.querySelectorAll('[data-close-informations-dialog]').forEach(function (b) {
    b.addEventListener('click', function () {
      dialog.close();
    });
  });

  window.KairosFloatingWindow.attacherFermetureAuFond(dialog);
})();

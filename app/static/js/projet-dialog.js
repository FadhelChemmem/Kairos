// Fenêtre flottante "Nouveau projet" (retour Fadhel, 2026-09-28) — voir
// partials/projet_dialog.html. Même principe d'ouverture/fermeture que
// post-dialog.js, mais sans sélecteur d'intention ni projet imposé : un
// seul formulaire, ouvert par n'importe quel déclencheur
// [data-open-projet-dialog] (bouton "+ Nouveau projet" de /projets).
(function () {
  var dialog = document.getElementById('dialog-nouveau-projet');
  if (!dialog) return;

  document.querySelectorAll('[data-open-projet-dialog]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (typeof dialog.showModal === 'function') {
        dialog.showModal();
      } else {
        dialog.setAttribute('open', 'open');
      }
    });
  });

  dialog.querySelectorAll('[data-close-projet-dialog]').forEach(function (b) {
    b.addEventListener('click', function () {
      dialog.close();
    });
  });
  // Clic sur le fond (backdrop) : ferme, sauf si un texte a déjà été saisi
  // (nom/code) — même règle commune que les autres fenêtres flottantes,
  // voir floating-window.js.
  window.KairosFloatingWindow.attacherFermetureAuFond(dialog);

  // Code proposé recalculé à chaque changement de phase (même logique que
  // projet_creer.html — PROMPT_CORRECTIONS.md P2 #22), sauf si l'utilisateur
  // a déjà modifié le champ lui-même.
  var champCode = dialog.querySelector('#dialog-projet-code');
  var champPhase = dialog.querySelector('#dialog-projet-phase');
  var urlCodePropose = dialog.getAttribute('data-url-code-propose');
  var modifieManuellement = false;
  var derniereDemande = 0;

  if (champCode && champPhase && urlCodePropose) {
    champCode.addEventListener('input', function () {
      modifieManuellement = true;
    });

    champPhase.addEventListener('change', function () {
      if (modifieManuellement) return;
      var numero = ++derniereDemande;
      fetch(urlCodePropose + '?phase=' + encodeURIComponent(champPhase.value))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (numero !== derniereDemande || modifieManuellement) return;
          if (data.code) {
            champCode.value = data.code;
          }
        })
        .catch(function () {
          // Silencieux, comme sur la page "Nouveau projet" complète : le
          // code déjà affiché reste une proposition valable.
        });
    });
  }
})();

// Fenêtre flottante "Nouveau post" (retour Fadhel, 2026-09-19) — voir
// partials/post_dialog.html. Un seul <dialog> par page, ouvert par
// n'importe quel déclencheur [data-open-post-dialog] (le bouton "+ Nouveau
// post" de la page projet/accueil, ou le rebond sous un post). Le
// déclencheur porte les infos nécessaires en attributs data- :
//   data-parent-post-id  : id du post d'origine (rebond) — vide sinon
//   data-intent          : "tache" | "information" | "requete" (panneau
//                           préselectionné)
//   data-projet-id       : projet imposé (rebond sur un post d'un projet
//                           précis) — vide si l'utilisateur doit choisir
//                           (bouton "+ Nouveau post" de l'accueil)
//   data-projet-label    : libellé "Code_nom" à afficher quand le projet
//                           est imposé
(function () {
  var dialog = document.getElementById('dialog-nouveau-post');
  if (!dialog) return;

  var tacheForm = dialog.querySelector('.panel-tache form');
  var requeteForm = dialog.querySelector('.panel-requete form');
  var projetSelect = dialog.querySelector('#dialog-post-projet');
  var projetRow = dialog.querySelector('[data-post-dialog-projet-row]');
  var projetFigee = dialog.querySelector('[data-post-dialog-projet-figee]');
  var projetFigeeLabel = dialog.querySelector('[data-post-dialog-projet-figee-label]');
  var tacheActionTemplate = tacheForm ? tacheForm.getAttribute('data-action-template') : null;

  function appliquerProjet(pid) {
    if (!pid) return;
    if (tacheForm && tacheActionTemplate) {
      tacheForm.action = tacheActionTemplate.replace('999999999', pid);
    }
    if (requeteForm) {
      var champ = requeteForm.querySelector('input[name="projet_id"]');
      if (champ) champ.value = pid;
    }
  }

  function definirParent(id) {
    dialog.querySelectorAll('input[name="parent_post_id"]').forEach(function (i) {
      i.value = id || '';
    });
  }

  document.querySelectorAll('[data-open-post-dialog]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      definirParent(btn.getAttribute('data-parent-post-id'));

      var intent = btn.getAttribute('data-intent') || 'tache';
      var radio = dialog.querySelector('#intent-' + intent);
      if (radio) radio.checked = true;

      var pidImpose = btn.getAttribute('data-projet-id');
      if (projetSelect) {
        if (pidImpose) {
          projetSelect.value = pidImpose;
          appliquerProjet(pidImpose);
          if (projetRow) projetRow.style.display = 'none';
          if (projetFigee) {
            projetFigee.style.display = '';
            if (projetFigeeLabel) projetFigeeLabel.textContent = btn.getAttribute('data-projet-label') || '';
          }
        } else {
          if (projetRow) projetRow.style.display = '';
          if (projetFigee) projetFigee.style.display = 'none';
          appliquerProjet(projetSelect.value);
        }
      } else if (pidImpose) {
        appliquerProjet(pidImpose);
      }

      if (typeof dialog.showModal === 'function') {
        dialog.showModal();
      } else {
        dialog.setAttribute('open', 'open');
      }
    });
  });

  if (projetSelect) {
    projetSelect.addEventListener('change', function () {
      appliquerProjet(projetSelect.value);
    });
  }

  dialog.querySelectorAll('[data-close-post-dialog]').forEach(function (b) {
    b.addEventListener('click', function () {
      dialog.close();
    });
  });
  // Clic sur le fond (backdrop) du <dialog> : ferme, SAUF si la fenêtre
  // contient du texte saisi (retour Fadhel, 2026-09-28 — voir
  // floating-window.js, règle commune à toutes les fenêtres flottantes).
  // Il faut alors passer par "Annuler"/le X pour fermer explicitement.
  window.KairosFloatingWindow.attacherFermetureAuFond(dialog);

  // Retour visuel du glisser-déposer pour la pièce jointe (panneau Requête) —
  // géré par app/static/js/dropzone.js (extrait d'ici le 2026-09-28, Lot 5,
  // pour être réutilisé par le composeur de commentaire de post_card.html ;
  // s'initialise seul sur tout le document, rien à appeler ici).
})();

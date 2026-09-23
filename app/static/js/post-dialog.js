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
  // Clic sur le fond (backdrop) du <dialog> = clic sur le <dialog> lui-même
  // (pas sur son contenu, qui est dans un enfant) : on ferme dans ce cas.
  dialog.addEventListener('click', function (e) {
    if (e.target === dialog) dialog.close();
  });

  // Retour visuel du glisser-déposer pour la pièce jointe (panneau Requête) —
  // le vrai <input type=file> couvre toute la zone, donc clic et glisser-
  // déposer fonctionnent tous les deux nativement ; ce script se contente
  // d'afficher le nom du fichier choisi/déposé.
  dialog.querySelectorAll('[data-dropzone]').forEach(function (dz) {
    var input = dz.querySelector('input[type="file"]');
    var label = dz.querySelector('[data-dropzone-label]');
    var original = label.textContent;

    function showFile(name) {
      label.textContent = name;
      dz.classList.add('has-file');
    }

    input.addEventListener('change', function () {
      if (input.files && input.files[0]) {
        showFile(input.files[0].name);
      } else {
        dz.classList.remove('has-file');
        label.textContent = original;
      }
    });

    dz.addEventListener('dragover', function (e) {
      e.preventDefault();
      dz.classList.add('dragover');
    });
    dz.addEventListener('dragleave', function () {
      dz.classList.remove('dragover');
    });
    dz.addEventListener('drop', function (e) {
      e.preventDefault();
      dz.classList.remove('dragover');
      var files = e.dataTransfer && e.dataTransfer.files;
      if (files && files[0]) {
        input.files = files;
        showFile(files[0].name);
      }
    });
  });
})();

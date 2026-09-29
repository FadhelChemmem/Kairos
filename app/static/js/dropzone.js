/* Zone de glisser-déposer générique pour un champ fichier (`.dropzone` +
 * `[data-dropzone]`, voir app.css) — extrait le 2026-09-28 (Lot 5, retour
 * Fadhel : "glisser-déposer" pour les pièces jointes de commentaire) du
 * script qui vivait jusqu'ici DANS post-dialog.js, scopé au seul <dialog>
 * "Nouveau post" : cette version s'initialise sur TOUT le document, comme
 * chip-select.js/search-combobox.js, pour pouvoir aussi servir au
 * composeur de commentaire de post_card.html (et à toute future zone de
 * dépôt) sans dépendre du dialog.
 *
 * Nouveauté par rapport à l'ancienne version : aperçu d'image (Lot 5,
 * "aperçu image") — si le fichier choisi/déposé est une image, une
 * vignette est affichée via URL.createObjectURL au lieu du simple nom de
 * fichier ; l'URL objet est révoquée à chaque changement pour ne pas fuiter
 * de mémoire (voir revoke ci-dessous).
 *
 * Utilisation : <div class="dropzone" data-dropzone>
 *                 <span data-dropzone-label>Texte par défaut</span>
 *                 <input type="file" class="dropzone-input" name="…">
 *               </div>
 */
(function () {
  var RE_IMAGE = /\.(png|jpe?g|gif|webp)$/i;

  function build(dz) {
    if (dz.dataset.dropzoneInit) return;
    dz.dataset.dropzoneInit = '1';

    var input = dz.querySelector('input[type="file"]');
    var label = dz.querySelector('[data-dropzone-label]');
    if (!input || !label) return;
    var original = label.textContent;
    var preview = null;
    var previewUrl = null;

    function clearPreview() {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
        previewUrl = null;
      }
      if (preview) {
        preview.remove();
        preview = null;
      }
    }

    function showFile(file) {
      label.textContent = file.name;
      dz.classList.add('has-file');
      clearPreview();
      if (RE_IMAGE.test(file.name)) {
        previewUrl = URL.createObjectURL(file);
        preview = document.createElement('img');
        preview.className = 'dropzone-preview';
        preview.src = previewUrl;
        preview.alt = file.name;
        dz.appendChild(preview);
      }
    }

    function reset() {
      dz.classList.remove('has-file');
      label.textContent = original;
      clearPreview();
    }

    input.addEventListener('change', function () {
      if (input.files && input.files[0]) {
        showFile(input.files[0]);
      } else {
        reset();
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
        showFile(files[0]);
      }
    });
  }

  function init() {
    document.querySelectorAll('[data-dropzone]').forEach(build);
  }

  // Capture d'écran collée (Ctrl+V) pendant qu'on écrit un post : elle va
  // dans la zone de dépôt du formulaire en cours (retour Fadhel : « on
  // utilise beaucoup de captures d'écran »). Le champ de commentaire gère
  // son propre collage (comment-composer.js).
  document.addEventListener('paste', function (e) {
    var files = e.clipboardData && e.clipboardData.files;
    if (!files || !files.length) return;
    var actif = document.activeElement;
    var form = actif && actif.closest && actif.closest('form');
    if (!form || form.hasAttribute('data-comment-composer') || form.hasAttribute('data-comment-edit')) return;
    var input = form.querySelector('[data-dropzone] input[type="file"]');
    if (!input) return;
    try {
      var dt = new DataTransfer();
      dt.items.add(files[0]);
      input.files = dt.files;
    } catch (err) {
      return;
    }
    e.preventDefault();
    input.dispatchEvent(new Event('change'));
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

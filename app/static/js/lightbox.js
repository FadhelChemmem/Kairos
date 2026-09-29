/* Visionneuse d'images (retour Fadhel, 2026-09-29) : une image de
 * commentaire (lien [data-lightbox], voir partials/post_card.html) s'ouvre
 * dans une fenêtre flottante par-dessus le fil ; un clic à côté de l'image
 * ou Échap la referme, et l'on retrouve le fil exactement où on l'avait
 * laissé (la page ne bouge pas). Sans JavaScript, le lien ouvre l'image
 * dans un nouvel onglet.
 */
(function () {
  var dialog = null;
  var img = null;

  function creer() {
    dialog = document.createElement('dialog');
    dialog.className = 'lightbox';
    dialog.setAttribute('aria-label', 'Image');
    img = document.createElement('img');
    img.alt = '';
    var fermer = document.createElement('button');
    fermer.type = 'button';
    fermer.className = 'lightbox-fermer';
    fermer.setAttribute('aria-label', 'Fermer');
    fermer.textContent = '×';
    dialog.appendChild(img);
    dialog.appendChild(fermer);
    document.body.appendChild(dialog);
    // Clic partout sauf sur l'image : ferme.
    dialog.addEventListener('click', function (e) {
      if (e.target !== img) dialog.close();
    });
    dialog.addEventListener('close', function () { img.removeAttribute('src'); });
  }

  document.addEventListener('click', function (e) {
    var lien = e.target.closest('a[data-lightbox]');
    if (!lien || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    if (!dialog) creer();
    var source = lien.querySelector('img');
    img.src = lien.href;
    img.alt = source ? source.alt : '';
    if (typeof dialog.showModal === 'function') {
      dialog.showModal();
    } else {
      dialog.setAttribute('open', 'open');
    }
  });
})();

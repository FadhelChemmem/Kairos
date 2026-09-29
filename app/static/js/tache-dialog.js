// Fenêtre d'une tâche (retour Fadhel, 2026-09-29) : un clic sur la ligne
// d'une tâche (page projet) ouvre sa fenêtre flottante — titre modifiable,
// état, clôture, pièces jointes — à la place de l'ancien menu "…". Voir
// projet_detail.html (<dialog id="dialog-tache-N">). Fermeture : X, Échap,
// ou clic à l'extérieur tant que rien n'a été modifié (floating-window.js).
(function () {
  function ouvrir(id) {
    var d = document.getElementById('dialog-tache-' + id);
    if (!d) return;
    if (typeof d.showModal === 'function') d.showModal(); else d.setAttribute('open', 'open');
  }

  document.querySelectorAll('dialog.tache-dialog').forEach(function (d) {
    window.KairosFloatingWindow.attacherFermetureAuFond(d);
    d.querySelectorAll('[data-close-tache]').forEach(function (b) {
      b.addEventListener('click', function () { d.close(); });
    });
  });

  document.querySelectorAll('[data-open-tache]').forEach(function (ligne) {
    ligne.addEventListener('click', function (e) {
      // Les contrôles de la ligne ("rejoindre cette tâche"…) gardent leur
      // propre action.
      if (e.target.closest('form, button, a, input, select')) return;
      ouvrir(ligne.getAttribute('data-open-tache'));
    });
    ligne.addEventListener('keydown', function (e) {
      if ((e.key === 'Enter' || e.key === ' ') && e.target === ligne) {
        e.preventDefault();
        ouvrir(ligne.getAttribute('data-open-tache'));
      }
    });
  });
})();

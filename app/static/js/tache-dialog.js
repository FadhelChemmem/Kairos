// Fenêtre d'une tâche (retour Fadhel, 2026-09-29) : un clic sur la ligne
// d'une tâche (page projet) ouvre sa fenêtre flottante — titre modifiable,
// état, clôture, pièces jointes — à la place de l'ancien menu "…". Voir
// projet_detail.html (<dialog id="dialog-tache-N">). Fermeture : X, Échap,
// ou clic à l'extérieur tant que rien n'a été modifié (floating-window.js).
(function () {
  function ouvrir(id) {
    var d = document.getElementById('dialog-tache-' + id);
    if (!d || d.open) return;
    if (typeof d.showModal === 'function') d.showModal(); else d.setAttribute('open', 'open');
    // Lot 10 : focus sur le premier champ (titre, état…) plutôt que « Fermer ».
    window.KairosFloatingWindow.focusPremierChamp(d);
  }

  document.querySelectorAll('dialog.tache-dialog').forEach(function (d) {
    window.KairosFloatingWindow.attacherFermetureAuFond(d);
    d.querySelectorAll('[data-close-tache]').forEach(function (b) {
      b.addEventListener('click', function () { d.close(); });
    });
  });

  // Lot 10 (audit front I8) : le titre de la tâche est un vrai bouton
  // (clavier : Tab, Entrée, Espace) ; le reste de la ligne reste un
  // raccourci souris. Les contrôles de la ligne ("rejoindre cette
  // tâche"…) gardent leur propre action.
  document.querySelectorAll('[data-open-tache]').forEach(function (ligne) {
    ligne.addEventListener('click', function (e) {
      if (!e.target.closest('[data-ouvrir-tache]') && e.target.closest('form, button, a, input, select')) return;
      ouvrir(ligne.getAttribute('data-open-tache'));
    });
  });
})();

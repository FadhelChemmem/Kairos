// Règle commune à TOUTES les fenêtres flottantes de l'appli (retour
// Fadhel, 2026-09-28 : "On fait ça sur toutes les fenêtres flottantes.") —
// un clic à l'extérieur ne doit PAS fermer la fenêtre si l'utilisateur y a
// changé quelque chose (on perdrait sa saisie) : il faut alors passer par
// le bouton de fermeture explicite (X / Annuler). Sans modification, le
// clic extérieur ferme normalement.
//
// Revu le 2026-09-29 (retour Fadhel, point N1) : la version précédente
// bloquait dès qu'un champ texte était NON VIDE — donc toujours, pour une
// fenêtre dont un champ est prérempli (code proposé de "Nouveau projet",
// valeurs actuelles d'une fiche…). On compare maintenant à l'état des
// champs capturé à l'OUVERTURE de la fenêtre : seul un vrai changement
// protège la fenêtre.
window.KairosFloatingWindow = (function () {
  // État de tous les champs de `container` : valeur des champs
  // texte/date/select (sélection multiple triée), cases cochées, fichiers
  // choisis. Les champs cachés sont ignorés (remplis par le code, pas
  // par l'utilisateur).
  function capturer(container) {
    var etat = [];
    container.querySelectorAll('input, select, textarea').forEach(function (el) {
      if (el.type === 'hidden' || el.disabled) return;
      var v;
      if (el.type === 'checkbox' || el.type === 'radio') {
        v = el.checked ? '1' : '0';
      } else if (el.type === 'file') {
        v = el.files ? String(el.files.length) : '0';
      } else if (el.multiple) {
        v = Array.prototype.map.call(el.selectedOptions, function (o) { return o.value; }).sort().join(',');
      } else {
        v = el.value;
      }
      etat.push((el.name || el.id || '') + '=' + v);
    });
    return etat.join('\u0001');
  }

  function memoriser(container) {
    container._kairosInstantane = capturer(container);
  }

  function aEteModifiee(container) {
    if (container._kairosInstantane === undefined) return false;
    return capturer(container) !== container._kairosInstantane;
  }

  // Ferme `dialogEl` (un <dialog> natif) au clic sur son propre fond
  // (backdrop) — sauf si l'utilisateur y a changé quelque chose depuis
  // l'ouverture. L'état de référence est capturé automatiquement à chaque
  // ouverture (attribut `open`), après que le déclencheur a prérempli les
  // champs ; setTimeout laisse chip-select.js/search-combobox.js finir
  // d'initialiser leurs <select> masqués.
  function attacherFermetureAuFond(dialogEl) {
    new MutationObserver(function () {
      if (dialogEl.hasAttribute('open')) {
        setTimeout(function () { memoriser(dialogEl); }, 0);
      }
    }).observe(dialogEl, { attributes: true, attributeFilter: ['open'] });
    if (dialogEl.hasAttribute('open')) memoriser(dialogEl);

    dialogEl.addEventListener('click', function (e) {
      if (e.target !== dialogEl) return;
      if (aEteModifiee(dialogEl)) return;
      dialogEl.close();
    });
  }

  return { memoriser: memoriser, aEteModifiee: aEteModifiee, attacherFermetureAuFond: attacherFermetureAuFond };
})();

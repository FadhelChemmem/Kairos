// Lot 15 : menu « ⋯ » d'un post (Modifier, Supprimer) et modification sur
// place. Sans JavaScript : l'ancre #post-<id>-edition affiche le formulaire
// (:target) et « Supprimer » envoie un formulaire classique.
(function () {
  'use strict';

  function fermerMenus(sauf) {
    document.querySelectorAll('details.post-menu[open]').forEach(function (d) {
      if (d !== sauf) d.open = false;
    });
  }

  function ouvrir(carte) {
    var form = carte.querySelector('form[data-post-edition]');
    if (!form) return;
    carte.classList.add('post-en-edition');
    var champ = form.querySelector('input[type=text], textarea');
    if (champ) {
      champ.focus();
      if (champ.setSelectionRange) champ.setSelectionRange(champ.value.length, champ.value.length);
    }
  }

  function fermer(carte) {
    var form = carte.querySelector('form[data-post-edition]');
    carte.classList.remove('post-en-edition');
    if (form) form.reset();
    if (window.location.hash === '#' + (form && form.id)) {
      try { history.replaceState(null, '', window.location.pathname + window.location.search); } catch (e) { /* rien */ }
    }
    var b = carte.querySelector('.post-menu-bouton');
    if (b) b.focus();
  }

  function modifie(form) {
    return Array.prototype.some.call(form.elements, function (el) {
      if (el.type === 'checkbox') return el.checked !== el.defaultChecked;
      if (el.type === 'file') return el.files && el.files.length > 0;
      if (el.tagName === 'TEXTAREA' || el.type === 'text') return el.value !== el.defaultValue;
      return false;
    });
  }

  document.addEventListener('click', function (e) {
    var t = e.target;
    var mod = t.closest && t.closest('[data-post-modifier]');
    if (mod) {
      e.preventDefault();
      var carte = mod.closest('.post-card');
      fermerMenus(null);
      if (carte) ouvrir(carte);
      return;
    }
    var ann = t.closest && t.closest('[data-post-edition-annuler]');
    if (ann) {
      e.preventDefault();
      fermer(ann.closest('.post-card'));
      return;
    }
    // Un clic ailleurs referme le menu ouvert.
    var menu = t.closest && t.closest('details.post-menu');
    fermerMenus(menu);
  });

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || e.defaultPrevented) return;
    var menu = document.querySelector('details.post-menu[open]');
    if (menu) {
      e.preventDefault();
      menu.open = false;
      var s = menu.querySelector('summary');
      if (s) s.focus();
      return;
    }
    var form = e.target && e.target.closest ? e.target.closest('form[data-post-edition]') : null;
    if (!form) return;
    e.preventDefault();
    var carte = form.closest('.post-card');
    var K = window.Kairos;
    if (!modifie(form) || !K || !K.confirmer) { fermer(carte); return; }
    K.confirmer(e.target, 'Abandonner les modifications ?', { libelleOk: 'Abandonner', libelleAnnuler: 'Continuer', danger: true })
      .then(function (oui) { if (oui) fermer(carte); });
  });

  // Le formulaire affiché par l'ancre (lien ouvert dans un nouvel onglet,
  // ou JavaScript chargé après le clic).
  function depuisAncre() {
    var m = /^#post-(\d+)-edition$/.exec(window.location.hash || '');
    if (!m) return;
    var carte = document.getElementById('post-' + m[1]);
    if (carte) ouvrir(carte);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', depuisAncre);
  else depuisAncre();
})();

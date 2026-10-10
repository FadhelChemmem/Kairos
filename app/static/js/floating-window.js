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
      // Les champs désactivés restent comptés : un onglet activé ou
      // désactivé par le code ne doit pas passer pour une saisie.
      if (el.type === 'hidden') return;
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
  function mouvementReduit() {
    try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; }
  }

  // Fermeture animée (revue d'interaction P1-10) : fondu / glissement de
  // 180 ms, puis close() — `fin` remplace close() (tache-dialog.js).
  function fermer(dialogEl, fin) {
    var terminer = fin || function () { dialogEl.close(); };
    if (!dialogEl.open || dialogEl._kairosSortie) return;
    if (mouvementReduit() || !dialogEl.animate) { terminer(); return; }
    dialogEl._kairosSortie = true;
    var fait = false;
    var finir = function () {
      if (fait) return;
      fait = true;
      dialogEl._kairosSortie = false;
      dialogEl.classList.remove('k-sortie', 'k-glisse', 'k-retour');
      dialogEl.style.transform = '';
      terminer();
    };
    dialogEl.classList.remove('k-glisse', 'k-retour');
    dialogEl.classList.add('k-sortie');
    dialogEl.addEventListener('animationend', function surFin(e) {
      if (e.target !== dialogEl) return;
      dialogEl.removeEventListener('animationend', surFin);
      finir();
    });
    setTimeout(finir, 260);
  }

  // Demande de fermeture par un geste (glisser, Échap, fond) : la fenêtre
  // peut fournir la sienne (tache-dialog.js : historique) ; sinon, question
  // si la saisie a changé, fermeture animée sinon.
  function demander(dialogEl) {
    if (typeof dialogEl._kairosDemanderFermeture === 'function') { dialogEl._kairosDemanderFermeture(); return; }
    if (aEteModifiee(dialogEl)) { demanderFermeture(dialogEl); return; }
    fermer(dialogEl);
  }

  // Feuille en bas (téléphone) : glisser vers le bas depuis la poignée ou
  // l'en-tête ferme au-delà de 30 % de la hauteur ou à plus de 0,5 px/ms ;
  // sinon, retour en place (P1-10).
  function attacherGlisser(dialogEl) {
    var depart = null;
    dialogEl.addEventListener('touchstart', function (e) {
      if (e.touches.length !== 1 || !window.matchMedia('(max-width: 600px)').matches) return;
      if (dialogEl.classList.contains('tache-panneau') || dialogEl._kairosSortie) return;
      if (e.target.closest && e.target.closest('button, a, input, select, textarea, label, [role="option"]')) return;
      var r = dialogEl.getBoundingClientRect();
      var t = e.touches[0];
      if (t.clientY - r.top > 56 || dialogEl.scrollTop > 0) return;
      depart = { y: t.clientY, t: Date.now(), dy: 0, h: r.height };
    }, { passive: true });
    dialogEl.addEventListener('touchmove', function (e) {
      if (!depart) return;
      depart.dy = Math.max(0, e.touches[0].clientY - depart.y);
      if (depart.dy > 4) {
        // La feuille suit le doigt (pas de défilement ni de rebond).
        if (e.cancelable) e.preventDefault();
        dialogEl.classList.add('k-glisse');
        dialogEl.style.transform = 'translateY(' + depart.dy + 'px)';
      }
    }, { passive: false });
    function lacher() {
      if (!depart) return;
      var d = depart;
      depart = null;
      dialogEl.classList.remove('k-glisse');
      if (d.dy <= 4) { dialogEl.style.transform = ''; return; }
      var assez = d.dy > d.h * 0.3 || d.dy / Math.max(1, Date.now() - d.t) > 0.5;
      // Fermeture sans question : la sortie part de la position du doigt.
      if (assez && !aEteModifiee(dialogEl) && !dialogEl._kairosDemanderFermeture) { fermer(dialogEl); return; }
      dialogEl.classList.add('k-retour');
      dialogEl.style.transform = '';
      setTimeout(function () { dialogEl.classList.remove('k-retour'); }, 220);
      if (assez) demander(dialogEl);
    }
    dialogEl.addEventListener('touchend', lacher);
    dialogEl.addEventListener('touchcancel', lacher);
  }

  function attacherFermetureAuFond(dialogEl, opts) {
    opts = opts || {};
    attacherGlisser(dialogEl);
    new MutationObserver(function () {
      if (dialogEl.hasAttribute('open')) {
        setTimeout(function () { memoriser(dialogEl); }, 0);
      }
    }).observe(dialogEl, { attributes: true, attributeFilter: ['open'] });
    if (dialogEl.hasAttribute('open')) memoriser(dialogEl);

    dialogEl.addEventListener('click', function (e) {
      if (e.target !== dialogEl) return;
      // Lot 10 (audit front I4) : e.target vaut aussi le <dialog> pour un
      // clic dans son propre padding (20 px) — on ne ferme que pour un
      // clic réellement hors du cadre (sur le fond).
      var r = dialogEl.getBoundingClientRect();
      if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) return;
      if (aEteModifiee(dialogEl)) { demanderFermeture(dialogEl); return; }
      if (opts.fermeture) { opts.fermeture(); return; }
      fermer(dialogEl);
    });
    // Échap : même règle que le clic sur le fond — une saisie en cours
    // n'est pas jetée sans confirmation. Lot 13 (audit UX M11) : question
    // posée DANS la fenêtre (Abandonner / Continuer), plus de confirm().
    dialogEl.addEventListener('cancel', function (e) {
      if (!aEteModifiee(dialogEl)) {
        // Fenêtre qui gère elle-même Échap (tache-dialog.js) : rien ici.
        if (opts.fermeture) return;
        e.preventDefault();
        fermer(dialogEl);
        return;
      }
      e.preventDefault();
      demanderFermeture(dialogEl);
    });
  }

  function demanderFermeture(dialogEl) {
    var K = window.Kairos;
    if (!K || !K.confirmer) {
      if (window.confirm('Fermer sans enregistrer\u202f? La saisie sera perdue.')) dialogEl.close();
      return;
    }
    if (dialogEl.querySelector('.k-confirmation')) return;
    var ancre = document.activeElement && dialogEl.contains(document.activeElement) ? document.activeElement : dialogEl;
    K.confirmer(ancre, 'Abandonner les modifications\u202f? La saisie sera perdue.', {
      libelleOk: 'Abandonner', libelleAnnuler: 'Continuer la saisie', danger: true
    }).then(function (oui) {
      if (!oui) return;
      // « Abandonner » vide vraiment la saisie (P2-7) : la fenêtre écoute
      // kairos:abandon ; fermer par le X ou « Annuler » garde le brouillon.
      dialogEl.dispatchEvent(new CustomEvent('kairos:abandon'));
      fermer(dialogEl);
    });
  }

  // Focus initial d'une fenêtre : le premier champ de saisie visible (et
  // non le bouton « Fermer », premier élément focalisable).
  function focusPremierChamp(container) {
    var champs = container.querySelectorAll('input:not([type=hidden]):not([type=radio]):not([type=file]):not([disabled]), textarea:not([disabled]), select:not([disabled])');
    for (var i = 0; i < champs.length; i++) {
      var c = champs[i];
      if (c.offsetParent !== null && getComputedStyle(c).visibility !== 'hidden') { c.focus(); return true; }
    }
    return false;
  }

  return { memoriser: memoriser, aEteModifiee: aEteModifiee, attacherFermetureAuFond: attacherFermetureAuFond, focusPremierChamp: focusPremierChamp,
    demanderFermeture: demanderFermeture, fermer: fermer };
})();

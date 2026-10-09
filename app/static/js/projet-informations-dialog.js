// Fenêtre flottante "Informations" du projet (retour Fadhel, 2026-09-28,
// Lot 5) — voir partials/projet_informations_dialog.html. Même principe
// d'ouverture/fermeture que projet-dialog.js/post-dialog.js : un seul
// formulaire, ouvert par [data-open-informations-dialog].
//
// Clic sur le fond : règle commune (floating-window.js) — ferme sauf si un
// champ a été modifié depuis l'ouverture. Cette fenêtre avait sa propre
// copie de la règle "comparée à l'ouverture" (formulaire toujours
// prérempli) ; depuis le 2026-09-29 la règle commune fait exactement ça.
(function () {
  var dialog = document.getElementById('dialog-informations-projet');
  if (!dialog) return;

  function ouvrir() {
    // Bouton « Modifier » DANS la carte cliquable : un seul appel.
    if (dialog.open) return;
    if (typeof dialog.showModal === 'function') {
      dialog.showModal();
    } else {
      dialog.setAttribute('open', 'open');
    }
    // Lot 10 : focus sur le premier champ (et non sur « Fermer »).
    window.KairosFloatingWindow.focusPremierChamp(dialog);
  }

  // Déclencheur : le panneau "Informations" de la page projet lui-même
  // (2026-09-29, PR6) — cliquable, et au clavier (Entrée/Espace).
  // Délégation (lot 13) : la carte Informations remplacée par un fragment
  // partiel reste un déclencheur.
  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('[data-open-informations-dialog]')) ouvrir();
  });
  document.addEventListener('keydown', function (e) {
    var el = e.target;
    if ((e.key === 'Enter' || e.key === ' ') && el && el.hasAttribute && el.hasAttribute('data-open-informations-dialog')) {
      e.preventDefault();
      ouvrir();
    }
  });

  // Délégation (lot 13) : le formulaire est remplacé après un envoi.
  dialog.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('[data-close-informations-dialog]')) dialog.close();
    if (e.target.closest && e.target.closest('[data-informations-retour]')) restaurer(true);
  });

  window.KairosFloatingWindow.attacherFermetureAuFond(dialog);

  // Lot 13 (phase 2) : enregistrement en partiel. Succès : le serveur
  // renvoie le formulaire à jour marqué data-enregistre (la fiche est mise
  // à jour hors cible) — la fenêtre se ferme, le focus revient sur
  // « Modifier ». Clôture d'un projet qui a des tâches ouvertes : la
  // confirmation prend la place du formulaire ; « Revenir au formulaire »
  // ou la fermeture le rétablissent (GET du formulaire seul).
  // « Revenir au formulaire » remet le formulaire envoyé, saisie comprise
  // (nœud gardé quand la confirmation le remplace — recette finale NF1) ;
  // la fermeture repart du formulaire du serveur.
  var urlFormulaire = (dialog.querySelector('#informations-form') || {}).action;
  var formEnvoye = null;
  dialog.addEventListener('submit', function (e) {
    var f = e.target;
    if (f && f.id === 'informations-form' && f.tagName === 'FORM') formEnvoye = f;
  }, true);
  function restaurer(garderOuverte) {
    var K = window.Kairos;
    var actuel = dialog.querySelector('#informations-form');
    var garde = formEnvoye;
    formEnvoye = null;
    if (!actuel || actuel.tagName === 'FORM') return;
    if (garderOuverte && garde && !document.contains(garde) && actuel.parentNode) {
      actuel.parentNode.replaceChild(garde, actuel);
      if (dialog.open) window.KairosFloatingWindow.focusPremierChamp(dialog);
      return;
    }
    if (!K || !urlFormulaire) return;
    K.requete({ url: urlFormulaire, methode: 'GET', cible: '#informations-form', historique: 'aucun', transition: false })
      .then(function () {
        if (garderOuverte && dialog.open) window.KairosFloatingWindow.focusPremierChamp(dialog);
        window.KairosFloatingWindow.memoriser(dialog);
      });
  }
  dialog.addEventListener('close', function () { restaurer(false); });
  document.addEventListener('kairos:fragment', function (e) {
    var racine = e.detail && e.detail.racine;
    if (!racine || racine.id !== 'informations-form') return;
    if (racine.tagName === 'FORM') formEnvoye = null;
    if (racine.hasAttribute('data-enregistre')) {
      racine.removeAttribute('data-enregistre');
      // Après le focus rendu par kairos-partiel.js (même tour de boucle).
      setTimeout(function () {
        window.KairosFloatingWindow.memoriser(dialog);
        if (dialog.open) dialog.close();
        var modifier = document.querySelector('#carte-informations button[data-open-informations-dialog]');
        if (modifier) modifier.focus();
      }, 0);
    } else if (racine.tagName !== 'FORM') {
      // Confirmation affichée : focus sur sa question.
      var titre = racine.querySelector('[data-partiel-titre]');
      if (titre) titre.focus();
    }
  });

  // Lot 11 b : lien « Changer le chef » de l'encart Admin (liste
  // Utilisateurs, ?informations=chef) — fenêtre ouverte, focus dans le
  // champ « Chef de projet » (sa liste s'ouvre au focus), nom du chef
  // actuel sélectionné : la frappe le remplace. Le paramètre est retiré de
  // l'adresse : un rechargement ne rouvre pas la fenêtre.
  if (dialog.getAttribute('data-ouvrir-au-chargement') === 'chef') {
    ouvrir();
    var champ = dialog.querySelector('#dialog-info-chef ~ .search-combobox-wrap .search-combobox-input');
    if (champ) { champ.focus(); champ.select(); }
    try {
      var u = new URL(window.location.href);
      u.searchParams.delete('informations');
      window.history.replaceState(window.history.state, '', u.pathname + u.search + u.hash);
    } catch (e) { /* adresse laissée telle quelle */ }
  }
})();

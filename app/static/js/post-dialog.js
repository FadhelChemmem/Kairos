// Fenêtre flottante "Nouveau post" (retour Fadhel, 2026-09-19) — voir
// partials/post_dialog.html. Un seul <dialog> par page, ouvert par
// n'importe quel déclencheur [data-open-post-dialog] (le bouton "+ Nouveau
// post" de la page projet/accueil, ou "Reposter" sous un post). Le
// déclencheur porte les infos nécessaires en attributs data- :
//   data-parent-post-id  : id du post d'origine (Reposter) — vide sinon
//   data-parent-label    : "auteur — début du texte" du post d'origine,
//                           affiché en tête de la fenêtre
//   data-intent          : "tache" | "information" | "requete" (panneau
//                           préselectionné)
//   data-intents         : onglets proposés (ex. "information,requete") —
//                           tous par défaut
//   data-projet-id       : projet imposé (Reposter un post d'un projet) —
//                           vide si l'utilisateur doit choisir (bouton
//                           "+ Nouveau post" de l'accueil) ; "aucun" pour
//                           imposer "sans projet" (Reposter une Information
//                           d'équipe)
//   data-projet-label    : libellé "Code_nom" à afficher quand le projet
//                           est imposé
//   data-gere            : "1"/"0" — je gère (ou non) le projet du
//                           déclencheur : décide de l'onglet Tâche quand le
//                           projet est imposé ou fixé par la page
//
// Règles du sélecteur de projet (retour Fadhel, 2026-09-29) :
// - "Tâche" seulement pour un projet que je gère (option data-gere="1") ;
// - "Aucun projet" seulement pour une Information (N5) — c'est même le
//   choix par défaut de l'onglet Information ("laisser le champ projet
//   vide avec la possibilité de mettre un projet", marqué optionnel) ;
//   choisir "Aucun projet" bascule sur l'onglet Information, et quitter
//   l'onglet Information revient au premier projet de la liste ;
// - sans projet, le choix des équipes destinataires apparaît.
(function () {
  var dialog = document.getElementById('dialog-nouveau-post');
  if (!dialog) return;

  var AUCUN = 'aucun';
  var tacheForm = dialog.querySelector('.panel-tache form');
  var projetSelect = dialog.querySelector('#dialog-post-projet');
  var projetRow = dialog.querySelector('[data-post-dialog-projet-row]');
  var projetFigee = dialog.querySelector('[data-post-dialog-projet-figee]');
  var projetFigeeLabel = dialog.querySelector('[data-post-dialog-projet-figee-label]');
  var equipesRow = dialog.querySelector('[data-post-dialog-equipes]');
  var projetOptionnel = dialog.querySelector('[data-projet-optionnel]');
  var projetImpose = false;
  var parentBandeau = dialog.querySelector('[data-post-dialog-parent]');
  var parentLabel = dialog.querySelector('[data-post-dialog-parent-label]');
  var tacheActionTemplate = tacheForm ? tacheForm.getAttribute('data-action-template') : null;
  var intentsAutorises = null; // null = tous
  var gereForce = null;        // data-gere du déclencheur, s'il y en a un

  function radio(intent) { return dialog.querySelector('#intent-' + intent); }
  function onglet(intent) { return dialog.querySelector('.seg label[for="intent-' + intent + '"]'); }
  function intentCourant() {
    var r = dialog.querySelector('.composer-radio:checked');
    return r ? r.id.replace('intent-', '') : 'tache';
  }
  function optionProjet(pid) {
    if (!projetSelect) return null;
    return Array.prototype.filter.call(projetSelect.options, function (o) { return o.value === pid; })[0] || null;
  }
  function premierProjet() {
    if (!projetSelect) return null;
    var o = Array.prototype.filter.call(projetSelect.options, function (x) { return x.value && x.value !== AUCUN; })[0];
    return o ? o.value : null;
  }
  function projetCourant() {
    return projetSelect ? projetSelect.value : null;
  }
  function choisirProjet(pid, label) {
    // Projet imposé absent de la liste (Reposter un post d'un projet que je
    // vois sans en être membre) : option ajoutée pour que la valeur tienne.
    if (!optionProjet(pid)) {
      var o = document.createElement('option');
      o.value = pid;
      o.textContent = label || pid;
      o.dataset.gere = '0';
      projetSelect.appendChild(o);
    }
    projetSelect.value = pid;
    // Sans bulles : resynchronise le texte affiché du combobox, et notre
    // propre écouteur (plus bas) le distingue d'un choix de l'utilisateur.
    projetSelect.dispatchEvent(new Event('change'));
  }

  // Onglets visibles selon le projet choisi et le déclencheur.
  function majOnglets() {
    var pid = projetCourant();
    var sansProjet = pid === AUCUN;
    // Sans projet (onglet Information), Tâche/Requête restent proposés :
    // les choisir revient au premier projet de la liste — c'est lui qui
    // décide alors de l'onglet Tâche.
    var opt = sansProjet ? optionProjet(premierProjet()) : (pid ? optionProjet(pid) : null);
    var gere = gereForce !== null ? gereForce === '1'
      : (!projetSelect || (opt && opt.dataset.gere === '1'));
    ['tache', 'information', 'requete'].forEach(function (intent) {
      var ok = !intentsAutorises || intentsAutorises.indexOf(intent) !== -1;
      if (intent === 'tache' && !gere) ok = false;
      if (intent !== 'information' && sansProjet && !premierProjet()) ok = false;
      var lab = onglet(intent);
      if (lab) lab.style.display = ok ? '' : 'none';
      var r = radio(intent);
      if (r) r.disabled = !ok;
    });
    var courant = radio(intentCourant());
    if (!courant || courant.disabled) {
      var premier = ['tache', 'information', 'requete'].filter(function (i) { return radio(i) && !radio(i).disabled; })[0];
      if (premier) radio(premier).checked = true;
    }
    if (equipesRow) equipesRow.style.display = (sansProjet && intentCourant() === 'information') ? '' : 'none';
    if (projetOptionnel) projetOptionnel.style.display = intentCourant() === 'information' ? '' : 'none';
  }

  function appliquerProjet() {
    var pid = projetCourant();
    var valeur = (!pid || pid === AUCUN) ? '' : pid;
    if (tacheForm && tacheActionTemplate && valeur) {
      tacheForm.action = tacheActionTemplate.replace('999999999', valeur);
    }
    if (projetSelect) {
      dialog.querySelectorAll('.panel-information form, .panel-requete form').forEach(function (f) {
        var champ = f.querySelector('input[name="projet_id"]');
        if (champ) champ.value = valeur;
      });
    }
    majOnglets();
  }

  function definirParent(id, label) {
    dialog.querySelectorAll('input[name="parent_post_id"]').forEach(function (i) {
      i.value = id || '';
    });
    if (parentBandeau) {
      parentBandeau.style.display = id ? '' : 'none';
      if (parentLabel) parentLabel.textContent = label || '';
    }
  }

  document.querySelectorAll('[data-open-post-dialog]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (btn.disabled) return;
      definirParent(btn.getAttribute('data-parent-post-id'), btn.getAttribute('data-parent-label'));
      var intents = btn.getAttribute('data-intents');
      intentsAutorises = intents ? intents.split(',') : null;
      gereForce = btn.getAttribute('data-gere');

      var intent = btn.getAttribute('data-intent') || 'tache';
      var r = radio(intent);
      if (r) { r.disabled = false; r.checked = true; }

      var pidImpose = btn.getAttribute('data-projet-id');
      projetImpose = !!pidImpose;
      if (projetSelect) {
        if (pidImpose) {
          choisirProjet(pidImpose, btn.getAttribute('data-projet-label'));
          if (projetRow) projetRow.style.display = 'none';
          if (projetFigee) {
            projetFigee.style.display = '';
            if (projetFigeeLabel) projetFigeeLabel.textContent = btn.getAttribute('data-projet-label') || '';
          }
        } else {
          if (projetRow) projetRow.style.display = '';
          if (projetFigee) projetFigee.style.display = 'none';
          if (intent === 'information') {
            choisirProjet(AUCUN);
          } else if (projetSelect.value === AUCUN && premierProjet()) {
            choisirProjet(premierProjet());
          }
        }
      }
      appliquerProjet();

      if (typeof dialog.showModal === 'function') {
        dialog.showModal();
      } else {
        dialog.setAttribute('open', 'open');
      }
    });
  });

  if (projetSelect) {
    projetSelect.addEventListener('change', function (e) {
      // Choix de l'utilisateur dans le combobox (évènement à bulles, voir
      // search-combobox.js) : "Aucun projet" ⇒ onglet Information.
      if (e.bubbles) gereForce = null; // l'utilisateur a changé de projet
      if (e.bubbles && projetSelect.value === AUCUN && radio('information')) {
        radio('information').disabled = false;
        radio('information').checked = true;
      }
      appliquerProjet();
    });
  }

  dialog.querySelectorAll('.composer-radio').forEach(function (r) {
    r.addEventListener('change', function () {
      // Onglet Information : projet vide par défaut (s'il n'est pas imposé).
      if (projetSelect && !projetImpose && intentCourant() === 'information') {
        choisirProjet(AUCUN);
      }
      // Quitter l'onglet Information sans projet : revenir à un projet.
      if (projetSelect && projetSelect.value === AUCUN && intentCourant() !== 'information' && premierProjet()) {
        choisirProjet(premierProjet());
      }
      appliquerProjet();
    });
  });

  var equipesSelect = dialog.querySelector('#dialog-equipes-information');
  var equipesAide = dialog.querySelector('[data-post-dialog-equipes-aide]');
  if (equipesSelect && equipesAide) {
    equipesSelect.addEventListener('change', function () {
      if (equipesSelect.selectedOptions.length) equipesAide.style.display = 'none';
    });
  }

  var toutes = dialog.querySelector('[data-toutes-equipes]');
  if (toutes) {
    toutes.addEventListener('click', function () {
      var sel = dialog.querySelector('#dialog-equipes-information');
      Array.prototype.forEach.call(sel.options, function (o) { o.selected = true; });
      sel.dispatchEvent(new Event('change'));
    });
  }

  // Sans projet : au moins une équipe destinataire (vérifié aussi par le
  // serveur, voir routes/posts.py:creer).
  var infoForm = dialog.querySelector('.panel-information form');
  if (infoForm) {
    infoForm.addEventListener('submit', function (e) {
      var sel = dialog.querySelector('#dialog-equipes-information');
      if (projetSelect && projetSelect.value === AUCUN && sel && !sel.selectedOptions.length) {
        e.preventDefault();
        var aide = dialog.querySelector('[data-post-dialog-equipes-aide]');
        if (aide) aide.style.display = '';
      }
    });
  }

  dialog.querySelectorAll('[data-close-post-dialog]').forEach(function (b) {
    b.addEventListener('click', function () {
      dialog.close();
    });
  });
  // Clic sur le fond (backdrop) du <dialog> : ferme, SAUF si un champ a
  // été modifié depuis l'ouverture (voir floating-window.js, règle commune
  // à toutes les fenêtres flottantes). Il faut alors passer par
  // "Annuler"/le X pour fermer explicitement.
  window.KairosFloatingWindow.attacherFermetureAuFond(dialog);

  // Retour visuel du glisser-déposer pour les pièces jointes — géré par
  // app/static/js/dropzone.js (s'initialise seul sur tout le document).
  appliquerProjet();
})();

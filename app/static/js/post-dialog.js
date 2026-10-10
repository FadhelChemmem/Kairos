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
  // "Aucun projet" absent de la liste pour qui ne peut pas publier
  // d'Information d'équipe (Client, ou compte sans équipe — lot 7) : on ne
  // doit alors jamais le choisir d'office.
  var aucunPossible = !!(projetSelect && Array.prototype.some.call(projetSelect.options, function (o) { return o.value === AUCUN; }));
  var gereForce = null;        // data-gere du déclencheur, s'il y en a un
  var ouvreur = null;          // bouton qui a ouvert la fenêtre

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
      o.dataset.temporaire = '1';
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
    // Reposter une Information d'équipe : la réponse va aux mêmes équipes
    // que le post d'origine (imposé par le serveur) — pas de choix ici.
    if (equipesRow) equipesRow.style.display = (sansProjet && !projetImpose && intentCourant() === 'information') ? '' : 'none';
    if (projetOptionnel) projetOptionnel.style.display = intentCourant() === 'information' ? '' : 'none';
  }

  // Lot 13 (contre-expertise rôles I7) : l'onglet Tâche ne propose que les
  // personnes qui voient le projet choisi (option data-voient, ids fournis
  // par le serveur) ; sans cette donnée (projet imposé), tout reste proposé
  // et le serveur écarte en le disant.
  var intervenantsTache = tacheForm ? tacheForm.querySelector('select[name="intervenants"]') : null;
  function filtrerIntervenants(pid) {
    if (!intervenantsTache || !projetSelect) return;
    var opt = pid && pid !== AUCUN ? optionProjet(pid) : null;
    var voient = null;
    if (opt && opt.hasAttribute('data-voient')) {
      voient = {};
      opt.getAttribute('data-voient').split(' ').forEach(function (id) { if (id) voient[id] = true; });
    }
    Array.prototype.forEach.call(intervenantsTache.options, function (o) {
      var hors = !!voient && !voient[o.value];
      if (hors) o.selected = false;
      o.disabled = hors;
    });
    intervenantsTache.dispatchEvent(new Event('change'));
  }

  function appliquerProjet() {
    var pid = projetCourant();
    var valeur = (!pid || pid === AUCUN) ? '' : pid;
    if (tacheForm && tacheActionTemplate && valeur) {
      tacheForm.action = tacheActionTemplate.replace('999999999', valeur);
    }
    filtrerIntervenants(pid);
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

  // Délégation (lot 13) : les déclencheurs insérés par un fragment partiel
  // (« Reposter » d'un post ajouté) fonctionnent aussi.
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-open-post-dialog]');
    if (!btn) return;
    ouvreur = btn;
    (function () {
      if (btn.disabled) return;
      // Lot 10 (audit front I4) : un brouillon reste lié à SON contexte
      // (post d'origine, projet). Ouvrir la fenêtre pour un autre post ou
      // un autre projet repart d'un formulaire vierge — avant, le texte
      // saisi pour un post partait sous un autre.
      var contexte = (btn.getAttribute('data-parent-post-id') || '') + '|' + (btn.getAttribute('data-projet-id') || '');
      if (dialog.dataset.contexte !== undefined && dialog.dataset.contexte !== contexte) {
        dialog.querySelectorAll('.intent-panel form').forEach(function (f) {
          f.reset();
          f.querySelectorAll('select[data-chip-select], .dropzone-input').forEach(function (s) { s.dispatchEvent(new Event('change')); });
        });
        var aideEquipes = dialog.querySelector('[data-post-dialog-equipes-aide]');
        if (aideEquipes) aideEquipes.style.display = 'none';
      }
      dialog.dataset.contexte = contexte;
      projetImpose = !!btn.getAttribute('data-projet-id');
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
          // Options ajoutées pour un Reposter précédent : retirées, la
          // liste redevient "mes projets".
          projetSelect.querySelectorAll('option[data-temporaire]').forEach(function (o) {
            if (projetSelect.value === o.value) projetSelect.value = premierProjet() || AUCUN;
            o.remove();
          });
          if (projetRow) projetRow.style.display = '';
          if (projetFigee) projetFigee.style.display = 'none';
          if (intent === 'information' && aucunPossible) {
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
      // Focus sur le premier champ du panneau ouvert (et non sur « Fermer »).
      var panneau = dialog.querySelector('.panel-' + intentCourant());
      if (panneau) window.KairosFloatingWindow.focusPremierChamp(panneau);
    })();
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
      if (projetSelect && !projetImpose && aucunPossible && intentCourant() === 'information') {
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

  // Lot 13 (audit UX §2.2 « Publier ») : envoi en partiel. La fenêtre se
  // ferme, le post arrive en tête du fil de la page (data-fil : #fil-liste
  // à l'accueil, #fil-posts sur la fiche projet) avec un surlignage ; une
  // tâche créée apparaît aussi, surlignée, dans le tableau de la fiche.
  // Erreur : la fenêtre reste ouverte avec la saisie, le champ en cause
  // est signalé (422). Sans JavaScript : POST puis retour à la page.
  function viderFormulaires() {
    dialog.querySelectorAll('.intent-panel form').forEach(function (f) {
      f.reset();
      if (window.Kairos && window.Kairos.effacerErreurs) window.Kairos.effacerErreurs(f);
      f.querySelectorAll('select[data-chip-select], .dropzone-input').forEach(function (x) { x.dispatchEvent(new Event('change')); });
    });
    delete dialog.dataset.contexte;
  }
  dialog.addEventListener('submit', function (e) {
    var form = e.target;
    var K = window.Kairos;
    if (e.defaultPrevented || !K || !K.requete || !form.closest('.intent-panel')) return;
    e.preventDefault();
    if (K.lectureSeule && K.lectureSeule()) { K.toast(K.MESSAGE_LECTURE_SEULE, { type: 'info' }); return; }
    var envoyeur = e.submitter || form.querySelector('button[type="submit"]');
    if (envoyeur && envoyeur.getAttribute('aria-disabled') === 'true') return;
    var selecteurFil = dialog.getAttribute('data-fil');
    var fil = selecteurFil ? document.querySelector(selecteurFil) : null;
    K.requete({
      url: form.action, methode: 'POST', corps: new FormData(form),
      cible: fil ? selecteurFil : '#dialog-nouveau-post', mode: fil ? 'avant' : 'outer',
      historique: 'aucun', declencheur: envoyeur || form
    }).then(function (res) {
      if (!res || res.statut < 200 || res.statut >= 300 || res.redirection) return;
      viderFormulaires();
      // Le bouton qui a ouvert la fenêtre a pu être remplacé (carte des
      // tâches mise à jour) : le focus va à son homologue, une fois la
      // fenêtre fermée (sortie animée).
      var apres = function () {
        dialog.close();
        if (!ouvreur || !document.contains(ouvreur)) {
          var homologue = (ouvreur && ouvreur.id && document.getElementById(ouvreur.id)) || document.querySelector('[data-open-post-dialog]:not([disabled])');
          if (homologue) homologue.focus();
        }
      };
      var FW = window.KairosFloatingWindow;
      if (FW && FW.fermer) FW.fermer(dialog, apres); else apres();
    });
  });

  // Revue d'interaction P0-8 : Entrée dans un champ d'une ligne passe au
  // champ suivant (elle publiait la tâche, échéance par défaut et sans
  // intervenant) ; publier = le bouton, ou Ctrl/⌘ + Entrée.
  function visibleEtActif(el) {
    return !el.disabled && el.offsetParent !== null && getComputedStyle(el).visibility !== 'hidden';
  }
  dialog.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' || e.isComposing || e.altKey || e.shiftKey) return;
    var champ = e.target;
    var form = champ && (champ.form || (champ.closest && champ.closest('form')));
    if (!form || !form.closest('.intent-panel')) return;
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      if (form.requestSubmit) form.requestSubmit(); else form.submit();
      return;
    }
    if (e.defaultPrevented || champ.tagName !== 'INPUT' || /^(button|submit|reset|checkbox|radio|file|image)$/i.test(champ.type)) return;
    e.preventDefault();
    var champs = Array.prototype.filter.call(form.querySelectorAll('input:not([type=hidden]), select, textarea, button'), visibleEtActif);
    var suivant = champs[champs.indexOf(champ) + 1];
    if (suivant) suivant.focus();
  });

  dialog.querySelectorAll('[data-close-post-dialog]').forEach(function (b) {
    b.addEventListener('click', function () {
      (window.KairosFloatingWindow && window.KairosFloatingWindow.fermer ? window.KairosFloatingWindow.fermer(dialog) : dialog.close());
    });
  });
  // Clic sur le fond (backdrop) du <dialog> : ferme, SAUF si un champ a
  // été modifié depuis l'ouverture (voir floating-window.js, règle commune
  // à toutes les fenêtres flottantes). Il faut alors passer par
  // "Annuler"/le X pour fermer explicitement.
  window.KairosFloatingWindow.attacherFermetureAuFond(dialog);
  // « Abandonner » (question d'Échap ou du fond) vide la saisie (P2-7).
  dialog.addEventListener('kairos:abandon', viderFormulaires);

  // Retour visuel du glisser-déposer pour les pièces jointes — géré par
  // app/static/js/dropzone.js (s'initialise seul sur tout le document).
  appliquerProjet();
})();

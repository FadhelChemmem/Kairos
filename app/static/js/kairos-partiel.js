/* Kairos — mises à jour partielles, toasts, confirmation en ligne (lot 13,
 * audit UX §4.3 et §4.5). Mode d'emploi : docs/partiel.md.
 *
 * Attributs déclaratifs (sans JavaScript, le formulaire ou le lien garde son
 * comportement habituel — POST puis redirection) :
 *   data-partiel="#cible"            <form>, <a>, ou bouton d'envoi : remplace #cible par la réponse
 *   data-partiel-mode="outer|inner|avant|apres|retirer"   (défaut outer)
 *   data-partiel-historique="push|replace|aucun"          (défaut : push pour un GET, aucun pour un POST)
 *   data-partiel-auto="input:250 change"                  <form method=get> : envoi automatique (filtres)
 *   data-optimiste="nom"             Kairos.optimistes[nom](élément) applique l'état et renvoie l'annulation
 *   data-confirmer="texte"           confirmation en ligne (au lieu de confirm())
 *   data-focus-apres="#sel"          élément à focaliser après le remplacement
 *   data-partiel-oob                 (dans la réponse) élément qui remplace son homonyme (même id) hors de la cible
 *   data-partiel-oob="avant"         (dans la réponse) enfants nouveaux insérés en tête de l'homonyme (fil)
 *   data-partiel-defiler="haut"      pagination : haut de la cible ramené à l'écran
 *   data-partiel-vide                état vide retiré quand la liste reçoit ses premiers éléments
 * 422 en JSON {message, champs} : champs signalés dans le formulaire envoyé (Kairos.marquerErreurs).
 * Contrat serveur : app/partiel.py (X-Kairos-Partiel, X-Kairos-Toasts, 401/403/409/422).
 *
 * Algorithme d'une requête : la précédente sur la même cible est annulée ;
 * focus et position de la cible mémorisés ; état optimiste appliqué tout de
 * suite ; après 150 ms sans réponse, la cible passe en aria-busy +
 * .k-en-cours (affiché au moins 300 ms) ; à la réponse, remplacement (View
 * Transition si disponible et sans mouvement réduit), focus rendu, défilement
 * compensé, toasts, historique, puis évènement « kairos:fragment » ({racine})
 * auquel les composants (chip-select, search-combobox, comment-composer,
 * dropzone…) répondent en s'initialisant sur la racine.
 *
 * Toasts : zone #k-toasts en popover, déplacée dans la fenêtre modale
 * ouverte ; texte lu par les régions live persistantes #k-annonce /
 * #k-alerte (Kairos.annoncer, aussi utilisable seul) ; Ctrl/⌘ + Z hors d'un
 * champ = « Annuler » du dernier toast (Kairos.annulerDernier).
 *
 * Exporté pour les tests node (tests_js/kairos-partiel.test.mjs) :
 * module.exports.creer(env) ; dans la page : window.Kairos.
 */
(function (global, fabrique) {
  if (typeof module === 'object' && module.exports) {
    module.exports = { creer: fabrique };
  } else if (global.document) {
    global.Kairos = fabrique({ window: global, document: global.document });
    global.Kairos.demarrer();
  }
})(typeof self !== 'undefined' ? self : this, function creer(env) {
  'use strict';
  var win = env.window;
  var doc = env.document;
  var fetchFn = env.fetch || function (u, o) { return win.fetch(u, o); };
  // Lot 24 (contre-expertise FR7) : navigateur sans fetch — formulaires et
  // liens gardent leur comportement natif (navigation complète).
  function sansFetch() { return !env.fetch && typeof win.fetch !== 'function'; }
  var maintenant = env.maintenant || function () { return Date.now(); };
  var minuter = env.setTimeout || function (f, d) { return win.setTimeout(f, d); };
  var annulerMinuteur = env.clearTimeout || function (t) { return win.clearTimeout(t); };

  var DELAI_INDICATEUR = 150;
  var DUREE_MIN_INDICATEUR = 300;
  var MAX_TOASTS = 3;
  var DUREE_TOAST = 5000;
  var DUREE_TOAST_ACTION = 10000;

  var K = {
    DELAI_INDICATEUR: DELAI_INDICATEUR,
    DUREE_MIN_INDICATEUR: DUREE_MIN_INDICATEUR,
    optimistes: {},
    _enCours: {},
    _seq: 0
  };

  function mouvementReduit() {
    try { return !!(win.matchMedia && win.matchMedia('(prefers-reduced-motion: reduce)').matches); } catch (e) { return false; }
  }
  K.mouvementReduit = mouvementReduit;

  function lectureSeule() {
    return !!(doc.documentElement && doc.documentElement.hasAttribute('data-lecture-seule'));
  }
  K.lectureSeule = lectureSeule;
  K.MESSAGE_LECTURE_SEULE = 'Lecture seule («\u00a0Voir comme\u00a0»)\u00a0: rien n’est modifié. Revenez à votre compte pour agir.';

  /* ------------------------------------------------------------------ */
  /* Outils                                                               */
  /* ------------------------------------------------------------------ */

  /** « input:250 change » -> { input: 250, change: 0 } */
  K.lireAuto = function (valeur) {
    var res = {};
    String(valeur || '').split(/[\s,]+/).forEach(function (morceau) {
      if (!morceau) return;
      var p = morceau.split(':');
      var d = parseInt(p[1], 10);
      res[p[0]] = isNaN(d) ? (p[0] === 'input' ? 250 : 0) : Math.max(0, d);
    });
    return res;
  };

  /** En-tête X-Kairos-Toasts (JSON encodé en pourcents) -> liste. */
  K.lireToasts = function (entete) {
    if (!entete) return [];
    try {
      var liste = JSON.parse(decodeURIComponent(entete));
      return Array.isArray(liste) ? liste.filter(function (t) { return t && t.texte; }) : [];
    } catch (e) { return []; }
  };

  /** Adresse GET d'un formulaire : champs non vides seulement. */
  K.urlFormulaire = function (form, envoyeur) {
    var action = (envoyeur && envoyeur.getAttribute && envoyeur.getAttribute('formaction')) || form.getAttribute('action') || win.location.pathname;
    var url = new URL(action, win.location.href);
    var donnees = new win.FormData(form);
    if (envoyeur && envoyeur.name) donnees.append(envoyeur.name, envoyeur.value || '');
    var params = new URLSearchParams();
    donnees.forEach(function (v, k) {
      if (typeof v === 'string' && v !== '' && k !== 'csrf_token') params.append(k, v);
    });
    var qs = params.toString();
    return url.pathname + (qs ? '?' + qs : '');
  };

  /** Historique par défaut : push pour un GET, aucun pour un POST. */
  K.historiqueParDefaut = function (methode, valeur) {
    if (valeur === 'push' || valeur === 'replace' || valeur === 'aucun') return valeur;
    return String(methode || 'GET').toUpperCase() === 'GET' ? 'push' : 'aucun';
  };

  /** Message lisible d'une réponse d'erreur (JSON {message} ou texte). */
  K.messageErreur = function (statut, texte) {
    try {
      var j = JSON.parse(texte);
      if (j && j.message) return String(j.message);
    } catch (e) { /* pas du JSON */ }
    if (statut === 403) return 'Action non autorisée.';
    if (statut === 404) return 'Élément introuvable\u00a0: il a peut-être été supprimé. Rechargez la page.';
    if (statut === 409) return 'Conflit\u00a0: l’élément a changé entre-temps. Rechargez la page.';
    if (statut >= 500) return 'Erreur du serveur\u00a0: réessayez dans un instant.';
    return 'La demande n’a pas abouti.';
  };

  function echapperSel(v) {
    return win.CSS && win.CSS.escape ? win.CSS.escape(v) : String(v).replace(/["\\]/g, '\\$&');
  }

  function focalisable(el) {
    return !!el && (el.tabIndex >= 0 || /^(A|BUTTON|INPUT|SELECT|TEXTAREA)$/.test(el.tagName));
  }

  /* ------------------------------------------------------------------ */
  /* Ré-initialisation des composants après un remplacement               */
  /* ------------------------------------------------------------------ */
  var initialiseurs = [];
  /** fn(racine) : appelée au démarrage (document) puis pour chaque fragment inséré. */
  K.surFragment = function (fn) { initialiseurs.push(fn); };
  K.initialiser = function (racine) {
    racine = racine || doc;
    initialiseurs.forEach(function (fn) {
      try { fn(racine); } catch (e) { if (win.console) win.console.error(e); }
    });
    try {
      doc.dispatchEvent(new win.CustomEvent('kairos:fragment', { detail: { racine: racine } }));
    } catch (e) { /* CustomEvent indisponible */ }
  };

  /* ------------------------------------------------------------------ */
  /* Toasts                                                               */
  /* ------------------------------------------------------------------ */
  var ICONES = {
    succes: '<path d="M20 6 9 17l-5-5"/>',
    erreur: '<path d="M12 7v6"/><path d="M12 17h.01"/>',
    avertissement: '<path d="M12 7v6"/><path d="M12 17h.01"/>',
    info: '<path d="M12 11v6"/><path d="M12 7h.01"/>'
  };

  /* Zone des toasts (#k-toasts, popover="manual") et régions live
   * persistantes (#k-annonce role=status, #k-alerte role=alert), déclarées
   * vides au chargement dans base.html (audit a11y R2). Une fenêtre modale
   * (showModal) rend le reste de la page inerte et passe au-dessus de tout
   * z-index : la zone entière (toasts ET régions live) est alors déplacée
   * dans la dernière fenêtre modale ouverte et remise dans la couche
   * supérieure (showPopover) — « Annuler », « Réessayer » restent visibles,
   * cliquables et annoncés (bug UX N1). Retour dans <body> à la fermeture. */
  function zoneToasts() {
    var z = doc.getElementById('k-toasts');
    if (!z) {
      z = doc.createElement('div');
      z.id = 'k-toasts';
      z.className = 'k-toasts';
      z.setAttribute('popover', 'manual');
      doc.body.appendChild(z);
    }
    return z;
  }

  function regionLive(id, role) {
    var r = doc.getElementById(id);
    if (!r) {
      r = doc.createElement('div');
      r.id = id;
      r.className = 'sr-only';
      r.setAttribute('role', role);
      r.setAttribute('aria-atomic', 'true');
      zoneToasts().appendChild(r);
    }
    return r;
  }

  function estModale(d) {
    try { return d.matches(':modal'); } catch (e) { return false; }
  }

  var modales = [];
  /** Zone placée dans la dernière fenêtre modale ouverte (sinon <body>), puis
   *  repassée au premier plan de la couche supérieure. */
  function placerZone() {
    var z = zoneToasts();
    modales = modales.filter(function (d) { return doc.contains(d) && d.hasAttribute('open') && estModale(d); });
    Array.prototype.forEach.call(doc.querySelectorAll('dialog[open]'), function (d) {
      if (modales.indexOf(d) === -1 && estModale(d)) modales.push(d);
    });
    var parent = modales.length ? modales[modales.length - 1] : doc.body;
    if (z.parentNode !== parent) {
      var focus = z.contains(doc.activeElement) ? doc.activeElement : null;
      parent.appendChild(z);
      if (focus && focus.focus) focus.focus({ preventScroll: true });
    }
    remonterZone(z);
    return z;
  }
  K.placerZoneToasts = placerZone;

  function remonterZone(z) {
    if (typeof z.showPopover !== 'function') return;
    try {
      if (z.matches(':popover-open')) z.hidePopover();
      z.showPopover();
    } catch (e) { /* popover indisponible : z-index de la zone */ }
  }

  function surveillerFenetres() {
    if (!win.MutationObserver) return;
    var obs = new win.MutationObserver(function (liste) {
      for (var i = 0; i < liste.length; i++) {
        if (liste[i].target && liste[i].target.tagName === 'DIALOG') { placerZone(); return; }
      }
    });
    obs.observe(doc.body, { attributes: true, attributeFilter: ['open'], subtree: true });
    doc.addEventListener('close', function (e) { if (e.target && e.target.tagName === 'DIALOG') placerZone(); }, true);
  }

  /**
   * K.annoncer(texte, { urgent }) : texte lu par les lecteurs d'écran, sans
   * rien afficher. Régions persistantes déclarées au chargement : #k-annonce
   * (role=status, poli) ou, si urgent, #k-alerte (role=alert). La région est
   * vidée puis remplie 30 ms plus tard (un même texte répété est relu) ; les
   * annonces d'une même rafale sont lues ensemble. À utiliser pour tout
   * changement que l'œil voit et que l'oreille ne saurait pas : Daily log
   * (« Journée enregistrée »), changement de tâche par ↑ / ↓, etc. Les
   * toasts (K.toast) s'annoncent déjà par ce moyen.
   */
  var fileAnnonces = {};
  K.annoncer = function (texte, opts) {
    texte = String(texte == null ? '' : texte).trim();
    if (!texte) return;
    var urgent = !!(opts && (opts.urgent || opts.type === 'erreur'));
    var id = urgent ? 'k-alerte' : 'k-annonce';
    var region = regionLive(id, urgent ? 'alert' : 'status');
    var f = fileAnnonces[id] || (fileAnnonces[id] = { textes: [], minuteur: null });
    f.textes.push(texte);
    if (f.minuteur) return;
    region.textContent = '';
    f.minuteur = minuter(function () {
      var lu = f.textes.join(' ');
      region.textContent = lu;
      f.textes = [];
      f.minuteur = null;
      // Région vidée ensuite (rien de périmé au curseur de lecture).
      minuter(function () { if (region.textContent === lu && !f.minuteur) region.textContent = ''; }, 10000);
    }, 30);
  };

  var RE_ANNULER = /^Annuler\b/;
  /** Texte annoncé pour un toast : son message, et comment atteindre son action. */
  K.texteAnnonce = function (texte, action) {
    var t = String(texte);
    if (action && action.libelle) {
      t += RE_ANNULER.test(action.libelle)
        ? ' «\u00a0' + action.libelle + '\u00a0»\u00a0: Ctrl+Z.'
        : ' Bouton «\u00a0' + action.libelle + '\u00a0» dans le message.';
    }
    return t;
  };

  /** Ctrl/⌘ + Z hors d'un champ de saisie : bouton « Annuler » du toast le
   *  plus récent encore affiché (10 s ; minuterie suspendue au survol et au
   *  focus) — l'action reste accessible sans aller chercher le toast au
   *  clavier (audit a11y N4). Renvoie true si une action a été déclenchée. */
  K.annulerDernier = function () {
    var z = doc.getElementById('k-toasts');
    if (!z) return false;
    var toasts = z.querySelectorAll('.k-toast:not(.k-sortie)');
    for (var i = toasts.length - 1; i >= 0; i--) {
      var boutons = toasts[i].querySelectorAll('.k-toast-action');
      for (var j = 0; j < boutons.length; j++) {
        if (boutons[j].hasAttribute('data-k-annuler') || RE_ANNULER.test((boutons[j].textContent || '').trim())) {
          boutons[j].click();
          return true;
        }
      }
    }
    return false;
  };

  function dansUnChamp(el) {
    if (!el || el === doc.body) return false;
    if (el.isContentEditable) return true;
    var t = el.tagName;
    if (t === 'TEXTAREA' || t === 'SELECT') return true;
    if (t === 'INPUT') return !/^(button|submit|reset|checkbox|radio|range|color|file)$/i.test(el.type);
    return false;
  }

  function fermerToast(el, rendreFocus) {
    if (!el || el._ferme) return;
    el._ferme = true;
    el._avaitFocus = el.contains(doc.activeElement);
    annulerMinuteur(el._minuteur);
    var retirer = function () {
      // Focus rendu seulement s'il est encore dans ce toast (ou perdu) : un
      // focus posé ailleurs pendant la sortie (130 ms) n'est pas repris.
      var actif = doc.activeElement;
      var avaitFocus = el.contains(actif) || ((!actif || actif === doc.body) && el._avaitFocus);
      if (el.parentNode) el.parentNode.removeChild(el);
      if (avaitFocus && rendreFocus !== false) {
        // Revue d'interaction P1-5 : le focus revient au contrôle d'où vient
        // l'action (ou à son homologue), jamais hors d'une fenêtre ouverte.
        var autre = doc.querySelector('#k-toasts .k-toast .k-toast-fermer');
        if (autre) autre.focus();
        else if (!focusOrigine(el)) {
          var m = doc.getElementById('contenu');
          if (m) m.focus({ preventScroll: true });
        }
      }
    };
    if (mouvementReduit()) retirer();
    else {
      el.classList.add('k-sortie');
      // P2-4 : le toast se replie en hauteur avant d'être retiré — les
      // autres glissent au lieu de sauter.
      minuter(function () {
        if (!el.parentNode) return;
        var h = el.offsetHeight;
        el.style.height = h + 'px';
        el.style.overflow = 'hidden';
        void el.offsetHeight;
        el.classList.add('k-repli');
        minuter(retirer, 140);
      }, 120);
    }
  }
  /** Rend le focus au contrôle d'origine d'un toast (ou à son homologue de
   *  même id après remplacement ; à défaut, à la fenêtre ouverte). */
  function focusOrigine(t) {
    var el = t && t._origine && doc.contains(t._origine) ? t._origine : null;
    if (!el && t && t._origineId) el = doc.getElementById(t._origineId);
    if (el && el.closest && el.closest('[hidden], dialog:not([open]), [inert]')) el = null;
    if (!el) {
      var d = doc.querySelector('dialog[open]');
      if (d) el = d.querySelector('[data-partiel-titre]') || d;
    }
    if (!el || !el.focus) return false;
    if (!focalisable(el)) el.setAttribute('tabindex', '-1');
    el.focus({ preventScroll: true });
    return doc.activeElement === el;
  }
  K.fermerToast = fermerToast;

  /**
   * K.toast(texte, { type: 'succes'|'erreur'|'avertissement'|'info',
   *                  action: { libelle, surClic(), url, methode, donnees, cible, mode, focus },
   *                  duree, annonce })
   * Le toast visuel n'est pas une région live : son texte (ou `annonce`) est
   * lu par K.annoncer (#k-alerte pour une erreur, #k-annonce sinon).
   */
  K.toast = function (texte, opts) {
    opts = opts || {};
    var type = ['succes', 'erreur', 'avertissement', 'info'].indexOf(opts.type) >= 0 ? opts.type : 'succes';
    var zone = placerZone();
    var presents = zone.querySelectorAll('.k-toast:not(.k-sortie)');
    for (var i = 0; i <= presents.length - MAX_TOASTS; i++) fermerToast(presents[i], false);
    // Un seul « Annuler » vivant (retour du 17/10) : la souris et Ctrl+Z
    // visent la même action ; l'ancien toast « Annuler » se ferme.
    if (opts.action && opts.action.libelle && RE_ANNULER.test(opts.action.libelle)) {
      Array.prototype.forEach.call(presents, function (t) {
        if (t.querySelector && t.querySelector('[data-k-annuler]')) fermerToast(t, false);
      });
    }

    var el = doc.createElement('div');
    el.className = 'k-toast k-toast-' + type;
    // Contrôle d'origine (P1-5) : le focus y revient après « Annuler ».
    var origine = doc.activeElement;
    if (origine && origine !== doc.body && origine !== doc.documentElement && !(origine.closest && origine.closest('#k-toasts'))) {
      el._origine = origine;
      el._origineId = origine.id || null;
    }
    el.innerHTML = '<span class="k-toast-icone" aria-hidden="true"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">'
      + (ICONES[type] || ICONES.info) + '</svg></span><span class="k-toast-texte"></span><span class="k-toast-actions"></span>';
    el.querySelector('.k-toast-texte').textContent = String(texte);
    var actions = el.querySelector('.k-toast-actions');
    if (opts.action && opts.action.libelle) {
      var b = doc.createElement('button');
      b.type = 'button';
      b.className = 'k-toast-action';
      b.textContent = opts.action.libelle;
      if (RE_ANNULER.test(opts.action.libelle)) {
        b.setAttribute('data-k-annuler', '');
        b.setAttribute('aria-keyshortcuts', 'Control+Z');
      }
      b.addEventListener('click', function () {
        var focusDedans = el.contains(doc.activeElement);
        fermerToast(el, false);
        if (focusDedans) focusOrigine(el);
        if (typeof opts.action.surClic === 'function') opts.action.surClic();
        else K.rejouerAction(opts.action);
      });
      actions.appendChild(b);
    }
    var x = doc.createElement('button');
    x.type = 'button';
    x.className = 'k-toast-fermer';
    x.setAttribute('aria-label', 'Fermer le message');
    x.innerHTML = '<svg aria-hidden="true" focusable="false" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
    x.addEventListener('click', function () { fermerToast(el); });
    actions.appendChild(x);
    zone.appendChild(el);
    // annonce: false — l'appelant annonce lui-même (Daily log) : pas de double lecture.
    if (opts.annonce !== false) K.annoncer(opts.annonce || K.texteAnnonce(texte, opts.action), { urgent: type === 'erreur' });

    // Succès / info : effacement automatique, suspendu au survol et au focus
    // (règle du lot 10) ; erreur et avertissement : jusqu'à fermeture.
    var duree = opts.duree !== undefined ? opts.duree : (type === 'erreur' || type === 'avertissement' ? 0 : (opts.action ? DUREE_TOAST_ACTION : DUREE_TOAST));
    if (duree > 0) {
      var restant = duree, debut = 0;
      var lancer = function () { debut = maintenant(); el._minuteur = minuter(function () { fermerToast(el); }, restant); };
      var suspendre = function () { annulerMinuteur(el._minuteur); restant = Math.max(1500, restant - (maintenant() - debut)); };
      el.addEventListener('mouseenter', suspendre);
      el.addEventListener('focusin', suspendre);
      el.addEventListener('mouseleave', function () { if (!el.contains(doc.activeElement)) lancer(); });
      el.addEventListener('focusout', function (e) { if (!el.contains(e.relatedTarget)) lancer(); });
      lancer();
    }
    return el;
  };

  /** Liste de toasts {type, texte, action} (en-tête serveur, flash initiaux). */
  K.toasts = function (liste) {
    (liste || []).forEach(function (t) { K.toast(t.texte, { type: t.type, action: t.action }); });
  };

  /** Action d'un toast décrite par le serveur : rejouée en requête partielle. */
  K.rejouerAction = function (a) {
    if (!a || !a.url) return null;
    var corps = null;
    if (String(a.methode || 'POST').toUpperCase() !== 'GET') {
      corps = new win.FormData();
      Object.keys(a.donnees || {}).forEach(function (k) { corps.append(k, a.donnees[k]); });
    }
    if (!a.cible) { win.location.assign(a.url); return null; }
    return K.requete({ url: a.url, methode: a.methode || 'POST', corps: corps, cible: a.cible, mode: a.mode || 'outer',
                       historique: 'aucun', focusApres: a.focus || null });
  };

  /* ------------------------------------------------------------------ */
  /* Confirmation en ligne (remplace window.confirm)                     */
  /* ------------------------------------------------------------------ */
  var confirmationOuverte = null;

  /**
   * K.confirmer(ancre, texte, { libelleOk, libelleAnnuler, danger }) -> Promise<boolean>
   * Dans une <dialog>, la question s'affiche en tête de la fenêtre ; ailleurs,
   * en bulle sous l'élément. Échap ou clic ailleurs = non. Le focus revient
   * à l'ancre.
   */
  K.confirmer = function (ancre, texte, opts) {
    opts = opts || {};
    if (confirmationOuverte) confirmationOuverte(false);
    return new Promise(function (resoudre) {
      var boite = doc.createElement('div');
      var id = 'k-confirmation-' + (++K._seq);
      boite.className = 'k-confirmation';
      boite.setAttribute('role', 'alertdialog');
      boite.setAttribute('aria-labelledby', id);
      boite.innerHTML = '<p></p><div class="k-confirmation-actions"></div>';
      var p = boite.querySelector('p');
      p.id = id;
      p.textContent = texte;
      var ok = doc.createElement('button');
      ok.type = 'button';
      ok.className = 'btn-primaire btn-petit' + (opts.danger ? ' k-bouton-danger' : '');
      ok.textContent = opts.libelleOk || 'Confirmer';
      var non = doc.createElement('button');
      non.type = 'button';
      non.className = 'btn btn-petit';
      non.textContent = opts.libelleAnnuler || 'Annuler';
      var actions = boite.querySelector('.k-confirmation-actions');
      actions.appendChild(ok);
      actions.appendChild(non);

      var fenetre = ancre && ancre.closest ? ancre.closest('dialog') : null;
      if (fenetre) {
        boite.classList.add('k-confirmation-bloc');
        fenetre.insertBefore(boite, fenetre.firstChild);
        // Par-dessus le haut de la fenêtre, sans pousser son contenu
        // (revue d'interaction P1-1) : sa hauteur est rendue en marge basse.
        boite.style.marginBottom = -boite.offsetHeight + 'px';
      } else {
        doc.body.appendChild(boite);
        var r = ancre && ancre.getBoundingClientRect ? ancre.getBoundingClientRect() : { left: 16, bottom: 80, top: 60 };
        var larg = boite.offsetWidth || 300;
        var haut = boite.offsetHeight || 90;
        var gauche = Math.min(Math.max(8, r.left), (win.innerWidth || 1024) - larg - 8);
        var y = r.bottom + 6;
        if (y + haut > (win.innerHeight || 768) - 8 && r.top - haut - 6 > 8) y = r.top - haut - 6;
        boite.style.left = (gauche + (win.scrollX || 0)) + 'px';
        boite.style.top = (y + (win.scrollY || 0)) + 'px';
      }

      var fini = false;
      function terminer(valeur) {
        if (fini) return;
        fini = true;
        confirmationOuverte = null;
        doc.removeEventListener('mousedown', dehors, true);
        if (boite.parentNode) boite.parentNode.removeChild(boite);
        if (ancre && ancre.focus && doc.contains(ancre)) ancre.focus({ preventScroll: true });
        resoudre(valeur);
      }
      function dehors(e) { if (!boite.contains(e.target)) terminer(false); }
      confirmationOuverte = terminer;
      ok.addEventListener('click', function () { terminer(true); });
      non.addEventListener('click', function () { terminer(false); });
      boite.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); terminer(false); }
        else if (e.key === 'Tab') {
          // Focus gardé dans la question tant qu'elle est ouverte.
          var premier = ok, dernier = non;
          if (e.shiftKey && doc.activeElement === premier) { e.preventDefault(); dernier.focus(); }
          else if (!e.shiftKey && doc.activeElement === dernier) { e.preventDefault(); premier.focus(); }
        }
      });
      minuter(function () { doc.addEventListener('mousedown', dehors, true); }, 0);
      (opts.danger ? non : ok).focus();
    });
  };

  /* ------------------------------------------------------------------ */
  /* Session expirée (401)                                               */
  /* ------------------------------------------------------------------ */
  K.sessionExpiree = function (urlConnexion) {
    var url;
    try {
      url = new URL(urlConnexion || '/connexion', win.location.href);
      url.searchParams.set('next', win.location.pathname + win.location.search);
    } catch (e) { url = '/connexion'; }
    var d = doc.getElementById('k-session-expiree');
    if (!d) {
      d = doc.createElement('dialog');
      d.id = 'k-session-expiree';
      d.className = 'post-dialog';
      d.setAttribute('aria-labelledby', 'k-session-expiree-titre');
      d.innerHTML = '<h2 id="k-session-expiree-titre" class="carte-titre" style="font-size:16px;margin:0 0 8px;">Session expirée</h2>'
        + '<p style="margin:0 0 16px;font-size:13.5px;color:var(--text-secondary);">Reconnectez-vous pour continuer\u00a0: votre saisie reste dans la page, rien n’a été envoyé.</p>'
        + '<div class="k-confirmation-actions"><a class="btn-primaire" data-k-reconnexion target="_blank" rel="opener">Se reconnecter</a>'
        + '<button type="button" class="btn" data-k-fermer>Fermer</button></div>';
      doc.body.appendChild(d);
      d.querySelector('[data-k-fermer]').addEventListener('click', function () { d.close(); });
    }
    d.querySelector('[data-k-reconnexion]').setAttribute('href', String(url));
    if (!d.open && typeof d.showModal === 'function') d.showModal();
    else d.setAttribute('open', '');
    var lien = d.querySelector('[data-k-reconnexion]');
    if (lien) lien.focus();
    return d;
  };

  /* ------------------------------------------------------------------ */
  /* Barre de progression de navigation                                  */
  /* ------------------------------------------------------------------ */
  var progression = { el: null, minuteur: null };
  function barre() {
    if (!progression.el) {
      progression.el = doc.createElement('div');
      progression.el.className = 'k-progression';
      progression.el.setAttribute('aria-hidden', 'true');
      doc.body.appendChild(progression.el);
    }
    return progression.el;
  }
  K.progressionDebut = function () {
    annulerMinuteur(progression.minuteur);
    progression.minuteur = minuter(function () {
      var b = barre();
      b.classList.remove('k-fin');
      b.style.setProperty('--k-progression', '0');
      b.classList.add('k-actif');
      // Deux images plus tard, la barre glisse vers 80 % en 2 s.
      win.requestAnimationFrame(function () { win.requestAnimationFrame(function () { b.style.setProperty('--k-progression', '0.8'); }); });
    }, 120);
  };
  K.progressionFin = function () {
    annulerMinuteur(progression.minuteur);
    if (!progression.el) return;
    var b = progression.el;
    b.classList.add('k-fin');
    b.style.setProperty('--k-progression', '1');
    minuter(function () { b.classList.remove('k-actif'); b.style.setProperty('--k-progression', '0'); }, 220);
  };

  /* ------------------------------------------------------------------ */
  /* Remplacement d'un fragment                                          */
  /* ------------------------------------------------------------------ */
  function analyser(html) {
    var tpl = doc.createElement('template');
    tpl.innerHTML = html;
    return tpl.content;
  }

  /** Retire l'état vide (« Aucun post pour l'instant ») d'une liste qui
   *  reçoit ses premiers éléments. */
  function retirerVide(conteneur) {
    Array.prototype.slice.call(conteneur.children).forEach(function (n) {
      if (n.hasAttribute('data-partiel-vide')) conteneur.removeChild(n);
    });
  }

  /** data-partiel-oob="avant" : les enfants du fragment absents de la page
   *  (même id) sont insérés en tête du conteneur homonyme, surlignés. */
  /** Élément inséré en tête d'une liste : sa hauteur s'ouvre en 240 ms
   *  (le fil glisse au lieu de sauter — revue d'interaction P1-13). */
  function deplier(el) {
    if (mouvementReduit() || !el || !el.animate || !el.parentElement) return;
    var h = el.offsetHeight;
    if (!h) return;
    var ecart = parseFloat(win.getComputedStyle(el.parentElement).rowGap) || 0;
    el.style.overflow = 'hidden';
    var a = el.animate([{ height: '0px', marginBottom: (-ecart) + 'px' }, { height: h + 'px', marginBottom: '0px' }],
      { duration: 240, easing: 'cubic-bezier(.2, 0, 0, 1)' });
    a.onfinish = a.oncancel = function () { el.style.overflow = ''; };
  }
  K.deplier = deplier;

  function insererNouveaux(existant, el) {
    var nouveaux = Array.prototype.filter.call(el.children, function (n) {
      return !(n.id && doc.getElementById(n.id));
    });
    if (!nouveaux.length) return [];
    retirerVide(existant);
    var premier = existant.firstElementChild;
    nouveaux.forEach(function (n) {
      if (n.classList && !mouvementReduit()) n.classList.add('k-nouveau');
      existant.insertBefore(n, premier);
      deplier(n);
    });
    return nouveaux;
  }

  /** Remplace `cible` selon `mode` ; renvoie { racine, autres[] }. */
  K.remplacer = function (cible, html, mode, selecteur) {
    var frag = analyser(html);
    var autres = [];
    var tous = Array.prototype.slice.call(frag.querySelectorAll('[data-partiel-oob]'));
    // Élément hors cible imbriqué dans un autre : il part avec lui.
    var hauts = tous.filter(function (el) { return !(el.parentElement && el.parentElement.closest('[data-partiel-oob]')); });
    tous.forEach(function (el) { if (hauts.indexOf(el) === -1) el.removeAttribute('data-partiel-oob'); });
    hauts.forEach(function (el) {
      var oob = el.getAttribute('data-partiel-oob');
      el.parentNode.removeChild(el);
      el.removeAttribute('data-partiel-oob');
      var existant = el.id && doc.getElementById(el.id);
      if (!existant) return;
      if (oob === 'avant') {
        autres.push.apply(autres, insererNouveaux(existant, el));
      } else if (existant.getAttribute('role') === 'status' || existant.hasAttribute('aria-live')) {
        // Région live (compteur role=status) : texte mis à jour sur place,
        // pour que le lecteur d'écran l'annonce.
        if (existant.textContent !== el.textContent) existant.textContent = el.textContent;
      } else {
        existant.parentNode.replaceChild(el, existant);
        autres.push(el);
      }
    });
    var racine = cible;
    // Cible retirée entre-temps (fenêtre de tâche changée de tâche) : seuls
    // les éléments hors cible sont appliqués.
    if (!cible.parentNode || !doc.contains(cible)) return { racine: null, autres: autres };
    if (mode === 'avant' || mode === 'apres') retirerVide(cible);
    if (mode === 'inner') {
      while (cible.firstChild) cible.removeChild(cible.firstChild);
      cible.appendChild(frag);
    } else if (mode === 'avant') {
      var premier = frag.firstElementChild;
      if (premier && premier.classList && !mouvementReduit()) premier.classList.add('k-nouveau');
      cible.insertBefore(frag, cible.firstChild);
      racine = premier || cible;
      deplier(premier);
    } else if (mode === 'apres') {
      var debut = frag.firstElementChild;
      cible.appendChild(frag);
      racine = debut || cible;
    } else if (mode === 'retirer') {
      if (cible.parentNode) cible.parentNode.removeChild(cible);
      racine = null;
    } else {
      var elements = Array.prototype.filter.call(frag.childNodes, function (n) { return n.nodeType === 1; });
      var parent = cible.parentNode;
      parent.replaceChild(frag, cible);
      racine = (selecteur && doc.querySelector(selecteur)) || elements[0] || null;
    }
    return { racine: racine, autres: autres };
  };

  /* ------------------------------------------------------------------ */
  /* Requête partielle                                                   */
  /* ------------------------------------------------------------------ */
  function memoriserFocus() {
    var a = doc.activeElement;
    if (!a || a === doc.body || a === doc.documentElement) return null;
    return { el: a, id: a.id || null, cle: a.getAttribute && a.getAttribute('data-cle') };
  }

  function rendreFocus(memo, o, racine) {
    var actif = doc.activeElement;
    // Focus dans un toast qui se ferme (« Annuler ») : perdu lui aussi.
    var dansToastFerme = !!(actif && actif.closest && actif.closest('.k-sortie'));
    var perdu = !actif || actif === doc.body || !doc.contains(actif) || dansToastFerme || (memo && memo.el && !doc.contains(memo.el));
    if (!perdu) return;
    var el = null;
    if (memo && memo.id) el = doc.getElementById(memo.id);
    if (!el && memo && memo.cle) el = doc.querySelector('[data-cle="' + echapperSel(memo.cle) + '"]');
    if (!el && o.focusApres) el = doc.querySelector(o.focusApres);
    if (!el && racine && racine.nodeType === 1) {
      el = racine.querySelector('[data-partiel-titre]') || racine;
      if (!focalisable(el)) el.setAttribute('tabindex', '-1');
    }
    if (!el || !el.focus) return;
    // Champ à recherche : focus rendu par le code, la liste reste fermée
    // (« Daily log de » : elle cachait la page chargée — verif-final F4).
    var combobox = !!(el.classList && el.classList.contains('search-combobox-input') && el.dataset);
    if (combobox) el.dataset.sansOuverture = '1';
    el.focus({ preventScroll: true });
    if (combobox) delete el.dataset.sansOuverture;
  }

  function etatHistorique(o, saisie) {
    var st = {};
    var actuel = win.history.state;
    if (actuel && typeof actuel === 'object') Object.keys(actuel).forEach(function (k) { st[k] = actuel[k]; });
    st.kairosPartiel = { cible: o.cible, mode: o.mode || 'outer', saisie: saisie || null };
    // Lot 20 (revue QA n° 8) : l'entrée du panneau de tâche n'est pas
    // recopiée — fermer le panneau ne doit pas revenir en arrière par
    // dessus ce changement (onglet du fil, vue Deadlines).
    delete st.kairosTache;
    return st;
  }

  // Adresse affichée, tenue à jour à chaque écriture de l'historique (lot
  // 20) : Retour / Avancer entre deux entrées qui ne diffèrent que par la
  // tâche ouverte (?tache=) ne recharge rien — c'est le panneau qui suit.
  var adresseAffichee = win.location.href;
  ['pushState', 'replaceState'].forEach(function (nom) {
    var original = win.history && win.history[nom];
    if (typeof original !== 'function') return;
    win.history[nom] = function () {
      var r = original.apply(this, arguments);
      adresseAffichee = win.location.href;
      return r;
    };
  });
  function sansTache(adresse) {
    try {
      var u = new URL(adresse, win.location.href);
      u.searchParams.delete('tache');
      if (/^#tache-\d+$/.test(u.hash)) u.hash = '';
      return u.pathname + '?' + u.searchParams.toString() + u.hash;
    } catch (e) { return adresse; }
  }
  K.sansTache = sansTache;
  K.sansFetch = sansFetch;

  /**
   * K.requete({ url, methode, corps, cible, mode, historique, declencheur,
   *             optimiste, focusApres, transition, saisie }) -> Promise
   */
  K.requete = function (o) {
    var methode = String(o.methode || 'GET').toUpperCase();
    var cible = typeof o.cible === 'string' ? doc.querySelector(o.cible) : o.cible;
    var selecteur = typeof o.cible === 'string' ? o.cible : (cible && cible.id ? '#' + cible.id : null);
    if (!cible || !selecteur || sansFetch()) {
      // Cible absente : vraie navigation (GET) ; un POST reste à la charge de l'appelant.
      if (methode === 'GET') win.location.assign(o.url);
      return Promise.resolve(null);
    }
    var cle = selecteur;
    var precedente = K._enCours[cle];
    if (precedente) { precedente.abandonnee = true; if (precedente.ctrl) precedente.ctrl.abort(); precedente.nettoyer(); }

    var etat = { abandonnee: false, ctrl: win.AbortController ? new win.AbortController() : null };
    K._enCours[cle] = etat;
    var memo = memoriserFocus();
    // Position gardée quand l'œil est sur la cible (geste fait dedans) ou
    // qu'elle est au-dessus de l'écran. Une cible plus bas, que l'on ne
    // regarde pas (le fil sous le tableau quand on publie une tâche), ne
    // fait plus défiler la page.
    var ancre = null;
    // Cible dans une <dialog> (fixe) : la page derrière ne défile jamais
    // (bug UX N6 : confirmation de clôture, page décalée de 196 px).
    var cibleEnFenetre = !!(cible.closest && cible.closest('dialog'));
    if (cible.getBoundingClientRect && !cibleEnFenetre) {
      var hautCible = cible.getBoundingClientRect().top;
      var gesteDedans = !!(o.declencheur && o.declencheur.nodeType === 1 && cible.contains(o.declencheur));
      if (gesteDedans || hautCible < 0) ancre = hautCible;
    }
    var annuler = null;
    if (o.optimiste && K.optimistes[o.optimiste]) {
      try { annuler = K.optimistes[o.optimiste](o.declencheur || cible, o) || null; } catch (e) { annuler = null; }
    }
    var declencheur = o.declencheur && o.declencheur.setAttribute ? o.declencheur : null;
    if (declencheur) declencheur.setAttribute('aria-disabled', 'true');
    var formDeclencheur = declencheur && (declencheur.form || (declencheur.closest && declencheur.closest('form')));
    if (formDeclencheur && methode !== 'GET') K.effacerErreurs(formDeclencheur);

    var affichageDebut = 0;
    var minuteur = minuter(function () {
      affichageDebut = maintenant();
      cible.setAttribute('aria-busy', 'true');
      cible.classList.add('k-en-cours');
    }, DELAI_INDICATEUR);

    etat.nettoyer = function () {
      annulerMinuteur(minuteur);
      if (cible.removeAttribute) {
        cible.removeAttribute('aria-busy');
        cible.classList.remove('k-en-cours');
      }
      if (declencheur) declencheur.removeAttribute('aria-disabled');
      if (K._enCours[cle] === etat) delete K._enCours[cle];
    };

    function attendreIndicateur() {
      annulerMinuteur(minuteur);
      if (!affichageDebut) return Promise.resolve();
      var reste = DUREE_MIN_INDICATEUR - (maintenant() - affichageDebut);
      return reste > 0 ? new Promise(function (r) { minuter(r, reste); }) : Promise.resolve();
    }

    var entetes = { 'X-Kairos-Partiel': selecteur, 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'text/html, application/json;q=0.9' };
    // Lot 24 (filtres, Q13/Q14) : une page rejouée par Retour / Avancer
    // n'est pas un geste à l'écran — le serveur ne mémorise pas ses filtres.
    if (o.historiqueRejoue) entetes['X-Kairos-Historique'] = '1';
    var options = { method: methode, headers: entetes, credentials: 'same-origin' };
    if (etat.ctrl) options.signal = etat.ctrl.signal;
    if (methode !== 'GET' && o.corps) options.body = o.corps;

    function echec(message, reessayer) {
      if (annuler) { try { annuler(); } catch (e) { /* état déjà remplacé */ } }
      K.toast(message, { type: 'erreur', action: reessayer ? { libelle: 'Réessayer', surClic: function () { K.requete(o); } } : null });
    }

    return fetchFn(o.url, options).then(function (r) {
      return r.text().then(function (texte) { return { r: r, texte: texte }; });
    }).then(function (res) {
      return attendreIndicateur().then(function () { return res; });
    }).then(function (res) {
      if (etat.abandonnee) return null;
      etat.nettoyer();
      var r = res.r;
      var statut = r.status;
      K.toasts(K.lireToasts(r.headers.get('X-Kairos-Toasts')));
      var redirection = r.headers.get('X-Kairos-Redirection');
      if (redirection) {
        K.progressionDebut();
        win.location.assign(redirection);
        return { statut: statut, redirection: redirection };
      }
      if (statut === 401) {
        if (annuler) { try { annuler(); } catch (e) { /* */ } }
        K.sessionExpiree(r.headers.get('X-Kairos-Connexion'));
        return { statut: statut };
      }
      var donnees = null;
      if (/json/.test(r.headers.get('Content-Type') || '')) {
        try { donnees = JSON.parse(res.texte); } catch (e) { donnees = null; }
      }
      // 422 en JSON {message, champs: {nom: message}} : la saisie reste,
      // les champs en erreur sont signalés (aria-invalid, message relié).
      if (statut === 422 && donnees) {
        if (annuler) { try { annuler(); } catch (e) { /* */ } }
        var form = declencheur && (declencheur.form || (declencheur.closest && declencheur.closest('form')));
        var marques = donnees.champs && form ? K.marquerErreurs(form, donnees.champs) : 0;
        if (!marques) K.toast(donnees.message || K.messageErreur(statut, res.texte), { type: 'erreur' });
        return { statut: statut, donnees: donnees };
      }
      if ((statut >= 200 && statut < 300) || statut === 422) {
        if (statut === 204) return { statut: statut };
        if (donnees) return { statut: statut, donnees: donnees };
        return appliquer(res.texte, statut).then(function (racine) { return { statut: statut, racine: racine }; });
      }
      echec(K.messageErreur(statut, res.texte), statut >= 500);
      return { statut: statut, donnees: donnees };
    }).catch(function (err) {
      if (etat.abandonnee || (err && err.name === 'AbortError')) return null;
      etat.nettoyer();
      echec('Connexion au serveur impossible\u00a0: vérifiez le réseau, puis réessayez.', true);
      return { statut: 0, erreur: err };
    });

    function appliquer(texte, statut) {
      var resultat = null;
      // Pas de View Transition (capture de toute la page) quand une fenêtre
      // est ouverte ou que la cible est dans une fenêtre : simple fondu.
      var dansFenetre = !!((cible.closest && cible.closest('dialog')) || doc.querySelector('dialog[open]'));
      // Revue d'interaction P0-1 : ni pour une écriture ni pour une mise à
      // jour optimiste (déjà rendue) — la capture de la page avalait les
      // clics suivants (2 interrupteurs sur 4 pris à la suite).
      var sansVT = o.transition === false || dansFenetre || !!o.optimiste || methode !== 'GET';
      var faire = function () {
        resultat = K.remplacer(cible, texte, o.mode || 'outer', selecteur);
        if (resultat.racine && sansVT && !mouvementReduit() && resultat.racine.classList) {
          resultat.racine.classList.add('k-entree');
        }
      };
      var vt = null;
      if (!sansVT && doc.startViewTransition && !mouvementReduit()) {
        try { vt = doc.startViewTransition(faire); } catch (e) { vt = null; }
      }
      var fini = vt ? vt.updateCallbackDone.catch(function () { if (!resultat) faire(); }) : Promise.resolve(faire());
      return fini.then(function () {
        if (!resultat) return null;
        var racine = resultat.racine;
        // Ajout au début ou à la fin (« Charger plus ») : le repère reste la
        // cible elle-même, pas le premier élément ajouté (lot 13, phase 2).
        var mode = o.mode || 'outer';
        var repere = (mode === 'apres' || mode === 'avant') ? cible : racine;
        if (o.defiler === 'haut' && racine && racine.getBoundingClientRect) {
          // Pagination : le haut de la liste revient à l'écran (sous la
          // barre collante, scroll-padding-top).
          if (racine.getBoundingClientRect().top < 0 && racine.scrollIntoView) racine.scrollIntoView({ block: 'start' });
        } else if (ancre !== null && repere && repere.getBoundingClientRect && mode !== 'retirer') {
          var ecart = repere.getBoundingClientRect().top - ancre;
          if (Math.abs(ecart) > 1 && win.scrollBy) win.scrollBy(0, ecart);
        }
        if (methode === 'GET' && statut < 300) {
          var h = K.historiqueParDefaut(methode, o.historique);
          // Première entrée partielle d'une page sans filtre automatique
          // (lien data-partiel) : l'entrée de départ est marquée, Retour y
          // revient en partiel (lot 13, phase 2).
          if (h === 'push' && !(win.history.state && win.history.state.kairosPartiel)) {
            try { win.history.replaceState(etatHistorique(o, null), '', win.location.href); } catch (e) { /* Retour = rechargement */ }
          }
          // Lot 25 (UT-04) : « defaut=1 » (Effacer les filtres) a servi une
          // fois ; l'adresse gardée ne l'a plus (F5 ou Retour n'oublient
          // pas un choix fait entre-temps ailleurs).
          var adresseGardee = sansGeste(o.url);
          if (h === 'push') win.history.pushState(etatHistorique(o, o.saisie), '', adresseGardee);
          else if (h === 'replace') win.history.replaceState(etatHistorique(o, o.saisie), '', adresseGardee);
        }
        if (o.synchroniser) synchroniserFormulaires();
        if (racine) K.initialiser(racine);
        resultat.autres.forEach(function (el) { K.initialiser(el); });
        if (statut === 422 && racine && racine.querySelector) {
          var invalide = racine.querySelector('[aria-invalid="true"]');
          if (invalide) { invalide.focus(); return racine; }
        }
        rendreFocus(memo, o, racine);
        return racine;
      });
    }
  };

  /* ------------------------------------------------------------------ */
  /* Erreurs de saisie reliées aux champs (audit a11y I5)                 */
  /* ------------------------------------------------------------------ */
  /** Contrôle visible d'un champ (liste masquée remplacée par un
   *  composant : champ de recherche, puces). */
  function controleVisible(champ) {
    var suivant = champ.nextElementSibling;
    if (suivant && suivant.classList) {
      if (suivant.classList.contains('search-combobox-wrap')) return suivant.querySelector('.search-combobox-input') || champ;
      if (suivant.classList.contains('chip-select-wrap')) return suivant.querySelector('input, button') || champ;
    }
    return champ;
  }

  function retirerDescription(el, id) {
    var ids = (el.getAttribute('aria-describedby') || '').split(/\s+/).filter(function (x) { return x && x !== id; });
    if (ids.length) el.setAttribute('aria-describedby', ids.join(' '));
    else el.removeAttribute('aria-describedby');
  }

  /** `garderPlace` (champ corrigé à la frappe, lot 20 — test Chrome N4) :
   *  le message est masqué mais garde sa hauteur jusqu'au prochain envoi ;
   *  le bouton d'envoi ne remonte plus sous le pointeur. */
  function effacerErreurChamp(el, garderPlace) {
    var id = el.getAttribute('data-k-invalide');
    if (id === null) return;
    el.removeAttribute('aria-invalid');
    el.removeAttribute('data-k-invalide');
    if (id) {
      retirerDescription(el, id);
      var msg = doc.getElementById(id);
      if (msg && msg.hasAttribute('data-k-erreur')) {
        var autres = doc.querySelectorAll('[data-k-invalide="' + echapperSel(id) + '"]');
        if (autres.length || !msg.parentNode) return;
        if (garderPlace === true) {
          msg.style.visibility = 'hidden';
          msg.setAttribute('aria-hidden', 'true');
        } else {
          msg.parentNode.removeChild(msg);
        }
      }
    }
  }

  K.effacerErreurs = function (form) {
    if (!form || !form.querySelectorAll) return;
    Array.prototype.forEach.call(form.querySelectorAll('[data-k-invalide]'), function (el) { effacerErreurChamp(el); });
    Array.prototype.forEach.call(form.querySelectorAll('[data-k-erreur]'), function (m) { if (m.parentNode) m.parentNode.removeChild(m); });
  };

  /** champs : { nom: message } -> nombre de champs signalés ; focus sur le
   *  premier (ordre du formulaire). */
  K.marquerErreurs = function (form, champs) {
    var premiers = [];
    Object.keys(champs || {}).forEach(function (nom) {
      var champ = form.querySelector('[name="' + echapperSel(nom) + '"]:not([type=hidden])');
      if (!champ) return;
      var visible = controleVisible(champ);
      var id = 'err-' + (form.id || 'f' + (++K._seq)) + '-' + nom.replace(/[^\w-]/g, '_');
      var msg = doc.getElementById(id);
      if (!msg) {
        msg = doc.createElement('p');
        msg.id = id;
        msg.className = 'champ-erreur';
        msg.setAttribute('data-k-erreur', '');
        var rangee = champ.closest('.form-row') || champ.parentNode;
        rangee.appendChild(msg);
      }
      msg.textContent = champs[nom];
      msg.style.visibility = '';
      msg.removeAttribute('aria-hidden');
      [champ, visible].forEach(function (el) {
        el.setAttribute('aria-invalid', 'true');
        el.setAttribute('data-k-invalide', id);
        var ids = (el.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
        if (ids.indexOf(id) === -1) ids.unshift(id);
        el.setAttribute('aria-describedby', ids.join(' '));
      });
      premiers.push(visible);
    });
    premiers.sort(function (a, b) { return a.compareDocumentPosition(b) & 4 ? -1 : 1; });
    if (premiers[0] && premiers[0].focus) premiers[0].focus();
    return premiers.length;
  };

  /* ------------------------------------------------------------------ */
  /* Optimistes fournis                                                  */
  /* ------------------------------------------------------------------ */
  /** Interrupteur (role=switch) ou bouton à état (aria-pressed). */
  K.optimistes.bascule = function (el) {
    var b = el.matches && el.matches('[role="switch"], [aria-pressed]') ? el : (el.querySelector && el.querySelector('[role="switch"], [aria-pressed]'));
    if (!b) return null;
    var attr = b.hasAttribute('aria-checked') ? 'aria-checked' : 'aria-pressed';
    var avant = b.getAttribute(attr);
    b.setAttribute(attr, avant === 'true' ? 'false' : 'true');
    return function () { if (doc.contains(b)) b.setAttribute(attr, avant); };
  };

  /* ------------------------------------------------------------------ */
  /* Attributs déclaratifs                                               */
  /* ------------------------------------------------------------------ */
  function optionsFormulaire(form, envoyeur, extra) {
    var methode = String((envoyeur && envoyeur.getAttribute('formmethod')) || form.getAttribute('method') || 'GET').toUpperCase();
    var lire = function (nom) { return (envoyeur && envoyeur.getAttribute(nom)) || form.getAttribute(nom); };
    var o = {
      methode: methode,
      cible: lire('data-partiel'),
      mode: lire('data-partiel-mode') || 'outer',
      historique: K.historiqueParDefaut(methode, lire('data-partiel-historique')),
      optimiste: lire('data-optimiste'),
      focusApres: lire('data-focus-apres'),
      defiler: lire('data-partiel-defiler'),
      declencheur: envoyeur || form
    };
    if (methode === 'GET') {
      o.url = K.urlFormulaire(form, envoyeur);
    } else {
      o.url = (envoyeur && envoyeur.getAttribute('formaction')) || form.getAttribute('action') || win.location.pathname;
      o.corps = new win.FormData(form);
      if (envoyeur && envoyeur.name) o.corps.append(envoyeur.name, envoyeur.value || '');
    }
    Object.keys(extra || {}).forEach(function (k) { o[k] = extra[k]; });
    return o;
  }

  function formulairePermisEnLecture(form) {
    return form.hasAttribute('data-permis-lecture') || String(form.getAttribute('method') || 'get').toLowerCase() !== 'post';
  }

  var minuteursAuto = typeof WeakMap === 'function' ? new WeakMap() : null;

  function envoyerAuto(form, evenement, champ) {
    var o = optionsFormulaire(form, null, { transition: false });
    if (evenement === 'input') {
      var st = win.history.state && win.history.state.kairosPartiel;
      var nom = (champ && champ.name) || 'saisie';
      // Une rafale de frappe = une seule entrée d'historique.
      o.historique = st && st.saisie === nom ? 'replace' : 'push';
      o.saisie = nom;
    }
    if (o.url === win.location.pathname + win.location.search) return null;
    return K.requete(o);
  }

  function brancherDeclaratif() {
    // Envoi d'un formulaire partiel (et garde « lecture seule »).
    doc.addEventListener('submit', function (e) {
      var form = e.target;
      if (!form || form.tagName !== 'FORM' || e.defaultPrevented) return;
      if (lectureSeule() && !formulairePermisEnLecture(form)) {
        e.preventDefault();
        K.toast(K.MESSAGE_LECTURE_SEULE, { type: 'info' });
        return;
      }
      var envoyeur = e.submitter || null;
      var cibleAttr = (envoyeur && envoyeur.getAttribute('data-partiel')) || form.getAttribute('data-partiel');
      if (!cibleAttr || sansFetch()) return;
      e.preventDefault();
      if (envoyeur && envoyeur.getAttribute('aria-disabled') === 'true') return;
      if (minuteursAuto && minuteursAuto.get(form)) { annulerMinuteur(minuteursAuto.get(form)); minuteursAuto.delete(form); }
      var o = optionsFormulaire(form, envoyeur);
      if (form.hasAttribute('data-partiel-auto') && o.url === win.location.pathname + win.location.search) return;
      K.requete(o);
    });

    // Lien partiel.
    doc.addEventListener('click', function (e) {
      var a = e.target.closest && e.target.closest('a[data-partiel]');
      if (!a || e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      if (sansFetch()) return;
      e.preventDefault();
      K.requete({
        url: a.getAttribute('href'), methode: 'GET', cible: a.getAttribute('data-partiel'),
        mode: a.getAttribute('data-partiel-mode') || 'outer',
        historique: K.historiqueParDefaut('GET', a.getAttribute('data-partiel-historique')),
        focusApres: a.getAttribute('data-focus-apres'), defiler: a.getAttribute('data-partiel-defiler'),
        // data-optimiste vaut aussi pour un lien (« Les miennes | Toutes »,
        // tuiles dépliables) : état appliqué au clic, sans capture de page.
        optimiste: a.getAttribute('data-optimiste'),
        declencheur: a, synchroniser: true
      });
    });

    // Champ en erreur corrigé : son message disparaît.
    function corrige(e) {
      var el = e.target;
      if (!el || !el.hasAttribute || !el.hasAttribute('data-k-invalide')) return;
      var id = el.getAttribute('data-k-invalide');
      Array.prototype.forEach.call(doc.querySelectorAll('[data-k-invalide="' + echapperSel(id) + '"]'), function (x) { effacerErreurChamp(x, true); });
    }
    doc.addEventListener('input', corrige);
    doc.addEventListener('change', corrige);

    // Confirmation en ligne : [data-confirmer] (bouton d'envoi ou lien).
    doc.addEventListener('click', function (e) {
      var el = e.target.closest && e.target.closest('[data-confirmer]');
      if (!el) return;
      if (el._kConfirme) { el._kConfirme = false; return; }
      e.preventDefault();
      e.stopPropagation();
      K.confirmer(el, el.getAttribute('data-confirmer'), {
        libelleOk: el.getAttribute('data-confirmer-ok') || 'Confirmer',
        danger: el.hasAttribute('data-confirmer-danger')
      }).then(function (oui) {
        if (!oui) return;
        if (el.form && el.type === 'submit' && el.form.requestSubmit) el.form.requestSubmit(el);
        else { el._kConfirme = true; el.click(); }
      });
    }, true);

    // Filtres automatiques : frappe (avec délai), listes et cases (immédiat).
    function auto(e) {
      var champ = e.target;
      var form = champ && champ.form;
      if (!form || !form.hasAttribute('data-partiel-auto')) return;
      var conf = K.lireAuto(form.getAttribute('data-partiel-auto'));
      var texte = /^(text|search|email|tel|url|number)$/.test(champ.type || '') || champ.tagName === 'TEXTAREA';
      if (e.type === 'change' && texte) return;   // déjà traité à la frappe
      if (!(e.type in conf)) return;
      if (minuteursAuto && minuteursAuto.get(form)) annulerMinuteur(minuteursAuto.get(form));
      var delai = conf[e.type];
      var t = minuter(function () { if (minuteursAuto) minuteursAuto.delete(form); envoyerAuto(form, e.type, champ); }, delai);
      if (minuteursAuto) minuteursAuto.set(form, t);
    }
    doc.addEventListener('input', auto);
    doc.addEventListener('change', auto);

    // Retour / Avancer : entrée créée par une requête partielle.
    win.addEventListener('popstate', function (e) {
      var avant = adresseAffichee;
      adresseAffichee = win.location.href;
      var st = e.state && e.state.kairosPartiel;
      if (!st || !doc.querySelector(st.cible)) return;
      if (sansTache(avant) === sansTache(win.location.href)) return;
      synchroniserFormulaires();
      K.requete({ url: win.location.pathname + win.location.search, methode: 'GET', cible: st.cible, mode: st.mode, historique: 'aucun', transition: false,
                  historiqueRejoue: true });
    });
  }

  /** Champs des filtres automatiques remis aux valeurs de l'adresse (Retour). */
  function synchroniserFormulaires() {
    var params = new URLSearchParams(win.location.search);
    Array.prototype.forEach.call(doc.querySelectorAll('form[data-partiel-auto]'), function (form) {
      Array.prototype.forEach.call(form.elements, function (champ) {
        if (!champ.name || champ.type === 'hidden' || champ.type === 'submit' || champ.type === 'button') return;
        var valeurs = params.getAll(champ.name);
        if (champ.type === 'checkbox' || champ.type === 'radio') champ.checked = valeurs.indexOf(champ.value) !== -1;
        else if (champ.multiple) Array.prototype.forEach.call(champ.options, function (op) { op.selected = valeurs.indexOf(op.value) !== -1; });
        else champ.value = valeurs.length ? valeurs[0] : '';
      });
    });
  }
  K.synchroniserFormulaires = synchroniserFormulaires;

  /** L'entrée d'historique de la page est marquée : Retour y revient en partiel. */
  function marquerEntreeInitiale() {
    var form = doc.querySelector('form[data-partiel-auto][data-partiel]');
    if (!form || (win.history.state && win.history.state.kairosPartiel)) return;
    var o = { cible: form.getAttribute('data-partiel'), mode: form.getAttribute('data-partiel-mode') || 'outer' };
    try { win.history.replaceState(etatHistorique(o, null), '', win.location.href); } catch (e) { /* */ }
  }

  function brancherProgression() {
    // Après tous les autres gestionnaires (écoute sur window, phase de bulle).
    win.addEventListener('click', function (e) {
      if (e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      var a = e.target.closest && e.target.closest('a[href]');
      if (!a || a.hasAttribute('download') || a.hasAttribute('data-partiel') || (a.target && a.target !== '_self')) return;
      var url;
      try { url = new URL(a.href, win.location.href); } catch (x) { return; }
      if (url.origin !== win.location.origin || /^(mailto|tel):/.test(a.getAttribute('href'))) return;
      if (url.pathname === win.location.pathname && url.search === win.location.search && url.hash) return;
      K.progressionDebut();
    });
    win.addEventListener('submit', function (e) {
      if (e.defaultPrevented) return;
      K.progressionDebut();
    });
    win.addEventListener('pagehide', function () { K.progressionFin(); });
    win.addEventListener('pageshow', function (e) { if (e.persisted) K.progressionFin(); });
  }

  /** Messages flash() du rendu complet : même zone que les toasts. */
  function toastsInitiaux() {
    var src = doc.getElementById('k-toasts-initiaux');
    if (!src) return;
    var racine = src.content || src;
    var liste = Array.prototype.map.call(racine.querySelectorAll('[data-type]'), function (p) {
      return { type: p.getAttribute('data-type'), texte: p.textContent };
    });
    // Injectés juste après le chargement : une région déjà présente au rendu
    // n'est pas lue par tous les lecteurs d'écran (lot 10, B7).
    minuter(function () { K.toasts(liste); }, 150);
  }

  /** Lot 24 (filtres, contre-expertise FI-04) : « choix=1 » (Filtrer sans
   *  JavaScript, « Afficher tous les projets ») a servi une fois ; retiré de
   *  l'adresse, un F5 ou un Retour ne réécrit pas le choix mémorisé. */
  function sansGeste(adresse) {
    try {
      var url = new URL(adresse, win.location.href);
      if (!url.searchParams.has('defaut') && !url.searchParams.has('choix')) return adresse;
      url.searchParams.delete('defaut');
      url.searchParams.delete('choix');
      return url.pathname + url.search + url.hash;
    } catch (e) { return adresse; }
  }
  function retirerChoix() {
    try {
      var url = new URL(win.location.href);
      if (!url.searchParams.has('choix') && !url.searchParams.has('defaut')) return;
      url.searchParams.delete('choix');
      url.searchParams.delete('defaut');
      win.history.replaceState(win.history.state, '', url.pathname + url.search + url.hash);
    } catch (e) { /* navigateur ancien : sans effet */ }
  }

  K.demarrer = function () {
    doc.addEventListener('keydown', function (e) {
      if (e.defaultPrevented || e.altKey || e.shiftKey || !(e.ctrlKey || e.metaKey) || (e.key !== 'z' && e.key !== 'Z')) return;
      if (dansUnChamp(e.target)) return;
      if (K.annulerDernier()) e.preventDefault();
    });
    brancherDeclaratif();
    brancherProgression();
    var pret = function () {
      regionLive('k-annonce', 'status');
      regionLive('k-alerte', 'alert');
      placerZone();
      surveillerFenetres();
      toastsInitiaux();
      retirerChoix();
      marquerEntreeInitiale();
      K.initialiser(doc);
    };
    if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', pret);
    else pret();
  };

  return K;
});

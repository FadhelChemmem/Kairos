// Panneau d'une tâche (fiche projet). Historique : fenêtre flottante
// ouverte par un clic sur la ligne (retour Fadhel, 2026-09-29) ; lot 11 :
// UNE seule <dialog id="dialog-tache">, remplie à l'ouverture par le
// fragment de la tâche (GET /projets/<id>/taches/<tid>/fenetre), préchargé
// au survol ; lot 11 b : ?tache=<id> ou #tache-<id> ouvre la tâche.
//
// Lot 13 (phase 2, audit UX §4.5 « Panneau de tâche ») :
// - à partir de 1 024 px, panneau latéral NON modal de 480 px qui glisse
//   depuis la droite (240 ms) : le tableau reste utilisable, un clic sur
//   une autre ligne change de tâche ; en dessous, fenêtre modale (feuille
//   en bas sous 600 px) ;
// - l'adresse porte ?tache=<id> (pushState à l'ouverture, replaceState en
//   changeant de tâche) : Retour ferme le panneau, Avancer le rouvre ;
//   Échap ferme ; ↑ / ↓ passent à la tâche précédente / suivante ;
// - toutes les actions du panneau partent en partiel (kairos-partiel.js) :
//   état (optimiste, sans « Appliquer »), titre modifié en place (Entrée
//   ou sortie du champ), clôture, rejoindre, intervenants, échéance
//   (plus de pièce jointe sur une tâche depuis le lot 20).
//
// Correctifs du lot 13 (contre-expertise) :
// - un seul chargement à l'ouverture à la souris (préchargement annulé,
//   jamais celui de la tâche ouverte) — verif-ux N8 ;
// - renommer avec Entrée : un seul envoi (la sortie du champ remplacé ne
//   renvoie pas le même titre) — verif-ux N4 ;
// - ↑ / ↓ annoncent « Tâche n sur N : titre » (verif-a11y-perf N7) ;
// - réutilisable hors de la fiche (Deadlines) : adresse du panneau portée
//   par la ligne (data-tache-url), lignes voisines (data-lignes), ?tache=
//   lu dans l'adresse (data-ouvrir-param), contenu rafraîchi après une
//   action (data-rafraichir) et « Annuler » rejoué sur le panneau quand la
//   ligne du tableau n'existe pas.
(function () {
  var dialog = document.getElementById('dialog-tache');
  if (!dialog) return;
  var corps = dialog.querySelector('[data-tache-corps]');
  var modeleUrl = dialog.getAttribute('data-url');
  var FW = window.KairosFloatingWindow;
  var K = window.Kairos || null;
  var DUREE_PRECHARGE = 20000;
  var LARGEUR_PANNEAU = '(min-width: 1024px)';
  var precharges = {};   // id -> { promesse, t }
  var seq = 0;
  var declencheur = null;
  var tacheCourante = null;
  var entreePoussee = false;   // ?tache= ajouté par nous (pushState)
  var fermetureEnCours = false;
  var minuteurFermeture = null;
  // Lot 25 : fermeture en cours annulée par une réouverture (la fin de
  // l'animation ne referme plus le panneau rouvert entre-temps).
  var numeroFermeture = 0;
  var transitionFermeture = null;
  var minuteur = null;          // préchargement au survol
  var urlsTaches = {};          // id -> adresse du panneau (hors fiche projet)
  var SELECTEUR_LIGNES = dialog.getAttribute('data-lignes') || '#carte-taches [data-open-tache]';

  function urlTache(id) {
    if (urlsTaches[id]) return urlsTaches[id];
    return modeleUrl.replace(/\/taches\/0\/fenetre$/, '/taches/' + encodeURIComponent(id) + '/fenetre');
  }
  function enPanneau() { return dialog.classList.contains('tache-panneau'); }
  function mouvementReduit() {
    try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; }
  }

  /* ---------------------------------------------------------------- */
  /* Chargement du fragment                                            */
  /* ---------------------------------------------------------------- */
  function charger(id) {
    return fetch(urlTache(id), { credentials: 'same-origin', headers: { 'Accept': 'text/html' } })
      .then(function (r) {
        // Session expirée : la redirection vers /connexion est suivie et
        // renvoie la page de connexion — jamais notre fragment.
        if (r.ok && r.headers.get('X-Kairos-Fragment') === 'tache') return r.text();
        var e = new Error('http');
        e.code = r.ok ? 'session' : r.status;
        throw e;
      });
  }
  // Un préchargement qui a échoué ne sert jamais au clic : nouvelle
  // demande (revue d'interaction P0-7, faux « Tâche introuvable »).
  function obtenir(id) {
    var p = precharges[id];
    delete precharges[id];
    if (p && Date.now() - p.t < DUREE_PRECHARGE) return p.promesse.catch(function () { return charger(id); });
    return charger(id);
  }
  function precharger(id) {
    if (dialog.open && String(id) === tacheCourante) return;
    var p = precharges[id];
    if (p && Date.now() - p.t < DUREE_PRECHARGE) return;
    var promesse = charger(id);
    promesse.catch(function () { delete precharges[id]; });
    precharges[id] = { promesse: promesse, t: Date.now() };
  }
  // Une action a modifié des tâches : les fragments préchargés sont périmés.
  function oublierPrecharges() { precharges = {}; }

  function etatChargement() {
    dialog.setAttribute('aria-busy', 'true');
    corps.classList.remove('k-en-cours');
    corps.innerHTML = '';
    var p = document.createElement('p');
    p.className = 'tache-dialog-chargement';
    p.setAttribute('role', 'status');
    var roue = document.createElement('span');
    roue.className = 'roue-chargement';
    roue.setAttribute('aria-hidden', 'true');
    p.appendChild(roue);
    p.appendChild(document.createTextNode('Chargement de la tâche…'));
    corps.appendChild(p);
    // Squelette (titre, 3 lignes, 2 boutons) pendant le chargement.
    var sq = document.createElement('div');
    sq.className = 'tache-dialog-squelette';
    sq.setAttribute('aria-hidden', 'true');
    sq.innerHTML = '<span class="k-squelette k-squelette-titre"></span><span class="k-squelette k-squelette-ligne"></span>'
      + '<span class="k-squelette k-squelette-ligne"></span><span class="k-squelette k-squelette-ligne k-squelette-court"></span>'
      + '<span class="k-squelette k-squelette-bouton"></span> <span class="k-squelette k-squelette-bouton"></span>';
    corps.appendChild(sq);
    // Rien de saisi dans un panneau qui charge.
    if (FW) FW.memoriser(dialog);
  }

  function etatErreur(id, err) {
    dialog.removeAttribute('aria-busy');
    corps.classList.remove('k-en-cours');
    corps.innerHTML = '';
    var bloc = document.createElement('div');
    bloc.className = 'tache-dialog-erreur';
    bloc.setAttribute('role', 'alert');
    var msg = document.createElement('p');
    var bouton = document.createElement('button');
    bouton.type = 'button';
    bouton.className = 'btn';
    if (err && (err.code === 'session' || err.code === 404)) {
      msg.textContent = err.code === 'session'
        ? 'Votre session a expiré\u00a0: rechargez la page pour vous reconnecter.'
        : 'Tâche introuvable\u00a0: elle a peut-être été supprimée, ou vous n’y avez plus accès. Rechargez la page.';
      bouton.textContent = 'Recharger la page';
      bouton.addEventListener('click', function () { window.location.reload(); });
    } else {
      msg.textContent = 'Impossible de charger la tâche. Vérifiez la connexion, puis réessayez.';
      bouton.textContent = 'Réessayer';
      bouton.addEventListener('click', function () { afficher(id, { premier: true }); });
    }
    bloc.appendChild(msg);
    bloc.appendChild(bouton);
    corps.appendChild(bloc);
    if (FW) FW.memoriser(dialog);
    bouton.focus();
  }

  // Annonce persistante (région vide dès l'ouverture, dans la fenêtre : une
  // fenêtre modale rend inerte ce qui est hors d'elle). Kairos.annoncer
  // (socle) quand il existe et que le panneau n'est pas modal.
  var annonce = null, minuteurAnnonce = null;
  function annoncer(texte) {
    var modal = false;
    try { modal = dialog.matches(':modal'); } catch (e) { modal = false; }
    if (!modal && K && typeof K.annoncer === 'function') { K.annoncer(texte); return; }
    if (!annonce) {
      annonce = document.createElement('div');
      annonce.className = 'sr-only';
      annonce.id = 'tache-dialog-annonce';
      annonce.setAttribute('role', 'status');
      dialog.appendChild(annonce);
    }
    clearTimeout(minuteurAnnonce);
    annonce.textContent = '';
    minuteurAnnonce = setTimeout(function () { annonce.textContent = texte; }, 30);
  }
  function annoncerPosition(id) {
    var lignes = lignesVisibles();
    var i = -1;
    lignes.forEach(function (l, j) { if (l.getAttribute('data-open-tache') === String(id)) i = j; });
    var racine = corps.querySelector('[data-tache-fenetre]');
    var titre = racine ? racine.getAttribute('data-titre') : '';
    if (i >= 0) annoncer('Tâche ' + (i + 1) + ' sur ' + lignes.length + ' : ' + titre);
    else if (titre) annoncer('Tâche : ' + titre);
  }

  // Hors de la fiche (Deadlines) : le code du projet mène à sa fiche.
  function lienFiche() {
    if (!dialog.hasAttribute('data-rafraichir')) return;
    var code = corps.querySelector('.tache-fenetre-projet[data-url-fiche]');
    if (!code || code.tagName === 'A') return;
    var a = document.createElement('a');
    a.className = code.className + ' tache-fenetre-projet-lien';
    a.href = code.getAttribute('data-url-fiche');
    a.title = 'Ouvrir la fiche du projet ' + (code.getAttribute('title') || code.textContent);
    a.textContent = code.textContent;
    code.parentNode.replaceChild(a, code);
  }

  function nommer() {
    var racine = corps.querySelector('[data-tache-fenetre]');
    if (racine) dialog.setAttribute('aria-label', 'Tâche « ' + racine.getAttribute('data-titre') + ' »');
  }

  /** Affiche la tâche `id` ; opts.premier : focus sur le premier champ ;
   *  opts.voisine : -1 / 1 (focus rendu à la flèche utilisée). */
  function afficher(id, opts) {
    opts = opts || {};
    var n = ++seq;
    tacheCourante = String(id);
    marquerLigne();
    if (opts.premier || !corps.querySelector('[data-tache-fenetre]')) etatChargement();
    else { corps.classList.add('k-en-cours'); dialog.setAttribute('aria-busy', 'true'); }
    obtenir(id).then(function (html) {
      if (n !== seq || !dialog.open) return;
      var actifAvant = document.activeElement;
      var focusDedans = !!actifAvant && corps.contains(actifAvant);
      corps.classList.remove('k-en-cours');
      corps.innerHTML = html;
      dialog.removeAttribute('aria-busy');
      // Composants du fragment (sélecteur à recherche, zone de dépôt,
      // lecture seule « Voir comme »…).
      if (window.KairosSearchCombobox) window.KairosSearchCombobox.init(corps);
      if (K && K.initialiser) K.initialiser(corps);
      initEcheances(corps);
      nommer();
      lienFiche();
      if (opts.voisine) annoncerPosition(id);
      // État de référence pour « fermer sans enregistrer ? ».
      if (FW) FW.memoriser(dialog);
      var actif = document.activeElement;
      var perdu = focusDedans || !actif || actif === document.body || actif === dialog
        || actif.hasAttribute('data-close-tache');
      if (opts.voisine && perdu) {
        var fleche = corps.querySelector('[data-tache-voisine="' + opts.voisine + '"]');
        if (fleche) { fleche.focus(); return; }
      }
      if ((opts.premier || focusDedans) && perdu) {
        // Revue d'interaction P1-6 : jamais dans le champ du titre (clavier
        // virtuel ouvert, frappe involontaire qui renomme la tâche) — sur
        // l'en-tête (pastille, code) ; le titre reste modifiable au clic.
        var entete = corps.querySelector('[data-tache-entete]') || corps.querySelector('.tache-fenetre-titre');
        if (entete) { entete.setAttribute('tabindex', '-1'); entete.focus(); }
      }
    }, function (err) {
      if (n !== seq || !dialog.open) return;
      etatErreur(id, err);
    });
  }

  /* ---------------------------------------------------------------- */
  /* Ouverture, fermeture, historique                                  */
  /* ---------------------------------------------------------------- */
  // La ligne visible d'abord (Deadlines : frise sur ordinateur, liste sur téléphone).
  function ligneDe(id) {
    var lignes = document.querySelectorAll('[data-open-tache="' + id + '"]');
    for (var i = 0; i < lignes.length; i++) if (lignes[i].offsetParent !== null) return lignes[i];
    return lignes[0] || null;
  }
  var idDernierFerme = null, fermeLe = 0;

  function marquerLigne() {
    document.querySelectorAll('.taskrow-ouverte').forEach(function (l) { l.classList.remove('taskrow-ouverte'); });
    var l = tacheCourante && dialog.open ? ligneDe(tacheCourante) : null;
    if (l) l.classList.add('taskrow-ouverte');
  }

  function adresseAvec(id) {
    var u = new URL(window.location.href);
    if (id) u.searchParams.set('tache', id); else u.searchParams.delete('tache');
    if (/^#tache-\d+$/.test(u.hash)) u.hash = '';
    return u.pathname + u.search + u.hash;
  }
  function etatHistorique(id) {
    var st = {};
    var actuel = window.history.state;
    if (actuel && typeof actuel === 'object') Object.keys(actuel).forEach(function (k) { st[k] = actuel[k]; });
    if (id) st.kairosTache = String(id); else delete st.kairosTache;
    return st;
  }

  /** opts.historique : 'push' (ouverture par l'utilisateur), 'replace'
   *  (changement de tâche), 'aucun' (adresse déjà à jour). */
  function ouvrir(ligne, opts) {
    opts = opts || {};
    clearTimeout(minuteur);
    var id = ligne.getAttribute('data-open-tache');
    if (ligne.hasAttribute('data-tache-url')) urlsTaches[id] = ligne.getAttribute('data-tache-url');
    var titreBouton = ligne.querySelector('[data-ouvrir-tache]');
    if (fermetureEnCours) {
      // Réouverture pendant l'animation de sortie : le panneau reste.
      clearTimeout(minuteurFermeture);
      numeroFermeture++;
      if (transitionFermeture && transitionFermeture.skipTransition) {
        try { transitionFermeture.skipTransition(); } catch (e) { /* déjà finie */ }
      }
      fermetureEnCours = false;
      dialog.classList.remove('tache-panneau-sortie');
      if (String(id) === tacheCourante) tacheCourante = null;
    }
    if (dialog.open) {
      // Panneau déjà ouvert : on change de tâche.
      if (String(id) === tacheCourante) return;
      // Lot 20 (revue QA n° 16b) : saisie en cours (motif de blocage…)
      // — même confirmation qu'à la fermeture.
      if (!opts.confirme && opts.historique !== 'aucun' && FW && FW.aEteModifiee(dialog) && K && K.confirmer) {
        if (dialog.querySelector('.k-confirmation')) return;
        var ancre = dialog.contains(document.activeElement) ? document.activeElement : dialog;
        K.confirmer(ancre, 'Abandonner les modifications\u202f? La saisie sera perdue.', {
          libelleOk: 'Abandonner', libelleAnnuler: 'Continuer la saisie', danger: true
        }).then(function (oui) {
          if (!oui) return;
          var suite = {};
          Object.keys(opts).forEach(function (k) { suite[k] = opts[k]; });
          suite.confirme = true;
          ouvrir(ligne, suite);
        });
        return;
      }
      declencheur = titreBouton;
      if (opts.historique === 'push') {
        // Réouverture pendant la sortie : l'entrée ?tache= a déjà été
        // retirée (Échap → Retour) ; on en pousse une nouvelle, sinon
        // Retour quitterait la fiche.
        try { window.history.pushState(etatHistorique(id), '', adresseAvec(id)); entreePoussee = true; } catch (e) { /* */ }
      } else if (opts.historique !== 'aucun') {
        try { window.history.replaceState(etatHistorique(id), '', adresseAvec(id)); } catch (e) { /* */ }
      }
      afficher(id, { voisine: opts.voisine });
      return;
    }
    declencheur = titreBouton;
    var titre = titreBouton ? (titreBouton.getAttribute('data-titre') || titreBouton.textContent.trim()) : '';
    dialog.setAttribute('aria-label', titre ? 'Tâche « ' + titre + ' »' : 'Tâche');
    var panneau = !!(window.matchMedia && window.matchMedia(LARGEUR_PANNEAU).matches);
    dialog.classList.toggle('tache-panneau', panneau);
    dialog.classList.remove('tache-panneau-sortie');
    etatChargement();
    if (panneau && typeof dialog.show === 'function') dialog.show();
    else if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', 'open');
    // Largeur de la barre de défilement : le contenu garde son bord gauche
    // quand la page se resserre à côté du panneau (app.css).
    document.documentElement.style.setProperty('--k-barre', Math.max(0, window.innerWidth - document.documentElement.clientWidth) + 'px');
    document.body.classList.toggle('tache-panneau-ouvert', panneau);
    if (opts.historique === 'push') {
      try { window.history.pushState(etatHistorique(id), '', adresseAvec(id)); entreePoussee = true; } catch (e) { /* */ }
    }
    afficher(id, { premier: true });
  }

  /** Ferme ; `depuisHistorique` : l'adresse a déjà changé (Retour). */
  function fermer(depuisHistorique) {
    if (!dialog.open || fermetureEnCours) return;
    var jeton = ++numeroFermeture;
    var finir = function () {
      if (jeton !== numeroFermeture) return;  // rouvert entre-temps
      fermetureEnCours = false;
      if (dialog.open) dialog.close();
    };
    if (!depuisHistorique) {
      if (entreePoussee && window.history.state && window.history.state.kairosTache) {
        entreePoussee = false;
        window.history.back();
      } else {
        try { window.history.replaceState(etatHistorique(null), '', adresseAvec(null)); } catch (e) { /* */ }
      }
    } else {
      entreePoussee = false;
    }
    if (enPanneau() && !mouvementReduit() && typeof document.startViewTransition === 'function') {
      // Lot 25 (demande du gérant, 23/10) : fermeture fluide — le panneau
      // glisse et la page (tableau des tâches, fil, colonne de droite)
      // reprend sa largeur en même temps, sans saut (View Transitions ;
      // css/lot25.css). Ailleurs : l'animation d'avant.
      fermetureEnCours = true;
      document.documentElement.classList.add('k-vt-panneau');
      var transition = document.startViewTransition(function () { finir(); });
      transitionFermeture = transition;
      var nettoyer = function () {
        document.documentElement.classList.remove('k-vt-panneau');
        if (transitionFermeture === transition) transitionFermeture = null;
      };
      transition.finished.then(nettoyer, nettoyer);
    } else if (enPanneau() && !mouvementReduit()) {
      fermetureEnCours = true;
      dialog.classList.add('tache-panneau-sortie');
      minuteurFermeture = setTimeout(finir, 180);
    } else if (FW && FW.fermer && !mouvementReduit()) {
      // Fenêtre ou feuille : sortie animée (revue d'interaction P1-10).
      fermetureEnCours = true;
      FW.fermer(dialog, finir);
    } else {
      finir();
    }
  }

  function demanderFermeture() {
    // Lot 25 (TA-07) : une échéance changée à l'instant (enregistrée seule,
    // 900 ms après) part tout de suite — ce n'est pas une saisie perdue.
    if (minuteurEcheance) {
      var formEcheance = dialog.querySelector('.tache-echeance-form');
      if (formEcheance) envoyerEcheance(formEcheance);
    }
    if (FW && FW.aEteModifiee(dialog) && K && K.confirmer) {
      if (dialog.querySelector('.k-confirmation')) return;
      var ancre = dialog.contains(document.activeElement) ? document.activeElement : dialog;
      K.confirmer(ancre, 'Abandonner les modifications\u202f? La saisie sera perdue.', {
        libelleOk: 'Abandonner', libelleAnnuler: 'Continuer la saisie', danger: true
      }).then(function (oui) { if (oui) fermer(false); });
      return;
    }
    fermer(false);
  }

  if (FW) FW.attacherFermetureAuFond(dialog, { fermeture: function () { fermer(false); } });
  // Geste « glisser vers le bas » de la feuille : même sortie que le X.
  dialog._kairosDemanderFermeture = function () { demanderFermeture(); };
  dialog.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('[data-close-tache]')) demanderFermeture();
  });
  // Fenêtre modale : Échap passe par « cancel » (floating-window.js demande
  // confirmation si la saisie a changé) ; même sortie que le bouton.
  dialog.addEventListener('cancel', function (e) {
    if (e.defaultPrevented) return;
    e.preventDefault();
    fermer(false);
  });
  dialog.addEventListener('close', function () {
    seq++;   // une réponse arrivée après la fermeture est ignorée
    var idFerme = tacheCourante;
    idDernierFerme = idFerme;
    fermeLe = Date.now();
    corps.innerHTML = '';
    corps.classList.remove('k-en-cours');
    dialog.removeAttribute('aria-busy');
    dialog.classList.remove('tache-panneau', 'tache-panneau-sortie');
    document.body.classList.remove('tache-panneau-ouvert');
    tacheCourante = null;
    marquerLigne();
    // Focus rendu au titre de la tâche (retrouvé par son id si la ligne a
    // été remplacée entre-temps par une mise à jour partielle).
    var cible = declencheur && document.contains(declencheur) ? declencheur : null;
    if (!cible && idFerme) {
      var ligne = ligneDe(idFerme);
      cible = ligne ? ligne.querySelector('[data-ouvrir-tache]') : null;
    }
    if (cible) {
      var repli = cible.closest('details');
      if (repli && !repli.open) repli.open = true;
      cible.focus();
    }
    declencheur = null;
  });

  // Clic sur une ligne (le titre est le vrai bouton ; le reste de la ligne
  // est un raccourci souris). Délégation : lignes remplacées comprises.
  document.addEventListener('click', function (e) {
    var ligne = e.target.closest('[data-open-tache]');
    if (!ligne) return;
    if (!e.target.closest('[data-ouvrir-tache]') && e.target.closest('form, button, a, input, select')) return;
    var lien = e.target.closest('a[href]');
    if (lien) {
      // Barre du Gantt : nouvel onglet (Ctrl, clic du milieu…) = la fiche.
      if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
    }
    ouvrir(ligne, { historique: dialog.open && !fermetureEnCours ? 'replace' : 'push' });
  });

  // ?tache=<id> (recherche globale, notification) ou #tache-<id> : ligne
  // dépliée parmi les tâches closes si besoin, panneau ouvert.
  function ouvrirDemandee(id, historique) {
    var ligne = id && ligneDe(id);
    if (!ligne) return;
    var repli = ligne.closest('details');
    if (repli && !repli.open) repli.open = true;
    if (ligne.scrollIntoView) ligne.scrollIntoView({ block: 'center' });
    ouvrir(ligne, { historique: historique || 'aucun' });
  }
  function idAncre() {
    var m = /^#tache-(\d+)$/.exec(window.location.hash);
    return m ? m[1] : null;
  }
  function idParametre() {
    if (!dialog.hasAttribute('data-ouvrir-param')) return null;
    var v = new URL(window.location.href).searchParams.get('tache');
    return v && /^\d+$/.test(v) ? v : null;
  }
  ouvrirDemandee(dialog.getAttribute('data-ouvrir-au-chargement') || idParametre() || idAncre());
  window.addEventListener('hashchange', function () { ouvrirDemandee(idAncre()); });

  // Retour / Avancer : l'adresse dit quelle tâche est ouverte.
  window.addEventListener('popstate', function () {
    var id = new URL(window.location.href).searchParams.get('tache');
    // Lot 21 (revue F2) : Retour avec une saisie en cours (motif…) — même
    // question qu'Échap ; l'entrée de la tâche est remise le temps de
    // répondre (« Continuer la saisie » garde panneau et adresse).
    if (dialog.open && !fermetureEnCours && tacheCourante && id !== tacheCourante
        && FW && FW.aEteModifiee(dialog) && K && K.confirmer) {
      var cible = id;
      try { window.history.pushState(etatHistorique(tacheCourante), '', adresseAvec(tacheCourante)); entreePoussee = true; } catch (e) { /* */ }
      if (!cible) { demanderFermeture(); return; }
      var ligneCible = ligneDe(cible);
      if (ligneCible) ouvrir(ligneCible, { historique: 'replace' });
      return;
    }
    if (!id) { fermer(true); return; }
    if (dialog.open && id === tacheCourante) return;
    if (!ligneDe(id)) {
      // Lot 21 (revue F4) : la page revient d'abord en partiel (Retour sur
      // une autre vue des Deadlines) ; la tâche est ouverte quand le
      // contenu qui la porte est arrivé.
      document.addEventListener('kairos:fragment', function reessayer() {
        document.removeEventListener('kairos:fragment', reessayer);
        if (new URL(window.location.href).searchParams.get('tache') === id) {
          ouvrirDemandee(id, 'aucun');
          if (dialog.open) entreePoussee = !!(window.history.state && window.history.state.kairosTache);
        }
      });
      return;
    }
    ouvrirDemandee(id, 'aucun');
    // Entrée ?tache= poussée par nous (Avancer) : Échap y revient par Retour.
    if (dialog.open) entreePoussee = !!(window.history.state && window.history.state.kairosTache);
  });

  /* ---------------------------------------------------------------- */
  /* Clavier : Échap (panneau non modal), ↑ / ↓                         */
  /* ---------------------------------------------------------------- */
  function lignesVisibles() {
    return Array.prototype.filter.call(document.querySelectorAll(SELECTEUR_LIGNES), function (l) {
      // Lot 25 (TA-13) : une ligne d'un repli fermé (tâches closes) n'est
      // pas visible, même si le navigateur lui donne une boîte.
      var repli = l.closest && l.closest('details');
      if (repli && !repli.open && !(l.closest('summary'))) return false;
      if (l.offsetParent !== null) return true;
      // Lot 21 (revue F3) : lignes du Gantt en « display: contents » (sans
      // boîte propre) — visibles si une de leurs cellules l'est.
      if (window.getComputedStyle && window.getComputedStyle(l).display === 'contents') {
        return Array.prototype.some.call(l.children, function (c) { return c.offsetParent !== null; });
      }
      return false;
    });
  }
  function voisine(sens) {
    var lignes = lignesVisibles();
    var i = -1;
    lignes.forEach(function (l, j) { if (l.getAttribute('data-open-tache') === tacheCourante) i = j; });
    var suivante = i === -1 ? null : lignes[i + sens];
    if (!suivante) return false;
    if (suivante.scrollIntoView) suivante.scrollIntoView({ block: 'nearest' });
    ouvrir(suivante, { historique: 'replace', voisine: sens });
    return true;
  }
  function editable(el) {
    return !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable
      || !!(el.closest && el.closest('[role="listbox"], .search-combobox-wrap, .k-confirmation')));
  }
  // Lot 25 (demande du gérant, 23/10) : panneau latéral, un clic hors du
  // panneau = Échap (même confirmation si une saisie est en cours). Pas
  // pour un clic sur une autre tâche (elle s'ouvre à la place), une
  // confirmation, un toast, une autre fenêtre ou un élément retiré entre-
  // temps de la page (mise à jour partielle).
  document.addEventListener('click', function (e) {
    if (!dialog.open || !enPanneau() || fermetureEnCours || e.defaultPrevented || e.button !== 0) return;
    var cible = e.target;
    if (!cible || !document.contains(cible) || dialog.contains(cible)) return;
    if (cible.closest && cible.closest('[data-open-tache], .k-confirmation, .k-toast, .k-toasts, dialog[open], '
        + '[role="listbox"], .search-combobox-wrap, .bandeau-admin')) return;
    if (document.querySelector('dialog[open]:not(#dialog-tache)') || document.querySelector('.k-confirmation')) return;
    demanderFermeture();
  });
  document.addEventListener('keydown', function (e) {
    if (!dialog.open || e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
    var actif = document.activeElement;
    var autreModale = document.querySelector('dialog[open]:not(#dialog-tache)');
    if (e.key === 'Escape' && enPanneau()) {
      if (autreModale || document.querySelector('.k-confirmation')) return;
      e.preventDefault();
      demanderFermeture();
      return;
    }
    if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && !e.shiftKey && !autreModale) {
      if (editable(actif)) return;
      var dansPage = !actif || actif === document.body || dialog.contains(actif)
        || !!(actif.closest && actif.closest('#carte-taches, [data-open-tache]'));
      if (!dansPage) return;
      if (voisine(e.key === 'ArrowUp' ? -1 : 1)) e.preventDefault();
    }
  });
  dialog.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-tache-voisine]');
    if (b) voisine(parseInt(b.getAttribute('data-tache-voisine'), 10));
  });

  /* ---------------------------------------------------------------- */
  /* Actions du panneau                                                */
  /* ---------------------------------------------------------------- */
  function ligneCourante(el) {
    var f = el && el.closest ? el.closest('[data-tache-fenetre]') : null;
    var id = f ? f.getAttribute('data-tache-fenetre') : tacheCourante;
    return id ? document.getElementById('tache-ligne-' + id) : null;
  }

  if (K && K.optimistes) {
    // État : la pastille change tout de suite, dans le panneau et la ligne.
    K.optimistes['etat-tache'] = function (bouton) {
      if (!bouton || !bouton.getAttribute || !bouton.hasAttribute('data-classe')) return null;
      var groupe = bouton.form || bouton.closest('form');
      var fenetre = bouton.closest('[data-tache-fenetre]');
      var pastilles = [];
      if (fenetre) pastilles.push(fenetre.querySelector('[data-tache-pastille]'));
      var ligne = ligneCourante(bouton);
      if (ligne) pastilles.push(ligne.querySelector('[data-tache-pastille]'));
      var avant = pastilles.filter(Boolean).map(function (p) { return { el: p, cls: p.className, txt: p.textContent }; });
      var presses = Array.prototype.map.call(groupe.querySelectorAll('[aria-pressed]'), function (b) {
        return { el: b, val: b.getAttribute('aria-pressed') };
      });
      presses.forEach(function (p) { p.el.setAttribute('aria-pressed', p.el === bouton ? 'true' : 'false'); });
      avant.forEach(function (p) {
        p.el.className = 'pill ' + bouton.getAttribute('data-classe');
        p.el.textContent = bouton.getAttribute('data-libelle');
      });
      return function () {
        presses.forEach(function (p) { if (document.contains(p.el)) p.el.setAttribute('aria-pressed', p.val); });
        avant.forEach(function (p) { if (document.contains(p.el)) { p.el.className = p.cls; p.el.textContent = p.txt; } });
      };
    };
    // Titre : la ligne du tableau change tout de suite.
    K.optimistes['titre-tache'] = function (form) {
      var champ = form && form.querySelector ? form.querySelector('.tache-titre-champ') : null;
      var ligne = ligneCourante(form);
      var bouton = ligne ? ligne.querySelector('[data-ouvrir-tache]') : null;
      if (!champ || !bouton) return null;
      var avant = bouton.textContent;
      bouton.textContent = champ.value.trim();
      bouton.title = bouton.textContent;
      return function () { if (document.contains(bouton)) { bouton.textContent = avant; bouton.title = avant; } };
    };
    // Blocage (lot 14) : « Signaler le blocage » presse « Bloquée » tout de suite.
    K.optimistes['blocage-tache'] = function (el) {
      var form = el && (el.form || (el.closest && el.closest('form')));
      var fenetre = form && form.closest ? form.closest('[data-tache-fenetre]') : null;
      var bouton = fenetre ? fenetre.querySelector('.tache-etat-choix[value="bloque"]') : null;
      return bouton ? K.optimistes['etat-tache'](bouton) : null;
    };
    // « Rejoindre » de la ligne : bouton occupé tout de suite.
    K.optimistes.rejoindre = function (bouton) {
      if (!bouton || !bouton.classList) return null;
      bouton.classList.add('task-join-btn-attente');
      return function () { if (document.contains(bouton)) bouton.classList.remove('task-join-btn-attente'); };
    };
  }

  // L'état déjà choisi n'est pas renvoyé.
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('.tache-etat-choix[aria-pressed="true"]');
    if (b) { e.preventDefault(); e.stopPropagation(); }
  }, true);

  /* ---------------------------------------------------------------- */
  /* « Qu'est-ce qui bloque ? » (lot 14, revue produit P0-1)            */
  /* ---------------------------------------------------------------- */
  // « Bloquée » ouvre la question par-dessus le panneau (rien ne bouge) ;
  // le motif est obligatoire. Annuler ou Échap la ferment (saisie gardée),
  // le focus revient à « Bloquée » ; Entrée envoie, Maj+Entrée va à la ligne.
  function questionBlocage(bouton) {
    var id = bouton && bouton.getAttribute('data-blocage-ouvrir');
    return id ? document.getElementById(id) : null;
  }
  function fermerBlocage(pop, rendreFocus) {
    if (!pop || pop.hidden) return;
    pop.hidden = true;
    // Lot 18 : le motif saisi est gardé (Échap ou Annuler ne le jette plus).
    if (K && K.effacerErreurs) K.effacerErreurs(pop);
    var bouton = document.querySelector('[data-blocage-ouvrir="' + pop.id + '"]');
    if (bouton) {
      bouton.setAttribute('aria-expanded', 'false');
      if (rendreFocus) bouton.focus();
    }
  }
  function ouvrirBlocage(bouton) {
    var pop = questionBlocage(bouton);
    if (!pop) return;
    pop.hidden = false;
    bouton.setAttribute('aria-expanded', 'true');
    var champ = pop.querySelector('textarea');
    if (champ) champ.focus();
  }
  document.addEventListener('click', function (e) {
    var cible = e.target.closest ? e.target : null;
    if (!cible) return;
    var b = cible.closest('[data-blocage-ouvrir]');
    if (b) {
      if (b.getAttribute('aria-pressed') === 'true') return;
      e.preventDefault();
      e.stopPropagation();
      if (K && K.lectureSeule && K.lectureSeule()) { K.toast(K.MESSAGE_LECTURE_SEULE, { type: 'info' }); return; }
      var pop = questionBlocage(b);
      if (pop && !pop.hidden) fermerBlocage(pop, true); else ouvrirBlocage(b);
      return;
    }
    var annuler = cible.closest('[data-blocage-annuler]');
    if (annuler) {
      e.preventDefault();
      fermerBlocage(annuler.closest('.tache-blocage'), true);
      return;
    }
    // Un autre état choisi : la question se ferme.
    if (cible.closest('.tache-etat-choix')) {
      document.querySelectorAll('.tache-blocage:not([hidden])').forEach(function (p) { fermerBlocage(p, false); });
    }
  }, true);
  // Envoi : le focus passe sur « Bloquée » (pressé tout de suite) — il y
  // revient après la réponse (data-focus-apres) et après « Annuler » du
  // toast (contrôle d'origine). Refus (motif vide) : focus sur le champ.
  document.addEventListener('submit', function (e) {
    var pop = e.target;
    if (!pop.classList || !pop.classList.contains('tache-blocage') || pop.hidden) return;
    var bouton = document.querySelector('[data-blocage-ouvrir="' + pop.id + '"]');
    var champ = pop.querySelector('textarea');
    if (bouton && champ && champ.value.trim()) bouton.focus({ preventScroll: true });
  }, true);
  document.addEventListener('keydown', function (e) {
    var pop = e.target && e.target.closest ? e.target.closest('.tache-blocage') : null;
    if (!pop || pop.hidden) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      fermerBlocage(pop, true);
    } else if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.target.tagName === 'TEXTAREA') {
      e.preventDefault();
      if (pop.requestSubmit) pop.requestSubmit();
    }
  }, true);

  // Titre modifié en place : Entrée envoie (formulaire), la sortie du champ
  // aussi si le texte a changé ; Échap rend le titre d'avant.
  document.addEventListener('focusout', function (e) {
    var champ = e.target;
    if (!champ.classList || !champ.classList.contains('tache-titre-champ')) return;
    var form = champ.form;
    var valeur = champ.value.trim();
    if (!form || !valeur || valeur === champ.getAttribute('data-valeur-initiale')) return;
    // Champ retiré (panneau remplacé après Entrée) ou titre déjà envoyé :
    // pas de second envoi.
    if (!document.contains(champ) || form.getAttribute('data-titre-envoye') === valeur) return;
    if (form.getAttribute('aria-disabled') === 'true' || !champ.checkValidity()) return;
    if (form.requestSubmit) form.requestSubmit();
  });
  document.addEventListener('keydown', function (e) {
    var champ = e.target;
    if (!champ.classList || !champ.classList.contains('tache-titre-champ') || e.key !== 'Escape') return;
    var initial = champ.getAttribute('data-valeur-initiale');
    if (champ.value !== initial) {
      e.preventDefault();
      e.stopPropagation();
      champ.value = initial;
    }
  }, true);
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.hasAttribute || !form.hasAttribute('data-tache-titre-form')) return;
    form.setAttribute('data-optimiste', 'titre-tache');
    var champ = form.querySelector('.tache-titre-champ');
    // Rien de changé : pas d'envoi (ni de post « renommée » vide).
    if (champ && champ.value.trim() === champ.getAttribute('data-valeur-initiale')) { e.preventDefault(); return; }
    if (champ) form.setAttribute('data-titre-envoye', champ.value.trim());
  }, true);

  // Échéance : « Enregistrer » actif seulement après une modification
  // (revue d'interaction P2-9 : sinon toast « Échéance inchangée »).
  function valeurEcheance(form) {
    var d = form.querySelector('input[name="date_echeance"]'), t = form.querySelector('select[name="type_deadline"]');
    return (d ? d.value : '') + '|' + (t ? t.value : '');
  }
  function majEcheance(form) {
    if (!form || !form.classList || !form.classList.contains('tache-echeance-form')) return;
    if (form.dataset.initial === undefined) form.dataset.initial = valeurEcheance(form);
    var b = form.querySelector('button[type="submit"]:not(.k-sans-js)') || form.querySelector('button[type="submit"]');
    if (!b) return;
    b.classList.toggle('k-inchange', valeurEcheance(form) === form.dataset.initial);
  }
  function initEcheances(racine) {
    (racine && racine.querySelectorAll ? racine : document).querySelectorAll('.tache-echeance-form').forEach(majEcheance);
  }
  ['input', 'change'].forEach(function (type) {
    document.addEventListener(type, function (e) { if (e.target && e.target.form) majEcheance(e.target.form); });
  });
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.classList || !form.classList.contains('tache-echeance-form')) return;
    if (valeurEcheance(form) === form.dataset.initial) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
  document.addEventListener('kairos:fragment', function (e) { initEcheances(e.detail && e.detail.racine); });

  // Choix dans un sélecteur à recherche (« + Affecter quelqu'un… ») :
  // envoi immédiat.
  document.addEventListener('change', function (e) {
    var select = e.target;
    var form = select && select.form;
    if (!form || !form.hasAttribute('data-soumettre-au-choix') || select.tagName !== 'SELECT' || !select.value) return;
    if (form.requestSubmit) form.requestSubmit();
  });

  /* ---------------------------------------------------------------- */
  /* Hors de la fiche projet (Deadlines)                               */
  /* ---------------------------------------------------------------- */
  // Le contenu de la page (data-rafraichir) suit les actions du panneau ;
  // « Annuler » d'un toast vise la ligne du tableau de la fiche : sans elle,
  // il est rejoué sur le panneau ouvert, sinon dans un réceptacle caché.
  var rafraichir = dialog.getAttribute('data-rafraichir');
  var minuteurRafraichir = null;
  function rafraichirContenu() {
    if (!rafraichir || !K || !K.requete || !document.querySelector(rafraichir)) return;
    clearTimeout(minuteurRafraichir);
    minuteurRafraichir = setTimeout(function () {
      var u = new URL(window.location.href);
      u.searchParams.delete('tache');
      // Focus perdu (barre remplacée, panneau fermé entre-temps) : il revient
      // sur la ligne visible de la tâche.
      var id = tacheCourante || idDernierFerme;
      var l = id ? ligneDe(id) : null;
      var focusApres = l ? '.' + l.classList[0] + '[data-open-tache="' + id + '"] [data-ouvrir-tache]' : null;
      K.requete({ url: u.pathname + u.search, methode: 'GET', cible: rafraichir, historique: 'aucun', transition: false, focusApres: focusApres });
    }, 50);
  }
  function receptacle(id) {
    var boite = document.getElementById('tache-receptacle');
    if (!boite) {
      boite = document.createElement('div');
      boite.id = 'tache-receptacle';
      boite.hidden = true;
      document.body.appendChild(boite);
    }
    boite.innerHTML = '';
    var el = document.createElement('div');
    el.id = 'tache-ligne-' + id;
    boite.appendChild(el);
    return '#tache-ligne-' + id;
  }
  if (K && typeof K.rejouerAction === 'function' && !K.rejouerAction.tacheDialog) {
    var rejouer = K.rejouerAction;
    K.rejouerAction = function (a) {
      var m = a && typeof a.cible === 'string' ? /^#tache-ligne-(\d+)$/.exec(a.cible) : null;
      if (m && !document.querySelector(a.cible)) {
        var copie = {};
        Object.keys(a).forEach(function (k) { copie[k] = a[k]; });
        copie.cible = document.getElementById('tache-fenetre-' + m[1]) ? '#tache-fenetre-' + m[1] : receptacle(m[1]);
        a = copie;
      }
      return rejouer.call(K, a);
    };
    K.rejouerAction.tacheDialog = true;
  }

  /* ---------------------------------------------------------------- */
  /* Après une mise à jour partielle                                   */
  /* ---------------------------------------------------------------- */
  var closesOuvertes = false;
  document.addEventListener('toggle', function (e) {
    if (e.target && e.target.id === 'taches-closes') closesOuvertes = e.target.open;
  }, true);
  document.addEventListener('kairos:fragment', function (e) {
    var racine = e.detail && e.detail.racine;
    if (!racine || !racine.nodeType) return;
    oublierPrecharges();
    // Action faite depuis le panneau (pas son chargement) : le contenu de
    // la page hors fiche suit ; le réceptacle de « Annuler » est vidé.
    if (rafraichir && racine !== corps && (dialog.contains(racine) || (racine.closest && racine.closest('#tache-receptacle')))) {
      var boite = document.getElementById('tache-receptacle');
      if (boite && boite.contains(racine)) boite.innerHTML = '';
      rafraichirContenu();
    }
    // Contenu hors fiche rafraîchi juste après la fermeture (Retour vers
    // l'entrée sans ?tache=, rejouée par le socle) : la barre qui avait le
    // focus a été remplacée ; il revient sur la ligne de la tâche fermée,
    // après la remise du focus du socle.
    if (rafraichir && !dialog.open && idDernierFerme && Date.now() - fermeLe < 5000 && racine.matches && racine.matches(rafraichir)) {
      setTimeout(function () {
        var actif = document.activeElement;
        if (dialog.open || (actif && actif !== document.body && actif !== racine && document.contains(actif))) return;
        var l = ligneDe(idDernierFerme);
        var b = l ? l.querySelector('[data-ouvrir-tache]') : null;
        if (b) b.focus({ preventScroll: true });
      }, 0);
    }
    // Panneau remplacé : nom de la fenêtre et état de référence à jour.
    if (dialog.contains(racine)) {
      nommer();
      lienFiche();
      if (FW) FW.memoriser(dialog);
    }
    // Carte des tâches remplacée : tâches closes dépliées si elles
    // l'étaient, ligne de la tâche ouverte marquée.
    if (racine.id === 'carte-taches') {
      var det = document.getElementById('taches-closes');
      if (det && closesOuvertes && !det.open) det.open = true;
    }
    if (dialog.open) marquerLigne();
  });

  // Préchargement au survol (souris seulement, après 120 ms).
  document.addEventListener('pointerover', function (e) {
    if (e.pointerType !== 'mouse') return;
    var ligne = e.target.closest && e.target.closest('[data-open-tache]');
    if (!ligne || ligne.contains(e.relatedTarget)) return;
    clearTimeout(minuteur);
    // Adresse du panneau portée par la ligne (Deadlines) lue AVANT le
    // préchargement : sinon l'adresse modèle (projet 0) répondait 404.
    var id = ligne.getAttribute('data-open-tache');
    if (ligne.hasAttribute('data-tache-url')) urlsTaches[id] = ligne.getAttribute('data-tache-url');
    minuteur = setTimeout(function () { precharger(id); }, 120);
  });
  document.addEventListener('pointerout', function (e) {
    var ligne = e.target.closest && e.target.closest('[data-open-tache]');
    if (ligne && !ligne.contains(e.relatedTarget)) clearTimeout(minuteur);
  });

  // Lot 17 : échéance enregistrée au changement (plus de bouton). Le type
  // part tout de suite ; la date à la sortie du champ ou 900 ms après la
  // dernière modification (la saisie au clavier change jour, mois, année
  // l'un après l'autre) ; Entrée envoie (formulaire natif).
  var minuteurEcheance = null;
  function envoyerEcheance(form) {
    clearTimeout(minuteurEcheance);
    if (!form || !document.contains(form)) return;
    var date = form.querySelector('input[type="date"]');
    var type = form.querySelector('select');
    var cle = (date ? date.value : '') + '|' + (type ? type.value : '');
    if (form.dataset.envoye === cle) return;
    // Date hors bornes : message du navigateur, rien n'est envoyé.
    if (date && date.value && !date.checkValidity()) { date.reportValidity(); return; }
    if (form.dataset.initial === undefined) form.dataset.initial = cle;
    if (cle === form.dataset.initial) return;
    form.dataset.envoye = cle;
    if (form.requestSubmit) form.requestSubmit(); else form.submit();
  }
  document.addEventListener('focusin', function (e) {
    var form = e.target.closest && e.target.closest('.tache-echeance-form');
    if (!form || form.dataset.initial !== undefined) return;
    var date = form.querySelector('input[type="date"]');
    var type = form.querySelector('select');
    form.dataset.initial = (date ? date.value : '') + '|' + (type ? type.value : '');
  });
  document.addEventListener('change', function (e) {
    var form = e.target.closest && e.target.closest('.tache-echeance-form');
    if (!form) return;
    clearTimeout(minuteurEcheance);
    if (e.target.tagName === 'SELECT') { envoyerEcheance(form); return; }
    minuteurEcheance = setTimeout(function () { envoyerEcheance(form); }, 900);
  });
  document.addEventListener('focusout', function (e) {
    var form = e.target.closest && e.target.closest('.tache-echeance-form');
    if (!form || form.contains(e.relatedTarget)) return;
    envoyerEcheance(form);
  });
})();

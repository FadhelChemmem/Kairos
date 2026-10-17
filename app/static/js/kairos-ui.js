// Comportements communs à toutes les pages (lot 13 : sortis des <script> en
// ligne de base.html — la CSP n'autorise plus que des fichiers).
//   - bascule clair/sombre (bouton à état, transition de couleurs de 180 ms) ;
//   - « Copier le chemin » des chemins réseau \\NAS\… (lot 10, B8) ;
//   - pas de double envoi des formulaires POST classiques (lot 10, I4) ;
//   - « Voir comme » : toute écriture désactivée dans la page (bug UX I1) ;
//   - contrôle segmenté à indicateur glissant (.k-segmente).
(function () {
  var K = window.Kairos || {};

  // --- Thème -----------------------------------------------------------------
  var bouton = document.getElementById('theme-toggle');
  if (bouton) {
    var racine = document.documentElement;
    bouton.setAttribute('aria-pressed', racine.dataset.theme === 'dark' ? 'true' : 'false');
    var minuteurTheme = null;
    bouton.addEventListener('click', function () {
      var suivant = racine.dataset.theme === 'dark' ? 'light' : 'dark';
      racine.classList.add('k-theme-transition');
      clearTimeout(minuteurTheme);
      minuteurTheme = setTimeout(function () { racine.classList.remove('k-theme-transition'); }, 260);
      racine.dataset.theme = suivant;
      bouton.setAttribute('aria-pressed', suivant === 'dark' ? 'true' : 'false');
      window.kairosThemeChoisi = true;
      try { localStorage.setItem('kairos-theme', suivant); } catch (e) { /* session en cours seulement */ }
    });
  }

  // --- Copier le chemin -------------------------------------------------------
  // navigator.clipboard n'existe qu'en contexte sécurisé (HTTPS ou
  // localhost) ; Kairos est servi en HTTP sur le LAN : repli par sélection.
  function parSelection(texte, b) {
    var ta = document.createElement('textarea');
    ta.value = texte;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed; top:0; left:0; opacity:0;';
    document.body.appendChild(ta);
    ta.select();
    var reussi = false;
    try { reussi = document.execCommand('copy'); } catch (x) { reussi = false; }
    ta.remove();
    b.focus();
    return reussi;
  }
  function copier(texte, b) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(texte).catch(function () {
        if (!parSelection(texte, b)) throw new Error('copie impossible');
      });
    }
    return parSelection(texte, b) ? Promise.resolve() : Promise.reject(new Error('copie impossible'));
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-copier]');
    if (!b) return;
    var texte = b.getAttribute('data-copier');
    var libelle = b.querySelector('.copier-libelle') || b;
    var initial = b.dataset.libelleInitial || libelle.textContent;
    b.dataset.libelleInitial = initial;
    var retour = b.parentNode.querySelector('.copier-statut');
    function afficher(msg) {
      libelle.textContent = msg;
      if (retour) retour.textContent = msg;
      clearTimeout(b._minuteur);
      b._minuteur = setTimeout(function () { libelle.textContent = initial; if (retour) retour.textContent = ''; }, 2500);
    }
    copier(texte, b).then(function () { afficher('Chemin copié'); }, function () {
      var code = b.parentNode.querySelector('code');
      if (code) { var r = document.createRange(); r.selectNodeContents(code); var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r); }
      afficher('Sélectionné\u00a0: Ctrl+C pour copier');
    });
  });

  // --- Pas de double envoi ----------------------------------------------------
  // Formulaire POST classique (hors réaction ✓ et formulaires partiels, qui
  // gardent le focus avec aria-disabled) : boutons désactivés une fois
  // parti ; réactivés si la page revient du cache.
  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (e.defaultPrevented || (f.method || '').toLowerCase() !== 'post' || f.classList.contains('post-reaction-form') || f.hasAttribute('data-partiel')) return;
    setTimeout(function () {
      if (e.defaultPrevented) return;
      f.querySelectorAll('button[type=submit], button:not([type])').forEach(function (b) {
        b.disabled = true;
        b.dataset.autoDesactive = '1';
      });
    }, 0);
  });
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) document.querySelectorAll('[data-auto-desactive]').forEach(function (b) { b.disabled = false; delete b.dataset.autoDesactive; });
  });

  // --- « Voir comme » : lecture seule ------------------------------------------
  // Le serveur refuse déjà toute écriture ; l'interface ne la propose plus
  // (bug UX I1 : un clic sur ✓ menait à la page « Lecture seule »). Seuls
  // restent actifs les formulaires marqués data-permis-lecture (Revenir à
  // mon compte, date simulée, déconnexion). Le Daily log affiche son propre
  // refus (réponse 403 de son API).
  var TITRE_LS = 'Lecture seule («\u00a0Voir comme\u00a0»)\u00a0: revenez à votre compte pour agir.';
  function lectureSeule(racine) {
    if (!document.documentElement.hasAttribute('data-lecture-seule')) return;
    racine = racine && racine.querySelectorAll ? racine : document;
    racine.querySelectorAll('form').forEach(function (f) {
      if ((f.getAttribute('method') || 'get').toLowerCase() !== 'post' || f.hasAttribute('data-permis-lecture')) return;
      f.querySelectorAll('button, input:not([type=hidden]), textarea, select').forEach(function (c) {
        c.disabled = true;
        c.title = TITRE_LS;
      });
    });
    racine.querySelectorAll('button[form]').forEach(function (b) {
      var f = document.getElementById(b.getAttribute('form'));
      if (f && !f.hasAttribute('data-permis-lecture')) { b.disabled = true; b.title = TITRE_LS; }
    });
    racine.querySelectorAll('[data-open-post-dialog], [data-open-projet-dialog]').forEach(function (b) {
      b.disabled = true;
      b.title = TITRE_LS;
    });
  }
  lectureSeule(document);
  document.addEventListener('kairos:fragment', function (e) { lectureSeule(e.detail && e.detail.racine); });
  // Revue d'interaction P1-11 : un appui sur une commande désactivée en
  // lecture seule le dit (une fois par page), avec « Revenir à mon compte ».
  var lectureSeuleDite = false;
  document.addEventListener('pointerdown', function (e) {
    if (lectureSeuleDite || !document.documentElement.hasAttribute('data-lecture-seule')) return;
    var c = e.target.closest && e.target.closest('button:disabled, input:disabled, select:disabled, textarea:disabled');
    if (!c || c.title !== TITRE_LS || !window.Kairos || !window.Kairos.toast) return;
    lectureSeuleDite = true;
    var revenir = document.querySelector('.bandeau-admin-voir form[data-permis-lecture] .bandeau-admin-bouton');
    window.Kairos.toast(window.Kairos.MESSAGE_LECTURE_SEULE, { type: 'info', action: revenir ? {
      libelle: revenir.textContent.trim(),
      surClic: function () { var f = revenir.form; if (f.requestSubmit) f.requestSubmit(revenir); else f.submit(); }
    } : null });
  }, true);

  // --- Contrôle segmenté -------------------------------------------------------
  function actifDe(groupe) {
    var a = groupe.querySelector(':scope > [aria-current="page"], :scope > [aria-pressed="true"], :scope > [aria-selected="true"]');
    if (a) return a;
    var labels = groupe.querySelectorAll('label[for]');
    for (var i = 0; i < labels.length; i++) {
      var r = document.getElementById(labels[i].htmlFor);
      if (r && r.checked) return labels[i];
    }
    return null;
  }
  function placer(groupe) {
    var a = actifDe(groupe);
    if (!a || !a.offsetWidth) { groupe.classList.remove('k-segmente-pret'); return; }
    groupe.style.setProperty('--seg-x', a.offsetLeft + 'px');
    groupe.style.setProperty('--seg-w', a.offsetWidth + 'px');
    groupe.classList.add('k-segmente-pret');
  }
  var observateur = window.ResizeObserver ? new ResizeObserver(function (entrees) { entrees.forEach(function (en) { placer(en.target); }); }) : null;
  // L'indicateur suit le segment courant quel que soit celui qui le change
  // (clic, état optimiste, fragment re-rendu, retour en arrière) : sans
  // cela il restait sur l'ancien segment (vidéo du 17/10, « Les miennes |
  // Toutes » de l'accueil).
  var suiveur = window.MutationObserver ? new MutationObserver(function (mutations) {
    var vus = [];
    mutations.forEach(function (m) {
      var g = m.target.closest && m.target.closest('.k-segmente');
      if (g && vus.indexOf(g) < 0) { vus.push(g); placer(g); }
    });
  }) : null;
  function segmentes(racine) {
    (racine && racine.querySelectorAll ? racine : document).querySelectorAll('.k-segmente').forEach(function (g) {
      if (g.dataset.segInit) { placer(g); return; }
      g.dataset.segInit = '1';
      placer(g);
      if (observateur) observateur.observe(g);
      if (suiveur) suiveur.observe(g, { subtree: true, attributes: true, attributeFilter: ['aria-current', 'aria-pressed', 'aria-checked'] });
    });
  }
  segmentes(document);
  document.addEventListener('kairos:fragment', function (e) { segmentes(e.detail && e.detail.racine); });
  document.addEventListener('change', function (e) {
    if (e.target && e.target.type === 'radio') document.querySelectorAll('.k-segmente').forEach(placer);
  });
  document.addEventListener('click', function (e) {
    var g = e.target.closest && e.target.closest('.k-segmente');
    if (g) setTimeout(function () { placer(g); }, 0);
  });

  // Lot 15 : <details data-preference="cle" data-preference-url="…"> — l'état
  // ouvert ou replié est gardé pour le compte (utilisateur_preference).
  K.enregistrerPreference = function (url, cle, valeur) {
    var corps = new URLSearchParams();
    corps.set('cle', cle);
    corps.set('valeur', valeur ? '1' : '0');
    return fetch(url, { method: 'POST', body: corps, credentials: 'same-origin' }).catch(function () { /* réglage non gardé */ });
  };
  document.addEventListener('toggle', function (e) {
    var d = e.target;
    if (!d || !d.hasAttribute || !d.hasAttribute('data-preference') || lectureSeule()) return;
    // « toggle » part aussi au chargement d'un <details open> : on n'écrit
    // que si l'état diffère de celui gardé pour le compte.
    var etat = d.open ? '1' : '0';
    if (d.getAttribute('data-preference-etat') === etat) return;
    d.setAttribute('data-preference-etat', etat);
    K.enregistrerPreference(d.getAttribute('data-preference-url'), d.getAttribute('data-preference'), d.open);
  }, true);

  K.lectureSeuleUI = lectureSeule;
})();

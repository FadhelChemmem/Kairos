// Notifications (lot 13, audit UX §2.7 et §4.5) :
//  - aperçu de la cloche : les 10 dernières, chargées à la demande
//    (squelette au premier affichage, ancien contenu atténué ensuite) ;
//    Échap, clic ailleurs ou Tab hors de l'aperçu le ferment, le focus
//    revient à la cloche. Sans JavaScript, la cloche mène à la page ;
//  - « Marquer comme lue » et « Tout marquer comme lu » optimistes (pastilles
//    éteintes, badge mis à jour tout de suite, rétablis si le serveur refuse) ;
//  - badge de la cloche et de la barre basse tenu à jour : après chaque
//    fragment (#notifs-nb, hors cible) et toutes les 60 s quand la page est
//    visible (/notifications/compte).
//  - correctif du lot 13 (verif-ux, écart d) : sur téléphone, la cloche de
//    la barre basse ouvre le même aperçu en feuille en bas de l'écran (au
//    lieu de la page) ; Échap, clic à côté ou un second appui la ferment,
//    le focus revient à la cloche de la barre basse.
(function () {
  var cloche = document.getElementById('notifs-cloche');
  var popover = document.getElementById('notifs-popover');
  var K = window.Kairos;

  function nb() {
    var d = document.getElementById('notifs-nb');
    var n = d ? parseInt(d.getAttribute('value'), 10) : 0;
    return isNaN(n) ? 0 : n;
  }
  function libelle(n) { return 'Notifications' + (n ? ', ' + n + (n > 1 ? ' non lues' : ' non lue') : ''); }
  function majBadge(n) {
    n = Math.max(0, n | 0);
    var d = document.getElementById('notifs-nb');
    if (d) d.setAttribute('value', String(n));
    document.querySelectorAll('[data-notifs-badge]').forEach(function (b) {
      b.textContent = n < 10 ? String(n) : '9+';
      b.hidden = !n;
    });
    if (cloche) cloche.setAttribute('aria-label', libelle(n));
    // Lot 24 : pastille sur l'icône de l'appli installée (barre des tâches).
    try {
      if (navigator.setAppBadge) { if (n) navigator.setAppBadge(n).catch(function () {}); else navigator.clearAppBadge().catch(function () {}); }
    } catch (e) { /* navigateur sans pastille */ }
    document.querySelectorAll('[data-notifs-lien]').forEach(function (a) { a.setAttribute('aria-label', libelle(n)); });
  }
  window.KairosNotifications = { majBadge: majBadge, nb: nb };

  // --- Optimistes ---------------------------------------------------------
  function eteindre(ligne) {
    ligne.classList.remove('non-lu');
    var b = ligne.querySelector('.notif-item');
    if (b) b.classList.remove('non-lu');
    var dot = ligne.querySelector('.notif-dot');
    if (dot) dot.classList.add('vide');
    var etat = ligne.querySelector('.notif-etat');
    if (etat) etat.hidden = true;
  }
  function rallumer(ligne) {
    ligne.classList.add('non-lu');
    var b = ligne.querySelector('.notif-item');
    if (b) b.classList.add('non-lu');
    var dot = ligne.querySelector('.notif-dot');
    if (dot) dot.classList.remove('vide');
    var etat = ligne.querySelector('.notif-etat');
    if (etat) etat.hidden = false;
  }
  if (K && K.optimistes) {
    K.optimistes['notif-lue'] = function (el) {
      var ligne = el.closest && el.closest('.notif-ligne');
      if (!ligne || !ligne.classList.contains('non-lu')) return null;
      var avant = nb();
      // La même notification peut être à la fois dans l'aperçu et dans la page.
      var lignes = Array.prototype.filter.call(document.querySelectorAll('.notif-ligne.non-lu'), function (l) { return l.id === ligne.id; });
      lignes.forEach(eteindre);
      majBadge(avant - 1);
      return function () { lignes.forEach(function (l) { if (document.contains(l)) rallumer(l); }); majBadge(avant); };
    };
    K.optimistes['notifs-toutes-lues'] = function () {
      var avant = nb();
      var lignes = Array.prototype.slice.call(document.querySelectorAll('.notif-ligne.non-lu'));
      lignes.forEach(eteindre);
      majBadge(0);
      return function () { lignes.forEach(function (l) { if (document.contains(l)) rallumer(l); }); majBadge(avant); };
    };
  }
  document.addEventListener('kairos:fragment', function () { majBadge(nb()); });
  if (navigator.setAppBadge && document.getElementById('notifs-nb')) majBadge(nb());

  // --- Badge tenu à jour --------------------------------------------------
  var urlCompte = cloche && cloche.getAttribute('data-url-compte');
  var dernier = 0;
  function rafraichir() {
    if (!urlCompte || !window.fetch || document.hidden || Date.now() - dernier < 20000) return;
    dernier = Date.now();
    fetch(urlCompte, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.ok && /json/.test(r.headers.get('Content-Type') || '') ? r.json() : null; })
      .then(function (d) { if (d && typeof d.non_lues === 'number' && d.non_lues !== nb()) majBadge(d.non_lues); })
      .catch(function () { /* réseau : on réessaiera */ });
  }
  if (urlCompte) {
    dernier = Date.now();
    setInterval(rafraichir, 60000);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) rafraichir(); });
  }

  // --- Aperçu de la cloche --------------------------------------------------
  if (!cloche || !popover || !K || !K.requete) return;
  var ouvert = false;
  var declencheur = cloche;   // cloche du haut ou de la barre basse
  var proprietes = ['width', 'right', 'left', 'top', 'bottom', 'maxHeight', 'borderRadius', 'maxWidth'];

  function enFeuille() { return declencheur !== cloche; }
  function placer() {
    proprietes.forEach(function (p) { popover.style[p] = ''; });
    popover.classList.toggle('notifs-popover-feuille', enFeuille());
    if (enFeuille()) {
      // Feuille au-dessus de la barre basse, pleine largeur.
      var barre = declencheur.closest('.k-nav-basse');
      var bas = barre ? Math.round(window.innerHeight - barre.getBoundingClientRect().top) : 0;
      popover.style.left = '0px';
      popover.style.right = '0px';
      popover.style.width = 'auto';
      popover.style.maxWidth = 'none';
      popover.style.top = 'auto';
      popover.style.bottom = bas + 'px';
      popover.style.maxHeight = 'min(70vh, calc(100vh - ' + (bas + 72) + 'px))';
      popover.style.borderRadius = '16px 16px 0 0';
      return;
    }
    var r = cloche.getBoundingClientRect();
    var largeur = Math.min(380, window.innerWidth - 16);
    popover.style.width = largeur + 'px';
    var droite = Math.max(8, window.innerWidth - r.right - 8);
    if (window.innerWidth - droite - largeur < 8) droite = window.innerWidth - largeur - 8;
    popover.style.right = droite + 'px';
    popover.style.top = Math.round(r.bottom + 8) + 'px';
  }
  function fermer(rendreFocus) {
    if (!ouvert) return;
    ouvert = false;
    popover.hidden = true;
    declencheur.setAttribute('aria-expanded', 'false');
    document.removeEventListener('mousedown', dehors, true);
    if (rendreFocus) declencheur.focus();
  }
  function dehors(e) {
    if (popover.contains(e.target) || declencheur.contains(e.target) || (e.target.closest && e.target.closest('.k-toasts, .k-confirmation'))) return;
    // Revue d'interaction P2-14 : focus dans l'aperçu et clic sur une zone
    // non focalisable (il tombait sur <main>) : il revient à la cloche.
    var dedans = popover.contains(document.activeElement);
    var focalisable = e.target.closest && e.target.closest('a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex="-1"])');
    var retour = declencheur;
    fermer(false);
    if (dedans && !focalisable) setTimeout(function () { retour.focus({ preventScroll: true }); }, 0);
  }
  function ouvrir(depuis) {
    declencheur = depuis || cloche;
    ouvert = true;
    placer();
    popover.hidden = false;
    declencheur.setAttribute('aria-expanded', 'true');
    document.addEventListener('mousedown', dehors, true);
    K.requete({ url: cloche.getAttribute('href'), methode: 'GET', cible: '#notifs-apercu', historique: 'aucun', transition: false })
      .then(function (res) {
        if (!ouvert || !res || !res.racine) return;
        var titre = document.getElementById('notifs-apercu-titre');
        if (titre && !popover.contains(document.activeElement)) titre.focus({ preventScroll: true });
      });
  }
  cloche.addEventListener('click', function (e) {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    if (!cloche.offsetParent) return;
    e.preventDefault();
    if (ouvert && declencheur === cloche) fermer(false);
    else { if (ouvert) fermer(false); ouvrir(cloche); }
  });
  document.querySelectorAll('[data-notifs-lien]').forEach(function (lien) {
    lien.setAttribute('aria-haspopup', 'dialog');
    lien.setAttribute('aria-controls', 'notifs-popover');
    lien.setAttribute('aria-expanded', 'false');
    lien.addEventListener('click', function (e) {
      if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || !lien.offsetParent) return;
      // Déjà sur la page des notifications : le lien garde son rôle.
      if (lien.getAttribute('aria-current') === 'page') return;
      e.preventDefault();
      if (ouvert && declencheur === lien) fermer(false);
      else { if (ouvert) fermer(false); ouvrir(lien); }
    });
    lien.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && ouvert && declencheur === lien) { e.preventDefault(); fermer(true); }
    });
  });
  popover.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); fermer(true); }
  });
  cloche.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && ouvert) { e.preventDefault(); fermer(true); }
  });
  popover.addEventListener('focusout', function (e) {
    var vers = e.relatedTarget;
    if (vers && !popover.contains(vers) && vers !== declencheur && !(vers.closest && vers.closest('.k-toasts, .k-confirmation'))) fermer(false);
  });
  window.addEventListener('resize', function () { if (ouvert) placer(); });
})();

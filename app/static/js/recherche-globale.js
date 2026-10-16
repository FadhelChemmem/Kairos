// Recherche globale (topbar) — demandée par Fadhel (2026-09-19) : projets,
// tâches et personnes visibles, via /recherche/api (adresse dans data-url).
// Lot 10 (audit front I1) : jeton de séquence, combobox ARIA, flèches,
// Échap, fermeture quand le focus quitte la recherche, nombre annoncé.
// Lot 13 (sorti de base.html) : lignes squelettes si la réponse tarde
// (> 150 ms), terme surligné (<mark>), et sous 860 px un bouton loupe qui
// ouvre la recherche en plein écran (audit UX I8, a11y I2) ; Ctrl/⌘ + K et
// « / » (raccourcis.js) passent par Kairos.ouvrirRecherche().
(function () {
  var input = document.getElementById('recherche-globale');
  var box = document.getElementById('recherche-globale-resultats');
  var statut = document.getElementById('recherche-globale-statut');
  var ouvrirBtn = document.querySelector('[data-recherche-ouvrir]');
  var fermerBtn = document.querySelector('[data-recherche-fermer]');
  if (!input || !box) return;
  var url = input.getAttribute('data-url');
  var timer = null;
  var attente = null;
  var seq = 0;
  var mobile = window.matchMedia ? window.matchMedia('(max-width: 860px)') : null;

  function sansAccents(s) {
    if (window.KairosTexte) return window.KairosTexte.sansAccents(s);
    return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  }

  function montrer(v) {
    box.hidden = !v;
    input.setAttribute('aria-expanded', v ? 'true' : 'false');
    if (!v) activer(-1);
  }
  function liens() { return Array.prototype.slice.call(box.querySelectorAll('a')); }

  // Lot 13 (audit a11y M7) : le focus reste dans le champ ; l'option
  // parcourue aux flèches est désignée par aria-activedescendant (lue par
  // les lecteurs d'écran, surlignée à l'écran), Entrée l'ouvre.
  var actif = -1;
  function activer(i) {
    var l = liens();
    actif = i >= 0 && i < l.length ? i : -1;
    l.forEach(function (a, j) {
      a.classList.toggle('is-active', j === actif);
      a.setAttribute('aria-selected', j === actif ? 'true' : 'false');
    });
    if (actif >= 0) {
      input.setAttribute('aria-activedescendant', l[actif].id);
      if (l[actif].scrollIntoView) l[actif].scrollIntoView({ block: 'nearest' });
    } else {
      input.removeAttribute('aria-activedescendant');
    }
  }

  /** Libellé avec les mots cherchés entourés de <mark> (DOM, jamais innerHTML). */
  function surligner(parent, texte, q) {
    var mots = sansAccents(q).split(/\s+/).filter(function (m) { return m.length > 0; });
    // Texte normalisé caractère par caractère, avec l'indice d'origine.
    var norm = '', origine = [];
    for (var i = 0; i < texte.length; i++) {
      var n = sansAccents(texte.charAt(i));
      for (var j = 0; j < n.length; j++) { norm += n.charAt(j); origine.push(i); }
    }
    var marque = new Array(texte.length);
    mots.forEach(function (mot) {
      var pos = norm.indexOf(mot);
      while (pos !== -1) {
        for (var k = pos; k < pos + mot.length; k++) marque[origine[k]] = true;
        pos = norm.indexOf(mot, pos + mot.length);
      }
    });
    var courant = '', dedans = false;
    function vider() {
      if (!courant) return;
      if (dedans) { var m = document.createElement('mark'); m.textContent = courant; parent.appendChild(m); }
      else parent.appendChild(document.createTextNode(courant));
      courant = '';
    }
    for (var c = 0; c < texte.length; c++) {
      if (!!marque[c] !== dedans) { vider(); dedans = !!marque[c]; }
      courant += texte.charAt(c);
    }
    vider();
  }

  function squelettes() {
    activer(-1);
    box.innerHTML = '';
    for (var i = 0; i < 3; i++) {
      var s = document.createElement('div');
      s.className = 'recherche-squelette';
      s.setAttribute('aria-hidden', 'true');
      s.innerHTML = '<span class="k-squelette k-squelette-ligne" style="width:' + (70 - i * 15) + '%"></span>';
      box.appendChild(s);
    }
    if (statut) statut.textContent = 'Recherche…';
    montrer(true);
  }

  function render(items, q) {
    // Contrôle XSS (PROMPT_CORRECTIONS.md P0 #4) : libellés construits par le
    // DOM (textContent), jamais par concaténation de HTML.
    activer(-1);
    box.innerHTML = '';
    if (statut) statut.textContent = items.length ? (items.length + (items.length > 1 ? ' résultats' : ' résultat')) : 'Aucun résultat';
    if (!items.length) {
      var vide = document.createElement('div');
      vide.className = 'recherche-vide';
      vide.textContent = 'Aucun résultat.';
      box.appendChild(vide);
      montrer(true);
      return;
    }
    items.forEach(function (it, i) {
      var a = document.createElement('a');
      a.href = it.url;
      a.id = 'recherche-globale-opt-' + i;
      a.tabIndex = -1;
      a.setAttribute('role', 'option');
      a.setAttribute('aria-selected', 'false');
      a.className = 'recherche-resultat';
      var label = document.createElement('span');
      surligner(label, String(it.label || ''), q);
      a.appendChild(label);
      if (it.sous_titre) {
        var sous = document.createElement('span');
        sous.className = 'recherche-resultat-sous';
        sous.textContent = it.sous_titre;
        a.appendChild(sous);
      }
      box.appendChild(a);
    });
    montrer(true);
  }

  var entreeEnAttente = false;
  input.addEventListener('input', function () {
    entreeEnAttente = false;
    var q = input.value.trim();
    clearTimeout(timer);
    clearTimeout(attente);
    var n = ++seq;
    if (q.length < 2) { montrer(false); if (statut) statut.textContent = ''; return; }
    timer = setTimeout(function () {
      attente = setTimeout(function () { if (n === seq) squelettes(); }, 150);
      fetch(url + '?q=' + encodeURIComponent(q), { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          clearTimeout(attente);
          if (n !== seq) return;
          render(data.resultats || [], q);
          if (entreeEnAttente) { entreeEnAttente = false; var l0 = liens(); if (l0.length) l0[0].click(); }
        })
        .catch(function () { clearTimeout(attente); if (n === seq) montrer(false); });
    }, 220);
  });

  input.addEventListener('keydown', function (e) {
    var l = liens();
    if (e.key === 'Escape') {
      if (!box.hidden) { e.preventDefault(); montrer(false); }
      else if (document.body.classList.contains('k-recherche-ouverte')) { e.preventDefault(); fermerPleinEcran(); }
    } else if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && l.length && !box.hidden) {
      e.preventDefault();
      if (e.key === 'ArrowDown') activer(actif < l.length - 1 ? actif + 1 : actif);
      else activer(actif - 1);
    } else if (e.key === 'Enter' && input.value.trim().length >= 2) {
      // Lot 15 (revue UX) : Entrée ouvre le résultat choisi, à défaut le
      // premier ; résultats pas encore arrivés : ouvert dès leur arrivée.
      e.preventDefault();
      if (!box.hidden && l.length) (l[actif >= 0 ? actif : 0]).click();
      else entreeEnAttente = true;
    }
  });
  // Liste fermée dès que le focus (Tab) ou un clic quitte la recherche.
  var zone = input.closest('.topbar-search') || box.parentNode;
  document.addEventListener('focusin', function (e) {
    if (!box.contains(e.target) && e.target !== input) montrer(false);
    if (document.body.classList.contains('k-recherche-ouverte') && !zone.contains(e.target)) fermerPleinEcran(true);
  });
  document.addEventListener('click', function (e) {
    if (!box.contains(e.target) && e.target !== input) montrer(false);
  });

  // --- Plein écran (téléphone, zoom) ---------------------------------------
  function ouvrirPleinEcran() {
    document.body.classList.add('k-recherche-ouverte');
    if (ouvrirBtn) ouvrirBtn.setAttribute('aria-expanded', 'true');
    input.focus();
    if (input.value.trim().length >= 2 && box.childNodes.length) montrer(true);
  }
  function fermerPleinEcran(sansFocus) {
    if (!document.body.classList.contains('k-recherche-ouverte')) return;
    document.body.classList.remove('k-recherche-ouverte');
    montrer(false);
    if (ouvrirBtn) {
      ouvrirBtn.setAttribute('aria-expanded', 'false');
      if (!sansFocus) ouvrirBtn.focus();
    }
  }
  if (ouvrirBtn) ouvrirBtn.addEventListener('click', ouvrirPleinEcran);
  if (fermerBtn) fermerBtn.addEventListener('click', function () { fermerPleinEcran(); });
  if (mobile && mobile.addEventListener) {
    mobile.addEventListener('change', function (e) { if (!e.matches) fermerPleinEcran(true); });
  }

  window.Kairos = window.Kairos || {};
  window.Kairos.ouvrirRecherche = function () {
    if (mobile && mobile.matches) ouvrirPleinEcran();
    else { input.focus(); input.select(); }
  };
})();

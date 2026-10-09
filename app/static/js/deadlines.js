// Deadlines (lot 13 : sorti du <script> en ligne de deadlines.html).
// - Aide « Faites défiler… » affichée seulement s'il y a vraiment à défiler.
// - Filtre « par projet ou tâche » : masque les lignes du Gantt, de la liste
//   du téléphone et (vue Admin) des tâches sans échéance, sans recharger
//   (Fadhel, 2026-09-19) ; sans accents, état vide annoncé ; ?q= tenu dans
//   l'adresse (replaceState).
// - Lot 13 (phase 2) : bascule « Mes projets / Tous les projets » et filtres
//   en mise à jour partielle (kairos-partiel.js) — le contrôle segmenté
//   suit tout de suite le clic (optimiste) puis l'adresse (Retour) ; le
//   contenu remplacé est ré-initialisé sur « kairos:fragment ».
(function () {
  function norm(s) {
    if (window.KairosTexte) return window.KairosTexte.sansAccents(s || '');
    return (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  }

  // Recette finale : ombre au bord droit du Gantt tant qu'il reste des
  // jours à droite (panneau de tâche ouvert : la carte rétrécit sans que
  // la fenêtre change de taille — ResizeObserver).
  var observateur = window.ResizeObserver ? new window.ResizeObserver(function () { majAide(); }) : null;
  function majAide() {
    var carte = document.getElementById('gantt-carte');
    var aide = document.getElementById('gantt-aide-defilement');
    var defile = !!carte && !!carte.offsetParent && carte.scrollWidth > carte.clientWidth + 1;
    if (aide) aide.hidden = !defile;
    if (!carte) return;
    if (observateur && !carte._kairosObserve) { carte._kairosObserve = true; observateur.observe(carte); }
    var ombre = carte.querySelector(':scope > .gantt-ombre');
    if (!ombre) {
      ombre = document.createElement('div');
      ombre.className = 'gantt-ombre';
      ombre.setAttribute('aria-hidden', 'true');
      carte.insertBefore(ombre, carte.firstChild);
    }
    var gantt = carte.querySelector('.gantt');
    var hauteur = gantt ? gantt.offsetHeight + 'px' : '';
    if (gantt && carte.style.getPropertyValue('--gantt-h') !== hauteur) carte.style.setProperty('--gantt-h', hauteur);
    carte.classList.toggle('k-defile-droite', defile && carte.scrollLeft + carte.clientWidth < carte.scrollWidth - 1);
  }
  document.addEventListener('scroll', function (e) {
    if (e.target && e.target.id === 'gantt-carte') majAide();
  }, true);

  function filtrer() {
    var input = document.getElementById('filtre-deadlines');
    if (!input) return;
    var q = norm(input.value.trim()), visibles = 0, total = 0;
    document.querySelectorAll('.g-row, .g-row-mobile, .g-row-sans-echeance').forEach(function (el) {
      if (el._filtre === undefined) el._filtre = norm(el.getAttribute('data-filtre'));
      var ok = !q || el._filtre.indexOf(q) !== -1;
      el.hidden = !ok;
      if (el.classList.contains('g-row')) { total++; if (ok) visibles++; }
    });
    document.querySelectorAll('.deadlines-semaine').forEach(function (s) {
      s.hidden = !s.querySelector('.g-row-mobile:not([hidden])');
    });
    var vide = document.getElementById('deadlines-vide');
    if (vide) {
      var texte = (total && !visibles) ? 'Aucune échéance ne correspond à ce filtre.' : '';
      if (vide.textContent !== texte) vide.textContent = texte;
    }
    majAide();
  }

  function adresseAvecQ(valeur) {
    try {
      var u = new URL(window.location.href);
      if (valeur) u.searchParams.set('q', valeur); else u.searchParams.delete('q');
      return u.pathname + u.search + u.hash;
    } catch (e) { return null; }
  }

  // Contrôle segmenté : l'élément « courant » suit la vue demandée.
  function vueDe(href) {
    try { return new URL(href, window.location.href).searchParams.get('vue') === 'tous' ? 'tous' : ''; } catch (e) { return ''; }
  }
  function marquerVue(vue) {
    document.querySelectorAll('[data-deadlines-bascule] > a').forEach(function (a) {
      if ((a.getAttribute('data-vue') || '') === vue) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
  }

  document.addEventListener('input', function (e) {
    if (!e.target || e.target.id !== 'filtre-deadlines') return;
    filtrer();
    var u = adresseAvecQ(e.target.value.trim());
    if (u) { try { window.history.replaceState(window.history.state, '', u); } catch (x) { /* adresse inchangée */ } }
  });
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[data-partiel="#deadlines-contenu"]');
    if (!a || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    marquerVue(vueDe(a.getAttribute('href')));
  });
  document.addEventListener('kairos:fragment', function (e) {
    var r = e.detail && e.detail.racine;
    if (!r || r === document || !(r.id === 'deadlines-contenu' || (r.closest && r.closest('#deadlines-contenu')))) return;
    marquerVue(vueDe(window.location.href));
    document.querySelectorAll('[data-deadlines-bascule]').forEach(function (n) {
      document.dispatchEvent(new CustomEvent('kairos:fragment', { detail: { racine: n.parentNode } }));
    });
    filtrer();
  });
  window.addEventListener('resize', majAide);
  // Entrée d'historique de la page marquée : Retour après une bascule
  // revient à la vue précédente en partiel (kairos-partiel.js, popstate).
  if (document.getElementById('deadlines-contenu') && !(window.history.state && window.history.state.kairosPartiel)) {
    var st = {};
    if (window.history.state && typeof window.history.state === 'object') Object.keys(window.history.state).forEach(function (k) { st[k] = window.history.state[k]; });
    st.kairosPartiel = { cible: '#deadlines-contenu', mode: 'outer', saisie: null };
    try { window.history.replaceState(st, '', window.location.href); } catch (e) { /* Retour = rechargement */ }
  }
  filtrer();
  majAide();
})();

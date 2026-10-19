// Filtre des posts (accueil, fiche projet) — lot 13 : sorti des <script> en
// ligne d'accueil.html et projet_detail.html. Champ <input data-filtre-fil
// data-filtre-liste="#fil-liste" data-filtre-vide="#fil-vide"
// data-filtre-message="…"> ; chaque post est un .fil-item dont le texte
// filtrable (auteur, projet, équipes, contenu, commentaires) est rendu côté
// serveur dans data-filtre (lot 10, audit front I11). Sans accents ni casse ;
// résultat vide annoncé (role=status). Lot 13 (phase 2) : la liste est
// relue à chaque fois (elle peut être remplacée ou recevoir un post par une
// mise à jour partielle) et le filtre en cours s'applique aux posts
// insérés.
//
// Lot 14 (revue produit P1-3) : contrôle segmenté « Tout · Échanges ·
// Activité » (nav[data-fil-filtres]) — la liste est remplacée en partiel,
// l'adresse suit (?fil=, History API : Retour revient à la catégorie
// précédente), le choix est mémorisé par page (localStorage, protégé) et
// rétabli à l'ouverture suivante ; « Afficher plus » annoncé ; une ancre
// #post-<id> absente de la catégorie affichée bascule sur « Tout » et un
// regroupement replié qui la contient est déplié ; un post plus ancien que
// la première page est chargé (?jusqua=<id>, recette du lot 14 n° 13).
// Lot 21 : bascule « Me concernant » de la fiche projet (?moi=1).
(function () {
  function norm(s) {
    if (window.KairosTexte) return window.KairosTexte.sansAccents(s || '');
    return (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  }
  function filtrer(champ) {
    var liste = document.querySelector(champ.getAttribute('data-filtre-liste'));
    var vide = document.querySelector(champ.getAttribute('data-filtre-vide'));
    var message = champ.getAttribute('data-filtre-message') || 'Aucun résultat pour ce filtre.';
    if (!liste) return;
    var q = norm(champ.value.trim());
    var items = liste.querySelectorAll('.fil-item');
    var visibles = 0;
    Array.prototype.forEach.call(items, function (item) {
      if (item._filtre === undefined) item._filtre = norm(item.getAttribute('data-filtre'));
      var ok = !q || item._filtre.indexOf(q) !== -1;
      if (ok && item.hidden) { item.hidden = false; item.classList.add('k-entree'); }
      else if (!ok) item.hidden = true;
      if (ok) visibles++;
    });
    var aucun = q && items.length && !visibles;
    if (vide) {
      // Lot 13 (audit UX §2.2) : « 3 posts sur 21 » pendant le filtrage.
      vide.textContent = aucun ? message : (q ? visibles + ' post' + (visibles > 1 ? 's' : '') + ' sur ' + items.length : '');
      vide.classList.toggle('card', !!aucun);
    }
  }
  // Le filtre est dans l'adresse (?q=, replaceState) : un rechargement ou un
  // lien partagé le retrouve.
  function memoriser(champ) {
    try {
      var u = new URL(window.location.href);
      if (champ.value.trim()) u.searchParams.set('q', champ.value.trim()); else u.searchParams.delete('q');
      window.history.replaceState(window.history.state, '', u.pathname + u.search + u.hash);
    } catch (e) { /* adresse laissée telle quelle */ }
  }
  document.addEventListener('input', function (e) {
    if (e.target && e.target.hasAttribute && e.target.hasAttribute('data-filtre-fil')) {
      filtrer(e.target);
      memoriser(e.target);
    }
  });
  var initial = new URLSearchParams(window.location.search).get('q');
  if (initial) {
    document.querySelectorAll('input[data-filtre-fil]').forEach(function (champ) {
      if (!champ.value) champ.value = initial;
      filtrer(champ);
    });
  }
  document.addEventListener('kairos:fragment', function () {
    document.querySelectorAll('input[data-filtre-fil]').forEach(function (champ) { if (champ.value.trim()) filtrer(champ); });
  });

  // --- Catégorie du fil (lot 14) --------------------------------------------
  var CATEGORIES = ['tout', 'echanges', 'activite'];
  var CLE = 'kairos-fil-';
  function lire(page) { try { return window.localStorage.getItem(CLE + page); } catch (e) { return null; } }
  // Lot 20 : le choix est aussi écrit en cookie, lu par le serveur — la
  // page complète s'ouvre directement sur la catégorie mémorisée (plus de
  // bascule à l'ouverture qui marquait « vu » l'onglet par défaut).
  function cookie(page, valeur) {
    if (!/^[a-z]+$/.test(page || '') || CATEGORIES.indexOf(valeur) === -1) return;
    // Lot 21 (revue R31) : un document où l'accès aux cookies lève
    // (iframe isolée) garde des onglets fonctionnels, choix non mémorisé.
    try {
      document.cookie = 'kairos_fil_' + page + '=' + valeur + '; path=/; max-age=31536000; SameSite=Lax' +
        (window.location.protocol === 'https:' ? '; Secure' : '');
    } catch (e) { /* choix non mémorisé */ }
  }
  function ecrire(page, valeur) {
    cookie(page, valeur);
    try { window.localStorage.setItem(CLE + page, valeur); } catch (e) { /* choix non mémorisé */ }
  }
  function parametre(nom) { try { return new URL(window.location.href).searchParams.get(nom); } catch (e) { return null; } }
  function adresse(fil, avecAncre, jusqua) {
    var u = new URL(window.location.href);
    u.searchParams.set('fil', fil);
    u.searchParams.delete('avant');
    // Lot 21 : un post demandé par son ancre se cherche dans tout le fil.
    if (jusqua) { u.searchParams.set('jusqua', jusqua); u.searchParams.delete('moi'); } else u.searchParams.delete('jusqua');
    return u.pathname + u.search + (avecAncre ? u.hash : '');
  }
  function courante(nav) {
    var a = nav.querySelector('a[aria-current="page"]');
    return a ? a.getAttribute('data-fil') : null;
  }
  function marquer(nav, fil) {
    Array.prototype.forEach.call(nav.querySelectorAll('a[data-fil]'), function (a) {
      if (a.getAttribute('data-fil') === fil) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
  }
  function navDe(cible) { return document.querySelector('[data-fil-filtres][data-fil-cible="' + cible + '"]'); }
  var ancreAttendue = null;
  function choisir(nav, fil, historique, declencheur, avecAncre, jusqua) {
    var K = window.Kairos;
    var cible = nav.getAttribute('data-fil-cible');
    // Lot 21 (revue R26 / F5) : l'entrée quittée garde sa catégorie dans
    // l'adresse — Retour la rend (sans elle, le serveur prendrait le choix
    // mémorisé, c'est-à-dire la nouvelle catégorie).
    var avant = courante(nav);
    if (historique === 'push' && avant && !parametre('fil')) {
      try {
        var u = new URL(window.location.href);
        u.searchParams.set('fil', avant);
        window.history.replaceState(window.history.state, '', u.pathname + u.search + u.hash);
      } catch (e) { /* adresse laissée telle quelle */ }
    }
    marquer(nav, fil);
    if (!K || !K.requete || !document.querySelector(cible)) { window.location.href = adresse(fil, avecAncre, jusqua); return; }
    K.requete({ url: adresse(fil, avecAncre, jusqua), methode: 'GET', cible: cible, mode: 'outer', historique: historique,
      declencheur: declencheur || null, synchroniser: true });
  }
  // Capture : avant le lien partiel générique du socle (qui voit alors
  // defaultPrevented) — l'adresse est construite depuis la page affichée
  // (autres paramètres gardés, curseur « avant » retiré).
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[data-fil]');
    if (!a || e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    var nav = a.closest('[data-fil-filtres]') || navDe(a.getAttribute('data-partiel'));
    var fil = a.getAttribute('data-fil');
    if (!nav || CATEGORIES.indexOf(fil) === -1) return;
    e.preventDefault();
    ecrire(nav.getAttribute('data-fil-filtres'), fil);
    if (courante(nav) === fil && nav.contains(a)) return;
    choisir(nav, fil, 'push', nav.contains(a) ? a : null);
    if (!nav.contains(a)) { var seg = nav.querySelector('a[data-fil="' + fil + '"]'); if (seg) seg.focus(); }
  }, true);

  // --- Bascule « Me concernant » (lot 21, fiche projet) ---------------------
  // a[data-fil-moi][role=switch] : mes posts, mes mentions et les suites
  // données à mes posts, ou tout le fil. Même mécanique que la catégorie
  // (liste remplacée en partiel, ?moi=1 dans l'adresse, Retour la rend) ;
  // l'état affiché suit la liste reçue (data-fil-moi).
  function adresseMoi(actif) {
    var u = new URL(window.location.href);
    if (actif) u.searchParams.set('moi', '1'); else u.searchParams.delete('moi');
    u.searchParams.delete('avant');
    u.searchParams.delete('jusqua');
    return u;
  }
  function majMoi(actif) {
    Array.prototype.forEach.call(document.querySelectorAll('[role="switch"][data-fil-moi]'), function (b) {
      b.setAttribute('aria-checked', actif ? 'true' : 'false');
      try { var u = adresseMoi(!actif); b.setAttribute('href', u.pathname + u.search); } catch (e) { /* lien gardé */ }
    });
  }
  function basculerMoi(lien, actif) {
    var K = window.Kairos;
    var interrupteur = document.querySelector('[role="switch"][data-fil-moi]');
    var cible = (interrupteur && interrupteur.getAttribute('data-fil-cible')) || '#fil-posts';
    var u = adresseMoi(actif);
    var nav = navDe(cible);
    var categorie = nav && courante(nav);
    if (categorie) u.searchParams.set('fil', categorie);
    var url = u.pathname + u.search;
    majMoi(actif);
    if (!K || !K.requete || !document.querySelector(cible)) { window.location.href = url; return; }
    K.requete({ url: url, methode: 'GET', cible: cible, mode: 'outer', historique: 'push',
      declencheur: interrupteur || lien, synchroniser: true });
  }
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[data-fil-moi], a[data-fil-moi-lien]');
    if (!a || e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    var actif = a.hasAttribute('data-fil-moi') ? a.getAttribute('aria-checked') !== 'true' : false;
    basculerMoi(a, actif);
    if (!a.hasAttribute('data-fil-moi')) { var sw = document.querySelector('[role="switch"][data-fil-moi]'); if (sw) sw.focus(); }
  }, true);
  // Un interrupteur se bascule aussi à la barre d'espace.
  document.addEventListener('keydown', function (e) {
    var a = e.target;
    if ((e.key === ' ' || e.key === 'Spacebar') && a && a.matches && a.matches('[role="switch"][data-fil-moi]')) {
      e.preventDefault();
      a.click();
    }
  });

  // Lot 17 : l'onglet ouvert n'a plus de nouveautés (le serveur le note vu).
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('[data-fil-filtres] a[data-fil]');
    var pastille = a && a.querySelector('[data-fil-non-vus]');
    if (pastille) pastille.remove();
  }, true);

  // « Afficher plus » : nombre de posts ajoutés annoncé (le focus reste sur
  // le bouton, remplacé à l'identique).
  var plus = null;
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a.fil-plus');
    if (!a) return;
    var liste = document.querySelector(a.getAttribute('data-partiel'));
    plus = liste ? { liste: liste, n: liste.querySelectorAll('.fil-item').length } : null;
  }, true);

  function revelerAncre(ancre) {
    var m = /^#post-(\d+)$/.exec(ancre || window.location.hash || '');
    if (!m) return false;
    var el = document.getElementById('post-' + m[1]);
    if (!el) return false;
    var det = el.closest('details.fil-groupe-details');
    if (det && !det.open) { det.open = true; el.scrollIntoView({ block: 'start' }); }
    return true;
  }

  document.addEventListener('kairos:fragment', function (e) {
    var r = e.detail && e.detail.racine;
    if (!r || !r.id) return;
    var nav = navDe('#' + r.id);
    if (nav && r.hasAttribute('data-fil-categorie')) marquer(nav, r.getAttribute('data-fil-categorie'));
    if (r.hasAttribute('data-fil-moi')) majMoi(r.getAttribute('data-fil-moi') === '1');
    if (plus && plus.liste.contains(r) && plus.liste !== r) {
      var n = plus.liste.querySelectorAll('.fil-item').length - plus.n;
      plus = null;
      if (window.Kairos && window.Kairos.annoncer) {
        window.Kairos.annoncer(n > 0 ? n + (n > 1 ? ' éléments ajoutés au fil.' : ' élément ajouté au fil.') : 'Rien de plus à afficher.');
      }
    }
    if (ancreAttendue && nav) {
      var ancre = ancreAttendue;
      ancreAttendue = null;
      if (revelerAncre(ancre)) {
        var el = document.getElementById(ancre.slice(1));
        if (el) el.scrollIntoView({ block: 'start' });
      }
    }
  });

  // Ouverture de la page : ancre d'un post (notification) d'abord, sinon
  // catégorie mémorisée pour cette page quand l'adresse n'en donne pas.
  Array.prototype.forEach.call(document.querySelectorAll('[data-fil-filtres]'), function (nav) {
    var actuelle = courante(nav);
    var dansAdresse = parametre('fil');
    var ancre = /^#post-\d+$/.test(window.location.hash || '');
    if (ancre) {
      // Post absent de la page affichée (autre catégorie, ou plus ancien
      // que la première page — recette du lot 14, n° 13) : « Tout »,
      // chargé jusqu'à lui (?jusqua=, borné côté serveur).
      if (!revelerAncre()) {
        ancreAttendue = window.location.hash;
        choisir(nav, 'tout', 'replace', null, true, window.location.hash.slice('#post-'.length));
      }
      return;
    }
    var memorisee = lire(nav.getAttribute('data-fil-filtres'));
    // Choix mémorisé avant le lot 20 (localStorage seul) : recopié en
    // cookie pour les ouvertures suivantes.
    if (memorisee) cookie(nav.getAttribute('data-fil-filtres'), memorisee);
    if (!dansAdresse && memorisee && CATEGORIES.indexOf(memorisee) !== -1 && memorisee !== actuelle) {
      choisir(nav, memorisee, 'replace');
    }
  });
})();

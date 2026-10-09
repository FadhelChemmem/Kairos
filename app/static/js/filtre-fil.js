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
})();

// « Tous les projets ». Lot 13 (phase 2) : la recherche, les puces de
// filtre et la pagination passent par le socle partiel (kairos-partiel.js,
// attributs data-partiel du formulaire et des liens) — plus de requête
// maison : seul #projets-resultats est remplacé, l'adresse suit
// (pushState ; Retour = filtre ou page précédents, sans recharger),
// indicateur après 150 ms. Ce script ajoute :
//   - les puces resynchronisées sur l'adresse au Retour (sélecteurs à puces
//     et filtre « Lots » à trois états) ;
//   - le titre de l'onglet (« — page 2 ») ;
//   - la ligne entière cliquable à la souris (le lien est sur le nom) ;
//   - « Télécharger en Excel » avec retour : « Préparation… » jusqu'au
//     fichier, toast en cas d'échec.
(function () {
  var form = document.getElementById('filtres-projets');
  if (!form) return;

  // Première arrivée sans filtre dans l'adresse (filtres par défaut du
  // serveur : En cours + Bloqué, chef = moi) : l'adresse les reprend, pour
  // qu'un Retour vers cette entrée retrouve les mêmes puces.
  if (!window.location.search && window.Kairos && window.Kairos.urlFormulaire) {
    try { window.history.replaceState(window.history.state, '', window.Kairos.urlFormulaire(form)); } catch (e) { /* */ }
  }

  // Retour / Avancer : kairos-partiel.js a remis les <select> aux valeurs
  // de l'adresse ; les puces suivent.
  window.addEventListener('popstate', function () {
    var params = new URLSearchParams(window.location.search);
    form.querySelectorAll('select[data-chip-select]').forEach(function (s) { s.dispatchEvent(new Event('change')); });
    form.querySelectorAll('select[data-chip-tristate]').forEach(function (s) {
      var contient = params.getAll(s.getAttribute('data-name-contient') || 'lot_contient');
      var egal = params.getAll(s.getAttribute('data-name-egal') || 'lot_egal');
      Array.prototype.forEach.call(s.options, function (o) {
        o.dataset.mode = egal.indexOf(o.value) !== -1 ? 'egal' : (contient.indexOf(o.value) !== -1 ? 'contient' : '');
      });
      s.dispatchEvent(new Event('kairos:resynchroniser'));
    });
  });

  // Titre de l'onglet (audit a11y M9 : pages 1 et 2 distinguées).
  document.addEventListener('kairos:fragment', function (e) {
    var r = e.detail && e.detail.racine;
    if (!r || r.id !== 'projets-resultats') return;
    var page = parseInt(r.getAttribute('data-page'), 10) || 1;
    document.title = 'Tous les projets' + (page > 1 ? ' — page ' + page : '') + ' — Kairos';
  });

  // Ligne cliquable à la souris (le clavier passe par le lien du nom).
  document.addEventListener('click', function (e) {
    var ligne = e.target.closest && e.target.closest('.ptable-row[data-lien-ligne]');
    if (!ligne || e.target.closest('a, button, input, select') || e.button !== 0) return;
    var lien = ligne.querySelector('a.ptable-lien');
    if (!lien) return;
    if (window.getSelection && String(window.getSelection())) return;   // sélection de texte
    if (e.ctrlKey || e.metaKey) { window.open(lien.href, '_blank', 'noopener'); return; }
    lien.click();
  });

  // Export Excel avec retour.
  document.addEventListener('click', function (e) {
    var lien = e.target.closest && e.target.closest('#export-excel');
    if (!lien || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || !window.fetch || !window.URL || !URL.createObjectURL) return;
    e.preventDefault();
    if (lien.getAttribute('aria-busy') === 'true') return;
    var K = window.Kairos;
    var libelle = lien.querySelector('.export-libelle');
    var initial = libelle ? libelle.textContent : '';
    lien.setAttribute('aria-busy', 'true');
    if (libelle) libelle.textContent = 'Préparation…';
    function fin() {
      lien.removeAttribute('aria-busy');
      if (libelle) libelle.textContent = initial;
    }
    fetch(lien.href, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok || !/spreadsheetml/.test(r.headers.get('Content-Type') || '')) throw new Error('export');
      var dispo = r.headers.get('Content-Disposition') || '';
      var m = /filename="([^"]+)"/.exec(dispo);
      return r.blob().then(function (b) { return { blob: b, nom: m ? m[1] : 'projets-kairos.xlsx' }; });
    }).then(function (res) {
      var url = URL.createObjectURL(res.blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = res.nom;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
      fin();
      if (K) K.toast('Fichier « ' + res.nom + ' » téléchargé.', { type: 'succes' });
    }).catch(function () {
      fin();
      if (K) K.toast('Le fichier Excel n’a pas pu être préparé. Réessayez.', { type: 'erreur' });
    });
  });
})();

/* Combobox de recherche pour un <select> à sélection UNIQUE — remplace
 * visuellement un <select> classique par un champ texte + une liste
 * déroulante filtrée en direct (retour Fadhel, 2026-09-28 : le champ
 * "Projet" du composeur "Nouveau post" listait tous les projets dans un
 * <select> natif, pénible à parcourir à mesure que leur nombre grandit).
 *
 * Même principe que chip-select.js (2026-09-19), mais pour un choix
 * unique plutôt qu'un nuage de puces : le filtrage se fait entièrement
 * côté client sur les <option> déjà présentes dans le <select> d'origine
 * (pas d'appel réseau — la liste est déjà complète côté serveur, comme
 * pour Intervenant(s)). Le <select> d'origine reste dans le DOM (masqué)
 * et reste la source de vérité : sa valeur change et un évènement
 * `change` est déclenché dessus à chaque sélection, donc le reste du
 * code (ex. post-dialog.js, qui écoute déjà ce `change`) n'a rien à
 * changer.
 *
 * Utilisation : <select data-search-combobox data-search-placeholder="…">
 */
(function () {
  function build(select) {
    if (select.dataset.comboInit) return;
    select.dataset.comboInit = '1';
    select.style.display = 'none';

    var wrap = document.createElement('div');
    wrap.className = 'search-combobox-wrap';

    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'search-combobox-input';
    input.placeholder = select.dataset.searchPlaceholder || 'Rechercher…';
    input.setAttribute('aria-label', input.placeholder);
    input.autocomplete = 'off';
    wrap.appendChild(input);

    var list = document.createElement('div');
    list.className = 'search-combobox-list';
    list.setAttribute('role', 'listbox');
    list.hidden = true;
    wrap.appendChild(list);

    select.insertAdjacentElement('afterend', wrap);

    function options() {
      return Array.prototype.filter.call(select.options, function (o) { return o.value; });
    }

    function labelFor(valeur) {
      var trouve = options().filter(function (o) { return o.value === valeur; })[0];
      return trouve ? trouve.textContent : '';
    }

    function fermer() {
      list.hidden = true;
    }

    function afficher(filtre) {
      list.innerHTML = '';
      var f = (filtre || '').trim().toLowerCase();
      var matches = options().filter(function (o) {
        return !f || o.textContent.toLowerCase().indexOf(f) !== -1;
      });
      if (!matches.length) {
        var vide = document.createElement('div');
        vide.className = 'search-combobox-empty';
        vide.textContent = 'Aucun résultat';
        list.appendChild(vide);
      }
      matches.forEach(function (o) {
        var item = document.createElement('button');
        item.type = 'button';
        item.className = 'search-combobox-item';
        item.setAttribute('role', 'option');
        item.textContent = o.textContent;
        if (o.value === select.value) item.classList.add('is-selected');
        item.addEventListener('click', function () {
          select.value = o.value;
          input.value = o.textContent;
          fermer();
          select.dispatchEvent(new Event('change', { bubbles: true }));
        });
        list.appendChild(item);
      });
      list.hidden = false;
    }

    input.addEventListener('focus', function () {
      // Au premier focus (rien tapé, ou le texte affiché est juste la
      // sélection actuelle) : montrer toute la liste plutôt qu'un filtre
      // déjà réduit à une seule entrée.
      afficher(input.value === labelFor(select.value) ? '' : input.value);
    });
    input.addEventListener('input', function () { afficher(input.value); });
    input.addEventListener('keydown', function (evt) {
      // Entrée dans ce champ ne doit jamais soumettre le formulaire
      // parent (même règle que chip-select.js) — juste garder/fermer.
      if (evt.key === 'Enter') { evt.preventDefault(); fermer(); }
      if (evt.key === 'Escape') { fermer(); input.blur(); }
    });
    document.addEventListener('click', function (evt) {
      if (!wrap.contains(evt.target)) fermer();
    });

    // Texte affiché initial = l'option déjà sélectionnée côté serveur.
    input.value = labelFor(select.value);

    // Si le code applicatif change select.value par programmation (ex.
    // post-dialog.js, quand le projet est imposé par un rebond), garder
    // le texte affiché synchronisé.
    select.addEventListener('change', function () {
      input.value = labelFor(select.value);
    });
  }

  function init() {
    document.querySelectorAll('select[data-search-combobox]').forEach(build);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

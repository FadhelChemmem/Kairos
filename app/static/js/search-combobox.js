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

    var trouves = [];
    var actif = -1;

    function fermer() {
      list.hidden = true;
    }

    function choisir(o) {
      select.value = o.value;
      input.value = o.textContent;
      fermer();
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function surligner() {
      Array.prototype.forEach.call(list.querySelectorAll('.search-combobox-item'), function (el, i) {
        el.classList.toggle('is-active', i === actif);
        if (i === actif) el.scrollIntoView({ block: 'nearest' });
      });
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
      trouves = matches;
      actif = matches.length ? 0 : -1;
      matches.forEach(function (o) {
        var item = document.createElement('button');
        item.type = 'button';
        item.className = 'search-combobox-item';
        item.setAttribute('role', 'option');
        item.textContent = o.textContent;
        if (o.value === select.value) item.classList.add('is-selected');
        item.addEventListener('click', function () { choisir(o); });
        list.appendChild(item);
      });
      list.hidden = false;
      surligner();
    }

    input.addEventListener('focus', function () {
      // Au premier focus (rien tapé, ou le texte affiché est juste la
      // sélection actuelle) : montrer toute la liste plutôt qu'un filtre
      // déjà réduit à une seule entrée.
      afficher(input.value === labelFor(select.value) ? '' : input.value);
    });
    input.addEventListener('input', function () { afficher(input.value); });
    // Clavier (audit du 2026-09-29) : flèches pour parcourir, Entrée pour
    // CHOISIR le résultat surligné (avant, Entrée fermait seulement la
    // liste : le champ affichait « Olivi » mais le post partait sur le
    // projet précédent), Échap pour annuler. Entrée ne soumet jamais le
    // formulaire parent (même règle que chip-select.js).
    input.addEventListener('keydown', function (evt) {
      if (evt.key === 'ArrowDown' || evt.key === 'ArrowUp') {
        evt.preventDefault();
        if (list.hidden) { afficher(input.value === labelFor(select.value) ? '' : input.value); return; }
        if (!trouves.length) return;
        actif = (actif + (evt.key === 'ArrowDown' ? 1 : trouves.length - 1)) % trouves.length;
        surligner();
      } else if (evt.key === 'Enter') {
        evt.preventDefault();
        if (!list.hidden && actif >= 0 && trouves[actif]) choisir(trouves[actif]);
        else { input.value = labelFor(select.value); fermer(); }
      } else if (evt.key === 'Escape') {
        input.value = labelFor(select.value);
        fermer();
        input.blur();
      }
    });
    // Le texte affiché correspond toujours au projet réellement choisi :
    // une saisie abandonnée (clic ailleurs) revient au choix en cours.
    function annulerSaisie() {
      if (input.value !== labelFor(select.value)) input.value = labelFor(select.value);
    }
    document.addEventListener('click', function (evt) {
      if (!wrap.contains(evt.target)) { fermer(); annulerSaisie(); }
    });
    input.addEventListener('blur', function () {
      // Après un éventuel clic dans la liste (traité avant).
      setTimeout(function () { if (list.hidden) annulerSaisie(); }, 150);
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

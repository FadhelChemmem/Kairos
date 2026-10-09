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
 *
 * Lot 11 :
 *   - recherche sans accents ni casse (« helene » trouve « Hélène ») ;
 *   - data-search-riche : chaque résultat montre un avatar (data-photo, à
 *     défaut initiales sur data-couleur, depuis data-prenom/data-nom) et un
 *     sous-titre (data-sous-titre) — sélecteur d'intervenant de la fiche
 *     projet (demande du gérant : « un champ où on appuie et on choisit qui
 *     rajouter ») ;
 *   - data-search-action : le champ sert à DÉCLENCHER une action (ajouter
 *     quelqu'un), pas à garder une valeur : il revient vide après le choix ;
 *   - data-search-vide : texte quand rien ne correspond ;
 *   - window.KairosSearchCombobox.init(racine) pour les contenus insérés
 *     après coup.
 *
 * Lot 13 (audit a11y-perf M11) : data-search-url — les options sont
 * chargées à la demande (GET <url>?q=…, réponse {"resultats": [{id,
 * libelle}]}) au lieu d'être toutes rendues dans la page ; l'option choisie
 * et l'option vide (data-vide) restent toujours dans le <select>.
 */
(function () {
  // Mêmes règles que fn_recherche côté serveur (texte-recherche.js,
  // chargé avant par base.html) ; repli minimal si le fichier manque.
  function sansAccents(s) {
    if (window.KairosTexte) return window.KairosTexte.sansAccents(s);
    return String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  }

  function avatarDe(o) {
    var photo = o.getAttribute('data-photo');
    var el;
    if (photo) {
      el = document.createElement('img');
      el.src = photo;
      el.alt = '';
    } else {
      el = document.createElement('span');
      el.textContent = ((o.getAttribute('data-prenom') || '').charAt(0) + (o.getAttribute('data-nom') || '').charAt(0)).toUpperCase() || '?';
      el.style.background = o.getAttribute('data-couleur') || '';
    }
    el.className = 'avatar avatar-sm search-combobox-avatar';
    el.setAttribute('aria-hidden', 'true');
    return el;
  }

  function build(select) {
    if (select.dataset.comboInit) return;
    select.dataset.comboInit = '1';
    select.style.display = 'none';
    var riche = select.hasAttribute('data-search-riche');
    var modeAction = select.hasAttribute('data-search-action');
    var urlDistante = select.getAttribute('data-search-url');

    var wrap = document.createElement('div');
    wrap.className = 'search-combobox-wrap' + (riche ? ' search-combobox-riche' : '');

    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'search-combobox-input';
    input.placeholder = select.dataset.searchPlaceholder || 'Rechercher…';
    // Nom accessible : le <label for> du <select> d'origine s'il existe
    // (« Projet », « Phase liée »…), sinon le texte d'aide.
    var libelle = select.id && document.querySelector('label[for="' + select.id + '"]');
    if (libelle) {
      if (!libelle.id) libelle.id = select.id + '-libelle';
      input.setAttribute('aria-labelledby', libelle.id);
      libelle.htmlFor = '';
      libelle.addEventListener('click', function () { input.focus(); });
    } else {
      input.setAttribute('aria-label', input.placeholder);
    }
    // Aide sous le champ (lot 11 b : « L'ancien chef devient co-chef »).
    if (select.hasAttribute('aria-describedby')) input.setAttribute('aria-describedby', select.getAttribute('aria-describedby'));
    input.autocomplete = 'off';
    wrap.appendChild(input);

    var list = document.createElement('div');
    list.className = 'search-combobox-list';
    list.setAttribute('role', 'listbox');
    // Lot 13 (audit a11y N1) : liste défilante hors de l'ordre de
    // tabulation — sans cela, Chromium la rend focalisable : Tab depuis le
    // champ ouvert y allait, le blur la fermait et le focus tombait sur
    // <body>. Les options restent pilotées par aria-activedescendant.
    list.tabIndex = -1;
    list.hidden = true;
    wrap.appendChild(list);

    // Lot 10 (audit front I5) : vrai combobox ARIA (rôle, état ouvert,
    // option active annoncée) ; les options ne sont plus des boutons
    // tabulables.
    var listId = 'cbx-' + (select.id || Math.random().toString(36).slice(2));
    list.id = listId;
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-controls', listId);
    input.setAttribute('aria-expanded', 'false');

    // Lot 13 (audit a11y M7) : nombre de résultats annoncé pendant la frappe.
    var statut = document.createElement('span');
    statut.className = 'sr-only';
    statut.setAttribute('role', 'status');
    wrap.appendChild(statut);

    select.insertAdjacentElement('afterend', wrap);

    function options() {
      // Une option vide explicite (data-vide, « — Aucune — ») reste
      // choisissable : c'est le seul moyen de RETIRER une phase liée.
      return Array.prototype.filter.call(select.options, function (o) { return o.value || o.hasAttribute('data-vide'); });
    }

    function labelFor(valeur) {
      // Mode action : le champ revient toujours vide (texte d'aide visible).
      if (modeAction) return '';
      var trouve = options().filter(function (o) { return o.value === valeur; })[0];
      // « — Aucune — » choisi : champ vide (le texte d'aide réapparaît).
      return trouve && !trouve.hasAttribute('data-vide') ? trouve.textContent : '';
    }

    var trouves = [];
    var actif = -1;

    function fermer() {
      list.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
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
        el.setAttribute('aria-selected', i === actif ? 'true' : 'false');
        if (i === actif) { el.scrollIntoView({ block: 'nearest' }); input.setAttribute('aria-activedescendant', el.id); }
      });
    }

    function afficher(filtre) {
      list.innerHTML = '';
      var f = sansAccents((filtre || '').trim());
      var matches = options().filter(function (o) {
        if (!f) return true;
        var texte = sansAccents(o.textContent);
        // « fadhel chem » comme « chem fadhel » : chaque mot doit figurer.
        return f.split(/\s+/).every(function (mot) { return texte.indexOf(mot) !== -1; });
      });
      if (!matches.length) {
        var vide = document.createElement('div');
        vide.className = 'search-combobox-empty';
        vide.textContent = select.getAttribute('data-search-vide') || 'Aucun résultat';
        list.appendChild(vide);
      }
      trouves = matches;
      statut.textContent = !f ? '' : (matches.length
        ? matches.length + ' résultat' + (matches.length > 1 ? 's' : '')
        : (select.getAttribute('data-search-vide') || 'Aucun résultat'));
      // Sans filtre, le choix en cours reste surligné : Entrée juste après
      // le focus ne change rien (avant : le premier projet de la liste était
      // choisi en silence). Avec un filtre, le premier résultat.
      var courant = matches.map(function (o) { return o.value; }).indexOf(select.value);
      actif = f ? (matches.length ? 0 : -1) : courant;
      if (actif < 0) input.removeAttribute('aria-activedescendant');
      matches.forEach(function (o, i) {
        var item = document.createElement('div');
        item.id = listId + '-opt-' + i;
        item.className = 'search-combobox-item';
        item.setAttribute('role', 'option');
        item.setAttribute('aria-selected', 'false');
        if (riche) {
          item.appendChild(avatarDe(o));
          var texte = document.createElement('span');
          texte.className = 'search-combobox-texte';
          var nom = document.createElement('span');
          nom.className = 'search-combobox-nom';
          nom.textContent = o.textContent;
          texte.appendChild(nom);
          var sous = o.getAttribute('data-sous-titre');
          if (sous) {
            var st = document.createElement('span');
            st.className = 'search-combobox-sous';
            st.textContent = sous;
            texte.appendChild(st);
          }
          item.appendChild(texte);
        } else {
          item.textContent = o.textContent;
        }
        if (!modeAction && o.value === select.value) item.classList.add('is-selected');
        item.addEventListener('click', function () { choisir(o); });
        list.appendChild(item);
      });
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      surligner();
    }

    // Options chargées à la demande (data-search-url) : dernière réponse
    // seulement (frappe rapide), puis la liste ouverte est réaffichée.
    var demande = 0, minuteur = null;
    function charger(texte) {
      if (!urlDistante) return;
      clearTimeout(minuteur);
      minuteur = setTimeout(function () {
        var numero = ++demande;
        var adresse = urlDistante + (urlDistante.indexOf('?') === -1 ? '?' : '&') + 'q=' + encodeURIComponent(texte.trim());
        fetch(adresse, { headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (corps) {
            if (!corps || numero !== demande) return;
            Array.prototype.slice.call(select.options).forEach(function (o) {
              if (o.value && !o.hasAttribute('data-vide') && o.value !== select.value) select.removeChild(o);
            });
            (corps.resultats || []).forEach(function (r) {
              var valeur = String(r.id);
              if (valeur === select.value) return;
              var o = document.createElement('option');
              o.value = valeur;
              o.textContent = r.libelle;
              select.appendChild(o);
            });
            if (!list.hidden && document.activeElement === input) {
              afficher(input.value === labelFor(select.value) ? '' : input.value);
            }
          })
          .catch(function () { /* hors ligne : la liste actuelle reste */ });
      }, texte ? 200 : 0);
    }

    input.addEventListener('focus', function () {
      if (urlDistante) charger(input.value === labelFor(select.value) ? '' : input.value);
      // Focus rendu par le code après une action (data-sans-ouverture) :
      // la liste reste fermée (flèche ↓ ou clic pour l'ouvrir).
      if (input.dataset.sansOuverture) { delete input.dataset.sansOuverture; return; }
      // Au premier focus (rien tapé, ou le texte affiché est juste la
      // sélection actuelle) : montrer toute la liste plutôt qu'un filtre
      // déjà réduit à une seule entrée.
      afficher(input.value === labelFor(select.value) ? '' : input.value);
    });
    // Clic dans le champ déjà actif (liste refermée après un choix) : la
    // rouvrir, comme au focus.
    input.addEventListener('click', function () {
      if (list.hidden) afficher(input.value === labelFor(select.value) ? '' : input.value);
    });
    input.addEventListener('input', function () {
      afficher(input.value);
      charger(input.value);
      // Champ vidé : Entrée choisit « — Aucune — » (retirer la phase liée).
      if (!input.value.trim()) {
        for (var i = 0; i < trouves.length; i++) {
          if (trouves[i].hasAttribute('data-vide')) { actif = i; surligner(); break; }
        }
      }
    });
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
        else { annulerSaisie(); fermer(); }
      } else if (evt.key === 'Escape') {
        // Lot 10 (audit front I5/M17) : Échap referme la liste ou annule la
        // saisie SANS fermer la fenêtre parente, et le focus reste dans le
        // champ (il partait sur <body>). Champ déjà au repos : Échap
        // remonte normalement (fermeture de la fenêtre).
        if (!list.hidden || input.value !== labelFor(select.value)) {
          evt.preventDefault();
          evt.stopPropagation();
        }
        input.value = labelFor(select.value);
        fermer();
      }
    });
    // Le texte affiché correspond toujours au projet réellement choisi :
    // une saisie abandonnée (clic ailleurs) revient au choix en cours.
    function annulerSaisie() {
      if (input.value !== labelFor(select.value)) input.value = labelFor(select.value);
    }
    // Une seule écoute du document pour tous les champs (lot 13 : les
    // champs remplacés par un fragment partiel ne laissent rien derrière).
    wrap._fermerSiDehors = function (cibleClic) {
      if (!wrap.contains(cibleClic)) { fermer(); annulerSaisie(); }
    };
    // Un clic dans la liste (résultat, barre de défilement) ne fait pas
    // perdre le focus au champ : quitter le champ (Tab, clic ailleurs) veut
    // donc toujours dire « abandonner la saisie » — liste fermée, texte
    // ramené au choix en cours (avant, un Tab laissait la liste ouverte et
    // « Olivi » affiché alors que l'ancien projet restait choisi).
    list.addEventListener('mousedown', function (evt) { evt.preventDefault(); });
    input.addEventListener('blur', function () {
      fermer();
      annulerSaisie();
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

  function init(racine) {
    (racine && racine.querySelectorAll ? racine : document).querySelectorAll('select[data-search-combobox]').forEach(build);
  }
  window.KairosSearchCombobox = { init: init };
  document.addEventListener('click', function (evt) {
    document.querySelectorAll('.search-combobox-wrap').forEach(function (w) { if (w._fermerSiDehors) w._fermerSiDehors(evt.target); });
  });
  document.addEventListener('kairos:fragment', function (e) { init(e.detail && e.detail.racine); });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(); });
  } else {
    init();
  }
})();

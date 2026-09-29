/* Sélecteur à puces réutilisable — remplace visuellement un <select
 * multiple> par un nuage de puces cliquables, façon LinkedIn/Facebook
 * (retour Fadhel, 2026-09-19). Le <select multiple> d'origine reste dans
 * le DOM (juste masqué) et reste la source de vérité soumise avec le
 * formulaire : aucun changement côté serveur n'est nécessaire pour
 * bénéficier du nouveau visuel sur un formulaire existant.
 *
 * Utilisation : <select multiple data-chip-select> ... </select>
 * Options :
 *   data-chip-filter="1"   -> ajoute un champ texte pour filtrer les puces
 *                             (utile pour de longues listes, ex. Intervenant(s))
 *   data-chip-recent="1"   -> (avec data-chip-filter) tant que la recherche
 *                             est vide, n'affiche que les options marquées
 *                             data-recent="1" et celles déjà choisies ; la
 *                             recherche porte sur toutes (8 résultats au
 *                             plus) — retour Fadhel, 2026-09-29, N4 :
 *                             "~5 personnes récentes + une recherche", pour
 *                             que la fenêtre ne s'allonge pas avec l'équipe.
 *   data-chip-autosubmit="1" -> soumet le formulaire à chaque bascule
 *                                (utilisé pour les filtres de liste)
 *   data-chip-avatar="1"   -> puces rondes (avatar + initiales, ou photo)
 *                             au lieu de puces texte avec le nom complet —
 *                             utilisé pour "Chef de projet" (retour Fadhel,
 *                             2026-09-27 : la liste des noms complets
 *                             prenait toute la largeur du filtre). Chaque
 *                             <option> doit porter data-prenom/data-nom
 *                             (initiales + tooltip/aria-label) et
 *                             data-couleur ou data-photo (avatar_color(u.id)
 *                             ou l'URL de la photo de profil, voir
 *                             projets_liste.html). Le nom complet reste
 *                             consultable au survol (title natif du
 *                             navigateur) et est exposé aux lecteurs d'écran
 *                             (aria-label) puisque le contenu visible de la
 *                             puce n'est que la photo ou deux initiales.
 */
(function () {
  function buildChipSelect(select) {
    if (select.dataset.chipInit) return;
    select.dataset.chipInit = '1';
    select.style.display = 'none';

    var wrap = document.createElement('div');
    wrap.className = 'chip-select-wrap';

    var filterInput = null;
    if (select.dataset.chipFilter) {
      filterInput = document.createElement('input');
      filterInput.type = 'text';
      filterInput.className = 'chip-select-filter';
      filterInput.placeholder = select.dataset.chipFilterPlaceholder || 'Rechercher…';
      filterInput.setAttribute('aria-label', filterInput.placeholder);
      // Entrée dans ce champ de filtre soumettait le formulaire parent
      // (ex. publier une tâche avant d'avoir choisi un intervenant) —
      // audit n°2.
      filterInput.addEventListener('keydown', function (evt) {
        if (evt.key === 'Enter') evt.preventDefault();
      });
      wrap.appendChild(filterInput);
    }

    var cloud = document.createElement('div');
    cloud.className = 'chip-cloud';
    cloud.setAttribute('role', 'group');
    var libelle = select.id && document.querySelector('label[for="' + select.id + '"]');
    if (libelle) cloud.setAttribute('aria-label', libelle.textContent.trim());
    wrap.appendChild(cloud);

    var avatarMode = !!select.dataset.chipAvatar;

    var chips = [];
    Array.prototype.forEach.call(select.options, function (opt) {
      // Vrai bouton (et non <span>) : atteignable au clavier (Tab) et
      // activable par Entrée/Espace, état annoncé par aria-pressed (audit
      // n°2 — les puces n'étaient utilisables qu'à la souris).
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'chip-opt' + (avatarMode ? ' chip-avatar' : '') + (opt.selected ? ' chip-selected' : '');
      chip.setAttribute('aria-pressed', opt.selected ? 'true' : 'false');
      chip.dataset.label = opt.textContent.trim().toLowerCase();
      if (opt.title) chip.title = opt.title;
      chip._opt = opt;

      if (avatarMode) {
        var nomComplet = (opt.dataset.prenom + ' ' + opt.dataset.nom).trim();
        chip.title = nomComplet;
        chip.setAttribute('aria-label', nomComplet);
        if (opt.dataset.photo) {
          var img = document.createElement('img');
          img.src = opt.dataset.photo;
          img.alt = '';
          chip.appendChild(img);
        } else {
          var initiales = document.createElement('span');
          initiales.textContent = ((opt.dataset.prenom || '').charAt(0) + (opt.dataset.nom || '').charAt(0)).toUpperCase();
          chip.style.background = opt.dataset.couleur || '';
          chip.appendChild(initiales);
        }
      } else {
        var label = document.createElement('span');
        label.textContent = opt.textContent;
        chip.appendChild(label);
      }

      // Retour Fadhel (2026-09-27) : plus de croix "×" sur les puces
      // sélectionnées — la sélection se voit uniquement par la
      // surbrillance (.chip-selected), comme c'est déjà le cas ailleurs
      // dans l'appli. On re-clique une puce sélectionnée pour la retirer.
      chip.addEventListener('click', function () {
        opt.selected = !opt.selected;
        chip.classList.toggle('chip-selected', opt.selected);
        chip.setAttribute('aria-pressed', opt.selected ? 'true' : 'false');
        select.dispatchEvent(new Event('change', { bubbles: true }));
        if (select.dataset.chipAutosubmit && select.form) {
          select.form.submit();
        }
        if (filterInput && filterInput.value) {
          // Personne choisie depuis la recherche : on vide la recherche,
          // elle reste visible parmi les puces (choisies).
          filterInput.value = '';
          filtrer();
        }
      });

      cloud.appendChild(chip);
      chips.push(chip);
    });

    var modeRecent = !!(filterInput && select.dataset.chipRecent);
    var MAX_RESULTATS = 8;

    function filtrer() {
      var q = filterInput.value.trim().toLowerCase();
      var montres = 0;
      chips.forEach(function (chip) {
        var visible;
        if (!modeRecent) {
          visible = q.length === 0 || chip.dataset.label.indexOf(q) !== -1;
        } else if (q.length === 0) {
          visible = chip._opt.selected || chip._opt.dataset.recent === '1';
        } else {
          visible = chip._opt.selected ||
            (chip.dataset.label.indexOf(q) !== -1 && montres < MAX_RESULTATS);
          if (visible && !chip._opt.selected) montres++;
        }
        chip.classList.toggle('chip-hidden', !visible);
      });
    }

    if (filterInput) {
      filterInput.addEventListener('input', filtrer);
      if (modeRecent) filtrer();
    }

    // Sélection changée par le code (bouton "Toutes les équipes",
    // réinitialisation du formulaire…) : les puces suivent le <select>.
    select.addEventListener('change', function () {
      chips.forEach(function (chip) {
        chip.classList.toggle('chip-selected', chip._opt.selected);
        chip.setAttribute('aria-pressed', chip._opt.selected ? 'true' : 'false');
      });
      if (modeRecent) filtrer();
    });

    select.parentNode.insertBefore(wrap, select.nextSibling);
  }

  function init() {
    document.querySelectorAll('select[data-chip-select]').forEach(buildChipSelect);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

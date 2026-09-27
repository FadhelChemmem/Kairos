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
 *   data-chip-autosubmit="1" -> soumet le formulaire à chaque bascule
 *                                (utilisé pour les filtres de liste)
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

    var chips = [];
    Array.prototype.forEach.call(select.options, function (opt) {
      // Vrai bouton (et non <span>) : atteignable au clavier (Tab) et
      // activable par Entrée/Espace, état annoncé par aria-pressed (audit
      // n°2 — les puces n'étaient utilisables qu'à la souris).
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'chip-opt' + (opt.selected ? ' chip-selected' : '');
      chip.setAttribute('aria-pressed', opt.selected ? 'true' : 'false');
      chip.dataset.label = opt.textContent.trim().toLowerCase();

      var label = document.createElement('span');
      label.textContent = opt.textContent;
      chip.appendChild(label);

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
      });

      cloud.appendChild(chip);
      chips.push(chip);
    });

    if (filterInput) {
      filterInput.addEventListener('input', function () {
        var q = filterInput.value.trim().toLowerCase();
        chips.forEach(function (chip) {
          chip.classList.toggle('chip-hidden', q.length > 0 && chip.dataset.label.indexOf(q) === -1);
        });
      });
    }

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

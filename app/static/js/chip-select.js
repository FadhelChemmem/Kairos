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
      wrap.appendChild(filterInput);
    }

    var cloud = document.createElement('div');
    cloud.className = 'chip-cloud';
    wrap.appendChild(cloud);

    var chips = [];
    Array.prototype.forEach.call(select.options, function (opt) {
      var chip = document.createElement('span');
      chip.className = 'chip-opt' + (opt.selected ? ' chip-selected' : '');
      chip.dataset.label = opt.textContent.trim().toLowerCase();

      var label = document.createElement('span');
      label.textContent = opt.textContent;
      chip.appendChild(label);

      var remove = document.createElement('span');
      remove.className = 'chip-remove';
      remove.textContent = '×';
      remove.style.display = opt.selected ? 'inline-flex' : 'none';
      chip.appendChild(remove);

      chip.addEventListener('click', function () {
        opt.selected = !opt.selected;
        chip.classList.toggle('chip-selected', opt.selected);
        remove.style.display = opt.selected ? 'inline-flex' : 'none';
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

// Raccourcis clavier (lot 13, audit UX §4.6).
//   Ctrl/⌘ + K, ou « / »   recherche globale (plein écran sur téléphone)
//   ?                      aide des raccourcis
//   g puis a/p/d/l/n       Accueil / Projets / Deadlines / Daily log / Notifications
//   n                      nouveau post (accueil, fiche projet)
//   j / k                  ligne suivante / précédente (tâches, projets, utilisateurs)
//   Ctrl/⌘ + Entrée        envoie le formulaire en cours (fenêtre ouverte)
//   Ctrl/⌘ + Z             « Annuler » du dernier toast (kairos-partiel.js)
// WCAG 2.1.4 : les raccourcis d'une seule touche sont inactifs dans les
// champs de saisie et désactivables (préférence de ce navigateur, case de
// l'aide « ? » et de « Mes informations ») ; Ctrl/⌘ + K reste toujours actif.
(function () {
  var CLE = 'kairos-raccourcis';
  var LIENS_G = { a: 'accueil', p: 'projets', d: 'deadlines', l: 'dailylog', n: 'notifications' };
  // Lignes de « Tous les projets » : div[role=row] depuis le lot 13 (lien
  // sur le nom seulement) — audit a11y N3.
  var LIGNES = '.taskrow[data-open-tache], .ptable-row, .urow';
  var attenteG = 0;

  function actifs() {
    try { return localStorage.getItem(CLE) !== 'non'; } catch (e) { return true; }
  }
  function definir(oui) {
    try { localStorage.setItem(CLE, oui ? 'oui' : 'non'); } catch (e) { /* préférence non mémorisée */ }
    document.querySelectorAll('[data-pref-raccourcis]').forEach(function (c) { c.checked = oui; });
  }

  function dansUnChamp(el) {
    if (!el || el === document.body) return false;
    if (el.isContentEditable) return true;
    var t = el.tagName;
    if (t === 'TEXTAREA' || t === 'SELECT') return true;
    if (t === 'INPUT') return !/^(button|submit|reset|checkbox|radio|range|color|file)$/i.test(el.type);
    return false;
  }

  function visible(el) { return !!el && el.offsetParent !== null && !el.disabled; }

  function lignes() {
    return Array.prototype.filter.call(document.querySelectorAll(LIGNES), function (r) { return r.offsetParent !== null; });
  }
  function focusLigne(r) {
    var cible = r.matches('a, button') ? r : r.querySelector('[data-ouvrir-tache], a[href], button:not([disabled]), [tabindex="0"]');
    if (!cible) { r.setAttribute('tabindex', '-1'); cible = r; }
    cible.focus();
    if (cible.scrollIntoView) cible.scrollIntoView({ block: 'nearest' });
  }
  function deplacer(sens) {
    var liste = lignes();
    if (!liste.length) return false;
    var courante = document.activeElement && document.activeElement.closest ? document.activeElement.closest(LIGNES) : null;
    var i = liste.indexOf(courante);
    var suivante = i === -1 ? (sens > 0 ? 0 : liste.length - 1) : Math.min(liste.length - 1, Math.max(0, i + sens));
    focusLigne(liste[suivante]);
    return true;
  }

  var aide = null;
  function ouvrirAide() {
    if (!aide) {
      aide = document.createElement('dialog');
      aide.className = 'post-dialog k-aide-raccourcis';
      aide.setAttribute('aria-labelledby', 'k-aide-titre');
      aide.innerHTML = '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:6px;">'
        + '<h2 id="k-aide-titre" class="carte-titre" style="font-size:16px;">Raccourcis clavier</h2>'
        + '<button type="button" class="dialog-fermer" data-k-fermer aria-label="Fermer"><svg aria-hidden="true" focusable="false" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></button></div>'
        + '<table><tbody>'
        + '<tr><th colspan="2">Partout</th></tr>'
        + '<tr><td><kbd>Ctrl</kbd> + <kbd>K</kbd> ou <kbd>/</kbd></td><td>Rechercher un projet, une tâche, une personne</td></tr>'
        + '<tr><td><kbd>g</kbd> puis <kbd>a</kbd> <kbd>p</kbd> <kbd>d</kbd> <kbd>l</kbd> <kbd>n</kbd></td><td>Accueil, Projets, Deadlines, Daily log, Notifications</td></tr>'
        + '<tr><td><kbd>?</kbd></td><td>Cette aide</td></tr>'
        + '<tr><th colspan="2">Dans une page</th></tr>'
        + '<tr><td><kbd>n</kbd></td><td>Nouveau post (accueil, fiche projet)</td></tr>'
        + '<tr><td><kbd>j</kbd> / <kbd>k</kbd></td><td>Ligne suivante / précédente (tâches, projets, utilisateurs), puis <kbd>Entrée</kbd></td></tr>'
        + '<tr><td><kbd>Échap</kbd></td><td>Fermer la fenêtre ou la liste ouverte</td></tr>'
        + '<tr><td><kbd>Ctrl</kbd> + <kbd>Entrée</kbd></td><td>Envoyer le formulaire de la fenêtre</td></tr>'
        + '<tr><td><kbd>Ctrl</kbd> + <kbd>Z</kbd></td><td>«\u00a0Annuler\u00a0» du dernier message (10 s, hors d’un champ de saisie)</td></tr>'
        + '</tbody></table>'
        + '<label class="k-option"><input type="checkbox" data-pref-raccourcis> Raccourcis d’une seule touche (désactivables\u00a0: lecteur d’écran, commande vocale)</label>';
      document.body.appendChild(aide);
      aide.querySelector('[data-k-fermer]').addEventListener('click', function () { aide.close(); });
      aide.addEventListener('click', function (e) { if (e.target === aide) aide.close(); });
    }
    aide.querySelector('[data-pref-raccourcis]').checked = actifs();
    if (!aide.open) aide.showModal();
  }

  document.addEventListener('change', function (e) {
    if (e.target && e.target.hasAttribute && e.target.hasAttribute('data-pref-raccourcis')) definir(e.target.checked);
  });
  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('[data-aide-raccourcis]')) { e.preventDefault(); ouvrirAide(); }
  });
  document.querySelectorAll('[data-pref-raccourcis]').forEach(function (c) { c.checked = actifs(); });

  document.addEventListener('keydown', function (e) {
    if (e.defaultPrevented || e.isComposing) return;
    var mod = e.ctrlKey || e.metaKey;
    // Ctrl/⌘ + K : toujours.
    if (mod && !e.altKey && (e.key === 'k' || e.key === 'K')) {
      if (window.Kairos && window.Kairos.ouvrirRecherche) { e.preventDefault(); window.Kairos.ouvrirRecherche(); }
      return;
    }
    // Ctrl/⌘ + Entrée : envoie le formulaire en cours (dans une fenêtre ouverte).
    if (mod && e.key === 'Enter') {
      var el = document.activeElement;
      var form = el && el.form ? el.form : (el && el.closest ? el.closest('form') : null);
      if (form && form.closest('dialog[open]') && form.requestSubmit) { e.preventDefault(); form.requestSubmit(); }
      return;
    }
    if (mod || e.altKey || !actifs() || dansUnChamp(e.target) || document.querySelector('dialog[open]')) return;
    var touche = e.key;
    if (attenteG && Date.now() - attenteG < 1000) {
      attenteG = 0;
      var lien = LIENS_G[touche] && document.querySelector('[data-raccourci-g="' + touche + '"]');
      if (lien) { e.preventDefault(); lien.click(); }
      return;
    }
    attenteG = 0;
    if (touche === 'g') { attenteG = Date.now(); return; }
    if (touche === '/') {
      if (window.Kairos && window.Kairos.ouvrirRecherche) { e.preventDefault(); window.Kairos.ouvrirRecherche(); }
    } else if (touche === '?') {
      e.preventDefault();
      ouvrirAide();
    } else if (touche === 'n') {
      var b = Array.prototype.filter.call(document.querySelectorAll('[data-raccourci-n]'), visible)[0];
      if (b) { e.preventDefault(); b.click(); }
    } else if (touche === 'j' || touche === 'k') {
      if (deplacer(touche === 'j' ? 1 : -1)) e.preventDefault();
    }
  });

  window.Kairos = window.Kairos || {};
  window.Kairos.aideRaccourcis = ouvrirAide;
})();

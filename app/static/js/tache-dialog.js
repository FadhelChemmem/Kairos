// Fenêtre d'une tâche (retour Fadhel, 2026-09-29) : un clic sur la ligne
// d'une tâche (page projet) ouvre sa fenêtre flottante — titre modifiable,
// état, clôture, pièces jointes. Fermeture : X, Échap, ou clic à
// l'extérieur tant que rien n'a été modifié (floating-window.js).
//
// Lot 11 (audit front I2) : UNE seule <dialog id="dialog-tache"> dans la
// page, remplie à l'ouverture par le fragment HTML de la tâche
// (GET /projets/<id>/taches/<tid>/fenetre, partials/tache_fenetre.html).
// État « Chargement… » pendant la requête, message et bouton d'action en
// cas d'échec, focus sur le premier champ une fois chargé, et retour du
// focus au titre de la tâche à la fermeture (comme avant). Le fragment est
// préchargé au survol d'une ligne (souris) pour une ouverture immédiate.
(function () {
  var dialog = document.getElementById('dialog-tache');
  if (!dialog) return;
  var corps = dialog.querySelector('[data-tache-corps]');
  var modeleUrl = dialog.getAttribute('data-url');
  var FW = window.KairosFloatingWindow;
  var DUREE_PRECHARGE = 20000;
  var precharges = {};   // id -> { promesse, t }
  var seq = 0;
  var declencheur = null;

  function urlTache(id) {
    return modeleUrl.replace(/\/taches\/0\/fenetre$/, '/taches/' + encodeURIComponent(id) + '/fenetre');
  }

  function charger(id) {
    return fetch(urlTache(id), { credentials: 'same-origin', headers: { 'Accept': 'text/html' } })
      .then(function (r) {
        // Session expirée : la redirection vers /connexion est suivie et
        // renvoie la page de connexion — jamais notre fragment.
        if (r.ok && r.headers.get('X-Kairos-Fragment') === 'tache') return r.text();
        var e = new Error('http');
        e.code = r.ok ? 'session' : r.status;
        throw e;
      });
  }

  function obtenir(id) {
    var p = precharges[id];
    delete precharges[id];
    if (p && Date.now() - p.t < DUREE_PRECHARGE) return p.promesse;
    return charger(id);
  }

  function precharger(id) {
    var p = precharges[id];
    if (p && Date.now() - p.t < DUREE_PRECHARGE) return;
    var promesse = charger(id);
    promesse.catch(function () { delete precharges[id]; });
    precharges[id] = { promesse: promesse, t: Date.now() };
  }

  function etatChargement() {
    dialog.setAttribute('aria-busy', 'true');
    corps.innerHTML = '';
    var p = document.createElement('p');
    p.className = 'tache-dialog-chargement';
    p.setAttribute('role', 'status');
    var roue = document.createElement('span');
    roue.className = 'roue-chargement';
    roue.setAttribute('aria-hidden', 'true');
    p.appendChild(roue);
    p.appendChild(document.createTextNode('Chargement de la tâche…'));
    corps.appendChild(p);
  }

  function etatErreur(id, err) {
    dialog.removeAttribute('aria-busy');
    corps.innerHTML = '';
    var bloc = document.createElement('div');
    bloc.className = 'tache-dialog-erreur';
    bloc.setAttribute('role', 'alert');
    var msg = document.createElement('p');
    var bouton = document.createElement('button');
    bouton.type = 'button';
    bouton.className = 'btn-secondary';
    if (err && (err.code === 'session' || err.code === 404)) {
      msg.textContent = err.code === 'session'
        ? 'Votre session a expiré : rechargez la page pour vous reconnecter.'
        : 'Tâche introuvable : elle a peut-être été supprimée, ou vous n’y avez plus accès. Rechargez la page.';
      bouton.textContent = 'Recharger la page';
      bouton.addEventListener('click', function () { window.location.reload(); });
    } else {
      msg.textContent = 'Impossible de charger la tâche. Vérifiez la connexion, puis réessayez.';
      bouton.textContent = 'Réessayer';
      bouton.addEventListener('click', function () { afficher(id); });
    }
    bloc.appendChild(msg);
    bloc.appendChild(bouton);
    corps.appendChild(bloc);
    bouton.focus();
  }

  function afficher(id) {
    var n = ++seq;
    etatChargement();
    obtenir(id).then(function (html) {
      if (n !== seq || !dialog.open) return;
      corps.innerHTML = html;
      dialog.removeAttribute('aria-busy');
      var racine = corps.querySelector('[data-tache-fenetre]');
      if (racine) dialog.setAttribute('aria-label', 'Tâche « ' + racine.getAttribute('data-titre') + ' »');
      // État de référence pour « fermer sans enregistrer ? » : celui du
      // contenu chargé, pas de la fenêtre vide.
      if (FW) FW.memoriser(dialog);
      // Lot 10 : focus sur le premier champ (titre, état…) plutôt que
      // « Fermer » — sauf si l'utilisateur a déjà déplacé le focus.
      var actif = document.activeElement;
      if (!actif || actif === document.body || actif === dialog || corps.contains(actif) || actif.hasAttribute('data-close-tache')) {
        if (!(FW && FW.focusPremierChamp(corps))) {
          // Fenêtre en lecture seule : focus sur son titre.
          var titre = corps.querySelector('.tache-fenetre-titre');
          if (titre) { titre.setAttribute('tabindex', '-1'); titre.focus(); }
        }
      }
    }, function (err) {
      if (n !== seq || !dialog.open) return;
      etatErreur(id, err);
    });
  }

  function ouvrir(ligne) {
    if (dialog.open) return;
    var id = ligne.getAttribute('data-open-tache');
    declencheur = ligne.querySelector('[data-ouvrir-tache]');
    var titre = declencheur ? declencheur.textContent.trim() : '';
    dialog.setAttribute('aria-label', titre ? 'Tâche « ' + titre + ' »' : 'Tâche');
    etatChargement();
    if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', 'open');
    afficher(id);
  }

  if (FW) FW.attacherFermetureAuFond(dialog);
  dialog.querySelectorAll('[data-close-tache]').forEach(function (b) {
    b.addEventListener('click', function () { dialog.close(); });
  });
  dialog.addEventListener('close', function () {
    seq++;   // une réponse arrivée après la fermeture est ignorée
    corps.innerHTML = '';
    dialog.removeAttribute('aria-busy');
    // Retour du focus au titre de la tâche (ouverture à la souris par un
    // clic sur la ligne : le focus était sur <body>).
    if (declencheur && document.contains(declencheur)) declencheur.focus();
    declencheur = null;
  });

  // Lot 10 (audit front I8) : le titre de la tâche est un vrai bouton
  // (clavier : Tab, Entrée, Espace) ; le reste de la ligne reste un
  // raccourci souris. Les contrôles de la ligne (« rejoindre cette
  // tâche »…) gardent leur propre action. Délégation : une seule écoute
  // pour toutes les lignes (ouvertes et closes repliées).
  document.addEventListener('click', function (e) {
    var ligne = e.target.closest('[data-open-tache]');
    if (!ligne) return;
    if (!e.target.closest('[data-ouvrir-tache]') && e.target.closest('form, button, a, input, select')) return;
    ouvrir(ligne);
  });

  // Lot 11 b : tâche demandée dans l'adresse — ?tache=<id> (résultat
  // « tâche » de la recherche globale, notification d'affectation : le
  // serveur l'a vérifiée et l'indique dans data-ouvrir-au-chargement) ou
  // #tache-<id>. Ligne repliée parmi les tâches closes : dépliée. Fenêtre
  // ouverte comme par un clic sur le titre (focus dans la fenêtre, rendu au
  // titre de la ligne à la fermeture). À la fermeture, l'adresse redevient
  // celle de la fiche : un rechargement ne rouvre pas la tâche.
  function nettoyerAdresse() {
    try {
      var u = new URL(window.location.href);
      u.searchParams.delete('tache');
      if (/^#tache-\d+$/.test(u.hash)) u.hash = '';
      window.history.replaceState(window.history.state, '', u.pathname + u.search + u.hash);
    } catch (e) { /* adresse laissée telle quelle */ }
  }
  function ouvrirDemandee(id) {
    var ligne = id && document.querySelector('[data-open-tache="' + id + '"]');
    if (!ligne || dialog.open) return;
    var repli = ligne.closest('details');
    if (repli && !repli.open) repli.open = true;
    if (ligne.scrollIntoView) ligne.scrollIntoView({ block: 'center' });
    dialog.addEventListener('close', nettoyerAdresse, { once: true });
    ouvrir(ligne);
  }
  function idAncre() {
    var m = /^#tache-(\d+)$/.exec(window.location.hash);
    return m ? m[1] : null;
  }
  ouvrirDemandee(dialog.getAttribute('data-ouvrir-au-chargement') || idAncre());
  // Lien #tache-<id> suivi dans la page même (pas de rechargement).
  window.addEventListener('hashchange', function () { ouvrirDemandee(idAncre()); });

  // Préchargement au survol (souris seulement, après 120 ms).
  var minuteur = null;
  document.addEventListener('pointerover', function (e) {
    if (e.pointerType !== 'mouse') return;
    var ligne = e.target.closest && e.target.closest('[data-open-tache]');
    if (!ligne || ligne.contains(e.relatedTarget)) return;
    clearTimeout(minuteur);
    minuteur = setTimeout(function () { precharger(ligne.getAttribute('data-open-tache')); }, 120);
  });
  document.addEventListener('pointerout', function (e) {
    var ligne = e.target.closest && e.target.closest('[data-open-tache]');
    if (ligne && !ligne.contains(e.relatedTarget)) clearTimeout(minuteur);
  });
})();

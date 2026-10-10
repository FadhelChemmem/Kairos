// Bouton ✓ de validation des posts (retour Fadhel, 2026-09-28 : « Le bouton
// (V) ne rafraîchit pas toute la page »).
//
// Le formulaire reste un <form method="post"> normal (partials/post_card.html) :
// sans JavaScript, il se soumet comme avant (retour à la page via « next »).
//
// Lot 13 (audit UX §2.2, M4, M5, I9) : réaction OPTIMISTE — compteur, état
// pressé et petite animation « pop » tout de suite (t = 0) ; le serveur
// répond en JSON {nb, ma_reaction, reacteurs} (plus de rendu de toute la
// page suivi d'une redirection) : le compteur et l'infobulle des personnes
// qui ont réagi prennent les valeurs réelles. Refus (lecture seule « Voir
// comme », projet clos…) : retour à l'état d'avant et toast ; session
// expirée : fenêtre « Se reconnecter » ; réseau : retour arrière et toast.
// Correctif du lot 13 (verif-ux N7) : erreur réseau ou serveur (5xx) → le
// toast propose « Réessayer », comme les autres actions.
(function () {
  function reessayer(form) {
    return { libelle: 'Réessayer', surClic: function () {
      if (!document.contains(form)) return;
      if (form.requestSubmit) form.requestSubmit();
      else form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    } };
  }
  function appliquer(form, btn, actif, nb, reacteurs) {
    var compteur = btn.querySelector('.post-reaction-count');
    if (compteur) compteur.textContent = Math.max(0, nb);
    btn.setAttribute('aria-pressed', actif ? 'true' : 'false');
    btn.classList.toggle('est-presse', actif);
    if (reacteurs !== undefined) {
      if (reacteurs) btn.title = reacteurs.indexOf('Vu par') === 0 ? reacteurs : 'Vu par\u00a0: ' + reacteurs; else btn.removeAttribute('title');
    }
    // Prochain clic : l'action opposée.
    form.action = actif ? form.dataset.retirerUrl : form.dataset.reagirUrl;
    var champ = form.querySelector('input[name="reaction_code"]');
    if (actif && champ) champ.remove();
    if (!actif && !champ) {
      champ = document.createElement('input');
      champ.type = 'hidden';
      champ.name = 'reaction_code';
      champ.value = 'pouce';
      form.appendChild(champ);
    }
  }

  document.addEventListener('submit', function (e) {
    var form = e.target;
    // Déjà traité (lecture seule « Voir comme » : kairos-partiel.js).
    if (e.defaultPrevented || !form.classList || !form.classList.contains('post-reaction-form')) return;
    e.preventDefault();
    var btn = form.querySelector('button[type="submit"]');
    // Une requête à la fois (lot 10, audit front I3), sans désactiver le
    // bouton (un bouton désactivé perd le focus clavier).
    if (!btn || btn.disabled || form.dataset.enCours) return;
    form.dataset.enCours = '1';
    var K = window.Kairos;
    var compteur = btn.querySelector('.post-reaction-count');
    var avant = {
      actif: btn.getAttribute('aria-pressed') === 'true',
      nb: parseInt(compteur ? compteur.textContent : '0', 10) || 0,
      titre: btn.getAttribute('title'),
      action: form.action
    };
    var corps = new FormData(form);
    // État optimiste immédiat, avec l'animation « pop ».
    appliquer(form, btn, !avant.actif, avant.nb + (avant.actif ? -1 : 1));
    btn.classList.remove('k-pop');
    void btn.offsetWidth;
    btn.classList.add('k-pop');
    btn.setAttribute('aria-disabled', 'true');

    function revenir() {
      appliquer(form, btn, avant.actif, avant.nb, avant.titre || '');
      form.action = avant.action;
    }
    function fin() {
      delete form.dataset.enCours;
      btn.removeAttribute('aria-disabled');
    }

    fetch(avant.action, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-Kairos-Partiel': '#' + (form.closest('.post-card') || {}).id, 'Accept': 'application/json' },
      body: corps
    }).then(function (r) {
      return r.text().then(function (t) { return { r: r, t: t }; });
    }).then(function (res) {
      fin();
      if (res.r.status === 401) {
        revenir();
        if (K) K.sessionExpiree(res.r.headers.get('X-Kairos-Connexion'));
        return;
      }
      var donnees = null;
      try { donnees = JSON.parse(res.t); } catch (x) { donnees = null; }
      if (!res.r.ok || !donnees || donnees.erreur) {
        revenir();
        if (K) K.toast(K.messageErreur(res.r.status, res.t), { type: 'erreur', action: res.r.status >= 500 ? reessayer(form) : null });
        return;
      }
      appliquer(form, btn, !!donnees.ma_reaction, donnees.nb, donnees.reacteurs || '');
    }).catch(function () {
      fin();
      revenir();
      if (K) K.toast('Connexion au serveur impossible\u00a0: la validation n’a pas été enregistrée.', { type: 'erreur', action: reessayer(form) });
    });
  });
})();

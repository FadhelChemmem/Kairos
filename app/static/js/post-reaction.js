// Bouton "(V)" de validation sur les cartes de poste (icône coche) — retour
// Fadhel, 2026-09-28 : "Le bouton (V) ne rafraichi pas toute la page mais
// seulement la section pour ne pas remonter en haut."
//
// Le formulaire reste un <form method="post"> tout à fait normal (voir
// partials/post_card.html) : sans JavaScript, ou si le fetch échoue, il se
// soumet comme avant (rechargement complet, via le paramètre "next").
// Avec JavaScript, on intercepte l'envoi, on l'exécute en arrière-plan, et
// on met à jour seulement ce bouton (état pressé, compteur, couleur) sans
// jamais quitter/recharger la page.
(function () {
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.classList || !form.classList.contains('post-reaction-form')) return;
    e.preventDefault();

    var btn = form.querySelector('button[type="submit"]');
    // Lot 10 (audit front I3) : un double-clic envoyait deux requêtes et
    // le compteur passait de 1 à 3. Une seule requête à la fois — sans
    // désactiver le bouton (un bouton désactivé perd le focus clavier).
    if (!btn || btn.disabled || form.dataset.enCours) return;
    form.dataset.enCours = '1';
    btn.setAttribute('aria-busy', 'true');
    var countEl = btn.querySelector('.post-reaction-count');
    var activeAvant = btn.getAttribute('aria-pressed') === 'true';

    fetch(form.action, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body: new FormData(form),
    }).then(function (resp) {
      // Le serveur répond par une redirection vers la page (« next ») : c'est
      // le succès normal. Mais une session expirée redirige vers la
      // connexion — ce n'est pas un succès (lot 10, audit front I3).
      var versConnexion = resp.redirected && /^\/connexion\/?$/.test(new URL(resp.url).pathname);
      if (!resp.ok || versConnexion) throw new Error('Échec de la validation du post.');

      var count = parseInt(countEl.textContent, 10) || 0;
      var actifApres = !activeAvant;

      countEl.textContent = Math.max(0, count + (actifApres ? 1 : -1));
      btn.setAttribute('aria-pressed', actifApres ? 'true' : 'false');
      btn.classList.toggle('est-presse', actifApres);

      // Prochain clic : basculer vers l'action opposée, sans re-render serveur.
      form.action = actifApres ? form.dataset.retirerUrl : form.dataset.reagirUrl;
      var champReaction = form.querySelector('input[name="reaction_code"]');
      if (actifApres) {
        if (!champReaction) {
          champReaction = document.createElement('input');
          champReaction.type = 'hidden';
          champReaction.name = 'reaction_code';
          form.appendChild(champReaction);
        }
        champReaction.value = 'pouce';
      } else if (champReaction) {
        champReaction.remove();
      }
      delete form.dataset.enCours;
      btn.removeAttribute('aria-busy');
    }).catch(function () {
      // Filet de sécurité : en cas d'échec réseau, on retombe sur le
      // comportement d'origine (soumission normale du formulaire).
      HTMLFormElement.prototype.submit.call(form);
    });
  });
})();

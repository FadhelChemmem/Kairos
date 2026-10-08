// Ajout d'un intervenant depuis la fiche projet (lot 11, demande du
// gérant) : choisir une personne dans le champ de recherche
// (search-combobox.js, data-search-action) l'ajoute aussitôt — POST vers
// projets.ajouter_intervenant (jeton CSRF du formulaire), puis la carte
// « Intervenants » est remplacée par celle de la page renvoyée, sans
// recharger : la personne apparaît dans la liste et disparaît des choix.
// Le message du serveur (« Intervenant ajouté. », erreur…) est annoncé
// sous le champ, et le focus revient dans le champ pour enchaîner.
// Repli : si la réponse n'est pas exploitable, la page est rechargée (la
// demande est déjà partie) ; si la requête n'a pas pu partir, envoi
// classique du formulaire.
(function () {
  function texteFlash(doc) {
    var modeles = doc.getElementById('flash-modeles');
    if (!modeles) return null;
    var flash = modeles.content.querySelector('.flash');
    if (!flash) return null;
    return {
      texte: (flash.querySelector('.flash-texte') || flash).textContent.trim(),
      erreur: flash.classList.contains('flash-error')
    };
  }

  function brancher(carte) {
    var form = carte.querySelector('form[data-ajout-intervenant]');
    if (!form) return;
    var select = form.querySelector('select[name="utilisateur_id"]');
    var statut = form.querySelector('[data-ajout-statut]');
    var envoi = false;

    select.addEventListener('change', function () {
      if (!select.value || envoi) return;
      var option = select.options[select.selectedIndex];
      var nom = option ? option.textContent.trim() : '';
      envoi = true;
      var champ = form.querySelector('.search-combobox-input');
      if (champ) champ.disabled = true;
      statut.classList.remove('is-erreur');
      statut.textContent = 'Ajout de ' + nom + '…';
      var donnees = new FormData(form);
      var repondu = false;
      select.value = '';

      fetch(form.action, { method: 'POST', body: donnees, credentials: 'same-origin' })
        .then(function (r) {
          repondu = true;
          return r.text().then(function (html) { return { r: r, html: html }; });
        })
        .then(function (res) {
          var doc = new DOMParser().parseFromString(res.html, 'text/html');
          var nouvelle = doc.getElementById('carte-intervenants');
          if (!res.r.ok || !nouvelle) { window.location.reload(); return; }
          var message = texteFlash(doc);
          carte.replaceWith(nouvelle);
          if (window.KairosSearchCombobox) window.KairosSearchCombobox.init(nouvelle);
          brancher(nouvelle);
          var st = nouvelle.querySelector('[data-ajout-statut]') || nouvelle.querySelector('.ajout-intervenant-statut');
          if (st && message) {
            st.textContent = message.texte;
            st.classList.toggle('is-erreur', message.erreur);
            if (message.erreur) st.setAttribute('role', 'alert');
          }
          var nouveauChamp = nouvelle.querySelector('.search-combobox-input');
          // Focus rendu au champ (sans rouvrir la liste) pour enchaîner un
          // autre ajout ; à défaut, au titre de la carte.
          if (nouveauChamp) {
            nouveauChamp.dataset.sansOuverture = '1';
            nouveauChamp.focus();
          } else {
            var titre = nouvelle.querySelector('.carte-titre');
            if (titre) { titre.setAttribute('tabindex', '-1'); titre.focus(); }
          }
        })
        .catch(function () {
          // Réponse reçue mais inexploitable : la demande est partie, on
          // recharge. Requête jamais partie (réseau) : envoi classique.
          if (repondu) { window.location.reload(); return; }
          envoi = false;
          select.value = option ? option.value : '';
          form.submit();
        });
    });
  }

  function init() {
    var carte = document.getElementById('carte-intervenants');
    if (carte) brancher(carte);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();

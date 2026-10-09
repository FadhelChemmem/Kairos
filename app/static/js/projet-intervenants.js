// Ajout d'un intervenant depuis la fiche projet (lot 11, demande du
// gérant) : choisir une personne dans le champ de recherche
// (search-combobox.js, data-search-action) l'ajoute aussitôt.
//
// Lot 13 (phase 2) : envoi au socle partiel (kairos-partiel.js) — la carte
// « Intervenants » seule est remplacée par le fragment du serveur (plus de
// lecture de la page entière ni de rechargement de secours) ; le message
// part en toast ; un refus (droits, compte invalide…) laisse la carte telle
// quelle avec un toast d'erreur. Le focus revient dans le champ, liste
// fermée, pour enchaîner un autre ajout. Sans JavaScript : liste + bouton.
(function () {
  document.addEventListener('change', function (e) {
    var select = e.target;
    var form = select && select.form;
    if (!form || !form.hasAttribute('data-ajout-intervenant') || select.name !== 'utilisateur_id' || !select.value) return;
    var K = window.Kairos;
    if (!K || !K.requete) { form.submit(); return; }
    if (K.lectureSeule && K.lectureSeule()) { K.toast(K.MESSAGE_LECTURE_SEULE, { type: 'info' }); return; }
    if (form.dataset.envoi) return;
    form.dataset.envoi = '1';
    var option = select.options[select.selectedIndex];
    var nom = option ? option.textContent.trim() : '';
    var statut = form.querySelector('[data-ajout-statut]');
    if (statut) { statut.classList.remove('is-erreur'); statut.textContent = 'Ajout de ' + nom + '…'; }
    var champ = form.querySelector('.search-combobox-input');
    var corps = new FormData(form);
    select.value = '';
    K.requete({
      url: form.action, methode: 'POST', corps: corps, cible: '#carte-intervenants',
      historique: 'aucun', declencheur: champ || form
    }).then(function (res) {
      delete form.dataset.envoi;
      if (statut && document.contains(statut)) statut.textContent = '';
      var carte = document.getElementById('carte-intervenants');
      var nouveau = carte && carte.querySelector('.search-combobox-input');
      // Focus rendu au champ (sans rouvrir la liste) ; à défaut, au titre
      // de la carte (plus personne à ajouter).
      if (nouveau) { nouveau.dataset.sansOuverture = '1'; nouveau.focus(); }
      else if (res && res.racine) {
        var titre = carte && carte.querySelector('[data-partiel-titre]');
        if (titre) titre.focus();
      }
    });
  });
})();

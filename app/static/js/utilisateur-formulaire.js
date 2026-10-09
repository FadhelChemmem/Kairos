// Formulaires d'un compte : création, fiche, « Mes informations » (lot 13 :
// remplace champs-perso.js ; délégation au document, les formulaires sont
// remplacés en place après Enregistrer).
//  - lignes « Champs personnalisés » : nom / valeur, lus côté serveur comme
//    champs_perso (routes/utilisateurs.py : champ_perso_nom / champ_perso_valeur) ;
//  - photo de profil : aperçu immédiat de l'image choisie, avant l'envoi.
(function () {
  document.addEventListener('click', function (e) {
    var ajouter = e.target.closest && e.target.closest('#cf-add');
    if (ajouter) {
      var liste = document.getElementById('cf-list');
      if (!liste) return;
      var row = document.createElement('div');
      row.className = 'cf-row k-entree';
      row.innerHTML =
        '<input type="text" name="champ_perso_nom" aria-label="Nom du champ" placeholder="Nom du champ (ex. Taille T-shirt)">' +
        '<input type="text" name="champ_perso_valeur" aria-label="Valeur" placeholder="Valeur">' +
        '<button type="button" class="linkbtn cf-remove" aria-label="Retirer ce champ"><svg aria-hidden="true" focusable="false" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button>';
      liste.appendChild(row);
      row.querySelector('input').focus();
      return;
    }
    var retirer = e.target.closest && e.target.closest('#cf-list .cf-remove');
    if (retirer) {
      var ligne = retirer.closest('.cf-row');
      var suivant = ligne.nextElementSibling ? ligne.nextElementSibling.querySelector('input') : document.getElementById('cf-add');
      ligne.remove();
      if (suivant) suivant.focus();
    }
  });

  document.addEventListener('change', function (e) {
    var champ = e.target;
    if (!champ || !champ.matches || !champ.matches('input[type=file][data-apercu-avatar]')) return;
    var apercu = document.getElementById(champ.getAttribute('data-apercu-avatar'));
    if (!apercu) return;
    if (apercu._url) { URL.revokeObjectURL(apercu._url); apercu._url = null; }
    var f = champ.files && champ.files[0];
    if (!f || !/^image\//.test(f.type)) { apercu.hidden = true; apercu.removeAttribute('src'); return; }
    apercu._url = URL.createObjectURL(f);
    apercu.src = apercu._url;
    apercu.hidden = false;
  });
})();

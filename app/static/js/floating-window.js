// Règle commune à TOUTES les fenêtres flottantes de l'appli (retour
// Fadhel, 2026-09-28 : "On fait ça sur toutes les fenêtres flottantes.") —
// un clic à l'extérieur ne doit PAS fermer la fenêtre si elle contient du
// texte saisi par l'utilisateur (on perdrait la saisie) : il faut alors
// passer par le bouton de fermeture explicite (X / Annuler). Si elle est
// vide, le clic extérieur ferme normalement, comme avant.
//
// Utilisé par post-dialog.js aujourd'hui (la fenêtre "Nouveau post"), et
// à réutiliser par toute future fenêtre flottante du même genre (édition
// "Informations" du projet, "Nouveau projet"…) plutôt que de réécrire
// cette règle à chaque fois.
window.KairosFloatingWindow = (function () {
  // Compte comme "contenu" : un champ texte ou une zone de texte non vide
  // (hors champs désactivés), ou un fichier choisi dans un champ file.
  // Volontairement PAS les champs date/select/case à cocher/puces — préremplir
  // l'échéance à aujourd'hui (voir post_dialog.html) ne doit pas, à lui
  // seul, bloquer la fermeture d'une fenêtre par ailleurs vide.
  function aDuContenu(container) {
    var champsTexte = container.querySelectorAll(
      'input[type="text"]:not([disabled]), input[type="url"]:not([disabled]), ' +
      'input[type="email"]:not([disabled]), input[type="tel"]:not([disabled]), ' +
      'textarea:not([disabled])'
    );
    for (var i = 0; i < champsTexte.length; i++) {
      if (champsTexte[i].value.trim() !== '') return true;
    }
    var champsFichier = container.querySelectorAll('input[type="file"]');
    for (var j = 0; j < champsFichier.length; j++) {
      if (champsFichier[j].files && champsFichier[j].files.length > 0) return true;
    }
    return false;
  }

  // Ferme `dialogEl` (un <dialog> natif) au clic sur son propre fond
  // (backdrop) — sauf si elle contient du texte saisi, auquel cas seul un
  // bouton de fermeture explicite marche. Le clic sur le backdrop d'un
  // <dialog> se détecte via `e.target === dialogEl` (le contenu réel est
  // toujours dans un élément enfant, jamais le <dialog> lui-même).
  function attacherFermetureAuFond(dialogEl) {
    dialogEl.addEventListener('click', function (e) {
      if (e.target !== dialogEl) return;
      if (aDuContenu(dialogEl)) return;
      dialogEl.close();
    });
  }

  return { aDuContenu: aDuContenu, attacherFermetureAuFond: attacherFermetureAuFond };
})();

// Page « Nouveau projet » (lot 13 : sorti du <script> en ligne de
// projet_creer.html). PROMPT_CORRECTIONS.md P2 #22 : le code proposé est
// recalculé côté serveur (projets.api_code_propose, adresse dans
// data-url-code-propose) à chaque changement de phase ou de phase liée,
// sauf si l'utilisateur a déjà modifié le champ (data-modifie="1" : code
// déjà saisi, renvoi après erreur). Seule la réponse à la DERNIÈRE demande
// est appliquée (audit n°2).
(function () {
  var champCode = document.getElementById('code');
  var champPhase = document.getElementById('phase');
  if (!champCode || !champPhase) return;
  var urlCodePropose = champCode.getAttribute('data-url-code-propose');
  var modifieManuellement = champCode.getAttribute('data-modifie') === '1';
  var derniereDemande = 0;
  champCode.addEventListener('input', function () { modifieManuellement = true; });
  var champLie = document.getElementById('phase_liee_id');
  // Lot 21 (test Chrome) : client repris de la phase liée, tant que le
  // champ n'a pas été modifié à la main.
  var champClient = document.getElementById('client');
  var clientModifie = false;
  if (champClient) champClient.addEventListener('input', function () { clientModifie = true; });
  function recalculer(e) {
    var reprendreClient = !!(e && e.target === champLie && champClient && !clientModifie && champLie.value);
    if ((modifieManuellement && !reprendreClient) || !urlCodePropose) return;
    var numero = ++derniereDemande;
    fetch(urlCodePropose + '?phase=' + encodeURIComponent(champPhase.value)
          + (champLie && champLie.value ? '&phase_liee_id=' + encodeURIComponent(champLie.value) : ''))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (numero !== derniereDemande) return;
        if (reprendreClient && data.client && !clientModifie) champClient.value = data.client;
        if (!modifieManuellement && data.code) champCode.value = data.code;
      })
      .catch(function () { /* le code affiché reste une proposition valable */ });
  }
  champPhase.addEventListener('change', recalculer);
  if (champLie) champLie.addEventListener('change', recalculer);
})();

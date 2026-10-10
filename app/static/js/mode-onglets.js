/* Lot 13 (audit temps T-I3) : plusieurs onglets, un seul mode.
 *
 * La date simulée et « Voir / Agir comme » vivent dans la session (cookie),
 * partagée par tous les onglets. Chaque page porte l'empreinte du mode
 * qu'elle affiche (<meta name="kairos-mode">, app/modes_admin.py) ; ce
 * script la renvoie avec chaque écriture :
 *   - fetch() vers l'appli (POST, PUT, PATCH, DELETE) : en-tête X-Kairos-Mode ;
 *     réponse 409 marquée X-Kairos-Mode-Change → la page se recharge ;
 *   - formulaires POST (submit classique, form.submit(), FormData) : champ
 *     caché _mode, ajouté à l'envoi (évènement formdata) ;
 *   - BroadcastChannel('kairos-mode') : chaque page annonce son empreinte ;
 *     un onglet qui affiche un autre mode se recharge — tout de suite s'il
 *     est visible, sinon quand on y revient (pas de rafale de rechargements
 *     en arrière-plan) ; une page issue d'un envoi de formulaire (POST) ne
 *     se recharge pas (le navigateur renverrait le formulaire) : retour à la
 *     page précédente.
 * Saisie non envoyée (contre-expertise temps R1) : un champ modifié d'un
 * formulaire POST (commentaire, post…) ou une saisie signalée par
 * KairosModes.surveiller(fn) (Daily log) empêche le rechargement : une
 * barre « Le mode a changé dans un autre onglet — Recharger » le propose.
 * Le serveur refuse une écriture dont l'empreinte n'est pas celle de la
 * session (409 / message « Le mode a changé dans un autre onglet ») ; après
 * un rechargement dû à ce refus, le message est affiché (sessionStorage,
 * contre-expertise temps N2).
 */
(function () {
  var meta = document.querySelector('meta[name="kairos-mode"]');
  var empreinte = meta ? meta.getAttribute('content') : '';
  if (!empreinte) return;

  function memeOrigine(adresse) {
    try { return new URL(adresse, window.location.href).origin === window.location.origin; } catch (e) { return false; }
  }

  var CLE_MESSAGE = 'kairos-mode-message';
  var MESSAGE_REFUS = 'Le mode a changé dans un autre onglet — page rechargée\u00a0: rien n’a été enregistré. '
    + 'Vérifiez le compte et la date affichés, puis recommencez.';
  var surveillants = [];
  window.KairosModes = {
    /** fn() -> true tant qu'une saisie n'est pas envoyée (ex. Daily log).
     *  Renvoie la fonction qui retire ce surveillant (page remplacée). */
    surveiller: function (fn) {
      if (typeof fn !== 'function') return function () {};
      surveillants.push(fn);
      return function () {
        var i = surveillants.indexOf(fn);
        if (i >= 0) surveillants.splice(i, 1);
      };
    },
    saisieEnCours: saisieEnCours
  };

  function champModifie(el) {
    var type = (el.type || '').toLowerCase();
    // Sans nom : champ d'interface (recherche d'un sélecteur), jamais envoyé.
    if (!el.name || el.disabled || el.readOnly || ['hidden', 'submit', 'button', 'reset', 'image'].indexOf(type) >= 0) return false;
    if (type === 'file') return !!(el.files && el.files.length);
    if (type === 'checkbox' || type === 'radio') return el.checked !== el.defaultChecked;
    if (el.tagName === 'SELECT') {
      if (el.multiple) return Array.prototype.some.call(el.options, function (o) { return o.selected !== o.defaultSelected; });
      var defaut = Array.prototype.findIndex.call(el.options, function (o) { return o.defaultSelected; });
      return el.options.length > 0 && el.selectedIndex !== Math.max(defaut, 0);
    }
    return el.value !== el.defaultValue;
  }
  function saisieEnCours() {
    if (surveillants.some(function (fn) { try { return !!fn(); } catch (e) { return false; } })) return true;
    return Array.prototype.some.call(document.querySelectorAll('form input, form textarea, form select'), function (el) {
      var form = el.form;
      if (!form || (form.getAttribute('method') || 'get').toLowerCase() !== 'post') return false;
      if (el.closest('[data-saisie-ignorer]')) return false;
      return champModifie(el);
    });
  }

  var methodePage = (meta.getAttribute('data-methode') || 'GET').toUpperCase();
  var recharge = false;
  function rechargerMaintenant() {
    if (recharge) return;
    recharge = true;
    if (methodePage === 'GET') { window.location.reload(); return; }
    var retour = document.referrer && memeOrigine(document.referrer) ? document.referrer : '/';
    window.location.replace(retour);
  }
  var STYLE_BARRE = 'display:flex;gap:12px;align-items:center;flex-wrap:wrap;box-sizing:border-box;'
    + 'padding:10px 14px;border-radius:10px;background:var(--warn-bg,#fdf3ec);color:var(--warn-text,#8a5a1e);'
    + 'border:1px solid var(--warn-border,#f3ddc6);box-shadow:0 6px 24px rgba(0,0,0,.18);font-size:13.5px;z-index:10000;';
  function fenetreModale() {
    var ouvertes = document.querySelectorAll('dialog[open]');
    for (var i = ouvertes.length - 1; i >= 0; i--) {
      try { if (ouvertes[i].matches(':modal')) return ouvertes[i]; } catch (e) { return ouvertes[i]; }
    }
    return null;
  }
  // Une fenêtre modale ouverte rend le reste de la page inerte : la barre va
  // alors dans la fenêtre (en tête), et revient dans la page à sa fermeture.
  function placerBarre(barre) {
    var modale = fenetreModale();
    if (modale) {
      barre.style.cssText = STYLE_BARRE + 'position:sticky;top:0;margin:0 0 10px;';
      if (barre.parentNode !== modale) modale.insertBefore(barre, modale.firstChild);
      if (!modale._kairosBarre) {
        modale._kairosBarre = true;
        modale.addEventListener('close', function () { if (barre.parentNode === modale) placerBarre(barre); });
      }
      return;
    }
    barre.style.cssText = STYLE_BARRE + 'position:fixed;left:50%;top:12px;transform:translateX(-50%);max-width:calc(100vw - 32px);';
    if (barre.parentNode !== document.body) document.body.appendChild(barre);
  }
  function proposerRechargement(refus) {
    var barre = document.getElementById('kairos-mode-change');
    if (!barre) {
      barre = document.createElement('div');
      barre.id = 'kairos-mode-change';
      barre.setAttribute('role', 'alert');
      var span = document.createElement('span');
      span.className = 'kairos-mode-change-texte';
      var bouton = document.createElement('button');
      bouton.type = 'button';
      bouton.className = 'btn-primaire';
      bouton.textContent = 'Recharger';
      bouton.style.width = 'auto';
      bouton.addEventListener('click', rechargerMaintenant);
      barre.appendChild(span);
      barre.appendChild(bouton);
    }
    placerBarre(barre);
    barre.querySelector('.kairos-mode-change-texte').textContent = refus
      ? 'Le mode a changé dans un autre onglet\u00a0: rien n’a été enregistré. Votre saisie reste affichée (copiez-la si besoin).'
      : 'Le mode a changé dans un autre onglet. Votre saisie reste affichée tant que vous ne rechargez pas.';
  }
  function recharger(message) {
    var agir = function () {
      if (saisieEnCours()) { proposerRechargement(!!message); return; }
      if (message) { try { window.sessionStorage.setItem(CLE_MESSAGE, message); } catch (e) { /* stockage indisponible */ } }
      rechargerMaintenant();
    };
    if (document.visibilityState !== 'hidden') { agir(); return; }
    document.addEventListener('visibilitychange', function attendre() {
      if (document.visibilityState === 'hidden') return;
      document.removeEventListener('visibilitychange', attendre);
      agir();
    });
  }

  function afficherMessageMemorise() {
    var message = null;
    try {
      message = window.sessionStorage.getItem(CLE_MESSAGE);
      window.sessionStorage.removeItem(CLE_MESSAGE);
    } catch (e) { return; }
    if (!message) return;
    var montrer = function () {
      if (window.Kairos && typeof window.Kairos.toast === 'function') window.Kairos.toast(message, { type: 'erreur' });
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(montrer, 200); });
    else setTimeout(montrer, 200);
  }
  afficherMessageMemorise();

  var fetchAvant = window.fetch;
  if (fetchAvant) {
    window.fetch = function (ressource, options) {
      options = options || {};
      var methode = (options.method || (ressource && ressource.method) || 'GET').toUpperCase();
      var adresse = ressource instanceof Request ? ressource.url : String(ressource);
      if (['GET', 'HEAD', 'OPTIONS'].indexOf(methode) === -1 && memeOrigine(adresse)) {
        var entetes = new Headers(options.headers || (ressource && ressource.headers) || {});
        if (!entetes.has('X-Kairos-Mode')) entetes.set('X-Kairos-Mode', empreinte);
        options = Object.assign({}, options, { headers: entetes });
      }
      return fetchAvant.call(this, ressource, options).then(function (reponse) {
        if (reponse.status === 409 && reponse.headers.get('X-Kairos-Mode-Change')) {
          reponse.clone().json().then(function (corps) { recharger((corps && corps.message) || MESSAGE_REFUS); },
            function () { recharger(MESSAGE_REFUS); });
        }
        return reponse;
      });
    };
  }

  document.addEventListener('formdata', function (e) {
    var form = e.target;
    if (!form || (form.method || '').toLowerCase() !== 'post') return;
    if (!memeOrigine(form.action || window.location.href)) return;
    if (!e.formData.has('_mode')) e.formData.append('_mode', empreinte);
  });

  if (typeof BroadcastChannel === 'function') {
    var canal = new BroadcastChannel('kairos-mode');
    canal.onmessage = function (e) {
      var autre = e.data && e.data.empreinte;
      if (autre && autre !== empreinte) recharger();
    };
    canal.postMessage({ empreinte: empreinte });
  }
})();

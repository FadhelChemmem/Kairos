// Application installable et notifications Windows (lot 24).
//  - enregistre le service worker (/sw.js) sur toutes les pages (HTTPS) ;
//  - « Installer Kairos sur ce PC » quand le navigateur le propose ;
//  - « Mes informations » : activer / désactiver les notifications sur ce
//    PC, notification d'essai (routes de app/routes/push.py) ;
//  - /notifications?ouvrir=<id> (clic sur une notification Windows) : la
//    notification est ouverte par son formulaire POST habituel.
(function () {
  'use strict';
  var K = window.Kairos;
  var sw = 'serviceWorker' in navigator && window.isSecureContext;

  function toast(texte, type) {
    if (K && K.toast) K.toast(texte, { type: type || 'succes' });
  }
  // Lot 25 (PU-09) : une réponse qui n'est pas du JSON (session expirée :
  // page de connexion après redirection) est une erreur, jamais un succès.
  function json(url, corps) {
    return fetch(url, { method: corps === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      headers: corps === undefined ? {} : { 'Content-Type': 'application/json' },
      body: corps === undefined ? undefined : JSON.stringify(corps) })
      .then(function (r) {
        var typeJson = (r.headers.get('Content-Type') || '').indexOf('application/json') !== -1;
        if (!typeJson || r.redirected) {
          return { _statut: 401, erreur: 'session', message: 'Session expirée\u00a0: rechargez la page.' };
        }
        return r.json().catch(function () { return {}; }).then(function (d) { d._statut = r.status; return d; });
      });
  }
  function memeCle(sub, cleTexte) {
    // PU-12 : abonnement fait avec une autre clé du serveur → à refaire.
    try {
      var a = new Uint8Array(sub.options.applicationServerKey || new ArrayBuffer(0));
      var b = cleBinaire(cleTexte);
      if (a.length !== b.length) return false;
      for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
      return true;
    } catch (e) { return true; }
  }
  function cleBinaire(b64) {
    var s = (b64 + '='.repeat((4 - b64.length % 4) % 4)).replace(/-/g, '+').replace(/_/g, '/');
    var brut = window.atob(s);
    var out = new Uint8Array(brut.length);
    for (var i = 0; i < brut.length; i++) out[i] = brut.charCodeAt(i);
    return out;
  }

  // --- Service worker ------------------------------------------------------
  var inscription = sw && window.fetch
    ? navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function () { return null; })
    : Promise.resolve(null);

  // --- Installer (Chrome / Edge) ------------------------------------------
  var invite = null;
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    invite = e;
    document.querySelectorAll('[data-push-installer]').forEach(function (b) { b.hidden = false; });
  });
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-push-installer]');
    if (!b || !invite) return;
    invite.prompt();
    invite.userChoice.then(function () { invite = null; b.hidden = true; });
  });

  // --- Ouverture d'une notification cliquée dans Windows --------------------
  var auto = document.querySelector('form[data-auto-envoi]');
  if (auto) auto.submit();

  // --- Mes informations ------------------------------------------------------
  var zone = document.querySelector('[data-push]');
  if (!zone) return;
  var etat = zone.querySelector('[data-push-etat]');
  var bActiver = zone.querySelector('[data-push-activer]');
  var bDesactiver = zone.querySelector('[data-push-desactiver]');
  var bEssai = zone.querySelector('[data-push-essai]');
  var modeAdmin = zone.hasAttribute('data-push-mode-admin');
  var cle = null;

  var categories = document.getElementById('push-categories');
  function afficher(texte, actif) {
    etat.textContent = texte;
    bActiver.hidden = actif !== false;
    bDesactiver.hidden = actif !== true;
    bEssai.hidden = actif !== true;
    [bActiver, bDesactiver, bEssai].forEach(function (b) { b.disabled = modeAdmin; });
    // Lot 25 (U4) : les catégories n'ont de sens que si ce navigateur peut
    // recevoir les notifications.
    if (categories) categories.hidden = actif === null;
  }
  // Lot 25 (U2) : après « Activer » / « Désactiver », le focus va sur le
  // bouton qui reste affiché (plus de retour en haut de la page).
  function garderFocus() {
    var cible = [bEssai, bActiver, bDesactiver].filter(function (b) { return !b.hidden; })[0];
    if (cible) cible.focus();
  }
  function abonnement() {
    return inscription.then(function (reg) { return reg ? reg.pushManager.getSubscription() : null; });
  }
  function rafraichir() {
    if (!window.isSecureContext) {
      // Lot 25 (U1) : en http, ni service worker ni notifications.
      afficher('Les notifications Windows exigent une adresse sécurisée (https://)\u00a0: ouvrez Kairos par son adresse en https.', null);
      return Promise.resolve();
    }
    if (!sw || !('PushManager' in window) || !('Notification' in window)) {
      afficher('Ce navigateur ne peut pas afficher les notifications de Kairos (utilisez Chrome ou Edge).', null);
      return Promise.resolve();
    }
    return json(zone.getAttribute('data-push-cle')).then(function (d) {
      cle = d.cle || null;
      if (!cle) { afficher('Les notifications Windows ne sont pas encore configurées sur le serveur.', null); return; }
      if (Notification.permission === 'denied') {
        afficher('Notifications bloquées pour Kairos dans ce navigateur\u00a0: autorisez-les (cadenas à gauche de l’adresse), puis rechargez la page.', null);
        return;
      }
      return abonnement().then(function (sub) {
        if (!sub) { afficher('Désactivées sur ce PC.', false); return; }
        return json(zone.getAttribute('data-push-etat-url'), { endpoint: sub.endpoint }).then(function (r) {
          afficher(r.abonne ? 'Activées sur ce PC\u00a0: vous recevez vos notifications Kairos dans Windows.' : 'Désactivées sur ce PC.', !!r.abonne);
        });
      });
    }).catch(function () { afficher('État des notifications indisponible (réseau).', null); });
  }

  bActiver.addEventListener('click', function () {
    if (modeAdmin || !cle) return;
    bActiver.disabled = true;
    Notification.requestPermission().then(function (p) {
      if (p !== 'granted') throw new Error('refus');
      return inscription.then(function (reg) {
        if (!reg) throw new Error('sw');
        return reg.pushManager.getSubscription().then(function (ancien) {
          if (ancien && memeCle(ancien, cle)) return ancien;
          var defaire = ancien ? ancien.unsubscribe().catch(function () {}) : Promise.resolve();
          return defaire.then(function () {
            return reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: cleBinaire(cle) });
          });
        });
      });
    }).then(function (sub) {
      return json(zone.getAttribute('data-push-abonner'), sub.toJSON());
    }).then(function (r) {
      toast(r.message || 'Notifications activées sur ce PC.', r._statut < 300 ? 'succes' : 'erreur');
    }).catch(function (e) {
      toast(e && e.message === 'refus' ? 'Notifications refusées dans ce navigateur.' : 'Activation impossible sur ce PC.', 'erreur');
    }).then(rafraichir).then(garderFocus);
  });
  bDesactiver.addEventListener('click', function () {
    if (modeAdmin) return;
    bDesactiver.disabled = true;
    abonnement().then(function (sub) {
      if (!sub) return null;
      var endpoint = sub.endpoint;
      return sub.unsubscribe().catch(function () {}).then(function () {
        return json(zone.getAttribute('data-push-desabonner'), { endpoint: endpoint });
      });
    }).then(function (r) { toast((r && r.message) || 'Notifications désactivées sur ce PC.', r && r._statut >= 300 ? 'erreur' : 'succes'); })
      .catch(function () { toast('Désactivation impossible.', 'erreur'); })
      .then(rafraichir).then(garderFocus);
  });
  bEssai.addEventListener('click', function () {
    if (modeAdmin) return;
    json(zone.getAttribute('data-push-essai-url'), {}).then(function (r) {
      toast(r.message || 'Notification d’essai envoyée.', r._statut < 300 ? 'succes' : 'erreur');
    }).catch(function () { toast('Envoi impossible (réseau).', 'erreur'); });
  });
  rafraichir();
})();

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
  function json(url, corps) {
    return fetch(url, { method: corps === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      headers: corps === undefined ? {} : { 'Content-Type': 'application/json' },
      body: corps === undefined ? undefined : JSON.stringify(corps) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { d._statut = r.status; return d; }); });
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

  function afficher(texte, actif) {
    etat.textContent = texte;
    bActiver.hidden = actif !== false;
    bDesactiver.hidden = actif !== true;
    bEssai.hidden = actif !== true;
    [bActiver, bDesactiver, bEssai].forEach(function (b) { b.disabled = modeAdmin; });
  }
  function abonnement() {
    return inscription.then(function (reg) { return reg ? reg.pushManager.getSubscription() : null; });
  }
  function rafraichir() {
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
          return ancien || reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: cleBinaire(cle) });
        });
      });
    }).then(function (sub) {
      return json(zone.getAttribute('data-push-abonner'), sub.toJSON());
    }).then(function (r) {
      toast(r.message || 'Notifications activées sur ce PC.', r._statut < 300 ? 'succes' : 'erreur');
    }).catch(function (e) {
      toast(e && e.message === 'refus' ? 'Notifications refusées dans ce navigateur.' : 'Activation impossible sur ce PC.', 'erreur');
    }).then(rafraichir);
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
    }).then(function (r) { toast((r && r.message) || 'Notifications désactivées sur ce PC.'); })
      .catch(function () { toast('Désactivation impossible.', 'erreur'); })
      .then(rafraichir);
  });
  bEssai.addEventListener('click', function () {
    if (modeAdmin) return;
    json(zone.getAttribute('data-push-essai-url'), {}).then(function (r) {
      toast(r.message || 'Notification d’essai envoyée.', r._statut < 300 ? 'succes' : 'erreur');
    }).catch(function () { toast('Envoi impossible (réseau).', 'erreur'); });
  });
  rafraichir();
})();

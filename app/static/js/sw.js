/* Service worker de Kairos (lot 24, notifications Windows).
 *
 * Servi à la racine (/sw.js, portée « / ») par app/routes/push.py.
 * - push : affiche la notification reçue (titre, texte, icône Kairos) et
 *   met à jour la pastille de l'icône de l'appli (nombre de non-lues) ;
 * - clic : ouvre la notification dans un nouvel onglet ou une nouvelle
 *   fenêtre (lot 25) : la page déjà ouverte n'est jamais remplacée.
 * Aucun cache hors ligne : les pages de Kairos sont des données vivantes.
 */
'use strict';

self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (e) { e.waitUntil(self.clients.claim()); });

function pastille() {
  if (!self.navigator || !self.navigator.setAppBadge) return Promise.resolve();
  return fetch('/notifications/compte', { credentials: 'same-origin', cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      if (!d || typeof d.non_lues !== 'number') return;
      return d.non_lues > 0 ? self.navigator.setAppBadge(d.non_lues) : self.navigator.clearAppBadge();
    })
    .catch(function () { /* pastille inchangée */ });
}

self.addEventListener('push', function (e) {
  var d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = {}; }
  var titre = typeof d.titre === 'string' && d.titre ? d.titre : 'Kairos';
  var url = typeof d.url === 'string' && d.url.charAt(0) === '/' && d.url.charAt(1) !== '/' ? d.url : '/notifications';
  e.waitUntil(Promise.all([
    self.registration.showNotification(titre, {
      body: typeof d.texte === 'string' ? d.texte : '',
      icon: '/static/img/icone-192.png',
      badge: '/static/img/icone-maskable-192.png',
      tag: d.id ? 'kairos-' + d.id : undefined,
      lang: 'fr',
      data: { url: url }
    }),
    pastille()
  ]));
});

self.addEventListener('notificationclick', function (e) {
  // Lot 25 (décision du gérant du 23/10, U3) : toujours un NOUVEL onglet
  // (ou une nouvelle fenêtre de l'appli installée) — la page Kairos déjà
  // ouverte (saisie du Daily log, post en cours d'écriture) n'est jamais
  // remplacée.
  e.notification.close();
  var url = (e.notification.data && e.notification.data.url) || '/notifications';
  e.waitUntil(self.clients.openWindow(url));
});

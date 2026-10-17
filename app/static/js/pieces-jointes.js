// Pièces jointes d'un post (lot 17, demande du gérant du 17/10/2026) :
// on colle (Ctrl+V) une capture ou un fichier copié dans l'Explorateur
// dans le texte, on le glisse dessus, ou on clique « Joindre » (téléphone,
// clavier). Les fichiers s'affichent en puces sous le champ (miniature,
// nom, taille, ×) et partent avec le formulaire : le champ
// <input type=file name=fichier multiple> est tenu à jour par DataTransfer.
// Copie depuis Excel ou Word (texte + image du rendu) : le texte est collé,
// rien n'est joint. Une capture (nommée « image.png » par le navigateur)
// devient « Capture AAAA-MM-JJ HHhMM.png ». Contrôles avant l'envoi :
// nombre (data-pj-max), extension (data-pj-extensions), 25 Mo au total.
(function () {
  'use strict';
  var TOTAL_MAX = 25 * 1024 * 1024 - 64 * 1024; // marge pour les champs et en-têtes multipart (lot 18)

  function K() { return window.Kairos || {}; }
  function annoncer(t) { var k = K(); if (k.annoncer) k.annoncer(t); }
  function avertir(t) { var k = K(); if (k.toast) k.toast(t, { type: 'avertissement' }); else annoncer(t); }
  function taille(n) {
    if (n < 1024) return n + ' o';
    if (n < 1024 * 1024) return Math.round(n / 1024) + ' Ko';
    return (n / 1024 / 1024).toFixed(1).replace('.', ',') + ' Mo';
  }
  function deux(n) { return (n < 10 ? '0' : '') + n; }
  function nomCapture(f, existants) {
    var d = new Date();
    var base = 'Capture ' + d.getFullYear() + '-' + deux(d.getMonth() + 1) + '-' + deux(d.getDate()) + ' ' + deux(d.getHours()) + 'h' + deux(d.getMinutes());
    var ext = (/\.(\w+)$/.exec(f.name || '') || [null, (f.type.split('/')[1] || 'png')])[1].toLowerCase();
    var nom = base + '.' + ext, i = 2;
    while (existants.indexOf(nom) >= 0) { nom = base + '-' + i + '.' + ext; i++; }
    return nom;
  }
  function estCapture(f) { return /^image\//.test(f.type) && /^image\.\w+$/i.test(f.name || ''); }

  function init(zone) {
    if (zone._pj) return;
    var input = zone.querySelector('[data-pj-input]');
    var choix = zone.querySelector('[data-pj-choix]');
    var puces = zone.querySelector('[data-pj-puces]');
    var texte = zone.querySelector('textarea');
    var bouton = zone.querySelector('[data-pj-joindre]');
    if (!input || !puces) return;
    var max = parseInt(zone.getAttribute('data-pj-max'), 10) || 10;
    var extensions = (zone.getAttribute('data-pj-extensions') || '').split(',').filter(Boolean);
    if (choix && extensions.length) choix.setAttribute('accept', extensions.join(','));
    var fichiers = [];
    zone._pj = { vider: function () { fichiers = []; rendre(); } };

    function synchroniser() {
      try {
        var dt = new DataTransfer();
        fichiers.forEach(function (f) { dt.items.add(f); });
        input.files = dt.files;
      } catch (e) { /* navigateur ancien : seul le champ visible compte */ }
    }
    function rendre() {
      synchroniser();
      puces.textContent = '';
      fichiers.forEach(function (f, i) {
        var li = document.createElement('li');
        li.className = 'pj-puce';
        if (/^image\/(png|jpe?g|gif|webp)$/.test(f.type) && window.URL && URL.createObjectURL) {
          var img = document.createElement('img');
          img.alt = '';
          img.src = URL.createObjectURL(f);
          img.onload = function () { URL.revokeObjectURL(img.src); };
          li.appendChild(img);
        } else {
          var ico = document.createElement('span');
          ico.className = 'pj-ico';
          ico.setAttribute('aria-hidden', 'true');
          ico.textContent = ((/\.(\w+)$/.exec(f.name) || [null, '?'])[1] || '?').slice(0, 4).toUpperCase();
          li.appendChild(ico);
        }
        var nom = document.createElement('span');
        nom.className = 'pj-nom';
        nom.textContent = f.name;
        nom.title = f.name;
        li.appendChild(nom);
        var t = document.createElement('span');
        t.className = 'pj-taille';
        t.textContent = taille(f.size);
        li.appendChild(t);
        var x = document.createElement('button');
        x.type = 'button';
        x.className = 'pj-retirer';
        x.setAttribute('aria-label', 'Retirer ' + f.name);
        x.textContent = '×';
        x.addEventListener('click', function () {
          fichiers.splice(i, 1);
          rendre();
          annoncer('Pièce jointe retirée : ' + f.name + '.');
          if (texte) texte.focus();
        });
        li.appendChild(x);
        puces.appendChild(li);
      });
      zone.classList.toggle('pj-avec-fichiers', fichiers.length > 0);
      // Une pièce jointe compte comme une saisie (question « Abandonner ? »).
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
    function ajouter(liste) {
      var ajoutes = 0;
      var noms = fichiers.map(function (f) { return f.name; });
      var total = fichiers.reduce(function (s, f) { return s + f.size; }, 0);
      Array.prototype.forEach.call(liste || [], function (f) {
        if (!f) return;
        if (estCapture(f)) {
          try { f = new File([f], nomCapture(f, noms), { type: f.type }); } catch (e) { /* garde le nom */ }
        }
        var ext = (/\.\w+$/.exec(f.name || '') || [''])[0].toLowerCase();
        if (extensions.length && extensions.indexOf(ext) < 0) { avertir('Type de fichier non accepté : « ' + f.name + ' ».'); return; }
        if (fichiers.length >= max) { avertir('Au plus ' + max + ' fichiers par post.'); return; }
        if (total + f.size > TOTAL_MAX) { avertir('25 Mo au plus par post : « ' + f.name + ' » n’est pas joint.'); return; }
        fichiers.push(f);
        noms.push(f.name);
        total += f.size;
        ajoutes++;
      });
      if (ajoutes) {
        rendre();
        annoncer(ajoutes > 1 ? ajoutes + ' pièces jointes ajoutées.' : 'Pièce jointe ajoutée : ' + fichiers[fichiers.length - 1].name + '.');
      }
      return ajoutes;
    }

    if (texte) {
      texte.addEventListener('paste', function (e) {
        var cd = e.clipboardData;
        if (!cd || !cd.files || !cd.files.length) return;
        // Excel, Word, Outlook : du texte (ou du HTML) avec une image du
        // rendu — on colle le texte, on ne joint rien.
        var types = Array.prototype.slice.call(cd.types || []);
        var aDuTexte = types.indexOf('text/html') >= 0 || (cd.getData && (cd.getData('text/plain') || '').trim());
        if (aDuTexte) return;
        e.preventDefault();
        ajouter(cd.files);
      });
    }
    ['dragenter', 'dragover'].forEach(function (t) {
      zone.addEventListener(t, function (e) {
        if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') < 0) return;
        e.preventDefault();
        zone.classList.add('pj-survol');
      });
    });
    ['dragleave', 'dragend'].forEach(function (t) {
      zone.addEventListener(t, function (e) { if (!zone.contains(e.relatedTarget)) zone.classList.remove('pj-survol'); });
    });
    zone.addEventListener('drop', function (e) {
      zone.classList.remove('pj-survol');
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
        e.preventDefault();
        ajouter(e.dataTransfer.files);
      }
    });
    if (bouton && choix) {
      bouton.addEventListener('click', function () { choix.value = ''; choix.click(); });
      choix.addEventListener('change', function () { ajouter(choix.files); choix.value = ''; });
    }
    var form = zone.closest('form');
    if (form) form.addEventListener('reset', function () { setTimeout(function () { fichiers = []; rendre(); }, 0); });
  }

  function tout(racine) {
    (racine && racine.querySelectorAll ? racine : document).querySelectorAll('[data-pj-zone]').forEach(init);
  }
  tout(document);
  document.addEventListener('kairos:fragment', function (e) { tout(e.detail && e.detail.racine); });
  // Un fichier lâché à côté de la zone, dans une fenêtre ouverte, ne doit
  // pas ouvrir le fichier dans l'onglet (saisie perdue).
  ['dragover', 'drop'].forEach(function (t) {
    document.addEventListener(t, function (e) {
      if (e.defaultPrevented || !e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') < 0) return;
      if (e.target.closest && e.target.closest('dialog[open], .post-edition')) e.preventDefault();
    });
  });
})();

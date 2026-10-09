/* Daily log v9 (lot 10) — saisie de la journée, portée de la maquette v9
   validée par Fadhel le 2026-10-06 (/tmp/lot10-audit/maquette-dailylog-v9.html)
   et branchée sur l'API JSON de app/routes/dailylog.py.

   Deux parties :
   1. un noyau PUR (formatage, saisie « 2,5 · 2h30 · 45min », grille de
      30 min, dates ISO) — exporté pour les tests node (tests_js/) ;
   2. la page : état d'UN jour {date, statut, lignes, version} rendu EN
      PLACE (patchRow : le focus n'est jamais perdu), enregistrement par
      PUT avec verrou optimiste (409), file d'écriture unique, jetons de
      séquence contre les réponses périmées, autosave au changement de jour
      et en arrière-plan (fetch keepalive), une seule zone live.
   Tous les textes viennent du gabarit (#dl-textes) ; aucun HTML n'est
   construit à partir d'une donnée : textContent partout. */
(function (racine, fabrique) {
  var noyau = fabrique();
  if (typeof module === 'object' && module.exports) module.exports = noyau;
  else racine.KairosDailyLog = noyau;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  var PAS = 30;

  function deux(n) { return (n < 10 ? '0' : '') + n; }

  /** Minutes → « 2 h 30 », « 45 min », « 8 h », « 0 h ». */
  function fmt(minutes, unites) {
    var u = unites || { h: 'h', min: 'min' };
    var m = Math.round(minutes || 0);
    if (m <= 0) return '0 ' + u.h;
    var H = Math.floor(m / 60), mn = m % 60;
    if (H && mn) return H + ' ' + u.h + ' ' + deux(mn);
    if (H) return H + ' ' + u.h;
    return mn + ' ' + u.min;
  }

  /** Saisie libre → minutes (NaN si illisible, 0 si vide).
   *  « 2,5 » « 2.5h » « 2h30 » « 2h30min » « 2:30 » « 45min » « 90 min » ;
   *  un nombre nu se lit en heures. */
  function parse(texte) {
    var s = String(texte == null ? '' : texte).trim().toLowerCase().replace(',', '.');
    var m;
    if (!s) return 0;
    if ((m = s.match(/^(\d+)\s*[h:]\s*(\d{1,2})\s*(?:min)?$/))) {
      var mn = +m[2];
      return mn < 60 ? (+m[1]) * 60 + mn : NaN;
    }
    if ((m = s.match(/^(\d*\.?\d+)\s*h$/))) return (+m[1]) * 60;
    if ((m = s.match(/^(\d+)\s*min$/))) return +m[1];
    if ((m = s.match(/^(\d*\.?\d+)$/))) return (+m[1]) * 60;
    return NaN;
  }

  /** Nombre nu (lu en heures) : « 12 » au lieu de « 12min » est refusé. */
  function estNombreNu(texte) { return /^\d*[.,]?\d+$/.test(String(texte).trim()); }

  /** Pas de 30 min le plus proche. */
  function q(minutes) { return Math.round(minutes / PAS) * PAS; }

  /** − : valeur de grille inférieure (2 h 15 → 2 h ; 2 h → 1 h 30). */
  function versLeBas(minutes) {
    var f = Math.floor(minutes / PAS) * PAS;
    return Math.max(0, f === minutes ? minutes - PAS : f);
  }

  /** + : valeur de grille supérieure (2 h 15 → 2 h 30 ; 2 h → 2 h 30). */
  function versLeHaut(minutes) {
    var c = Math.ceil(minutes / PAS) * PAS;
    return c === minutes ? minutes + PAS : c;
  }

  /** Remise sur la grille d'une ancienne valeur (copie, annulation d'une absence). */
  function surGrille(minutes) { return Math.max(PAS, q(minutes)); }

  function cle(projetId, tacheId) { return projetId + ':' + (tacheId || 0); }

  // Palette catégorielle NON sémantique (ni rouge, ni ambre, ni vert, ni bleu de statut).
  var COULEURS = ['#6b53c4', '#7d6fb3', '#4a6fa5', '#8a5bb0', '#c47aa0', '#7a5c43', '#5a7d8c', '#3f6e7a', '#9a6cae', '#4d6b9e'];
  function couleur(code) {
    var s = 0, t = String(code || '');
    for (var i = 0; i < t.length; i++) s = (s * 31 + t.charCodeAt(i)) >>> 0;
    return COULEURS[s % COULEURS.length];
  }

  /** Recherche sans accents ni casse, comme fn_recherche côté serveur
   *  (lot 11 : unaccent, « œ » → « oe ») — règles de texte-recherche.js. */
  function norm(texte) {
    var kt = (typeof module === 'object' && module.exports && typeof require === 'function')
      ? require('./texte-recherche.js') : (typeof self !== 'undefined' ? self.KairosTexte : null);
    if (kt) return kt.sansAccents(texte);
    return String(texte || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  }

  // Dates ISO « AAAA-MM-JJ », calculées en UTC (aucun effet d'heure d'été).
  function versDate(k) { var p = String(k).split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])); }
  function versIso(d) { return d.getUTCFullYear() + '-' + deux(d.getUTCMonth() + 1) + '-' + deux(d.getUTCDate()); }
  function ajouterJours(k, n) { var d = versDate(k); d.setUTCDate(d.getUTCDate() + n); return versIso(d); }
  /** 0 = lundi … 6 = dimanche. */
  function jourSemaine(k) { return (versDate(k).getUTCDay() + 6) % 7; }
  function estWeekEnd(k) { return jourSemaine(k) >= 5; }
  /** Jour ouvré voisin (les flèches ‹ › sautent samedi et dimanche). */
  function jourOuvre(k, sens) {
    var d = ajouterJours(k, sens);
    while (estWeekEnd(d)) d = ajouterJours(d, sens);
    return d;
  }
  function moisDe(k) { return String(k).slice(0, 7); }
  function ajouterMois(m, n) {
    var p = m.split('-'), d = new Date(Date.UTC(+p[0], +p[1] - 1 + n, 1));
    return d.getUTCFullYear() + '-' + deux(d.getUTCMonth() + 1);
  }

  /** Lignes à renvoyer après une copie ou une annulation d'absence : sur la
   *  grille, 30 min au moins, 10 h au plus au total (les suivantes tombent). */
  function surGrilleEtPlafond(lignes, maxJour) {
    var total = 0, sortie = [], modifiees = false;
    lignes.forEach(function (l) {
      var m = surGrille(l.minutes);
      if (m !== l.minutes) modifiees = true;
      m = Math.min(m, Math.floor((maxJour - total) / PAS) * PAS);
      if (m < PAS) { modifiees = true; return; }
      if (m !== surGrille(l.minutes)) modifiees = true;
      total += m;
      sortie.push(Object.assign({}, l, { minutes: m }));
    });
    return { lignes: sortie, modifiees: modifiees };
  }

  return {
    PAS: PAS, fmt: fmt, parse: parse, estNombreNu: estNombreNu, q: q, versLeBas: versLeBas,
    versLeHaut: versLeHaut, surGrille: surGrille, cle: cle, couleur: couleur, norm: norm,
    versDate: versDate, versIso: versIso, ajouterJours: ajouterJours, jourSemaine: jourSemaine,
    estWeekEnd: estWeekEnd, jourOuvre: jourOuvre, moisDe: moisDe, ajouterMois: ajouterMois,
    surGrilleEtPlafond: surGrilleEtPlafond
  };
});

(function () {
  'use strict';
  if (typeof document === 'undefined') return;

  // Instance en cours : arrêtée (écouteurs du document et de la fenêtre)
  // quand la page est remplacée par celle d'une autre personne (#dl9).
  var arreter = null;

  function demarrer() {
    var N = window.KairosDailyLog;
    var $ = function (id) { return document.getElementById(id); };
    var racine = $('dl9');
    if (!racine || !$('dl-amorce') || racine.dataset.dlInit) return;
    racine.dataset.dlInit = '1';
    if (arreter) arreter();
    var ctrl = window.AbortController ? new window.AbortController() : null;
    var sig = ctrl ? { signal: ctrl.signal } : false;
    var aRetirer = [];
    arreter = function () { if (ctrl) ctrl.abort(); aRetirer.forEach(function (fn) { fn(); }); };
    var A = JSON.parse($('dl-amorce').textContent);
    var T = JSON.parse($('dl-textes').textContent);
    var C = A.constantes, PAS = C.pas, MAXJ = C.maxJour;
    var U = { h: T.unite_h, min: T.unite_min };
    var SVG_COPIE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>';
    var SVG_CADENAS = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>';

    function f(m) { return N.fmt(m, U); }
    function tr(texte, x, y) { return String(texte).split('{x}').join(x == null ? '' : x).split('{y}').join(y == null ? '' : y); }
    function jourNum(d) { return d === 1 ? '1er' : String(d); }
    // espaces insécables : « ven. 2 oct. » ne se coupe pas dans un toast ou une puce
    // L'année dès qu'elle n'est pas celle d'aujourd'hui (lot 13, audit temps T-M2).
    function dateCourte(k) {
      var d = N.versDate(k);
      var texte = T.jours_courts[N.jourSemaine(k)] + ' ' + d.getUTCDate() + ' ' + T.mois_courts[d.getUTCMonth()];
      return String(k).slice(0, 4) !== String(TODAY).slice(0, 4) ? texte + ' ' + d.getUTCFullYear() : texte;
    }
    function dateLongue(k) { var d = N.versDate(k); return T.jours_longs[N.jourSemaine(k)] + ' ' + jourNum(d.getUTCDate()) + ' ' + T.mois[d.getUTCMonth()]; }
    function url(modele, valeur) { return modele.replace(/AAAA-MM(-JJ)?/, valeur); }
    function avecParam(u, cleParam, valeur) { return u + (u.indexOf('?') >= 0 ? '&' : '?') + cleParam + '=' + encodeURIComponent(valeur); }

    // --- éléments ---------------------------------------------------------
    var listeEl = $('dl-liste'), totalEl = $('dl-total'), resteEl = $('dl-reste'), jaugeEl = $('dl-jauge'),
        saveBtn = $('dl-enregistrer'), statutEl = $('dl-status'), statutTexte = $('dl-status-texte'),
        objVal = $('dl-obj-val'), objMoins = $('dl-obj-moins'), objPlus = $('dl-obj-plus'),
        calEl = $('dl-cal'), dateBtn = $('dl-date'), dateLabel = $('dl-date-label'), titreEl = $('dl-titre'),
        precBtn = $('dl-prec'), suivBtn = $('dl-suiv'), banniere = $('dl-banniere'), banniereTexte = $('dl-banniere-texte'),
        ajoutBtn = $('dl-ajouter'), ajoutWrap = $('dl-ajout'), panneau = $('dl-catalogue'), rechercheEl = $('dl-recherche'),
        catCorps = $('dl-catalogue-corps'), copierBtn = $('dl-copier'), absentBtn = $('dl-absent'),
        outilsEl = $('dl-outils'), aideEl = $('dl-aide'), lectureEl = $('dl-lecture'), liveEl = $('dl-live'),
        barreEl = $('dl-barre'), quiDate = $('dl-qui-date'), catStatut = $('dl-catalogue-statut');

    // --- état -------------------------------------------------------------
    var jour = null;            // état serveur du jour affiché (format `Jour`)
    var TODAY = A.jour.aujourdhui;
    var sel = A.jour.date;
    var rows = [];              // lignes affichées : {cle, projet_id, tache_id, code, nom, tache_titre, m, prev, modifiable, masquee, couleur}
    var saved = 'nouveau';      // nouveau | modifie | envoi | enregistre | erreur
    var rev = 0;                // révision locale : +1 à chaque modification
    var chargement = false;
    var objectif = A.objectifMinutes;
    var versions = {};          // date -> dernière version connue
    var etatsMois = {};         // 'AAAA-MM' -> {date: statut}
    etatsMois[A.mois.mois] = A.mois.jours;
    var calMois = N.moisDe(sel);
    var catalogue = A.catalogue || { mine: [], recentes: [] };
    var seqJour = 0, seqMois = 0, seqRech = 0;
    var fileEcriture = Promise.resolve();
    var dernierEchec = false;
    var revKeepalive = -1;     // révision déjà envoyée en keepalive (fermeture / arrière-plan)
    var avantAbsent = {};       // date -> lignes d'avant « Marquer absent » (bouton Annuler)
    var lastState = '';
    var resultatsRecherche = null, rechercheMotif = '', tachesOuvertes = {}, tachesChargees = {};
    var cleBrouillon = 'kairos-dl-brouillon-' + A.acteur.id + '-' + A.proprietaire.id + '-';

    // « Voir comme » (lecture seule, lot 13) : aucune commande d'écriture
    // proposée — le serveur refuse de toute façon (403).
    var VOIR = document.documentElement.hasAttribute('data-lecture-seule');
    var K = window.Kairos;

    // --- messages : toasts du socle (lot 13) + annonces -------------------
    // Un seul message du Daily log à la fois (le suivant remplace le
    // précédent) ; ses actions (« Annuler », « Garder ma saisie »…) sont
    // des boutons du toast, qui garde l'id dl-toast. Correctif du lot 13
    // (verif-a11y-perf R2) : un toast créé déjà rempli n'est pas lu de façon
    // sûre ; le message part aussi dans une région persistante —
    // Kairos.annoncer (socle) s'il existe, sinon #dl-live — avec les actions
    // disponibles (« bouton Annuler disponible »).
    var toastCourant = null, sayT;
    function say(msg) { clearTimeout(sayT); liveEl.textContent = ''; sayT = setTimeout(function () { liveEl.textContent = msg; }, 30); }
    function annoncer(msg) {
      if (K && typeof K.annoncer === 'function') K.annoncer(msg);
      else say(msg);
    }
    function hideToast() {
      if (toastCourant) { var t = toastCourant; toastCourant = null; t.removeAttribute('id'); if (K) K.fermerToast(t, false); }
    }
    /** opt : {warn, actions:[{texte, fn}], duree (0 = jusqu'à action), back} */
    function toast(msg, opt) {
      opt = opt || {};
      var actions = opt.actions || (opt.undo ? [{ texte: T.annuler, fn: opt.undo }] : []);
      hideToast();
      if (!K || !K.toast) { say(msg); return; }
      var duree = opt.duree != null ? opt.duree : (actions.length ? 8000 : opt.warn ? 5500 : 2200);
      var el = K.toast(msg, { type: opt.warn ? 'avertissement' : 'succes', duree: duree, annonce: false });
      annoncer(msg + (actions.length ? (actions[0].texte === T.annuler ? T.annuler_dispo
        : ' — ' + actions.map(function (a) { return a.texte; }).join(', ')) : ''));
      el.id = 'dl-toast';
      el.classList.add('dl-toast-k');
      if (actions.length) el.classList.add('dl-has-undo');
      var zone = el.querySelector('.k-toast-actions'), fermer = el.querySelector('.k-toast-fermer');
      actions.forEach(function (a) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'k-toast-action dl-undo';
        b.textContent = a.texte;
        b.addEventListener('click', function () { hideToast(); a.fn(); if (opt.back && document.body.contains(opt.back)) opt.back.focus(); });
        zone.insertBefore(b, fermer);
      });
      toastCourant = el;
      if (fermer) fermer.addEventListener('click', function () { if (toastCourant === el) { toastCourant = null; el.removeAttribute('id'); } });
    }
    function hideToastIfStale() { if (toastCourant && toastCourant.classList.contains('dl-has-undo')) hideToast(); }
    /** Bouton indisponible sans perdre le focus (bug UX I3) : aria-disabled
     *  au lieu de disabled ; les gestionnaires vérifient estInactif(). */
    function inactif(btn, flag) {
      if (flag) btn.setAttribute('aria-disabled', 'true'); else btn.removeAttribute('aria-disabled');
    }
    function estInactif(btn) { return btn.getAttribute('aria-disabled') === 'true'; }

    // --- requêtes ----------------------------------------------------------
    /** fetch JSON ; résout toujours {status, data} (status 0 = réseau). */
    function requete(methode, adresse, corps, keepalive) {
      var opts = { method: methode, credentials: 'same-origin', headers: { 'Accept': 'application/json' } };
      if (corps !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(corps); }
      if (keepalive) opts.keepalive = true;
      return fetch(adresse, opts).then(function (r) {
        return r.json().then(function (d) { return { status: r.status, data: d }; }, function () { return { status: r.status, data: null }; });
      }, function () { return { status: 0, data: null }; });
    }
    function urlJour(k) { return url(A.urls.jour, k); }
    function urlAbsence(k) { return url(A.urls.absence, k); }
    function urlPage(k) {
      var u = avecParam(A.urls.page, 'date', k);
      return A.proprietaire.soi ? u : avecParam(u, 'utilisateur', A.proprietaire.id);
    }
    /** File d'écriture : une seule écriture en vol, la suivante part avec la nouvelle version. */
    function ecrire(fn) { var p = fileEcriture.then(fn, fn); fileEcriture = p.then(null, function () {}); return p; }

    // --- lignes ------------------------------------------------------------
    function ligneVersRow(l, i) {
      if (l.masquee) {
        return { cle: 'masquee-' + i, masquee: true, m: l.minutes, prev: l.minutes, modifiable: false,
                 code: '', nom: T.ligne_masquee, tache_titre: null, couleur: '#8a958d' };
      }
      return { cle: N.cle(l.projet_id, l.tache_id), projet_id: l.projet_id, tache_id: l.tache_id || null,
               code: l.code, nom: l.nom, tache_titre: l.tache_titre, m: l.minutes,
               prev: l.minutes > 0 ? l.minutes : PAS, modifiable: !VOIR && !!l.modifiable, masquee: false,
               couleur: N.couleur(l.code) };
    }
    function proposes(j) {
      // Nouveau jour : mes projets proposés à 0 h, grisés, jamais stockés (décision maquette n°7).
      if (VOIR || j.statut !== 'vide' || !j.droits.saisie_libre || j.droits.mode !== 'saisie') return [];
      return (catalogue.mine || []).filter(function (c) { return !c.tache_id && (!c.date_debut || c.date_debut <= j.date); })
        .slice(0, 8).map(function (c) {
          return { cle: N.cle(c.projet_id, null), projet_id: c.projet_id, tache_id: null, code: c.code, nom: c.nom,
                   tache_titre: null, m: 0, prev: PAS, modifiable: true, masquee: false, couleur: N.couleur(c.code) };
        });
    }
    function lignesServeur(j) {
      var out = {};
      (j ? j.lignes : []).forEach(function (l) { if (!l.masquee) out[N.cle(l.projet_id, l.tache_id)] = l.minutes; });
      return out;
    }
    function lignesLocales() {
      var out = {};
      rows.forEach(function (r) { if (!r.masquee && r.m > 0) out[r.cle] = r.m; });
      return out;
    }
    function egales(a, b) {
      var ka = Object.keys(a), kb = Object.keys(b);
      return ka.length === kb.length && ka.every(function (k) { return b[k] === a[k]; });
    }
    function aEnvoyer() {
      return rows.filter(function (r) { return !r.masquee && r.m > 0; })
        .map(function (r) { return { projet_id: r.projet_id, tache_id: r.tache_id || null, minutes: r.m }; });
    }
    function total() { return rows.reduce(function (s, r) { return s + Math.max(0, r.m); }, 0); }
    function sumOthers(i) { return rows.reduce(function (s, r, j) { return s + (j === i ? 0 : Math.max(0, r.m)); }, 0); }
    function isAbsent() { return !!jour && jour.statut === 'absent'; }
    function droits() {
      var d = jour ? jour.droits : A.jour.droits;
      if (!VOIR) return d;
      return Object.assign({}, d, { saisie_libre: false, lignes_de_ses_projets: false, absence: false, copie: false });
    }
    function editable() { return !chargement && !isAbsent() && rows.some(function (r) { return r.modifiable; }); }
    function peutAjouter() { var d = droits(); return !chargement && !isAbsent() && (d.saisie_libre || d.lignes_de_ses_projets); }

    function recalcSaved() {
      if (isAbsent()) { saved = 'enregistre'; return; }
      if (egales(lignesLocales(), lignesServeur(jour))) saved = jour && jour.version > 0 ? 'enregistre' : 'nouveau';
      else saved = 'modifie';
    }
    function touched() {
      hideToastIfStale();
      rev++;
      recalcSaved();
      renderStatus();
    }
    function renderStatus() {
      var abs = isAbsent(), lecture = !abs && !editable() && !peutAjouter() && !chargement;
      var s = abs ? 'absent' : lecture ? 'lecture' : saved;
      statutEl.dataset.s = s;
      statutTexte.textContent = T.statut[s] || '';
    }

    // flush : une saisie en cours dans un champ est validée avant toute action
    // (iOS ne fait pas toujours « blur » au tap d'un bouton).
    function flush() {
      var a = document.activeElement;
      if (a && a.dataset && a.dataset.v != null && rows[+a.dataset.v]) { commitInput(a); a.blur(); }
    }

    function setH(i, m) {
      var r = rows[i];
      if (!r || !r.modifiable) return false;
      m = Math.max(0, m);
      var cap = Math.max(0, Math.floor((MAXJ - sumOthers(i)) / PAS) * PAS);
      var msg = '';
      if (m > r.m && m > cap) {
        // Seule une HAUSSE est plafonnée (une ancienne journée de plus de
        // 10 h peut toujours être réduite) ; jamais sous la valeur actuelle.
        var plafond = Math.max(cap, r.m);
        msg = plafond > r.m ? tr(T.max_ligne, f(plafond)) : T.journee_pleine;
        m = plafond;
      }
      if (m === r.m) { render(); if (msg) toast(msg, { warn: true }); return false; }
      if (m > 0) r.prev = m;
      r.m = m;
      touched();
      render();
      if (msg) toast(msg, { warn: true });
      else if (total() >= MAXJ) toast(T.journee_pleine);
      return true;
    }

    // --- rendu de la liste : EN PLACE --------------------------------------
    function buildRow(fixe) {
      var row = document.createElement('div');
      row.className = 'dl-row';
      var dot = document.createElement('span');
      dot.className = 'dl-pdot';
      row.appendChild(dot);
      var info = document.createElement(fixe ? 'div' : 'button');
      info.className = 'dl-pinfo';
      if (!fixe) info.type = 'button';
      var code = document.createElement('span'); code.className = 'dl-pcode';
      var nom = document.createElement('span'); nom.className = 'dl-pname';
      info.appendChild(code); info.appendChild(nom);
      row.appendChild(info);
      if (fixe) {
        var v = document.createElement('span');
        v.className = 'dl-fixval';
        v.innerHTML = SVG_CADENAS;
        var t = document.createElement('span');
        t.className = 'dl-fixtexte';
        v.appendChild(t);
        row.appendChild(v);
      } else {
        var st = document.createElement('div');
        st.className = 'dl-stepper';
        var moins = document.createElement('button'); moins.type = 'button'; moins.className = 'dl-step dl-minus'; moins.tabIndex = -1; moins.textContent = '−';
        var val = document.createElement('input');
        val.className = 'dl-val'; val.type = 'text'; val.setAttribute('inputmode', 'text'); val.setAttribute('enterkeyhint', 'done');
        val.autocomplete = 'off'; val.setAttribute('role', 'spinbutton'); val.setAttribute('aria-valuemin', '0');
        var plus = document.createElement('button'); plus.type = 'button'; plus.className = 'dl-step dl-plus'; plus.tabIndex = -1; plus.textContent = '+';
        st.appendChild(moins); st.appendChild(val); st.appendChild(plus);
        row.appendChild(st);
      }
      row.dataset.fixe = fixe ? '1' : '0';
      return row;
    }
    function setDisabled(btn, flag, repli) {
      if (flag && document.activeElement === btn) {
        if (repli && btn.matches(':focus-visible')) repli.focus(); else btn.blur();
      }
      btn.disabled = flag;
    }
    function libelleCode(r) { return r.code + (r.tache_titre ? ' · ' + r.tache_titre : ''); }
    function patchRow(row, r, i, tot) {
      var off = r.m <= 0, plein = tot >= MAXJ;
      row.className = 'dl-row' + (off ? ' dl-off' : '') + (row.dataset.fixe === '1' ? ' dl-fixe' : '') + (row.classList.contains('dl-row-err') ? ' dl-row-err' : '');
      row.dataset.cle = r.cle;
      row.querySelector('.dl-pdot').style.background = /^#[0-9a-f]{6}$/i.test(r.couleur) ? r.couleur : '#6f8278';
      var info = row.querySelector('.dl-pinfo');
      info.querySelector('.dl-pcode').textContent = r.masquee ? '' : libelleCode(r);
      info.querySelector('.dl-pname').textContent = r.nom;
      if (row.dataset.fixe === '1') {
        row.querySelector('.dl-fixtexte').textContent = f(r.m);
        var titre = r.masquee ? T.ligne_masquee : (droits().futur_reel ? T.ligne_futur_reel
          : (droits().lecture_seule || droits().mode === 'saisie' ? T.ligne_verrouillee_fenetre : T.ligne_verrouillee));
        row.title = titre;
        row.querySelector('.dl-fixval').setAttribute('aria-label', f(r.m) + ' — ' + titre);
        return;
      }
      info.dataset.t = i;
      info.setAttribute('aria-pressed', String(!off));
      var val = row.querySelector('.dl-val'), moins = row.querySelector('.dl-minus'), plus = row.querySelector('.dl-plus');
      val.dataset.v = i;
      if (document.activeElement !== val || val.value === f(r.m) || !val.dataset.saisie) val.value = f(r.m);
      val.setAttribute('aria-label', tr(T.heures_sur, r.nom + (r.tache_titre ? ' · ' + r.tache_titre : '')));
      val.setAttribute('aria-valuenow', String(r.m / 60));
      val.setAttribute('aria-valuetext', f(r.m));
      val.setAttribute('aria-valuemax', String(MAXJ / 60));
      moins.dataset.m = i; moins.setAttribute('aria-label', tr(T.moins_30, r.nom));
      plus.dataset.p = i; plus.setAttribute('aria-label', tr(T.plus_30, r.nom));
      plus.title = plein ? T.journee_pleine : '';
      setDisabled(moins, off, val);
      setDisabled(plus, plein, val);
      if (document.activeElement === val && !val.dataset.saisie) val.select();
    }
    function render() {
      updateCopy();
      var d = droits();
      if (isAbsent()) {
        listeEl.textContent = '';
        var carte = document.createElement('div');
        carte.className = 'dl-absentcard';
        var b = document.createElement('b'); b.textContent = T.absent_carte_titre;
        carte.appendChild(b); carte.appendChild(document.createElement('br'));
        carte.appendChild(document.createTextNode(T.absent_carte_texte));
        listeEl.appendChild(carte);
        ajoutWrap.hidden = true; copierBtn.hidden = true; aideEl.hidden = true;
        renderTotal(); return;
      }
      if (listeEl.querySelector('.dl-absentcard')) listeEl.textContent = '';
      ajoutWrap.hidden = !peutAjouter();
      // État vide sans invitation à saisir quand rien n'est saisissable
      // (jour du futur réel sous date simulée, lecture seule).
      listeEl.setAttribute('data-vide', peutAjouter() ? T.aucun_projet : (d.futur_reel ? T.aucun_projet_futur : T.aucun_projet_lecture));
      copierBtn.hidden = !d.copie;
      aideEl.hidden = !editable() && !peutAjouter();
      listeEl.setAttribute('aria-busy', chargement ? 'true' : 'false');
      var enfants = listeEl.children;
      var meme = enfants.length === rows.length && Array.prototype.every.call(enfants, function (el, i) {
        return el.dataset.cle === rows[i].cle && el.dataset.fixe === (rows[i].modifiable ? '0' : '1');
      });
      if (!meme) {
        listeEl.textContent = '';
        rows.forEach(function (r) { listeEl.appendChild(buildRow(!r.modifiable)); });
      }
      var tot = total();
      rows.forEach(function (r, i) { patchRow(enfants[i], r, i, tot); });
      renderTotal();
    }
    function renderTotal() {
      var tot = total(), abs = isAbsent(), diff = tot - objectif, state, msg;
      totalEl.textContent = f(tot);
      totalEl.className = 'dl-totval' + (diff > 0 ? ' dl-over' : (diff === 0 && tot > 0 ? ' dl-ok' : (tot > 0 ? ' dl-under' : '')));
      jaugeEl.querySelector('i').style.width = Math.min(100, objectif > 0 ? tot / objectif * 100 : 0) + '%';
      jaugeEl.className = 'dl-gauge' + (diff > 0 ? ' dl-over' : (tot > 0 && diff < 0 ? ' dl-under' : ''));
      jaugeEl.setAttribute('aria-valuenow', String(tot / 60));
      jaugeEl.setAttribute('aria-valuemax', String(Math.max(objectif, tot) / 60));
      jaugeEl.setAttribute('aria-valuetext', tr(T.sur, f(tot), f(objectif)));
      resteEl.className = 'dl-reste';
      resteEl.textContent = '';
      if (abs) { state = 'absent'; resteEl.textContent = '—'; msg = ''; }
      else if (tot <= 0) { state = 'vide'; resteEl.textContent = T.aucune_heure; msg = T.aucune_heure; }
      else if (diff === 0) { state = 'ok'; resteEl.classList.add('dl-ok'); resteEl.textContent = tr(T.journee_complete, f(objectif)); msg = tr(T.annonce_total_ok, f(tot)); }
      else if (diff < 0) { state = 'under'; resteEl.classList.add('dl-under'); ecrireReste(T.sous_journee, f(-diff), f(objectif)); msg = tr(T.annonce_total_sous, f(tot)); }
      else { state = 'over'; resteEl.classList.add('dl-over'); ecrireReste(T.au_dessus, f(diff), f(objectif)); msg = tr(T.annonce_total_dessus, f(tot)); }
      // annonce vocale uniquement quand la CATÉGORIE change (pas à chaque pas de 30 min)
      if (state !== lastState) { if (lastState !== '' && msg) say(msg); lastState = state; }
      renderSave(tot, abs);
    }
    function ecrireReste(modele, x, y) {
      // « <b>1 h 30</b> sous la journée de 8 h » sans innerHTML : le gras sur {x}.
      var parts = String(modele).split('{x}'), avant = parts[0], apres = parts.slice(1).join('{x}'), signe = '';
      if (avant.slice(-1) === '+') { signe = '+'; avant = avant.slice(0, -1); }
      if (avant) resteEl.appendChild(document.createTextNode(tr(avant, '', y)));
      var b = document.createElement('b');
      b.textContent = signe + x;
      resteEl.appendChild(b);
      resteEl.appendChild(document.createTextNode(tr(apres, '', y)));
    }
    function renderSave(tot, abs) {
      var d = droits();
      saveBtn.hidden = !abs && !editable() && !peutAjouter();
      saveBtn.classList.remove('dl-done', 'dl-danger');
      if (abs) { inactif(saveBtn, true); saveBtn.textContent = T.absent_bouton; return; }
      if (saved === 'envoi') { inactif(saveBtn, true); saveBtn.textContent = T.enregistrement; return; }
      if (tot <= 0) {
        var vider = jour && jour.statut === 'rempli' && saved === 'modifie' && rows.every(function (r) { return r.modifiable || r.m <= 0; });
        inactif(saveBtn, !vider);
        saveBtn.textContent = vider ? T.vider_journee : T.enregistrer;
        if (vider) saveBtn.classList.add('dl-danger');
        return;
      }
      inactif(saveBtn, chargement || (!d.saisie_libre && !d.lignes_de_ses_projets));
      saveBtn.classList.toggle('dl-done', saved === 'enregistre');
      saveBtn.textContent = saved === 'enregistre' ? T.enregistre_ok : T.enregistrer;
    }

    // --- interactions de la liste ---------------------------------------
    listeEl.addEventListener('click', function (e) {
      var t = e.target.closest('[data-m],[data-p],[data-t]');
      if (!t || t.disabled) return;
      var actif = document.activeElement;
      if (actif && actif.dataset && actif.dataset.v != null) flush();
      if (t.dataset.m != null) { var i = +t.dataset.m; setH(i, N.versLeBas(rows[i].m)); }
      else if (t.dataset.p != null) { var k = +t.dataset.p; setH(k, N.versLeHaut(rows[k].m)); }
      else if (t.dataset.t != null) { var n = +t.dataset.t; setH(n, rows[n].m > 0 ? 0 : (rows[n].prev || PAS)); }
    });
    listeEl.addEventListener('focusin', function (e) { if (e.target.dataset.v != null) e.target.select(); });
    listeEl.addEventListener('input', function (e) { if (e.target.dataset.v != null) e.target.dataset.saisie = '1'; });
    function commitInput(inp) {
      var i = +inp.dataset.v, r = rows[i];
      delete inp.dataset.saisie;
      if (!r) return;
      var brut = inp.value.trim(), cur = r.m;
      if (brut === f(cur)) return;
      function retour(msg) { inp.value = f(cur); toast(msg, { warn: true }); }
      if (brut === '') { retour(T.saisie_vide); return; }
      var v = N.parse(brut);
      if (isNaN(v) || v < 0) { retour(T.format_inconnu); return; }
      if (N.estNombreNu(brut) && v > MAXJ) { retour(T.max_10h_nombre); return; }
      var qv = N.q(v);
      if (v > 0 && qv === 0) { retour(T.minimum_30); return; }
      if (toastCourant && toastCourant.classList.contains('k-toast-avertissement')) hideToast();
      setH(i, qv);
      if (Math.abs(qv - v) > 1e-9 && rows[i].m === qv) toast(tr(T.arrondi, f(qv)));
    }
    listeEl.addEventListener('keydown', function (e) {
      if (e.target.dataset.v == null) return;
      var i = +e.target.dataset.v;
      if (e.key === 'Enter') { e.preventDefault(); commitInput(e.target); e.target.select(); }
      else if (e.key === 'Escape') { e.preventDefault(); delete e.target.dataset.saisie; e.target.value = f(rows[i].m); e.target.select(); }
      else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault();
        var v = N.parse(e.target.value), base = isNaN(v) ? rows[i].m : Math.min(v, MAXJ);
        delete e.target.dataset.saisie;
        if (e.key === 'ArrowUp') setH(i, N.versLeHaut(base)); else setH(i, N.versLeBas(base));
        e.target.select();
      }
    });
    listeEl.addEventListener('focusout', function (e) { if (e.target.dataset.v != null) commitInput(e.target); });

    // --- catalogue ---------------------------------------------------------
    function dansLaListe(c) { return rows.some(function (r) { return r.cle === N.cle(c.projet_id, c.tache_id) && r.m > 0; }); }
    function catRow(c, plein, indent) {
      var b = document.createElement('button');
      var inl = dansLaListe(c);
      b.type = 'button';
      b.className = 'dl-catrow' + (plein && !inl ? ' dl-full' : '') + (indent ? ' dl-catrow-tache' : '');
      b.dataset.add = N.cle(c.projet_id, c.tache_id);
      if (plein && !inl) b.setAttribute('aria-disabled', 'true');
      var dot = document.createElement('span'); dot.className = 'dl-cdot'; dot.style.background = N.couleur(c.code);
      var code = document.createElement('span'); code.className = 'dl-ccode'; code.textContent = c.code;
      var nom = document.createElement('span'); nom.className = 'dl-cname'; nom.textContent = c.tache_id ? c.tache_titre : (indent ? T.projet_seul : c.nom);
      b.title = c.code + ' — ' + (c.tache_id ? c.tache_titre + ' (' + c.nom + ')' : c.nom);
      b.appendChild(dot); b.appendChild(code); b.appendChild(nom);
      if (c.tache_id && !indent) { var sous = document.createElement('span'); sous.className = 'dl-csous'; sous.textContent = c.nom; nom.appendChild(document.createTextNode(' ')); nom.appendChild(sous); }
      var fin = document.createElement('span');
      if (inl) { fin.className = 'dl-cin'; fin.textContent = T.deja_dans_liste; }
      else { fin.className = 'dl-cadd'; fin.setAttribute('aria-hidden', 'true'); fin.textContent = '+'; }
      b.appendChild(fin);
      return b;
    }
    function itemsCatalogue() {
      var tous = {};
      (catalogue.mine || []).concat(catalogue.recentes || [], resultatsRecherche || []).forEach(function (c) { tous[N.cle(c.projet_id, c.tache_id)] = c; });
      Object.keys(tachesOuvertes).forEach(function (pid) { (tachesOuvertes[pid].taches || []).forEach(function (c) { tous[N.cle(c.projet_id, c.tache_id)] = c; }); });
      return tous;
    }
    function section(titre, items, plein) {
      if (!items.length) return null;
      var frag = document.createDocumentFragment();
      var h = document.createElement('div'); h.className = 'dl-catsection'; h.textContent = titre;
      frag.appendChild(h);
      var liste = document.createElement('div'); liste.className = 'dl-catlist';
      items.forEach(function (c) {
        var ligne = document.createElement('div');
        ligne.className = 'dl-catitem';
        ligne.appendChild(catRow(c, plein));
        if (!c.tache_id && c.nb_taches > 0) {
          var t = document.createElement('button');
          t.type = 'button';
          t.className = 'dl-cattaches';
          t.dataset.taches = c.projet_id;
          var ouvert = !!tachesOuvertes[c.projet_id];
          t.setAttribute('aria-expanded', String(ouvert));
          t.setAttribute('aria-label', tr(T.taches_titre, c.code + ' ' + c.nom));
          t.textContent = T.taches_du_projet + ' (' + c.nb_taches + ') ' + (ouvert ? '▾' : '▸');
          ligne.appendChild(t);
        }
        liste.appendChild(ligne);
        var ouvertes = tachesOuvertes[c.projet_id];
        if (!c.tache_id && ouvertes) {
          var sous = document.createElement('div');
          sous.className = 'dl-catsous';
          sous.setAttribute('role', 'group');
          sous.setAttribute('aria-label', tr(T.taches_titre, c.code));
          if (ouvertes.chargement) {
            var att = document.createElement('div'); att.className = 'dl-catempty'; att.textContent = T.recherche_en_cours; sous.appendChild(att);
          } else if (!ouvertes.taches.length) {
            var v = document.createElement('div'); v.className = 'dl-catempty'; v.textContent = T.aucune_tache; sous.appendChild(v);
          } else {
            ouvertes.taches.forEach(function (tc) { sous.appendChild(catRow(tc, plein, true)); });
          }
          liste.appendChild(sous);
        }
      });
      frag.appendChild(liste);
      return frag;
    }
    function renderCat() {
      var motif = N.norm((rechercheEl.value || '').trim());
      var plein = total() >= MAXJ;
      catCorps.textContent = '';
      var frags = [];
      if (motif) {
        var locaux = (catalogue.mine || []).concat(catalogue.recentes || []).filter(function (c) {
          return N.norm(c.code + ' ' + c.nom + ' ' + (c.tache_titre || '')).indexOf(motif) >= 0;
        });
        var vus = {}, items = [];
        locaux.concat(resultatsRecherche && rechercheMotif === motif ? resultatsRecherche : []).forEach(function (c) {
          var k = N.cle(c.projet_id, c.tache_id); if (!vus[k]) { vus[k] = 1; items.push(c); }
        });
        var s = section(T.resultats, items.slice(0, 50), plein);
        if (s) frags.push(s);
        if (!items.length) {
          var vide = document.createElement('div'); vide.className = 'dl-catempty';
          vide.textContent = (motif.length >= 2 && rechercheMotif !== motif) ? T.recherche_en_cours : T.aucun_trouve;
          frags.push(vide);
        }
      } else {
        var libres = function (c) { return !dansLaListe(c); };
        // un projet déjà dans la liste reste proposé s'il a des tâches : on peut imputer une tâche précise
        var projetsMine = (catalogue.mine || []).filter(function (c) { return !c.tache_id && (libres(c) || c.nb_taches > 0); });
        var tachesMine = (catalogue.mine || []).filter(function (c) { return c.tache_id; }).filter(libres);
        var recentes = (catalogue.recentes || []).filter(libres);
        [section(T.vos_projets, projetsMine, plein), section(T.vos_taches, tachesMine, plein), section(T.recents, recentes, plein)]
          .forEach(function (s2) { if (s2) frags.push(s2); });
        if (!frags.length) { var v2 = document.createElement('div'); v2.className = 'dl-catempty'; v2.textContent = T.tous_dans_liste; frags.push(v2); }
      }
      frags.forEach(function (fr) { catCorps.appendChild(fr); });
      annoncerCatalogue(motif);
    }
    // Une annonce courte du nombre de résultats (audit a11y I8) : la liste
    // elle-même n'est plus une région live.
    var annonceCat = '';
    function annoncerCatalogue(motif) {
      if (!catStatut) return;
      var texte = '';
      if (motif) {
        var n = catCorps.querySelectorAll('.dl-catrow').length;
        var attente = !n && motif.length >= 2 && rechercheMotif !== motif;
        texte = attente ? '' : (n ? n + (n > 1 ? ' projets ou tâches trouvés' : ' projet ou tâche trouvé') : T.aucun_trouve);
      }
      if (texte === annonceCat) return;
      annonceCat = texte;
      catStatut.textContent = texte;
    }
    var rechT;
    function rechercher() {
      var brut = (rechercheEl.value || '').trim(), motif = N.norm(brut);
      clearTimeout(rechT);
      var s = ++seqRech;
      if (motif.length < 2) { resultatsRecherche = null; rechercheMotif = ''; renderCat(); return; }
      renderCat();
      rechT = setTimeout(function () {
        var adresse = avecParam(avecParam(A.urls.recherche, 'q', brut), 'date', sel);
        if (!A.proprietaire.soi) adresse = avecParam(adresse, 'utilisateur', A.proprietaire.id);
        requete('GET', adresse).then(function (r) {
          if (s !== seqRech) return;   // réponse périmée (frappe suivante déjà partie)
          resultatsRecherche = r.status === 200 && r.data ? (r.data.resultats || []) : [];
          rechercheMotif = motif;
          if (!panneau.hidden) renderCat();
        });
      }, 200);
    }
    function chargerTaches(projetId) {
      if (tachesOuvertes[projetId]) { delete tachesOuvertes[projetId]; renderCat(); return; }
      tachesOuvertes[projetId] = { chargement: true, taches: [] };
      renderCat();
      var p = itemsCatalogue()[N.cle(projetId, null)] || {};
      var adresse = avecParam(avecParam(A.urls.taches, 'projet', projetId), 'date', sel);
      if (!A.proprietaire.soi) adresse = avecParam(adresse, 'utilisateur', A.proprietaire.id);
      requete('GET', adresse).then(function (r) {
        if (!tachesOuvertes[projetId]) return;
        var liste = r.status === 200 && r.data ? r.data.taches : [];
        tachesOuvertes[projetId] = {
          chargement: false,
          taches: [{ projet_id: projetId, code: p.code, nom: p.nom, tache_id: null, tache_titre: null, nb_taches: 0 }].concat(
            liste.map(function (t) { return { projet_id: projetId, code: p.code, nom: p.nom, tache_id: t.tache_id, tache_titre: t.tache_titre, nb_taches: 0 }; }))
        };
        if (!panneau.hidden) {
          renderCat();
          var bouton = catCorps.querySelector('[data-taches="' + projetId + '"]');
          if (bouton) bouton.focus();
        }
      });
    }
    function openAdd(show) {
      var ouvrir = show == null ? panneau.hidden : show;
      panneau.hidden = !ouvrir;
      ajoutBtn.setAttribute('aria-expanded', String(ouvrir));
      if (ouvrir) {
        rechercheEl.value = ''; resultatsRecherche = null; rechercheMotif = '';
        renderCat();
        setTimeout(function () { rechercheEl.focus(); panneau.scrollIntoView({ block: 'nearest' }); }, 0);
      }
    }
    function focusRow(i) { var el = listeEl.querySelector('[data-v="' + i + '"]'); if (el) { el.focus(); el.select(); } }
    ajoutBtn.addEventListener('click', function (e) { e.stopPropagation(); toggleCal(false); openAdd(); });
    panneau.addEventListener('click', function (e) {
      e.stopPropagation();
      var tb = e.target.closest('[data-taches]');
      if (tb) { chargerTaches(+tb.dataset.taches); return; }
      var r = e.target.closest('[data-add]');
      if (!r) return;
      flush();
      var k = r.dataset.add, idx = rows.map(function (x) { return x.cle; }).indexOf(k);
      if (idx >= 0) {
        openAdd(false);
        if (rows[idx].m <= 0) setH(idx, rows[idx].prev || PAS);
        focusRow(idx);
        return;
      }
      var c = itemsCatalogue()[k];
      if (!c) return;
      var libre = Math.floor((MAXJ - total()) / PAS) * PAS;
      if (libre < PAS) { toast(T.journee_pleine, { warn: true }); return; }
      rows.push({ cle: k, projet_id: c.projet_id, tache_id: c.tache_id || null, code: c.code, nom: c.nom,
                  tache_titre: c.tache_titre || null, m: PAS, prev: PAS, modifiable: true, masquee: false,
                  couleur: N.couleur(c.code) });
      touched(); render(); openAdd(false); focusRow(rows.length - 1);
      toast(tr(T.ajoute, c.tache_titre ? c.code + ' · ' + c.tache_titre : c.nom, f(PAS)));
    });
    rechercheEl.addEventListener('input', rechercher);
    rechercheEl.addEventListener('click', function (e) { e.stopPropagation(); });

    // --- objectif (préférence personnelle : ne marque PAS le jour modifié) --
    // Envoyé tout de suite (keepalive : un clic juste avant de quitter la page
    // n'est pas perdu), une requête à la fois ; la dernière valeur gagne.
    var objectifEnAttente = null, objectifEnVol = false;
    function syncObj() {
      objVal.textContent = f(objectif);
      // Objectif non modifiable en lecture seule ni sur un jour du futur réel.
      var figer = VOIR || !A.objectifModifiable || !!droits().futur_reel;
      objMoins.hidden = figer; objPlus.hidden = figer;
      setDisabled(objMoins, objectif <= C.objMin, objPlus);
      setDisabled(objPlus, objectif >= C.objMax, objMoins);
      renderTotal();
    }
    function envoyerObjectif(force) {
      if (objectifEnAttente == null || (objectifEnVol && !force)) return;
      var valeur = objectifEnAttente;
      objectifEnAttente = null;
      objectifEnVol = true;
      requete('PUT', A.urls.objectif, { objectif_minutes: valeur }, true).then(function (r) {
        objectifEnVol = false;
        if (r.status !== 200) toast(T.objectif_erreur, { warn: true });
        envoyerObjectif();
      });
    }
    function changerObjectif(delta) {
      if (!A.objectifModifiable || VOIR || droits().futur_reel) return;
      objectif = Math.min(C.objMax, Math.max(C.objMin, objectif + delta));
      syncObj();
      objectifEnAttente = objectif;
      envoyerObjectif();
    }
    objMoins.addEventListener('click', function () { changerObjectif(-PAS); });
    objPlus.addEventListener('click', function () { changerObjectif(PAS); });

    // --- outils du jour ----------------------------------------------------
    function updateCopy() {
      var c = jour && jour.copie;
      copierBtn.innerHTML = SVG_COPIE;
      copierBtn.appendChild(document.createTextNode(c ? tr(T.copier_le, dateCourte(c.date)) : T.copier_aucun));
      copierBtn.disabled = !c || chargement;
      copierBtn.title = c ? '' : T.copier_aucun_titre;
    }
    function cloneRows() { return rows.map(function (r) { return Object.assign({}, r); }); }
    copierBtn.addEventListener('click', function () {
      flush();
      var c = jour && jour.copie;
      if (!c || isAbsent()) return;
      var k0 = sel, avant = cloneRows();
      var copies = c.lignes.map(ligneVersRow);
      // les lignes que la personne ne peut pas modifier restent telles quelles
      rows = rows.filter(function (r) { return !r.modifiable && r.m > 0; }).concat(copies.filter(function (r) {
        return !rows.some(function (x) { return !x.modifiable && x.cle === r.cle; });
      }));
      touched(); render();
      toast(tr(T.copie_depuis, dateCourte(c.date)) + (c.exclues ? tr(c.exclues > 1 ? T.copie_exclues_pl : T.copie_exclues, c.exclues) : ''), {
        back: copierBtn,
        undo: function () { if (sel !== k0) return; rows = avant; touched(); render(); }
      });
    });
    function syncMark() {
      var ab = isAbsent();
      absentBtn.hidden = !droits().absence;
      absentBtn.textContent = ab ? T.annuler_absence : T.marquer_absent;
      absentBtn.classList.toggle('dl-on', ab);
      absentBtn.setAttribute('aria-pressed', String(ab));
      inactif(absentBtn, chargement);
    }
    function lignesRestaurees(k) {
      var avant = avantAbsent[k];
      if (!avant) return { lignes: [], modifiees: false };
      return N.surGrilleEtPlafond(avant.filter(function (r) { return !r.masquee && r.m > 0; }).map(function (r) {
        return { projet_id: r.projet_id, tache_id: r.tache_id || null, minutes: r.m };
      }), MAXJ);
    }
    function toggleAbsent() {
      flush();
      var k = sel, etaitAbsent = isAbsent(), avant = cloneRows(), avaitHeures = total() > 0;
      var corps, restaurees = null;
      if (etaitAbsent) {
        restaurees = lignesRestaurees(k);
        corps = { absent: false, lignes: restaurees.lignes };
      } else {
        corps = { absent: true };
      }
      if (estInactif(absentBtn)) return Promise.resolve();
      inactif(absentBtn, true);
      return ecrire(function () {
        corps.version = versions[k] || 0;
        return requete('POST', urlAbsence(k), corps).then(function (r) {
          inactif(absentBtn, chargement);
          if (r.status !== 200) { traiterEchec(k, r, corps); return; }
          majApresEcriture(r.data);
          if (sel !== k) return;
          if (etaitAbsent) {
            delete avantAbsent[k];
            appliquerJour(r.data, { garderToast: true });
            toast(T.absence_annulee + (restaurees && restaurees.modifiees ? ' — ' + T.valeurs_arrondies : ''));
          } else {
            avantAbsent[k] = avant;
            appliquerJour(r.data, { garderToast: true });
            toast(T.absent_marque + (avaitHeures ? T.absent_conserve : ''), {
              back: absentBtn,
              undo: avaitHeures ? function () { if (sel === k) toggleAbsent(); } : null
            });
          }
        });
      });
    }
    absentBtn.addEventListener('click', toggleAbsent);

    // --- enregistrement ------------------------------------------------------
    function majApresEcriture(d) {
      versions[d.date] = d.version;
      var m = etatsMois[N.moisDe(d.date)];
      if (m) {
        if (d.statut === 'vide') { if (m[d.date] && m[d.date] !== 'vide') delete m[d.date]; }
        else m[d.date] = d.statut;
      }
      if (d.manques) {
        // la bannière et les pastilles « non renseigné » suivent le serveur
        Object.keys(etatsMois).forEach(function (mo) {
          var em = etatsMois[mo];
          Object.keys(em).forEach(function (k) { if (em[k] === 'vide' && d.manques.indexOf(k) < 0) delete em[k]; });
        });
        d.manques.forEach(function (k) { var em = etatsMois[N.moisDe(k)]; if (em && !em[k]) em[k] = 'vide'; });
        if (jour) jour.manques = d.manques;
      }
      dernierEchec = false;
      try { sessionStorage.removeItem(cleBrouillon + d.date); } catch (e) { /* stockage indisponible */ }
      renderBanner();
      renderCal();
    }
    function fusionnerApresEnregistrement(d) {
      // garde les lignes à 0 h affichées ; met à jour droits et lignes gardées par le serveur
      var serveur = {};
      d.lignes.forEach(function (l, i) { var r = ligneVersRow(l, i); serveur[r.cle] = r; });
      rows.forEach(function (r) { if (serveur[r.cle]) { r.modifiable = serveur[r.cle].modifiable; delete serveur[r.cle]; } });
      Object.keys(serveur).forEach(function (k) { rows.push(serveur[k]); });
      jour = d;
      recalcSaved();
      render();
    }
    /** snap : lignes affichées au moment de l'envoi. Sans lui, un échec
     *  survenu après un changement de jour gardait rows: null — brouillon
     *  jamais proposé au retour (revue 2). */
    function sauverBrouillon(k, lignes, snap) {
      var r = snap || (k === sel ? cloneRows() : null);
      if (!r) return;
      try { sessionStorage.setItem(cleBrouillon + k, JSON.stringify({ lignes: lignes, rows: r })); } catch (e) { /* commodité locale */ }
    }
    function marquerErreurs(lignesEnvoyees, erreurs) {
      Array.prototype.forEach.call(listeEl.querySelectorAll('.dl-row-err'), function (el) {
        el.classList.remove('dl-row-err'); var v = el.querySelector('.dl-val'); if (v) v.removeAttribute('aria-invalid');
      });
      (erreurs || []).forEach(function (er) {
        var l = er.ligne != null ? lignesEnvoyees[er.ligne] : null;
        if (!l) return;
        var el = listeEl.querySelector('[data-cle="' + N.cle(l.projet_id, l.tache_id) + '"]');
        if (el) { el.classList.add('dl-row-err'); var v = el.querySelector('.dl-val'); if (v) v.setAttribute('aria-invalid', 'true'); }
      });
    }
    /** snap : lignes du jour k au moment de l'envoi (persist). Un échec sur
     *  un jour qui n'est plus affiché (enregistrement automatique au
     *  changement de jour) garde la saisie en brouillon, proposée au retour. */
    function traiterEchec(k, r, corps, snap) {
      var courant = k === sel;
      var garder = function () { if (snap) sauverBrouillon(k, corps && corps.lignes, snap); };
      if (r.status === 409 && r.data && r.data.jour) {
        var srv = r.data.jour;
        versions[k] = srv.version;
        if (!courant) {
          garder();
          toast(dateCourte(k) + ' : ' + T.conflit + (snap ? T.brouillon_garde : ''), { warn: true, duree: 0, actions: [{ texte: T.revenir, fn: function () { goDay(k); } }] });
          return;
        }
        if (egales(lignesLocales(), lignesServeur(srv))) { fusionnerApresEnregistrement(srv); renderStatus(); return; }
        jour.version = srv.version;
        saved = 'erreur'; renderStatus(); render();
        toast(T.conflit, { warn: true, duree: 0, actions: [
          { texte: T.garder_ma_saisie, fn: function () { persist({}); } },
          { texte: T.reprendre, fn: function () { appliquerJour(srv); } }
        ] });
        return;
      }
      // Mode changé dans un autre onglet (409 mode_change) : rien n'est
      // écrit et mode-onglets.js le dit (barre « Recharger »). La saisie
      // envoyée reste à l'écran et en brouillon, sans second message.
      if (r.status === 409 && r.data && r.data.erreur === 'mode_change') {
        if (snap) {
          garder();
          if (courant) { saved = 'erreur'; renderStatus(); render(); }
        }
        return;
      }
      if (r.status === 401 || (r.status === 400 && r.data && r.data.erreur === 'csrf')) {
        // Un GET (chargement d'un jour) n'a rien à garder : ne pas écraser un
        // brouillon existant par une liste vide.
        if (corps && corps.lignes) sauverBrouillon(k, corps.lignes, snap);
        if (courant) { saved = 'erreur'; renderStatus(); render(); }
        dernierEchec = true;
        toast(T.session_expiree, { warn: true, duree: 0, actions: [{ texte: T.se_reconnecter, fn: function () {
          window.location.href = avecParam(A.urls.connexion, 'next', urlPage(k));
        } }] });
        return;
      }
      if (r.status === 422 && r.data) {
        var er = (r.data.erreurs && r.data.erreurs[0]) || { code: r.data.erreur };
        if (courant) { saved = 'erreur'; renderStatus(); render(); marquerErreurs(corps.lignes || [], r.data.erreurs); }
        else garder();
        toast((courant ? '' : dateCourte(k) + ' : ') + (T.erreurs[er.code] || r.data.message || T.erreurs.refus_base), { warn: true, duree: 8000 });
        return;
      }
      if (r.status === 403 && r.data) {
        if (courant) { saved = 'erreur'; renderStatus(); render(); }
        // Lot 12 : « Voir comme » (lecture seule) dit pourquoi.
        toast(r.data.erreur === 'lecture_seule' && r.data.message ? r.data.message : T.erreurs.interdit, { warn: true, duree: 6000 });
        return;
      }
      dernierEchec = true;
      garder();
      if (courant) {
        saved = 'erreur'; renderStatus(); render();
        toast(r.status === 0 ? T.reseau : T.erreur_serveur, { warn: true, duree: 6000 });
        return;
      }
      // Jour quitté (enregistrement automatique) : la saisie n'est plus à
      // l'écran — le dire, et offrir d'y revenir (brouillon proposé).
      toast(tr(T.non_enregistre_autre_jour, dateCourte(k), r.status === 0 ? T.cause_reseau : T.cause_serveur) + (snap ? T.brouillon_garde : ''),
        { warn: true, duree: 0, actions: [{ texte: T.revenir, fn: function () { goDay(k); } }] });
    }
    /** opts : {auto, silencieux, keepalive, vider} */
    function persist(opts) {
      opts = opts || {};
      flush();
      if (isAbsent() || chargement) return Promise.resolve(false);
      var d = droits();
      if (!d.saisie_libre && !d.lignes_de_ses_projets) return Promise.resolve(false);
      var k = sel, lignes = aEnvoyer(), somme = total(), monRev = rev, snap = cloneRows();
      if (somme <= 0 && !opts.vider) return Promise.resolve(false);
      hideToastIfStale();
      if (opts.keepalive) {
        // Page qui se ferme ou passe en arrière-plan : envoi IMMÉDIAT (une
        // promesse en file ne partirait plus après le déchargement), une
        // seule fois par révision.
        if (revKeepalive === monRev) return Promise.resolve(false);
        revKeepalive = monRev;
      } else if (k === sel) { saved = 'envoi'; renderStatus(); renderTotal(); }
      var envoyer = function () {
        var corps = { version: versions[k] || 0, lignes: lignes };
        if (opts.vider) corps.vider = true;
        return requete('PUT', urlJour(k), corps, !!opts.keepalive).then(function (r) {
          if (r.status !== 200 || !r.data) { traiterEchec(k, r, corps, snap); return false; }
          majApresEcriture(r.data);
          if (k === sel) {
            if (rev === monRev) fusionnerApresEnregistrement(r.data);
            // Saisie modifiée pendant l'envoi : on garde l'écran, mais la
            // référence devient l'état ENREGISTRÉ (sinon revenir à l'ancienne
            // valeur affichait « Enregistré » alors que la base avait l'envoi).
            else { jour = r.data; recalcSaved(); render(); }
            renderStatus();
            if (opts.vider) toast(T.journee_videe);
            else if (!opts.silencieux) toast(T.journee_enregistree);
          } else if (opts.auto && r.data.enregistre) {
            toast(tr(T.auto_enregistre, dateCourte(k), f(somme)));
          }
          return true;
        });
      };
      return opts.keepalive ? envoyer() : ecrire(envoyer);
    }
    saveBtn.addEventListener('click', function () {
      if (estInactif(saveBtn)) return;
      flush();
      if (total() <= 0) {
        // Lot 13 : confirmation en ligne (plus de boîte native).
        var k0 = sel;
        if (K && K.confirmer) {
          K.confirmer(saveBtn, tr(T.confirmer_vider, dateCourte(sel)), { libelleOk: T.vider_journee, danger: true })
            .then(function (oui) { if (oui && sel === k0) persist({ vider: true }); });
        } else if (window.confirm(tr(T.confirmer_vider, dateCourte(sel)))) persist({ vider: true });
        return;
      }
      persist({});
    });
    function enAttente() { return saved === 'modifie' || saved === 'erreur'; }
    // Autre onglet qui change de mode : pas de rechargement pendant une
    // saisie, envoi en cours compris (contre-expertise temps R1). Retiré
    // quand la page est remplacée (« Daily log de », Retour) : l'ancienne
    // instance ne retient plus une saisie qui n'est plus à l'écran.
    if (window.KairosModes) {
      var retirerSurveillant = window.KairosModes.surveiller(function () {
        return document.contains(racine) && (enAttente() || saved === 'envoi');
      });
      if (typeof retirerSurveillant === 'function') aRetirer.push(retirerSurveillant);
    }
    // filet de sécurité : onglet en arrière-plan (téléphone verrouillé…) ou page quittée
    // Filet supplémentaire : le brouillon est aussi gardé sur l'appareil
    // (sessionStorage) ; il est retiré dès qu'une réponse confirme
    // l'enregistrement, ou au retour sur le jour s'il est identique au serveur.
    function enregistrerEnPartant() {
      envoyerObjectif(true);   // dernière valeur de l'objectif pas encore partie
      flush();
      if (!enAttente() || isAbsent()) return;
      sauverBrouillon(sel, aEnvoyer());
      persist({ silencieux: true, keepalive: true });
    }
    document.addEventListener('visibilitychange', function () { if (document.hidden) enregistrerEnPartant(); }, sig);
    window.addEventListener('pagehide', enregistrerEnPartant, sig);
    window.addEventListener('beforeunload', function (e) {
      // seulement si la dernière écriture a échoué : l'autosave couvre le reste
      if (dernierEchec || saved === 'erreur') { e.preventDefault(); e.returnValue = T.quitter; return T.quitter; }
    }, sig);

    // --- jours ---------------------------------------------------------------
    function autosaveSiBesoin() {
      if (!jour || isAbsent() || !enAttente()) return;
      if (total() > 0) persist({ auto: true, silencieux: true });
      else if (jour.statut === 'rempli') toast(tr(T.vide_ignoree, dateCourte(sel)), { warn: true });
    }
    function renderEntete() {
      dateLabel.textContent = dateCourte(sel);
      // Lot 11 (audit front M10) : même libellé que le h1 rendu par le
      // serveur (« Journée du jeudi 8 octobre 2026 »), année comprise.
      titreEl.textContent = tr(T.titre_jour, dateLongue(sel) + ' ' + N.versDate(sel).getUTCFullYear());
      var suivant = N.jourOuvre(sel, 1);
      suivBtn.disabled = suivant > TODAY;
      if (quiDate) quiDate.value = sel;
    }
    function renderLecture() {
      var d = droits(), textes = [];
      if (VOIR) textes.push(K && K.MESSAGE_LECTURE_SEULE ? K.MESSAGE_LECTURE_SEULE : T.lecture_seule);
      else if (d.futur_reel) textes.push(T.futur_reel);
      else if (!isAbsent()) {
        if (d.mode === 'saisie' && d.lecture_seule) textes.push(T.lecture_seule);
        else if (d.mode === 'saisie' && d.lignes_de_ses_projets) textes.push(T.lecture_seule_chef);
      }
      if (jour && jour.modifie_par_autre && jour.modifie_par && d.mode === 'saisie') textes.push(tr(T.modifie_par, jour.modifie_par));
      lectureEl.textContent = textes.join(' ');
      lectureEl.hidden = !textes.length;
    }
    function lireBrouillon(k) {
      try { var b = sessionStorage.getItem(cleBrouillon + k); return b ? JSON.parse(b) : null; } catch (e) { return null; }
    }
    function proposerBrouillon(k) {
      var b = lireBrouillon(k);
      if (!b || !b.rows || isAbsent()) return;
      var local = {};
      b.rows.forEach(function (r) { if (!r.masquee && r.m > 0) local[r.cle] = r.m; });
      if (egales(local, lignesServeur(jour))) { try { sessionStorage.removeItem(cleBrouillon + k); } catch (e) { /* rien */ } return; }
      toast(tr(T.brouillon_trouve, dateCourte(k)), { warn: true, duree: 0, actions: [{ texte: T.restaurer, fn: function () {
        if (sel !== k) return;
        rows = b.rows; touched(); render();
      } }] });
    }
    function appliquerJour(j, opts) {
      opts = opts || {};
      jour = j;
      TODAY = j.aujourdhui;
      sel = j.date;
      versions[j.date] = j.version;
      chargement = false;
      rows = j.lignes.map(ligneVersRow).concat(j.statut === 'absent' ? [] : proposes(j));
      recalcSaved();
      lastState = '';
      tachesOuvertes = {};
      renderEntete(); syncMark(); syncObj(); renderLecture(); renderStatus(); render(); renderBanner();
      calMois = N.moisDe(sel);
      chargerMois(calMois);
      if (!opts.garderToast) proposerBrouillon(j.date);
    }
    var dayT;
    function loadDay(k) {
      if (typeof k !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(k)) return;
      hideToastIfStale();
      var s = ++seqJour;
      sel = k;
      chargement = true;
      rows = [];
      jour = Object.assign({}, jour, { date: k, statut: 'vide', lignes: [], copie: null, version: versions[k] || 0 });
      renderEntete(); syncMark(); renderStatus(); render();
      openAdd(false);
      // L'état d'historique est gardé : Retour après « Daily log de » revient
      // à la personne précédente en partiel (kairos-partiel.js).
      try { history.replaceState(history.state, '', urlPage(k)); } catch (e) { /* rien */ }
      requete('GET', urlJour(k)).then(function (r) {
        if (s !== seqJour) return;   // l'utilisateur est déjà ailleurs : réponse ignorée
        if (r.status === 200 && r.data) {
          appliquerJour(r.data);
          clearTimeout(dayT);
          dayT = setTimeout(function () { say(titreEl.textContent + ', ' + statutTexte.textContent); }, 700);
          return;
        }
        chargement = false;
        if (r.status === 401) { traiterEchec(k, r, {}); return; }
        if (r.status === 422 && r.data && r.data.aujourdhui) { TODAY = r.data.aujourdhui; goDay(TODAY); return; }
        toast(T.chargement_impossible, { warn: true });
        renderStatus(); render();
      });
    }
    function goDay(k) {
      if (k > TODAY) k = TODAY;
      flush();
      autosaveSiBesoin();
      loadDay(k);
    }

    // --- bannière des jours manqués -------------------------------------------
    function renderBanner() {
      // Jours après la vraie date (date simulée) : pas saisissables, donc pas « à compléter ».
      var reel = jour && jour.aujourdhui_reel && jour.aujourdhui_reel < TODAY ? jour.aujourdhui_reel : TODAY;
      var manques = (jour && jour.manques ? jour.manques : []).filter(function (k) { return k <= reel; }).sort();
      if (!manques.length || !A.proprietaire.soi) { banniere.hidden = true; return; }
      banniere.hidden = false;
      var affiches = manques.slice(-5), autres = manques.length - affiches.length;
      banniereTexte.textContent = '';
      var b = document.createElement('b');
      b.textContent = tr(T.banniere, manques.length + ' ' + (manques.length > 1 ? T.banniere_jours : T.banniere_jour));
      banniereTexte.appendChild(b);
      banniereTexte.appendChild(document.createTextNode(T.banniere_suite));
      affiches.forEach(function (k) {
        var c = document.createElement('button');
        c.type = 'button'; c.className = 'dl-chip'; c.dataset.g = k; c.textContent = dateCourte(k);
        if (k === sel) c.setAttribute('aria-current', 'date');
        banniereTexte.appendChild(c);
      });
      if (autres > 0) {
        var p = document.createElement('span');
        p.className = 'dl-more';
        p.textContent = ' ' + tr(autres > 1 ? T.banniere_plus_pl : T.banniere_plus, autres) + T.banniere_cal;
        banniereTexte.appendChild(p);
      }
    }
    banniere.addEventListener('click', function (e) {
      var c = e.target.closest('[data-g]');
      if (!c) return;
      goDay(c.dataset.g); toggleCal(false); dateBtn.focus();
    });

    // --- calendrier (popover non modal, flèches clavier) ----------------------
    function chargerMois(mo) {
      if (etatsMois[mo] || mo > N.moisDe(TODAY)) { if (!calEl.hidden) renderCal(); return; }
      var s = ++seqMois;
      requete('GET', url(A.urls.mois, mo)).then(function (r) {
        if (r.status === 200 && r.data) etatsMois[mo] = r.data.jours || {};
        if (s === seqMois && !calEl.hidden && calMois === mo) renderCal();
      });
    }
    function renderCal() {
      if (calEl.hidden) return;
      var p = calMois.split('-'), y = +p[0], m = +p[1] - 1;
      var premier = calMois + '-01', debut = N.jourSemaine(premier);
      var nbJours = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
      var etats = etatsMois[calMois] || {};
      var auMax = calMois >= N.moisDe(TODAY);
      calEl.textContent = '';
      var tete = document.createElement('div'); tete.className = 'dl-cal-head';
      var mp = document.createElement('button'); mp.type = 'button'; mp.className = 'dl-navbtn'; mp.dataset.cm = '-1'; mp.setAttribute('aria-label', T.mois_precedent); mp.textContent = '‹';
      var titre = document.createElement('b'); titre.textContent = T.mois[m] + ' ' + y;
      var ms = document.createElement('button'); ms.type = 'button'; ms.className = 'dl-navbtn'; ms.dataset.cm = '1'; ms.setAttribute('aria-label', T.mois_suivant); ms.textContent = '›'; ms.disabled = auMax;
      tete.appendChild(mp); tete.appendChild(titre); tete.appendChild(ms);
      calEl.appendChild(tete);
      var grille = document.createElement('div'); grille.className = 'dl-cal-grid';
      T.jours_courts.forEach(function (d) { var e = document.createElement('div'); e.className = 'dl-cal-dow'; e.setAttribute('aria-hidden', 'true'); e.textContent = d.charAt(0).toUpperCase(); grille.appendChild(e); });
      for (var i = 0; i < debut; i++) grille.appendChild(document.createElement('div'));
      for (var jj = 1; jj <= nbJours; jj++) {
        var k = calMois + '-' + (jj < 10 ? '0' : '') + jj, we = N.estWeekEnd(k), st = etats[k] || '', futur = k > TODAY;
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'dl-cal-day' + (st ? ' dl-' + st : '') + (k === sel ? ' dl-sel' : '') + (k === TODAY ? ' dl-today' : '') + (we ? ' dl-we' : '');
        b.dataset.d = k;
        var lab = T.jours_longs[N.jourSemaine(k)] + ' ' + jourNum(jj) + ' ' + T.mois[m] + (k === TODAY ? ', ' + T.aujourdhui : '') +
          (st ? ', ' + T.statut_jour[st] : (we ? ', ' + T.week_end : ''));
        b.setAttribute('aria-label', lab);
        b.setAttribute('aria-pressed', String(k === sel));
        if (k === TODAY) b.setAttribute('aria-current', 'date');
        if (futur) b.disabled = true;
        b.textContent = String(jj);
        if (st) { var pip = document.createElement('span'); pip.className = 'dl-pip'; b.appendChild(pip); }
        grille.appendChild(b);
      }
      calEl.appendChild(grille);
      var leg = document.createElement('div'); leg.className = 'dl-cal-legend';
      [['dl-ldot', T.legende.rempli], ['dl-lbar', T.legende.absent], ['dl-lring', T.legende.vide],
       ['dl-lring-gris', T.legende.verrouille]].forEach(function (x) {
        var s = document.createElement('span'); var ic = document.createElement('i'); ic.className = x[0]; s.appendChild(ic); s.appendChild(document.createTextNode(x[1])); leg.appendChild(s);
      });
      calEl.appendChild(leg);
    }
    function toggleCal(show) {
      var ouvrir = show == null ? calEl.hidden : show;
      calEl.hidden = !ouvrir;
      dateBtn.setAttribute('aria-expanded', String(ouvrir));
      if (ouvrir) {
        calMois = N.moisDe(sel);
        chargerMois(calMois);
        renderCal();
        setTimeout(function () { var s = calEl.querySelector('.dl-cal-day.dl-sel:not([disabled])') || calEl.querySelector('.dl-cal-day:not([disabled])'); if (s) s.focus(); }, 0);
      }
    }
    dateBtn.addEventListener('click', function (e) { e.stopPropagation(); openAdd(false); toggleCal(); });
    precBtn.addEventListener('click', function () { goDay(N.jourOuvre(sel, -1)); });
    suivBtn.addEventListener('click', function () {
      if (suivBtn.disabled) return;
      goDay(N.jourOuvre(sel, 1));
      if (suivBtn.disabled) dateBtn.focus();
    });
    calEl.addEventListener('click', function (e) {
      e.stopPropagation();
      var cm = e.target.closest('[data-cm]');
      if (cm) {
        if (cm.disabled) return;
        var dir = cm.dataset.cm;
        calMois = N.ajouterMois(calMois, +dir);
        chargerMois(calMois);
        renderCal();
        var nb = calEl.querySelector('[data-cm="' + dir + '"]');
        if (nb && !nb.disabled) nb.focus(); else { var o = calEl.querySelector('[data-cm]:not([disabled])'); if (o) o.focus(); }
        return;
      }
      var d = e.target.closest('[data-d]');
      if (d && !d.disabled) { goDay(d.dataset.d); toggleCal(false); dateBtn.focus(); }
    });
    calEl.addEventListener('keydown', function (e) {
      var dk = e.target.dataset && e.target.dataset.d;
      if (!dk) return;
      var pas = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
      if (!pas) return;
      e.preventDefault();
      var nd = N.ajouterJours(dk, pas);
      if (nd > TODAY) return;
      if (N.moisDe(nd) !== calMois) { calMois = N.moisDe(nd); chargerMois(calMois); renderCal(); }
      var b = calEl.querySelector('[data-d="' + nd + '"]');
      if (b && !b.disabled) b.focus();
    });
    // popover non modal : se ferme quand le focus le quitte
    $('dl-datenav').addEventListener('focusout', function (e) {
      if (calEl.hidden || !e.relatedTarget) return;
      if (!$('dl-datenav').contains(e.relatedTarget)) toggleCal(false);
    });
    document.addEventListener('click', function (e) {
      if (!calEl.hidden && !$('dl-datenav').contains(e.target)) toggleCal(false);
      if (!panneau.hidden && !ajoutWrap.contains(e.target)) openAdd(false);
    }, sig);
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (!calEl.hidden) { toggleCal(false); dateBtn.focus(); }
      else if (!panneau.hidden) { openAdd(false); ajoutBtn.focus(); }
    }, sig);

    // --- « Daily log de » (chef, Admin) ---------------------------------------
    // Lot 13 (correctifs, verif-ux) : champ à recherche ; au choix, la saisie
    // en attente est enregistrée, puis la page de la personne remplace
    // celle-ci (fragment #dl9, adresse poussée : Retour revient).
    var quiSelect = $('dl-qui-select'), quiForm = quiSelect && quiSelect.form;
    function ouvrirPersonne() {
      var id = quiSelect.value || '';
      var actuel = A.proprietaire.soi ? '' : String(A.proprietaire.id);
      if (id === actuel || !K || !K.requete) return;
      flush();
      envoyerObjectif(true);
      autosaveSiBesoin();
      var u = avecParam(A.urls.page, 'date', sel);
      if (id) u = avecParam(u, 'utilisateur', id);
      fileEcriture.then(function () {
        if (!document.contains(racine)) return;
        K.requete({ url: u, methode: 'GET', cible: '#dl9', historique: 'push', transition: false,
                    focusApres: '#dl-qui-select ~ .search-combobox-wrap .search-combobox-input' });
      });
    }
    if (quiForm) {
      quiSelect.addEventListener('change', ouvrirPersonne);
      quiForm.addEventListener('submit', function (e) {
        if (!K || !K.requete) return;
        e.preventDefault();
        ouvrirPersonne();
      });
    }

    // --- démarrage -----------------------------------------------------------
    appliquerJour(A.jour);
    // Lot 13 (audit a11y I1, CLS 0,14) : la page se montre une fois la liste,
    // la bannière et les outils construits (dailylog.css).
    racine.classList.add('dl-pret');
    window.KairosDailyLogPage = {   // accès de test (Playwright) : lecture seule de l'état
      etat: function () { return { sel: sel, saved: saved, total: total(), version: versions[sel], chargement: chargement, rows: cloneRows() }; }
    };
  }

  // Page d'une autre personne insérée (« Daily log de », Retour) : nouveau départ.
  document.addEventListener('kairos:fragment', function (e) {
    var r = e.detail && e.detail.racine;
    if (r && r.id === 'dl9') demarrer();
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrer);
  else demarrer();
})();

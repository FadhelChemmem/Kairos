/* Champ de commentaire du fil (retours Fadhel, 2026-09-29) — voir
 * partials/post_card.html (macro composer_commentaire / commentaire) :
 *
 * - le champ grandit avec le texte ; Entrée envoie, Maj+Entrée va à la
 *   ligne ;
 * - "@" propose les personnes (liste #kairos-personnes, rendue par
 *   base.html) : le tag s'écrit "@Prénom Nom" directement dans le texte,
 *   le serveur retrouve ensuite les personnes taguées (routes/posts.py) ;
 * - un fichier se glisse directement sur le champ (ou se colle, ou se
 *   choisit avec le trombone) — plus de bandeau "Glisser une image…" ;
 * - "Répondre" ouvre le champ de réponse sous le commentaire, "Modifier"
 *   remplace le commentaire par son champ d'édition ;
 * - lot 14 (revue produit P1-3) : le champ d'un post est replié derrière
 *   « Commenter » (aria-expanded), déplié au clic avec le focus ; il reste
 *   ouvert tant qu'il contient un brouillon (Échap le replie s'il est
 *   vide) ; les brouillons survivent au remplacement du fil (changement de
 *   catégorie) et du bloc des commentaires.
 *
 * Sans JavaScript, les formulaires restent de simples formulaires.
 */
(function () {
  var personnes = [];
  try {
    var src = document.getElementById('kairos-personnes');
    if (src) personnes = JSON.parse(src.textContent) || [];
  } catch (e) { personnes = []; }
  personnes.forEach(function (p) {
    p.complet = (p.prenom + ' ' + p.nom).trim();
    // Lot 20 (revue QA n° 16d) : « @hel » trouve Hélène.
    p.cle = norm(p.complet);
    p.cleNom = norm(p.nom);
  });
  function norm(t) {
    if (window.KairosTexte && window.KairosTexte.sansAccents) return window.KairosTexte.sansAccents(t || '');
    return String(t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  }
  var numeroListe = 0;

  var RE_IMAGE = /\.(png|jpe?g|gif|webp)$/i;

  function autoGrow(ta) {
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 180) + 'px';
  }

  // --- Suggestions "@" ---------------------------------------------------
  function initMentions(ta) {
    var wrap = ta.parentNode;
    var liste = document.createElement('div');
    liste.className = 'mention-liste';
    liste.setAttribute('role', 'listbox');
    liste.id = 'mention-liste-' + (++numeroListe);
    liste.setAttribute('aria-label', 'Personnes à mentionner');
    liste.hidden = true;
    wrap.appendChild(liste);
    // Le champ (textbox multiligne : role combobox interdit sur textarea)
    // garde le focus ; l'option active est annoncée par
    // aria-activedescendant, la liste reliée par aria-controls.
    ta.setAttribute('aria-autocomplete', 'list');
    ta.setAttribute('aria-controls', liste.id);
    var choix = [];
    var actif = 0;
    var debut = -1;

    function fermer() {
      liste.hidden = true; choix = []; debut = -1;
      ta.removeAttribute('aria-activedescendant');
    }

    function requete() {
      var avant = ta.value.slice(0, ta.selectionStart);
      var m = /(^|\s)@([^\s@]{0,24}(?: [^\s@]{0,24})?)$/.exec(avant);
      if (!m) return null;
      return { debut: avant.length - m[2].length - 1, texte: norm(m[2]) };
    }

    function afficher() {
      var r = requete();
      if (!r || !personnes.length) return fermer();
      choix = personnes.filter(function (p) {
        return !r.texte || p.cle.indexOf(r.texte) === 0 || p.cleNom.indexOf(r.texte) === 0 ||
          p.cle.indexOf(' ' + r.texte) !== -1;
      }).slice(0, 6);
      if (!choix.length) return fermer();
      debut = r.debut;
      actif = Math.min(actif, choix.length - 1);
      liste.innerHTML = '';
      choix.forEach(function (p, i) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'mention-choix' + (i === actif ? ' actif' : '');
        b.setAttribute('role', 'option');
        b.id = liste.id + '-' + i;
        b.tabIndex = -1;
        b.setAttribute('aria-selected', i === actif ? 'true' : 'false');
        b.textContent = p.complet;
        // mousedown (pas click) : garder le focus dans le champ.
        b.addEventListener('mousedown', function (e) { e.preventDefault(); inserer(p); });
        liste.appendChild(b);
      });
      liste.hidden = false;
      ta.setAttribute('aria-activedescendant', liste.id + '-' + actif);
    }

    function inserer(p) {
      var fin = ta.selectionStart;
      var texte = '@' + p.complet + ' ';
      ta.value = ta.value.slice(0, debut) + texte + ta.value.slice(fin);
      var pos = debut + texte.length;
      ta.setSelectionRange(pos, pos);
      fermer();
      autoGrow(ta);
      ta.focus();
    }

    ta.addEventListener('input', function () { actif = 0; afficher(); });
    ta.addEventListener('click', afficher);
    ta.addEventListener('blur', function () { setTimeout(fermer, 150); });
    ta.addEventListener('keydown', function (e) {
      if (liste.hidden) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        actif = (actif + (e.key === 'ArrowDown' ? 1 : choix.length - 1)) % choix.length;
        afficher();
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        e.stopImmediatePropagation();
        inserer(choix[actif]);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        fermer();
      }
    });
    return { ouverte: function () { return !liste.hidden; } };
  }

  // --- Fichier glissé / collé / choisi ------------------------------------
  function initFichier(form) {
    var input = form.querySelector('[data-comment-file]');
    var puce = form.querySelector('[data-comment-file-chip]');
    if (!input || !puce) return;
    var urlApercu = null;

    function maj() {
      if (urlApercu) { URL.revokeObjectURL(urlApercu); urlApercu = null; }
      puce.innerHTML = '';
      var f = input.files && input.files[0];
      puce.hidden = !f;
      form.classList.toggle('has-file', !!f);
      if (!f) return;
      if (RE_IMAGE.test(f.name)) {
        urlApercu = URL.createObjectURL(f);
        var img = document.createElement('img');
        img.src = urlApercu;
        img.alt = '';
        puce.appendChild(img);
      }
      var nom = document.createElement('span');
      nom.textContent = f.name;
      puce.appendChild(nom);
      var x = document.createElement('button');
      x.type = 'button';
      x.className = 'comment-file-retirer';
      x.setAttribute('aria-label', 'Retirer le fichier');
      x.textContent = '×';
      x.addEventListener('click', function () { input.value = ''; maj(); });
      puce.appendChild(x);
    }

    function prendre(fichiers) {
      if (!fichiers || !fichiers.length) return false;
      try {
        var dt = new DataTransfer();
        dt.items.add(fichiers[0]);
        input.files = dt.files;
      } catch (e) {
        return false;
      }
      maj();
      return true;
    }

    input.addEventListener('change', maj);
    ['dragenter', 'dragover'].forEach(function (t) {
      form.addEventListener(t, function (e) {
        if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types, 'Files') === -1) return;
        e.preventDefault();
        form.classList.add('dragover');
      });
    });
    ['dragleave', 'dragend'].forEach(function (t) {
      form.addEventListener(t, function (e) {
        if (!form.contains(e.relatedTarget)) form.classList.remove('dragover');
      });
    });
    form.addEventListener('drop', function (e) {
      form.classList.remove('dragover');
      if (e.dataTransfer && e.dataTransfer.files.length) {
        e.preventDefault();
        prendre(e.dataTransfer.files);
      }
    });
    var ta = form.querySelector('textarea');
    if (ta) {
      ta.addEventListener('paste', function (e) {
        var files = e.clipboardData && e.clipboardData.files;
        if (files && files.length && prendre(files)) e.preventDefault();
      });
    }
  }

  function initForm(form) {
    if (form.dataset.commentInit) return;
    form.dataset.commentInit = '1';
    var ta = form.querySelector('textarea');
    if (!ta) return;
    var mentions = initMentions(ta);
    autoGrow(ta);
    ta.addEventListener('input', function () { autoGrow(ta); });
    ta.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' || e.shiftKey || e.isComposing || mentions.ouverte()) return;
      e.preventDefault();
      if (!ta.value.trim()) return;
      // Lot 13 : envoi par le bouton (il passe « occupé » pendant l'envoi).
      var envoi = form.querySelector('.comment-send');
      if (form.requestSubmit) form.requestSubmit(envoi || undefined); else form.submit();
    });
    form.addEventListener('submit', function () {
      // Envoi partiel (lot 13) : le bouton reste focalisable (aria-disabled,
      // posé par kairos-partiel.js) et la saisie reste en cas d'erreur.
      if (form.hasAttribute('data-partiel')) return;
      var b = form.querySelector('.comment-send');
      // Après la validation du navigateur : évite un double envoi.
      setTimeout(function () { if (b) b.disabled = true; }, 0);
    });
    initFichier(form);
  }

  // --- « Commenter » replié (lot 14) ---------------------------------------
  var ouverts = {};      // id du post -> champ déplié
  var brouillons = {};   // « p<post> » (champ du post) / « r<commentaire> » (réponse) -> texte
  function cleBrouillon(form) {
    if (!form || !form.hasAttribute('data-comment-composer')) return null;
    var m = /\/posts\/(\d+)\/commenter/.exec(form.getAttribute('action') || '');
    if (!m) return null;
    var parent = form.querySelector('input[name="parent_commentaire_id"]');
    return parent ? 'r' + parent.value : 'p' + m[1];
  }
  function zoneDe(postId) { return document.getElementById('post-' + postId + '-composer'); }
  function synchroniserBouton(postId) {
    var b = document.getElementById('post-' + postId + '-commenter');
    var z = zoneDe(postId);
    if (b) b.setAttribute('aria-expanded', z && !z.hasAttribute('data-replie') ? 'true' : 'false');
  }
  function ouvrirChamp(postId, focus) {
    var z = zoneDe(postId);
    if (!z) return;
    z.removeAttribute('data-replie');
    ouverts[postId] = true;
    synchroniserBouton(postId);
    var ta = z.querySelector('textarea');
    if (ta) {
      autoGrow(ta);
      if (focus) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
    }
  }
  function replierChamp(postId) {
    var z = zoneDe(postId);
    if (!z) return;
    z.setAttribute('data-replie', '');
    delete ouverts[postId];
    synchroniserBouton(postId);
  }
  function aUnBrouillon(z) {
    var ta = z.querySelector('textarea');
    var f = z.querySelector('input[type="file"]');
    return !!((ta && ta.value.trim()) || (f && f.files && f.files.length));
  }
  /** Fragment inséré : brouillons remis, champs dépliés gardés dépliés. */
  function retablir(racine) {
    var r = racine && racine.querySelectorAll ? racine : document;
    var zones = Array.prototype.slice.call(r.querySelectorAll('.post-commenter[id$="-composer"]'));
    if (r.matches && r.matches('.post-commenter')) zones.push(r);
    zones.forEach(function (z) {
      var id = z.id.replace(/^post-/, '').replace(/-composer$/, '');
      var ta = z.querySelector('textarea');
      var texte = brouillons['p' + id];
      if (ta && texte && !ta.value) { ta.value = texte; ouvrirChamp(id, false); }
      else if (ouverts[id]) ouvrirChamp(id, false);
      else if (!z.hasAttribute('data-replie')) ouverts[id] = true;
      synchroniserBouton(id);
    });
    Array.prototype.forEach.call(r.querySelectorAll('[data-reponse-a]'), function (bloc) {
      var texte = brouillons['r' + bloc.getAttribute('data-reponse-a')];
      var ta = bloc.querySelector('textarea');
      if (ta && texte && !ta.value) { ta.value = texte; bloc.hidden = false; autoGrow(ta); }
    });
  }
  document.addEventListener('input', function (e) {
    var ta = e.target;
    if (!ta || ta.tagName !== 'TEXTAREA') return;
    var cle = cleBrouillon(ta.form);
    if (!cle) return;
    if (ta.value.trim()) brouillons[cle] = ta.value; else delete brouillons[cle];
  });
  document.addEventListener('submit', function (e) {
    var cle = cleBrouillon(e.target);
    if (cle) delete brouillons[cle];
  }, true);

  // Idempotent (data-comment-init) : document au chargement, puis chaque
  // fragment inséré (lot 13, évènement kairos:fragment).
  function initForms(racine) {
    (racine && racine.querySelectorAll ? racine : document)
      .querySelectorAll('form[data-comment-composer], form[data-comment-edit]').forEach(initForm);
  }
  window.KairosCommentComposer = { init: initForms };

  function init() {
    initForms(document);
    retablir(document);
    document.addEventListener('kairos:fragment', function (e) {
      var racine = e.detail && e.detail.racine;
      initForms(racine);
      retablir(racine);
      // Lot 13 : commentaires plus anciens dépliés avant l'envoi : ils le
      // restent une fois le bloc des commentaires remplacé.
      var carte = racine && racine.closest ? racine.closest('.post-card') : null;
      if (carte && carte.dataset.commentairesDeplies === '1') {
        var det = carte.querySelector('details.post-comments-plus');
        if (det) det.open = true;
      }
    });
    document.addEventListener('submit', function (e) {
      var carte = e.target && e.target.closest ? e.target.closest('.post-card') : null;
      if (!carte || !e.target.hasAttribute('data-partiel')) return;
      var det = carte.querySelector('details.post-comments-plus');
      carte.dataset.commentairesDeplies = det && det.open ? '1' : '0';
    }, true);

    document.addEventListener('click', function (e) {
      // Lot 14 : « Commenter » déplie le champ (focus) ; replie un champ
      // vide ; avec un brouillon, le champ reste ouvert et reprend le focus.
      var com = e.target.closest('[data-commenter]');
      if (com) {
        var pid = com.getAttribute('data-commenter');
        var z = zoneDe(pid);
        if (!z) return;
        if (z.hasAttribute('data-replie')) ouvrirChamp(pid, true);
        else if (aUnBrouillon(z)) ouvrirChamp(pid, true);
        else replierChamp(pid);
        return;
      }
      var rep = e.target.closest('[data-repondre]');
      if (rep) {
        var carte = rep.closest('.post-card') || document;
        var bloc = carte.querySelector('[data-reponse-a="' + rep.getAttribute('data-repondre') + '"]');
        if (!bloc) return;
        bloc.hidden = false;
        var ta = bloc.querySelector('textarea');
        var mention = rep.getAttribute('data-mention');
        if (mention && ta.value.indexOf(mention.trim()) === -1) ta.value = mention + ta.value;
        ta.focus();
        ta.setSelectionRange(ta.value.length, ta.value.length);
        autoGrow(ta);
        return;
      }
      var mod = e.target.closest('[data-modifier]');
      if (mod) {
        var com = mod.closest('.post-comment');
        var form = com.querySelector('[data-comment-edit="' + mod.getAttribute('data-modifier') + '"]');
        com.querySelector('.post-comment-body').hidden = true;
        com.querySelector('.post-comment-meta').hidden = true;
        form.hidden = false;
        var t = form.querySelector('textarea');
        t.focus();
        t.setSelectionRange(t.value.length, t.value.length);
        autoGrow(t);
        return;
      }
      var ann = e.target.closest('[data-annuler-modif]');
      if (ann) {
        var f = ann.closest('form');
        var c = f.closest('.post-comment');
        f.hidden = true;
        f.reset();
        c.querySelector('.post-comment-body').hidden = false;
        c.querySelector('.post-comment-meta').hidden = false;
        // Lot 10 : le focus revient sur « Modifier » (il tombait sur <body>).
        var btnMod = c.querySelector('[data-modifier]');
        if (btnMod) btnMod.focus();
        return;
      }
      // Lot 10 (audit front I12) : renoncer à une suppression sans recharger.
      var annSup = e.target.closest('[data-annuler-suppression]');
      if (annSup) {
        var det = annSup.closest('details');
        det.open = false;
        var sum = det.querySelector('summary');
        if (sum) sum.focus();
      }
    });
    // Revue d'interaction P2-6 : Échap dans le champ de réponse le replie
    // (vide, ou seulement la mention posée d'office) et rend le focus à
    // « Répondre » ; avec une saisie, la même question que les fenêtres.
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      // Lot 14 : Échap dans le champ d'un post vide le replie, le focus
      // revient à « Commenter » ; avec un brouillon, rien ne se perd.
      var zc = e.target && e.target.tagName === 'TEXTAREA' && e.target.closest ? e.target.closest('.post-commenter[id$="-composer"]') : null;
      if (zc) {
        if (aUnBrouillon(zc)) return;
        e.preventDefault();
        var idc = zc.id.replace(/^post-/, '').replace(/-composer$/, '');
        replierChamp(idc);
        var bc = document.getElementById('post-' + idc + '-commenter');
        if (bc) bc.focus();
        return;
      }
      var ta = e.target;
      var bloc = ta && ta.tagName === 'TEXTAREA' && ta.closest ? ta.closest('[data-reponse-a]') : null;
      if (!bloc || bloc.hidden || (ta.closest('.comment-input') && ta.closest('.comment-input').querySelector('.mention-liste:not([hidden])'))) return;
      e.preventDefault();
      var carte = bloc.closest('.post-card') || document;
      var replier = function () {
        bloc.hidden = true;
        ta.value = '';
        var b = carte.querySelector('[data-repondre="' + bloc.getAttribute('data-reponse-a') + '"]');
        if (b) b.focus();
      };
      var reste = ta.value.replace(/^@\S+ \S+ /, '').trim();
      var K = window.Kairos;
      if (!reste) { replier(); return; }
      if (K && K.confirmer) {
        K.confirmer(ta, 'Abandonner les modifications\u00a0? La saisie sera perdue.', { libelleOk: 'Abandonner', libelleAnnuler: 'Continuer la saisie', danger: true })
          .then(function (oui) { if (oui) replier(); });
      }
    });
    // À l'ouverture de « Supprimer », le focus va sur « Oui, supprimer »
    // (l'évènement toggle ne remonte pas : écoute en capture).
    document.addEventListener('toggle', function (e) {
      var det = e.target;
      if (!det.classList || !det.classList.contains('post-comment-supprimer') || !det.open) return;
      var ok = det.querySelector('[data-confirmer-suppression]');
      if (ok) ok.focus();
    }, true);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

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
 *   remplace le commentaire par son champ d'édition.
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
    p.cle = p.complet.toLowerCase();
  });

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
    liste.hidden = true;
    wrap.appendChild(liste);
    var choix = [];
    var actif = 0;
    var debut = -1;

    function fermer() { liste.hidden = true; choix = []; debut = -1; }

    function requete() {
      var avant = ta.value.slice(0, ta.selectionStart);
      var m = /(^|\s)@([^\s@]{0,24}(?: [^\s@]{0,24})?)$/.exec(avant);
      if (!m) return null;
      return { debut: avant.length - m[2].length - 1, texte: m[2].toLowerCase() };
    }

    function afficher() {
      var r = requete();
      if (!r || !personnes.length) return fermer();
      choix = personnes.filter(function (p) {
        return !r.texte || p.cle.indexOf(r.texte) === 0 || p.nom.toLowerCase().indexOf(r.texte) === 0 ||
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
        b.textContent = p.complet;
        // mousedown (pas click) : garder le focus dans le champ.
        b.addEventListener('mousedown', function (e) { e.preventDefault(); inserer(p); });
        liste.appendChild(b);
      });
      liste.hidden = false;
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
      if (form.requestSubmit) form.requestSubmit(); else form.submit();
    });
    form.addEventListener('submit', function () {
      var b = form.querySelector('.comment-send');
      // Après la validation du navigateur : évite un double envoi.
      setTimeout(function () { if (b) b.disabled = true; }, 0);
    });
    initFichier(form);
  }

  function init() {
    document.querySelectorAll('form[data-comment-composer], form[data-comment-edit]').forEach(initForm);

    document.addEventListener('click', function (e) {
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
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

# Mises à jour partielles — mode d'emploi (lot 13)

Ce document s'adresse à qui convertit une interaction de Kairos au **socle
partiel** : plus de rechargement de toute la page quand on filtre ou qu'on
agit. Le socle est livré et prouvé sur deux pilotes de la page Utilisateurs
(filtres automatiques, interrupteur « Actif »). Lisez-les avant de
commencer : `app/templates/utilisateurs_liste.html`,
`app/templates/partials/utilisateur_ligne.html`,
`app/templates/partials/utilisateurs_resultats.html`, et dans
`app/routes/utilisateurs.py` les fonctions `liste()` et
`_toggle_actif_partiel()`.

Pièces du socle :

| Fichier | Rôle |
|---|---|
| `app/partiel.py` | contrat serveur : `est_partiel()`, `repondre()`, `refuser()`, `toast()`, `lire_flash()` |
| `app/static/js/kairos-partiel.js` | brique cliente (`window.Kairos`) : attributs `data-partiel*`, requête, toasts, confirmation, historique |
| `app/static/js/kairos-ui.js` | thème, copier, anti double envoi, « Voir comme », contrôle segmenté |
| `app/static/css/app.css`, section « Lot 13 » | jetons, toasts, `.k-en-cours`, squelettes, états vides, boutons, fenêtres |
| `app/paquets.py` | `commun.js` (scripts communs assemblés, dont celui-ci) et `app.css` sans commentaires, servis sous `/static/paquets/` |
| `tests_js/kairos-partiel.test.mjs` | algorithme de la requête (horloge et DOM simulés) |
| `tests_e2e/partiel.e2e.js` | critères d'acceptation de bout en bout (Playwright) |

## 1. Principe

1. Le formulaire ou le lien **existe déjà** et marche sans JavaScript
   (POST puis redirection, ou GET). On n'y touche pas : on **ajoute** des
   attributs.
2. Le navigateur envoie la même requête avec l'en-tête
   `X-Kairos-Partiel: #cible`.
3. La route reconnaît l'en-tête (`partiel.est_partiel()`) et renvoie un
   **fragment** (un gabarit partiel) au lieu de la redirection ; les
   messages passent en **toasts** (en-tête `X-Kairos-Toasts`).
4. La brique remplace `#cible` par le fragment, rend le focus, garde le
   défilement, met à jour l'adresse si demandé, affiche les toasts, puis
   émet `kairos:fragment` pour que les composants s'initialisent dans le
   nouveau contenu.

## 2. Convertir une action en 4 étapes

### Étape 1 — Extraire le fragment

Le morceau à remplacer devient un gabarit `partials/<nom>.html`, inclus
par la page **et** rendu seul par la route. Il porte l'`id` de la cible
sur son élément racine (règle : la réponse remplace la cible, son élément
racine doit donc avoir le même id).

```jinja
{# partials/utilisateur_ligne.html #}
<div class="urow" role="row" id="u-{{ u.id }}"> … </div>
```

Tout ce dont le fragment a besoin doit être passé par la route (une
variable posée par `{% set %}` dans la page ne l'est pas quand le fragment
est rendu seul : voir `peut_gerer` dans le pilote).

**Hors cible** (compteur dans la sous-barre, badge…) : un élément du
fragment marqué `data-partiel-oob` remplace son homonyme (même `id`)
ailleurs dans la page. Une région live (`role="status"`, `aria-live`)
n'est pas remplacée : son texte est mis à jour, pour être annoncé.

```jinja
<span id="utilisateurs-compte" role="status"{% if oob_compte %} data-partiel-oob{% endif %}>…</span>
```

### Étape 2 — Ajouter le chemin partiel à la route

En tête de réponse, **sans toucher au reste** (le repli PRG reste) :

```python
from .. import partiel

@bp.route("/<int:user_id>/toggle-actif", methods=["POST"])
def toggle_actif(user_id):
    ...                                    # logique existante, flash() compris
    if partiel.est_partiel():
        return _toggle_actif_partiel(...)  # fragment + toasts
    return redirect(url_for(...))          # inchangé
```

Fonctions de `app/partiel.py` :

| Appel | Réponse |
|---|---|
| `partiel.repondre("partials/x.html", toasts=[...], **contexte)` | 200, fragment ; les `flash()` en attente partent en toasts |
| `partiel.repondre(..., statut=422)` | fragment re-rendu avec les champs en erreur (`aria-invalid="true"` : le focus y va) |
| `partiel.refuser("message", 403 \| 409 \| 400)` | JSON `{"erreur", "message"}` ; l'état optimiste est annulé, le message affiché |
| `partiel.toast("texte", "succes" \| "erreur" \| "avertissement" \| "info", action=...)` | un toast ; `action` = bouton du toast (voir § 4) |
| `partiel.lire_flash()` | les `flash()` en attente, **une seule fois** par requête (Flask garde la liste en cache : ne pas appeler `get_flashed_messages()` puis `repondre()`, les messages sortiraient en double) |
| `partiel.refuser("message", 422, champs={"titre": "…"})` | JSON `{erreur, message, champs}` : la saisie reste, chaque champ nommé est signalé dans le formulaire envoyé (`aria-invalid`, message relié par `aria-describedby`, focus sur le premier — audit a11y I5) ; sans champ reconnu, toast |
| `partiel.rien(toasts=[...])` | 204 : rien à remplacer, seulement des toasts |

Déjà gérés pour toute requête partielle, sans rien écrire :

- une route **non convertie** qui redirige → 204 + `X-Kairos-Redirection` :
  le navigateur fait une vraie navigation, les `flash()` restent pour la
  page d'arrivée ;
- session absente ou expirée (redirection vers la connexion, jeton CSRF
  refusé sans session) → **401** + `X-Kairos-Connexion` : fenêtre « Session
  expirée — Se reconnecter », la saisie reste dans la page ;
- page d'erreur (`abort(404)`…) et refus « Voir comme » → JSON avec le
  message ;
- jeton CSRF refusé (session présente) → 400 JSON.

### Étape 3 — Ajouter les attributs

| Attribut | Sur | Effet |
|---|---|---|
| `data-partiel="#cible"` | `<form>`, `<a>`, bouton d'envoi | intercepte, envoie avec `X-Kairos-Partiel`, remplace `#cible` |
| `data-partiel-mode` | idem | `outer` (défaut), `inner` (contenu de la cible), `avant` (au début de la cible), `apres` (à la fin), `retirer` |
| `data-partiel-historique` | idem | `push` (défaut d'un GET), `replace`, `aucun` (défaut d'un POST) |
| `data-partiel-auto="input:250 change"` | `<form method="get">` | envoi automatique : frappe avec délai (ms), listes et cases au changement. Une rafale de frappe = une seule entrée d'historique |
| `data-optimiste="bascule"` | formulaire ou bouton | état appliqué à t = 0, annulé si la réponse n'est pas 2xx. `bascule` (fourni) inverse `aria-checked` / `aria-pressed` |
| `data-confirmer="Supprimer ce commentaire ?"` | bouton, lien | confirmation **en ligne** (jamais `confirm()`) ; `data-confirmer-ok="Supprimer"`, `data-confirmer-danger` |
| `data-focus-apres="#sel"` | idem | focus après remplacement (sinon : l'élément de même `id` que celui qui avait le focus, sinon `[data-partiel-titre]` du fragment, sinon sa racine) |
| `data-partiel-defiler="haut"` | lien, formulaire | pagination : le haut de la cible revient à l'écran (au lieu de compenser le défilement) |
| `data-partiel-oob="avant"` | élément du fragment | ses enfants absents de la page (même `id`) sont insérés **en tête** du conteneur homonyme, surlignés (`.k-nouveau`) — nouveaux posts du fil |
| `data-partiel-vide` | élément d'une liste | état vide retiré quand la liste reçoit ses premiers éléments (modes `avant`, `apres`, `oob="avant"`) |

Exemple (pilote, interrupteur) :

```html
<form method="post" action="/utilisateurs/40/toggle-actif" data-partiel="#u-40" data-optimiste="bascule">
  …champs cachés existants…
  <button type="submit" id="actif-40" class="toggle toggle-liste" role="switch" aria-checked="false" …>
```

Exemple (pilote, filtres) — le bouton « Filtrer » reste pour le repli
sans JavaScript, masqué sinon par `.k-sans-js` :

```html
<form method="get" action="/utilisateurs" data-partiel="#utilisateurs-resultats" data-partiel-auto="input:250 change">
  <input type="search" id="filtre-utilisateurs-q" name="q" …>
  <select name="role">…</select>
  <button type="submit" class="btn-secondary k-sans-js">Filtrer</button>
</form>
```

**Ids stables** : donnez un `id` aux contrôles qui peuvent avoir le focus
dans la cible (`actif-40`), pour que le focus leur revienne après le
remplacement.

### Étape 4 — Tester

1. **Unitaire** (`tests/`, client Flask, mocks comme `test_smoke.py`) :
   avec l'en-tête `X-Kairos-Partiel`, la réponse est le fragment seul
   (pas de `<html>`), les toasts sont dans l'en-tête (`json.loads(unquote(...))`),
   les refus sont en JSON avec le bon statut et **aucun** `flash()` ne
   reste en session ; sans l'en-tête, la redirection est inchangée. Voir
   `TestPiloteUtilisateurs` dans `tests/test_lot13_front.py`.
2. **Navigateur** : ajoutez des étapes à `tests_e2e/partiel.e2e.js` (ou un
   scénario de la page) avec les critères ci-dessous ; lancement :
   `KAIROS_E2E_SCENARIO=partiel KAIROS_E2E_PORT=<port libre> bash tests_e2e/lancer.sh`.

Critères d'acceptation (audit UX §4.8), déjà outillés dans le scénario
(`instrumenter()`, `etat()`, `latence()`) :

- aucune navigation de document (marqueur `window.__marque` intact) ;
- |Δ défilement| ≤ 40 px (sauf pagination : haut du tableau visible) ;
- focus jamais sur `<body>` après l'action ;
- avec 800 ms de latence : première mutation ≤ 100 ms (optimiste), sinon
  `aria-busy` visible après 150 ms ;
- Retour du navigateur = état précédent, sans rechargement ;
- `prefers-reduced-motion` : aucune animation > 1 ms ;
- 1440 / 1024 / 768 / 375 px, clair et sombre : ni débordement horizontal
  ni chevauchement ;
- « Voir comme » : aucune commande d'écriture active ;
- aucune erreur JavaScript ni boîte native (`page.on('dialog')`).

## 3. Ce que fait la brique à chaque requête

1. Annule la requête précédente sur la même cible (`AbortController`).
2. Mémorise le focus (`id` ou `data-cle`) et la position de la cible.
3. Applique l'optimiste éventuel ; le déclencheur passe en
   `aria-disabled="true"` (jamais `disabled` : il garderait mal le focus).
4. Après **150 ms** sans réponse : `aria-busy="true"` et `.k-en-cours`
   sur la cible (contenu atténué, barre de 2 px) ; affiché au moins
   **300 ms**.
5. Réponse : toasts de l'en-tête, puis selon le statut —
   2xx : remplacement (View Transition si disponible et sans mouvement
   réduit ; fondu de 120 ms pour les filtres), défilement compensé, focus
   rendu, historique, `kairos:fragment` ;
   422 : remplacement et focus sur le premier `[aria-invalid=true]` ;
   401 : fenêtre « Session expirée » ;
   403 / 409 / 4xx : annulation de l'optimiste + toast d'erreur ;
   5xx ou réseau : idem, avec « Réessayer ».

Appel direct possible : `Kairos.requete({ url, methode, corps, cible, mode,
historique, optimiste, declencheur, focusApres })` (renvoie une promesse
`{ statut, racine }`).

## 4. Toasts

- Côté serveur : `partiel.toast(...)` dans `repondre(toasts=[...])`, ou
  simplement `flash()` (converti). Au chargement complet d'une page, les
  `flash()` arrivent dans la même zone (`#k-toasts`).
- Côté client : `Kairos.toast("Texte", { type: "erreur" })`.
- Succès et info : 5 s (10 s avec une action), suspendus au survol et au
  focus ; erreur et avertissement : jusqu'à fermeture ; 3 au plus.
- **Au-dessus des fenêtres** : `#k-toasts` est un `popover="manual"`
  (couche supérieure). Quand une fenêtre est ouverte en `showModal()`
  (feuille de tâche, Nouveau post, Informations, aide « ? »…), la zone est
  déplacée dans cette fenêtre (le reste de la page est inerte) puis
  remise au premier plan ; elle revient dans `<body>` à la fermeture.
  Rien à faire côté composant : `Kairos.toast` s'en charge.
- **Annonces** : le toast visuel n'est pas une région live. Son texte est
  écrit dans une des deux régions **persistantes**, déclarées vides au
  chargement dans `base.html` : `#k-annonce` (`role=status`) ou
  `#k-alerte` (`role=alert`, erreurs). Avec une action, l'annonce dit
  comment l'atteindre (« « Annuler » : Ctrl+Z. »). Option
  `annonce: "…"` pour lire un autre texte que celui affiché.
- **Ctrl/⌘ + Z** (hors d'un champ de saisie) déclenche le bouton
  « Annuler… » du toast le plus récent encore affiché
  (`Kairos.annulerDernier()`), documenté dans l'aide « ? ».

### Annoncer sans toast : `Kairos.annoncer`

```js
Kairos.annoncer('Tâche 3 sur 12 : Plans de ferraillage');   // poli (#k-annonce)
Kairos.annoncer('Enregistrement impossible.', { urgent: true }); // #k-alerte
```

Pour tout changement visible que le lecteur d'écran ne saurait pas
autrement (Daily log : « Journée enregistrée », « Copié depuis… » ;
panneau de tâche : changement de tâche par ↑ / ↓). La région est vidée
puis remplie 30 ms plus tard (un même texte répété est relu) ; les appels
d'une même rafale sont lus ensemble ; elle se vide seule après 10 s. Ne
pas créer de nouvelle région live remplie d'avance : elle n'est pas lue
par NVDA ni JAWS avec Chrome.
- **Action** (« Annuler ») : décrite par le serveur et rejouée en requête
  partielle :

```python
action = {"libelle": "Annuler", "url": url_for("utilisateurs.toggle_actif", user_id=uid),
          "methode": "POST", "donnees": {"actif_cible": "1", "annulation": "1"},
          "cible": f"#u-{uid}", "focus": f"#actif-{uid}"}
partiel.repondre("partials/utilisateur_ligne.html", toasts=[partiel.toast(texte, action=action)], …)
```

Le jeton CSRF est ajouté automatiquement (en-tête `X-CSRFToken`,
`kairos-amorce.js`). L'annulation ne propose pas d'annuler l'annulation
(champ `annulation`).

## 5. Composants : ré-initialisation sur un fragment

Tout composant qui s'attache à des éléments du DOM doit être **idempotent
sur une racine** et écouter `kairos:fragment` :

```js
function init(racine) {
  (racine && racine.querySelectorAll ? racine : document)
    .querySelectorAll('[data-mon-composant]').forEach(function (el) {
      if (el.dataset.monComposantInit) return;   // idempotent
      el.dataset.monComposantInit = '1';
      …
    });
}
document.addEventListener('kairos:fragment', function (e) { init(e.detail && e.detail.racine); });
```

Déjà faits : `chip-select.js` (`KairosChipSelect.init`), `search-combobox.js`
(`KairosSearchCombobox.init`), `comment-composer.js`
(`KairosCommentComposer.init`), `dropzone.js` (`KairosDropzone.init`),
`projet-intervenants.js`, la lecture seule et le contrôle segmenté
(`kairos-ui.js`). Les déclencheurs de fenêtres (`data-open-post-dialog`,
`data-open-projet-dialog`, `data-open-informations-dialog`) et la fenêtre
de tâche sont délégués au document : rien à faire. Contenu inséré à la
main (`innerHTML`) : appeler `Kairos.initialiser(racine)`.

Pour un écouteur global (clic hors d'un composant…), préférez **une seule**
écoute du document à une écoute par élément : les éléments remplacés ne
laissent alors rien derrière (voir `search-combobox.js`).

## 6. Règles

- **Jamais de script en ligne** dans un gabarit : la CSP est
  `script-src 'self'` (test de garde dans `tests/test_lot13_front.py`). Les
  données passent par `data-*` ou `<script type="application/json">`.
- **Lecture seule (« Voir comme »)** : `<html data-lecture-seule>` ; tout
  formulaire POST est désactivé et son envoi refusé côté client, sauf ceux
  marqués `data-permis-lecture` (déconnexion, « Revenir à mon compte »,
  date simulée). Le serveur refuse de toute façon (403 JSON).
- **Pas de couleur en dur** : pastilles par classe (`pill pill-bleu`…,
  `utils.*_style()["classe"]`), couleurs par jetons (`--etat-*`,
  `--surface`…), ombres `--ombre-1/2/3`, durées `--duree-*` (mouvement
  réduit : 1 ms).
- **Boutons** : `.btn` (secondaire), `.btn-primaire`, `.btn-fantome`,
  `.btn-petit` ; occupé : `aria-busy="true"` (roue), indisponible :
  `aria-disabled="true"`.
- **États vides** : `.k-vide` (icône, `.k-vide-titre`, `.k-vide-texte`,
  une action). **Premier chargement à la demande** : squelettes
  `.k-squelette` ; un rafraîchissement garde l'ancien contenu atténué.
- **Navigation voulue** (ouvrir une fiche, « Agir comme ») : rester une
  vraie navigation ; la barre de progression s'affiche seule.
- **Script commun à toutes les pages** : l'ajouter à `PAQUETS["commun.js"]`
  (`app/paquets.py`, dans l'ordre d'exécution voulu) et non en
  `<script>` dans `base.html` ; un script propre à une page reste dans son
  gabarit. On édite toujours les sources de `app/static/`.

## 7. Conversions faites en phase 2 (lot 13, parties C et D)

Exemples à suivre pour une page à plusieurs fragments :

- **Fiche projet** (`routes/projets.py`) : `_contexte_fiche(projet)` calcule
  le contexte de la page ET des fragments ; `_maj_fiche(projet_id, racine,
  parties)` rend `partials/fiche_maj.html` : le fragment de la cible, puis
  les fragments hors cible (`oob=True` dans le gabarit : ligne ou carte des
  tâches, compteur, état du projet, carte Intervenants, nouveaux posts du
  fil). `_reponse_tache()` choisit la racine selon la cible demandée
  (`#tache-fenetre-<id>` : panneau, `#tache-ligne-<id>` : ligne). Un
  fragment inclus dans un autre est rendu avec `oob=false`.
- **Panneau de tâche** (`tache-dialog.js`) : optimistes `etat-tache`,
  `titre-tache`, `rejoindre` (`Kairos.optimistes`) ; actions de toast
  « Annuler » rejouées sur la ligne (`#tache-ligne-<id>`, toujours présente) ;
  pièce jointe par `XMLHttpRequest` (progression), réponse appliquée par
  `Kairos.remplacer` + `Kairos.initialiser`.
- **Fil** (`routes/posts.py`) : bloc des commentaires d'un post
  (`#post-<id>-commentaires`), réaction en JSON, publication insérée en tête
  du fil de la page (`reponse_publication`, cible `#fil-liste` ou
  `#fil-posts`, mode `avant`).
- **Tous les projets** : formulaire GET `data-partiel-auto`, pagination
  `data-partiel-defiler="haut"`, statut et lien d'export hors cible.

Partie D :

- **Deadlines** (`routes/deadlines.py`, `partials/deadlines_contenu.html`) :
  bascule « Mes projets / Tous » (liens `data-partiel`, contrôle segmenté
  synchronisé par `deadlines.js` sur l'adresse) et filtres Chef / Équipe
  (`data-partiel-auto="change"`), compteur hors cible ; filtre texte en
  `replaceState ?q=`. Sous 600 px, liste groupée par semaine.
- **Notifications** (`routes/notifications.py`, `notifications.js`) :
  aperçu de la cloche chargé à la demande (cible `#notifs-apercu`) ;
  optimistes `notif-lue` et `notifs-toutes-lues` ; badge tenu à jour par
  l'élément hors cible `#notifs-nb` (`partials/notifs_nb.html`) et par
  `GET /notifications/compte` (JSON). Ouvrir une notification reste une
  vraie navigation (POST).
- **Journal d'audit** (`routes/admin.py`) : filtres automatiques
  (`#journal-resultats`) ; « Charger 100 de plus » en mode `apres` sur le
  `<table>` (des `<tbody>` par jour), suite et compteur hors cible ; curseur
  `avant=<created_at>_<id>` ; données d'une entrée chargées au dépliage
  (`GET /admin/journal/<id>`, mode `inner`).
- **Utilisateurs** (`routes/utilisateurs.py`) : fiche, création, « Mes
  informations », mot de passe : 422 + fragment re-rendu avec les erreurs
  sous les champs (macros `partials/champs.html` : `attrs()` pose
  `aria-invalid`, `aria-describedby`, `autofocus` sur la 1re erreur ;
  `message()`) ; création réussie = redirection (navigation voulue, toast à
  l'arrivée). Interrupteur « Compte actif » de la fiche : même route que la
  liste avec `retour=fiche`. Profil : « Voir la semaine précédente » en lien
  `data-partiel` (`#profil-activite`).
- **Daily log** (`dailylog.js`, API JSON inchangée) : boutons en
  `aria-disabled` pendant l'envoi (focus gardé), toasts du socle (un
  message à la fois, actions ajoutées au toast), `Kairos.confirmer` pour
  « Vider la journée », lecture seule en « Voir comme ».
- Socle : en mode `apres` / `avant`, le repère de défilement est la cible ;
  le premier `pushState` partiel d'une page marque d'abord l'entrée de
  départ (Retour y revient en partiel).

Correctifs après contre-expertise (F3) :

- **Deadlines** : une barre (ou une ligne de la liste du téléphone, ou une
  tâche sans échéance) ouvre le panneau de tâche sur place —
  `tache-dialog.js` réutilisé : adresse du panneau portée par la ligne
  (`data-tache-url`), lignes voisines (`data-lignes`), `?tache=` lu dans
  l'adresse (`data-ouvrir-param`), contenu rafraîchi après chaque action
  (`data-rafraichir`) ; « Annuler » d'un toast, qui vise la ligne du
  tableau de la fiche, est rejoué sur le panneau ou dans un réceptacle
  caché quand cette ligne n'existe pas.
- **« Daily log de »** (chef, Admin) : champ à recherche ; le choix charge
  la page de la personne en fragment (`#dl9`, `partials/dailylog_page.html`,
  amorce JSON comprise), `dailylog.js` redémarre sur `kairos:fragment`
  (écouteurs du document arrêtés par `AbortController`) ; Retour revient.
- **Cloche de la barre basse** (téléphone) : même aperçu, en feuille au-dessus
  de la barre basse.
- **Date simulée** « Appliquer » / « Revenir à aujourd'hui » : rechargement
  gardé (toute la page dépend de la date : contenus, retards, Daily log,
  empreinte du mode `kairos-mode`) ; barre de progression, toast à
  l'arrivée, focus rendu au champ de date.
- **Supprimer un commentaire** : pas d'« Annuler » (suppression définitive
  côté serveur, réponses et fichiers compris) ; confirmation en ligne
  gardée.

Reste : retrait de `'unsafe-inline'` de `style-src` (environ 320 `style=""`
restants, surtout fiche projet, fil, accueil, et le `@font-face` en ligne de
`base.html`).

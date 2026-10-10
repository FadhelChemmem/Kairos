"""Typographie française de l'interface (revue produit P1-16, § 3) : espace
insécable avant « : » (U+00A0) et espace fine insécable avant « ; ? ! »
(U+202F), espaces insécables à l'intérieur des guillemets « », apostrophe
typographique ’ dans les textes affichés. Test anti-régression sur :

- les gabarits Jinja (textes affichés et attributs lus : title, aria-label,
  placeholder, alt, data-confirmer…), commentaires, balises et expressions
  Jinja retirés ;
- les chaînes des scripts (static/js) et des routes Python (messages
  flash, toasts, textes du Daily log), commentaires et docstrings exclus.

Une espace normale (U+0020) avant « : ; ? ! » est une faute : au retour à
la ligne, la ponctuation part seule au début de la ligne suivante.
"""
import ast
import html.parser
import io
import pathlib
import re
import tokenize
import unittest

RACINE = pathlib.Path(__file__).resolve().parent.parent
APP = RACINE / "app"

# Ponctuation haute précédée d'une espace sécable, suivie d'une fin de mot.
ESPACE_SECABLE = re.compile(r"(?:^|\S)( )[:;?!](?=\s|$|[»\"'’)<])")
# Guillemets français sans espace insécable à l'intérieur.
GUILLEMETS = re.compile(r"«(?![  ])|(?<![  ])»")
# Apostrophe droite entre deux lettres (l'information, d'activité).
APOSTROPHE = re.compile(r"[A-Za-zÀ-ÿœ]'[A-Za-zÀ-ÿœ]")

ATTRIBUTS_LUS = {"title", "aria-label", "placeholder", "alt", "data-confirmer", "data-confirmer-ok",
                 "data-filtre-message", "data-search-placeholder", "data-search-vide", "data-vide",
                 "data-parent-label", "data-projet-label", "aria-description"}
BALISES_IGNOREES = {"script", "style", "code", "pre", "kbd"}


def _sans_jinja(texte: str) -> str:
    texte = re.sub(r"\{#.*?#\}", "", texte, flags=re.S)
    texte = re.sub(r"\{%-?.*?-?%\}", "", texte, flags=re.S)
    # Une expression devient un mot neutre (« Lot{{ s }} : » reste détecté).
    return re.sub(r"\{\{.*?\}\}", "X", texte, flags=re.S)


class _Lecteur(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.textes, self.pile = [], []

    def handle_starttag(self, tag, attrs):
        if tag in BALISES_IGNOREES:
            self.pile.append(tag)
        for nom, valeur in attrs:
            if nom in ATTRIBUTS_LUS and valeur:
                self.textes.append((self.getpos()[0], valeur, True))

    def handle_endtag(self, tag):
        if self.pile and self.pile[-1] == tag:
            self.pile.pop()

    def handle_data(self, data):
        if not self.pile and data.strip():
            self.textes.append((self.getpos()[0], data, False))


def textes_gabarit(chemin: pathlib.Path):
    lecteur = _Lecteur()
    lecteur.feed(_sans_jinja(chemin.read_text(encoding="utf-8")))
    lecteur.close()
    return lecteur.textes


_LITTERAL_JS = re.compile(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|`(?:[^`\\]|\\.)*`", re.S)


def chaines_js(chemin: pathlib.Path):
    """Littéraux de chaîne des lignes de code (commentaires de ligne et de
    bloc retirés), échappements \\uXXXX décodés."""
    texte = chemin.read_text(encoding="utf-8")
    texte = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group().count("\n"), texte, flags=re.S)
    for num, ligne in enumerate(texte.split("\n"), 1):
        code = re.sub(r"^\s*//.*$", "", ligne)
        for m in _LITTERAL_JS.finditer(code):
            brut = m.group()[1:-1]
            brut = re.sub(r"\$\{[^}]*\}", "X", brut)
            brut = re.sub(r"\\u([0-9a-fA-F]{4})", lambda u: chr(int(u.group(1), 16)), brut)
            yield num, brut.replace("\\'", "'").replace('\\"', '"')


def chaines_python(chemin: pathlib.Path):
    """Constantes de chaîne d'un module Python, docstrings exclues."""
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    docstrings = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and noeud.body:
            premier = noeud.body[0]
            if isinstance(premier, ast.Expr) and isinstance(premier.value, ast.Constant):
                docstrings.add(id(premier.value))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str) and id(noeud) not in docstrings:
            yield noeud.lineno, noeud.value


def _est_du_francais(texte: str) -> bool:
    """Phrase lue par une personne : au moins deux mots en lettres (écarte
    sélecteurs CSS, SQL, formats, expressions) ; les messages du journal
    technique (« %s ») ne sont pas affichés."""
    return (len(re.findall(r"[A-Za-zÀ-ÿœ]{2,}", texte)) >= 2
            and not re.search(r"\b(SELECT|INSERT|UPDATE|WHERE|FROM)\b", texte)
            and "%s" not in texte and "%(" not in texte)


_LITTERAL_JINJA = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")


def chaines_jinja(chemin: pathlib.Path):
    """Chaînes écrites dans les balises et expressions Jinja ({% set %},
    {{ … if … else … }}) : elles aussi finissent à l'écran."""
    texte = re.sub(r"\{#.*?#\}", lambda m: "\n" * m.group().count("\n"), chemin.read_text(encoding="utf-8"), flags=re.S)
    for m in re.finditer(r"\{%.*?%\}|\{\{.*?\}\}", texte, flags=re.S):
        ligne = texte.count("\n", 0, m.start()) + 1
        for lit in _LITTERAL_JINJA.finditer(m.group()):
            yield ligne, lit.group()[1:-1].replace("\\'", "'")


def fautes(texte: str, apostrophes: bool = True) -> list[str]:
    trouve = []
    if ESPACE_SECABLE.search(texte):
        trouve.append("espace sécable avant : ; ? !")
    if GUILLEMETS.search(texte):
        trouve.append("guillemets sans espace insécable")
    if apostrophes and APOSTROPHE.search(texte):
        trouve.append("apostrophe droite")
    return trouve


def relevé() -> list[str]:
    erreurs = []
    for chemin in sorted((APP / "templates").rglob("*.html")):
        for ligne, texte, _attr in textes_gabarit(chemin):
            for f in fautes(texte):
                erreurs.append(f"{chemin.relative_to(RACINE)}:{ligne} {f} : {texte.strip()[:80]!r}")
        for ligne, texte in chaines_jinja(chemin):
            if _est_du_francais(texte) and " " in texte.strip():
                for f in fautes(texte):
                    erreurs.append(f"{chemin.relative_to(RACINE)}:{ligne} {f} (Jinja) : {texte.strip()[:80]!r}")
    for chemin in sorted((APP / "static" / "js").glob("*.js")):
        for ligne, texte in chaines_js(chemin):
            if _est_du_francais(texte):
                for f in fautes(texte):
                    erreurs.append(f"{chemin.relative_to(RACINE)}:{ligne} {f} : {texte.strip()[:80]!r}")
    for chemin in sorted((APP / "routes").glob("*.py")) + [APP / "auth.py", APP / "modes_admin.py", APP / "partiel.py",
                                                           APP / "validation.py", APP / "utils.py"]:
        for ligne, texte in chaines_python(chemin):
            if _est_du_francais(texte):
                for f in fautes(texte):
                    erreurs.append(f"{chemin.relative_to(RACINE)}:{ligne} {f} : {texte.strip()[:80]!r}")
    return erreurs


class TestTypographieFrancaise(unittest.TestCase):
    def test_detecteur(self):
        self.assertTrue(fautes("Mot de passe oublié ?"))
        self.assertTrue(fautes("Compte actif : X"))
        self.assertTrue(fautes("Fil d'activité"))
        self.assertTrue(fautes("« Annuler »"))
        self.assertFalse(fautes("Mot de passe oublié ?"))
        self.assertFalse(fautes("Compte actif : X"))
        self.assertFalse(fautes("Fil d’activité"))
        self.assertFalse(fautes("« Annuler »"))
        self.assertFalse(fautes("14:30 · https://exemple.test"))
        self.assertEqual(textes_gabarit_chaine('<p title="Rendu : {{ x }}">a{{ y }} : b</p>'), 2)

    def test_interface_sans_faute_de_typographie(self):
        erreurs = relevé()
        self.assertEqual(erreurs, [], "\n" + "\n".join(erreurs[:60]))

    def test_aucun_marqueur_de_conflit_git(self):
        """Revue visuelle P0-1 : une ligne « ======= » oubliée dans app.css
        rendait invalide la règle suivante (.k-page sans marge)."""
        marqueur = re.compile(r"^(<{7}|={7}|>{7})( |$)", re.M)
        for chemin in list((APP / "static").rglob("*.css")) + list((APP / "static").rglob("*.js")) + list((APP / "templates").rglob("*.html")):
            self.assertIsNone(marqueur.search(chemin.read_text(encoding="utf-8")), str(chemin))


def textes_gabarit_chaine(source: str) -> int:
    lecteur = _Lecteur()
    lecteur.feed(_sans_jinja(source))
    return sum(1 for _l, t, _a in lecteur.textes if fautes(t))


if __name__ == "__main__":
    for e in relevé():
        print(e)

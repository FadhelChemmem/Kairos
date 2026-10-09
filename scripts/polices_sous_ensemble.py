"""Régénère les polices de app/static/fonts (lot 13, audit a11y-perf R5).

Usage (poste de développement, hors du serveur) :
    pip install fonttools brotli
    python scripts/polices_sous_ensemble.py <dossier des webfonts Plus Jakarta Sans>

Le dossier source est celui du projet d'origine (PlusJakartaSans-Regular,
-SemiBold, -Bold .woff2 ; licence OFL, app/static/fonts/OFL.txt). Sortie :
plus-jakarta-sans-{400,600,700}.woff2, sous-ensemble latin + latin étendu A
+ ponctuation générale, et l'espace fine insécable U+202F (absente de la
police, produite par Intl / toLocaleString en français et « oublié ? ») qui
reprend le dessin de l'espace fine U+2009.
"""
import pathlib
import sys

from fontTools import subset
from fontTools.ttLib import TTFont

GRAISSES = {400: "Regular", 600: "SemiBold", 700: "Bold"}
UNICODES = (
    set(range(0x20, 0x7F)) | set(range(0xA0, 0x180)) | set(range(0x300, 0x370)) | set(range(0x2000, 0x2070))
    | {0x131, 0x152, 0x153, 0x2BB, 0x2BC, 0x2C6, 0x2DA, 0x2DC, 0x20AC, 0x2122, 0x2190, 0x2191, 0x2192, 0x2193,
       0x2212, 0x2215, 0xFEFF, 0xFFFD, 0x202F}
)
FONCTIONS = ["calt", "case", "ccmp", "liga", "locl", "pnum", "tnum", "kern", "mark", "mkmk"]
SORTIE = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "fonts"


def main(source: pathlib.Path) -> None:
    for graisse, nom in GRAISSES.items():
        police = TTFont(source / f"PlusJakartaSans-{nom}.woff2")
        for table in police["cmap"].tables:
            if table.isUnicode() and 0x2009 in table.cmap:
                table.cmap[0x202F] = table.cmap[0x2009]
        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = FONCTIONS
        options.name_IDs = ["*"]
        options.notdef_outline = True
        decoupe = subset.Subsetter(options)
        decoupe.populate(unicodes=UNICODES)
        decoupe.subset(police)
        police.flavor = "woff2"
        cible = SORTIE / f"plus-jakarta-sans-{graisse}.woff2"
        police.save(cible)
        print(cible, cible.stat().st_size, "octets")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(pathlib.Path(sys.argv[1]))

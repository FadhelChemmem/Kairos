"""Motif LIKE littéral (audit données lot 10) : « _ » ou « % » tapés dans
une recherche ne doivent pas tout renvoyer. Antislash = caractère
d'échappement par défaut de LIKE/ILIKE sous PostgreSQL."""


def motif_contient(texte: str) -> str:
    t = (texte or "").strip().lower()
    t = t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{t}%"


def motif_recherche(texte: str) -> str:
    """Motif d'une recherche libre (lot 11) : littéral comme motif_contient,
    espaces multiples réduits à un seul (« Fadhel  Chemmem »). À comparer
    avec fn_recherche() DES DEUX CÔTÉS du LIKE (accents et casse ignorés,
    migration 0016) : `fn_recherche(colonne) LIKE fn_recherche(%s)`."""
    return motif_contient(" ".join((texte or "").split()))

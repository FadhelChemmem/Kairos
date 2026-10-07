"""Motif LIKE littéral (audit données lot 10) : « _ » ou « % » tapés dans
une recherche ne doivent pas tout renvoyer. Antislash = caractère
d'échappement par défaut de LIKE/ILIKE sous PostgreSQL."""


def motif_contient(texte: str) -> str:
    t = (texte or "").strip().lower()
    t = t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{t}%"

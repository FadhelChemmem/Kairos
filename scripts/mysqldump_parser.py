"""Parseur générique et réutilisable pour un mysqldump (format --extended-insert par défaut).
Aucune dépendance externe, aucune connexion réseau/DB nécessaire : lit le .sql tel quel.
"""
import re

def _split_columns(create_body):
    cols = []
    for line in create_body.split('\n'):
        line = line.strip().rstrip(',')
        m = re.match(r'`(\w+)`\s+', line)
        if m and not line.upper().startswith(('PRIMARY KEY', 'UNIQUE KEY', 'KEY ', 'CONSTRAINT')):
            cols.append(m.group(1))
    return cols

def parse_create_tables(sql_text):
    """Retourne {table_name: [colonnes dans l'ordre]}"""
    tables = {}
    for m in re.finditer(r'CREATE TABLE `(\w+)` \((.*?)\n\) ENGINE=', sql_text, re.DOTALL):
        name = m.group(1)
        tables[name] = _split_columns(m.group(2))
    return tables

def _tokenize_values(values_str):
    """Découpe le contenu entre parenthèses d'UN tuple VALUES(...) en valeurs Python
    (str / None / int / float), en gérant les guillemets simples échappés (backslash)."""
    vals = []
    i = 0
    n = len(values_str)
    while i < n:
        c = values_str[i]
        if c == ' ' or c == ',':
            i += 1
            continue
        if c == "'":
            j = i + 1
            buf = []
            while j < n:
                if values_str[j] == '\\' and j + 1 < n:
                    nxt = values_str[j+1]
                    mapping = {'n': '\n', 'r': '\r', 't': '\t', '0': '\0', 'Z': '\x1a',
                               "'": "'", '"': '"', '\\': '\\'}
                    buf.append(mapping.get(nxt, nxt))
                    j += 2
                    continue
                if values_str[j] == "'":
                    if j + 1 < n and values_str[j+1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(values_str[j])
                j += 1
            vals.append(''.join(buf))
            i = j + 1
        else:
            j = i
            while j < n and values_str[j] not in ',':
                j += 1
            token = values_str[i:j].strip()
            if token == 'NULL':
                vals.append(None)
            elif re.match(r'^-?\d+$', token):
                vals.append(int(token))
            elif re.match(r'^-?\d+\.\d+$', token):
                vals.append(float(token))
            else:
                vals.append(token)
            i = j
    return vals

def _split_tuples(values_blob):
    """Sépare 'V1),(V2),(V3' (contenu entre le premier '(' après VALUES et le ';' final)
    en une liste de chaînes, chacune le contenu interne d'un tuple, en respectant
    les guillemets et parenthèses imbriquées."""
    tuples = []
    depth = 0
    buf = []
    in_str = False
    i = 0
    n = len(values_blob)
    while i < n:
        c = values_blob[i]
        if in_str:
            if c == '\\' and i + 1 < n:
                buf.append(c)
                buf.append(values_blob[i+1])
                i += 2
                continue
            if c == "'":
                in_str = False
            buf.append(c)
            i += 1
            continue
        if c == "'":
            in_str = True
            buf.append(c)
            i += 1
            continue
        if c == '(':
            depth += 1
            if depth == 1:
                buf = []
            else:
                buf.append(c)
            i += 1
            continue
        if c == ')':
            depth -= 1
            if depth == 0:
                tuples.append(''.join(buf))
            else:
                buf.append(c)
            i += 1
            continue
        if depth > 0:
            buf.append(c)
        i += 1
    return tuples

def parse_inserts(sql_text, table_columns):
    """Retourne {table_name: [ {col: val, ...}, ... ]}"""
    data = {t: [] for t in table_columns}
    for m in re.finditer(r'INSERT INTO `(\w+)` VALUES\s*(.*?);\n', sql_text, re.DOTALL):
        name = m.group(1)
        if name not in table_columns:
            continue
        cols = table_columns[name]
        blob = m.group(2)
        for tup in _split_tuples(blob):
            vals = _tokenize_values(tup)
            if len(vals) != len(cols):
                raise ValueError(f"{name}: {len(vals)} valeurs vs {len(cols)} colonnes attendues")
            data[name].append(dict(zip(cols, vals)))
    return data

def load_dump(path):
    with open(path, encoding='utf-8') as f:
        sql_text = f.read()
    table_columns = parse_create_tables(sql_text)
    data = parse_inserts(sql_text, table_columns)
    return table_columns, data

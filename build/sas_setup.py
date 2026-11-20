"""Parse NCHS's SAS setup programs for the NSFG (Datasets/NSFG/sas/ on ftp.cdc.gov).

Two styles, one parser:
- ICPSR style, 1982-1995 (one file): PROC FORMAT with VALUE fmt 1='(1) Yes' ..., a DATA step whose
  INPUT lists NAME start-end (1982 reads a record type first and keeps only rec_type 0), LABEL
  NAME='...', and FORMAT NAME fmt. statements.
- NCHS style, 2002 on (one file, or for 2002 three: Input, ValueLabel, VarLabel): the same
  statements, with labels in double quotes and value labels without the "(code)" prefix.

parse(paths) -> {NAME (upper case): entry}, entry = {name, start, end (1-based, inclusive),
is_text, label, format, rows: [(value label, code token, None)]}, plus parse(...)["__filter__"]
when the INPUT reads a record type and deletes the other types (1982):
{"column": (start, end), "keep": 0}.

Code tokens are as written: "1", "9797", "1-5" (a range), "." Value labels keep NCHS's text
without the ICPSR "(code) " prefix.
"""

import re
from pathlib import Path

COMMENT = re.compile(r"/\*.*?\*/", re.S)
VALUE = re.compile(r"(?im)^\s*value\s+(\$?\w+)\s+(.*?);", re.S)
PAIR = re.compile(r"""(-?[\d.]+(?:\s*-\s*-?[\d.]+)?|'[^']*'|"[^"]*"|\w+)\s*=\s*('(?:[^']|'')*'|"(?:[^"]|"")*")""", re.S)
INPUT_ITEM = re.compile(r"\b([A-Za-z_]\w*)\s+(\$\s*)?(\d+)(?:\s*-\s*(\d+))?(?:\s+\.(\d+))?(?=\s|$|;)")
LABEL_ITEM = re.compile(r"""\b([A-Za-z_]\w*)\s*=\s*('(?:[^']|'')*'|"(?:[^"]|"")*")""", re.S)
FORMAT_ITEM = re.compile(r"\b([A-Za-z_]\w*)\s+(\$?[A-Za-z_]\w*)\.(?=\s|;|$)")
STATEMENT = re.compile(r"(?ism)^\s*(?:else\s+)?(input|label|format)\b(.*?);")
CODE_PREFIX = re.compile(r"^\(\s*-?[\w.]+\s*\)\s*")


def unquote(s):
    q = s[0]
    return s[1:-1].replace(q + q, q)


FORMAT_BLOCK = re.compile(r"(?im)^\s*format\b(.*?);", re.S)


def parse(paths):
    text = "\n".join(Path(p).read_text(encoding="latin-1") for p in paths)
    # NCHS ships some PROC FORMAT and FORMAT statements commented out (2015-2017: "/* FORMAT ... */");
    # they still give the value labels and which variable has which, so read them before comments go.
    assigned = {}
    for block in FORMAT_BLOCK.findall(text):
        for name, fmt in FORMAT_ITEM.findall(block):
            assigned.setdefault(name.upper(), fmt.upper())
    raw = text
    text = COMMENT.sub(" ", text)
    text = re.sub(r"(?m)^\s*\*[^;]*;", " ", text)          # SAS comment statements: * ... ;
    formats = {}
    for m in VALUE.finditer(raw):   # 2015-2017 ships PROC FORMAT commented out too; read it anyway
        rows = []
        for code, label in PAIR.findall(m.group(2)):
            code = unquote(code) if code[0] in "'\"" else re.sub(r"\s+", "", code)
            rows.append((CODE_PREFIX.sub("", unquote(label)).strip(), code, None))
        formats[m.group(1).upper()] = rows
    entries, filter_ = {}, None
    body = re.sub(r"(?is)proc\s+format\s*;", " ", text)
    for m in STATEMENT.finditer(body):
        kind, rest = m.group(1).lower(), m.group(2)
        if kind == "input":
            items = INPUT_ITEM.findall(rest)
            if rest.rstrip().endswith("@") and len(items) == 1 and re.search(r"if\s+\w+\s*>\s*0\s+then\s+delete",
                                                                               body[m.end():m.end() + 200], re.I):
                name, _, s, e, _ = items[0]
                filter_ = {"column": (int(s), int(e or s)), "keep": 0, "name": name}
                continue
            for name, dollar, s, e, dec in items:
                if name.lower() in ("input", "if", "then", "else", "delete"):
                    continue
                entries.setdefault(name.upper(), {"name": name.upper(), "rows": []}).update(
                    start=int(s), end=int(e or s), is_text=bool(dollar), decimals=int(dec) if dec else None)
        elif kind == "label":
            for name, label in LABEL_ITEM.findall(rest):
                if name.upper() in entries:
                    entries[name.upper()]["label"] = " ".join(unquote(label).split())
        elif kind == "format":
            for name, fmt in FORMAT_ITEM.findall(rest):
                if name.upper() in entries:
                    entries[name.upper()]["format"] = fmt.upper()
    for name, e in entries.items():
        e.setdefault("format", assigned.get(name))
        e["rows"] = list(formats.get(e.get("format") or "", []))
    if filter_:
        entries["__filter__"] = filter_
    return entries


INFILE = re.compile(r"(?i)\binfile\b[^;]*?\brecfm\s*=\s*f\b[^;]*?\blrecl\s*=\s*(\d+)")


def record_length(paths):
    """The fixed record length an INFILE statement gives with recfm=f (1988: lrecl=3553), else None:
    such a file has no line breaks."""
    text = COMMENT.sub(" ", "\n".join(Path(p).read_text(encoding="latin-1") for p in paths))
    m = INFILE.search(text)
    return int(m.group(1)) if m else None


def records(dat, length=None):
    """The data file's records as text lines: split at line breaks, or every `length` bytes (recfm=f)."""
    import gzip
    opener = gzip.open if str(dat).endswith(".gz") else open
    with opener(dat, "rb") as f:
        raw = f.read()
    if length:
        if len(raw) % length:
            raise ValueError(f"{dat}: {len(raw)} bytes isn't a whole number of {length}-byte records")
        return [raw[i:i + length].decode("latin-1") for i in range(0, len(raw), length)]
    return raw.decode("latin-1").splitlines()


def read(dat, paths, names, fixes=None):
    """The named columns of a fixed-width NSFG file, laid out by its SAS setup program, as a raw frame.

    Numeric columns hold int or float; a blank field (SAS reads it as missing) is the code "." (pdt's
    Code), as pdt.readers does. Text ($) columns keep their text. Records of another type are dropped
    where the program does so (1982: rec_type > 0)."""
    import pandas as pd
    from pdt.data import Code
    layout = parse(paths)
    for name, fix in (fixes or {}).items():   # hand-checked corrections to the program's columns
        layout[name.upper()].update(start=fix["start"], end=fix["end"])
    filt = layout.pop("__filter__", None)
    lines = records(dat, record_length(paths))
    if filt:
        s, e = filt["column"]
        lines = [l for l in lines if int(l[s - 1:e].strip() or 0) <= filt["keep"]]
    out = {}
    for name in names:
        x = layout[name.upper()]
        cells = [l[x["start"] - 1:x["end"]] for l in lines]
        if x["is_text"]:
            out[name] = pd.Series(cells, dtype=object)
        else:
            vals = []
            for c in cells:
                c = c.strip()
                if c in ("", "."):
                    vals.append(Code("."))
                else:
                    try:
                        vals.append(int(c))
                    except ValueError:
                        vals.append(float(c))
            out[name] = pd.Series(vals, dtype=object)
    return pd.DataFrame(out)

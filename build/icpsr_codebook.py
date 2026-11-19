"""Parse NSFG codebooks in ICPSR's layout (2017-2019 and earlier), converted with pdftotext -layout.

Each entry looks like this (indentation varies by file):

    MARSTAT(28-28)                         name, then its columns in the data file
    Variable Type : raw
    AD-7b : Now I'd like to ask about ...  raw items: item reference, then the question
    Description : R's formal ...           other types: a description instead
      value label                Total
      1     Married to a ...      1913     rows: code, label, count; a range for continuous ones
            INAPPLICABLE          5387     no code: system missing
            Total                 6141
    Universe : Applicable for all respondents
    Notes : use recode RMARITAL

Fields wrap onto following lines until a blank line. Page headers ("National
Survey of Family Growth, 2017-2019 ... Page 3 of 177" or a date), footers (the
ICPSR URL) and the section heading after a page break are dropped.

Returns the same entry shape as build_slice.parse_codebook, plus "item",
"question" and "name" (the codebook's own spelling).
"""

import re

# The column numbers are sometimes misread in the PDF ("agescrn(lS-16)"), so accept any characters there.
HEADER = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)[({]\s*[^(){}\s]+\s*-\s*[^(){}\s]+\s*[)}]\s*$")
# The colon is sometimes missing ("Description          R's age at interview").
FIELD = re.compile(r"^\s*(Variable Type|Description|Universe|Notes)(?:\s*:\s*|\s{2,})(.*)$")
ITEM = re.compile(r"^\s*([A-Z]{1,3}-\d+[a-z]?)\s*:\s*(.*)$")
TABLE_HEAD = re.compile(r"^\s*value\s+label\s+Total\s*$")
TOTAL = re.compile(r"^\s*Total\s+\d+\s*$")
ROW = re.compile(r"^\s*(-?\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?|\.)?\s+(.*?)\s{2,}(\d+)\s*$")
NOISE = re.compile(r"^\s*(\d+/\d+/\d{4}\s+National Survey of Family Growth.*|National Survey of Family Growth, \d{4}-\d{4}.*"
                   r"|https?://\S*icpsr\S*.*)$")
SECTION = re.compile(r"Codebook\s*:\s*:")


def parse(paths, wanted):
    """Return {NAME (upper): entry} for the wanted names, reading the files in order."""
    wanted_upper = {w.upper() for w in wanted}
    entries = {}
    for path in paths:
        current, field, in_table, skip_heading = None, None, False, False
        for line in path.read_text(encoding="utf-8", errors="replace").replace("\f", "\n").splitlines():
            if NOISE.match(line):
                continue
            if SECTION.search(line):
                skip_heading = True  # the heading may wrap onto the next line; it ends at a blank line
                continue
            if skip_heading:
                if not line.strip():
                    skip_heading = False
                continue
            m = HEADER.match(line)
            if m:
                name = m.group(1)
                current = entries.setdefault(name.upper(), {"name": name, "rows": []}) if name.upper() in wanted_upper else None
                field, in_table = None, False
                continue
            if current is None:
                continue
            if in_table:
                if TOTAL.match(line):
                    in_table = False
                    continue
                row = ROW.match(line)
                if row:
                    token = row.group(1) or "."
                    current["rows"].append([row.group(2).strip(), token, int(row.group(3))])
                elif line.strip() and current["rows"]:
                    current["rows"][-1][0] += " " + line.strip()
                continue
            if TABLE_HEAD.match(line):
                in_table, field = True, None
                continue
            if not line.strip():
                field = None
                continue
            m = FIELD.match(line)
            if m:
                field = {"Variable Type": "variable_type", "Description": "label"}.get(m.group(1), m.group(1).lower())
                current[field] = m.group(2).strip()
                continue
            m = ITEM.match(line)
            if m and "item" not in current:
                current["item"], current["question"], field = m.group(1), m.group(2).strip(), "question"
                continue
            if field:
                current[field] += " " + line.strip()
    return entries

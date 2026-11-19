"""Parse an NSFG CAPI-lite questionnaire (pdftotext -layout) into question text by variable name.

Rule nsfg_capilite_text. In the CAPI-lite format each question is a block:

    { ASKED IF R IS UNDER AGE 25          the universe (not used; the codebook has one)
    ATTND14                               the variable name, as in the CRQ and the data
    IC-3. (Please look at Card 77.)       the item reference, then the wording
          When you were 14, ...
    [HELP AVAILABLE]                      ends the wording
          More than once a week.....1     response options end it too

When the wording depends on a condition, the block has several wordings, each
after a line like "IF ANY RELAR[X]=1 and SEX[X]=1, ASK:" or "ELSE ASK:". Each
becomes one question, with the condition as printed ("IF ANY RELAR[X]=1 and
SEX[X]=1", "ELSE") in `condition` (STANDARD.md §4.1). Lines entirely in
capitals ("SELECT ALL THAT APPLY."), or marked with a symbol-font glyph (a
private-use character in the text), are interviewer instructions; they go in
`instructions` and stay out of `text`. Layout line breaks are removed.

Page headers and footers are dropped. The page number of each block is kept for
source locations.
"""

import re

RULE = "nsfg_capilite_text"
RULE_VERSION = "0.2"  # 0.2: the condition goes in `condition`, as printed

NAME = re.compile(r"^([A-Z][A-Z0-9_]*)(\[X\])?\s*$")
ITEM = re.compile(r"^([A-Z]{1,3}-\d+[a-z]?)\.\s*(.*)$")
PAGE_NOISE = re.compile(r"^\s*(NSFG-2022-2023-Capilite-\w+|Page \d+ of \d+|NSFG (Fe)?[Mm]ale CAPI-lite for .*|OMB Number .*)\s*$")
OPTION = re.compile(r"\.{3,}\s*\d+\s*$|\.\s*\d+\s*$")
# "IF ANY RELAR[X]=1 and SEX[X]=1, ASK:", "ELSE IF ..., THEN ASK:", "ELSE ASK:", "ELSE, ASK:"; group 1 is
# the condition as printed, without the trailing ASK.
CONDITION = re.compile(r"^((?:ELSE\b)?\s*,?\s*(?:IF .*?)?)\s*,?\s*(?:THEN\s+)?ASK:\s*$", re.IGNORECASE)
ENDS = ("[HELP AVAILABLE]", "{", "[IF ", "FLOW CHECK")


PRIVATE_USE = re.compile("[-]")  # symbol-font glyphs; the PDF marks instructions with one


def is_instruction(line):
    s = line.strip()
    if PRIVATE_USE.match(s):
        return True
    s = PRIVATE_USE.sub("", s).strip()
    if s.startswith(("“", '"')):
        return True
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.9


def unwrap(lines):
    return re.sub(r"\s+", " ", PRIVATE_USE.sub("", " ".join(lines))).strip()


def parse(path):
    """Return {NAME: {"item": "AD-7b", "page": 6, "questions": [question objects]}}."""
    pages = path.read_text(encoding="utf-8", errors="replace").split("\f")
    lines = [(i + 1, l.rstrip()) for i, p in enumerate(pages) for l in p.splitlines() if not PAGE_NOISE.match(l)]
    blocks = {}
    k = 0
    while k < len(lines) - 1:
        page, line = lines[k]
        name = NAME.match(line)
        nxt = next((j for j in range(k + 1, min(k + 4, len(lines))) if lines[j][1].strip()), None)
        item = ITEM.match(lines[nxt][1]) if (name and nxt is not None) else None
        if not item:
            k += 1
            continue
        body = [item.group(2)]
        j = nxt + 1
        while j < len(lines):
            text = lines[j][1]
            s = text.strip()
            if s.startswith(ENDS) or OPTION.search(text):
                break
            n2 = NAME.match(text)
            if n2 and j + 1 < len(lines) and ITEM.match(lines[j + 1][1]):
                break
            body.append(text)
            j += 1
        blocks.setdefault(name.group(1), {"item": item.group(1), "page": page, "questions": split_wordings(body)})
        k = j
    return blocks


def split_wordings(body):
    """Split a block's lines into wordings at IF/ELSE ... ASK: lines."""
    wordings, condition, text, instructions = [], None, [], []

    def close():
        if any(t.strip() for t in text):
            q = {"text": unwrap(text)}
            if instructions:
                q["instructions"] = unwrap(instructions)
            if condition:
                q["condition"] = condition
            wordings.append(q)

    for line in body:
        s = line.strip()
        if not s:
            continue
        m = CONDITION.match(s)
        if m:
            close()
            condition = re.sub(r"\s+", " ", m.group(1).strip(" ,")) or None
            text, instructions = [], []
        elif is_instruction(s):
            instructions.append(s)
        else:
            text.append(s)
    close()
    return wordings

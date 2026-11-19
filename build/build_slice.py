"""Build the NSFG slice's metadata records from the codebooks, questionnaires and data files.

Usage:
    python build/build_slice.py

Reads build/slice.yaml and the files under data/raw/ it names. Writes
metadata/releases/<release>/<table>/variables.jsonl, metadata/links.jsonl,
metadata/derived/scale_signature.jsonl and build/report.md.

Two releases, with different documentation:

- 2022-2023: one codebook per table in NCHS's own layout (parse_codebook below),
  with no question text; the SAS data files. Question text comes from the
  CAPI-lite questionnaires, matched by variable name (build/capilite.py; the
  User's Guide says names match the questionnaire's).
- 2017-2019: section codebooks per table in ICPSR's layout, with question text
  (build/icpsr_codebook.py); fixed-width data with Stata dictionaries (.dct),
  whose variable labels are the records' labels.

Where each field comes from:
- label, variable type, universe, notes, codes and labels: the codebook
  (2017-2019 labels: the .dct)
- questions: the codebook (2017-2019) or the CAPI-lite questionnaire (2022-2023)
- which codes occur, storage type: the data file
- measure: build/slice.yaml (hand)
- which codes are missing, and why: a rule over the codebook's labels, because
  the NSFG codebook doesn't mark missing codes (rule nsfg_missing_from_labels)

Links between the releases (STANDARD.md §5.2): the ones NCHS's summary of
questionnaire changes asserts (slice.yaml publisher_links), and the rule
nsfg_identical_documentation (see identical_documentation below).
"""

import collections
import gzip
import json
import re
import subprocess
from pathlib import Path

import pandas as pd
import yaml

import capilite
import icpsr_codebook

# The scale-signature rule is shared (PublicDataToolkit lib/pdt/derived.py). Use pdt from
# PYTHONPATH; otherwise use a checkout next to this repo, or $PDT.
try:
    from pdt.derived import scale_signatures
except ImportError:
    import os, sys
    sys.path.insert(0, str(Path(os.environ.get("PDT", Path(__file__).resolve().parents[2] / "PublicDataToolkit")) / "lib"))
    from pdt.derived import scale_signatures

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
META = ROOT / "metadata"

RULE_VERSION = "0.1"
LINK_RULE, LINK_RULE_VERSION = "nsfg_identical_documentation", "0.3"
CHANGES_SOURCE = "nsfg-2022-2023-quex-changes"


def text_of(rel_path):
    """The text of a file under data/raw; a PDF is converted with pdftotext -layout once and cached beside it."""
    path = RAW / rel_path
    if path.suffix == ".pdf":
        txt = path.with_suffix(".txt")
        if not txt.exists():
            subprocess.run(["pdftotext", "-layout", str(path), str(txt)], check=True)
        return txt
    return path


# ------------------------------------------------- 2022-2023 codebook (NCHS layout)

NAME_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\s*$")
FIELD = re.compile(r"^(LABEL|VARIABLE TYPE|UNIVERSE|NOTES|LENGTH|VARNUM)\s{2,}(.*)$")
DIST_HEADER = re.compile(r"^([A-Za-z][A-Za-z0-9_]*): Distribution\s+Value\s+n\s*$")
# A distribution row: label, then a value (a number, a range, or "."), then a count.
DIST_ROW = re.compile(r"^(.*?)\s{2,}(-?\d+(?:\.\d+)?(?:\s*-\s*-?\d+(?:\.\d+)?)?|\.)\s+(\d+)\s*$")
TOTAL_ROW = re.compile(r"^\s+\d+\s*$")
PAGE_NOISE = re.compile(r"^(Section [A-Z]+|\f.*)$")
# A box in the page margin, which `pdftotext -layout` puts on the same lines as
# the entry: text after 20 or more spaces, starting at column 110 or later. The
# only one in the 2022-2023 codebooks is NCHS's "Corrected universe for MFLASTP".
MARGIN = re.compile(r"(?<=\S) {20,}(?=\S)")


def split_margin(line):
    """Return (main text, margin text or None)."""
    only = re.match(r"^ {100,}(\S.*)$", line)
    if only:
        return "", only.group(1).strip()
    for m in MARGIN.finditer(line):
        if m.end() >= 110:
            return line[:m.start()], line[m.end():].strip()
    return line, None


def parse_codebook(path, wanted):
    """Return {NAME: {fields..., "rows": [(label, value token, n)]}} for the wanted names."""
    wanted_upper = {w.upper() for w in wanted}
    entries, current, field, in_dist = {}, None, None, False
    margin_for = None  # the entry a margin box belongs to
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line, margin = split_margin(raw_line)
        if margin:
            m = re.match(r"^([A-Za-z][A-Za-z0-9_]*)\b", line.strip())
            if m and m.group(1).upper() in wanted_upper:
                margin_for = m.group(1).upper()
            if margin_for:
                entries.setdefault(margin_for, {"rows": []}).setdefault("margin", []).append(margin)
        if PAGE_NOISE.match(line):
            continue
        m = DIST_HEADER.match(line)
        if m:
            current = entries.get(m.group(1).upper())
            in_dist, field = current is not None, None
            continue
        if in_dist:
            if not line.strip() or TOTAL_ROW.match(line):
                if TOTAL_ROW.match(line):
                    in_dist = False
                continue
            row = DIST_ROW.match(line)
            if row:
                current["rows"].append([row.group(1).strip(), row.group(2).replace(" ", ""), int(row.group(3))])
            elif current["rows"]:
                current["rows"][-1][0] += " " + line.strip()  # a label wrapped onto the next line
            continue
        m = NAME_LINE.match(line)
        if m and m.group(1).upper() not in {"LABEL", "NOTES", "UNIVERSE"}:
            name = m.group(1).upper()
            if current is not None and entries.get(name) is current:
                continue  # after a page break the PDF repeats the variable's name as a header
            if name != margin_for:
                margin_for = None  # a margin box ends where the next variable begins
            current = entries.setdefault(name, {"rows": []}) if name in wanted_upper else None
            field = None
            continue
        if current is None:
            continue
        m = FIELD.match(line)
        if m:
            field = m.group(1).lower().replace(" ", "_")
            current[field] = m.group(2).strip()
        elif field and line.startswith(" ") and line.strip():
            current[field] += " " + line.strip()  # continuation of a wrapped field
    return entries


# ------------------------------------------------------------------ rules

# Rule nsfg_missing_from_labels: the NSFG codebook doesn't mark missing codes,
# so a code is missing when its whole label is one of these.
MISSING_LABELS = {
    "refused": ["refused"],
    "don't know": ["dk"],
    "inapplicable": ["inap"],
    "not ascertained": ["no_answer"],
}

ITEM = re.compile(r"^([A-Z]{1,3}-\d+[a-z]?)\s+")


# Rule nsfg_variable_type: NCHS's VARIABLE TYPE, mapped to the standard's variable_type.
NSFG_TYPES = {"raw": "response", "recode": "recode", "respondent recode": "recode", "pregnancy recode": "recode",
              "computed": "computed", "computed in post-processing": "computed", "intermediate": "computed",
              "imputation flag": "imputation_flag"}


def variable_type(nchs_type, name):
    if not nchs_type:
        return None
    key = nchs_type.strip().lower()
    if key == "weight-related":
        return "weight" if name.upper().startswith("WGT") else "design"
    return NSFG_TYPES.get(key, "other")


def missing_types(label):
    return MISSING_LABELS.get(label.strip().lower())


# ---------------------------------------------------------------- data files

DCT_LINE = re.compile(r"_column\((\d+)\)\s+\S+\s+(\w+)\s+%(\d+)(?:\.\d+)?[a-z]\s+\"(.*)\"")


def read_dct(path):
    """Return [(name, start, width, label)] from a Stata dictionary."""
    return [(m.group(2), int(m.group(1)), int(m.group(3)), m.group(4))
            for line in path.read_text(encoding="latin-1").splitlines() if (m := DCT_LINE.search(line))]


def read_data(t, names):
    """Return (frame, {NAME: dictionary label}) for one table; columns keep the file's spelling."""
    data = t["data"]
    if "dictionary" not in data:
        return pd.read_sas(RAW / data["path"], format="sas7bdat", encoding="latin-1"), {}
    wanted = {n.upper() for n in names}
    cols = [c for c in read_dct(RAW / data["dictionary"]["path"]) if c[0].upper() in wanted]
    path = RAW / data["path"]
    with (gzip.open(path, "rt", encoding="latin-1") if path.suffix == ".gz" else open(path, encoding="latin-1")) as f:
        frame = pd.read_fwf(f, colspecs=[(s - 1, s - 1 + w) for _, s, w, _ in cols],
                            names=[n for n, _, _, _ in cols], header=None, dtype=str)
    frame = frame.apply(pd.to_numeric, errors="coerce")
    return frame, {n.upper(): label for n, _, _, label in cols}


# ---------------------------------------------------------------- build


def load_slice():
    """Return (spec, {release: {table: [names]}}, measure by upper-case name)."""
    spec = yaml.safe_load((ROOT / "build" / "slice.yaml").read_text())
    names = {}
    for rel, r in spec["releases"].items():
        names[rel] = {}
        for table, t in r["tables"].items():
            ns = [n for group in t["variables"].values() for n in group]
            assert len(ns) == len(set(ns)), f"duplicate names in {rel}/{table}"
            names[rel][table] = ns
    measure = {n.upper(): m for m, ns in spec["measure"].items() for n in ns}
    return spec, names, measure


def build_variable(name, rel, rspec, measure, entry, col, table, codebook_src, data_src,
                   label=None, label_src=None, block=None, questionnaire_src=None):
    """One record. entry is the codebook entry; label and label_src override its label (2017-2019's .dct);
    block is the questionnaire block for this name (2022-2023)."""
    report = []
    hand = {"origin": "hand", "author": rspec["author"], "date": rspec["date"]}
    record = {"dataset": "nsfg", "release": rel, "table": table, "name": name}
    label = label or entry.get("label", "")
    item = ITEM.match(label)
    if label:
        record["label"] = label
    numbers = pd.to_numeric(col, errors="coerce")
    present = numbers.dropna()
    if len(present):
        record["storage_type"] = "integer" if (present % 1 == 0).all() else "float"
    if name.upper() in measure:
        record["measure"] = measure[name.upper()]
    if entry.get("universe"):
        record["universe"] = entry["universe"]
    if entry.get("notes"):
        record["notes"] = entry["notes"]
    universe_fix = None
    if entry.get("margin"):
        # NCHS's own correction, printed in a margin box. It's what the publisher says, so the
        # corrected universe goes in `universe`, and the superseded text in `notes` (STANDARD.md §5.3).
        margin = " ".join(entry["margin"])
        m = re.match(r"Corrected universe for \w+:\s*(.*)$", margin)
        if m and "universe" in record:
            superseded = record["universe"]
            record["universe"] = m.group(1)
            note = f"Universe as printed in the entry: {superseded!r}; corrected in a margin box."
            record["notes"] = (record["notes"] + "\n" if "notes" in record else "") + note
            universe_fix = margin
        else:
            record["notes"] = (record["notes"] + "\n" if "notes" in record else "") + "Codebook margin note: " + margin
        report.append(f"`{name}`: margin box in the codebook: {margin[:100]}")

    # Question text: the 2017-2019 codebook gives it; for 2022-2023 it's the questionnaire block.
    item_ref = entry.get("item") or (item.group(1) if item else None)
    questions_prov = None
    if entry.get("question"):
        record["questions"] = [{"text": re.sub(r"\s+", " ", entry["question"]).strip()}]
        questions_prov = {"origin": "publisher", "source": codebook_src, "location": f"{name.upper()}, item {item_ref}"}
    elif block:
        record["questions"] = block["questions"]
        questions_prov = {"origin": "rule", "rule": capilite.RULE, "rule_version": capilite.RULE_VERSION,
                          "source": questionnaire_src, "location": f"{block['item']} {name.upper()}, p. {block['page']}",
                          "note": "Matched by variable name. Layout line breaks removed; one wording per IF/ELSE "
                                  "condition in the questionnaire, with the condition in the note; lines in capitals "
                                  "are instructions."}
        if item_ref and item_ref != block["item"]:
            report.append(f"`{name}`: the codebook's label gives item {item_ref}, the questionnaire {block['item']}")

    values, documented, ranges, n_valid = [], set(), [], 0
    for row_label, token, n in entry.get("rows", []):
        if token == ".":
            code = "."
        elif re.search(r"\d-", token):
            lo, hi = re.split(r"(?<=\d)-", token, maxsplit=1)
            # The codebook rounds ranges (1170.96-78770.13), each end to its own number of places
            # ("1340.862-83332.1"); allow half a unit in the last place shown at each end.
            def slack(x):
                return 0.5 * 10 ** -len(x.split(".")[1]) if "." in x else 0
            ranges.append((float(lo) - slack(lo), float(hi) + slack(hi)))
            n_valid += n
            continue
        else:
            number = float(token)
            code = int(number) if number.is_integer() else number
        documented.add(code)
        types = missing_types(row_label)
        if types:
            values.append({"code": code, "label": row_label, "kind": "missing", "missing_types": types,
                           "origin": {"origin": "rule", "rule": "nsfg_missing_from_labels", "rule_version": RULE_VERSION,
                                      "source": codebook_src,
                                      "note": "The codebook doesn't mark missing codes; kind and type from the label."}})
        else:
            values.append({"code": code, "label": row_label, "kind": "valid"})
            n_valid += n
            if code == "." :
                report.append(f"`{name}`: '.' labeled {row_label!r}, not recognized as missing")
    if ranges:
        # The range spans the range rows and any single valid codes beside them
        # (2017-2019 age_r lists 15 to 48 singly, then "49-50").
        singles = [float(v["code"]) for v in values if v["kind"] == "valid" and v["code"] != "."]
        lows = [float(t.split("-")[0]) for _, t, _ in entry["rows"] if re.search(r"\d-", t)] + singles
        highs = [float(re.split(r"(?<=\d)-", t, maxsplit=1)[1]) for _, t, _ in entry["rows"] if re.search(r"\d-", t)] + singles
        # Labeled ranges ("0-19  Under 20 years") keep their labels in the note, as pdt-fars does.
        labeled = [f"{t}: {lab}" for lab, t, _ in entry["rows"]
                   if re.search(r"\d-", t) and not re.fullmatch(r"[\d.\s-]+", lab)]  # not a label that only repeats the range
        record["valid_range"] = {"min": min(lows), "max": max(highs),
                                 "note": ("; ".join(labeled) + ". " if labeled else "")
                                         + "From the distribution in the codebook, which rounds it."}
        record["valid_range"] = {k: (int(v) if isinstance(v, float) and v.is_integer() else v)
                                 for k, v in record["valid_range"].items()}

    if not entry.get("rows") and len(present):
        report.append(f"`{name}`: the codebook entry gave no codes or ranges, but the data has {len(present)} values")
    # C4: codes in the data that the codebook doesn't list.
    occurring = collections.Counter(present)
    # The codebook's counts should match the data's; a mismatch means a parsing or recognition error.
    for row_label, token, n in entry.get("rows", []):
        if re.search(r"\d-", token):
            continue
        got = int(col.isna().sum()) if token == "." else occurring.get(float(token), 0)
        if got != n:
            report.append(f"`{name}` code {token}: the codebook counts {n}, the data {got}")
    n_null = int(col.isna().sum())
    if n_null and "." not in documented and (values or ranges):
        report.append(f"`{name}`: {n_null} missing values in the data, but no '.' row in the codebook")
    for code, count in sorted(occurring.items()):
        code = int(code) if float(code).is_integer() else code
        in_range = any(lo <= code <= hi for lo, hi in ranges)
        if code not in documented and not in_range and (values or ranges):
            values.append({"code": code, "label": "", "kind": "unresolved",
                           "origin": {"origin": "data_file", "source": data_src,
                                      "note": f"Occurs {count} times in the data; not in the codebook."}})
            report.append(f"`{name}` code {code}: occurs {count} times, not in the codebook; marked unresolved")
    if values:
        record["values"] = values
    if "valid_range" not in record and measure.get(name.upper()) in {"continuous", "weight", "identifier", "count"} \
            and len(present) and not values:
        record["valid_range"] = {k: (int(v) if float(v).is_integer() else float(v))
                                 for k, v in {"min": present.min(), "max": present.max()}.items()}

    record["availability"] = [{"wave": rel, "n": int(n_valid) if (values or ranges) else int(len(present))}]
    record["source_location"] = {"source": codebook_src, "anchor": name.upper()}

    fields = {
        "values": {"origin": "publisher", "source": codebook_src,
                   "note": "Codes and labels from the codebook's distribution table; which are missing by rule (see each code)."},
        "availability": {"origin": "publisher", "source": codebook_src,
                         "note": "n is the codebook's count of valid answers."},
    }
    if label_src and "label" in record:
        fields["label"] = {"origin": "publisher", "source": label_src, "note": "The variable label in NCHS's Stata dictionary."}
    if questions_prov:
        fields["questions"] = questions_prov
    if "storage_type" in record:
        fields["storage_type"] = {"origin": "rule", "rule": "storage_type_from_values", "rule_version": RULE_VERSION,
                                  "source": data_src, "note": "integer if every value in the data is whole, else float."}
    if "measure" in record:
        fields["measure"] = hand
    if "valid_range" in record and not ranges:
        fields["valid_range"] = {"origin": "data_file", "source": data_src, "note": "Min and max of the values that occur."}
    if universe_fix:
        fields["universe"] = {"origin": "publisher", "source": codebook_src, "location": f"{name}, margin box",
                              "note": "NCHS's corrected universe, printed beside the entry."}
    vtype = variable_type(entry.get("variable_type"), name)
    if vtype:
        record["variable_type"] = vtype
        fields["variable_type"] = {"origin": "rule", "rule": "nsfg_variable_type", "rule_version": RULE_VERSION,
                                   "source": codebook_src, "note": f"From the codebook's VARIABLE TYPE {entry['variable_type']!r}."}
    record["provenance"] = {"record": {"origin": "publisher", "source": codebook_src}, "fields": fields}

    ext = {}
    if item_ref:
        ext["item"] = item_ref
    if ext:
        record["extensions"] = {"nsfg": ext}
    return record, report


def codebook_entries(rspec, t, names):
    """Return {NAME: entry}, each with entry["source"], the codebook source it came from."""
    entries = {}
    for cb in t["codebook"]:
        path = text_of(cb["path"])
        found = parse_codebook(path, names) if rspec["codebook_format"] == "nchs" else icpsr_codebook.parse([path], names)
        for name, entry in found.items():
            if name not in entries:
                entries[name] = dict(entry, source=cb["source"])
    return entries


def build_table(spec, rel, table, names, measure):
    """Build one table's records; return (records, notes, summary line)."""
    rspec = spec["releases"][rel]
    t = rspec["tables"][table]
    codebook = codebook_entries(rspec, t, names)
    frame, dict_labels = read_data(t, names)
    upper = {c.upper(): c for c in frame.columns}
    blocks, q_src = {}, None
    if "questionnaire" in t:
        blocks, q_src = capilite.parse(text_of(t["questionnaire"]["path"])), t["questionnaire"]["source"]
    records, notes = [], []
    for name in names:
        entry = codebook.get(name.upper())
        if entry is None:
            notes.append(f"`{table}/{name}`: not found in the codebook")
            entry = {"rows": [], "source": t["codebook"][0]["source"]}
        if name.upper() not in upper:
            notes.append(f"`{table}/{name}`: not in the data")
            continue
        record_name = entry.get("name", name)  # 2017-2019: the codebook's own spelling
        if rspec["codebook_format"] == "nchs" and name.upper() != name and name.upper() in codebook:
            notes.append(f"`{table}/{name}`: the codebook writes it as {name.upper()}")
        dct = t["data"].get("dictionary", {})
        record, report = build_variable(record_name, rel, rspec, measure, entry, frame[upper[name.upper()]], table,
                                        entry["source"], t["data"]["source"],
                                        label=dict_labels.get(name.upper()), label_src=dct.get("source"),
                                        block=blocks.get(name.upper()), questionnaire_src=q_src)
        records.append(record)
        notes.extend(f"`{table}/{n[1:]}" if n.startswith("`") else n for n in report)
    if rspec["codebook_format"] == "nchs":
        # Coverage (C3) for the whole file: codebook entries vs data columns.
        all_codebook = parse_codebook(text_of(t["codebook"][0]["path"]), list(upper))
        only_data = sorted(set(upper) - set(all_codebook))
        summary = (f"- `{table}`: {len(records)} variables in the slice; data file has {len(upper)} columns, "
                   f"codebook entries found for {len(all_codebook)}; in the data but not the codebook: {only_data[:10] or 'none'}")
    else:
        summary = (f"- `{table}`: {len(records)} variables in the slice, from {len(t['codebook'])} section codebook(s). "
                   f"Coverage isn't checked: only the sections that hold slice variables are sources.")
    return records, notes, summary


# ---------------------------------------------------------------- links


def norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def documentation(record):
    """What rule nsfg_identical_documentation compares: item, question texts, and coded values.
    The '.' row is left out: the codebook prints it only when some case is system missing."""
    return {"item": record.get("extensions", {}).get("nsfg", {}).get("item"),
            "questions": [norm(q["text"]) for q in record.get("questions", [])],
            "values": [(v["code"], v["label"]) for v in record.get("values", []) if v["code"] != "."]}


COUNT_RULE, COUNT_RULE_VERSION = "nsfg_count_labels_reworded", "0.1"
# A count label: the code itself, maybe with an ordinal suffix and a unit ("15 years", "2 PARTNERS", "1ST BIRTH").
COUNT_LABEL = r"^{code}(?:st|nd|rd|th)?(?:\s+(?:years?|partners?|births?|pregnanc(?:y|ies)))?$"


def is_count_label(code, label):
    return isinstance(code, int) and re.match(COUNT_LABEL.format(code=code), norm(label), re.IGNORECASE) is not None


def identical_documentation(a, b):
    """Rule nsfg_identical_documentation 0.3: return (differences, allowances, reworded count labels).

    No differences means same_item. Same name (ignoring case), the same question
    text where either record has one, and the same labels for the codes both
    codebooks list, in both cycles' NCHS documentation. Three things that are
    artifacts of the documentation, not changes to the item, are allowed, and each
    link's note lists the ones it used:
    - labels that differ only in case (2017-2019 prints recode labels in capitals);
    - codes listed by only one codebook, when one release's codes are a subset of
      the other's: the NSFG codebooks list only codes that occur in the data, so a
      code nobody gave is missing from that cycle's codebook. When each side has
      codes the other lacks, the codes changed, and this doesn't apply;
    - different item references, when nothing else differs (sections were renumbered).
    NCHS doesn't assert any of this, and its 2022-2023 FAQ cautions against
    comparing 2022-2023 with earlier cycles because of the multimode design, so
    links from this rule have origin: rule. 0.1 allowed none of the three; 0.2
    allowed one-sided codes on both sides at once.

    The third return value lists the codes whose labels differ only as count labels
    ("15 years" vs "15"); rule nsfg_count_labels_reworded uses it."""
    da, db = documentation(a), documentation(b)
    diffs, allowed = [], []
    if da["questions"] != db["questions"]:
        if not da["questions"] or not db["questions"]:
            diffs.append("question text in only one release")
        else:
            diffs.append("question text differs")
    ca, cb = dict(da["values"]), dict(db["values"])
    changed = sorted((c for c in set(ca) & set(cb) if norm(ca[c]).casefold() != norm(cb[c]).casefold()), key=str)
    counts = [c for c in changed if is_count_label(c, ca[c]) and is_count_label(c, cb[c])]
    if changed:
        diffs.append(f"labels differ for codes {changed}")
    if any(ca[c] != cb[c] for c in set(ca) & set(cb)) and not changed:
        allowed.append("labels differ only in case")
    only_a, only_b = sorted(set(ca) - set(cb), key=str), sorted(set(cb) - set(ca), key=str)
    if only_a and only_b:
        diffs.append(f"codes changed (only in {a['release']}: {only_a}; only in {b['release']}: {only_b})")
    elif only_a or only_b:
        lacking, rel = (only_a, b["release"]) if only_a else (only_b, a["release"])
        allowed.append(f"codes {lacking} aren't in the {rel} codebook (no cases)")
    if da["item"] != db["item"]:
        if diffs:
            diffs.insert(0, f"item {da['item']} vs {db['item']}")
        else:
            allowed.append(f"item reference {da['item']} in {a['release']}, {db['item']} in {b['release']}")
    return diffs, allowed, (counts if changed and counts == changed else [])


def build_links(spec, by_key):
    """Return (links, report lines). by_key maps (release, table, NAME) to a record."""
    old, new = "2017-2019", "2022-2023"
    links, lines, done = [], [], set()

    def ref(r):
        return {"release": r["release"], "table": r["table"], "name": r["name"]}

    for pl in spec.get("publisher_links", []):
        for table in pl["tables"]:
            a, b = by_key.get((old, table, pl["from"].upper())), by_key.get((new, table, pl["to"].upper()))
            if not (a and b):
                lines.append(f"- publisher link {table}/{pl['from']} -> {pl['to']}: a record is missing")
                continue
            links.append({"from": ref(a), "to": ref(b), "relations": pl["relations"],
                          "origin": {"origin": "publisher", "source": CHANGES_SOURCE, "location": pl["location"],
                                     "note": f"Quote: {pl['quote']}"},
                          "note": norm(pl["note"])})
            done.add((table, pl["from"].upper()))

    caveat = ("NCHS doesn't assert this, and its 2022-2023 FAQ cautions against comparing 2022-2023 with earlier "
              "cycles because of the multimode design.")
    shared = sorted((t, n) for (rel, t, n) in by_key if rel == new and (old, t, n) in by_key)
    linked, reworded, unlinked = [], [], []
    for table, name in shared:
        if (table, name) in done:
            continue
        a, b = by_key[(old, table, name)], by_key[(new, table, name)]
        diffs, allowed, counts = identical_documentation(a, b)
        sources = f"({a['source_location']['source']} and {b['source_location']['source']})"
        if not diffs:
            link = {"from": ref(a), "to": ref(b), "relations": ["same_item"],
                    "origin": {"origin": "rule", "rule": LINK_RULE, "rule_version": LINK_RULE_VERSION,
                               "source": b["source_location"]["source"],
                               "note": "Same name (ignoring case), question text and value labels in both cycles' NCHS "
                                       f"documentation {sources}. {caveat}"}}
            if allowed:
                link["note"] = "Allowed by the rule: " + "; ".join(allowed) + "."
            links.append(link)
            linked.append(f"`{table}/{name}`" + (f" ({'; '.join(allowed)})" if allowed else ""))
            continue
        # Rule nsfg_count_labels_reworded: everything else passes nsfg_identical_documentation, and every
        # label that differs is a count label in both cycles ("15 years" vs "15"): the same count, reworded.
        other = [d for d in diffs if not d.startswith(("labels differ", "item "))]
        if counts and not other:
            if any(d.startswith("item ") for d in diffs):
                da, db = documentation(a), documentation(b)
                allowed.append(f"item reference {da['item']} in {a['release']}, {db['item']} in {b['release']}")
            links.append({"from": ref(a), "to": ref(b), "relations": ["labels_changed"],
                          "origin": {"origin": "rule", "rule": COUNT_RULE, "rule_version": COUNT_RULE_VERSION,
                                     "source": b["source_location"]["source"],
                                     "note": "The documentation is the same in both cycles' NCHS codebooks "
                                             f"{sources} as rule {LINK_RULE} {LINK_RULE_VERSION} compares it, except "
                                             "that value labels for counts are worded differently: the code alone, or "
                                             f"with an ordinal or a unit ('15' vs '15 years'). {caveat}"},
                          "note": f"Count labels reworded for codes {counts}."
                                  + (" Allowed by the rule: " + "; ".join(allowed) + "." if allowed else "")})
            reworded.append(f"`{table}/{name}`" + (f" ({'; '.join(allowed)})" if allowed else ""))
            continue
        unlinked.append(f"- `{table}/{name}`: {'; '.join(diffs)}"
                        + (f" (allowed: {'; '.join(allowed)})" if allowed else ""))
    lines = [f"- From NCHS's summary of questionnaire changes: {len(done)}",
             f"- By rule `{LINK_RULE}` {LINK_RULE_VERSION} (same_item): {len(linked)}: {', '.join(linked) or 'none'}",
             f"- By rule `{COUNT_RULE}` {COUNT_RULE_VERSION} (labels_changed): {len(reworded)}: "
             f"{', '.join(reworded) or 'none'}",
             f"- Shared names left unlinked: {len(unlinked)}", "", *unlinked] + (lines and ["", *lines])
    return links, lines


# ---------------------------------------------------------------- main


def main():
    spec, names, measure = load_slice()
    all_records, sections = [], []
    for rel in spec["releases"]:
        release_dir = META / "releases" / rel
        notes, summaries = [], []
        for table in spec["releases"][rel]["tables"]:
            records, table_notes, summary = build_table(spec, rel, table, names[rel][table], measure)
            write_jsonl(release_dir / table / "variables.jsonl", records)
            all_records += records
            notes += table_notes
            summaries.append(summary)
        recs = [r for r in all_records if r["release"] == rel]
        types = collections.Counter(t for r in recs for v in r.get("values", []) if v["kind"] == "missing"
                                    for t in v["missing_types"])
        sections += [
            f"## Release {rel}", "",
            *summaries,
            f"- With a questionnaire item: {sum('item' in r.get('extensions', {}).get('nsfg', {}) for r in recs)} of {len(recs)}",
            f"- With question text: {sum('questions' in r for r in recs)} of {len(recs)}",
            f"- Unresolved codes: {sum(v['kind'] == 'unresolved' for r in recs for v in r.get('values', []))}",
            "", "Missing types assigned, by number of codes:", "",
            "| Type | Codes |", "|---|---|",
            *[f"| `{t}` | {k} |" for t, k in sorted(types.items())],
            "", "Values and labels to look at:", "",
            *([f"- {n}" for n in notes] or ["None."]),
            "",
        ]

    signatures = scale_signatures(all_records)
    write_jsonl(META / "derived" / "scale_signature.jsonl", signatures)

    by_key = {(r["release"], r["table"], r["name"].upper()): r for r in all_records}
    links, link_lines = build_links(spec, by_key)
    write_jsonl(META / "links.jsonl", links)

    lines = [
        "# Build report: NSFG slice",
        "",
        "Generated by `build/build_slice.py`. Do not edit.",
        "",
        f"- Releases: {', '.join(spec['releases'])}; {len(all_records)} records; scale signatures: {len(signatures)}",
        "",
        *sections,
        "## Links from 2017-2019 to 2022-2023",
        "",
        *link_lines,
        "",
    ]
    (ROOT / "build" / "report.md").write_text("\n".join(lines))
    print(f"{len(all_records)} records, {len(links)} links; see build/report.md")


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

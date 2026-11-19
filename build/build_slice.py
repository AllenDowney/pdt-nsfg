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
questionnaire changes asserts (slice.yaml publisher_links), links entered by
hand (slice.yaml hand_links), and the rule nsfg_identical_documentation (see
identical_documentation below).
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
from pdt.compare import absent_by_chance, compare_text, total_cases

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
META = ROOT / "metadata"

RULE_VERSION = "0.1"
LINK_RULE, LINK_RULE_VERSION = "nsfg_identical_documentation", "0.5"
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
                   label=None, label_src=None, block=None, questionnaire_src=None, table_names=None):
    """One record. entry is the codebook entry; label and label_src override its label (2017-2019's .dct);
    block is the questionnaire block for this name (2022-2023); table_names maps each upper-case name in
    the table's slice to the spelling its record uses (for flag_for)."""
    table_names = table_names or {}
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
    # Each wording's `number` is the item number in the document the wording comes from.
    if entry.get("question"):
        question = {"text": re.sub(r"\s+", " ", entry["question"]).strip()}
        if item_ref:
            question["number"] = item_ref
        record["questions"] = [question]
        questions_prov = {"origin": "publisher", "source": codebook_src, "location": f"{name.upper()}, item {item_ref}"}
    elif block:
        record["questions"] = [dict(q, number=block["item"]) for q in block["questions"]]
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
            values.append({"code": code, "label": row_label, "kind": "missing", "missing_types": types, "n": n,
                           "origin": {"origin": "rule", "rule": "nsfg_missing_from_labels", "rule_version": RULE_VERSION,
                                      "source": codebook_src,
                                      "note": "The codebook doesn't mark missing codes; kind and type from the label."}})
        else:
            values.append({"code": code, "label": row_label, "kind": "valid", "n": n})
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
    # An imputation flag's label names what it flags: "HIEDUC imputation flag", "OUTCOME Imputation Flag".
    flag = re.match(r"^(\w+) imputation flag\b", record.get("label", ""), re.I)
    if flag and flag.group(1).upper() in table_names:
        record["flag_for"] = [table_names[flag.group(1).upper()]]
        fields["flag_for"] = {"origin": "rule", "rule": "nsfg_flag_from_label", "rule_version": RULE_VERSION,
                              "source": label_src or codebook_src,
                              "note": "From the label, \"<NAME> imputation flag\"."}
    record["provenance"] = {"record": {"origin": "publisher", "source": codebook_src}, "fields": fields}
    if item_ref and "questions" not in record:
        report.append(f"`{name}`: item {item_ref}, but no question text, so no place for the number")
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
    table_names = {n.upper(): codebook.get(n.upper(), {}).get("name", n) for n in names}
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
                                        block=blocks.get(name.upper()), questionnaire_src=q_src,
                                        table_names=table_names)
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
    """What rule nsfg_identical_documentation compares: label, universe, item, question texts, coded values.
    The '.' row is left out: the codebook prints it only when some case is system missing."""
    return {"label": record.get("label"), "universe": record.get("universe"),
            "item": next((q["number"] for q in record.get("questions", []) if q.get("number")), None),
            "questions": [norm(q["text"]) for q in record.get("questions", [])],
            "values": [(v["code"], v["label"]) for v in record.get("values", []) if v["code"] != "."]}


COUNT_RULE, COUNT_RULE_VERSION = "nsfg_count_labels_reworded", "0.1"
# A count label: the code itself, maybe with an ordinal suffix and a unit ("15 years", "2 PARTNERS", "1ST BIRTH").
COUNT_LABEL = r"^{code}(?:st|nd|rd|th)?(?:\s+(?:years?|partners?|births?|pregnanc(?:y|ies)))?$"


def is_count_label(code, label):
    return isinstance(code, int) and re.match(COUNT_LABEL.format(code=code), norm(label), re.IGNORECASE) is not None


def identical_documentation(a, b, omits=(True, True)):
    """Rule nsfg_identical_documentation 0.5: (differences, allowances, reworded count labels, label change,
    codes changed).

    No differences means a link: same_item, labels_changed when the variable's label
    changed (the fourth value, both labels, which the link's note quotes), and
    codes_changed when codes were added or dropped (the fifth value). Texts are
    compared with pdt.compare: a difference only in case, spacing or dashes (text_only),
    or in questionnaire item references and type markers such as "IC-9", "(Computed in
    FC A-2b)" or "(RECODE)" (reference_only), isn't a change, and each link's note lists
    the ones it allowed. Also allowed, as in 0.3: codes listed by only one codebook, when
    one release's codes are a subset of the other's (the NSFG codebooks list only codes
    that occur in the data). A universe that changed blocks the link: whether the
    population changed is for a person to say.

    Codes on one side only (0.5): allowed when the code is inside the other release's
    valid_range (2017-2019 prints AGE_R 49 and 50 as one range row), or when the other
    release's codebook lists only codes that occur (sources.yaml lists_only_occurring_codes;
    omits) and the code's count makes zero cases there plausible (pdt.compare.absent_by_chance:
    PREGORDR 15, 1 case). Any other one-sided code is a change of codes: the link is
    codes_changed (OUTCOME_I's "multiple regression imputation", 7 cases in 2017-2019, none
    after), instead of no link. 0.4 allowed one-sided codes when one release's codes were a
    subset of the other's, which would have called a recoding "no cases".

    0.4 compares the variable label and the universe, which 0.3 left out. Under 0.3,
    EVRMARRY ("Whether R was ever married" / "Ever married to an opposite-sex spouse")
    linked as same_item. NCHS doesn't assert any of this, and its 2022-2023 FAQ cautions
    against comparing 2022-2023 with earlier cycles because of the multimode design, so
    links from this rule have origin: rule.

    The third value lists the codes whose labels differ only as count labels ("15 years"
    vs "15"); rule nsfg_count_labels_reworded uses it."""
    da, db = documentation(a), documentation(b)
    diffs, allowed = [], []

    def note_allowed(what, how):
        if how in ("text_only", "reference_only"):
            verb = "differ" if what.endswith("s") else "differs"
            allowed.append(f"{what} {verb} only in " + ("case, spacing or dashes" if how == "text_only"
                                                         else "item references or type markers"))

    hows = [compare_text(x, y) for x, y in zip(da["questions"], db["questions"])]
    if len(da["questions"]) != len(db["questions"]):
        diffs.append("question text in only one release" if not da["questions"] or not db["questions"]
                     else "number of question texts differs")
    elif "changed" in hows:
        diffs.append("question text differs")
    else:
        for how in set(hows):
            note_allowed("question text", how)
    how = compare_text(da["universe"], db["universe"])
    if how == "changed":
        diffs.append("universe differs")
    note_allowed("universe", how)
    how = compare_text(da["label"], db["label"])
    label_change = (da["label"], db["label"]) if how == "changed" else None
    note_allowed("label", how)
    ca, cb = dict(da["values"]), dict(db["values"])
    value_hows = {c: compare_text(ca[c], cb[c]) for c in set(ca) & set(cb)}
    changed = sorted((c for c, h in value_hows.items() if h == "changed"), key=str)
    counts = [c for c in changed if is_count_label(c, ca[c]) and is_count_label(c, cb[c])]
    if changed:
        diffs.append(f"value labels differ for codes {changed}")
    for h in sorted({h for h in value_hows.values() if h != "changed"}):
        note_allowed("value labels", h)
    n_of = [{v["code"]: v.get("n") for v in r.get("values", [])} for r in (a, b)]
    totals = (total_cases(a), total_cases(b))
    codes_changed = []
    for side, code in [(0, c) for c in sorted(set(ca) - set(cb), key=str)] + \
                      [(1, c) for c in sorted(set(cb) - set(ca), key=str)]:
        other = (b, a)[side]
        n = n_of[side].get(code)
        vr = other.get("valid_range") or {}
        if isinstance(code, (int, float)) and vr.get("min") is not None and vr["min"] <= code <= vr["max"]:
            allowed.append(f"code {code} is in {other['release']}'s range {vr['min']}-{vr['max']}")
        elif omits[1 - side] and absent_by_chance(n, totals[side], totals[1 - side]):
            allowed.append(f"code {code} isn't in the {other['release']} codebook ({n} case(s) in "
                           f"{(a, b)[side]['release']}, so none there is plausible)")
        else:
            codes_changed.append(f"{code} only in {(a, b)[side]['release']} ({n} case(s))")
    if da["item"] != db["item"]:
        allowed.append(f"item reference {da['item']} in {a['release']}, {db['item']} in {b['release']}")
    return diffs, allowed, (counts if changed and counts == changed else []), label_change, codes_changed


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

    hand = []
    for hl in spec.get("hand_links", []):
        for table in hl["tables"]:
            a, b = by_key.get((old, table, hl["name"].upper())), by_key.get((new, table, hl["name"].upper()))
            if not (a and b):
                lines.append(f"- hand link {table}/{hl['name']}: a record is missing")
                continue
            links.append({"from": ref(a), "to": ref(b), "relations": hl["relations"],
                          "origin": {"origin": "hand", "author": hl["author"], "date": hl["date"],
                                     "source": b["source_location"]["source"],
                                     "note": "The labels quoted are from both cycles' codebooks."},
                          "note": f"Label in {old}: {a.get('label')!r}; in {new}: {b.get('label')!r}. "
                                  + norm(hl.get("note", ""))})
            done.add((table, hl["name"].upper()))
            hand.append(f"`{table}/{hl['name']}`")

    occurring = {s["id"]: s.get("lists_only_occurring_codes")
                 for s in yaml.safe_load((ROOT / "sources.yaml").read_text())["sources"]}
    caveat = ("NCHS doesn't assert this, and its 2022-2023 FAQ cautions against comparing 2022-2023 with earlier "
              "cycles because of the multimode design.")
    shared = sorted((t, n) for (rel, t, n) in by_key if rel == new and (old, t, n) in by_key)
    linked, reworded, unlinked = [], [], []
    for table, name in shared:
        if (table, name) in done:
            continue
        a, b = by_key[(old, table, name)], by_key[(new, table, name)]
        omits = (bool(occurring.get(a["source_location"]["source"])),
                 bool(occurring.get(b["source_location"]["source"])))
        diffs, allowed, counts, label_change, codes_changed = identical_documentation(a, b, omits)
        codes_note = (f" Codes changed: {'; '.join(codes_changed)}." if codes_changed else "")
        sources = f"({a['source_location']['source']} and {b['source_location']['source']})"
        label_note = (f" The variable's label changed: {label_change[0]!r} in {old}, {label_change[1]!r} in {new}."
                      if label_change else "")
        allowed_note = (" Allowed by the rule: " + "; ".join(allowed) + ".") if allowed else ""
        if not diffs:
            relations = (["codes_changed"] if codes_changed else []) + (["labels_changed"] if label_change else [])
            relations = relations or ["same_item"]
            link = {"from": ref(a), "to": ref(b), "relations": relations,
                    "origin": {"origin": "rule", "rule": LINK_RULE, "rule_version": LINK_RULE_VERSION,
                               "source": b["source_location"]["source"],
                               "note": "Same name (ignoring case), universe, question text and value labels in both "
                                       f"cycles' NCHS documentation {sources}. {caveat}"}}
            if allowed or label_change or codes_changed:
                link["note"] = (codes_note + label_note + allowed_note).strip()
            links.append(link)
            linked.append(f"`{table}/{name}` ({', '.join(relations)})" + (f": {'; '.join(allowed)}" if allowed else ""))
            continue
        # Rule nsfg_count_labels_reworded: everything else passes nsfg_identical_documentation, and every
        # value label that differs is a count label in both cycles ("15 years" vs "15"): the same count, reworded.
        other = [d for d in diffs if not d.startswith("value labels differ")]
        if counts and not other:
            links.append({"from": ref(a), "to": ref(b),
                          "relations": (["codes_changed"] if codes_changed else []) + ["labels_changed"],
                          "origin": {"origin": "rule", "rule": COUNT_RULE, "rule_version": COUNT_RULE_VERSION,
                                     "source": b["source_location"]["source"],
                                     "note": "The documentation is the same in both cycles' NCHS codebooks "
                                             f"{sources} as rule {LINK_RULE} {LINK_RULE_VERSION} compares it, except "
                                             "that value labels for counts are worded differently: the code alone, or "
                                             f"with an ordinal or a unit ('15' vs '15 years'). {caveat}"},
                          "note": (f"Count labels reworded for codes {counts}." + codes_note + label_note
                                   + allowed_note).strip()})
            reworded.append(f"`{table}/{name}`" + (f" ({'; '.join(allowed)})" if allowed else ""))
            continue
        unlinked.append(f"- `{table}/{name}`: {'; '.join(diffs + (['codes changed: ' + '; '.join(codes_changed)] if codes_changed else []))}"
                        + (f" (allowed: {'; '.join(allowed)})" if allowed else ""))
    lines = [f"- From NCHS's summary of questionnaire changes: {len(done) - len(hand)}",
             f"- Entered by hand (slice.yaml hand_links): {len(hand)}: {', '.join(hand) or 'none'}",
             f"- By rule `{LINK_RULE}` {LINK_RULE_VERSION}: {len(linked)}: {', '.join(linked) or 'none'}",
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
            f"- With a questionnaire item number: {sum(any(q.get('number') for q in r.get('questions', [])) for r in recs)} of {len(recs)}",
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

"""Build the NSFG slice's metadata records from the codebook text and the SAS data file.

Usage:
    python build/build_slice.py

Reads build/slice.yaml, data/raw/2022-2023-FemResp-Codebook.txt (the CDC PDF
codebook converted with `pdftotext -layout`) and
data/raw/NSFG-2022-2023-FemRespPUFData.sas7bdat. Writes
metadata/releases/<release>/variables.jsonl, metadata/derived/scale_signature.jsonl
and build/report.md.

Where each field comes from:
- label, variable type, universe, notes, codes and labels: the codebook
- which codes occur, storage type: the SAS file (public pandas API)
- measure: build/slice.yaml (hand)
- which codes are missing, and why: a rule over the codebook's labels, because
  the NSFG codebook doesn't mark missing codes (rule nsfg_missing_from_labels)

The codebook has no question text; labels start with the questionnaire item
(e.g. "AD-7b"), which is recorded as an extension.
"""

import collections
import json
import re
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
META = ROOT / "metadata"

CODEBOOK = "nsfg-femresp-codebook"
DATA = "nsfg-femresp-sas"
RULE_VERSION = "0.1"

# ---------------------------------------------------------------- codebook

NAME_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\s*$")
FIELD = re.compile(r"^(LABEL|VARIABLE TYPE|UNIVERSE|NOTES|LENGTH|VARNUM)\s{2,}(.*)$")
DIST_HEADER = re.compile(r"^([A-Za-z][A-Za-z0-9_]*): Distribution\s+Value\s+n\s*$")
# A distribution row: label, then a value (a number, a range, or "."), then a count.
DIST_ROW = re.compile(r"^(.*?)\s{2,}(-?\d+(?:\.\d+)?(?:\s*-\s*-?\d+(?:\.\d+)?)?|\.)\s+(\d+)\s*$")
TOTAL_ROW = re.compile(r"^\s+\d+\s*$")
PAGE_NOISE = re.compile(r"^(Section [A-Z]+|\f.*)$")


def parse_codebook(path, wanted):
    """Return {NAME: {fields..., "rows": [(label, value token, n)]}} for the wanted names."""
    wanted_upper = {w.upper() for w in wanted}
    entries, current, field, in_dist = {}, None, None, False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
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
            current = {"rows": []} if name in wanted_upper else None
            if current is not None:
                entries[name] = current
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

SCALE_SIGNATURES = {("Yes", "No"): "yes_no"}


def missing_types(label):
    return MISSING_LABELS.get(label.strip().lower())


# ---------------------------------------------------------------- build


def load_slice():
    spec = yaml.safe_load((ROOT / "build" / "slice.yaml").read_text())
    names = [n for group in spec["variables"].values() for n in group]
    assert len(names) == len(set(names)), "duplicate names in slice.yaml"
    measure = {n: m for m, ns in spec["measure"].items() for n in ns}
    return spec, names, measure


def build_variable(name, spec, measure, entry, col):
    report = []
    hand = {"origin": "hand", "author": spec["author"], "date": spec["date"]}
    record = {"dataset": "nsfg", "release": spec["release"], "name": name}
    label = entry.get("label", "")
    item = ITEM.match(label)
    if label:
        record["label"] = label
    numbers = pd.to_numeric(col, errors="coerce")
    present = numbers.dropna()
    if len(present):
        record["storage_type"] = "integer" if (present % 1 == 0).all() else "float"
    if name in measure:
        record["measure"] = measure[name]
    if entry.get("universe"):
        record["universe"] = entry["universe"]
    if entry.get("notes"):
        record["notes"] = entry["notes"]

    values, documented, ranges, n_valid = [], set(), [], 0
    for row_label, token, n in entry.get("rows", []):
        if token == ".":
            code = "."
        elif re.search(r"\d-", token):
            lo, hi = re.split(r"(?<=\d)-", token, maxsplit=1)
            # The codebook rounds ranges (1170.96-78770.13); allow half a unit in the last place shown.
            places = max(len(x.split(".")[1]) if "." in x else 0 for x in (lo, hi))
            slack = 0.5 * 10 ** -places if places else 0
            ranges.append((float(lo) - slack, float(hi) + slack))
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
                                      "source": CODEBOOK,
                                      "note": "The codebook doesn't mark missing codes; kind and type from the label."}})
        else:
            values.append({"code": code, "label": row_label, "kind": "valid"})
            n_valid += n
            if code == "." :
                report.append(f"`{name}`: '.' labeled {row_label!r}, not recognized as missing")
    if ranges:
        lows = [float(t.split("-")[0]) for _, t, _ in entry["rows"] if re.search(r"\d-", t)]
        highs = [float(re.split(r"(?<=\d)-", t, maxsplit=1)[1]) for _, t, _ in entry["rows"] if re.search(r"\d-", t)]
        record["valid_range"] = {"min": min(lows), "max": max(highs),
                                 "note": "From the distribution in the codebook, which rounds it."}
        record["valid_range"] = {k: (int(v) if isinstance(v, float) and v.is_integer() else v)
                                 for k, v in record["valid_range"].items()}

    # C4: codes in the data that the codebook doesn't list.
    occurring = collections.Counter(present)
    n_null = int(col.isna().sum())
    if n_null and "." not in documented and (values or ranges):
        report.append(f"`{name}`: {n_null} missing values in the data, but no '.' row in the codebook")
    for code, count in sorted(occurring.items()):
        code = int(code) if float(code).is_integer() else code
        in_range = any(lo <= code <= hi for lo, hi in ranges)
        if code not in documented and not in_range and (values or ranges):
            values.append({"code": code, "label": "", "kind": "unresolved",
                           "origin": {"origin": "data_file", "source": DATA,
                                      "note": f"Occurs {count} times in the data; not in the codebook."}})
            report.append(f"`{name}` code {code}: occurs {count} times, not in the codebook; marked unresolved")
    if values:
        record["values"] = values
    if "valid_range" not in record and measure.get(name) in {"continuous", "weight", "identifier", "count"} \
            and len(present) and not values:
        record["valid_range"] = {k: (int(v) if float(v).is_integer() else float(v))
                                 for k, v in {"min": present.min(), "max": present.max()}.items()}

    record["availability"] = [{"wave": spec["release"], "n": int(n_valid) if (values or ranges) else int(len(present))}]
    record["source_location"] = {"source": CODEBOOK, "anchor": name.upper()}

    fields = {
        "values": {"origin": "publisher", "source": CODEBOOK,
                   "note": "Codes and labels from the codebook's distribution table; which are missing by rule (see each code)."},
        "availability": {"origin": "publisher", "source": CODEBOOK,
                         "note": "n is the codebook's count of valid answers."},
    }
    if "storage_type" in record:
        fields["storage_type"] = {"origin": "rule", "rule": "storage_type_from_values", "rule_version": RULE_VERSION,
                                  "source": DATA, "note": "integer if every value in the data is whole, else float."}
    if "measure" in record:
        fields["measure"] = hand
    if "valid_range" in record and not ranges:
        fields["valid_range"] = {"origin": "data_file", "source": DATA, "note": "Min and max of the values that occur."}
    record["provenance"] = {"record": {"origin": "publisher", "source": CODEBOOK}, "fields": fields}

    ext = {}
    if item:
        ext["item"] = item.group(1)
    if entry.get("variable_type"):
        ext["variable_type"] = entry["variable_type"]
    if ext:
        record["extensions"] = {"nsfg": ext}
    return record, report


def main():
    spec, names, measure = load_slice()
    codebook = parse_codebook(RAW / "2022-2023-FemResp-Codebook.txt", names)
    frame = pd.read_sas(RAW / "NSFG-2022-2023-FemRespPUFData.sas7bdat", format="sas7bdat", encoding="latin-1")
    upper = {c.upper(): c for c in frame.columns}

    records, notes = [], []
    for name in names:
        entry = codebook.get(name.upper())
        if entry is None:
            notes.append(f"`{name}`: not found in the codebook")
            entry = {"rows": []}
        if name not in frame.columns:
            notes.append(f"`{name}`: not in the data (as {upper.get(name.upper())!r})")
        if name.upper() != name and name.upper() in codebook:
            notes.append(f"`{name}`: the codebook writes it as {name.upper()}")
        record, report = build_variable(name, spec, measure, entry, frame[upper[name.upper()]])
        records.append(record)
        notes.extend(report)

    # Coverage (C3) for the whole file: codebook entries vs data columns.
    all_codebook = parse_codebook(RAW / "2022-2023-FemResp-Codebook.txt", list(upper))
    only_data = sorted(set(upper) - set(all_codebook))
    write_jsonl(META / "releases" / spec["release"] / "variables.jsonl", records)
    signatures = [{"target": {"variable": r["name"]}, "property": "scale_signature",
                   "value": SCALE_SIGNATURES[labels], "rule": "scale_signature_from_valid_labels",
                   "rule_version": RULE_VERSION}
                  for r in records
                  if (labels := tuple(v["label"] for v in r.get("values", []) if v["kind"] == "valid")) in SCALE_SIGNATURES]
    write_jsonl(META / "derived" / "scale_signature.jsonl", signatures)

    types = collections.Counter(t for r in records for v in r.get("values", []) if v["kind"] == "missing"
                                for t in v["missing_types"])
    lines = [
        f"# Build report: NSFG slice, release {spec['release']} (female respondent file)",
        "",
        "Generated by `build/build_slice.py`. Do not edit.",
        "",
        f"- Variables: {len(records)}",
        f"- Data file columns: {len(upper)}; codebook entries found for {len(all_codebook)}; "
        f"in the data but not the codebook: {only_data[:10] or 'none'}",
        f"- With a questionnaire item in the label: {sum('item' in r.get('extensions', {}).get('nsfg', {}) for r in records)}",
        f"- Unresolved codes: {sum(v['kind'] == 'unresolved' for r in records for v in r.get('values', []))}",
        f"- Scale signatures: {len(signatures)}",
        "",
        "## Missing types assigned, by number of codes",
        "",
        "| Type | Codes |",
        "|---|---|",
        *[f"| `{t}` | {k} |" for t, k in sorted(types.items())],
        "",
        "## Values and labels to look at",
        "",
        *([f"- {n}" for n in notes] or ["None."]),
        "",
    ]
    (ROOT / "build" / "report.md").write_text("\n".join(lines))
    print(f"{len(records)} variables; see build/report.md")


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

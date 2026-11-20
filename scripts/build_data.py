#!/usr/bin/env python3
"""Write the NSFG data release in the common format (STANDARD.md §8).

Reads the publisher's files in data/raw (fetch them with scripts/download.py):
SAS for 2022-2023, fixed-width .dat files with Stata dictionaries (.dct) for
2017-2019, and fixed-width .dat files laid out by NCHS's SAS setup programs for
1982 to 2015-2017 (build/sas_setup.py). Writes
data/processed/nsfg-<release>-<table>.parquet, one per table, holding the
variables this repo has records for. Each file is read back and every cell
compared with the SAS file, so the conversion is lossless.

A missing value in either format (SAS's ".", a blank field in the .dat) becomes the
code "." in the code column, which the records list as "Inapplicable" (inap).
"""

import sys
from pathlib import Path

try:
    from pdt.readers import read_sas, read_stata_dictionary
    from pdt.release import data_source, write_release
except ImportError:
    sys.exit("Needs the PublicDataToolkit library: pip install -e ../PublicDataToolkit, "
             "or run through `make data`.")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))
import sas_setup  # noqa: E402  (build/sas_setup.py)
import yaml  # noqa: E402


def need(source):
    path = ROOT / source["path"]
    if not path.exists():
        sys.exit(f"{path} is missing; run scripts/download.py first")
    return path


def read(release, table, names):
    try:
        source = data_source(ROOT, release, table, format="sas7bdat")
        return read_sas(need(source), names), source["id"]
    except ValueError:
        pass
    dat = data_source(ROOT, release, table, format="fixed-width")
    try:
        dct = data_source(ROOT, release, table, format="stata-dictionary")
        return read_stata_dictionary(need(dat), need(dct), names), dat["id"]
    except ValueError:
        pass
    # 1982 to 2015-2017: laid out by NCHS's SAS setup program, with the hand-checked fixes in build/slice.yaml
    spec = yaml.safe_load((ROOT / "build" / "slice.yaml").read_text())["releases"][release]["tables"][table]
    setups = [ROOT / "data" / "raw" / cb["path"] for cb in spec["codebook"]]
    return sas_setup.read(need(dat), setups, names, spec.get("layout_fixes")), dat["id"]


if __name__ == "__main__":
    write_release(ROOT, read)

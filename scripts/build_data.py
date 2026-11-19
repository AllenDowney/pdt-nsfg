#!/usr/bin/env python3
"""Write the NSFG data release in the common format (STANDARD.md §8).

Reads the SAS files in data/raw (fetch them with scripts/download.py) and writes
data/processed/nsfg-<release>-<table>.parquet, one per table, holding the
variables this repo has records for. Each file is read back and every cell
compared with the SAS file, so the conversion is lossless.

SAS's system missing value (".") becomes the code "." in the code column, which
the records list as "Inapplicable" (inap).
"""

import sys
from pathlib import Path

try:
    from pdt.readers import read_sas
    from pdt.release import data_source, write_release
except ImportError:
    sys.exit("Needs the PublicDataToolkit library: pip install -e ../PublicDataToolkit, "
             "or run through `make data`.")

ROOT = Path(__file__).resolve().parent.parent


def read(release, table, names):
    """The SAS releases; others (2017-2019's fixed-width .dat) need a reader of their own."""
    try:
        source = data_source(ROOT, release, table, format="sas7bdat")
    except ValueError:
        return None
    path = ROOT / source["path"]
    if not path.exists():
        sys.exit(f"{path} is missing; run scripts/download.py first")
    return read_sas(path, names), source["id"]


if __name__ == "__main__":
    write_release(ROOT, read)

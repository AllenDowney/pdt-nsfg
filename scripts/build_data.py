#!/usr/bin/env python3
"""Write the NSFG data release in the common format (STANDARD.md §8).

Reads the SAS files in data/raw (fetch them with scripts/download.py) and writes
data/processed/nsfg-2022-2023-<table>.parquet, one per table, holding the
variables this repo has records for. Each file is read back and every cell
compared with the SAS file, so the conversion is lossless.

SAS's system missing value (".") becomes the code "." in the code column, which
the records list as "Inapplicable" (inap).
"""

import sys
from pathlib import Path

import pandas as pd
import yaml

try:
    from pdt.data import Code
    from pdt.release import write_release
except ImportError:
    sys.exit("Needs the PublicDataToolkit library: pip install -e ../PublicDataToolkit, "
             "or run through `make data`.")

ROOT = Path(__file__).resolve().parent.parent
SLICE = yaml.safe_load((ROOT / "build" / "slice.yaml").read_text())


def read(release, table):
    """The publisher's file as a raw frame: numbers, and Code('.') for SAS missing."""
    spec = SLICE["tables"][table]["data"]
    path = ROOT / "data" / "raw" / spec["path"]
    if not path.exists():
        sys.exit(f"{path} is missing; run scripts/download.py first")
    frame = pd.read_sas(path, format="sas7bdat", encoding="latin-1")
    raw = frame.astype(object).where(frame.notna(), Code("."))
    return raw, spec["source"]


if __name__ == "__main__":
    write_release(ROOT, read)

#!/usr/bin/env python3
"""Write an extract of the NSFG data, from the common-format files in data/processed.

Run `make data` first. Then, for example:

    python scripts/extract.py --release 2017-2019 --table female --vars CASEID,RMARITAL,RELIGION,WGT2017_2019 \
        --out nsfg.csv

You name the variables, the release (and the table, for a release with several),
the waves, and what to do with each missing type: `--missing dk=DK refused=DK`
replaces those types, and every other missing value is null. Unresolved codes
are null too, unless you pass --unresolved. --codes keeps each variable's code
column. The extract makes no analysis choices of its own.

What the extract relied on goes to stderr, including every code classified, or
made valid, only by an `inferred` correction (STANDARD.md §5.3).

Uses the PublicDataToolkit library (pdt.extract); `pip install -e ../PublicDataToolkit`,
or run with PYTHONPATH=../PublicDataToolkit/lib.
"""

import sys
from pathlib import Path

try:
    from pdt.extract import main
except ImportError:
    sys.exit("Needs the PublicDataToolkit library: pip install -e ../PublicDataToolkit, "
             "or run with PYTHONPATH=../PublicDataToolkit/lib.")

ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    sys.exit(main([str(ROOT), *sys.argv[1:]]))

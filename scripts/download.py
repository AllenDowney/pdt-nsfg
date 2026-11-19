#!/usr/bin/env python3
"""Fetch the NSFG files this repo is built from, as sources.yaml lists them.

    python scripts/download.py --check            # what is present; no network
    python scripts/download.py --accept-terms     # fetch what's missing

NCHS distributes the NSFG public-use files under a data user agreement:
statistical reporting and analysis only, no attempt to identify anyone, and no
linking to individually identifiable data. Read it before downloading:

    https://www.cdc.gov/nchs/policy/data-user-agreement.html

The script won't fetch anything until you pass --accept-terms. The codebooks are
fetched as PDF and converted with `pdftotext -layout` (poppler-utils).

Uses the PublicDataToolkit library (pdt.download); `make download` sets PYTHONPATH.
"""

import sys
from pathlib import Path

try:
    from pdt.download import main
except ImportError:
    sys.exit("Needs the PublicDataToolkit library: pip install -e ../PublicDataToolkit, "
             "or run through `make download`.")

ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    sys.exit(main([str(ROOT), *sys.argv[1:]]))

PYTHON ?= python
# A PublicDataToolkit checkout. Or `pip install -e $(PDT)` and run `pdt check`.
PDT ?= ../PublicDataToolkit

.PHONY: download data package build views check

## Fetch the sources into data/raw. Read the NCHS terms first, then: make download ARGS=--accept-terms
download:
	PYTHONPATH=$(PDT)/lib $(PYTHON) scripts/download.py $(ARGS)

## Write the common-format parquet files in data/processed (the data release)
data:
	PYTHONPATH=$(PDT)/lib $(PYTHON) scripts/build_data.py

## Assemble the data release in data/release (ship data only; publish it by hand)
package:
	PYTHONPATH=$(PDT)/lib $(PYTHON) -m pdt package .

## Build metadata records from data/raw (see build/build_slice.py)
build:
	PYTHONPATH=$(PDT)/lib $(PYTHON) build/build_slice.py

## Generate agent/, docs/ and export/ from the records (pdt views)
views:
	PYTHONPATH=$(PDT)/lib $(PYTHON) -m pdt views .

## Check the repo against the PublicDataToolkit standard (pdt check)
check:
	PYTHONPATH=$(PDT)/lib $(PYTHON) -m pdt check .

PYTHON ?= python
# A PublicDataToolkit checkout. Or `pip install -e $(PDT)` and run `pdt check`.
PDT ?= ../PublicDataToolkit

.PHONY: build views check

## Build metadata records from data/raw (see build/build_slice.py)
build:
	$(PYTHON) build/build_slice.py

## Generate agent/, docs/ and export/ from the records (pdt views)
views:
	PYTHONPATH=$(PDT)/lib $(PYTHON) -m pdt views .

## Check the repo against the PublicDataToolkit standard (pdt check)
check:
	PYTHONPATH=$(PDT)/lib $(PYTHON) -m pdt check .

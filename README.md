# pdt-nsfg

Metadata for the [National Survey of Family Growth](https://www.cdc.gov/nchs/nsfg/) (NSFG), built to the [PublicDataToolkit](https://github.com/AllenDowney/PublicDataToolkit) standard.

**Status:** preliminary. A 52-variable slice of the 2022-2023 (cycle 12) release, in three tables: female respondents (23 variables), male respondents (17) and pregnancies (12).

## What the dataset is

The NSFG, run by the National Center for Health Statistics, surveys US men and women aged 15-49 about family life, marriage, pregnancy, contraception and health. It is released in cycles; cycle 12 covers 2022-2023 and has separate files for female respondents, male respondents and pregnancies.

## Terms of use

The [NCHS Data User Agreement](https://www.cdc.gov/nchs/policy/data-user-agreement.html) limits public-use files to statistical analysis and forbids any attempt to identify respondents. NCHS documentation is a US government work in the public domain. Allen Downey reviewed the terms (2026-11-20): the metadata, the documentation and the common-format data ship, with this notice:

> Source: National Center for Health Statistics, National Survey of Family Growth, public-use data files. Use is subject to the NCHS Data User Agreement (https://www.cdc.gov/nchs/policy/data-user-agreement.html): the data may be used only for statistical reporting and analysis, and users must not attempt to identify any person or link the data to identifiable data.

The terms as reviewed are in [`dataset.yaml`](dataset.yaml).

## How to get the data

The files are on the CDC FTP site; [`sources.yaml`](sources.yaml) lists them with checksums.

## The metadata

- `metadata/releases/2022-2023/<table>/variables.jsonl`, for [`female`](metadata/releases/2022-2023/female/variables.jsonl), [`male`](metadata/releases/2022-2023/male/variables.jsonl) and [`pregnancy`](metadata/releases/2022-2023/pregnancy/variables.jsonl): one record per variable, with label, universe, notes, codes, counts, and where each fact came from. Refused, don't know and inapplicable are typed by a rule, since the codebook doesn't mark them.
- [`dataset.yaml`](dataset.yaml) declares the tables, their keys (`CaseID`; `CaseID` and `PREGORDR`), and that each pregnancy's `CaseID` refers to a female respondent.

## How to cite

National Center for Health Statistics, National Survey of Family Growth, 2022-2023.

## How to rebuild

With the sources in `data/raw/` and a PublicDataToolkit checkout next to this repo:

```bash
make build
make check
```

## License

Code here is under the MIT License. Our metadata, corrections and generated views are under CC BY 4.0. The publisher's files and documentation keep the publisher's terms (above). See [`LICENSE`](LICENSE).

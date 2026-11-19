# pdt-nsfg

Metadata for the [National Survey of Family Growth](https://www.cdc.gov/nchs/nsfg/) (NSFG), built to the [PublicDataToolkit](https://github.com/AllenDowney/PublicDataToolkit) standard.

**Status:** preliminary. A 23-variable slice of the 2022-2023 (cycle 12) female respondent file.

## What the dataset is

The NSFG, run by the National Center for Health Statistics, surveys US men and women aged 15-49 about family life, marriage, pregnancy, contraception and health. It is released in cycles; cycle 12 covers 2022-2023 and has separate files for female respondents, male respondents and pregnancies.

## Terms of use

The [NCHS Data User Agreement](https://www.cdc.gov/nchs/policy/data-user-agreement.html) limits public-use files to statistical analysis and forbids any attempt to identify respondents. NCHS documentation is a US government work in the public domain. The terms as reviewed are in [`dataset.yaml`](dataset.yaml).

## How to get the data

The files are on the CDC FTP site; [`sources.yaml`](sources.yaml) lists them with checksums.

## The metadata

- [`metadata/releases/2022-2023/variables.jsonl`](metadata/releases/2022-2023/variables.jsonl): one record per variable: label, universe, notes, codes (with refused, don't know and inapplicable typed by rule, since the codebook doesn't mark them), counts, and where each fact came from.

## How to cite

National Center for Health Statistics, National Survey of Family Growth, 2022-2023.

## How to rebuild

With the sources in `data/raw/` and a PublicDataToolkit checkout next to this repo:

```bash
make build
make check
```

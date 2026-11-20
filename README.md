# pdt-nsfg

Metadata for the [National Survey of Family Growth](https://www.cdc.gov/nchs/nsfg/) (NSFG), built to the [PublicDataToolkit](https://github.com/AllenDowney/PublicDataToolkit) standard.

**Status:** preliminary. 427 variable records across ten releases, from 1982 (cycle 3) to 2022-2023 (cycle 12): the female respondent file of every cycle, the male file from 2002, and pregnancies for 2017-2019 and 2022-2023. Each release has every variable [MarriageNSFG](https://github.com/AllenDowney/MarriageNSFG) reads, so it can read this repo's data instead of its own readers.

## What the dataset is

The NSFG, run by the National Center for Health Statistics, surveys US men and women aged 15-49 about family life, marriage, pregnancy, contraception and health. It is released in cycles: 1982, 1988, 1995, 2002, then 2006-2010, 2011-2013, 2013-2015, 2015-2017, 2017-2019 and 2022-2023, each with separate files for female respondents, male respondents (from 2002) and pregnancies.

| Releases | Documentation used | Question text |
|---|---|---|
| 1982 to 2015-2017 | NCHS's SAS setup programs: layout, variable labels, value labels | no |
| 2017-2019 | NCHS's section codebooks (PDF) and Stata dictionaries | yes |
| 2022-2023 | NCHS's codebooks (PDF) and the CAPI-lite questionnaires | yes |

## Terms of use

The [NCHS Data User Agreement](https://www.cdc.gov/nchs/policy/data-user-agreement.html) limits public-use files to statistical analysis and forbids any attempt to identify respondents. NCHS documentation is a US government work in the public domain. Allen Downey reviewed the terms (2026-11-20): the metadata, the documentation and the common-format data ship, with this notice:

> Source: National Center for Health Statistics, National Survey of Family Growth, public-use data files. Use is subject to the NCHS Data User Agreement (https://www.cdc.gov/nchs/policy/data-user-agreement.html): the data may be used only for statistical reporting and analysis, and users must not attempt to identify any person or link the data to identifiable data.

The terms as reviewed are in [`dataset.yaml`](dataset.yaml).

## How to get the data

The files are on the CDC FTP site; [`sources.yaml`](sources.yaml) lists them with checksums.

## The metadata

- `metadata/releases/<release>/<table>/variables.jsonl`: one record per variable, with label, codes, counts (where the codebook prints them), and where each fact came from. Refused, don't know and inapplicable are typed by a rule, since NCHS doesn't mark them.
- `metadata/links.jsonl`: how each variable continues from one cycle to the next: NCHS's statements, and a rule where the documentation is the same.
- `metadata/corrections.jsonl`: where this repo departs from NCHS's documentation, with evidence. A blank field the setup programs don't label is classified Inapplicable (inferred from 2002's value labels and the 2017-2019 codebooks). In 1982, F22_1CM is read from columns 625-628, not the setup program's 622-628 (build/slice.yaml).
- [`dataset.yaml`](dataset.yaml) declares the tables, their keys (`CaseID`; `CaseID` and `PREGORDR`), and that each pregnancy's `CaseID` refers to a female respondent.

## How to cite

National Center for Health Statistics, National Survey of Family Growth, <cycle>.

## How to rebuild

With the sources in `data/raw/` and a PublicDataToolkit checkout next to this repo:

```bash
make build
make data
make views
make check
```

Run them under a memory cap; the largest step peaks below 1 GB.

## License

Code here is under the MIT License. Our metadata, corrections and generated views are under CC BY 4.0. The publisher's files and documentation keep the publisher's terms (above). See [`LICENSE`](LICENSE).

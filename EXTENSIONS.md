# Extensions

| Key | What it holds | Source | Why it's an extension |
|---|---|---|---|
| `nsfg.item` | The questionnaire item a variable comes from, e.g. `AD-7b`, taken from the start of its codebook label | codebook LABEL | The NSFG codebook has no question text, only the item reference. With the questionnaire, this could become `questions` and a link to the instrument |
| `nsfg.variable_type` | NCHS's variable type: `raw`, `recode`, `computed`, `imputation flag`, `weight-related` | codebook VARIABLE TYPE | Says whether a variable is a direct answer or derived. Other publishers make the same distinction; a candidate for the standard |

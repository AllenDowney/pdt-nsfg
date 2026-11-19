# Extensions

| Key | What it holds | Source | Why it's an extension |
|---|---|---|---|
| `nsfg.item` | The questionnaire item a variable comes from, e.g. `AD-7b`, taken from the start of its codebook label | codebook LABEL | The NSFG codebook has no question text, only the item reference. With the questionnaire, this could become `questions` and a link to the instrument |

`nsfg.variable_type` moved into the standard as `variable_type` (PublicDataToolkit Task 25), mapped by the rule `nsfg_variable_type`.

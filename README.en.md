![Find Similar Medical Cases](./assets/readme-cover.svg)

# Find Similar Medical Cases

[中文](./README.md) · [Case details](./examples/README.md) · [Search and comparison details](./examples/search-details.md)

A bilingual Codex Skill that finds and compares source-grounded medical cases from a de-identified clinical presentation.

## Install and use

Ask a Skill-capable AI assistant in natural language to install this repository: `https://github.com/JuneYaooo/find-similar-medical-cases`, then restart the agent. After installation, describe the de-identified case and desired comparison directly in natural language; no fixed command or Skill name is required.

Do not submit names, contact details, identity documents, record numbers, exact addresses, exact admission dates, or identifying clinical documents.

## Demonstrated results

The [Chinese README](./README.md) presents two unique public inputs from the China Clinical Case Repository. The first is a multicause presentation of palpitations involving documented hypoglycemia, renal potassium loss, and a myocardial bridge. The second is bowel-associated dermatosis-arthritis syndrome following toxigenic *Clostridioides difficile* colitis, with different upper- and lower-limb histopathology.

For each input, the README shows three verified similar patients with a weighted clinical-similarity score, evidence coverage, key differences, treatment, outcome, and primary-paper links. The submitted list contained the first URL twice, so it is not counted as a third case. [Detailed case pages](./examples/README.md) retain five verified comparisons per input and their 0–5 dimension scores, while [search and comparison details](./examples/search-details.md) record the scoring method and retrieval results.

## Disclaimer

This project supports case review, discussion preparation, literature retrieval, and research exploration. It does not provide diagnosis or treatment advice. Similar cases cannot establish an individual's diagnosis, causality, treatment suitability, or prognosis. Similarity scores are structured literature comparisons, not validated diagnostic probabilities. Evidence coverage is reported separately and does not represent source quality. Facts absent from the original source are not inferred. Public-account material is used only as an input or discovery lead; clinical claims about similar cases are checked against primary papers or other authoritative sources.

[MIT License](./LICENSE)

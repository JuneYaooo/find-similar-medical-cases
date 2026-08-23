![Find Similar Medical Cases](./assets/readme-cover.svg)

# Find Similar Medical Cases

[中文](./README.md) · [Detailed case review](./examples/search-details.md)

A bilingual Codex Skill that finds and compares source-grounded medical cases from a de-identified clinical presentation.

## Install and use

Download this repository and place it at `~/.codex/skills/find-similar-medical-cases`, then restart Codex. Invoke `$find-similar-medical-cases` and provide a de-identified presentation containing the age band, symptom sequence, key findings, exposures, and treatment response.

Do not submit names, contact details, identity documents, record numbers, exact addresses, exact admission dates, or identifying clinical documents.

## Demonstrated results

The [Chinese README](./README.md) presents three complete public clinical inputs and the top three similar cases for each:

- Posaconazole-associated refractory hypokalemia, hypertension, metabolic alkalosis, and suppressed renin and aldosterone.
- Anti-NMDAR encephalitis in a 29-year-old woman initially treated as viral encephalitis, with seizures, hypoventilation, positive serum and CSF antibodies, and no tumor detected.
- A 9-year-old girl treated for refractory epilepsy for five years before cardiorespiratory arrest revealed CPVT with simultaneous focal atrial tachycardia.

For each input, the README shows concise similarities, important differences, treatment, outcome, and primary-paper links. [Detailed case review](./examples/search-details.md) records the comparison stages, dimensions, qualitative similarity basis, and full case index.

## Disclaimer

This project supports case review, discussion preparation, literature retrieval, and research exploration. It does not provide diagnosis or treatment advice. Similar cases cannot establish an individual's diagnosis, causality, treatment suitability, or prognosis. Similarity labels are literature comparisons, not validated diagnostic probabilities. Facts absent from the original source are not inferred. Public-account material is used only to discover leads; clinical claims are checked against primary papers or other authoritative sources.

## Resources

- [中文首页](./README.md)
- [Detailed case review](./examples/search-details.md)
- [Complete Skill documentation](./SKILL.md)
- [Sources and boundaries](./references/sources.md)

[MIT License](./LICENSE)

![Find Similar Medical Cases](./assets/readme-cover.svg)

# Find Similar Medical Cases

[中文](./README.md) · [Real case details](./examples/)

A bilingual similar-medical-case retrieval Skill for medical researchers and clinicians. Given a de-identified clinical presentation, it finds comparable real cases in medical literature and summarizes each patient's presentation, similarities, important differences, treatment, outcome, and original source.

The examples shown here come from verifiable publications rather than simulated patients. Similarity helps organize comparison; it is not a diagnostic probability.

## Real case gallery

![Three complex clinical cases](./assets/real-case-overview.svg)

| Area | Input case | What the similar cases show | Details |
|---|---|---|---|
| Drug adverse effect / endocrinology | An adult develops hypertension, hypokalemia, metabolic alkalosis, low renin, and low aldosterone after posaconazole | Reports across different ages and underlying diseases reproduce an apparent-mineralocorticoid-excess phenotype. Withdrawal, dose reduction, switching treatment, or spironolactone can improve it, while mechanisms and recovery vary | [Posaconazole cases](./examples/posaconazole-real-cases.md) |
| Neuroimmunology / gynecology | A young woman develops acute psychiatric or behavioral symptoms followed by seizures, altered consciousness, or abnormal movements, with an ovarian teratoma | Close cases commonly have serum or CSF anti-NMDAR antibodies. Most improve after tumor removal and immunotherapy, but recovery and recurrence differ | [Anti-NMDAR cases](./examples/anti-nmdar-real-cases.md) |
| Inherited arrhythmia | A child or young adult has exercise- or emotion-triggered syncope, seizure-like episodes, or cardiac arrest; resting tests may be normal and exercise testing reveals bidirectional or polymorphic VT | A normal resting ECG does not exclude CPVT. Trigger pattern, exercise testing, and genetics are highly discriminating; reported treatment ranges from medication to an ICD, sympathetic denervation, or ECMO | [CPVT cases](./examples/cpvt-real-cases.md) |

## Conclusions

- **Posaconazole:** hypertension with hypokalemia and suppressed renin and aldosterone repeatedly points toward drug-associated apparent mineralocorticoid excess. Dechallenge and lower-dose rechallenge strengthen the temporal association without proving causality in another patient.
- **Anti-NMDAR encephalitis:** new psychiatric symptoms in a young woman warrant a broader differential when seizures, memory or consciousness disturbance, or abnormal movements rapidly follow. An ovarian teratoma and CSF antibodies strongly distinguish the closest cases.
- **CPVT:** exercise- or emotion-triggered convulsive episodes should not automatically be treated as epilepsy. Resting studies can be normal; exercise-induced bidirectional or polymorphic VT, family history, and genetics carry more weight.
- **Across all three:** symptom sequence, triggers, medication timing, and objective findings are more useful than a shared diagnostic label. Treatment and outcome still need case-by-case comparison.

## Similarity labels

- **Highly similar:** the core presentation, timing, and decisive objective findings align.
- **Similar:** the main clinical pattern aligns, but a key test is missing or age, cause, severity, or treatment differs.
- **Partially similar:** important features or a diagnostic detour align, but a major difference changes the comparison.

Facts absent from the source are marked as not reported rather than inferred.

## Use and limits

Submit only de-identified details such as age band, symptom sequence, key tests, medication or exposure, and treatment response. Do not include names, contact details, identity documents, medical-record numbers, exact addresses, or identifying clinical documents.

Each showcased case links to a PMID, DOI, or open full text for verification. This project supports case review, discussion preparation, and research exploration. Similar cases cannot establish an individual's diagnosis, causality, treatment suitability, or prognosis and do not replace clinical judgment or a formal systematic review.

## Resources

- [中文首页](./README.md)
- [Real case details](./examples/)
- [Complete Skill documentation](./SKILL.md)
- [Sources and boundaries](./references/sources.md)

[MIT License](./LICENSE)

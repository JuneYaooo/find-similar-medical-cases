# Retrieval, comparison, and reporting workflow

## Contents

- Build a de-identified case fingerprint
- Build query variants
- Execute a multi-query plan
- Choose retrieval routes
- Normalize and deduplicate
- Compare similarity
- Assess source quality
- Report failed and partial searches
- Cite evidence precisely

## 1. Build a de-identified case fingerprint

Extract only search-relevant fields:

```text
specialty:
age_band:
sex_if_relevant:
main_presentation:
duration_and_course:
key_positive_findings:
key_negative_findings:
labs_imaging_pathology:
suspected_or_confirmed_diagnosis:
intervention:
response_and_outcome:
rare_or_discriminating_features:
```

Remove identifiers before external calls. Generalize exact dates to duration and exact age to an age band unless age itself is a discriminating clinical feature. Never search using a name, phone number, email, medical-record number, national identifier, exact address, or a pasted unredacted chart.

## 2. Build query variants

Create at least four compact core variants rather than one long narrative. Encode ordinary variants as `concept_groups`: place synonyms and equivalent expressions in the same nested array, and place independently required concepts in separate arrays. The runner compiles OR within a group and AND between groups. Use raw `text` only when source-specific syntax is genuinely required.

1. High-precision: rare finding + anatomical site + suspected diagnosis.
2. Presentation-first: main symptoms + key test/pathology + `case report`.
3. Differential-first: one plausible alternative diagnosis + discriminating finding.
4. Broad synonyms: spelling variants, former names, abbreviations, eponyms, and broader concepts; allow a controlled query without a case-report filter.
5. Chinese: specialty terms plus `病例报告 OR 个案报告 OR 病例讨论`; for traditional Chinese medicine add `医案 OR 验案 OR 名医医案 OR 经方医案` as appropriate.

Translate Chinese clinical terms into common English synonyms and MeSH-like expressions. Keep each API query de-identified and usually below 12 concepts. Do not include every normal result.

## 3. Execute a multi-query plan

Use `run_search_plan.py` and the structure in `search-plan-template.json` for comprehensive work. Preserve query IDs and intents so a result found by several independent formulations receives stronger retrieval support. Treat this as reproducibility metadata, not as a clinical similarity score.

Add `candidate_features` derived from the de-identified fingerprint when deterministic triage is useful. Configure each feature's synonyms, relative weight, required status, optional explicit `mismatch_terms`, and searchable fields in the plan. These settings are case-local and must not become a fixed disease rubric. The emitted `feature_evidence` is document-level matching; it does not replace patient-level comparison or source verification.

Configure final presentation independently with `selection_policy`. An optional `max_detailed_verified_cases` value applies only to patient-level verified close cases after deduplication. It must not cap retrieval, document triage, verification, or the total number of eligible cases. Put eligible cases beyond the detailed budget in a supplementary list and retain them in `search-results.json`.

## 4. Choose retrieval routes

- Always attempt PubMed and Europe PMC for a clinical case-report request when network access exists.
- Add OpenAlex when recall is thin, the condition is rare, or citation expansion is useful.
- Add Crossref only for DOI and publisher-metadata discovery; do not use it as clinical evidence.
- Add Chinese browser sources for Chinese-language evidence, region-specific practice, or Chinese medicine.
- Add specialty libraries only when imaging, pathology, ophthalmology, or patient-safety teaching cases materially help.
- Add WeChat only when requested, when the user supplies an article, or when a known professional account is likely to cover the topic. Use TikHub only with an explicit call budget and keep its provider status separate from article evidence quality.
- Use a local cache for deduplication and longitudinal monitoring, not as an unlabeled replacement for live retrieval.

## 5. Normalize and deduplicate

Preserve these fields where available:

```json
{
  "source_name": "Europe PMC",
  "source_class": "official_literature_api",
  "retrieval_method": "official_api_live",
  "retrieved_at": "ISO-8601 UTC",
  "record_id": "...",
  "pmid": "...",
  "pmcid": "...",
  "doi": "...",
  "title": "...",
  "abstract": "...",
  "authors": ["..."],
  "journal": "...",
  "year": 2025,
  "url": "...",
  "full_text_url": "...",
  "open_access": true,
  "access_scope": "open_full_text",
  "retrieved_evidence_scope": "abstract",
  "license": "CC BY",
  "publication_types": ["case report"]
}
```

Deduplicate in this order:

1. Normalized DOI.
2. PMID or PMCID.
3. Normalized exact title.
4. Fuzzy title plus year and first author, followed by manual confirmation.

Merge identifiers and access links, but preserve every contributing source in `found_via`. Do not count the same article from PubMed, Europe PMC, OpenAlex, a publisher page, and a WeChat repost as five cases.

`access_scope` describes availability. `retrieved_evidence_scope` describes what the connector returned in the current run. A PMCID can therefore produce `access_scope: open_full_text` and `retrieved_evidence_scope: abstract` until the full text is actually opened and inspected.

## 6. Compare similarity

Score clinical similarity separately from source quality. Use the score to organize review, not as a validated medical model.

| Dimension | Suggested weight |
|---|---:|
| Rare/discriminating feature | 20 |
| Main presentation and course | 20 |
| Imaging/pathology/key tests | 20 |
| Confirmed diagnosis or closest differential | 15 |
| Age band, sex, comorbidities | 10 |
| Intervention and response | 10 |
| Outcome/context | 5 |

For every high-ranked case, state matched facts, mismatched facts, and unknowns. A shared diagnostic label without similar presentation is not automatically a close case. A high similarity score does not increase evidence quality.

Do not select a fixed number merely to fill a report. First determine eligibility from the case-local required dimensions and verified evidence. When the eligible set exceeds the configured detailed budget, select the detailed subset using the plan's ordered dimensions, such as clinical similarity, decisive conflicts, evidence completeness, original-source quality, and phenotype or management diversity. These dimensions are configurable guidance, not a universal disease score.

## 7. Assess source quality

Use the labels in `sources.md`. Check:

- Is this the original case or a repost?
- Is the publication record identifiable by DOI, PMID, PMCID, journal, or institutional URL?
- Was full text inspected, or only title/abstract?
- Does the source state peer review or editorial oversight?
- Is the case sufficiently detailed to support the extracted comparison?
- Is the license known?

Case reports are valuable for rare presentations and hypothesis generation, but normally cannot establish incidence, causality, comparative efficacy, or treatment suitability.

## 8. Report failed and partial searches

Include a coverage table even when results are empty:

| Source | Method | Status | Retrieved at | Results | Limitation |
|---|---|---|---|---:|---|
| PubMed | official API live | success | ... | 12 | abstract coverage varies |
| CMCR | browser live | blocked | ... | unknown | login or site unavailable |
| WeChat | user-link ingestion | not requested | ... | 0 | no exhaustive public API |

Use `not_searched`, `success`, `partial`, `blocked`, `subscription`, or `failed`. Never rewrite `failed` as `0 results`.

Begin the final report with three explicit accounting blocks:

1. Route accounting: query families, source routes, and query-source executions, each with its own denominator and status counts.
2. Candidate funnel: provider-reported overlapping hits, returned records, duplicate occurrences removed, unique publication candidates, ranked candidates, verified patient cases, included close cases, detailed close cases shown, additional eligible cases retained, near misses, and exclusions.
3. Dimension triage: case-local dimensions, configured priority/weight, and matched, mismatched, conflicting, and unknown counts.

Use `result_accounting` from `run_search_plan.py` for the live API stage, then extend it with browser, citation-expansion, subscription, Chinese, specialty, and social routes actually attempted. Leave verification fields unset until the corresponding papers and possible duplicate patients have been reviewed. Never translate a publication count directly into a patient-case count.

For persistent output, pass an absolute user-workspace path with `--output-root` and a short de-identified `--output-label`. The runner creates `output/<brief>_<UTC-timestamp>/search-report.md`, `search-results.json`, and `cases/*.md` without overwriting an existing run. The generated case files are candidate-publication dossiers with patient-level verification placeholders. Enrich the same bundle as browser, citation, full-text, Chinese, specialty, or social evidence is reviewed. After verification, report the complete eligible count, the detailed subset, and the retained overflow separately; do not leave the only copy of overflow cases or final evidence in terminal output or temporary files.

## 9. Cite evidence precisely

- Link the DOI or stable source record.
- Identify whether a claim came from title, abstract, full text, or a secondary summary.
- Quote sparingly and preserve the original wording for decisive facts.
- If only a title is visible, do not infer patient details, treatment, or outcome.
- If sources conflict, show the conflict rather than silently reconciling it.

End with a concise safety statement: similarity search supports literature review and clinical reasoning but is not a diagnosis, treatment recommendation, or prediction for an individual patient.

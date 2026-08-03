# Comprehensive search protocol

## Contents

- Objective
- Stage 1: case fingerprint
- Stage 2: query lattice
- Stage 3: source fan-out
- Stage 4: deduplication and triage
- Stage 5: seed expansion
- Stage 6: clinical verification
- Stopping rule
- Quality reporting

## Objective

Maximize useful recall first, then precision. Never promise literal completeness: unpublished cases, inaccessible databases, indexing delay, terminology variation, and closed social platforms make that unverifiable. Instead, make search coverage, query diversity, marginal yield, failures, and stopping decisions reproducible.

Use `comprehensive` mode by default. Use `quick` only when the user explicitly prefers speed or low cost.

## Stage 1: case fingerprint

Create the structured fingerprint defined in `retrieval-workflow.md`. Separate observed facts from suspected diagnoses. Identify two to six discriminating features; a query containing the entire narrative usually has poor recall.

## Stage 2: query lattice

Build at least four independent API query families:

1. `high_precision`: two or three rare/discriminating findings, anatomy, pathology, or exposure.
2. `presentation`: symptoms, course, demographics only; do not assume the diagnosis.
3. `diagnosis_or_differential`: leading diagnosis plus credible alternatives and one discriminating feature.
4. `broad_synonyms`: spelling variants, former disease names, acronyms, eponyms, and broader concepts.

Add `test_or_pathology`, `treatment_or_outcome`, `adverse_event`, or `population_or_context` when they distinguish the case.

For the first three families, normally keep the case-report filter. Run at least one controlled broad query with `case_filter=false` to recover CPCs, diagnostic images, letters, brief reports, and newly indexed cases that lack a formal case-report label. Expect noise and verify these candidates strictly.

Use English variants for PubMed, Europe PMC, and OpenAlex. Add Chinese variants for CMCR, SinoMed, CNKI, Wanfang, VIP, Chinese publisher sites, and WeChat when Chinese coverage matters. For traditional Chinese medicine, search both disease/presentation language and `医案`, `验案`, `名医医案`, `经方医案`, formula names, syndrome patterns, tongue/pulse terms, and historical terminology as applicable.

Copy `search-plan-template.json` to a temporary location, replace the example with de-identified case facts, and run:

```bash
python3 scripts/run_search_plan.py \
  --plan /tmp/case-search-plan.json \
  --mode comprehensive \
  --limit 20 \
  --max-api-searches 30 \
  --workers 4 \
  --pretty
```

The output records each query-source execution and the number of newly discovered unique candidates. Do not report the protocol as complete if the audit lists missing requirements or failed required searches.

## Stage 3: source fan-out

Search in this order while retaining all candidates:

1. PubMed and Europe PMC for every core English query.
2. OpenAlex for broad discovery, citation metadata, and queries with sparse official-index recall.
3. Crossref only when DOI or publisher-metadata discovery is useful; verify clinical facts elsewhere.
4. Chinese databases and case repositories through browser or licensed connectors.
5. Publisher and specialty case libraries when the presentation is imaging-, pathology-, ophthalmology-, or safety-centric.
6. WeChat/TikHub for Chinese professional discussion and source leads, never as a replacement for the original evidence.

Do not stop after finding a convincing diagnosis. Prematurely narrowing to one label causes confirmation bias and lost alternative cases.

## Stage 4: deduplication and triage

Deduplicate across queries and sources using all available aliases, not only one preferred identifier: DOI, PMID, PMCID, or normalized title plus year and first author. Never merge records with conflicting stable identifiers solely because their titles match. Preserve `found_via`, `matched_queries`, `query_intents`, and source occurrences.

Use retrieval confidence only for triage:

- `high`: official index, stable identifier, and explicit case-report signal.
- `medium`: stable identifier plus official indexing or independent query support.
- `discovery_only`: incomplete or third-party-only metadata requiring verification.

Retrieval confidence is not clinical similarity and not evidence strength.

## Stage 5: seed expansion

After identifying two to five verified close seed cases, expand each through references, citations, and related works:

```bash
python3 scripts/expand_related_cases.py \
  --doi '10.xxxx/xxxxx' \
  --providers pubmed,openalex \
  --directions related,references,citations \
  --limit-per-direction 20 \
  --pretty
```

This runs PubMed Similar Articles in addition to OpenAlex citation and related-work expansion. All routes are noisy and may return non-case papers. Reapply the case fingerprint and case-report verification. Inspect references in accessible full text when graph relationships are incomplete.

## Stage 6: clinical verification

For every shortlisted candidate:

1. Verify stable identity and that it describes an actual patient or case series.
2. Record whether evidence came from title, abstract, full text, educational page, or social summary.
3. Extract matched facts, mismatched facts, and unknowns for each weighted clinical dimension.
4. Trace secondary articles and WeChat posts to the original case whenever possible.
5. Exclude papers that merely mention the disease, aggregate cases without patient-level detail, duplicate a previously counted patient, or conflict with the requested presentation on decisive features.
6. Keep near misses in a separate section when they illuminate a differential diagnosis.

## Stopping rule

Stop only when all applicable conditions are met:

- All four core query families ran successfully against PubMed and Europe PMC.
- At least one broad unfiltered query ran and its noise was triaged.
- Required Chinese, specialty, and WeChat routes were executed or their access failures were documented.
- Two to five verified seed cases received backward, forward, and related-work expansion where identifiers allow it.
- Two consecutive independent query or expansion steps each add fewer than two new plausible cases or less than five percent new unique candidates.
- The highest-ranked cases have verified identifiers, source scope, matching facts, important differences, and uncertainty.

Continue when a new terminology branch, diagnosis, author cluster, reference, or source yields material new cases. A time, cost, access, or API limit is a truncation reason, not evidence of saturation.

## Quality reporting

Report:

- Unique candidates before and after verification.
- Included close cases, near misses, duplicates, and exclusions with reasons.
- Query-source coverage and failures.
- Marginal new candidates per search step.
- Full-text versus abstract-only counts.
- Original peer-reviewed, educational, bibliographic-only, and social-source counts.
- Remaining blind spots and whether the stopping rule was satisfied.

Do not claim a recall percentage without a known gold-standard case set. Use terms such as `protocol complete`, `saturated under stated sources`, `access-limited`, or `budget-limited` instead of `all cases found`.

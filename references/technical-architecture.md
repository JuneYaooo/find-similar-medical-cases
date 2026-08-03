# Technical architecture for high-recall similar-case research

## Contents

- Decision summary
- What Deep Research contributes
- Target architecture
- WeChat/TikHub path
- Evaluation plan
- Phased implementation
- Research basis

## Decision summary

Use a deterministic, source-aware medical retrieval core. Add Deep Research as an optional orchestration layer for query planning, browser-only gap filling, iterative follow-up searches, evidence checking, and report writing. Do not let a general research agent replace the retrieval ledger, deduplication, clinical comparison, or source verification.

This boundary matters because a fluent report is not evidence of complete retrieval. Similar-case research needs reproducible queries, source-specific adapters, stable identifiers, patient-level duplicate detection, and separate measures for retrieval confidence, clinical similarity, and source quality.

## What Deep Research contributes

The useful patterns shared by OpenAI Deep Research and open-source implementations such as LangChain Open Deep Research, GPT Researcher, and the Hugging Face smolagents example are:

- clarify the task and write a search plan before browsing;
- fan out independent research threads, then iterate when evidence exposes a new term or gap;
- retain the search and source trail;
- compress retrieved material before final synthesis;
- attach claims to sources and verify citation support;
- keep long-running work recoverable;
- stop by measured saturation or a stated resource limit, not because the first plausible answer was found.

These patterns are valuable around the medical retrieval engine. They do not by themselves solve biomedical vocabulary, case-report filtering, duplicate publication, duplicate patients, source quality, or clinical feature matching.

## Target architecture

```text
de-identified case
       |
       v
case fingerprint + query lattice <---- optional Deep Research planner
       |
       v
parallel source adapters
  | official APIs | scholarly APIs | browser databases | WeChat/TikHub |
       |
       v
canonical candidate/evidence store ----> immutable query-run ledger
       |
       +--> identity and patient-level deduplication
       |
       +--> hybrid candidate generation
       |      BM25/FTS + MedCPT + PubMed Similar + citation graph
       |
       +--> RRF fusion --> biomedical reranker --> clinical feature comparison
       |
       v
evidence verifier + claim-to-source ledger
       |
       v
saturation monitor ----> optional follow-up queries / seed expansion
       |
       v
source-separated report
```

### 1. Intake and privacy boundary

Create a structured fingerprint before any external call. Keep observed facts separate from suspected diagnoses. Remove direct identifiers, exact dates, exact locations, and unnecessary rare identifying combinations. A later structured representation may map findings to MeSH, UMLS/SNOMED CT where licensed, HPO, and GA4GH Phenopackets; the raw narrative must not be required by every provider.

### 2. Query planner

Produce multiple independent query families rather than one long query:

- discriminating-feature/high-precision;
- presentation-first without the presumed diagnosis;
- diagnosis and differential branches;
- synonyms, historical names, eponyms, abbreviations, spelling variants;
- pathology, imaging, laboratory, exposure, treatment, adverse-event, or outcome branches when discriminating;
- English and Chinese variants routed to appropriate sources;
- one controlled query without a formal case-report filter.

The planner may use an LLM, but its output must validate against `search-plan-template.json`. Persist the final query text, rationale, source routing, filters, and timestamp.

### 3. Source adapters and freshness

Different channels require different retrieval paths. “Live” means querying the provider's current index during the task; it does not mean the index has no publication delay.

| Channel | Default path | Execution policy | Authority |
|---|---|---|---|
| PubMed, Europe PMC | official APIs | live on each comprehensive request | evidence backbone and metadata verification |
| PubMed Similar Articles | NCBI ELink `neighbor_score` | live for each verified seed with a PMID | official similarity-based candidate generator |
| OpenAlex | third-party scholarly API | live for discovery and citation expansion | discovery only until verified |
| Crossref | official DOI metadata API | on demand | identity and metadata, not clinical evidence |
| CNKI, Wanfang, VIP, SinoMed, CMCR | browser or licensed connector | live on demand; log authentication/access limits | bibliographic discovery; inspect original record/article |
| Publisher and specialty libraries | browser search | live on demand after API stage or when specialty-specific | original article or labeled educational evidence |
| WeChat | canonical user link, in-app/manual search, or bounded TikHub API | live on demand; paid calls require a visible budget | secondary/social source until claims trace to originals |
| Local index/cache | SQLite/Postgres plus permitted files | snapshot, always show build time | recall and speed supplement, never silently reported as live |

Do not build scrapers around undocumented endpoints when a browser or licensed connector is the supported route. A provider that locates a record is not necessarily the publisher or evidence authority.

### 4. Canonical data and provenance

Store three related objects instead of only a final list:

1. `QueryRun`: query, intent, provider, connector version, live/snapshot state, start/end time, filters, total hits, returned count, errors, cost, and marginal unique yield.
2. `Candidate`: DOI, PMID, PMCID, source record IDs, normalized title, bibliographic metadata, abstract/full-text scope, license, source occurrences, and seed relationships.
3. `EvidenceClaim`: candidate ID, normalized claim, quoted or precisely located supporting text, evidence scope (`title`, `abstract`, `full_text`, `educational_page`, `social_post`), source URL, support status, and verifier notes.

Keep raw provider responses in a time-limited debug cache when terms permit it. Keep normalized metadata and hashes longer. Never redistribute licensed full text merely because it was retrievable.

### 5. Candidate generation and ranking

Use multiple retrieval systems because biomedical evaluations show that no single corpus/retriever is consistently best.

Recommended sequence:

1. Union candidates from PubMed/Europe PMC queries, Chinese routes, PubMed Similar Articles, and citation/related-work expansion.
2. Add local lexical retrieval with SQLite FTS5 or another BM25 implementation over title, abstract, MeSH/keywords, and extracted case features.
3. Add dense retrieval with MedCPT embeddings for biomedical query-document matching. Keep the model name/version and embedding date in the index manifest.
4. Fuse lexical, dense, official-similarity, and graph result ranks with Reciprocal Rank Fusion (RRF). Do not average provider scores whose scales have different meanings.
5. Apply a biomedical cross-encoder/reranker to the top 100–200 candidates.
6. Extract structured case features for the top 20–50 and compare matches, decisive mismatches, and unknowns. Negative findings, timing, anatomy, pathology, and treatment response should be explicit rather than buried in one embedding.
7. Verify that each selected item is an actual case or patient-level series and inspect possible duplicate patients/publications.

Avoid a single opaque “confidence” number. At minimum retain:

- `retrieval_confidence`: how well identity and retrieval are corroborated;
- `clinical_similarity`: feature-level similarity to the de-identified case;
- `source_quality`: original peer-reviewed, educational, bibliographic-only, secondary, or social/unverified;
- `citation_support`: whether the displayed source actually supports each reported claim.

### 6. Seed expansion and iterative research

For two to five close, verified seeds, run both:

- PubMed Similar Articles, which uses NCBI's official article-similarity route;
- backward references, forward citations, and related works through OpenAlex or another graph provider.

Then generate follow-up queries from new terminology, author clusters, pathology names, or differentials. This is the best place for an iterative Deep Research controller such as i-MedRAG-style follow-up querying. Every generated query still passes the privacy check and enters the query ledger.

### 7. Deduplication

Perform two levels of deduplication:

- publication identity: DOI, PMID, PMCID, title/year/author, corrections, translations, and multi-index records;
- case identity: institution, authors, age/sex, dates rounded to safe granularity, unusual findings, intervention, images, and explicit “previously reported” statements.

The second level should initially be human-reviewed. An uncertain duplicate should be clustered and labeled, not automatically discarded.

### 8. Evidence verification and reporting

The report writer may use an LLM only after retrieval and evidence objects exist. It must produce a claim-to-source ledger and fail closed when the cited passage does not support the claim. Separate original peer-reviewed cases, educational cases, Chinese bibliographic records, and WeChat/social leads.

Adapt the DeepResearch Bench FACT pattern:

1. split the draft into externally verifiable statements;
2. map every statement to one or more URLs and evidence locations;
3. remove duplicate citations that add no support;
4. judge entailment/support, not merely topical relevance;
5. report unsupported or abstract-only statements as uncertain.

### 9. Saturation and recovery

Track marginal new plausible cases by query and expansion step. Stop only under the rule in `comprehensive-search.md`. Persist state after planning, retrieval, deduplication, seed expansion, and verification so browser failures or API limits can be resumed without rerunning paid calls.

## WeChat/TikHub path

TikHub is useful as a paid retrieval connector for WeChat account search, article search, account history, and canonical article acquisition where its current API and terms permit. It does not turn a WeChat post into primary medical evidence.

Use this sequence:

1. search de-identified concepts and likely specialty accounts with a strict call/page cap;
2. verify account identity against the maintained allowlist, hospital/society affiliation, and canonical account metadata;
3. store canonical article URL, account, date, author, retrieval provider, endpoint, and call cost;
4. extract cited DOI/PMID/title/hospital case source;
5. retrieve and rank the original literature separately;
6. label uncited clinical narratives as `social_or_unverified` and never merge their quality with peer-reviewed cases.

A display-name match is insufficient account verification. Search results are not exhaustive because WeChat and third-party indexes have opaque and changing coverage.

## Evaluation plan

### Retrieval benchmarks

Use three complementary sets:

- RELISH for biomedical similar-article retrieval;
- TREC Clinical Decision Support topics/qrels for case-based literature retrieval;
- an internal, de-identified set of real case fingerprints adjudicated by at least two clinicians, including Chinese and WeChat-discovered cases where permitted.

Public benchmarks test literature relevance, not patient-level clinical equivalence, so the internal set is essential.

### Metrics

Measure by source class and overall:

- Recall@50, Recall@100, and Recall@200;
- nDCG@10 and MRR;
- unique relevant cases added by each query family/source;
- duplicate-publication and duplicate-patient error rate;
- citation precision and claim-support accuracy;
- source coverage and full-text verification rate;
- latency, API calls, paid cost, and resume success rate.

Do not report estimated recall as actual recall unless the test query has judged relevance labels. In production, report protocol coverage and saturation instead.

### Ablations

Before adopting a component, compare:

- API keyword baseline;
- baseline + PubMed Similar Articles;
- baseline + BM25;
- BM25 + MedCPT with RRF;
- hybrid + reranker;
- hybrid + structured clinical feature reranking;
- each configuration with and without citation expansion.

This shows whether added complexity improves relevant-case recall instead of only producing more records.

## Phased implementation

### V1 — current repository

- deterministic multi-query PubMed, Europe PMC, and OpenAlex API stage;
- optional Crossref DOI and publisher-metadata discovery connector;
- parallel source execution with provider-specific concurrency limits;
- query-run coverage and marginal-yield ledger;
- DOI/PMID/PMCID/title deduplication;
- PubMed Similar Articles plus OpenAlex references/citations/related works;
- browser plans for Chinese/specialty sources;
- bounded TikHub connector and source-class separation.

### V2 — local evidence store

- SQLite schema for query runs, canonical candidates, aliases, evidence claims, exclusions, and costs;
- HTTP cache with TTL and provider-aware retry/backoff;
- FTS5/BM25 local retrieval;
- resumable run ID and machine-readable inclusion/exclusion ledger.

### V3 — hybrid biomedical retrieval

- MedCPT document embeddings and versioned index manifest;
- RRF fusion and a biomedical reranker;
- structured clinical feature extractor with explicit unknown values;
- benchmark harness and ablation reports.

### V4 — clinical semantics and monitoring

- HPO/MeSH mappings and optional Phenopacket import/export;
- clinician-adjudicated multilingual gold set;
- duplicate-patient review workflow;
- scheduled monitoring of saved queries and verified WeChat accounts, with new-item diffing and budget controls.

Do not introduce LangGraph, GPT Researcher, or another orchestration framework until recovery, branching, and tool extensibility justify the dependency. The current standard-library scripts are easier to audit. A future controller should call the same source adapters and write the same data contracts rather than create a second retrieval path.

## Research basis

Accessed 2026-08-03 unless otherwise stated.

- OpenAI, Deep Research guide: <https://developers.openai.com/api/docs/guides/deep-research>
- OpenAI Cookbook, Deep Research API introduction: <https://cookbook.openai.com/examples/deep_research_api/introduction_to_deep_research_api>
- LangChain, Open Deep Research: <https://github.com/langchain-ai/open_deep_research>
- GPT Researcher: <https://github.com/assafelovic/gpt-researcher>
- Hugging Face, Open Deep Research with smolagents: <https://huggingface.co/learn/cookbook/en/open_deep_research>
- DeepResearch Bench, RACE and FACT evaluation: <https://arxiv.org/abs/2506.11763>
- MedCPT: Jin et al., *Bioinformatics* (2023), DOI <https://doi.org/10.1093/bioinformatics/btad651>
- MIRAGE/MedRAG: Xiong et al., ACL Findings (2024), DOI <https://doi.org/10.18653/v1/2024.findings-acl.372>
- BMRetriever: Xu et al., EMNLP (2024), DOI <https://doi.org/10.18653/v1/2024.emnlp-main.1241>
- RELISH benchmark: Brown et al., *Database* (2019), DOI <https://doi.org/10.1093/database/baz085>
- Evaluation of biomedical similar-article recommendation: DOI <https://doi.org/10.1016/j.jbi.2022.104106>
- NCBI PubMed Similar Articles help: <https://pubmed.ncbi.nlm.nih.gov/help/#similar-articles>
- NCBI ELink documentation: <https://www.ncbi.nlm.nih.gov/books/NBK25499/#chapter4.ELink>
- TREC Clinical Decision Support tracks: <https://www.trec-cds.org/>
- Human Phenotype Ontology: <https://hpo.jax.org/>
- GA4GH Phenopackets: <https://www.ga4gh.org/product/phenopackets/>

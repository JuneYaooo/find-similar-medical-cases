![Find Similar Medical Cases](./assets/readme-cover.svg)

# Find Similar Medical Cases

A bilingual (Chinese/English) similar-medical-case retrieval skill for medical researchers, executed by Codex to run reproducible search, verification, comparison, and evidence synthesis.

Searching for cases is rarely as simple as finding one paper. The hard parts are rephrasing the query several ways, following reference chains, deduplicating results, and judging whether two cases actually resemble each other. This project hands those steps to Codex and leaves behind verifiable sources and an explicit search scope.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)

## Who it is for

The project primarily serves medical researchers, and is also useful to clinicians, case-report authors, and medical information specialists for case review, case-discussion preparation, research-topic exploration, and similar-case evidence synthesis. It emphasizes auditable search routes, patient-level deduplication, and evidence from the original source — search results are never presented as diagnosis or treatment advice.

Unless the user explicitly restricts the language or asks only for a quick initial pass, a full search plans the major English and Chinese case sources together by default. English coverage leans on PubMed, Europe PMC, and the major case-report journals; Chinese coverage leans on the China Clinical Case Repository (CMCR), SinoMed, CNKI, Wanfang, VIP, and the Chinese Medical Journal Network. Sources that are inaccessible or behind a subscription are recorded explicitly, never silently dropped. "Coverage" here means these primary search routes were executed and reported, not that all published or unpublished cases were proven to be found.

## How to use

First, send this in Codex:

> Please install this skill: https://github.com/JuneYaooo/find-similar-medical-cases

After installation, open a new conversation and describe the already-de-identified case:

> Help me find similar cases: an adult patient developed hypertension, hypokalemia, metabolic alkalosis, low renin, and low aldosterone after posaconazole. Explain the similarities and differences for each case, and which sources you actually searched.

You do not need to craft a professional search string first. Age range, symptom order, key findings, medication or exposure, and treatment response are more useful than a full medical record. When information is insufficient, Codex asks follow-up questions.

A full search writes a result bundle named after a de-identified brief and a UTC timestamp into the `output` directory of the current workspace: `search-report.md` holds the overall report, `search-results.json` holds the reproducible search ledger, and `cases/` holds an individual page for each ranked candidate. Candidate pages are not labeled as distinct patient cases until they have been verified one by one.

Search and verification never stop early just to hit or stay under a fixed number of cases. The number of detailed final displays is separately configurable in the case plan — for example 50: when patient-level verification yields no more than 50 similar cases, all are shown; when there are more, the 50 with the best ranking and representativeness are shown in detail, while the remaining qualifying cases stay in the supplementary list and machine-readable results. This mechanism is triggered by the actual count of qualifying cases; it does not maintain a hardcoded "common/rare disease" list.

## What it does

- Organizes different search angles from clinical presentation, findings, medications, and timing, rather than searching a single diagnosis name.
- Covers the major English and Chinese case routes in a full search: PubMed, Europe PMC, OpenAlex, plus available entrances such as CMCR, SinoMed, CNKI, Wanfang, VIP, and the Chinese Medical Journal Network.
- Follows similar articles, references, and later citations from a close candidate paper.
- Removes duplicate records by DOI, PMID, title, and author.
- Compares, point by point, the similarities, important differences, and what the original text does not state.
- Records which sources were searched, which were limited or failed, and why searching stopped.

The point is not to produce a seemingly precise "similarity score," but to lay the reasoning open so a human can return to the original text and verify it.

## How the search works

In one sentence: **cast a wide net in several directions first, then verify and compare each hit.**

Codex does not free-search once it sees a diagnosis name. Work is split into two layers: Codex understands the case, adds synonyms, decides what to search next, and reads and compares evidence; a fixed retrieval layer executes queries, records every hit, normalizes bibliographic data, deduplicates, and tracks citations. This keeps language understanding while leaving an auditable search record.

![Similar-case search logic](./assets/search-logic.svg)

### 1. Build a "case fingerprint"

Before searching, remove identifying information, then keep only what actually affects retrieval from the narrative: age range, main presentation, disease course, key positive and negative findings, imaging or pathology, medication or exposure, treatment response, and outcome.

Observed facts and suspected diagnoses are recorded separately. Even if the initial diagnosis is wrong, this keeps the search from being steered into too narrow a direction. Usually 2–6 of the most discriminating features are selected as the focus for subsequent combined queries.

### 2. Split the case into multiple search routes

A long full record usually does not search well, so it is split into several mutually independent angles:

- **High-precision route**: combinations of rare findings, special tests, or medication exposure.
- **Presentation-first route**: symptoms, course, and findings only, without a diagnosis name for now.
- **Diagnosis-and-differential route**: tries the primary suspicion and plausible alternative diagnoses separately.
- **Broad route**: adds old terms, abbreviations, spelling variants, and synonyms, and keeps one search not restricted to "case report".
- **Supplementary branches**: pathology, imaging, treatment response, adverse reactions, and Chinese phrasing when needed.

If the same paper is found by several different routes, its retrieval signals are relatively stable; that does not mean it is clinically more similar.

The search plan groups synonymous expressions into the same concept group and the program generates "OR within a group, AND across groups" queries. Concepts and synonyms come from the current case; the code does not presuppose how any disease or drug must be searched. Free-text queries can still be kept when a database requires special syntax.

### 3. Search source by source

PubMed and Europe PMC are the backbone of English medical literature. OpenAlex widens the candidate pool and finds citation relationships; Crossref only fills in DOI and publication data and is not used to establish clinical facts. A full search also plans the major Chinese case and literature entrances — CMCR, SinoMed, CNKI, Wanfang, VIP, and the Chinese Medical Journal Network — and adds specialty case databases and channels such as WeChat when the case calls for them. Every source is labeled with its access status and evidence type.

Every query records its source, query intent, execution time, number of returns, how many records this step added, and any failure or restriction reason. "Query failed" and "no results" are two different things.

The final results split the accounting: planned and actually-successful query routes, the sources actually called, the number of executions per query–source combination, database-reported overlapping hits, records actually returned, deduplicated paper candidates, and the number of patient cases confirmed after per-case verification. The number of paper candidates is not written as the number of cases, because one paper may contain several patients and several papers may describe the same patient.

### 4. Merge and deduplicate results across sources

The same paper can appear in PubMed, Europe PMC, OpenAlex, and a publisher's page at once. The project merges records by DOI, then PMID, PMCID, normalized title, year, and first author, while keeping the routes through which each record was found.

If two records carry stable identifiers that conflict, they are not merged even when the titles match. Different papers may also describe the same patient; such cases are flagged as suspected duplicates and held for further verification.

### 5. Follow key papers after the initial pass

The first-round candidates are checked first: is it really a case report or case series, does it have stable identifiers, and is the title, abstract, or full text currently visible. Then 2–5 close, identity-confirmed papers are chosen as "seeds."

Their similar articles, references, later citations, and related research are then reviewed. Newly discovered disease names, pathological terms, or author leads return to the earlier search stage and start the next round. Many rare cases are picked up exactly at this step.

### 6. Judge "how similar" item by item

Comparison is not just about the disease name, nor does it rely on a single semantic score. Review is currently organized around the following dimensions:

| Comparison dimension | Reference weight | What it mainly looks at |
| --- | ---: | --- |
| Rare or discriminating features | 20 | Whether the most unusual, scope-narrowing findings appear |
| Main presentation and course | 20 | Whether symptom clusters, order, and progression are close |
| Imaging, pathology, and key findings | 20 | Whether objective evidence matches |
| Diagnosis or closest differential | 15 | Whether the final diagnosis and exclusion process are relevant |
| Age, sex, and baseline condition | 10 | Whether the patient background is comparable |
| Intervention and treatment response | 10 | Whether medication, management, and later changes are close |
| Outcome and clinical scenario | 5 | Whether follow-up outcomes and setting are similar |

Each dimension must state **same, different, unknown** separately. These weights only order the reading, not clinically validated diagnosis probabilities. Case similarity, source quality, and retrieval confidence are always judged separately.

Before the item-by-item human comparison, the program can run an explainable first pass over titles and abstracts using the case features from the current search plan. Features, synonyms, and relative weights are defined per case; anything the original text does not mention stays "unknown", and only contradiction expressions explicitly listed in the plan are marked as mismatches. This first pass only decides what to read first; it is not a clinical similarity score.

When the top of the list needs further improvement, you can optionally run a local MedCPT cross-encoder to rescore the pre-ranked candidate prefix. Required features, explicit contradictions, whether the record is an actual case report, and key title features remain ranking guardrails; the model only fine-ranks among candidates whose signals are comparable, and raw model scores are never interpreted as diagnosis probabilities. This heavier optional dependency is not installed or enabled by default.

### 7. Check every conclusion against its source

A title can prove very little, and an abstract must not be conflated with the full text. The report marks whether a given judgment actually comes from the title, the abstract, the full text, a teaching page, or second-hand retelling, and returns to the original case wherever possible.

Important clinical conclusions are bound to a specific source. If the original text does not provide age, findings, or outcome, the report writes "unknown" rather than filling gaps from common sense. WeChat articles or reposts can help surface leads but do not automatically gain the same evidence status as the original paper.

### 8. Decide when to stop

Finding the first plausible-looking paper is not the end. A full run must at least cover the four query types — high precision, presentation, diagnosis and differential, and broad synonyms — and run similar-article and citation expansion on the closer seed papers.

If two consecutive independent queries or expansions each add fewer than 2 reasonable candidates, or less than 5% of the existing candidates, the search can be considered saturated within the declared source scope. If the run stops because of access, time, cost, or service failure, the report states the limitation plainly and does not call it "fully searched".

## What the output looks like

![Example similar-case search record](./assets/report-preview.svg)

Each included case keeps its original title, year, and stable link, and states whether verification reached the title, abstract, or full text. Similarities and differences between cases are written separately; not found, inaccessible, and not stated in the original are also written separately.

The report closes by stating the scope of this search. It does not turn "searched a few common sources" into "found all cases".

## Optional reranking

To further improve the top of the list, you can enable a local MedCPT cross-encoder on `run_search_plan.py` to rescore the pre-ranked candidate prefix. Required features, explicit contradictions, whether the record is an actual case report, and key title features remain ranking guardrails; the model only fine-ranks among candidates whose signals are comparable, and raw model scores are never interpreted as diagnosis probabilities. This heavier optional dependency is not installed or enabled by default.

```bash
python3 -m pip install -r requirements-reranker.txt
python3 scripts/run_search_plan.py \
  --plan /tmp/case-search-plan.json \
  --mode comprehensive \
  --limit 20 \
  --reranker medcpt \
  --rerank-top-k 50 \
  --pretty
```

The default model is `ncbi/MedCPT-Cross-Encoder`. The program records the requested and actually-resolved model revision, device, batch size, truncation length, the raw logit for each candidate, and the before/after rank. When the model or its dependencies are unavailable, the pre-reranker order is preserved and the status is written as `skipped`; add `--reranker-required` when the run should fail strictly instead. The model only processes the de-identified case fingerprint and the currently retrieved titles/abstracts on your own machine, but the model files still need a one-time network download on first use.

If you use an authorized SiliconFlow API instead, PyTorch is not needed:

```bash
export SILICONFLOW_API_KEY='set in your local shell; never commit it to git'
python3 scripts/run_search_plan.py \
  --plan /tmp/case-search-plan.json \
  --mode comprehensive \
  --limit 20 \
  --reranker siliconflow \
  --rerank-top-k 50 \
  --pretty
```

You can also copy [.env.example](./.env.example) to `.env`. The default SiliconFlow model is `BAAI/bge-reranker-v2-m3`; the request sends the de-identified case fingerprint and the candidate titles/abstracts to a remote service, so confirm your organization's data-transfer, privacy, and terms-of-service requirements before use. API keys are read only from environment variables or the git-ignored `.env`, and are never written into result JSON, Markdown, or error messages.

## Other ways to ask

> Don't assume the diagnosis first. Search from this set of clinical findings and keep the differential directions separate.

> Besides English papers, add Chinese case reports and specialty teaching cases. Do not mix different source types together.

> Use this paper as the starting point and keep checking its references, its citing papers, and similar articles: paste the paper link.

> This time only do a quick initial pass. Tell me directly what has not been searched and do not call it a complete search.

## Where it can search

English medical literature is centered on PubMed and Europe PMC, with OpenAlex and the major case-report journals adding discovery and citation relationships. Chinese cases cover the main entrances — CMCR, SinoMed, CNKI, Wanfang, VIP, and the Chinese Medical Journal Network — and specialty resources in imaging, pathology, ophthalmology, and others can be added per case type.

Some full texts and Chinese databases require a personal account or institutional subscription. Content such as WeChat articles can only serve as leads; key facts should still be verified against the paper or an institutional source. When a paid source is involved, Codex first states the cost and asks for consent.

## Boundaries of use

This skill is aimed at medical research, and fits similar-case review for both common and rare diseases, as well as atypical presentations, adverse drug reactions, unusual treatment responses, imaging or pathology combinations, case discussions, and research-topic selection.

It is not for personal diagnosis, prescribing, treatment choices, or prognosis, and it does not replace a formal systematic review. Case similarity is not the same as identical diagnosis, and case reports themselves can suffer from missing information and selective publication.

Unpublished cases, indexing delays, language differences, access restrictions, and closed platforms all cause omissions, so "search complete" here applies only to the scope stated in the report.

## Privacy

Do not send names, contact details, identity documents, medical-record numbers, exact addresses, exact visit dates, test sheets with identifying information, or full medical-record screenshots. Rare combinations of personal characteristics can also make a patient identifiable — keep only the clinical facts needed for the search.

Even after information has been de-identified, you must still comply with your institution's privacy, ethics, and data-management requirements.

## Project resources

- [Complete skill documentation](./SKILL.md)
- [Sources and boundaries of use](./references/sources.md)
- [Retrieval workflow and stopping conditions](./references/retrieval-workflow.md)

## Community

[**LINUX DO — Chinese Developer Community**](https://linux.do/)

[MIT License](./LICENSE)

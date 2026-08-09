---
name: find-similar-medical-cases
description: Bilingual, source-grounded similar-case research for medical researchers. Comprehensively search, verify, compare, and synthesize cases across major English sources such as PubMed and Europe PMC; major Chinese case repositories and literature databases such as CMCR, SinoMed, CNKI, Wanfang, VIP, and the Chinese Medical Journal Network; scholarly and citation APIs; specialty libraries; publisher sites; and authorized WeChat routes. Use when a user asks to find similar clinical cases, 病例报告, 个案报告, 医案, 罕见病例, diagnostic or treatment analogues, or to build a reproducible high-recall case search while keeping language coverage, source type, retrieval method, evidence scope, similarity, and uncertainty explicit.
---

# Find Similar Medical Cases

Support medical researchers conducting reproducible bilingual case discovery, comparison, and evidence review. Maximize useful recall, then verify and rerank for accuracy without presenting retrieval results as diagnosis or treatment advice. Keep English and Chinese coverage explicit, and keep peer-reviewed papers, educational cases, database records, and social-media articles visibly separate. Never equate broad source coverage with guaranteed completeness.

Resolve the directory containing this `SKILL.md` as the Skill directory. Read references relative to that directory and run every bundled command with that directory as its working directory; never assume the user's current project contains `scripts/` or `references/`.

## Required workflow

1. Remove identifiers before sending any query to an external service. Exclude names, contact details, record numbers, exact addresses, exact admission dates, and unneeded rare identifying details.
2. Convert the request into a compact case fingerprint: age band, sex if relevant, main presentation, duration, key positive and negative findings, imaging/pathology/labs, suspected diagnoses, interventions, response, outcome, and specialty.
3. Read [references/comprehensive-search.md](references/comprehensive-search.md), [references/retrieval-workflow.md](references/retrieval-workflow.md), and [references/technical-architecture.md](references/technical-architecture.md). Use the deterministic medical retrieval core; use a Deep Research agent only as an optional planner, browser gap-filler, iterative query generator, evidence checker, or report writer. Build a query lattice that separates high-precision, presentation-first, diagnosis/differential, broad-synonym, and applicable test/treatment variants. Represent ordinary queries as `concept_groups`: put interchangeable expressions in one group and independent concepts in separate groups so the script compiles explicit OR-within-group and AND-between-group logic. Use legacy free text only for provider-specific syntax that the structured form cannot express.
4. Read [references/sources.md](references/sources.md) before choosing sources. Unless the user explicitly limits language or requests a quick pass, make every comprehensive plan bilingual: run the core English queries through PubMed and Europe PMC, use OpenAlex and major case journals for discovery as applicable, and attempt the principal Chinese routes CMCR, SinoMed, CNKI, Wanfang, VIP, and the Chinese Medical Journal Network through available browser or licensed access. Route each source by its supported access method; never assume every website has an API. Record blocked, subscription-only, or unavailable Chinese routes instead of silently omitting them. Use Crossref only as optional DOI/publisher-metadata discovery, not as clinical evidence or a replacement for PubMed and Europe PMC.
5. Copy [references/search-plan-template.json](references/search-plan-template.json) to a temporary file, replace the example with de-identified facts, and define `candidate_features` from this case rather than from a global disease checklist. Give each feature case-specific synonyms and relative weight; add `mismatch_terms` only for text that explicitly contradicts the feature. Do not treat an unmentioned feature as a mismatch. Configure `selection_policy` separately: it may limit how many verified close cases receive full detailed presentation, but it must not limit retrieval, screening, verification, or the total eligible-case count. A value such as `max_detailed_verified_cases: 50` naturally presents every eligible rare case when fewer than 50 exist and moves only the excess to a supplement when more exist; never classify diseases through a hard-coded common/rare list. Resolve the user's workspace `output` directory to an absolute path before changing to the Skill directory. Run the comprehensive live API stage and create a timestamped output bundle with a short de-identified label:

   ```bash
   python3 scripts/run_search_plan.py --plan /tmp/case-search-plan.json --mode comprehensive --limit 20 --max-api-searches 30 --workers 4 --output-root '/absolute/user/workspace/output' --output-label '<de-identified-brief>' --pretty
   ```

   When the optional dependencies in `requirements-reranker.txt` and the local model are available, add `--reranker medcpt --rerank-top-k 50` to rerank the initial candidate prefix with `ncbi/MedCPT-Cross-Encoder`. Keep required-feature, explicit-mismatch, actual-case, and title-feature guardrails ahead of the model signal. Record the requested and resolved model revision, raw logit, input evidence scope, and before/after rank. Use `--reranker-required` only when failure should abort the run; otherwise preserve the pre-reranker order and report `skipped`. Never present a reranker logit as a probability or validated clinical similarity.

   When the user has authorized a remote provider and the case has been de-identified, `--reranker siliconflow` may use `BAAI/bge-reranker-v2-m3` through `SILICONFLOW_API_KEY`. Treat the provider as an external processing route: record endpoint, model, request status, and evidence scope; never store or print the key; and report privacy, data-transfer, availability, and cost limitations. Use the same required-feature, explicit-mismatch, actual-case, and title-feature guardrails and fallback semantics as the local reranker.

   Use `scripts/search_cases.py` only for a deliberately quick single-query pass. Do not call a quick pass comprehensive.

6. Generate browser searches for sources without a supported API:

   ```bash
   python3 scripts/build_browser_searches.py --query '<Chinese or English query>' --pretty
   ```

   Open only the relevant generated searches. Respect authentication, subscriptions, robots rules, rate limits, and publisher terms. Do not bypass access controls.
7. For WeChat, read [references/tikhub-wechat.md](references/tikhub-wechat.md). Prefer user-supplied canonical article links or a maintained account allowlist. When `TIKHUB_API_KEY` is available and the user authorizes paid retrieval, use the bounded TikHub connector:

   ```bash
   python3 scripts/search_wechat_tikhub.py --dry-run --max-calls 6 --pretty collect --query '<de-identified keywords>' --pages 1 --details 5
   ```

   Inspect the cost plan before removing `--dry-run`. Otherwise use manual WeChat/Sogou search. Do not claim comprehensive coverage and do not bulk-crawl `mp.weixin.qq.com` or Sogou results.
8. Select two to five verified close seed papers and expand them through backward references, forward citations, and related works:

   ```bash
   python3 scripts/expand_related_cases.py --doi '<verified DOI>' --providers pubmed,openalex --directions related,references,citations --limit-per-direction 20 --pretty
   ```

9. Deduplicate across all query and source aliases. Treat reposts and multi-index appearances as the same case unless patient-level evidence shows otherwise.
10. Compare cases using explicit matching, mismatching, and unknown facts. Rank clinical similarity separately from retrieval confidence and source quality. Verify and patient-deduplicate every plausible eligible case before counting it. Do not stop verification merely because a detailed-presentation budget has been reached.
11. Build a claim-to-source ledger for the final report. Each externally verifiable clinical claim must identify its candidate, URL, evidence scope (`title`, `abstract`, `full_text`, `educational_page`, or `social_post`), supporting passage or precise location, and support status. A topical citation is not sufficient.
12. Apply the stopping rule in `comprehensive-search.md`, then produce a source-aware report.

## Output artifact contract

Store the final work under `output/<de-identified-brief>_<UTC-timestamp>/`. Keep `search-report.md` as the overall human-readable report, `search-results.json` as the complete machine-readable retrieval and eligibility ledger, and one ranked candidate file per retrieved publication under `cases/`. Candidate files must state that patient-level verification is pending until completed. After verification, distinguish the total eligible close-case count from the smaller detailed-presentation set. Keep every eligible case in the machine results and a supplementary eligible-case list when the configured detailed limit is exceeded; the limit must never silently discard or relabel eligible cases. Add browser, Chinese, specialty, citation-expansion, full-text, and social findings used later in the workflow to the same bundle rather than leaving the only copy in transient tool output. Update the overall report and relevant case files after verification, and return a clickable link to `search-report.md`.

## Retrieval policy

- Treat API and browser searches as live only when executed during the current request. Always show `retrieved_at`.
- Treat TikHub as a paid third-party retrieval route, not as an original evidence source. Report call count and estimated cost, and trace every article's clinical claims to the article or its cited primary source.
- Explain that live retrieval searches the source's current index, which may lag publication and is not equivalent to live clinical data.
- Use cached/local records only as an explicitly labeled supplement. Never silently replace a failed live search with cached results.
- Preserve every query variant, source execution, marginal new-candidate count, seed expansion, exclusion reason, and stopping decision. Do not claim a recall percentage without a gold-standard case set.
- Fuse future lexical, dense, official-similarity, and citation-graph rankings by rank fusion such as RRF; do not average scores with incompatible meanings. Keep model/index versions in provenance.
- Label unsupported, blocked, subscription-only, or failed sources. Do not infer that zero returned results means zero cases exist.
- Use PubMed and Europe PMC as the default evidence backbone. Use OpenAlex and similar services for discovery and citation expansion, then verify promising records against the publisher, PubMed, Europe PMC, or DOI landing page.
- Quote only the minimum evidence needed. Store or redistribute full text only when its license permits it.
- Treat `access_scope` as availability and `retrieved_evidence_scope` as what the connector actually retrieved. Never imply that full text was inspected merely because a PMCID or open-full-text link exists.
- Treat `feature_evidence` as configurable document triage, not validated clinical similarity. Review its matched, mismatched, conflicting, and unknown evidence before assigning clinical similarity.
- Preserve original titles and bibliographic metadata. Write summaries in the user's language.

## Required output contract

Start with a one-paragraph de-identified search fingerprint and list the query variants used. Then report:

1. **Route accounting**: separately count supported, planned, attempted, and successful query families; supported, planned, attempted, and usable source routes; and planned, successful, and failed query-source executions. Show English and Chinese coverage separately. Do not collapse these distinct meanings into one ambiguous path count. Include browser, subscription, Chinese, specialty, citation-expansion, and social routes when they were attempted outside the API stage.
2. **Candidate funnel**: report overlapping provider-index hits, records actually returned, duplicate record occurrences removed, unique publication candidates, document-triaged candidates, ranked candidates, patient-level cases verified, included close cases, detailed close cases shown, additional eligible cases retained, near misses, and exclusions. Never call hits, returned records, or deduplicated publications patient cases. Fill the verified-case fields only after source-level and patient-level review.
3. **Dimension-based triage and selection**: list the case-local dimensions in priority order with their relative weights and required status. For each dimension and shortlisted candidate, show matched, mismatched, conflicting, and unknown evidence. State the criteria used to form any review queue and detailed-presentation set; do not apply an unstated fixed threshold. Retrieve and verify by relevance rather than a target count. Apply any configured maximum only to the post-verification detailed-presentation set, and retain all other eligible cases in a supplement and the machine ledger.
4. **Search coverage**: query family, source, source class, retrieval method, live/cached status, retrieval time, result count, newly unique candidates, and failures or access limitations.
5. **Closest cases**: title, year, source/publisher, identifiers, direct link, source class, access scope, peer-review status when known, similarity reasons, important differences, and a short source-grounded evidence excerpt or abstract-based fact.
6. **Evidence separation**: group peer-reviewed case reports, educational case libraries, Chinese bibliographic records, and social-media/user-supplied material under different headings.
7. **Verification accounting**: included close cases, near misses, possible duplicate patients, exclusions with reasons, full-text versus abstract-only counts, and source-class counts.
8. **Stopping status and blind spots**: state whether the protocol stopped by saturation, access, time, API, or budget limit and list unsearched or failed channels.
9. **Uncertainty**: distinguish facts reported by a source from inference; identify missing full text and unverified reposts.
10. **Claim-to-source ledger**: list the source and evidence scope supporting each material clinical statement; flag unsupported, secondary-only, and abstract-only statements.
11. **Safety note**: state that case similarity is hypothesis-generating and cannot establish diagnosis, causality, treatment suitability, or expected outcome for the current patient.

Never merge source classes into a single unlabeled confidence score. Report `clinical_similarity` and `source_quality` separately.

## Maintenance

Update changing endpoints, access rules, and source classifications in [references/sources.md](references/sources.md). Keep stable execution rules here. When adding an API connector, normalize it to the fields emitted by `scripts/search_cases.py` and `scripts/run_search_plan.py`, add graceful failure behavior, test one real query, run `python3 -m unittest discover -s tests -v`, run `python3 scripts/validate_project.py`, and rerun the official Skill validator when available.

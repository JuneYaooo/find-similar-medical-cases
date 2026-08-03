---
name: find-similar-medical-cases
description: Comprehensively search, verify, compare, and synthesize source-grounded similar medical cases across PubMed, Europe PMC, scholarly and citation APIs, Chinese literature databases, specialty case libraries, publisher sites, and user-supplied or TikHub-retrieved WeChat articles. Use when a user asks to find similar clinical cases, 病例报告, 个案报告, 医案, 罕见病例, diagnostic or treatment analogues, or to build a reproducible high-recall case search while keeping source type, query coverage, retrieval method, evidence scope, recency, licensing, cost, similarity, and uncertainty explicit.
---

# Find Similar Medical Cases

Maximize useful recall, then verify and rerank for accuracy without presenting retrieval results as diagnosis or treatment advice. Keep peer-reviewed papers, educational cases, database records, and social-media articles visibly separate. Never equate a broad search with guaranteed completeness.

Resolve the directory containing this `SKILL.md` as the Skill directory. Read references relative to that directory and run every bundled command with that directory as its working directory; never assume the user's current project contains `scripts/` or `references/`.

## Required workflow

1. Remove identifiers before sending any query to an external service. Exclude names, contact details, record numbers, exact addresses, exact admission dates, and unneeded rare identifying details.
2. Convert the request into a compact case fingerprint: age band, sex if relevant, main presentation, duration, key positive and negative findings, imaging/pathology/labs, suspected diagnoses, interventions, response, outcome, and specialty.
3. Read [references/comprehensive-search.md](references/comprehensive-search.md), [references/retrieval-workflow.md](references/retrieval-workflow.md), and [references/technical-architecture.md](references/technical-architecture.md). Use the deterministic medical retrieval core; use a Deep Research agent only as an optional planner, browser gap-filler, iterative query generator, evidence checker, or report writer. Build a query lattice that separates high-precision, presentation-first, diagnosis/differential, broad-synonym, and applicable test/treatment variants.
4. Read [references/sources.md](references/sources.md) before choosing sources. Route each source by access method; never assume every website has an API. Use Crossref only as optional DOI/publisher-metadata discovery, not as clinical evidence or a replacement for PubMed and Europe PMC.
5. Copy [references/search-plan-template.json](references/search-plan-template.json) to a temporary file, replace the example with de-identified facts, and run the comprehensive live API stage:

   ```bash
   python3 scripts/run_search_plan.py --plan /tmp/case-search-plan.json --mode comprehensive --limit 20 --max-api-searches 30 --workers 4 --pretty
   ```

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
10. Compare cases using explicit matching, mismatching, and unknown facts. Rank clinical similarity separately from retrieval confidence and source quality.
11. Build a claim-to-source ledger for the final report. Each externally verifiable clinical claim must identify its candidate, URL, evidence scope (`title`, `abstract`, `full_text`, `educational_page`, or `social_post`), supporting passage or precise location, and support status. A topical citation is not sufficient.
12. Apply the stopping rule in `comprehensive-search.md`, then produce a source-aware report.

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
- Preserve original titles and bibliographic metadata. Write summaries in the user's language.

## Required output contract

Start with a one-paragraph de-identified search fingerprint and list the query variants used. Then report:

1. **Search coverage**: query family, source, source class, retrieval method, live/cached status, retrieval time, result count, newly unique candidates, and failures or access limitations.
2. **Closest cases**: title, year, source/publisher, identifiers, direct link, source class, access scope, peer-review status when known, similarity reasons, important differences, and a short source-grounded evidence excerpt or abstract-based fact.
3. **Evidence separation**: group peer-reviewed case reports, educational case libraries, Chinese bibliographic records, and social-media/user-supplied material under different headings.
4. **Verification accounting**: unique candidates, included close cases, near misses, duplicates, exclusions with reasons, full-text versus abstract-only counts, and source-class counts.
5. **Stopping status and blind spots**: state whether the protocol stopped by saturation, access, time, API, or budget limit and list unsearched or failed channels.
6. **Uncertainty**: distinguish facts reported by a source from inference; identify missing full text and unverified reposts.
7. **Claim-to-source ledger**: list the source and evidence scope supporting each material clinical statement; flag unsupported, secondary-only, and abstract-only statements.
8. **Safety note**: state that case similarity is hypothesis-generating and cannot establish diagnosis, causality, treatment suitability, or expected outcome for the current patient.

Never merge source classes into a single unlabeled confidence score. Report `clinical_similarity` and `source_quality` separately.

## Maintenance

Update changing endpoints, access rules, and source classifications in [references/sources.md](references/sources.md). Keep stable execution rules here. When adding an API connector, normalize it to the fields emitted by `scripts/search_cases.py` and `scripts/run_search_plan.py`, add graceful failure behavior, test one real query, run `python3 -m unittest discover -s tests -v`, run `python3 scripts/validate_project.py`, and rerun the official Skill validator when available.

# Source registry and routing

Consult this file whenever selecting, adding, or troubleshooting sources. A "live" search means querying the source's current index at request time; indexing itself may lag publication.

## Contents

- Routing matrix
- Baseline bilingual coverage
- Supported live API connectors
- Supported third-party API connector
- Browser-search sources
- WeChat and other social sources
- Access and license labels
- Source quality labels
- Maintenance checklist

## Routing matrix

| Source class | Examples | Default retrieval | Real-time behavior | Evidence use |
|---|---|---|---|---|
| Official literature API | PubMed/NCBI, Europe PMC | Official API | Query on every comprehensive request | Evidence backbone; verify full-text scope |
| Official DOI metadata API | Crossref | Official API | Query on demand | DOI/publisher metadata discovery, not clinical evidence |
| Third-party scholarly API | OpenAlex, Semantic Scholar | Third-party API | Query on every request when available | Discovery, citation expansion, OA-location hints |
| Case repository or Chinese index | CMCR, SinoMed, CNKI, Wanfang, VIP | Browser search or licensed connector | Search on demand; coverage/access varies | Chinese discovery and bibliographic evidence |
| Publisher case journal | BMJ Case Reports, Journal of Medical Case Reports, Oxford Medical Case Reports, Clinical Case Reports, Cureus | Literature API first, browser second | Search on demand | Prefer the original article and DOI |
| Specialty educational library | Radiopaedia, AHRQ WebM&M, EyeRounds, Pathology Outlines | Browser search | Search on demand | Educational comparison; not automatically peer reviewed |
| Social media | WeChat articles | User link, manual search, allowlist, or licensed API | Search/ingest on demand | Secondary source until original evidence is verified |
| Local collection | Previously saved metadata or licensed full text | Local search | Snapshot only | Supplement; always show snapshot date |

## Baseline bilingual coverage

This Skill is intended for medical researchers. Unless the user explicitly restricts language or requests a quick pass, a comprehensive search must plan and account for both language groups:

- English: run every core query family through PubMed and Europe PMC; use OpenAlex for discovery and citation expansion; search major case journals or relevant specialty libraries when index recall is insufficient.
- Chinese: attempt CMCR, SinoMed, CNKI, Wanfang, VIP, and the Chinese Medical Journal Network with Chinese terminology through supported browser or licensed access; add relevant Chinese specialty repositories when applicable.

Coverage means that the route was planned and its status was recorded. It does not mean every route was accessible or that all cases were found. Report each language group separately and label unavailable, blocked, login-required, and subscription-only routes explicitly. Never report an inaccessible Chinese source as zero results, and never call a comprehensive bilingual search complete when the Chinese group was silently omitted.

## Supported live API connectors

### PubMed / NCBI E-utilities

- Home: <https://pubmed.ncbi.nlm.nih.gov/>
- API: <https://eutils.ncbi.nlm.nih.gov/entrez/eutils/>
- Class: official literature API.
- Use: indexed case reports, article types, abstracts, MeSH-oriented retrieval.
- Query pattern: `(<case concepts>) AND ("Case Reports"[Publication Type] OR "case report"[Title/Abstract])`.
- Access scope: metadata and abstracts; PubMed inclusion does not imply open full text.
- Operation: set `NCBI_API_KEY` for higher rate limits and `NCBI_EMAIL` for responsible identification. Without an API key, keep requests at or below three per second.

### Europe PMC

- Home: <https://europepmc.org/>
- REST API: <https://www.ebi.ac.uk/europepmc/webservices/rest/>
- Class: official literature API and repository index.
- Use: case-report retrieval, abstracts, citation metadata, PMCID links, and open-access discovery.
- Query pattern: `(<case concepts>) AND PUB_TYPE:"case report"`; optionally add `OPEN_ACCESS:Y`.
- Access scope: record-specific. `isOpenAccess=Y` is not by itself permission to ignore the article's stated license.

### Crossref

- API: <https://api.crossref.org/>
- Class: official DOI metadata API.
- Use: DOI normalization, publisher metadata, and deduplication.
- Operation: optional `--sources crossref` connector; set `CROSSREF_EMAIL` for polite identification. It is intentionally excluded from default sources because its broad bibliographic search is noisy for clinical similarity.
- Do not use as the sole clinical evidence source because abstracts and article-type precision vary.

## Supported third-party API connector

### OpenAlex

- Home: <https://openalex.org/>
- API: <https://api.openalex.org/>
- Class: third-party scholarly discovery API.
- Use: broader recall, related works, citation counts, and open-access location hints.
- Verify: confirm clinically important facts and accessible full text against the original paper or a primary index.
- Operation: set `OPENALEX_API_KEY` if required by the current service policy and `OPENALEX_EMAIL` for the polite pool when supported.

### Optional future connector: Semantic Scholar

- API: <https://www.semanticscholar.org/product/api>
- Class: third-party scholarly discovery API.
- Add only when an API key and stable quota are available. Treat similarity and OA links as discovery signals, not source verification.

## Browser-search sources

These sources are not called by `search_cases.py`. Use `build_browser_searches.py`, then search only sources relevant to the specialty and language.

### Chinese literature and case repositories

- China Clinical Case Repository (CMCR): <https://cmcr.yiigle.com/>
  - Focused clinical case repository.
  - Use browser search. Its internal application endpoints are undocumented and must not be treated as a supported public API.
- SinoMed: <https://www.sinomed.ac.cn/index.jsp>
  - Search Chinese biomedical literature with `病例报告`, `个案报告`, `病例讨论`, or specialty terms.
- CNKI: <https://www.cnki.net/>
- Wanfang Data: <https://www.wanfangdata.com.cn/>
- VIP: <https://www.cqvip.com/>
- Chinese Medical Journal Network: <https://www.yiigle.com/>
  - Use institutional access where required. Save bibliographic metadata and permissible excerpts; never bypass login or subscription controls.

### Case journals

- Journal of Medical Case Reports: <https://link.springer.com/journal/13256>
- BMJ Case Reports: <https://casereports.bmj.com/>
- Oxford Medical Case Reports: <https://academic.oup.com/omcr>
- Clinical Case Reports: <https://onlinelibrary.wiley.com/journal/20500904>
- Cureus: <https://www.cureus.com/>

Search these directly only when API recall is insufficient. Bot protection or subscription pages are access limitations, not permission to work around them.

### Specialty educational collections

- Radiopaedia: <https://radiopaedia.org/>
- AHRQ WebM&M: <https://psnet.ahrq.gov/webmm>
- EyeRounds: <https://webeye.ophth.uiowa.edu/eyeforum/cases.htm>
- Pathology Outlines: <https://www.pathologyoutlines.com/>

Label these `educational_case_library`. Record editorial or peer-review status only when the site explicitly states it.

## WeChat and other social sources

- WeChat in-app search is the preferred manual discovery route.
- Sogou WeChat Search: <https://weixin.sogou.com/>. It is browser-only, may require CAPTCHA, and offers no supported public search API for this Skill.
- Prefer canonical `https://mp.weixin.qq.com/` links supplied by the user.
- TikHub: <https://api.tikhub.io/docs>. It currently provides paid WeChat Search and WeChat MP article/account endpoints. Classify retrieval as `licensed_third_party_api_live` and the article itself as `social_media`; TikHub is the retrieval provider, not the publisher or clinical evidence authority. Read `tikhub-wechat.md` before use.
- Maintain an allowlist by specialty. Record account name, canonical account identity when available, editorial affiliation, article URL, publication date, author, and cited original source.
- Seed and maintain candidate identities in `wechat-accounts.json`; never treat display-name matching alone as verification.
- For systematic monitoring, use TikHub, Newrank, Qingbo, or another provider only after the user supplies access and confirms permitted use. Keep provider terms and billing visible.
- Treat a repost as a pointer. If it cites a paper, conference case, hospital article, or book, retrieve and cite that original source.
- Do not claim exhaustive WeChat coverage. Do not defeat CAPTCHA, login, paywall, or anti-bot controls.

## Access and license labels

Assign one value per record:

- `open_full_text`: full text is accessible; also record the stated license when known.
- `abstract_only`: metadata/abstract accessible, full text not inspected.
- `subscription`: full text requires authorized access.
- `user_supplied`: the user provided the material; redistribution rights remain unknown unless stated.
- `unknown`: access or license could not be established.

Never translate `open_full_text` into permission for bulk redistribution. Preserve the explicit license and original URL.

Record `retrieved_evidence_scope` separately as `metadata`, `title`, `abstract`, or `full_text`. Availability of a full-text link does not prove that the current workflow inspected it. Verify the link at use time because repository synchronization or embargo state can make an advertised route temporarily unavailable.

## Source quality labels

Use these independently from clinical similarity:

1. `peer_reviewed_original_case`: original case report with identifiable publication record.
2. `peer_reviewed_case_series_or_discussion`: peer-reviewed but not a single directly comparable case.
3. `editorial_educational_case`: curated teaching case with stated institutional/editorial provenance.
4. `bibliographic_record_only`: title/abstract or index record without inspected full text.
5. `secondary_professional_summary`: professional article summarizing another source.
6. `social_or_unverified`: social-media material without verified original evidence.

Do not downgrade a case solely because it is old. Do downgrade claims that cannot be traced to the displayed source.

## Maintenance checklist

Review quarterly or when a connector fails:

1. Verify home page and API endpoint.
2. Recheck authentication, rate limits, terms, robots rules, and license fields.
3. Run a known query and record whether metadata, abstracts, and full text still appear as expected.
4. Update routing rather than scraping an undocumented endpoint.
5. Mark removed or blocked sources instead of silently deleting their history from reports.

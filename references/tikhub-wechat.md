# TikHub WeChat retrieval

Use TikHub as an optional paid transport for WeChat search and collection. It does not make a公众号 article peer reviewed, original, licensed for redistribution, or medically reliable.

## Contents

- Supported endpoints
- Authentication and region
- Always inspect cost first
- Retrieval patterns
- Evidence handling
- Coverage limits

## Supported endpoints

Verified against TikHub OpenAPI V5.3.2, updated 2026-06-22:

| Task | Endpoint | Skill command |
|---|---|---|
| Search articles or accounts | `/api/v1/wechat_search/v2/fetch_search` | `search` |
| Verify an account profile | `/api/v1/wechat_mp/v2/fetch_account_profile` | `profile` |
| List one account's articles | `/api/v1/wechat_mp/v2/fetch_account_articles` | `account-articles` |
| Extract one article | `/api/v1/wechat_mp/v2/fetch_article_detail` | `article` |
| Search and fetch bounded details | search + article detail | `collect` |

TikHub's documentation listed these calls at USD 0.01 each on 2026-08-03, QPS 10, and recommended 30–60 second timeouts. Pricing and terms may change; inspect the provider before a large run. The connector defaults to a 45-second timeout and no automatic retries because a timed-out paid request may already have been billed.

## Authentication and region

Pass the token only through the environment:

```bash
export TIKHUB_API_KEY='...'
```

Never put the token in a prompt, command argument, source file, report, or log. The default base is `https://api.tikhub.io`. TikHub currently advises mainland-China clients to use:

```bash
export TIKHUB_BASE_URL='https://api.tikhub.dev'
```

## Always inspect cost first

```bash
python3 scripts/search_wechat_tikhub.py \
  --dry-run --max-calls 6 --pretty \
  collect --query '低钾 高血压 病例' --pages 1 --details 5
```

Remove `--dry-run` only when paid retrieval is authorized. `--max-calls` is a hard cap on HTTP attempts, including retries. Dry-run reports both logical requests and the retry-adjusted maximum HTTP-call cost. Keep `--retries 0` unless the user accepts that retries can add cost.

## Retrieval patterns

### Global case search

```bash
python3 scripts/search_wechat_tikhub.py \
  --max-calls 6 --pretty \
  collect --query '低钾 高血压 病例' \
  --sort default --publish-time half_year \
  --pages 1 --details 5
```

Use `--include-body` only when full article text is needed and permitted. Without it, the connector returns metadata plus body availability, character count, and SHA-256 rather than reproducing the text.

### Discover an account

```bash
python3 scripts/search_wechat_tikhub.py \
  --max-calls 1 --pretty \
  search --business-type account --query '公众号名称' --pages 1
```

Take `gh_username` from the result and verify account identity before allowlisting it.

```bash
python3 scripts/search_wechat_tikhub.py \
  --max-calls 1 --pretty \
  profile --username 'gh_xxx'
```

Candidate account names live in `wechat-accounts.json`. They are deliberately marked `candidate_unverified`; update `gh_username` and status only after search/profile verification.

### Monitor an allowlisted account

```bash
python3 scripts/search_wechat_tikhub.py \
  --max-calls 2 --pretty \
  account-articles --username 'gh_xxx' --pages 2 --page-size 20
```

Persist `next_offset` only when the user wants incremental collection. Stop at `is_end`. Deduplicate by canonical article URL, then app-message ID, then account + normalized title + publication time.

### Extract a supplied article

```bash
python3 scripts/search_wechat_tikhub.py \
  --max-calls 1 --pretty \
  article --url 'https://mp.weixin.qq.com/s/...' --include-body
```

## Evidence handling

Keep two identities on every record:

- Retrieval provider: `WeChat via TikHub`, `licensed_third_party_api_live`.
- Content publisher:公众号 name and `gh_username`, `social_media`.

Default source quality to `social_or_unverified`. Promote only after verifying explicit editorial provenance and the original evidence. If an article cites a DOI, PMID, PMCID, journal, guideline, conference abstract, or hospital case page, retrieve that source through the appropriate route and treat the WeChat article as a secondary pointer.

Do not infer peer review from a professional-sounding account name. Do not count reposts as independent cases. Do not republish full article bodies or images unless the license or user authorization permits it.

## Coverage limits

- TikHub search results are not guaranteed exhaustive.
- Search ranking, availability, and historical depth depend on WeChat and TikHub.
- Article or account fields may be missing.
- A successful API response confirms retrieval, not authenticity or medical correctness.
- Report failed, partial, or budget-limited retrieval separately from zero results.

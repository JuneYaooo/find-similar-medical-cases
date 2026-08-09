#!/usr/bin/env python3
"""Search and collect WeChat MP articles through the optional paid TikHub API."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import search_cases as sc


SEARCH_PATH = "/api/v1/wechat_search/v2/fetch_search"
ARTICLE_PATH = "/api/v1/wechat_mp/v2/fetch_article_detail"
ACCOUNT_ARTICLES_PATH = "/api/v1/wechat_mp/v2/fetch_account_articles"
ACCOUNT_PROFILE_PATH = "/api/v1/wechat_mp/v2/fetch_account_profile"
DOCUMENTED_UNIT_PRICE_USD = 0.01
USER_AGENT = "find-similar-medical-cases/1.0"


class TikHubError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compact(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def clean_html(value: Any) -> Optional[str]:
    text = compact(value)
    if not text:
        return None
    return compact(html.unescape(re.sub(r"<[^>]+>", "", text)))


def validate_query(query: str) -> str:
    query = compact(query) or ""
    if not query:
        raise TikHubError("query must not be empty")
    # Shared privacy guard from search_cases.py; keep a single implementation so
    # the regex cannot drift between the scripts that rely on it.
    sensitive = sc.detect_sensitive_query(query)
    if sensitive:
        raise TikHubError(
            "query may contain sensitive identifiers: "
            + ", ".join(sensitive)
            + ". De-identify it before sending it to TikHub"
        )
    return query


def validate_wechat_url(url: str) -> str:
    value = compact(url) or ""
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {
        "mp.weixin.qq.com",
        "weixin.qq.com",
    }:
        raise TikHubError(
            "article URL must be an HTTPS mp.weixin.qq.com or weixin.qq.com URL"
        )
    return value


def walk_values(value: Any) -> Iterable[Any]:
    if isinstance(value, dict):
        for child in value.values():
            yield from walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_values(child)
    else:
        yield value


def find_wechat_url(value: Any) -> Optional[str]:
    for candidate in walk_values(value):
        if not isinstance(candidate, str) or "weixin.qq.com" not in candidate:
            continue
        match = re.search(
            r"https://(?:mp\.)?weixin\.qq\.com/[^\s\"'<>]+", html.unescape(candidate)
        )
        if match:
            return match.group(0).rstrip("),.;")
    return None


def get_nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


class TikHubClient:
    def __init__(
        self, base_url: str, token: str, timeout: int, max_calls: int, retries: int
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.max_calls = max_calls
        self.retries = retries
        self.http_attempts = 0

    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            if self.http_attempts >= self.max_calls:
                raise TikHubError(
                    f"TikHub call budget exhausted ({self.max_calls} HTTP attempts)"
                )
            self.http_attempts += 1
            request = urllib.request.Request(
                self.base_url + path,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": USER_AGENT,
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    # Keep all integer values as strings: TikHub documents 64-bit WeChat IDs.
                    return json.loads(response.read().decode("utf-8"), parse_int=str)
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
            ) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2**attempt, 4))
        raise TikHubError(
            f"TikHub request failed after {self.retries + 1} attempt(s): {last_error}"
        )


def response_data(response: Dict[str, Any]) -> Dict[str, Any]:
    data = response.get("data")
    if isinstance(data, dict):
        return data
    raise TikHubError(
        "TikHub returned no structured data"
        + (
            f" (code={response.get('code')}, message={response.get('message')})"
            if response
            else ""
        )
    )


def source_fields(retrieved_at: str) -> Dict[str, Any]:
    return {
        "source_name": "WeChat via TikHub",
        "source_class": "social_media",
        "retrieval_method": "licensed_third_party_api_live",
        "retrieved_at": retrieved_at,
        "source_quality": "social_or_unverified",
        "access_scope": "third_party_extracted",
        "peer_reviewed": None,
        "license": None,
    }


def normalize_search_item(item: Dict[str, Any], retrieved_at: str) -> Dict[str, Any]:
    jump = item.get("jumpInfo") or item.get("jump_info") or {}
    record = source_fields(retrieved_at)
    record.update(
        {
            "record_type": "wechat_search_result",
            "title": clean_html(item.get("title") or item.get("name")),
            "description": clean_html(
                item.get("desc") or item.get("description") or item.get("digest")
            ),
            "doc_id": compact(item.get("docID") or item.get("doc_id")),
            "account_name": clean_html(
                jump.get("nickName") or jump.get("nick_name") or item.get("nick_name")
            ),
            "gh_username": compact(
                jump.get("userName") or jump.get("user_name") or item.get("user_name")
            ),
            "url": find_wechat_url(item),
            "raw_item": item,
        }
    )
    return record


def normalize_account_article(
    item: Dict[str, Any], retrieved_at: str, username: str
) -> Dict[str, Any]:
    record = source_fields(retrieved_at)
    record.update(
        {
            "record_type": "wechat_account_article",
            "record_id": compact(item.get("app_msg_id") or item.get("appMsgId")),
            "title": clean_html(item.get("title")),
            "description": clean_html(item.get("digest")),
            "gh_username": username,
            "published_at": compact(item.get("create_time")),
            "updated_at": compact(item.get("update_time")),
            "url": compact(item.get("url")) or find_wechat_url(item),
            "is_paid": item.get("is_paid"),
        }
    )
    return record


def normalize_article_detail(
    response: Dict[str, Any], retrieved_at: str, requested_url: str, include_body: bool
) -> Dict[str, Any]:
    data = response_data(response)
    content = data.get("content") or {}
    if not isinstance(content, dict):
        raise TikHubError("TikHub article response has no normalized content object")
    body = compact(content.get("content_text"))
    record = source_fields(retrieved_at)
    record.update(
        {
            "record_type": "wechat_article_detail",
            "url": compact(data.get("url")) or requested_url,
            "title": clean_html(content.get("title")),
            "account_name": clean_html(content.get("nick_name")),
            "gh_username": compact(content.get("user_name")),
            "author": clean_html(content.get("author")),
            "description": clean_html(content.get("desc")),
            "published_at": compact(
                content.get("create_time") or content.get("ori_create_time")
            ),
            "cover_url": compact(content.get("cdn_url")),
            "body_available": body is not None,
            "body_characters": len(body) if body else 0,
            "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()
            if body
            else None,
            "content_text": body if include_body else None,
        }
    )
    return record


def run_search(
    client: TikHubClient, args: argparse.Namespace, retrieved_at: str
) -> Dict[str, Any]:
    query = validate_query(args.query)
    cursor: Optional[str] = None
    records: List[Dict[str, Any]] = []
    pages_fetched = 0
    continue_flag: Any = None
    for page in range(args.pages):
        payload: Dict[str, Any] = {
            "keyword": query,
            "business_type": args.business_type,
            "sort": args.sort,
            "publish_time": args.publish_time,
            "offset": 0,
            "raw": False,
        }
        if cursor:
            payload["cursor"] = cursor
        data = response_data(client.post(SEARCH_PATH, payload))
        pages_fetched += 1
        for value in data.get("items", []) or []:
            if isinstance(value, dict):
                records.append(normalize_search_item(value, retrieved_at))
        cursor = compact(data.get("cursor"))
        continue_flag = data.get("continue_flag")
        if not cursor or str(continue_flag).lower() in {"0", "false", "none"}:
            break
    return {
        "operation": "wechat_search",
        "query": query,
        "business_type": args.business_type,
        "pages_requested": args.pages,
        "pages_fetched": pages_fetched,
        "continue_flag": continue_flag,
        "next_cursor": cursor,
        "records": records,
    }


def run_account_articles(
    client: TikHubClient, args: argparse.Namespace, retrieved_at: str
) -> Dict[str, Any]:
    username = compact(args.username) or ""
    if not re.fullmatch(r"gh_[A-Za-z0-9_-]+", username):
        raise TikHubError("--username must be a WeChat gh_username beginning with gh_")
    offset = compact(args.offset)
    records: List[Dict[str, Any]] = []
    pages_fetched = 0
    is_end: Any = None
    for _ in range(args.pages):
        payload: Dict[str, Any] = {
            "username": username,
            "page_size": args.page_size,
            "item_show_type": 0,
            "raw": False,
        }
        if offset:
            payload["offset"] = offset
        data = response_data(client.post(ACCOUNT_ARTICLES_PATH, payload))
        pages_fetched += 1
        for value in data.get("articles", []) or []:
            if isinstance(value, dict):
                records.append(normalize_account_article(value, retrieved_at, username))
        offset = compact(data.get("next_offset"))
        is_end = data.get("is_end")
        if str(is_end).lower() in {"1", "true"} or not offset:
            break
    return {
        "operation": "wechat_account_articles",
        "gh_username": username,
        "pages_requested": args.pages,
        "pages_fetched": pages_fetched,
        "is_end": is_end,
        "next_offset": offset,
        "records": records,
    }


def run_account_profile(
    client: TikHubClient, args: argparse.Namespace, retrieved_at: str
) -> Dict[str, Any]:
    username = compact(args.username) or ""
    if not re.fullmatch(r"gh_[A-Za-z0-9_-]+", username):
        raise TikHubError("--username must be a WeChat gh_username beginning with gh_")
    data = response_data(
        client.post(ACCOUNT_PROFILE_PATH, {"username": username, "raw": False})
    )
    record = source_fields(retrieved_at)
    record.update(
        {
            "record_type": "wechat_account_profile",
            "gh_username": compact(data.get("user_name")) or username,
            "account_name": clean_html(data.get("nick_name")),
            "signature": clean_html(data.get("signature")),
            "service_type": compact(data.get("service_type")),
            "user_role": compact(data.get("user_role")),
            "head_url": compact(data.get("head_url")),
            "ban_type": compact(data.get("ban_type")),
        }
    )
    return {"operation": "wechat_account_profile", "records": [record]}


def fetch_detail(
    client: TikHubClient, url: str, retrieved_at: str, include_body: bool
) -> Dict[str, Any]:
    url = validate_wechat_url(url)
    response = client.post(ARTICLE_PATH, {"url": url, "raw": False})
    return normalize_article_detail(response, retrieved_at, url, include_body)


def run_article(
    client: TikHubClient, args: argparse.Namespace, retrieved_at: str
) -> Dict[str, Any]:
    return {
        "operation": "wechat_article_detail",
        "records": [fetch_detail(client, args.url, retrieved_at, args.include_body)],
    }


def run_collect(
    client: TikHubClient, args: argparse.Namespace, retrieved_at: str
) -> Dict[str, Any]:
    search_args = argparse.Namespace(
        query=args.query,
        business_type="article",
        sort=args.sort,
        publish_time=args.publish_time,
        pages=args.pages,
    )
    search_result = run_search(client, search_args, retrieved_at)
    urls: List[str] = []
    for record in search_result["records"]:
        url = record.get("url")
        if url and url not in urls:
            urls.append(url)
    details: List[Dict[str, Any]] = []
    detail_errors: List[Dict[str, str]] = []
    for url in urls[: args.details]:
        try:
            details.append(fetch_detail(client, url, retrieved_at, args.include_body))
        except TikHubError as exc:
            detail_errors.append({"url": url, "error": str(exc)})
    return {
        "operation": "wechat_search_and_collect",
        "query": search_result["query"],
        "search": search_result,
        "details_requested": args.details,
        "details_fetched": len(details),
        "detail_errors": detail_errors,
        "records": details,
    }


def dry_run_plan(args: argparse.Namespace, base_url: str) -> Dict[str, Any]:
    if args.command in {"search", "collect"}:
        validate_query(args.query)
    if args.command == "article":
        validate_wechat_url(args.url)
    if args.command in {"account-articles", "profile"} and not re.fullmatch(
        r"gh_[A-Za-z0-9_-]+", args.username
    ):
        raise TikHubError("--username must be a WeChat gh_username beginning with gh_")
    if args.command == "search":
        calls = args.pages
        paths = [{"path": SEARCH_PATH, "maximum_calls": args.pages}]
    elif args.command == "account-articles":
        calls = args.pages
        paths = [{"path": ACCOUNT_ARTICLES_PATH, "maximum_calls": args.pages}]
    elif args.command == "article":
        calls = 1
        paths = [{"path": ARTICLE_PATH, "maximum_calls": 1}]
    elif args.command == "profile":
        calls = 1
        paths = [{"path": ACCOUNT_PROFILE_PATH, "maximum_calls": 1}]
    else:
        calls = args.pages + args.details
        paths = [
            {"path": SEARCH_PATH, "maximum_calls": args.pages},
            {"path": ARTICLE_PATH, "maximum_calls": args.details},
        ]
    if calls > args.max_calls:
        raise TikHubError(
            f"planned maximum {calls} calls exceeds --max-calls {args.max_calls}"
        )
    maximum_attempts = min(args.max_calls, calls * (args.retries + 1))
    return {
        "dry_run": True,
        "operation": args.command,
        "base_url": base_url,
        "requests": paths,
        "maximum_logical_requests": calls,
        "maximum_http_calls": maximum_attempts,
        "estimated_maximum_cost_usd": round(
            maximum_attempts * DOCUMENTED_UNIT_PRICE_USD, 2
        ),
        "notice": "HTTP-call estimate includes configured retries and the global --max-calls cap. Pricing uses TikHub's documented $0.01 per call on 2026-08-03; verify current billing before execution.",
    }


def add_search_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--query", required=True)
    parser.add_argument(
        "--sort", choices=("default", "latest", "hot"), default="default"
    )
    parser.add_argument(
        "--publish-time", choices=("all", "day", "week", "half_year"), default="all"
    )
    parser.add_argument("--pages", type=int, default=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=sc.env_value("TIKHUB_BASE_URL") or "https://api.tikhub.io",
    )
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument(
        "--max-calls",
        type=int,
        default=10,
        help="Hard cap on HTTP attempts, including retries",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=0,
        help="Paid requests may be billed even when a response times out",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show endpoints, maximum calls, and estimated cost without calling TikHub",
    )
    parser.add_argument("--pretty", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser(
        "search", help="Search WeChat articles or accounts"
    )
    add_search_options(search_parser)
    search_parser.add_argument(
        "--business-type", choices=("article", "account"), default="article"
    )

    account_parser = subparsers.add_parser(
        "account-articles", help="Fetch article-list pages for one gh_username"
    )
    account_parser.add_argument("--username", required=True)
    account_parser.add_argument("--pages", type=int, default=1)
    account_parser.add_argument("--page-size", type=int, default=20)
    account_parser.add_argument("--offset")

    profile_parser = subparsers.add_parser(
        "profile", help="Fetch and verify one official-account profile"
    )
    profile_parser.add_argument("--username", required=True)

    article_parser = subparsers.add_parser(
        "article", help="Fetch one WeChat article by canonical URL"
    )
    article_parser.add_argument("--url", required=True)
    article_parser.add_argument(
        "--include-body",
        action="store_true",
        help="Include extracted article text in output",
    )

    collect_parser = subparsers.add_parser(
        "collect", help="Search article results and fetch a bounded number of details"
    )
    add_search_options(collect_parser)
    collect_parser.add_argument("--details", type=int, default=5)
    collect_parser.add_argument("--include-body", action="store_true")

    args = parser.parse_args()
    if not 1 <= args.max_calls <= 100:
        parser.error("--max-calls must be between 1 and 100")
    if not 1 <= args.timeout <= 300:
        parser.error("--timeout must be between 1 and 300 seconds")
    if not 0 <= args.retries <= 2:
        parser.error("--retries must be between 0 and 2")
    if hasattr(args, "pages") and not 1 <= args.pages <= 10:
        parser.error("--pages must be between 1 and 10")
    if hasattr(args, "page_size") and not 10 <= args.page_size <= 20:
        parser.error("--page-size must be between 10 and 20")
    if hasattr(args, "details") and not 0 <= args.details <= 20:
        parser.error("--details must be between 0 and 20")

    base_url = args.base_url.rstrip("/")
    try:
        if args.dry_run:
            output = dry_run_plan(args, base_url)
        else:
            token = sc.env_value("TIKHUB_API_KEY")
            if not token:
                raise TikHubError(
                    "set TIKHUB_API_KEY or use --dry-run; never put the token in command arguments"
                )
            retrieved_at = utc_now()
            client = TikHubClient(
                base_url, token, args.timeout, args.max_calls, args.retries
            )
            if args.command == "search":
                result = run_search(client, args, retrieved_at)
            elif args.command == "account-articles":
                result = run_account_articles(client, args, retrieved_at)
            elif args.command == "profile":
                result = run_account_profile(client, args, retrieved_at)
            elif args.command == "article":
                result = run_article(client, args, retrieved_at)
            else:
                if args.pages + args.details > args.max_calls:
                    raise TikHubError(
                        f"planned maximum {args.pages + args.details} calls exceeds --max-calls {args.max_calls}"
                    )
                result = run_collect(client, args, retrieved_at)
            output = {
                "retrieved_at": retrieved_at,
                "live_search": True,
                "provider": "TikHub",
                "source_class": "licensed_third_party_api",
                "retrieval_method": "licensed_third_party_api_live",
                "http_attempts": client.http_attempts,
                "estimated_cost_usd": round(
                    client.http_attempts * DOCUMENTED_UNIT_PRICE_USD, 2
                ),
                "billing_notice": "Estimate uses TikHub's documented $0.01 per call on 2026-08-03; verify the provider invoice.",
                **result,
            }
        json.dump(
            output, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None
        )
        sys.stdout.write("\n")
        return 0
    except TikHubError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

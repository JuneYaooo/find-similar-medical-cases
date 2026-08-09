#!/usr/bin/env python3
"""Build a source-labeled browser search plan for case sources without supported APIs."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List

import search_cases as sc


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# detect_sensitive_query lives in search_cases.py; keep a single implementation so
# the privacy guard cannot drift between the scripts that rely on it.


def quote(value: str) -> str:
    return urllib.parse.quote_plus(value)


def google_site(site: str, query: str) -> str:
    return f"https://www.google.com/search?q={quote(f'site:{site} {query}')}"


def item(
    source_name: str,
    source_class: str,
    url: str,
    query: str,
    *,
    access_scope: str = "unknown",
    note: str,
) -> Dict[str, Any]:
    return {
        "source_name": source_name,
        "source_class": source_class,
        "retrieval_method": "browser_search_live",
        "query": query,
        "url": url,
        "access_scope": access_scope,
        "note": note,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query", required=True, help="De-identified Chinese or English case concepts"
    )
    parser.add_argument(
        "--groups",
        default="chinese,journals,specialty,wechat",
        help="Comma-separated groups: chinese,journals,specialty,wechat",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    query = re.sub(r"\s+", " ", args.query).strip()
    if not query:
        parser.error("--query must not be empty")
    sensitive = sc.detect_sensitive_query(query)
    if sensitive:
        parser.error(
            "query may contain sensitive identifiers: "
            + ", ".join(sensitive)
            + ". De-identify it before browser search"
        )
    groups = {
        value.strip().lower() for value in args.groups.split(",") if value.strip()
    }
    allowed = {"chinese", "journals", "specialty", "wechat"}
    if not groups:
        parser.error("at least one group is required")
    unknown = sorted(groups - allowed)
    if unknown:
        parser.error("unknown groups: " + ", ".join(unknown))

    case_en = f'{query} "case report"'
    case_zh = f"{query} 病例报告 OR 个案报告 OR 病例讨论"
    searches: List[Dict[str, Any]] = []

    if "chinese" in groups:
        searches.extend(
            [
                item(
                    "China Clinical Case Repository (CMCR)",
                    "case_repository",
                    google_site("cmcr.yiigle.com", case_zh),
                    case_zh,
                    note="Use the repository's own search after opening it; no supported public API is assumed.",
                ),
                item(
                    "SinoMed",
                    "chinese_bibliographic_database",
                    "https://www.sinomed.ac.cn/index.jsp",
                    case_zh,
                    note="Paste the query into SinoMed and use institutional access when required.",
                ),
                item(
                    "CNKI",
                    "chinese_bibliographic_database",
                    "https://www.cnki.net/",
                    case_zh,
                    access_scope="subscription",
                    note="Search title/abstract/keywords; do not bypass subscription controls.",
                ),
                item(
                    "Wanfang Data",
                    "chinese_bibliographic_database",
                    "https://www.wanfangdata.com.cn/",
                    case_zh,
                    access_scope="subscription",
                    note="Search bibliographic records and licensed full text.",
                ),
                item(
                    "VIP",
                    "chinese_bibliographic_database",
                    "https://www.cqvip.com/",
                    case_zh,
                    access_scope="subscription",
                    note="Search bibliographic records and licensed full text.",
                ),
                item(
                    "Chinese Medical Journal Network",
                    "publisher_platform",
                    google_site("yiigle.com", case_zh),
                    case_zh,
                    note="Prefer the original journal article and stable identifier.",
                ),
            ]
        )

    if "journals" in groups:
        journals = [
            ("Journal of Medical Case Reports", "link.springer.com/journal/13256"),
            ("BMJ Case Reports", "casereports.bmj.com"),
            ("Oxford Medical Case Reports", "academic.oup.com/omcr"),
            ("Clinical Case Reports", "onlinelibrary.wiley.com/journal/20500904"),
            ("Cureus", "cureus.com"),
        ]
        searches.extend(
            item(
                name,
                "publisher_case_journal",
                google_site(site, case_en),
                case_en,
                note="Use browser discovery only when literature APIs are insufficient; verify DOI and access scope.",
            )
            for name, site in journals
        )

    if "specialty" in groups:
        specialty = [
            (
                "Radiopaedia",
                "radiopaedia.org",
                "Imaging teaching cases; label as educational unless publication status is explicit.",
            ),
            (
                "AHRQ WebM&M",
                "psnet.ahrq.gov/webmm",
                "Patient-safety teaching cases with editorial provenance.",
            ),
            (
                "EyeRounds",
                "webeye.ophth.uiowa.edu/eyeforum/cases.htm",
                "Ophthalmology teaching cases.",
            ),
            (
                "Pathology Outlines",
                "pathologyoutlines.com",
                "Pathology reference and case discovery.",
            ),
        ]
        searches.extend(
            item(
                name,
                "educational_case_library",
                google_site(site, query),
                query,
                note=note,
            )
            for name, site, note in specialty
        )

    if "wechat" in groups:
        searches.append(
            item(
                "Sogou WeChat Search",
                "social_media_search",
                f"https://weixin.sogou.com/weixin?type=2&query={quote(case_zh)}",
                case_zh,
                note="Browser/manual search only; CAPTCHA may appear and coverage is not exhaustive. Prefer user-supplied canonical WeChat links and trace original sources.",
            )
        )

    output = {
        "query": query,
        "generated_at": utc_now(),
        "live_search": False,
        "notice": "These are browser search instructions, not executed searches. Mark each source live only after opening and searching it during the request.",
        "searches": searches,
    }
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

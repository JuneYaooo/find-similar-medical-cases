#!/usr/bin/env python3
"""Expand a verified seed through PubMed similarity and OpenAlex graph relations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

import run_search_plan as rsp
import search_cases as sc


def openalex_params(extra: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **extra,
        "mailto": os.getenv("OPENALEX_EMAIL"),
        "api_key": os.getenv("OPENALEX_API_KEY"),
    }


def resolve_seed(args: argparse.Namespace, timeout: int) -> Dict[str, Any]:
    if args.openalex_id:
        value = args.openalex_id.rsplit("/", 1)[-1]
        payload = sc.request_json(
            "https://api.openalex.org/works",
            openalex_params({"filter": f"openalex_id:{value}", "per-page": 1}),
            timeout=timeout,
        )
    elif args.doi:
        doi = sc.normalize_doi(args.doi)
        payload = sc.request_json(
            "https://api.openalex.org/works",
            openalex_params({"filter": f"doi:https://doi.org/{doi}", "per-page": 1}),
            timeout=timeout,
        )
    else:
        pmid = str(args.pmid).strip()
        payload = sc.request_json(
            "https://api.openalex.org/works",
            openalex_params({"filter": f"pmid:{pmid}", "per-page": 1}),
            timeout=timeout,
        )
    results = payload.get("results", [])
    if not results:
        raise RuntimeError("seed article was not found in OpenAlex")
    return results[0]


def resolve_pubmed_seed(
    args: argparse.Namespace,
    openalex_seed: Dict[str, Any] | None,
    timeout: int,
    retrieved_at: str,
) -> Dict[str, Any] | None:
    pmid = str(args.pmid).strip() if args.pmid else None
    if not pmid and args.doi:
        doi = sc.normalize_doi(args.doi)
        payload = sc.request_json(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            {
                "db": "pubmed",
                "term": f"{doi}[AID]",
                "retmode": "json",
                "retmax": 1,
                "tool": "find_similar_medical_cases",
                "email": os.getenv("NCBI_EMAIL"),
                "api_key": os.getenv("NCBI_API_KEY"),
            },
            timeout=timeout,
        )
        ids = (payload.get("esearchresult") or {}).get("idlist", [])
        pmid = str(ids[0]) if ids else None
    if not pmid and openalex_seed:
        pmid = sc.normalize_openalex_item(openalex_seed, retrieved_at).get("pmid")
    records = sc.fetch_pubmed_records([pmid], timeout, retrieved_at) if pmid else []
    return records[0] if records else None


def fetch_ids(ids: List[str], limit: int, timeout: int) -> List[Dict[str, Any]]:
    values = [value.rsplit("/", 1)[-1] for value in ids[:limit]]
    if not values:
        return []
    payload = sc.request_json(
        "https://api.openalex.org/works",
        openalex_params(
            {"filter": "openalex_id:" + "|".join(values), "per-page": len(values)}
        ),
        timeout=timeout,
    )
    return payload.get("results", [])


def tag_relation(
    item: Dict[str, Any], relation: str, retrieved_at: str
) -> Dict[str, Any]:
    record = sc.normalize_openalex_item(item, retrieved_at)
    record["relations_to_seed"] = [relation]
    record["matched_queries"] = [f"seed_{relation}"]
    record["query_intents"] = ["citation_chaining"]
    record["source_occurrences"] = [
        {
            "source_name": "OpenAlex",
            "record_id": record.get("record_id"),
            "url": record.get("url"),
            "relation": relation,
        }
    ]
    return record


def pubmed_similar(
    pmid: str, limit: int, timeout: int, retrieved_at: str
) -> List[Dict[str, Any]]:
    payload = sc.request_json(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi",
        {
            "dbfrom": "pubmed",
            "db": "pubmed",
            "id": pmid,
            "cmd": "neighbor_score",
            "linkname": "pubmed_pubmed",
            "retmode": "json",
            "tool": "find_similar_medical_cases",
            "email": os.getenv("NCBI_EMAIL"),
            "api_key": os.getenv("NCBI_API_KEY"),
        },
        timeout=timeout,
    )
    links: List[Dict[str, Any]] = []
    for linkset in payload.get("linksets", []):
        for linkdb in linkset.get("linksetdbs", []) or []:
            if linkdb.get("linkname") == "pubmed_pubmed":
                links.extend(linkdb.get("links", []) or [])
    selected = [link for link in links if str(link.get("id")) != str(pmid)][:limit]
    records = sc.fetch_pubmed_records(
        [str(link["id"]) for link in selected], timeout, retrieved_at
    )
    score_by_pmid = {str(link["id"]): link.get("score") for link in selected}
    for record in records:
        record["relations_to_seed"] = ["pubmed_similar"]
        record["matched_queries"] = ["seed_pubmed_similar"]
        record["query_intents"] = ["similar_article_expansion"]
        record["pubmed_similarity_score"] = score_by_pmid.get(str(record.get("pmid")))
        record["source_occurrences"] = [
            {
                "source_name": "PubMed",
                "record_id": record.get("record_id"),
                "url": record.get("url"),
                "relation": "pubmed_similar",
            }
        ]
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    seed = parser.add_mutually_exclusive_group(required=True)
    seed.add_argument("--doi")
    seed.add_argument("--pmid")
    seed.add_argument("--openalex-id")
    parser.add_argument("--providers", default="pubmed,openalex")
    parser.add_argument("--directions", default="related,references,citations")
    parser.add_argument("--limit-per-direction", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    directions = list(
        dict.fromkeys(
            value.strip().lower()
            for value in args.directions.split(",")
            if value.strip()
        )
    )
    providers = list(
        dict.fromkeys(
            value.strip().lower()
            for value in args.providers.split(",")
            if value.strip()
        )
    )
    if not directions:
        parser.error("at least one direction is required")
    if not providers:
        parser.error("at least one provider is required")
    unknown = sorted(set(directions) - {"related", "references", "citations"})
    if unknown:
        parser.error("unknown directions: " + ", ".join(unknown))
    unknown_providers = sorted(set(providers) - {"pubmed", "openalex"})
    if unknown_providers:
        parser.error("unknown providers: " + ", ".join(unknown_providers))
    if not 1 <= args.limit_per_direction <= 50:
        parser.error("--limit-per-direction must be between 1 and 50")
    if not 1 <= args.timeout <= 300:
        parser.error("--timeout must be between 1 and 300 seconds")

    retrieved_at = sc.utc_now()
    expanded: List[Dict[str, Any]] = []
    coverage: List[Dict[str, Any]] = []
    seed_item: Dict[str, Any] | None = None
    pubmed_seed_record: Dict[str, Any] | None = None

    if "openalex" in providers or args.openalex_id:
        try:
            seed_item = resolve_seed(args, args.timeout)
        except Exception as exc:
            coverage.append(
                {
                    "provider": "OpenAlex",
                    "direction": "seed_resolution",
                    "status": "failed",
                    "returned": 0,
                    "limitation": str(exc),
                }
            )

    if "pubmed" in providers:
        try:
            pubmed_seed_record = resolve_pubmed_seed(
                args, seed_item, args.timeout, retrieved_at
            )
        except Exception as exc:
            coverage.append(
                {
                    "provider": "PubMed",
                    "direction": "seed_resolution",
                    "status": "failed",
                    "returned": 0,
                    "limitation": str(exc),
                }
            )

    seed_records = []
    if seed_item:
        seed_records.append(sc.normalize_openalex_item(seed_item, retrieved_at))
    if pubmed_seed_record:
        seed_records.append(pubmed_seed_record)
    if not seed_records:
        parser.error("seed article could not be resolved by the requested providers")
    seed_record = rsp.merge_with_aliases(seed_records)[0]

    if "openalex" in providers and seed_item:
        seed_id = str(seed_item.get("id", "")).rsplit("/", 1)[-1]
        if "related" in directions:
            try:
                items = fetch_ids(
                    seed_item.get("related_works", []) or [],
                    args.limit_per_direction,
                    args.timeout,
                )
                expanded.extend(
                    tag_relation(item, "related", retrieved_at) for item in items
                )
                coverage.append(
                    {
                        "provider": "OpenAlex",
                        "direction": "related",
                        "status": "success",
                        "returned": len(items),
                    }
                )
            except Exception as exc:
                coverage.append(
                    {
                        "provider": "OpenAlex",
                        "direction": "related",
                        "status": "failed",
                        "returned": 0,
                        "limitation": str(exc),
                    }
                )
        if "references" in directions:
            try:
                items = fetch_ids(
                    seed_item.get("referenced_works", []) or [],
                    args.limit_per_direction,
                    args.timeout,
                )
                expanded.extend(
                    tag_relation(item, "reference", retrieved_at) for item in items
                )
                coverage.append(
                    {
                        "provider": "OpenAlex",
                        "direction": "references",
                        "status": "success",
                        "returned": len(items),
                    }
                )
            except Exception as exc:
                coverage.append(
                    {
                        "provider": "OpenAlex",
                        "direction": "references",
                        "status": "failed",
                        "returned": 0,
                        "limitation": str(exc),
                    }
                )
        if "citations" in directions:
            try:
                payload = sc.request_json(
                    "https://api.openalex.org/works",
                    openalex_params(
                        {
                            "filter": f"cites:{seed_id}",
                            "per-page": args.limit_per_direction,
                            "sort": "cited_by_count:desc",
                        }
                    ),
                    timeout=args.timeout,
                )
                items = payload.get("results", [])
                expanded.extend(
                    tag_relation(item, "citation", retrieved_at) for item in items
                )
                coverage.append(
                    {
                        "provider": "OpenAlex",
                        "direction": "citations",
                        "status": "success",
                        "total_hits": int(
                            (payload.get("meta") or {}).get("count", 0) or 0
                        ),
                        "returned": len(items),
                    }
                )
            except Exception as exc:
                coverage.append(
                    {
                        "provider": "OpenAlex",
                        "direction": "citations",
                        "status": "failed",
                        "returned": 0,
                        "limitation": str(exc),
                    }
                )

    if "pubmed" in providers:
        pmid = (
            (pubmed_seed_record or {}).get("pmid")
            or seed_record.get("pmid")
            or args.pmid
        )
        if pmid:
            try:
                items = pubmed_similar(
                    str(pmid), args.limit_per_direction, args.timeout, retrieved_at
                )
                expanded.extend(items)
                coverage.append(
                    {
                        "provider": "PubMed",
                        "direction": "similar_articles",
                        "status": "success",
                        "returned": len(items),
                    }
                )
            except Exception as exc:
                coverage.append(
                    {
                        "provider": "PubMed",
                        "direction": "similar_articles",
                        "status": "failed",
                        "returned": 0,
                        "limitation": str(exc),
                    }
                )
        else:
            coverage.append(
                {
                    "provider": "PubMed",
                    "direction": "similar_articles",
                    "status": "not_available",
                    "returned": 0,
                    "limitation": "seed has no PMID",
                }
            )

    seed_aliases = rsp.aliases(seed_record)
    records = [
        record
        for record in rsp.merge_with_aliases(expanded)
        if not (rsp.aliases(record) & seed_aliases)
    ]
    for record in records:
        rsp.annotate_candidate(record)
    records.sort(
        key=lambda record: (
            {"high": 2, "medium": 1, "discovery_only": 0}[
                record["retrieval_support"]["retrieval_confidence"]
            ],
            len(record.get("relations_to_seed", [])),
            record.get("cited_by_count") or 0,
        ),
        reverse=True,
    )
    output = {
        "retrieved_at": retrieved_at,
        "live_search": True,
        "providers": providers,
        "retrieval_method": "official_and_third_party_api_live",
        "seed": seed_record,
        "coverage": coverage,
        "notice": "PubMed similar articles plus citation and related-work expansion improve recall but return non-case papers; verify and rerank clinically.",
        "unique_candidate_count": len(records),
        "records": records,
    }
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

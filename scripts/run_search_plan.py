#!/usr/bin/env python3
"""Execute a reproducible multi-query case-report search plan across scholarly APIs."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import search_cases as sc


ALLOWED_INTENTS = {
    "high_precision",
    "presentation",
    "diagnosis_or_differential",
    "broad_synonyms",
    "test_or_pathology",
    "treatment_or_outcome",
    "adverse_event",
    "population_or_context",
}
CORE_INTENTS = {
    "high_precision",
    "presentation",
    "diagnosis_or_differential",
    "broad_synonyms",
}
BROWSER_GROUPS = {"chinese", "journals", "specialty", "wechat"}


class PlanError(RuntimeError):
    pass


def load_plan(path: str) -> Dict[str, Any]:
    try:
        if path == "-":
            value = json.load(sys.stdin)
        else:
            with Path(path).open("r", encoding="utf-8") as handle:
                value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanError(f"cannot read search plan: {exc}") from exc
    if not isinstance(value, dict):
        raise PlanError("search plan must be a JSON object")
    return value


def validate_plan(plan: Dict[str, Any], mode: str) -> List[Dict[str, Any]]:
    if mode == "comprehensive" and not isinstance(plan.get("case_fingerprint"), dict):
        raise PlanError("comprehensive search plan requires a case_fingerprint object")
    requirements = plan.get("requirements") or {}
    if not isinstance(requirements, dict):
        raise PlanError("requirements must be an object")
    languages = requirements.get("languages", ["en"])
    if (
        not isinstance(languages, list)
        or not languages
        or not all(
            isinstance(language, str) and language.strip() for language in languages
        )
    ):
        raise PlanError("requirements.languages must be an array of non-empty strings")
    for field in ("include_chinese_sources", "include_wechat", "citation_chaining"):
        if field in requirements and not isinstance(requirements[field], bool):
            raise PlanError(f"requirements.{field} must be true or false")
    queries = plan.get("api_queries")
    if not isinstance(queries, list) or not queries:
        raise PlanError("search plan requires a non-empty api_queries array")
    seen: Set[str] = set()
    normalized: List[Dict[str, Any]] = []
    for index, query in enumerate(queries):
        if not isinstance(query, dict):
            raise PlanError(f"api_queries[{index}] must be an object")
        for field in ("id", "text", "intent"):
            if not isinstance(query.get(field), str):
                raise PlanError(f"api_queries[{index}].{field} must be a string")
        if "language" in query and not isinstance(query["language"], str):
            raise PlanError(f"api_queries[{index}].language must be a string")
        if (
            "rationale" in query
            and query["rationale"] is not None
            and not isinstance(query["rationale"], str)
        ):
            raise PlanError(f"api_queries[{index}].rationale must be a string")
        if "required" in query and not isinstance(query["required"], bool):
            raise PlanError(f"api_queries[{index}].required must be true or false")
        if "case_filter" in query and not isinstance(query["case_filter"], bool):
            raise PlanError(f"api_queries[{index}].case_filter must be true or false")
        query_id = sc.compact(query.get("id"))
        text = sc.compact(query.get("text"))
        intent = sc.compact(query.get("intent"))
        language = sc.compact(query.get("language")) or "en"
        if not query_id or query_id in seen:
            raise PlanError(f"api_queries[{index}].id must be unique and non-empty")
        if not text:
            raise PlanError(f"api_queries[{index}].text must be non-empty")
        if intent not in ALLOWED_INTENTS:
            raise PlanError(
                f"api_queries[{index}].intent must be one of {sorted(ALLOWED_INTENTS)}"
            )
        sensitive = sc.detect_sensitive_query(text)
        if sensitive:
            raise PlanError(
                f"api query {query_id} may contain sensitive identifiers: {', '.join(sensitive)}"
            )
        sources = query.get("sources") or ["pubmed", "europepmc"]
        if not isinstance(sources, list) or not sources:
            raise PlanError(f"api_queries[{index}].sources must be a non-empty array")
        if not all(isinstance(source, str) and source.strip() for source in sources):
            raise PlanError(
                f"api_queries[{index}].sources must contain non-empty strings"
            )
        sources = list(dict.fromkeys(source.strip().lower() for source in sources))
        unknown = sorted(set(sources) - set(sc.SUPPORTED_SOURCES))
        if unknown:
            raise PlanError(
                f"api query {query_id} has unknown sources: {', '.join(unknown)}"
            )
        seen.add(query_id)
        normalized.append(
            {
                "id": query_id,
                "text": text,
                "intent": intent,
                "language": language,
                "sources": sources,
                "rationale": sc.compact(query.get("rationale")),
                "required": bool(query.get("required", mode == "comprehensive")),
                "case_filter": bool(query.get("case_filter", True)),
            }
        )
    return normalized


def validate_supplemental_queries(plan: Dict[str, Any]) -> None:
    for field in ("browser_queries", "wechat_queries"):
        values = plan.get(field) or []
        if not isinstance(values, list):
            raise PlanError(f"{field} must be an array")
        seen: Set[str] = set()
        for index, value in enumerate(values):
            if not isinstance(value, dict):
                raise PlanError(f"{field}[{index}] must be an object")
            if not isinstance(value.get("id"), str) or not isinstance(
                value.get("text"), str
            ):
                raise PlanError(f"{field}[{index}].id and .text must be strings")
            query_id = sc.compact(value.get("id"))
            query_text = sc.compact(value.get("text"))
            if not query_id or query_id in seen:
                raise PlanError(f"{field}[{index}].id must be unique and non-empty")
            if not query_text:
                raise PlanError(f"{field}[{index}].text must be non-empty")
            sensitive = sc.detect_sensitive_query(query_text)
            if sensitive:
                raise PlanError(
                    f"{field} query {query_id} may contain sensitive identifiers: {', '.join(sensitive)}"
                )
            seen.add(query_id)
            if field == "browser_queries":
                groups = value.get("groups") or []
                if not isinstance(groups, list) or not groups:
                    raise PlanError(
                        f"browser query {query_id} requires a non-empty groups array"
                    )
                if not all(
                    isinstance(group, str) and group.strip() for group in groups
                ):
                    raise PlanError(
                        f"browser query {query_id}.groups must contain non-empty strings"
                    )
                groups = [group.strip().lower() for group in groups]
                unknown = sorted(set(groups) - BROWSER_GROUPS)
                if unknown:
                    raise PlanError(
                        f"browser query {query_id} has unknown groups: {', '.join(unknown)}"
                    )
            else:
                pages = value.get("maximum_pages", 1)
                details = value.get("maximum_details", 5)
                if not isinstance(pages, int) or not 1 <= pages <= 10:
                    raise PlanError(
                        f"WeChat query {query_id}.maximum_pages must be between 1 and 10"
                    )
                if not isinstance(details, int) or not 0 <= details <= 20:
                    raise PlanError(
                        f"WeChat query {query_id}.maximum_details must be between 0 and 20"
                    )


def aliases(record: Dict[str, Any]) -> Set[str]:
    return sc.record_aliases(record)


def merge_values(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    if (
        source.get("source_class") == "official_literature_api"
        and target.get("source_class") != "official_literature_api"
    ):
        for field in (
            "source_name",
            "source_class",
            "retrieval_method",
            "retrieved_at",
            "record_id",
            "url",
        ):
            if source.get(field):
                target[field] = source[field]
    for field in (
        "pmid",
        "pmcid",
        "doi",
        "title",
        "journal",
        "year",
        "url",
        "full_text_url",
        "license",
    ):
        if not target.get(field) and source.get(field):
            target[field] = source[field]
    if len(source.get("abstract") or "") > len(target.get("abstract") or ""):
        target["abstract"] = source["abstract"]
    if source.get("open_access") is True:
        target["open_access"] = True
    if source.get("access_scope") == "open_full_text":
        target["access_scope"] = "open_full_text"
    evidence_priority = {"metadata": 0, "title": 1, "abstract": 2, "full_text": 3}
    if evidence_priority.get(
        source.get("retrieved_evidence_scope"), 0
    ) > evidence_priority.get(target.get("retrieved_evidence_scope"), 0):
        target["retrieved_evidence_scope"] = source["retrieved_evidence_scope"]
    target["authors"] = target.get("authors") or source.get("authors", [])
    for field in ("found_via", "publication_types", "matched_queries", "query_intents"):
        target[field] = sorted(set(target.get(field, []) + source.get(field, [])))
    target["relations_to_seed"] = sorted(
        set(target.get("relations_to_seed", []) + source.get("relations_to_seed", []))
    )
    target["source_occurrences"] = target.get("source_occurrences", []) + source.get(
        "source_occurrences", []
    )
    sc.promote_source_quality(target, source)


def merge_with_aliases(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: List[Dict[str, Any]] = []
    grouped_aliases: List[Set[str]] = []
    for record in records:
        record_aliases = aliases(record)
        matching = [
            index
            for index, known in enumerate(grouped_aliases)
            if record_aliases & known
            and not sc.stable_identifier_conflict(grouped[index], record)
        ]
        if not matching:
            grouped.append(record.copy())
            grouped_aliases.append(set(record_aliases))
            continue
        target_index = matching[0]
        target = grouped[target_index]
        merge_values(target, record)
        grouped_aliases[target_index].update(record_aliases)
        for index in reversed(matching[1:]):
            duplicate = grouped[index]
            if sc.stable_identifier_conflict(target, duplicate):
                continue
            grouped.pop(index)
            duplicate_aliases = grouped_aliases.pop(index)
            grouped_aliases[target_index].update(duplicate_aliases)
            merge_values(target, duplicate)
    return grouped


def tag_record(record: Dict[str, Any], query: Dict[str, Any]) -> Dict[str, Any]:
    tagged = record.copy()
    tagged["matched_queries"] = [query["id"]]
    tagged["query_intents"] = [query["intent"]]
    tagged["source_occurrences"] = [
        {
            "source_name": record.get("source_name"),
            "record_id": record.get("record_id"),
            "url": record.get("url"),
            "query_id": query["id"],
        }
    ]
    return tagged


def annotate_candidate(record: Dict[str, Any]) -> None:
    publication_types = " ".join(record.get("publication_types", [])).casefold()
    title_abstract = " ".join(
        filter(None, [record.get("title"), record.get("abstract")])
    ).casefold()
    case_signal = (
        "case report" in publication_types
        or "case-report" in publication_types
        or "case report" in title_abstract
    )
    official = any(
        source in {"PubMed", "Europe PMC"} for source in record.get("found_via", [])
    )
    identifier = bool(record.get("doi") or record.get("pmid") or record.get("pmcid"))
    query_count = len(set(record.get("matched_queries", [])))
    intent_count = len(set(record.get("query_intents", [])))
    if official and case_signal and identifier:
        retrieval_confidence = "high"
    elif identifier and (official or query_count >= 2):
        retrieval_confidence = "medium"
    else:
        retrieval_confidence = "discovery_only"
    record["retrieval_support"] = {
        "retrieval_confidence": retrieval_confidence,
        "official_index_match": official,
        "case_report_signal": case_signal,
        "stable_identifier": identifier,
        "matched_query_count": query_count,
        "matched_intent_count": intent_count,
    }


def protocol_audit(
    plan: Dict[str, Any],
    queries: List[Dict[str, Any]],
    coverage: List[Dict[str, Any]],
    mode: str,
) -> Dict[str, Any]:
    intents = {query["intent"] for query in queries}
    languages = {query["language"] for query in queries}
    successful_sources = {
        item["source_key"] for item in coverage if item["status"] == "success"
    }
    successful_pairs = {
        (item["intent"], item["source_key"])
        for item in coverage
        if item["status"] == "success"
    }
    requirements = plan.get("requirements") or {}
    missing: List[str] = []
    warnings: List[str] = []
    if mode == "comprehensive":
        for intent in sorted(CORE_INTENTS - intents):
            missing.append(f"missing API query intent: {intent}")
        for intent in sorted(CORE_INTENTS):
            for source in ("pubmed", "europepmc"):
                if intent in intents and (intent, source) not in successful_pairs:
                    missing.append(
                        f"core intent {intent} not successfully searched in {source}"
                    )
        broad_unfiltered_succeeded = any(
            item["intent"] == "broad_synonyms"
            and item["case_filter"] is False
            and item["status"] == "success"
            for item in coverage
        )
        if not broad_unfiltered_succeeded:
            missing.append(
                "no broad_synonyms query successfully ran with case_filter=false"
            )
    required_languages = {
        str(language).strip().lower()
        for language in requirements.get("languages", ["en"])
    }
    for language in sorted(required_languages - languages):
        if language == "zh" and plan.get("browser_queries"):
            continue
        missing.append(f"required language has no search query: {language}")
    pending: List[str] = []
    if requirements.get("include_chinese_sources"):
        if plan.get("browser_queries"):
            pending.append("execute and log Chinese browser/database searches")
        else:
            missing.append("Chinese sources required but browser_queries is empty")
    if requirements.get("include_wechat"):
        if plan.get("wechat_queries"):
            pending.append(
                "execute bounded WeChat/TikHub searches and verify original sources"
            )
        else:
            missing.append("WeChat required but wechat_queries is empty")
    if requirements.get("citation_chaining"):
        pending.append(
            "expand verified seed cases through references, citations, and related works"
        )
    failed_required = [
        item
        for item in coverage
        if item["status"] != "success" and item.get("required")
    ]
    if failed_required:
        warnings.append(
            f"{len(failed_required)} required query-source executions failed"
        )
    status = "api_stage_complete"
    if missing or failed_required:
        status = "incomplete"
    elif pending:
        status = "api_stage_complete_external_steps_pending"
    return {
        "status": status,
        "missing_requirements": missing,
        "pending_steps": pending,
        "warnings": warnings,
        "searched_intents": sorted(intents),
        "searched_languages": sorted(languages),
        "successful_api_sources": sorted(successful_sources),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan", required=True, help="JSON search plan path, or - for stdin"
    )
    parser.add_argument(
        "--mode", choices=("comprehensive", "quick"), default="comprehensive"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Results per query-source execution (1-50)",
    )
    parser.add_argument(
        "--max-api-searches",
        type=int,
        default=30,
        help="Hard cap on query-source executions",
    )
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Parallel source workers; PubMed remains serialized",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 50:
        parser.error("--limit must be between 1 and 50")
    if not 1 <= args.max_api_searches <= 100:
        parser.error("--max-api-searches must be between 1 and 100")
    if not 1 <= args.workers <= 8:
        parser.error("--workers must be between 1 and 8")
    if not 1 <= args.timeout <= 300:
        parser.error("--timeout must be between 1 and 300 seconds")

    try:
        plan = load_plan(args.plan)
        queries = validate_plan(plan, args.mode)
        validate_supplemental_queries(plan)
        scheduled = sum(len(query["sources"]) for query in queries)
        if scheduled > args.max_api_searches:
            raise PlanError(
                f"plan schedules {scheduled} API searches, exceeding --max-api-searches {args.max_api_searches}"
            )
    except PlanError as exc:
        parser.error(str(exc))

    retrieved_at = sc.utc_now()
    connectors = {
        "pubmed": sc.pubmed_search,
        "europepmc": sc.europepmc_search,
        "openalex": sc.openalex_search,
        "crossref": sc.crossref_search,
    }
    source_semaphores = {
        "pubmed": threading.Semaphore(1),
        "europepmc": threading.Semaphore(2),
        "openalex": threading.Semaphore(2),
        "crossref": threading.Semaphore(2),
    }
    raw_records: List[Dict[str, Any]] = []
    coverage: List[Dict[str, Any]] = []
    scheduled_tasks: List[Tuple[Dict[str, Any], str, Dict[str, Any]]] = []
    for query in queries:
        for source in query["sources"]:
            source_name, source_class, retrieval_method = sc.SOURCE_CLASSES[source]
            entry = {
                "query_id": query["id"],
                "intent": query["intent"],
                "language": query["language"],
                "source_key": source,
                "source_name": source_name,
                "source_class": source_class,
                "retrieval_method": retrieval_method,
                "required": query["required"],
                "case_filter": query["case_filter"],
                "status": "failed",
                "retrieved_at": retrieved_at,
                "effective_query": None,
                "total_hits": None,
                "returned": 0,
                "new_unique_candidates": 0,
                "limitation": None,
            }
            scheduled_tasks.append((query, source, entry))

    def execute_task(
        task: Tuple[Dict[str, Any], str, Dict[str, Any]],
    ) -> Tuple[Optional[Tuple[str, int, List[Dict[str, Any]]]], Optional[str]]:
        query, source, _ = task
        try:
            with source_semaphores[source]:
                result = connectors[source](
                    query["text"],
                    args.limit,
                    args.timeout,
                    retrieved_at,
                    query["case_filter"],
                )
                if source == "pubmed" and not sc.os.getenv("NCBI_API_KEY"):
                    sc.time.sleep(0.34)
            return result, None
        except Exception as exc:
            return None, str(exc)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        task_results = list(executor.map(execute_task, scheduled_tasks))

    unique_before = 0
    for task, task_result in zip(scheduled_tasks, task_results):
        query, _, entry = task
        result, error = task_result
        if result is not None:
            effective_query, total, records = result
            tagged = [tag_record(record, query) for record in records]
            raw_records.extend(tagged)
            unique_after = len(merge_with_aliases(raw_records))
            entry.update(
                status="success",
                effective_query=effective_query,
                total_hits=total,
                returned=len(records),
                new_unique_candidates=max(0, unique_after - unique_before),
            )
            unique_before = unique_after
        else:
            entry["limitation"] = error
        coverage.append(entry)

    records = merge_with_aliases(raw_records)
    for record in records:
        annotate_candidate(record)
    records.sort(
        key=lambda record: (
            {"high": 2, "medium": 1, "discovery_only": 0}[
                record["retrieval_support"]["retrieval_confidence"]
            ],
            record["retrieval_support"]["matched_intent_count"],
            record["retrieval_support"]["matched_query_count"],
            record.get("year") or 0,
        ),
        reverse=True,
    )
    output = {
        "case_id": plan.get("case_id"),
        "case_fingerprint": plan.get("case_fingerprint"),
        "mode": args.mode,
        "retrieved_at": retrieved_at,
        "live_search": True,
        "notice": "Protocol coverage is measurable, but no search can prove that every published or unpublished case was found.",
        "plan_summary": {
            "api_queries": len(queries),
            "api_searches_scheduled": scheduled,
            "browser_queries_planned": len(plan.get("browser_queries") or []),
            "wechat_queries_planned": len(plan.get("wechat_queries") or []),
        },
        "protocol_audit": protocol_audit(plan, queries, coverage, args.mode),
        "coverage": coverage,
        "unique_candidate_count": len(records),
        "records": records,
    }
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0 if any(item["status"] == "success" for item in coverage) else 2


if __name__ == "__main__":
    raise SystemExit(main())

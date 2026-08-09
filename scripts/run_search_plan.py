#!/usr/bin/env python3
"""Execute a reproducible multi-query case-report search plan across scholarly APIs."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import html
import json
import re
import sys
import threading
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import search_cases as sc
import rerank_candidates as rc
import write_search_bundle as wsb


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
EVIDENCE_FIELDS = {"title", "abstract", "journal", "publication_types"}
RRF_K = 60


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


def normalize_string_list(value: Any, location: str) -> List[str]:
    if not isinstance(value, list) or not value:
        raise PlanError(f"{location} must be a non-empty array")
    normalized: List[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not (term := sc.compact(item)):
            raise PlanError(f"{location}[{index}] must be a non-empty string")
        sensitive = sc.detect_sensitive_query(term)
        if sensitive:
            raise PlanError(
                f"{location}[{index}] may contain sensitive identifiers: "
                + ", ".join(sensitive)
            )
        if term not in normalized:
            normalized.append(term)
    return normalized


def normalize_concept_groups(value: Any, location: str) -> List[List[str]]:
    if not isinstance(value, list) or not value:
        raise PlanError(f"{location} must be a non-empty array of term arrays")
    return [
        normalize_string_list(group, f"{location}[{index}]")
        for index, group in enumerate(value)
    ]


def compile_concept_groups(groups: List[List[str]]) -> str:
    """Compile provider-neutral AND-of-OR groups without medical assumptions."""

    rendered_groups = []
    for group in groups:
        alternatives = " OR ".join(f"({term})" for term in group)
        rendered_groups.append(f"({alternatives})")
    return " AND ".join(rendered_groups)


def validate_candidate_features(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    values = plan.get("candidate_features", [])
    if values is None:
        values = []
    if not isinstance(values, list):
        raise PlanError("candidate_features must be an array")
    seen: Set[str] = set()
    normalized: List[Dict[str, Any]] = []
    for index, value in enumerate(values):
        location = f"candidate_features[{index}]"
        if not isinstance(value, dict):
            raise PlanError(f"{location} must be an object")
        feature_id = sc.compact(value.get("id"))
        if not feature_id or feature_id in seen:
            raise PlanError(f"{location}.id must be unique and non-empty")
        label = sc.compact(value.get("label")) or feature_id
        terms = normalize_string_list(value.get("terms"), f"{location}.terms")
        mismatch_terms = value.get("mismatch_terms") or []
        if not isinstance(mismatch_terms, list):
            raise PlanError(f"{location}.mismatch_terms must be an array")
        if mismatch_terms:
            mismatch_terms = normalize_string_list(
                mismatch_terms, f"{location}.mismatch_terms"
            )
        weight = value.get("weight", 1)
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or weight <= 0
        ):
            raise PlanError(f"{location}.weight must be a positive number")
        required = value.get("required", False)
        if not isinstance(required, bool):
            raise PlanError(f"{location}.required must be true or false")
        fields = value.get("fields") or ["title", "abstract"]
        if not isinstance(fields, list) or not fields or not all(
            isinstance(field, str) and field.strip() for field in fields
        ):
            raise PlanError(f"{location}.fields must be a non-empty string array")
        fields = list(dict.fromkeys(field.strip() for field in fields))
        unknown_fields = sorted(set(fields) - EVIDENCE_FIELDS)
        if unknown_fields:
            raise PlanError(
                f"{location}.fields contains unsupported values: "
                + ", ".join(unknown_fields)
            )
        overlap = {
            normalize_evidence_text(term) for term in terms
        } & {normalize_evidence_text(term) for term in mismatch_terms}
        if overlap:
            raise PlanError(
                f"{location} uses the same term as matching and mismatching evidence"
            )
        seen.add(feature_id)
        normalized.append(
            {
                "id": feature_id,
                "label": label,
                "terms": terms,
                "mismatch_terms": mismatch_terms,
                "weight": float(weight),
                "required": required,
                "fields": fields,
            }
        )
    return normalized


def validate_selection_policy(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a case-local verified-case reporting policy.

    This policy never limits retrieval or document triage.  Its optional limit
    applies only after patient-level verification and deduplication.
    """

    value = plan.get("selection_policy")
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise PlanError("selection_policy must be an object")
    detailed_limit = value.get("max_detailed_verified_cases")
    if detailed_limit is not None and (
        isinstance(detailed_limit, bool)
        or not isinstance(detailed_limit, int)
        or detailed_limit < 1
    ):
        raise PlanError(
            "selection_policy.max_detailed_verified_cases must be a positive integer or null"
        )
    dimensions = value.get("ranking_dimensions")
    if dimensions is None:
        dimensions = []
    if not isinstance(dimensions, list):
        raise PlanError("selection_policy.ranking_dimensions must be an array")
    if dimensions:
        dimensions = normalize_string_list(
            dimensions, "selection_policy.ranking_dimensions"
        )
    return {
        "retrieval_policy": "maximize_recall_until_stopping_rule",
        "eligibility_scope": "patient_level_verified_close_cases",
        "max_detailed_verified_cases": detailed_limit,
        "retain_all_eligible_cases": True,
        "overflow_destination": "supplement_and_machine_results",
        "ranking_dimensions": dimensions,
        "notice": (
            "The optional limit controls detailed presentation only. It does not "
            "cap retrieval, screening, verification, or the total eligible-case count."
        ),
    }


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
        for field in ("id", "intent"):
            if not isinstance(query.get(field), str):
                raise PlanError(f"api_queries[{index}].{field} must be a string")
        has_text = "text" in query and query.get("text") is not None
        has_groups = (
            "concept_groups" in query and query.get("concept_groups") is not None
        )
        if has_text == has_groups:
            raise PlanError(
                f"api_queries[{index}] must define exactly one of text or concept_groups"
            )
        if has_text and not isinstance(query.get("text"), str):
            raise PlanError(f"api_queries[{index}].text must be a string")
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
        concept_groups: List[List[str]] = []
        if has_groups:
            concept_groups = normalize_concept_groups(
                query.get("concept_groups"), f"api_queries[{index}].concept_groups"
            )
            text = compile_concept_groups(concept_groups)
            query_representation = "concept_groups"
        else:
            text = sc.compact(query.get("text"))
            query_representation = "legacy_text"
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
                "concept_groups": concept_groups,
                "query_representation": query_representation,
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


def merge_with_aliases(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate records by identifier and title-year-author aliases.

    Delegates to the shared implementation in search_cases.py so dedup logic
    cannot drift between the scripts that rely on it.
    """

    return sc.merge_records(records)


def tag_record(
    record: Dict[str, Any],
    query: Dict[str, Any],
    source_key: str,
    source_rank: int,
) -> Dict[str, Any]:
    tagged = record.copy()
    tagged["matched_queries"] = [query["id"]]
    tagged["query_intents"] = [query["intent"]]
    tagged["source_occurrences"] = [
        {
            "source_key": source_key,
            "source_name": record.get("source_name"),
            "record_id": record.get("record_id"),
            "url": record.get("url"),
            "query_id": query["id"],
            "query_intent": query["intent"],
            "rank": source_rank,
        }
    ]
    return tagged


def normalize_evidence_text(value: Any) -> str:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    cleaned = sc.clean_markup(html.unescape(str(value or ""))) or ""
    return unicodedata.normalize("NFKC", cleaned).casefold()


def contains_evidence_term(text: str, term: str) -> bool:
    normalized_term = normalize_evidence_text(term)
    if not normalized_term:
        return False
    if normalized_term[0].isascii() and normalized_term[0].isalnum():
        prefix = r"(?<![A-Za-z0-9])"
    else:
        prefix = ""
    if normalized_term[-1].isascii() and normalized_term[-1].isalnum():
        suffix = r"(?![A-Za-z0-9])"
    else:
        suffix = ""
    return bool(re.search(prefix + re.escape(normalized_term) + suffix, text))


def first_feature_evidence(
    field_text: Dict[str, str], terms: List[str], fields: List[str]
) -> Optional[Dict[str, str]]:
    # Prefer stronger fields (normally title before abstract) even when the
    # matching title uses a later synonym from the configured term list.
    for field in fields:
        for term in terms:
            if contains_evidence_term(field_text.get(field, ""), term):
                return {"term": term, "field": field}
    return None


def annotate_feature_evidence(
    record: Dict[str, Any], features: List[Dict[str, Any]]
) -> None:
    if not features:
        return
    field_text = {
        field: normalize_evidence_text(record.get(field)) for field in EVIDENCE_FIELDS
    }
    details: List[Dict[str, Any]] = []
    matched_weight = 0.0
    mismatched_weight = 0.0
    title_matched_weight = 0.0
    required_matched_weight = 0.0
    required_total_weight = 0.0
    status_counts = {"matched": 0, "mismatched": 0, "conflicting": 0, "unknown": 0}
    for feature in features:
        match = first_feature_evidence(
            field_text, feature["terms"], feature["fields"]
        )
        mismatch = first_feature_evidence(
            field_text, feature["mismatch_terms"], feature["fields"]
        )
        if match and mismatch:
            status = "conflicting"
        elif match:
            status = "matched"
        elif mismatch:
            status = "mismatched"
        else:
            status = "unknown"
        status_counts[status] += 1
        if status == "matched":
            matched_weight += feature["weight"]
            if match["field"] == "title":
                title_matched_weight += feature["weight"]
            if feature["required"]:
                required_matched_weight += feature["weight"]
        if status in {"mismatched", "conflicting"}:
            mismatched_weight += feature["weight"]
        if feature["required"]:
            required_total_weight += feature["weight"]
        evidence = []
        if match:
            evidence.append({"kind": "match", **match})
        if mismatch:
            evidence.append({"kind": "mismatch", **mismatch})
        details.append(
            {
                "id": feature["id"],
                "label": feature["label"],
                "weight": feature["weight"],
                "required": feature["required"],
                "status": status,
                "evidence": evidence,
            }
        )
    total_weight = sum(feature["weight"] for feature in features)
    record["feature_evidence"] = {
        "method": "plan_defined_term_evidence",
        "notice": (
            "This is document-level triage from configured terms, not validated "
            "clinical similarity. Missing text is unknown, not a clinical mismatch."
        ),
        "matched_weight": matched_weight,
        "mismatched_weight": mismatched_weight,
        "matched_feature_count": status_counts["matched"],
        "title_matched_weight": title_matched_weight,
        "total_weight": total_weight,
        "evidence_match_percent": round(100 * matched_weight / total_weight, 2),
        "required_matched_weight": required_matched_weight,
        "required_total_weight": required_total_weight,
        "required_evidence_match_percent": (
            round(100 * required_matched_weight / required_total_weight, 2)
            if required_total_weight
            else None
        ),
        "status_counts": status_counts,
        "features": details,
    }


def candidate_sort_key(
    record: Dict[str, Any], use_feature_evidence: bool, use_reranker: bool = False
) -> Tuple[Any, ...]:
    retrieval = record["retrieval_support"]
    retrieval_key = (
        retrieval["rrf_score"],
        {"high": 2, "medium": 1, "discovery_only": 0}[
            retrieval["retrieval_confidence"]
        ],
        retrieval["matched_intent_count"],
        retrieval["matched_query_count"],
        -(retrieval["best_source_rank"] or 10**9),
        record.get("year") or 0,
    )
    reranker = record.get("reranker") or {}
    reranker_key = (
        (1, reranker["score"])
        if use_reranker and isinstance(reranker.get("score"), (int, float))
        else (0, float("-inf"))
    )
    if not use_feature_evidence:
        return (*reranker_key, *retrieval_key) if use_reranker else retrieval_key
    evidence = record["feature_evidence"]
    required_percent = evidence["required_evidence_match_percent"]
    return (
        required_percent if required_percent is not None else -1,
        -evidence["mismatched_weight"],
        retrieval["case_report_signal"],
        evidence["title_matched_weight"],
        *reranker_key,
        evidence["evidence_match_percent"],
        evidence["matched_feature_count"],
        *retrieval_key,
    )


def count_with_items(items: Set[str]) -> Dict[str, Any]:
    values = sorted(items)
    return {"count": len(values), "items": values}


def summarize_dimensions(
    records: List[Dict[str, Any]], features: List[Dict[str, Any]]
) -> Dict[str, Any]:
    dimensions = []
    for priority_order, feature in enumerate(features, start=1):
        counts = {"matched": 0, "mismatched": 0, "conflicting": 0, "unknown": 0}
        for record in records:
            feature_details = {
                detail["id"]: detail
                for detail in (record.get("feature_evidence") or {}).get(
                    "features", []
                )
            }
            status = (feature_details.get(feature["id"]) or {}).get(
                "status", "unknown"
            )
            counts[status] += 1
        dimensions.append(
            {
                "priority_order": priority_order,
                "id": feature["id"],
                "label": feature["label"],
                "weight": feature["weight"],
                "required": feature["required"],
                "candidate_status_counts": counts,
            }
        )
    return {
        "configured_dimension_count": len(features),
        "dimensions": dimensions,
        "notice": (
            "Counts describe configured term evidence in retrieved documents. "
            "They do not count verified patients or establish clinical similarity."
        ),
    }


def build_result_accounting(
    queries: List[Dict[str, Any]],
    coverage: List[Dict[str, Any]],
    records: List[Dict[str, Any]],
    features: List[Dict[str, Any]],
) -> Dict[str, Any]:
    planned_families = {query["intent"] for query in queries}
    attempted_families = {item["intent"] for item in coverage}
    successful_families = {
        item["intent"] for item in coverage if item["status"] == "success"
    }
    fully_successful_families = set()
    for intent in planned_families:
        intent_executions = [
            item for item in coverage if item["intent"] == intent
        ]
        if intent_executions and all(
            item["status"] == "success" for item in intent_executions
        ):
            fully_successful_families.add(intent)
    supported_sources = {
        f"{source}:{sc.SOURCE_CLASSES[source][0]}" for source in sc.SUPPORTED_SOURCES
    }
    planned_sources = {source for query in queries for source in query["sources"]}
    attempted_sources = {item["source_key"] for item in coverage}
    successful_sources = {
        item["source_key"] for item in coverage if item["status"] == "success"
    }
    raw_returned = sum(int(item.get("returned") or 0) for item in coverage)
    reported_hits = sum(
        int(item.get("total_hits") or 0)
        for item in coverage
        if item["status"] == "success"
    )
    succeeded_executions = sum(item["status"] == "success" for item in coverage)
    failed_executions = len(coverage) - succeeded_executions
    return {
        "scope": "live_api_stage",
        "query_families": {
            "supported": count_with_items(set(ALLOWED_INTENTS)),
            "planned": count_with_items(planned_families),
            "attempted": count_with_items(attempted_families),
            "succeeded_on_at_least_one_source": count_with_items(
                successful_families
            ),
            "succeeded_on_all_planned_sources": count_with_items(
                fully_successful_families
            ),
        },
        "source_routes": {
            "supported": count_with_items(supported_sources),
            "planned": count_with_items(planned_sources),
            "attempted": count_with_items(attempted_sources),
            "usable_this_run": count_with_items(successful_sources),
        },
        "query_source_executions": {
            "planned": len(coverage),
            "attempted": len(coverage),
            "succeeded": succeeded_executions,
            "failed": failed_executions,
        },
        "candidate_funnel": {
            "provider_reported_hits_sum": reported_hits,
            "returned_records_before_deduplication": raw_returned,
            "duplicate_record_occurrences_removed": max(
                0, raw_returned - len(records)
            ),
            "unique_candidates_after_deduplication": len(records),
            "document_triaged_candidates": len(records) if features else 0,
            "ranked_candidates": len(records),
            "clinically_verified_patient_cases": None,
            "included_close_cases": None,
            "detailed_included_cases": None,
            "additional_included_cases_retained": None,
            "near_misses": None,
            "excluded_after_verification": None,
        },
        "dimension_summary": summarize_dimensions(records, features),
        "notices": [
            "Provider-reported hit totals overlap across queries and sources and are not unique cases.",
            "Returned records and deduplicated candidates are publications or index records, not verified patient counts.",
            "Complete the null verification fields only after source-level and patient-level review.",
            "Browser, subscription, Chinese, specialty, citation-expansion, and social routes require separate accounting when used.",
        ],
    }


def annotate_candidate(
    record: Dict[str, Any], features: Optional[List[Dict[str, Any]]] = None
) -> None:
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
    ranked_occurrences: Dict[Tuple[str, str], int] = {}
    for occurrence in record.get("source_occurrences", []):
        source_key = str(
            occurrence.get("source_key") or occurrence.get("source_name") or ""
        )
        query_id = str(occurrence.get("query_id") or "")
        rank = occurrence.get("rank")
        if (
            not source_key
            or not query_id
            or isinstance(rank, bool)
            or not isinstance(rank, int)
            or rank < 1
        ):
            continue
        key = (source_key, query_id)
        ranked_occurrences[key] = min(rank, ranked_occurrences.get(key, rank))
    ranks = list(ranked_occurrences.values())
    rrf_score = sum(1.0 / (RRF_K + rank) for rank in ranks)
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
        "rank_fusion_method": f"rrf_k_{RRF_K}",
        "ranked_occurrence_count": len(ranks),
        "best_source_rank": min(ranks) if ranks else None,
        "rrf_score": round(rrf_score, 8),
    }
    annotate_feature_evidence(record, features or [])


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
    legacy_queries = [
        query
        for query in queries
        if query.get("query_representation") == "legacy_text"
    ]
    if legacy_queries:
        warnings.append(
            f"{len(legacy_queries)} API queries use legacy free text; "
            "Boolean grouping was not structurally compiled"
        )
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
    parser.add_argument(
        "--output-root",
        help="Write search-report.md, search-results.json, and case files below this directory",
    )
    parser.add_argument(
        "--output-label",
        help="De-identified brief used in the timestamped output directory name",
    )
    parser.add_argument(
        "--reranker",
        choices=("none", "medcpt", "siliconflow"),
        default="none",
        help="Optional local or SiliconFlow cross-encoder reranker",
    )
    parser.add_argument("--reranker-model")
    parser.add_argument("--reranker-revision")
    parser.add_argument("--reranker-endpoint")
    parser.add_argument("--rerank-top-k", type=int, default=50)
    parser.add_argument("--reranker-batch-size", type=int, default=8)
    parser.add_argument("--reranker-max-length", type=int, default=512)
    parser.add_argument(
        "--reranker-device",
        choices=("auto", "cpu", "mps", "cuda"),
        default="auto",
    )
    parser.add_argument(
        "--reranker-required",
        action="store_true",
        help="Fail instead of preserving the pre-reranker order when reranking is unavailable",
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= 50:
        parser.error("--limit must be between 1 and 50")
    if not 1 <= args.max_api_searches <= 100:
        parser.error("--max-api-searches must be between 1 and 100")
    if not 1 <= args.workers <= 8:
        parser.error("--workers must be between 1 and 8")
    if not 1 <= args.timeout <= 300:
        parser.error("--timeout must be between 1 and 300 seconds")
    if not 1 <= args.rerank_top_k <= 200:
        parser.error("--rerank-top-k must be between 1 and 200")
    if not 1 <= args.reranker_batch_size <= 64:
        parser.error("--reranker-batch-size must be between 1 and 64")
    if not 64 <= args.reranker_max_length <= 1024:
        parser.error("--reranker-max-length must be between 64 and 1024")
    if args.reranker_required and args.reranker == "none":
        parser.error("--reranker-required requires --reranker medcpt or siliconflow")
    if args.output_label and not args.output_root:
        parser.error("--output-label requires --output-root")
    if args.output_label:
        sensitive_label = sc.detect_sensitive_query(args.output_label)
        if sensitive_label:
            parser.error(
                "--output-label may contain sensitive identifiers: "
                + ", ".join(sensitive_label)
            )

    try:
        plan = load_plan(args.plan)
        queries = validate_plan(plan, args.mode)
        candidate_features = validate_candidate_features(plan)
        selection_policy = validate_selection_policy(plan)
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
                "query_representation": query["query_representation"],
                "concept_groups": query["concept_groups"] or None,
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
        query, source, entry = task
        result, error = task_result
        if result is not None:
            effective_query, total, records = result
            tagged = [
                tag_record(record, query, source, rank)
                for rank, record in enumerate(records, start=1)
            ]
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
        annotate_candidate(record, candidate_features)
    records.sort(
        key=lambda record: candidate_sort_key(record, bool(candidate_features)),
        reverse=True,
    )
    reranker_summary: Dict[str, Any] = {
        "status": "not_requested",
        "backend": args.reranker,
    }
    reranker_model = args.reranker_model or (
        rc.DEFAULT_SILICONFLOW_MODEL
        if args.reranker == "siliconflow"
        else rc.DEFAULT_MODEL
    )
    reranker_revision = args.reranker_revision or (
        rc.DEFAULT_SILICONFLOW_REVISION
        if args.reranker == "siliconflow"
        else rc.DEFAULT_REVISION
    )
    reranker_endpoint = args.reranker_endpoint or rc.env_value(
        "SILICONFLOW_RERANK_ENDPOINT"
    ) or rc.DEFAULT_SILICONFLOW_ENDPOINT
    if args.reranker in {"medcpt", "siliconflow"}:
        try:
            reranker_query = rc.build_case_query(plan)
            scorer = (
                rc.score_documents_siliconflow
                if args.reranker == "siliconflow"
                else rc.score_documents
            )
            reranker_summary = rc.rerank_records(
                records,
                reranker_query,
                top_k=args.rerank_top_k,
                model_name=reranker_model,
                revision=reranker_revision,
                batch_size=args.reranker_batch_size,
                max_length=args.reranker_max_length,
                device=(
                    "remote" if args.reranker == "siliconflow" else args.reranker_device
                ),
                endpoint=reranker_endpoint,
                scorer=scorer,
            )
            scored_count = reranker_summary["candidates_scored"]
            prefix = records[:scored_count]
            prefix.sort(
                key=lambda record: candidate_sort_key(
                    record, bool(candidate_features), True
                ),
                reverse=True,
            )
            records[:scored_count] = prefix
            for post_rank, record in enumerate(prefix, start=1):
                record["reranker"]["post_reranker_rank"] = post_rank
        except rc.RerankerError as exc:
            if args.reranker_required:
                parser.error(f"reranker failed: {exc}")
            reranker_summary = {
                "status": "skipped",
                "backend": args.reranker,
                "model": reranker_model,
                "requested_revision": reranker_revision,
                "reason": str(exc),
                "fallback": "preserved_pre_reranker_order",
            }
    if reranker_summary.get("status") == "applied":
        candidate_ranking = (
            "plan_defined_required_and_mismatch_guardrails_then_"
            f"{args.reranker}_cross_encoder_then_feature_and_rrf_support"
            if candidate_features
            else f"{args.reranker}_cross_encoder_then_rrf_retrieval_support"
        )
    else:
        candidate_ranking = (
            "plan_defined_feature_evidence_then_rrf_retrieval_support"
            if candidate_features
            else "rrf_retrieval_support"
        )
    output = {
        "case_id": plan.get("case_id"),
        "case_fingerprint": plan.get("case_fingerprint"),
        "mode": args.mode,
        "retrieved_at": retrieved_at,
        "live_search": True,
        "notice": "Protocol coverage is measurable, but no search can prove that every published or unpublished case was found.",
        "api_query_plan": queries,
        "candidate_features": candidate_features,
        "selection_policy": selection_policy,
        "reranker": reranker_summary,
        "plan_summary": {
            "api_queries": len(queries),
            "api_searches_scheduled": scheduled,
            "structured_api_queries": sum(
                query["query_representation"] == "concept_groups"
                for query in queries
            ),
            "legacy_text_api_queries": sum(
                query["query_representation"] == "legacy_text" for query in queries
            ),
            "candidate_features": len(candidate_features),
            "max_detailed_verified_cases": selection_policy[
                "max_detailed_verified_cases"
            ],
            "candidate_ranking": candidate_ranking,
            "rank_fusion": f"reciprocal_rank_fusion_k_{RRF_K}",
            "reranker": reranker_summary.get("status"),
            "reranker_model": reranker_summary.get("model"),
            "browser_queries_planned": len(plan.get("browser_queries") or []),
            "wechat_queries_planned": len(plan.get("wechat_queries") or []),
        },
        "protocol_audit": protocol_audit(plan, queries, coverage, args.mode),
        "result_accounting": build_result_accounting(
            queries, coverage, records, candidate_features
        ),
        "coverage": coverage,
        "unique_candidate_count": len(records),
        "records": records,
    }
    if args.output_root:
        try:
            wsb.write_bundle(output, args.output_root, args.output_label)
        except (OSError, ValueError) as exc:
            parser.error(f"cannot write output bundle: {exc}")
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0 if any(item["status"] == "success" for item in coverage) else 2


if __name__ == "__main__":
    raise SystemExit(main())

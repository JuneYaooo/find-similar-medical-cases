#!/usr/bin/env python3
"""Run a bounded live smoke test using published PMC-Patients case studies."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, Iterable, List

import run_search_plan as rsp
import rerank_candidates as rc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK = ROOT / "benchmarks" / "pmc-patients-case-studies.json"
DEFAULT_K_VALUES = (5, 10, 20, 50)


class BenchmarkError(RuntimeError):
    pass


def load_benchmark(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"cannot read benchmark: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise BenchmarkError("benchmark must be an object with a cases array")
    if payload.get("evaluation_scope") != "live_api_smoke_test":
        raise BenchmarkError("benchmark evaluation_scope must be live_api_smoke_test")
    caveat = payload.get("caveat")
    if not isinstance(caveat, str) or "not exhaustive relevance judgments" not in caveat:
        raise BenchmarkError(
            "benchmark caveat must state that references are not exhaustive relevance judgments"
        )
    seen = set()
    for index, case in enumerate(payload["cases"]):
        if not isinstance(case, dict):
            raise BenchmarkError(f"cases[{index}] must be an object")
        case_id = case.get("id")
        references = case.get("reference_top5")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise BenchmarkError(f"cases[{index}].id must be unique and non-empty")
        if not isinstance(references, list) or len(references) != 5:
            raise BenchmarkError(f"case {case_id} requires exactly five reference_top5 items")
        if not all(isinstance(item, dict) for item in references):
            raise BenchmarkError(f"case {case_id} reference_top5 items must be objects")
        pmids = [str(item.get("pmid") or "") for item in references]
        if any(not pmid for pmid in pmids) or len(pmids) != len(set(pmids)):
            raise BenchmarkError(f"case {case_id} has invalid reference PMIDs")
        if [item.get("rank") for item in references] != [1, 2, 3, 4, 5]:
            raise BenchmarkError(f"case {case_id} reference ranks must be 1 through 5")
        if any(not isinstance(item.get("title"), str) or not item["title"] for item in references):
            raise BenchmarkError(f"case {case_id} reference titles must be non-empty")
        if not isinstance(case.get("plan"), dict):
            raise BenchmarkError(f"case {case_id} requires a plan object")
        seen.add(case_id)
    return payload


def select_cases(cases: List[Dict[str, Any]], requested: str | None) -> List[Dict[str, Any]]:
    if not requested:
        return cases
    ids = [item.strip() for item in requested.split(",") if item.strip()]
    available = {case["id"]: case for case in cases}
    unknown = sorted(set(ids) - set(available))
    if unknown:
        raise BenchmarkError("unknown case ids: " + ", ".join(unknown))
    return [available[case_id] for case_id in ids]


def build_plan(case: Dict[str, Any]) -> Dict[str, Any]:
    plan = deepcopy(case["plan"])
    plan["case_id"] = case["id"]
    plan.setdefault(
        "requirements",
        {
            "languages": ["en"],
            "include_chinese_sources": False,
            "include_wechat": False,
            "citation_chaining": False,
        },
    )
    plan.setdefault(
        "selection_policy",
        {
            "max_detailed_verified_cases": 20,
            "ranking_dimensions": [
                "case-defined clinical feature similarity",
                "independent query and source support",
                "original-source quality",
            ],
        },
    )
    return plan


def validate_plan(plan: Dict[str, Any], max_api_searches: int) -> Dict[str, Any]:
    try:
        queries = rsp.validate_plan(plan, "comprehensive")
        features = rsp.validate_candidate_features(plan)
        rsp.validate_selection_policy(plan)
        rsp.validate_supplemental_queries(plan)
    except rsp.PlanError as exc:
        raise BenchmarkError(
            f"invalid search plan for case {plan.get('case_id')}: {exc}"
        ) from exc
    scheduled = sum(len(query["sources"]) for query in queries)
    if scheduled > max_api_searches:
        raise BenchmarkError(
            f"case {plan.get('case_id')} schedules {scheduled} searches, "
            f"above the per-case cap {max_api_searches}"
        )
    return {
        "case_id": plan.get("case_id"),
        "query_families": sorted({query["intent"] for query in queries}),
        "query_source_executions": scheduled,
        "candidate_features": len(features),
    }


def run_plan(
    plan: Dict[str, Any],
    *,
    limit: int,
    max_api_searches: int,
    workers: int,
    timeout: int,
    reranker: str,
    reranker_model: str,
    reranker_revision: str,
    rerank_top_k: int,
    reranker_endpoint: str | None,
    reranker_required: bool,
) -> Dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_search_plan.py"),
        "--plan",
        "-",
        "--mode",
        "comprehensive",
        "--limit",
        str(limit),
        "--max-api-searches",
        str(max_api_searches),
        "--workers",
        str(workers),
        "--timeout",
        str(timeout),
        "--reranker",
        reranker,
        "--reranker-model",
        reranker_model,
        "--reranker-revision",
        reranker_revision,
        "--rerank-top-k",
        str(rerank_top_k),
    ]
    if reranker_endpoint:
        command.extend(("--reranker-endpoint", reranker_endpoint))
    if reranker_required:
        command.append("--reranker-required")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        input=json.dumps(plan),
        capture_output=True,
        text=True,
        timeout=max(120, timeout * max_api_searches),
    )
    if completed.returncode:
        raise BenchmarkError(
            f"case {plan.get('case_id')} failed: {completed.stderr.strip()}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise BenchmarkError(
            f"case {plan.get('case_id')} returned invalid JSON"
        ) from exc


def overlap_summary(reference_pmids: Iterable[str], ranks: Dict[str, int]) -> Dict[str, Any]:
    references = list(reference_pmids)
    values: Dict[str, Any] = {}
    for k in DEFAULT_K_VALUES:
        found = [pmid for pmid in references if 0 < ranks.get(pmid, 10**9) <= k]
        values[f"at_{k}"] = {
            "count": len(found),
            "denominator": len(references),
            "pmids": found,
        }
    found_anywhere = [pmid for pmid in references if pmid in ranks]
    values["anywhere"] = {
        "count": len(found_anywhere),
        "denominator": len(references),
        "pmids": found_anywhere,
    }
    return values


def evaluate_case(case: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    records = result.get("records") or []
    rank_by_pmid = {
        str(record.get("pmid")): rank
        for rank, record in enumerate(records, start=1)
        if record.get("pmid")
    }
    references = [str(item["pmid"]) for item in case["reference_top5"]]
    known_ranks = {
        pmid: rank_by_pmid[pmid] for pmid in references if pmid in rank_by_pmid
    }
    first_rank = min(known_ranks.values()) if known_ranks else None
    top10 = records[:10]
    feature_complete = sum(
        (record.get("feature_evidence") or {}).get(
            "required_evidence_match_percent"
        )
        == 100
        for record in top10
    )
    accounting = result.get("result_accounting") or {}
    executions = accounting.get("query_source_executions") or {}
    return {
        "case_id": case["id"],
        "scenario": case.get("scenario"),
        "retrieved_at": result.get("retrieved_at"),
        "protocol_status": (result.get("protocol_audit") or {}).get("status"),
        "reranker": result.get("reranker"),
        "unique_candidates": result.get("unique_candidate_count", len(records)),
        "query_source_executions": executions,
        "reference_top5_overlap": overlap_summary(references, rank_by_pmid),
        "reference_ranks": known_ranks,
        "first_reference_reciprocal_rank": (
            round(1.0 / first_rank, 6) if first_rank else 0.0
        ),
        "feature_complete_candidates_at_10": feature_complete,
        "top10": [
            {
                "rank": rank,
                "pmid": record.get("pmid"),
                "title": record.get("title"),
                "required_feature_percent": (
                    record.get("feature_evidence") or {}
                ).get("required_evidence_match_percent"),
                "title_matched_weight": (
                    record.get("feature_evidence") or {}
                ).get("title_matched_weight"),
                "rrf_score": (record.get("retrieval_support") or {}).get(
                    "rrf_score"
                ),
                "reranker_score": (record.get("reranker") or {}).get("score"),
                "pre_reranker_rank": (record.get("reranker") or {}).get(
                    "pre_reranker_rank"
                ),
            }
            for rank, record in enumerate(top10, start=1)
        ],
    }


def aggregate(case_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    completed = [result for result in case_results if "error" not in result]
    aggregate_overlap = {}
    for key in [f"at_{k}" for k in DEFAULT_K_VALUES] + ["anywhere"]:
        aggregate_overlap[key] = {
            "count": sum(
                result["reference_top5_overlap"][key]["count"]
                for result in completed
            ),
            "denominator": sum(
                result["reference_top5_overlap"][key]["denominator"]
                for result in completed
            ),
        }
    return {
        "cases_requested": len(case_results),
        "cases_completed": len(completed),
        "reference_top5_overlap": aggregate_overlap,
        "mean_first_reference_reciprocal_rank": (
            round(
                sum(
                    result["first_reference_reciprocal_rank"]
                    for result in completed
                )
                / len(completed),
                6,
            )
            if completed
            else 0.0
        ),
        "successful_query_source_executions": sum(
            result["query_source_executions"].get("succeeded", 0)
            for result in completed
        ),
        "failed_query_source_executions": sum(
            result["query_source_executions"].get("failed", 0)
            for result in completed
        ),
        "reranker_applied_cases": sum(
            (result.get("reranker") or {}).get("status") == "applied"
            for result in completed
        ),
        "reranker_skipped_cases": sum(
            (result.get("reranker") or {}).get("status") == "skipped"
            for result in completed
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--cases", help="Comma-separated case ids; default is all")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-api-searches", type=int, default=12)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--reranker", choices=("none", "medcpt", "siliconflow"), default="none"
    )
    parser.add_argument("--reranker-model")
    parser.add_argument("--reranker-revision")
    parser.add_argument("--reranker-endpoint")
    parser.add_argument("--rerank-top-k", type=int, default=50)
    parser.add_argument("--reranker-required", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 50:
        parser.error("--limit must be between 1 and 50")
    if not 1 <= args.max_api_searches <= 100:
        parser.error("--max-api-searches must be between 1 and 100")
    if not 1 <= args.workers <= 8:
        parser.error("--workers must be between 1 and 8")
    if not 1 <= args.rerank_top_k <= 200:
        parser.error("--rerank-top-k must be between 1 and 200")
    if args.reranker_required and args.reranker == "none":
        parser.error("--reranker-required requires --reranker medcpt or siliconflow")

    try:
        benchmark = load_benchmark(args.benchmark)
        cases = select_cases(benchmark["cases"], args.cases)
        plans = [build_plan(case) for case in cases]
        validation = [
            validate_plan(plan, args.max_api_searches) for plan in plans
        ]
    except BenchmarkError as exc:
        parser.error(str(exc))

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

    output: Dict[str, Any] = {
        "benchmark_id": benchmark.get("benchmark_id"),
        "benchmark_file": str(args.benchmark.resolve()),
        "run_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "live_search": not args.dry_run,
        "metric_warning": benchmark.get("caveat"),
        "configuration": {
            "cases": [case["id"] for case in cases],
            "limit_per_query_source": args.limit,
            "max_api_searches_per_case": args.max_api_searches,
            "workers": args.workers,
            "reranker": args.reranker,
            "reranker_model": reranker_model,
            "reranker_revision": reranker_revision,
            "rerank_top_k": args.rerank_top_k,
            "reranker_endpoint": (
                reranker_endpoint if args.reranker == "siliconflow" else None
            ),
        },
    }
    if args.dry_run:
        output["validated_plans"] = validation
        failed = False
    else:
        case_results = []
        for case, plan in zip(cases, plans):
            try:
                result = run_plan(
                    plan,
                    limit=args.limit,
                    max_api_searches=args.max_api_searches,
                    workers=args.workers,
                    timeout=args.timeout,
                    reranker=args.reranker,
                    reranker_model=reranker_model,
                    reranker_revision=reranker_revision,
                    rerank_top_k=args.rerank_top_k,
                    reranker_endpoint=(
                        reranker_endpoint if args.reranker == "siliconflow" else None
                    ),
                    reranker_required=args.reranker_required,
                )
                case_results.append(evaluate_case(case, result))
            except BenchmarkError as exc:
                case_results.append({"case_id": case["id"], "error": str(exc)})
        output["aggregate"] = aggregate(case_results)
        output["cases"] = case_results
        failed = any("error" in result for result in case_results)

    rendered = json.dumps(output, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

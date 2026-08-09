#!/usr/bin/env python3
"""Write a reproducible Markdown and JSON bundle for a normalized search result."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import sys
import unicodedata
from typing import Any, Dict, List, Tuple

import search_cases as sc


def plain_text(value: Any) -> str:
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value)
    return sc.clean_markup(html.unescape(str(value or ""))) or ""


def markdown_cell(value: Any) -> str:
    return plain_text(value).replace("|", r"\|").replace("\n", " ") or "—"


def format_score(value: Any, suffix: str) -> str:
    return f"{value}{suffix}" if value is not None else "—"


def slugify(value: str, maximum_length: int = 72) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    pieces: List[str] = []
    pending_separator = False
    for character in normalized:
        if character.isalnum():
            if pending_separator and pieces:
                pieces.append("-")
            pieces.append(character.casefold())
            pending_separator = False
        else:
            pending_separator = True
    slug = "".join(pieces).strip("-")[:maximum_length].rstrip("-")
    return slug or "case-search"


def timestamp_from_result(payload: Dict[str, Any]) -> str:
    value = str(payload.get("retrieved_at") or "")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        parsed = datetime.now(timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def create_bundle_directory(output_root: Path, name: str) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    candidate = output_root / name
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = output_root / f"{name}-{suffix}"
    candidate.mkdir()
    return candidate


def source_link(record: Dict[str, Any]) -> str:
    url = record.get("url") or record.get("full_text_url")
    return f"[打开来源]({url})" if url else "—"


def render_feature_table(record: Dict[str, Any]) -> List[str]:
    features = (record.get("feature_evidence") or {}).get("features", [])
    lines = [
        "| 维度 | 权重 | 必需 | 状态 | 当前证据 |",
        "|---|---:|---|---|---|",
    ]
    if not features:
        lines.append("| 未配置 | — | — | unknown | 未执行文档特征初排 |")
        return lines
    for feature in features:
        evidence = "; ".join(
            f"{item.get('kind')}: {item.get('term')} @ {item.get('field')}"
            for item in feature.get("evidence", [])
        )
        lines.append(
            "| {label} | {weight:g} | {required} | {status} | {evidence} |".format(
                label=markdown_cell(feature.get("label")),
                weight=float(feature.get("weight") or 0),
                required="是" if feature.get("required") else "否",
                status=markdown_cell(feature.get("status")),
                evidence=markdown_cell(evidence),
            )
        )
    return lines


def render_case(record: Dict[str, Any], rank: int) -> str:
    evidence = record.get("feature_evidence") or {}
    retrieval = record.get("retrieval_support") or {}
    reranker = record.get("reranker") or {}
    identifiers = ", ".join(
        f"{label}: {record[field]}"
        for field, label in (("doi", "DOI"), ("pmid", "PMID"), ("pmcid", "PMCID"))
        if record.get(field)
    )
    lines = [
        f"# {plain_text(record.get('title')) or 'Untitled candidate'}",
        "",
        "> 候选文献资料。除非下方患者级核验已经完成，否则不要把本文件计为一个独立患者病例。",
        "",
        "## 检索与来源信息",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        f"| 排序位置 | {rank} |",
        f"| 年份 | {markdown_cell(record.get('year'))} |",
        f"| 来源 | {markdown_cell(record.get('source_name'))} |",
        f"| 期刊 | {markdown_cell(record.get('journal'))} |",
        f"| 标识符 | {markdown_cell(identifiers)} |",
        f"| 链接 | {source_link(record)} |",
        f"| 来源质量 | {markdown_cell(record.get('source_quality'))} |",
        f"| 可访问范围 | {markdown_cell(record.get('access_scope'))} |",
        f"| 当前证据范围 | {markdown_cell(record.get('retrieved_evidence_scope'))} |",
        f"| 检索可信度 | {markdown_cell(retrieval.get('retrieval_confidence'))} |",
        f"| RRF 融合分 | {markdown_cell(retrieval.get('rrf_score'))} |",
        f"| 最佳来源内排名 | {markdown_cell(retrieval.get('best_source_rank'))} |",
        f"| Reranker 模型 | {markdown_cell(reranker.get('model'))} |",
        f"| Reranker 原始分 | {markdown_cell(reranker.get('score'))} |",
        f"| Reranker 前后排名 | {markdown_cell(reranker.get('pre_reranker_rank'))} → {markdown_cell(reranker.get('post_reranker_rank'))} |",
        f"| 命中来源 | {markdown_cell(record.get('found_via'))} |",
        f"| 命中查询 | {markdown_cell(record.get('matched_queries'))} |",
        "",
        "## 文档证据初排",
        "",
        f"- 特征匹配分：{format_score(evidence.get('evidence_match_percent'), '/100')}",
        f"- 必需特征覆盖率：{format_score(evidence.get('required_evidence_match_percent'), '%')}",
        f"- 明确冲突权重：{evidence.get('mismatched_weight', '—')}",
        "- 说明：这只是题名/摘要等当前可见文本的排序依据，不是诊断概率。",
        "",
        *render_feature_table(record),
        "",
        "## 当前检索到的摘要",
        "",
        plain_text(record.get("abstract")) or "当前连接器未返回摘要。",
        "",
        "## 患者级核验",
        "",
        "- 是否描述实际患者或病例系列：待核验",
        "- 独立患者数量：待核验",
        "- 是否可能与其他文献重复报道同一患者：待核验",
        "- 已核验相同点：待核验",
        "- 已核验重要差异：待核验",
        "- 未知事实：待核验",
        "- 纳入状态：待核验",
        "- 排除理由：待核验",
        "",
        "## Claim-to-source ledger",
        "",
        "待在阅读摘要或全文后补充具体主张、原文位置、证据范围和支持状态。",
        "",
    ]
    return "\n".join(lines)


def accounting_item(accounting: Dict[str, Any], section: str, key: str) -> str:
    value = (accounting.get(section) or {}).get(key) or {}
    items = ", ".join(value.get("items") or [])
    return f"{value.get('count', 0)}（{items or '无'}）"


def update_selection_accounting(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate presentation counts without limiting retrieval or eligibility."""

    accounting = payload.setdefault("result_accounting", {})
    funnel = accounting.setdefault("candidate_funnel", {})
    policy = payload.get("selection_policy") or {}
    detailed_limit = policy.get("max_detailed_verified_cases")
    if detailed_limit is not None and (
        isinstance(detailed_limit, bool)
        or not isinstance(detailed_limit, int)
        or detailed_limit < 1
    ):
        raise ValueError(
            "max_detailed_verified_cases must be a positive integer or null"
        )
    included = funnel.get("included_close_cases")
    if included is None:
        detailed = None
        retained = None
    else:
        if (
            isinstance(included, bool)
            or not isinstance(included, int)
            or included < 0
        ):
            raise ValueError("included_close_cases must be a non-negative integer or null")
        detailed = (
            included
            if detailed_limit is None
            else min(included, int(detailed_limit))
        )
        retained = included - detailed
    funnel["detailed_included_cases"] = detailed
    funnel["additional_included_cases_retained"] = retained
    selection = {
        "limit_applies_to": "patient_level_verified_close_cases",
        "retrieval_candidate_limit": None,
        "max_detailed_verified_cases": detailed_limit,
        "eligible_verified_cases": included,
        "detailed_cases_selected": detailed,
        "additional_eligible_cases_retained": retained,
        "retain_all_eligible_cases": True,
        "overflow_destination": policy.get(
            "overflow_destination", "supplement_and_machine_results"
        ),
        "ranking_dimensions": policy.get("ranking_dimensions") or [],
    }
    accounting["selection_reporting"] = selection
    return selection


def render_overall_report(
    payload: Dict[str, Any], case_files: List[Tuple[Dict[str, Any], str]]
) -> str:
    accounting = payload.get("result_accounting") or {}
    funnel = accounting.get("candidate_funnel") or {}
    selection = accounting.get("selection_reporting") or {}
    dimensions = (accounting.get("dimension_summary") or {}).get("dimensions", [])
    coverage = payload.get("coverage") or []
    reranker = payload.get("reranker") or {}
    lines = [
        "# 总体搜索结果",
        "",
        f"- 检索 ID：{plain_text(payload.get('case_id')) or '未提供'}",
        f"- 检索时间：{plain_text(payload.get('retrieved_at')) or '未知'}",
        f"- 模式：{plain_text(payload.get('mode')) or '未知'}",
        f"- Reranker：{markdown_cell(reranker.get('status'))}；模型 {markdown_cell(reranker.get('model'))}；评分候选 {markdown_cell(reranker.get('candidates_scored'))}。",
        "- Reranker 分数是候选前缀内的原始排序信号，不是诊断概率或临床相似度概率。",
        "- 统计范围：当前文件的自动统计默认覆盖 live API 阶段；其他实际执行路径应在最终核验时补充。",
        "",
        "## 路径统计",
        "",
        f"- 查询家族：支持 {accounting_item(accounting, 'query_families', 'supported')}；计划 {accounting_item(accounting, 'query_families', 'planned')}；尝试 {accounting_item(accounting, 'query_families', 'attempted')}；全部计划来源成功 {accounting_item(accounting, 'query_families', 'succeeded_on_all_planned_sources')}。",
        f"- 来源路径：支持 {accounting_item(accounting, 'source_routes', 'supported')}；计划 {accounting_item(accounting, 'source_routes', 'planned')}；尝试 {accounting_item(accounting, 'source_routes', 'attempted')}；本次可用 {accounting_item(accounting, 'source_routes', 'usable_this_run')}。",
        f"- 查询×来源执行：计划 {((accounting.get('query_source_executions') or {}).get('planned', 0))}，尝试 {((accounting.get('query_source_executions') or {}).get('attempted', 0))}，成功 {((accounting.get('query_source_executions') or {}).get('succeeded', 0))}，失败 {((accounting.get('query_source_executions') or {}).get('failed', 0))}。",
        "",
        "## 候选漏斗",
        "",
        "| 阶段 | 数量 | 解释 |",
        "|---|---:|---|",
        f"| 数据库报告命中合计 | {funnel.get('provider_reported_hits_sum', '—')} | 跨查询和来源重叠，不是病例数 |",
        f"| 实际返回记录 | {funnel.get('returned_records_before_deduplication', '—')} | 文献或索引记录 |",
        f"| 删除重复记录出现 | {funnel.get('duplicate_record_occurrences_removed', '—')} | 同一文献的重复命中 |",
        f"| 去重后候选文献 | {funnel.get('unique_candidates_after_deduplication', '—')} | 仍不是独立患者数 |",
        f"| 完成文档初排 | {funnel.get('document_triaged_candidates', '—')} | 基于配置维度和当前文本 |",
        f"| 已排序候选 | {funnel.get('ranked_candidates', '—')} | 等待逐篇核验 |",
        f"| 核验后独立患者病例 | {funnel.get('clinically_verified_patient_cases') if funnel.get('clinically_verified_patient_cases') is not None else '待核验'} | 完成患者级去重后填写 |",
        f"| 最终纳入相似病例 | {funnel.get('included_close_cases') if funnel.get('included_close_cases') is not None else '待核验'} | 完成临床维度比较后填写 |",
        f"| 详细展示相似病例 | {funnel.get('detailed_included_cases') if funnel.get('detailed_included_cases') is not None else '待核验'} | 展示预算只在患者级核验后应用 |",
        f"| 补充保留相似病例 | {funnel.get('additional_included_cases_retained') if funnel.get('additional_included_cases_retained') is not None else '待核验'} | 合格但未进入详细展示的病例，不丢弃 |",
        f"| 近似病例 | {funnel.get('near_misses') if funnel.get('near_misses') is not None else '待核验'} | 有相关性但存在重要差异 |",
        f"| 核验后排除 | {funnel.get('excluded_after_verification') if funnel.get('excluded_after_verification') is not None else '待核验'} | 在病例资料页记录理由 |",
        "",
        "## 筛选与详细展示策略",
        "",
        "- 检索、文档初排和患者级核验不按病例数量截断；按已声明的饱和、访问、时间、API 或预算停止条件决定何时结束。",
        "- 只有患者级核验、患者去重并满足本病例纳入维度的结果，才计入相似病例。",
        "- 详细展示上限：{limit}；该上限不影响相似病例总数，也不删除超出部分。".format(
            limit=(
                selection.get("max_detailed_verified_cases")
                if selection.get("max_detailed_verified_cases") is not None
                else "未设置"
            )
        ),
        "- 超出详细展示预算的合格病例：保留在补充清单和机器结果中。",
        "- 详细展示排序维度：{dimensions}。".format(
            dimensions=markdown_cell(selection.get("ranking_dimensions"))
            if selection.get("ranking_dimensions")
            else "由病例计划和完成后的临床核验决定"
        ),
        "",
        "## 维度汇总",
        "",
        "| 优先级 | 维度 | 权重 | 必需 | 匹配 | 冲突 | 同时支持与冲突 | 未知 |",
        "|---:|---|---:|---|---:|---:|---:|---:|",
    ]
    if dimensions:
        for dimension in dimensions:
            counts = dimension.get("candidate_status_counts") or {}
            lines.append(
                "| {priority} | {label} | {weight:g} | {required} | {matched} | {mismatched} | {conflicting} | {unknown} |".format(
                    priority=dimension.get("priority_order", "—"),
                    label=markdown_cell(dimension.get("label")),
                    weight=float(dimension.get("weight") or 0),
                    required="是" if dimension.get("required") else "否",
                    matched=counts.get("matched", 0),
                    mismatched=counts.get("mismatched", 0),
                    conflicting=counts.get("conflicting", 0),
                    unknown=counts.get("unknown", 0),
                )
            )
    else:
        lines.append("| — | 未配置 | — | — | — | — | — | — |")
    lines.extend(
        [
            "",
            "## 排序后的候选文献",
            "",
            "| 排名 | 候选 | 年份 | 特征匹配分 | 必需特征覆盖 | Reranker | RRF | 来源质量 | 当前证据范围 |",
            "|---:|---|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for rank, (record, relative_path) in enumerate(case_files, start=1):
        evidence = record.get("feature_evidence") or {}
        lines.append(
            "| {rank} | [{title}]({path}) | {year} | {score} | {required} | {reranker} | {rrf} | {quality} | {scope} |".format(
                rank=rank,
                title=markdown_cell(record.get("title")),
                path=relative_path,
                year=markdown_cell(record.get("year")),
                score=format_score(evidence.get("evidence_match_percent"), "/100"),
                required=format_score(
                    evidence.get("required_evidence_match_percent"), "%"
                ),
                reranker=markdown_cell((record.get("reranker") or {}).get("score")),
                rrf=markdown_cell(
                    (record.get("retrieval_support") or {}).get("rrf_score")
                ),
                quality=markdown_cell(record.get("source_quality")),
                scope=markdown_cell(record.get("retrieved_evidence_scope")),
            )
        )
    lines.extend(
        [
            "",
            "## 查询覆盖",
            "",
            "| 查询 | 意图 | 来源 | 状态 | 命中 | 返回 | 新增去重候选 | 限制 |",
            "|---|---|---|---|---:|---:|---:|---|",
        ]
    )
    for item in coverage:
        lines.append(
            "| {query} | {intent} | {source} | {status} | {hits} | {returned} | {new} | {limitation} |".format(
                query=markdown_cell(item.get("query_id")),
                intent=markdown_cell(item.get("intent")),
                source=markdown_cell(item.get("source_name")),
                status=markdown_cell(item.get("status")),
                hits=markdown_cell(item.get("total_hits")),
                returned=markdown_cell(item.get("returned")),
                new=markdown_cell(item.get("new_unique_candidates")),
                limitation=markdown_cell(item.get("limitation")),
            )
        )
    lines.extend(
        [
            "",
            "## 待完成的临床核验",
            "",
            "- 逐篇确认是否为实际患者病例或病例系列。",
            "- 检查多篇文献是否重复报道同一患者。",
            "- 用全文或摘要逐项记录匹配、差异和未知事实。",
            "- 填写最终纳入、近似、排除数量及理由。",
            "- 完成 claim-to-source ledger、停止条件和盲区说明。",
            "",
            "## 安全说明",
            "",
            "病例相似性仅用于文献回顾和提出假设，不能确定当前患者的诊断、因果关系、治疗适用性或预后。",
            "",
        ]
    )
    return "\n".join(lines)


def write_bundle(
    payload: Dict[str, Any], output_root: str, label: str | None = None
) -> Dict[str, Any]:
    requested_label = sc.compact(label) or sc.compact(payload.get("case_id")) or "case-search"
    sensitive = sc.detect_sensitive_query(requested_label)
    if sensitive:
        raise ValueError(
            "output label may contain sensitive identifiers: " + ", ".join(sensitive)
        )
    directory_name = f"{slugify(requested_label)}_{timestamp_from_result(payload)}"
    update_selection_accounting(payload)
    bundle_directory = create_bundle_directory(
        Path(output_root).expanduser(), directory_name
    )
    case_directory = bundle_directory / "cases"
    case_directory.mkdir()
    case_files: List[Tuple[Dict[str, Any], str]] = []
    relative_case_paths: List[str] = []
    for rank, record in enumerate(payload.get("records") or [], start=1):
        filename = f"{rank:03d}_{slugify(plain_text(record.get('title')), 88)}.md"
        relative_path = f"cases/{filename}"
        (case_directory / filename).write_text(
            render_case(record, rank), encoding="utf-8"
        )
        case_files.append((record, relative_path))
        relative_case_paths.append(relative_path)
    metadata = {
        "directory": str(bundle_directory.resolve()),
        "report": "search-report.md",
        "machine_results": "search-results.json",
        "case_directory": "cases",
        "case_file_semantics": (
            "candidate_publication_dossiers_pending_patient_level_verification"
        ),
        "candidate_dossier_count": len(case_files),
        "case_file_count": len(case_files),
        "case_files": relative_case_paths,
    }
    payload["output_bundle"] = metadata
    (bundle_directory / "search-report.md").write_text(
        render_overall_report(payload, case_files), encoding="utf-8"
    )
    (bundle_directory / "search-results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Normalized search-result JSON")
    parser.add_argument("--output-root", default="output")
    parser.add_argument("--label")
    args = parser.parse_args()
    with Path(args.input).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    metadata = write_bundle(payload, args.output_root, args.label)
    json.dump(metadata, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

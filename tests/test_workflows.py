from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_search_plan as rsp  # noqa: E402
import write_search_bundle as wsb  # noqa: E402


class WorkflowTests(unittest.TestCase):
    def run_json(self, *args: str) -> dict:
        completed = subprocess.run(
            [sys.executable, *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_template_is_fully_valid(self) -> None:
        plan = rsp.load_plan(str(ROOT / "references" / "search-plan-template.json"))
        queries = rsp.validate_plan(plan, "comprehensive")
        features = rsp.validate_candidate_features(plan)
        selection = rsp.validate_selection_policy(plan)
        rsp.validate_supplemental_queries(plan)
        self.assertEqual(len(queries), 5)
        self.assertGreater(len(features), 1)
        self.assertTrue(
            all(q["query_representation"] == "concept_groups" for q in queries)
        )
        self.assertTrue(
            any(
                q["intent"] == "broad_synonyms" and not q["case_filter"]
                for q in queries
            )
        )
        self.assertEqual(selection["max_detailed_verified_cases"], 50)
        self.assertTrue(selection["retain_all_eligible_cases"])

    def test_selection_policy_limits_detail_only_after_verification(self) -> None:
        policy = rsp.validate_selection_policy(
            {
                "selection_policy": {
                    "max_detailed_verified_cases": 50,
                    "ranking_dimensions": [
                        "case-defined clinical similarity",
                        "evidence completeness",
                    ],
                }
            }
        )
        payload = {
            "selection_policy": policy,
            "result_accounting": {
                "candidate_funnel": {
                    "unique_candidates_after_deduplication": 240,
                    "ranked_candidates": 240,
                    "clinically_verified_patient_cases": 82,
                    "included_close_cases": 67,
                }
            },
        }
        selection = wsb.update_selection_accounting(payload)
        funnel = payload["result_accounting"]["candidate_funnel"]
        self.assertEqual(funnel["ranked_candidates"], 240)
        self.assertEqual(selection["eligible_verified_cases"], 67)
        self.assertEqual(selection["detailed_cases_selected"], 50)
        self.assertEqual(selection["additional_eligible_cases_retained"], 17)
        self.assertIsNone(selection["retrieval_candidate_limit"])
        report = wsb.render_overall_report(payload, [])
        self.assertIn("| 详细展示相似病例 | 50 |", report)
        self.assertIn("| 补充保留相似病例 | 17 |", report)
        self.assertIn("检索、文档初排和患者级核验不按病例数量截断", report)

    def test_selection_policy_rejects_invalid_limits(self) -> None:
        for value in (0, -1, True, "50"):
            with self.subTest(value=value):
                with self.assertRaises(rsp.PlanError):
                    rsp.validate_selection_policy(
                        {
                            "selection_policy": {
                                "max_detailed_verified_cases": value
                            }
                        }
                    )
        with self.assertRaises(rsp.PlanError):
            rsp.validate_selection_policy({"selection_policy": []})

    def test_concept_groups_compile_synonyms_with_explicit_precedence(self) -> None:
        plan = {
            "api_queries": [
                {
                    "id": "q1",
                    "intent": "high_precision",
                    "concept_groups": [
                        ["exposure alpha", "exposure beta"],
                        ["finding gamma"],
                    ],
                }
            ]
        }
        query = rsp.validate_plan(plan, "quick")[0]
        self.assertEqual(
            query["text"],
            "((exposure alpha) OR (exposure beta)) AND ((finding gamma))",
        )
        self.assertEqual(
            query["concept_groups"][0], ["exposure alpha", "exposure beta"]
        )
        self.assertEqual(query["query_representation"], "concept_groups")

    def test_legacy_text_query_remains_supported(self) -> None:
        plan = {
            "api_queries": [
                {"id": "q1", "intent": "high_precision", "text": "finding alpha"}
            ]
        }
        query = rsp.validate_plan(plan, "quick")[0]
        self.assertEqual(query["text"], "finding alpha")
        self.assertEqual(query["query_representation"], "legacy_text")

    def test_feature_evidence_is_plan_defined_and_reranks_documents(self) -> None:
        features = rsp.validate_candidate_features(
            {
                "candidate_features": [
                    {
                        "id": "exposure",
                        "terms": ["exposure alpha"],
                        "weight": 3,
                        "required": True,
                    },
                    {"id": "finding", "terms": ["finding beta"], "weight": 1},
                ]
            }
        )
        close = rsp.sc.base_record("pubmed", "now")
        close.update(
            title="Exposure alpha with finding beta: a case report",
            pmid="1",
            publication_types=["Case Reports"],
            matched_queries=["q1"],
            query_intents=["high_precision"],
        )
        broad = rsp.sc.base_record("pubmed", "now")
        broad.update(
            title="Finding beta from another exposure: a case report",
            pmid="2",
            publication_types=["Case Reports"],
            matched_queries=["q1", "q2"],
            query_intents=["high_precision", "presentation"],
        )
        for record in (close, broad):
            rsp.annotate_candidate(record, features)
        ranked = sorted(
            [broad, close],
            key=lambda record: rsp.candidate_sort_key(record, True),
            reverse=True,
        )
        self.assertEqual(ranked[0]["pmid"], "1")
        self.assertEqual(close["feature_evidence"]["evidence_match_percent"], 100.0)
        self.assertEqual(
            broad["feature_evidence"]["features"][0]["status"], "unknown"
        )

    def test_feature_evidence_requires_explicit_mismatch_terms(self) -> None:
        features = rsp.validate_candidate_features(
            {
                "candidate_features": [
                    {
                        "id": "population",
                        "terms": ["adult"],
                        "mismatch_terms": ["child"],
                    }
                ]
            }
        )
        mismatch = rsp.sc.base_record("pubmed", "now")
        mismatch["title"] = "A child with finding beta"
        unknown = rsp.sc.base_record("pubmed", "now")
        unknown["title"] = "A patient with finding beta"
        for record in (mismatch, unknown):
            rsp.annotate_candidate(record, features)
        self.assertEqual(
            mismatch["feature_evidence"]["features"][0]["status"], "mismatched"
        )
        self.assertEqual(
            unknown["feature_evidence"]["features"][0]["status"], "unknown"
        )
        self.assertFalse(rsp.contains_evidence_term("female patient", "male"))

    def test_result_accounting_separates_routes_records_and_verified_cases(self) -> None:
        queries = [
            {
                "intent": "high_precision",
                "sources": ["pubmed", "europepmc"],
            },
            {"intent": "presentation", "sources": ["pubmed"]},
        ]
        coverage = [
            {
                "intent": "high_precision",
                "source_key": "pubmed",
                "status": "success",
                "total_hits": 10,
                "returned": 3,
            },
            {
                "intent": "high_precision",
                "source_key": "europepmc",
                "status": "failed",
                "total_hits": None,
                "returned": 0,
            },
            {
                "intent": "presentation",
                "source_key": "pubmed",
                "status": "success",
                "total_hits": 5,
                "returned": 2,
            },
        ]
        features = rsp.validate_candidate_features(
            {"candidate_features": [{"id": "finding", "terms": ["finding alpha"]}]}
        )
        records = [
            rsp.sc.base_record("pubmed", "now"),
            rsp.sc.base_record("europepmc", "now"),
        ]
        records[0]["title"] = "Finding alpha in a patient"
        records[1]["title"] = "Another presentation"
        for record in records:
            rsp.annotate_candidate(record, features)
        accounting = rsp.build_result_accounting(
            queries, coverage, records, features
        )
        self.assertEqual(accounting["query_families"]["planned"]["count"], 2)
        self.assertEqual(
            accounting["query_families"]["succeeded_on_all_planned_sources"][
                "items"
            ],
            ["presentation"],
        )
        self.assertEqual(accounting["source_routes"]["usable_this_run"]["count"], 1)
        self.assertEqual(accounting["query_source_executions"]["failed"], 1)
        funnel = accounting["candidate_funnel"]
        self.assertEqual(funnel["provider_reported_hits_sum"], 15)
        self.assertEqual(funnel["returned_records_before_deduplication"], 5)
        self.assertEqual(funnel["unique_candidates_after_deduplication"], 2)
        self.assertIsNone(funnel["clinically_verified_patient_cases"])
        dimension = accounting["dimension_summary"]["dimensions"][0]
        self.assertEqual(dimension["candidate_status_counts"]["matched"], 1)
        self.assertEqual(dimension["candidate_status_counts"]["unknown"], 1)

    def test_output_bundle_contains_overall_report_json_and_case_files(self) -> None:
        features = rsp.validate_candidate_features(
            {"candidate_features": [{"id": "finding", "terms": ["finding alpha"]}]}
        )
        record = rsp.sc.base_record("pubmed", "2026-08-04T06:16:23+00:00")
        record.update(
            title="Finding alpha in a candidate case",
            abstract="A de-identified abstract.",
            pmid="1",
            publication_types=["Case Reports"],
            matched_queries=["q1"],
            query_intents=["high_precision"],
        )
        rsp.annotate_candidate(record, features)
        queries = [
            {
                "id": "q1",
                "intent": "high_precision",
                "sources": ["pubmed"],
            }
        ]
        coverage = [
            {
                "query_id": "q1",
                "intent": "high_precision",
                "source_key": "pubmed",
                "source_name": "PubMed",
                "status": "success",
                "total_hits": 1,
                "returned": 1,
                "new_unique_candidates": 1,
                "limitation": None,
            }
        ]
        payload = {
            "case_id": "deidentified-example",
            "retrieved_at": "2026-08-04T06:16:23+00:00",
            "mode": "quick",
            "coverage": coverage,
            "records": [record],
            "result_accounting": rsp.build_result_accounting(
                queries, coverage, [record], features
            ),
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            metadata = wsb.write_bundle(
                payload, temporary_directory, "finding alpha"
            )
            bundle = Path(metadata["directory"])
            self.assertTrue(bundle.name.startswith("finding-alpha_20260804T061623Z"))
            self.assertTrue((bundle / "search-report.md").is_file())
            self.assertTrue((bundle / "search-results.json").is_file())
            case_files = list((bundle / "cases").glob("*.md"))
            self.assertEqual(len(case_files), 1)
            self.assertIn(
                "候选漏斗", (bundle / "search-report.md").read_text(encoding="utf-8")
            )
            self.assertIn("患者级核验", case_files[0].read_text(encoding="utf-8"))
            saved = json.loads(
                (bundle / "search-results.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["output_bundle"]["case_file_count"], 1)
            self.assertEqual(saved["output_bundle"]["candidate_dossier_count"], 1)
            self.assertEqual(
                saved["output_bundle"]["case_file_semantics"],
                "candidate_publication_dossiers_pending_patient_level_verification",
            )

    def test_protocol_audit_requires_successful_unfiltered_broad_query(self) -> None:
        plan = {"requirements": {}}
        queries = [
            {"intent": intent, "language": "en"} for intent in sorted(rsp.CORE_INTENTS)
        ]
        coverage = [
            {
                "intent": intent,
                "source_key": source,
                "status": "success",
                "case_filter": True,
                "required": True,
            }
            for intent in rsp.CORE_INTENTS
            for source in ("pubmed", "europepmc")
        ]
        audit = rsp.protocol_audit(plan, queries, coverage, "comprehensive")
        self.assertIn(
            "no broad_synonyms query successfully ran with case_filter=false",
            audit["missing_requirements"],
        )

    def test_comprehensive_dedup_keeps_conflicting_stable_ids_separate(self) -> None:
        first = rsp.sc.base_record("pubmed", "now")
        first.update(
            doi="10.1128/aac.02130-17",
            pmid="29530850",
            title="Posaconazole",
            year=2018,
            authors=["Kuriakose K"],
        )
        second = rsp.sc.base_record("europepmc", "now")
        second.update(
            doi="10.1002/kjm2.12325",
            pmid="33231362",
            title="Posaconazole",
            year=2021,
            authors=["Tantiprawan J"],
        )
        self.assertEqual(len(rsp.merge_with_aliases([first, second])), 2)

    def test_browser_plan_is_generated_without_network(self) -> None:
        payload = self.run_json(
            "scripts/build_browser_searches.py",
            "--query",
            "低钾 高血压",
            "--groups",
            "chinese,wechat",
        )
        self.assertFalse(payload["live_search"])
        self.assertGreater(len(payload["searches"]), 1)

    def test_tikhub_dry_run_includes_retry_cost_ceiling(self) -> None:
        payload = self.run_json(
            "scripts/search_wechat_tikhub.py",
            "--dry-run",
            "--max-calls",
            "6",
            "--retries",
            "1",
            "collect",
            "--query",
            "低钾 高血压 病例",
            "--pages",
            "1",
            "--details",
            "2",
        )
        self.assertEqual(payload["maximum_logical_requests"], 3)
        self.assertEqual(payload["maximum_http_calls"], 6)
        self.assertEqual(payload["estimated_maximum_cost_usd"], 0.06)

    def test_standalone_project_validator(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/validate_project.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from copy import deepcopy
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_search_plan as rsp  # noqa: E402
import benchmark_case_studies as bcs  # noqa: E402
import rerank_candidates as rrc  # noqa: E402
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

    def test_conflicting_feature_does_not_count_as_required_match(self) -> None:
        features = rsp.validate_candidate_features(
            {
                "candidate_features": [
                    {
                        "id": "disease",
                        "terms": ["melanoma"],
                        "mismatch_terms": ["non-small cell lung cancer"],
                        "weight": 3,
                        "required": True,
                    }
                ]
            }
        )
        record = rsp.sc.base_record("pubmed", "now")
        record.update(
            title="A non-small cell lung cancer case report",
            abstract="BRAF inhibitors are also used in melanoma.",
        )
        rsp.annotate_candidate(record, features)
        evidence = record["feature_evidence"]
        self.assertEqual(evidence["features"][0]["status"], "conflicting")
        self.assertEqual(evidence["required_evidence_match_percent"], 0.0)
        self.assertEqual(evidence["matched_weight"], 0.0)
        self.assertEqual(evidence["mismatched_weight"], 3.0)

    def test_explicit_mismatch_and_case_signal_precede_title_bonus(self) -> None:
        features = rsp.validate_candidate_features(
            {
                "candidate_features": [
                    {
                        "id": "stones",
                        "terms": ["cholelithiasis"],
                        "weight": 3,
                        "required": True,
                    },
                    {
                        "id": "population",
                        "terms": ["older adult"],
                        "mismatch_terms": ["cat"],
                        "weight": 2,
                    },
                ]
            }
        )
        human_case = rsp.sc.base_record("pubmed", "now")
        human_case.update(
            pmid="1",
            title="Cholelithiasis: a case report",
            publication_types=["Case Reports"],
        )
        animal_case = rsp.sc.base_record("pubmed", "now")
        animal_case.update(
            pmid="2",
            title="Cholelithiasis in a cat: a case report",
            publication_types=["Case Reports"],
        )
        review = rsp.sc.base_record("pubmed", "now")
        review.update(pmid="3", title="Cholelithiasis: a review")
        for record in (human_case, animal_case, review):
            rsp.annotate_candidate(record, features)
        human_case["reranker"] = {"score": 0.1}
        animal_case["reranker"] = {"score": 100.0}
        review["reranker"] = {"score": 50.0}
        ranked = sorted(
            [review, animal_case, human_case],
            key=lambda record: rsp.candidate_sort_key(record, True, True),
            reverse=True,
        )
        self.assertEqual([record["pmid"] for record in ranked], ["1", "3", "2"])

    def test_medcpt_reranker_query_scoring_and_provenance(self) -> None:
        query = rrc.build_case_query(
            {
                "case_fingerprint": {
                    "age_band": "child",
                    "main_presentation": ["thrombocytopenia", "hearing loss"],
                    "labs_imaging_pathology": ["proteinuria"],
                }
            }
        )
        self.assertEqual(
            query,
            "Age: child. Presentation: thrombocytopenia, hearing loss. "
            "Tests and pathology: proteinuria",
        )
        first = rsp.sc.base_record("pubmed", "now")
        first.update(pmid="1", title="First case", abstract="Less relevant")
        second = rsp.sc.base_record("pubmed", "now")
        second.update(pmid="2", title="Second case", abstract="More relevant")
        for record in (first, second):
            rsp.annotate_candidate(record)

        def fake_scorer(query_text, documents, **kwargs):
            self.assertEqual(query_text, query)
            self.assertEqual(len(documents), 2)
            self.assertIn("Title: First case", documents[0])
            return [0.25, 2.5], {
                "backend": "fake_sequence_classifier",
                "model": kwargs["model_name"],
                "requested_revision": kwargs["revision"],
                "resolved_revision": "commit-abc",
                "score_semantics": "test_logit",
            }

        summary = rrc.rerank_records(
            [first, second],
            query,
            top_k=2,
            model_name="test/medcpt",
            revision="revision-1",
            scorer=fake_scorer,
        )
        self.assertEqual(summary["status"], "applied")
        self.assertEqual(summary["resolved_revision"], "commit-abc")
        self.assertEqual(second["reranker"]["pre_reranker_rank"], 2)
        ranked = sorted(
            [first, second],
            key=lambda record: rsp.candidate_sort_key(record, False, True),
            reverse=True,
        )
        self.assertEqual(ranked[0]["pmid"], "2")

    def test_reranker_rejects_invalid_scores(self) -> None:
        record = rsp.sc.base_record("pubmed", "now")
        record.update(pmid="1", title="Candidate")

        def invalid_scorer(*args, **kwargs):
            return [float("nan")], {"resolved_revision": "test"}

        with self.assertRaisesRegex(rrc.RerankerError, "not finite"):
            rrc.rerank_records(
                [record], "de-identified query", top_k=1, scorer=invalid_scorer
            )

    def test_siliconflow_reranker_parses_indexed_results_without_persisting_key(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(
                    {
                        "results": [
                            {"index": 1, "relevance_score": 2.0},
                            {"index": 0, "relevance_score": 0.5},
                        ]
                    }
                ).encode("utf-8")

        def fake_urlopen(request, timeout):
            self.assertEqual(request.full_url, rrc.DEFAULT_SILICONFLOW_ENDPOINT)
            self.assertEqual(timeout, 90)
            body = json.loads(request.data.decode("utf-8"))
            self.assertEqual(body["model"], rrc.DEFAULT_SILICONFLOW_MODEL)
            self.assertEqual(body["top_n"], 2)
            self.assertEqual(body["return_documents"], False)
            self.assertIn("Bearer unit-secret", str(request.headers))
            return FakeResponse()

        with mock.patch.dict(os.environ, {"SILICONFLOW_API_KEY": "unit-secret"}):
            with mock.patch.object(rrc.urlrequest, "urlopen", fake_urlopen):
                scores, metadata = rrc.score_documents_siliconflow(
                    "case query", ["doc one", "doc two"]
                )
        self.assertEqual(scores, [0.5, 2.0])
        self.assertEqual(metadata["backend"], "siliconflow_rerank_api")
        self.assertNotIn("unit-secret", json.dumps(metadata))

    def test_siliconflow_reranker_requires_key_and_https(self) -> None:
        with mock.patch.object(rrc, "env_value", return_value=None):
            with self.assertRaisesRegex(rrc.RerankerError, "SILICONFLOW_API_KEY"):
                rrc.score_documents_siliconflow("query", ["document"])
        with mock.patch.dict(os.environ, {"SILICONFLOW_API_KEY": "unit-secret"}):
            with self.assertRaisesRegex(rrc.RerankerError, "HTTPS"):
                rrc.score_documents_siliconflow(
                    "query", ["document"], endpoint="http://localhost/rerank"
                )

    def test_feature_evidence_prefers_title_over_abstract_synonym(self) -> None:
        features = rsp.validate_candidate_features(
            {
                "candidate_features": [
                    {
                        "id": "hearing",
                        "terms": ["deafness", "hearing impairment"],
                        "weight": 3,
                    }
                ]
            }
        )
        record = rsp.sc.base_record("pubmed", "now")
        record.update(
            title="Familial hearing impairment with nephropathy",
            abstract="The patient was evaluated for deafness.",
        )
        rsp.annotate_candidate(record, features)
        evidence = record["feature_evidence"]
        self.assertEqual(
            evidence["features"][0]["evidence"],
            [{"kind": "match", "term": "hearing impairment", "field": "title"}],
        )
        self.assertEqual(evidence["title_matched_weight"], 3)

    def test_provider_ranks_survive_merge_and_drive_rrf(self) -> None:
        query_one = {"id": "q1", "intent": "high_precision"}
        query_two = {"id": "q2", "intent": "presentation"}
        pubmed = rsp.sc.base_record("pubmed", "now")
        pubmed.update(pmid="123", title="A shared candidate")
        europepmc = rsp.sc.base_record("europepmc", "now")
        europepmc.update(pmid="123", title="A shared candidate")
        merged = rsp.merge_with_aliases(
            [
                rsp.tag_record(pubmed, query_one, "pubmed", 2),
                rsp.tag_record(europepmc, query_two, "europepmc", 7),
            ]
        )
        self.assertEqual(len(merged), 1)
        occurrences = merged[0]["source_occurrences"]
        self.assertEqual(
            {(item["source_key"], item["query_id"], item["rank"]) for item in occurrences},
            {("pubmed", "q1", 2), ("europepmc", "q2", 7)},
        )
        rsp.annotate_candidate(merged[0])
        support = merged[0]["retrieval_support"]
        self.assertEqual(support["ranked_occurrence_count"], 2)
        self.assertEqual(support["best_source_rank"], 2)
        self.assertAlmostEqual(
            support["rrf_score"],
            1 / (rsp.RRF_K + 2) + 1 / (rsp.RRF_K + 7),
            places=8,
        )

    def test_rrf_is_primary_retrieval_sort_signal(self) -> None:
        multi_route = rsp.sc.base_record("openalex", "now")
        multi_route.update(
            doi="10.1000/multi",
            title="Multi-route candidate",
            matched_queries=["q1", "q2"],
            query_intents=["presentation", "broad_synonyms"],
            source_occurrences=[
                {"source_key": "openalex", "query_id": "q1", "rank": 3},
                {"source_key": "openalex", "query_id": "q2", "rank": 4},
            ],
        )
        single_route = rsp.sc.base_record("pubmed", "now")
        single_route.update(
            pmid="456",
            title="Single-route case report",
            publication_types=["Case Reports"],
            matched_queries=["q1"],
            query_intents=["high_precision"],
            source_occurrences=[
                {"source_key": "pubmed", "query_id": "q1", "rank": 1}
            ],
        )
        for record in (multi_route, single_route):
            rsp.annotate_candidate(record)
        ranked = sorted(
            [single_route, multi_route],
            key=lambda record: rsp.candidate_sort_key(record, False),
            reverse=True,
        )
        self.assertEqual(ranked[0]["doi"], "10.1000/multi")

    def test_pmc_patients_fixture_and_overlap_metric_contract(self) -> None:
        benchmark = bcs.load_benchmark(
            ROOT / "benchmarks" / "pmc-patients-case-studies.json"
        )
        self.assertEqual(len(benchmark["cases"]), 3)
        self.assertIn("not exhaustive relevance judgments", benchmark["caveat"])
        expected_executions = {
            "pmc-case-1-diagnosis": 10,
            "pmc-case-2-test": 12,
            "pmc-case-3-treatment": 12,
        }
        for case in benchmark["cases"]:
            self.assertEqual(len(case["reference_top5"]), 5)
            validation = bcs.validate_plan(bcs.build_plan(case), 12)
            self.assertEqual(
                validation["query_source_executions"], expected_executions[case["id"]]
            )
        summary = bcs.overlap_summary(
            ["1", "2", "3", "4", "5"], {"1": 2, "3": 17}
        )
        self.assertEqual(summary["at_5"]["count"], 1)
        self.assertEqual(summary["at_20"]["count"], 2)
        self.assertNotIn("recall", json.dumps(summary).casefold())

        invalid = deepcopy(benchmark)
        invalid["cases"][0]["reference_top5"][0] = "not an object"
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid.json"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(
                bcs.BenchmarkError, "reference_top5 items must be objects"
            ):
                bcs.load_benchmark(path)

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
        record["reranker"] = {
            "status": "scored",
            "model": "test/medcpt",
            "score": 1.25,
            "pre_reranker_rank": 2,
            "post_reranker_rank": 1,
        }
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
            "reranker": {
                "status": "applied",
                "model": "test/medcpt",
                "candidates_scored": 1,
            },
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
            self.assertIn(
                "Reranker 原始分",
                case_files[0].read_text(encoding="utf-8"),
            )
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

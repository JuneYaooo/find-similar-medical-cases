from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_search_plan as rsp  # noqa: E402


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
        rsp.validate_supplemental_queries(plan)
        self.assertEqual(len(queries), 5)
        self.assertTrue(
            any(
                q["intent"] == "broad_synonyms" and not q["case_filter"]
                for q in queries
            )
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

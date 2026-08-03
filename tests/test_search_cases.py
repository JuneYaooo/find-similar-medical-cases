from __future__ import annotations

import json
import sys
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import search_cases as sc  # noqa: E402


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class SearchCasesTests(unittest.TestCase):
    def test_sensitive_query_detection(self) -> None:
        labels = sc.detect_sensitive_query("姓名：张三 家庭住址：北京市 2026-08-04")
        self.assertIn("record or identity label", labels)
        self.assertIn("address label", labels)
        self.assertIn("exact calendar date", labels)

    def test_source_quality_only_promotes_actual_case_reports(self) -> None:
        self.assertEqual(
            sc.source_quality_for_publication_types(["Journal Article", "Review"]),
            "bibliographic_record_only",
        )
        self.assertEqual(
            sc.source_quality_for_publication_types(
                ["Case Reports", "Journal Article"]
            ),
            "peer_reviewed_original_case",
        )

    @mock.patch.object(sc, "request_json")
    def test_europe_pmc_broad_results_are_not_mislabeled(
        self, request_json: mock.Mock
    ) -> None:
        request_json.return_value = {
            "hitCount": 1,
            "resultList": {
                "result": [
                    {
                        "id": "1",
                        "title": "A systematic review",
                        "pubTypeList": {"pubType": ["Review", "Journal Article"]},
                    }
                ]
            },
        }
        _, _, records = sc.europepmc_search(
            "hypertension", 1, 10, "now", case_filter=False
        )
        self.assertEqual(records[0]["source_quality"], "bibliographic_record_only")

    @mock.patch.object(sc, "request_json")
    def test_crossref_connector_normalizes_metadata(
        self, request_json: mock.Mock
    ) -> None:
        request_json.return_value = {
            "message": {
                "total-results": 1,
                "items": [
                    {
                        "DOI": "https://doi.org/10.1000/ABC",
                        "title": ["A case"],
                        "abstract": "<jats:p>Supported text</jats:p>",
                        "author": [{"given": "Ada", "family": "Lovelace"}],
                        "container-title": ["Journal"],
                        "published": {"date-parts": [[2025, 1, 1]]},
                        "URL": "https://doi.org/10.1000/abc",
                        "type": "journal-article",
                    }
                ],
            }
        }
        _, total, records = sc.crossref_search("rare disease", 1, 10, "now")
        self.assertEqual(total, 1)
        self.assertEqual(records[0]["doi"], "10.1000/abc")
        self.assertEqual(records[0]["abstract"], "Supported text")
        self.assertEqual(records[0]["authors"], ["Ada Lovelace"])
        self.assertEqual(records[0]["source_quality"], "bibliographic_record_only")

    def test_deduplication_uses_all_aliases_transitively(self) -> None:
        first = sc.base_record("openalex", "now")
        first.update(
            doi="10.1/example", title="A sufficiently distinctive medical case title"
        )
        second = sc.base_record("pubmed", "now")
        second.update(pmid="123", title="A sufficiently distinctive medical case title")
        third = sc.base_record("europepmc", "now")
        third.update(doi="10.1/example", pmid="123", title="Different index title")
        merged = sc.merge_records([first, second, third])
        self.assertEqual(len(merged), 1)
        self.assertEqual(
            set(merged[0]["found_via"]), {"OpenAlex", "PubMed", "Europe PMC"}
        )
        self.assertEqual(merged[0]["pmid"], "123")

    def test_same_title_with_conflicting_ids_is_not_merged(self) -> None:
        first = sc.base_record("pubmed", "now")
        first.update(
            doi="10.1128/aac.02130-17",
            pmid="29530850",
            title="Posaconazole",
            year=2018,
            authors=["Kuriakose K"],
        )
        second = sc.base_record("europepmc", "now")
        second.update(
            doi="10.1002/kjm2.12325",
            pmid="33231362",
            title="Posaconazole",
            year=2021,
            authors=["Tantiprawan J"],
        )
        self.assertEqual(len(sc.merge_records([first, second])), 2)

    def test_pubmed_pmc_link_does_not_claim_full_text_was_inspected(self) -> None:
        root = ET.fromstring(
            """
            <PubmedArticleSet><PubmedArticle>
              <MedlineCitation><PMID>123</PMID><Article>
                <ArticleTitle>A case report</ArticleTitle>
                <Abstract><AbstractText>Abstract evidence.</AbstractText></Abstract>
                <PublicationTypeList><PublicationType>Case Reports</PublicationType></PublicationTypeList>
              </Article></MedlineCitation>
              <PubmedData><ArticleIdList><ArticleId IdType="pmc">PMC123</ArticleId></ArticleIdList></PubmedData>
            </PubmedArticle></PubmedArticleSet>
            """
        )
        record = sc.pubmed_records_from_xml(root, "now")[0]
        self.assertEqual(record["access_scope"], "open_full_text")
        self.assertEqual(record["retrieved_evidence_scope"], "abstract")
        self.assertEqual(
            record["full_text_url"], "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/"
        )

    @mock.patch.object(sc.time, "sleep")
    @mock.patch.object(sc.urllib.request, "urlopen")
    def test_request_json_retries_transient_errors(
        self, urlopen: mock.Mock, sleep: mock.Mock
    ) -> None:
        urlopen.side_effect = [
            urllib.error.URLError("temporary"),
            FakeResponse({"ok": True}),
        ]
        payload = sc.request_json("https://example.test", {}, timeout=1, retries=2)
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once()

    def test_source_parser_accepts_crossref_and_rejects_empty(self) -> None:
        self.assertEqual(
            sc.parse_sources("crossref,pubmed,crossref"), ["crossref", "pubmed"]
        )
        with self.assertRaises(Exception):
            sc.parse_sources("")


if __name__ == "__main__":
    unittest.main()

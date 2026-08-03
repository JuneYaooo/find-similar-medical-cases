#!/usr/bin/env python3
"""Search live scholarly APIs for medical case reports and normalize results."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


USER_AGENT = "find-similar-medical-cases/1.0"
DEFAULT_SOURCES = ("pubmed", "europepmc", "openalex")
SUPPORTED_SOURCES = (*DEFAULT_SOURCES, "crossref")
SOURCE_CLASSES = {
    "pubmed": ("PubMed", "official_literature_api", "official_api_live"),
    "europepmc": ("Europe PMC", "official_literature_api", "official_api_live"),
    "openalex": ("OpenAlex", "third_party_scholarly_api", "third_party_api_live"),
    "crossref": ("Crossref", "official_doi_metadata_api", "official_api_live"),
}

SOURCE_QUALITY_PRIORITY = {
    "social_or_unverified": 0,
    "bibliographic_record_only": 1,
    "secondary_professional_summary": 2,
    "editorial_educational_case": 3,
    "peer_reviewed_case_series_or_discussion": 4,
    "peer_reviewed_original_case": 5,
}


class SearchError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compact(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def clean_markup(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return compact(re.sub(r"<[^>]+>", " ", value))


def element_text(element: Optional[ET.Element]) -> Optional[str]:
    if element is None:
        return None
    return compact("".join(element.itertext()))


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    doi = doi.strip().lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = re.sub(r"^doi:\s*", "", doi)
    return doi.rstrip(" .") or None


def normalized_title(title: Optional[str]) -> Optional[str]:
    if not title:
        return None
    value = title.casefold()
    value = re.sub(r"[^\w\u3400-\u9fff]+", "", value)
    return value or None


def normalized_first_author(record: Dict[str, Any]) -> Optional[str]:
    authors = record.get("authors") or []
    return normalized_title(str(authors[0])) if authors else None


def detect_sensitive_query(query: str) -> List[str]:
    checks = {
        "email": r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "mainland China phone number": r"(?<!\d)1[3-9]\d{9}(?!\d)",
        "mainland China national identifier": r"(?<!\d)\d{17}[0-9Xx](?!\d)",
        "record or identity label": r"(?:姓名|身份证|住院号|病历号|门诊号|medical\s*record|patient\s*id|mrn)\s*[:：]",
        "address label": r"(?:家庭住址|现住址|详细地址|home\s+address|street\s+address)\s*[:：]",
        "passport label": r"(?:护照号|passport\s*(?:number|no\.?))\s*[:：]",
        "exact calendar date": r"(?<!\d)(?:19|20)\d{2}[-/.年](?:0?[1-9]|1[0-2])[-/.月](?:0?[1-9]|[12]\d|3[01])日?(?!\d)",
    }
    return [
        label for label, pattern in checks.items() if re.search(pattern, query, re.I)
    ]


def retry_delay(exc: Exception, attempt: int) -> float:
    if isinstance(exc, urllib.error.HTTPError):
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        if retry_after and str(retry_after).isdigit():
            return min(float(retry_after), 10.0)
    return min(0.5 * (2**attempt), 4.0)


def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or exc.code >= 500
    return isinstance(
        exc, (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ET.ParseError)
    )


def request_json(
    url: str,
    params: Dict[str, Any],
    *,
    timeout: int,
    headers: Optional[Dict[str, str]] = None,
    retries: int = 2,
) -> Dict[str, Any]:
    query = urllib.parse.urlencode(
        {k: v for k, v in params.items() if v not in (None, "")}
    )
    request_headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(f"{url}?{query}", headers=request_headers)
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            last_error = exc
            if attempt >= retries or not is_retryable(exc):
                break
            time.sleep(retry_delay(exc, attempt))
    raise SearchError(
        f"GET {url} failed after {attempt + 1} attempt(s): {last_error}"
    ) from last_error


def request_xml(
    url: str, params: Dict[str, Any], *, timeout: int, retries: int = 2
) -> ET.Element:
    query = urllib.parse.urlencode(
        {k: v for k, v in params.items() if v not in (None, "")}
    )
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"Accept": "application/xml", "User-Agent": USER_AGENT},
    )
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return ET.fromstring(response.read())
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            ET.ParseError,
        ) as exc:
            last_error = exc
            if attempt >= retries or not is_retryable(exc):
                break
            time.sleep(retry_delay(exc, attempt))
    raise SearchError(
        f"GET {url} failed after {attempt + 1} attempt(s): {last_error}"
    ) from last_error


def base_record(source: str, retrieved_at: str) -> Dict[str, Any]:
    source_name, source_class, retrieval_method = SOURCE_CLASSES[source]
    return {
        "source_name": source_name,
        "source_class": source_class,
        "retrieval_method": retrieval_method,
        "retrieved_at": retrieved_at,
        "found_via": [source_name],
        "record_id": None,
        "pmid": None,
        "pmcid": None,
        "doi": None,
        "title": None,
        "abstract": None,
        "authors": [],
        "journal": None,
        "year": None,
        "url": None,
        "full_text_url": None,
        "open_access": None,
        "access_scope": "unknown",
        "retrieved_evidence_scope": "metadata",
        "license": None,
        "publication_types": [],
        "source_quality": "bibliographic_record_only",
    }


def source_quality_for_publication_types(publication_types: Iterable[str]) -> str:
    normalized = " ".join(str(value) for value in publication_types if value).casefold()
    if "case report" in normalized:
        return "peer_reviewed_original_case"
    if "case series" in normalized:
        return "peer_reviewed_case_series_or_discussion"
    return "bibliographic_record_only"


def promote_source_quality(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    current = target.get("source_quality") or "bibliographic_record_only"
    candidate = source.get("source_quality") or "bibliographic_record_only"
    if SOURCE_QUALITY_PRIORITY.get(candidate, 0) > SOURCE_QUALITY_PRIORITY.get(
        current, 0
    ):
        target["source_quality"] = candidate


def pubmed_records_from_xml(
    root: ET.Element, retrieved_at: str
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for article in root.findall(".//PubmedArticle"):
        record = base_record("pubmed", retrieved_at)
        citation = article.find("MedlineCitation")
        article_node = citation.find("Article") if citation is not None else None
        if citation is None or article_node is None:
            continue
        pmid = element_text(citation.find("PMID"))
        record["record_id"] = pmid
        record["pmid"] = pmid
        record["title"] = element_text(article_node.find("ArticleTitle"))
        abstract_parts = []
        for part in article_node.findall("Abstract/AbstractText"):
            text_value = element_text(part)
            if not text_value:
                continue
            label = compact(part.attrib.get("Label"))
            abstract_parts.append(f"{label}: {text_value}" if label else text_value)
        record["abstract"] = compact(" ".join(abstract_parts))
        record["journal"] = element_text(article_node.find("Journal/Title"))
        publication_types = [
            value
            for value in (
                element_text(node)
                for node in article_node.findall("PublicationTypeList/PublicationType")
            )
            if value
        ]
        record["publication_types"] = publication_types
        record["authors"] = [
            name
            for author in article_node.findall("AuthorList/Author")
            if (
                name := compact(
                    " ".join(
                        filter(
                            None,
                            [
                                element_text(author.find("ForeName")),
                                element_text(author.find("LastName")),
                            ],
                        )
                    )
                )
            )
        ]
        date_text = " ".join(
            filter(
                None,
                [
                    element_text(article_node.find("ArticleDate/Year")),
                    element_text(
                        article_node.find("Journal/JournalIssue/PubDate/Year")
                    ),
                    element_text(
                        article_node.find("Journal/JournalIssue/PubDate/MedlineDate")
                    ),
                ],
            )
        )
        year_match = re.search(r"(?:19|20)\d{2}", date_text)
        record["year"] = int(year_match.group(0)) if year_match else None
        for article_id in article.findall("PubmedData/ArticleIdList/ArticleId"):
            value = element_text(article_id)
            id_type = article_id.attrib.get("IdType", "").lower()
            if id_type == "doi":
                record["doi"] = normalize_doi(value)
            elif id_type == "pmc":
                record["pmcid"] = value
        record["url"] = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None
        if record["pmcid"]:
            record["full_text_url"] = (
                f"https://pmc.ncbi.nlm.nih.gov/articles/{record['pmcid']}/"
            )
            record["open_access"] = True
            record["access_scope"] = "open_full_text"
        else:
            record["open_access"] = None
            record["access_scope"] = (
                "abstract_only" if record["abstract"] else "metadata_only"
            )
        record["retrieved_evidence_scope"] = (
            "abstract" if record["abstract"] else "metadata"
        )
        record["source_quality"] = source_quality_for_publication_types(
            publication_types
        )
        records.append(record)
    return records


def fetch_pubmed_records(
    ids: List[str], timeout: int, retrieved_at: str
) -> List[Dict[str, Any]]:
    if not ids:
        return []
    common = {
        "db": "pubmed",
        "tool": "find_similar_medical_cases",
        "email": os.getenv("NCBI_EMAIL"),
        "api_key": os.getenv("NCBI_API_KEY"),
    }
    if not os.getenv("NCBI_API_KEY"):
        time.sleep(0.34)
    root = request_xml(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        {**common, "id": ",".join(ids), "rettype": "abstract", "retmode": "xml"},
        timeout=timeout,
    )
    return pubmed_records_from_xml(root, retrieved_at)


def pubmed_search(
    query: str, limit: int, timeout: int, retrieved_at: str, case_filter: bool = True
) -> Tuple[str, int, List[Dict[str, Any]]]:
    effective_query = (
        f'({query}) AND ("Case Reports"[Publication Type] OR "case report"[Title/Abstract])'
        if case_filter
        else query
    )
    common = {
        "db": "pubmed",
        "tool": "find_similar_medical_cases",
        "email": os.getenv("NCBI_EMAIL"),
        "api_key": os.getenv("NCBI_API_KEY"),
    }
    search = request_json(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        {
            **common,
            "term": effective_query,
            "retmode": "json",
            "retmax": limit,
            "sort": "relevance",
        },
        timeout=timeout,
    )
    result = search.get("esearchresult", {})
    ids = result.get("idlist", [])
    total = int(result.get("count", 0) or 0)
    if not ids:
        return effective_query, total, []

    records = fetch_pubmed_records(ids, timeout, retrieved_at)
    return effective_query, total, records


def europepmc_search(
    query: str, limit: int, timeout: int, retrieved_at: str, case_filter: bool = True
) -> Tuple[str, int, List[Dict[str, Any]]]:
    effective_query = f'({query}) AND PUB_TYPE:"case report"' if case_filter else query
    payload = request_json(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        {
            "query": effective_query,
            "format": "json",
            "resultType": "core",
            "pageSize": limit,
        },
        timeout=timeout,
    )
    records: List[Dict[str, Any]] = []
    for item in payload.get("resultList", {}).get("result", []):
        record = base_record("europepmc", retrieved_at)
        record_id = compact(str(item.get("id", "")))
        source_code = compact(item.get("source")) or "MED"
        record["record_id"] = record_id
        record["pmid"] = compact(item.get("pmid"))
        record["pmcid"] = compact(item.get("pmcid"))
        record["doi"] = normalize_doi(item.get("doi"))
        record["title"] = compact(item.get("title"))
        record["abstract"] = compact(item.get("abstractText"))
        author_list = item.get("authorList", {}).get("author", [])
        record["authors"] = [
            name for author in author_list if (name := compact(author.get("fullName")))
        ]
        record["journal"] = compact(item.get("journalTitle"))
        year = str(item.get("pubYear", ""))
        record["year"] = int(year) if year.isdigit() else None
        record["url"] = (
            f"https://europepmc.org/article/{source_code}/{record_id}"
            if record_id
            else None
        )
        is_oa = str(item.get("isOpenAccess", "")).upper() == "Y"
        record["open_access"] = is_oa
        record["access_scope"] = (
            "open_full_text"
            if is_oa and record["pmcid"]
            else ("abstract_only" if record["abstract"] else "metadata_only")
        )
        if record["pmcid"]:
            record["full_text_url"] = (
                f"https://pmc.ncbi.nlm.nih.gov/articles/{record['pmcid']}/"
            )
        record["retrieved_evidence_scope"] = (
            "abstract" if record["abstract"] else "metadata"
        )
        record["license"] = compact(item.get("license"))
        publication_types = item.get("pubTypeList", {}).get("pubType", [])
        if isinstance(publication_types, str):
            publication_types = [publication_types]
        record["publication_types"] = publication_types
        record["source_quality"] = source_quality_for_publication_types(
            publication_types
        )
        records.append(record)
    return effective_query, int(payload.get("hitCount", 0) or 0), records


def reconstruct_abstract(index: Any) -> Optional[str]:
    if not isinstance(index, dict):
        return None
    positions: List[Tuple[int, str]] = []
    for word, offsets in index.items():
        for offset in offsets or []:
            if isinstance(offset, int):
                positions.append((offset, word))
    return compact(" ".join(word for _, word in sorted(positions)))


def normalize_openalex_item(item: Dict[str, Any], retrieved_at: str) -> Dict[str, Any]:
    record = base_record("openalex", retrieved_at)
    openalex_id = compact(item.get("id"))
    record["record_id"] = openalex_id.rsplit("/", 1)[-1] if openalex_id else None
    ids = item.get("ids", {}) or {}
    record["pmid"] = compact(ids.get("pmid"))
    if record["pmid"]:
        record["pmid"] = record["pmid"].rstrip("/").rsplit("/", 1)[-1]
    record["pmcid"] = compact(ids.get("pmcid"))
    if record["pmcid"]:
        pmcid_match = re.search(r"PMC\d+", record["pmcid"], re.I)
        record["pmcid"] = (
            pmcid_match.group(0).upper()
            if pmcid_match
            else record["pmcid"].rstrip("/").rsplit("/", 1)[-1]
        )
    record["doi"] = normalize_doi(item.get("doi") or ids.get("doi"))
    record["title"] = compact(item.get("title") or item.get("display_name"))
    record["abstract"] = reconstruct_abstract(item.get("abstract_inverted_index"))
    record["authors"] = [
        name
        for authorship in item.get("authorships", [])
        if (name := compact((authorship.get("author") or {}).get("display_name")))
    ]
    primary_location = item.get("primary_location") or {}
    best_oa_location = item.get("best_oa_location") or {}
    record["journal"] = compact(
        (primary_location.get("source") or {}).get("display_name")
    )
    year = item.get("publication_year")
    record["year"] = int(year) if isinstance(year, int) or str(year).isdigit() else None
    record["url"] = compact(primary_location.get("landing_page_url")) or openalex_id
    open_access = item.get("open_access") or {}
    record["open_access"] = bool(open_access.get("is_oa"))
    pdf_url = primary_location.get("pdf_url") or best_oa_location.get("pdf_url")
    record["full_text_url"] = compact(pdf_url)
    record["access_scope"] = (
        "open_full_text"
        if pdf_url
        else ("abstract_only" if record["abstract"] else "metadata_only")
    )
    record["retrieved_evidence_scope"] = (
        "abstract" if record["abstract"] else "metadata"
    )
    record["license"] = compact(
        primary_location.get("license") or best_oa_location.get("license")
    )
    record["publication_types"] = [
        compact(item.get("type_crossref")) or compact(item.get("type"))
    ]
    record["publication_types"] = [
        value for value in record["publication_types"] if value
    ]
    record["source_quality"] = "bibliographic_record_only"
    record["cited_by_count"] = item.get("cited_by_count")
    return record


def openalex_search(
    query: str, limit: int, timeout: int, retrieved_at: str, case_filter: bool = True
) -> Tuple[str, int, List[Dict[str, Any]]]:
    effective_query = f'{query} "case report"' if case_filter else query
    params: Dict[str, Any] = {
        "search": effective_query,
        "filter": "type:article",
        "per-page": limit,
        "mailto": os.getenv("OPENALEX_EMAIL"),
        "api_key": os.getenv("OPENALEX_API_KEY"),
    }
    payload = request_json("https://api.openalex.org/works", params, timeout=timeout)
    records = [
        normalize_openalex_item(item, retrieved_at)
        for item in payload.get("results", [])
    ]
    total = int((payload.get("meta") or {}).get("count", 0) or 0)
    return effective_query, total, records


def crossref_search(
    query: str, limit: int, timeout: int, retrieved_at: str, case_filter: bool = True
) -> Tuple[str, int, List[Dict[str, Any]]]:
    effective_query = f'{query} "case report"' if case_filter else query
    payload = request_json(
        "https://api.crossref.org/works",
        {
            "query.bibliographic": effective_query,
            "filter": "type:journal-article",
            "rows": limit,
            "mailto": os.getenv("CROSSREF_EMAIL") or os.getenv("NCBI_EMAIL"),
        },
        timeout=timeout,
    )
    message = payload.get("message") or {}
    records: List[Dict[str, Any]] = []
    for item in message.get("items", []) or []:
        record = base_record("crossref", retrieved_at)
        doi = normalize_doi(item.get("DOI"))
        titles = item.get("title") or []
        containers = item.get("container-title") or []
        date_parts = ((item.get("published") or {}).get("date-parts") or [[]])[0]
        abstract = clean_markup(item.get("abstract"))
        record.update(
            record_id=doi,
            doi=doi,
            title=compact(titles[0]) if titles else None,
            abstract=abstract,
            authors=[
                name
                for author in item.get("author", []) or []
                if (
                    name := compact(
                        " ".join(
                            filter(None, [author.get("given"), author.get("family")])
                        )
                    )
                )
            ],
            journal=compact(containers[0]) if containers else None,
            year=int(date_parts[0])
            if date_parts and str(date_parts[0]).isdigit()
            else None,
            url=compact(item.get("URL")) or (f"https://doi.org/{doi}" if doi else None),
            access_scope="metadata_only",
            retrieved_evidence_scope="abstract" if abstract else "metadata",
            publication_types=[
                value
                for value in [compact(item.get("type")), compact(item.get("subtype"))]
                if value
            ],
            source_quality="bibliographic_record_only",
        )
        records.append(record)
    return effective_query, int(message.get("total-results", 0) or 0), records


def record_key(record: Dict[str, Any]) -> str:
    if record.get("doi"):
        return f"doi:{normalize_doi(record['doi'])}"
    if record.get("pmid"):
        return f"pmid:{record['pmid']}"
    if record.get("pmcid"):
        return f"pmcid:{record['pmcid']}"
    if normalized_title(record.get("title")):
        return f"title:{normalized_title(record['title'])}"
    return f"source:{record.get('source_name')}:{record.get('record_id')}"


def record_aliases(record: Dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    if record.get("doi"):
        aliases.add(f"doi:{normalize_doi(record['doi'])}")
    if record.get("pmid"):
        aliases.add(f"pmid:{record['pmid']}")
    if record.get("pmcid"):
        aliases.add(f"pmcid:{str(record['pmcid']).upper()}")
    title = normalized_title(record.get("title"))
    year = record.get("year")
    first_author = normalized_first_author(record)
    if title and len(title) >= 16 and year and first_author:
        aliases.add(f"title-year-author:{title}:{year}:{first_author}")
    return aliases or {f"source:{record.get('source_name')}:{record.get('record_id')}"}


def stable_identifier_conflict(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    normalizers = {
        "doi": lambda value: normalize_doi(str(value)),
        "pmid": lambda value: str(value).strip(),
        "pmcid": lambda value: str(value).strip().upper(),
    }
    for field, normalize in normalizers.items():
        left_value, right_value = left.get(field), right.get(field)
        if (
            left_value
            and right_value
            and normalize(left_value) != normalize(right_value)
        ):
            return True
    return False


def merge_record_values(current: Dict[str, Any], record: Dict[str, Any]) -> None:
    for source in record.get("found_via", []):
        if source not in current["found_via"]:
            current["found_via"].append(source)
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
        if not current.get(field) and record.get(field):
            current[field] = record[field]
    if len(record.get("abstract") or "") > len(current.get("abstract") or ""):
        current["abstract"] = record["abstract"]
    if record.get("open_access") is True:
        current["open_access"] = True
    if record.get("access_scope") == "open_full_text":
        current["access_scope"] = "open_full_text"
    evidence_priority = {"metadata": 0, "title": 1, "abstract": 2, "full_text": 3}
    if evidence_priority.get(
        record.get("retrieved_evidence_scope"), 0
    ) > evidence_priority.get(current.get("retrieved_evidence_scope"), 0):
        current["retrieved_evidence_scope"] = record["retrieved_evidence_scope"]
    current["authors"] = current.get("authors") or record.get("authors", [])
    current["publication_types"] = sorted(
        set(current.get("publication_types", []) + record.get("publication_types", []))
    )
    promote_source_quality(current, record)


def merge_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: List[Dict[str, Any]] = []
    grouped_aliases: List[set[str]] = []
    for record in records:
        aliases = record_aliases(record)
        matching = [
            index
            for index, known in enumerate(grouped_aliases)
            if aliases & known
            and not stable_identifier_conflict(grouped[index], record)
        ]
        if not matching:
            grouped.append(record.copy())
            grouped_aliases.append(set(aliases))
            continue
        target_index = matching[0]
        current = grouped[target_index]
        merge_record_values(current, record)
        grouped_aliases[target_index].update(aliases)
        for index in reversed(matching[1:]):
            duplicate = grouped[index]
            if stable_identifier_conflict(current, duplicate):
                continue
            duplicate = grouped.pop(index)
            duplicate_aliases = grouped_aliases.pop(index)
            grouped_aliases[target_index].update(duplicate_aliases)
            merge_record_values(current, duplicate)
    return grouped


def parse_sources(value: str) -> List[str]:
    sources = list(
        dict.fromkeys(item.strip().lower() for item in value.split(",") if item.strip())
    )
    if not sources:
        raise argparse.ArgumentTypeError("at least one source is required")
    unknown = sorted(set(sources) - set(SUPPORTED_SOURCES))
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown sources: {', '.join(unknown)}")
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query",
        required=True,
        help="De-identified clinical concepts; English works best for these APIs",
    )
    parser.add_argument(
        "--sources", default=",".join(DEFAULT_SOURCES), type=parse_sources
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Results requested from each source (1-50)",
    )
    parser.add_argument(
        "--timeout", type=int, default=25, help="Per-request timeout in seconds"
    )
    parser.add_argument(
        "--no-case-filter",
        action="store_true",
        help="Do not append a case-report publication/text filter",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()
    if not 1 <= args.limit <= 50:
        parser.error("--limit must be between 1 and 50")
    if not 1 <= args.timeout <= 300:
        parser.error("--timeout must be between 1 and 300 seconds")
    query = compact(args.query)
    if not query:
        parser.error("--query must not be empty")
    sensitive = detect_sensitive_query(query)
    if sensitive:
        parser.error(
            "query may contain sensitive identifiers: "
            + ", ".join(sensitive)
            + ". De-identify it before external search"
        )

    retrieved_at = utc_now()
    all_records: List[Dict[str, Any]] = []
    coverage: List[Dict[str, Any]] = []
    connectors = {
        "pubmed": pubmed_search,
        "europepmc": europepmc_search,
        "openalex": openalex_search,
        "crossref": crossref_search,
    }
    for source in args.sources:
        source_name, source_class, retrieval_method = SOURCE_CLASSES[source]
        entry = {
            "source_name": source_name,
            "source_class": source_class,
            "retrieval_method": retrieval_method,
            "status": "failed",
            "retrieved_at": retrieved_at,
            "effective_query": None,
            "total_hits": None,
            "returned": 0,
            "limitation": None,
        }
        try:
            effective_query, total, records = connectors[source](
                query, args.limit, args.timeout, retrieved_at, not args.no_case_filter
            )
            entry.update(
                status="success",
                effective_query=effective_query,
                total_hits=total,
                returned=len(records),
            )
            all_records.extend(records)
        except (
            Exception
        ) as exc:  # Keep one unavailable source from hiding other results.
            entry["limitation"] = str(exc)
        coverage.append(entry)

    output = {
        "query": query,
        "retrieved_at": retrieved_at,
        "live_search": True,
        "notice": "Live means the source index was queried now; index coverage may lag publication.",
        "coverage": coverage,
        "records": merge_records(all_records),
    }
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0 if any(item["status"] == "success" for item in coverage) else 2


if __name__ == "__main__":
    raise SystemExit(main())

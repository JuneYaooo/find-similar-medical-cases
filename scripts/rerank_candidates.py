#!/usr/bin/env python3
"""Optional local cross-encoder reranking for normalized medical candidates."""

from __future__ import annotations

import json
import math
import time
from typing import Any, Callable, Dict, List, Sequence, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest

import search_cases as sc


DEFAULT_MODEL = "ncbi/MedCPT-Cross-Encoder"
DEFAULT_REVISION = "main"
DEFAULT_SILICONFLOW_MODEL = "BAAI/bge-reranker-v2-m3"
DEFAULT_SILICONFLOW_REVISION = "api"
DEFAULT_SILICONFLOW_ENDPOINT = "https://api.siliconflow.cn/v1/rerank"
CASE_QUERY_FIELDS = (
    ("age_band", "Age"),
    ("sex_if_relevant", "Sex"),
    ("main_presentation", "Presentation"),
    ("duration_and_course", "Course"),
    ("key_positive_findings", "Positive findings"),
    ("key_negative_findings", "Negative findings"),
    ("labs_imaging_pathology", "Tests and pathology"),
    ("suspected_or_confirmed_diagnosis", "Diagnosis or differential"),
    ("intervention", "Intervention"),
    ("response_and_outcome", "Response and outcome"),
    ("rare_or_discriminating_features", "Discriminating features"),
    ("specialty", "Specialty"),
)


class RerankerError(RuntimeError):
    pass


def env_value(name: str) -> str | None:
    """Read an environment variable, with a minimal ignored .env fallback.

    Delegates to the shared loader in search_cases.py so every script resolves
    the same environment/.env precedence.
    """

    return sc.env_value(name)


def text_values(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        values: List[str] = []
        for nested in value.values():
            values.extend(text_values(nested))
        return values
    if isinstance(value, (list, tuple)):
        values = []
        for nested in value:
            values.extend(text_values(nested))
        return values
    cleaned = sc.compact(str(value))
    return [cleaned] if cleaned else []


def build_case_query(plan: Dict[str, Any]) -> str:
    """Build a stable, de-identified natural-language query from the plan."""

    explicit = sc.compact(plan.get("reranker_query"))
    if explicit:
        return explicit
    fingerprint = plan.get("case_fingerprint") or {}
    if not isinstance(fingerprint, dict):
        return ""
    sections = []
    for field, label in CASE_QUERY_FIELDS:
        values = text_values(fingerprint.get(field))
        if values:
            sections.append(f"{label}: {', '.join(values)}")
    return ". ".join(sections)


def build_document(record: Dict[str, Any]) -> str:
    title = sc.clean_markup(str(record.get("title") or "")) or ""
    abstract = sc.clean_markup(str(record.get("abstract") or "")) or ""
    parts = []
    if title:
        parts.append(f"Title: {title}")
    if abstract:
        parts.append(f"Abstract: {abstract}")
    return " ".join(parts) or "Untitled candidate"


def select_device(torch_module: Any, requested: str) -> str:
    if requested != "auto":
        return requested
    if torch_module.cuda.is_available():
        return "cuda"
    mps = getattr(torch_module.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def score_documents(
    query: str,
    documents: Sequence[str],
    *,
    model_name: str,
    revision: str,
    batch_size: int,
    max_length: int,
    device: str,
    endpoint: str | None = None,
) -> Tuple[List[float], Dict[str, Any]]:
    """Score query-document pairs with a Transformers sequence classifier."""

    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:
        raise RerankerError(
            "MedCPT reranking requires optional dependencies from "
            "requirements-reranker.txt"
        ) from exc

    try:
        tokenizer = AutoTokenizer.from_pretrained(model_name, revision=revision)
        model = AutoModelForSequenceClassification.from_pretrained(
            model_name, revision=revision
        )
        selected_device = select_device(torch, device)
        model.to(selected_device)
        model.eval()
        scores: List[float] = []
        with torch.inference_mode():
            for start in range(0, len(documents), batch_size):
                batch = list(documents[start : start + batch_size])
                encoded = tokenizer(
                    [query] * len(batch),
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=max_length,
                    return_tensors="pt",
                )
                encoded = {
                    key: value.to(selected_device) for key, value in encoded.items()
                }
                logits = model(**encoded).logits
                if logits.ndim == 1:
                    batch_scores = logits
                elif logits.shape[-1] == 1:
                    batch_scores = logits[:, 0]
                else:
                    batch_scores = logits[:, -1]
                scores.extend(batch_scores.detach().float().cpu().tolist())
    except RerankerError:
        raise
    except Exception as exc:
        raise RerankerError(f"cannot run reranker model {model_name}: {exc}") from exc

    resolved_revision = (
        getattr(model.config, "_commit_hash", None)
        or getattr(tokenizer, "init_kwargs", {}).get("_commit_hash")
        or revision
    )
    return scores, {
        "backend": "transformers_sequence_classification",
        "model": model_name,
        "requested_revision": revision,
        "resolved_revision": resolved_revision,
        "device": selected_device,
        "batch_size": batch_size,
        "max_length": max_length,
        "score_semantics": "raw_sequence_classification_logit_higher_is_better",
    }


def score_documents_siliconflow(
    query: str,
    documents: Sequence[str],
    *,
    model_name: str = DEFAULT_SILICONFLOW_MODEL,
    revision: str = DEFAULT_SILICONFLOW_REVISION,
    batch_size: int = 8,
    max_length: int = 512,
    device: str = "remote",
    endpoint: str = DEFAULT_SILICONFLOW_ENDPOINT,
) -> Tuple[List[float], Dict[str, Any]]:
    """Score query-document pairs through SiliconFlow's rerank endpoint."""

    del batch_size, max_length, device
    api_key = env_value("SILICONFLOW_API_KEY")
    if not api_key:
        raise RerankerError(
            "SILICONFLOW_API_KEY is not configured in the environment or .env"
        )
    if not endpoint.startswith("https://"):
        raise RerankerError("SiliconFlow endpoint must use HTTPS")
    payload = json.dumps(
        {
            "model": model_name,
            "query": query,
            "documents": list(documents),
            "return_documents": False,
            "top_n": len(documents),
        }
    ).encode("utf-8")
    http_request = urlrequest.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    response_payload: Dict[str, Any] | None = None
    last_error: Exception | None = None
    http_attempts = 0
    for attempt in range(2):
        http_attempts += 1
        try:
            with urlrequest.urlopen(http_request, timeout=90) as response:
                decoded = json.loads(response.read().decode("utf-8"))
            if not isinstance(decoded, dict):
                raise RerankerError("SiliconFlow response must be a JSON object")
            response_payload = decoded
            break
        except urlerror.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt:
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    detail = str(exc)
                raise RerankerError(
                    f"SiliconFlow rerank HTTP {exc.code}: {detail}"
                ) from exc
            time.sleep(0.5)
        except (OSError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt:
                raise RerankerError(f"SiliconFlow rerank request failed: {exc}") from exc
            time.sleep(0.5)
    if response_payload is None:
        raise RerankerError(f"SiliconFlow rerank request failed: {last_error}")
    results = response_payload.get("results")
    if not isinstance(results, list) or len(results) != len(documents):
        raise RerankerError(
            "SiliconFlow response results length does not match submitted documents"
        )
    scores: List[float | None] = [None] * len(documents)
    for item in results:
        if not isinstance(item, dict):
            raise RerankerError("SiliconFlow result item must be an object")
        index = item.get("index")
        score = item.get("relevance_score")
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < len(documents)
            or scores[index] is not None
            or isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
        ):
            raise RerankerError("SiliconFlow returned invalid result indices or scores")
        scores[index] = float(score)
    if any(score is None for score in scores):
        raise RerankerError("SiliconFlow response omitted a document score")
    return [float(score) for score in scores], {
        "backend": "siliconflow_rerank_api",
        "provider": "SiliconFlow",
        "endpoint": endpoint,
        "model": model_name,
        "requested_revision": revision,
        "resolved_revision": "api_model_endpoint",
        "device": "remote_api",
        "batch_size": len(documents),
        "max_length": None,
        "score_semantics": "provider_relevance_score_higher_is_better",
        "return_documents": False,
        "http_attempts": http_attempts,
        "documents_submitted": len(documents),
    }


def rerank_records(
    records: List[Dict[str, Any]],
    query: str,
    *,
    top_k: int,
    model_name: str = DEFAULT_MODEL,
    revision: str = DEFAULT_REVISION,
    batch_size: int = 8,
    max_length: int = 512,
    device: str = "auto",
    endpoint: str | None = None,
    scorer: Callable[..., Tuple[List[float], Dict[str, Any]]] = score_documents,
) -> Dict[str, Any]:
    if not query:
        raise RerankerError("cannot rerank without a case fingerprint or reranker_query")
    selected = records[: min(top_k, len(records))]
    if not selected:
        return {
            "status": "applied",
            "model": model_name,
            "requested_revision": revision,
            "candidates_scored": 0,
            "top_k_requested": top_k,
        }
    documents = [build_document(record) for record in selected]
    try:
        scores, backend = scorer(
            query,
            documents,
            model_name=model_name,
            revision=revision,
            batch_size=batch_size,
            max_length=max_length,
            device=device,
            endpoint=endpoint,
        )
    except RerankerError:
        raise
    except Exception as exc:
        raise RerankerError(f"reranker backend failed: {exc}") from exc
    if len(scores) != len(selected):
        raise RerankerError(
            f"reranker returned {len(scores)} scores for {len(selected)} candidates"
        )
    for pre_rank, (record, score) in enumerate(zip(selected, scores), start=1):
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise RerankerError(f"reranker score at position {pre_rank} is not numeric")
        numeric_score = float(score)
        if not math.isfinite(numeric_score):
            raise RerankerError(f"reranker score at position {pre_rank} is not finite")
        record["reranker"] = {
            "status": "scored",
            "model": model_name,
            "resolved_revision": backend.get("resolved_revision") or revision,
            "score": round(numeric_score, 8),
            "pre_reranker_rank": pre_rank,
            "post_reranker_rank": None,
            "query_scope": "deidentified_case_fingerprint",
            "document_scope": record.get("retrieved_evidence_scope") or "metadata",
        }
    return {
        "status": "applied",
        **backend,
        "top_k_requested": top_k,
        "candidates_scored": len(selected),
        "query_scope": "deidentified_case_fingerprint",
        "document_scope": "title_and_available_abstract",
        "notice": (
            "Raw cross-encoder logits only rerank the selected candidate prefix; "
            "they are not probabilities or validated clinical similarity scores."
        ),
    }

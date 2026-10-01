from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Iterable

from agents.v3.state_db import V3StateDB


ALLOWED_OUTCOMES = {"success", "failure"}
ALLOWED_POLARITIES = {"positive", "negative"}
ALLOWED_RECORD_STATUSES = {"active", "revised", "invalidated", "duplicate"}
ALLOWED_RELATION_TYPES = {
    "spatial",
    "causal",
    "temporal",
    "identity",
    "count",
    "style",
    "text",
    "preservation",
    "causal_state_change",
    "other",
}
PRIVATE_JUDGE_KEYS = {
    "judge_response",
    "raw_judge_response",
    "judge_reason",
    "judge_rationale",
    "judge_prompt",
    "judge_rubric",
    "score_breakdown",
    "scores_raw",
    "judge1",
    "judge2",
    "judge3",
    "results",
    "weighted_score",
    "score",
}
GENERIC_LESSON_PHRASES = {
    "benchmark criterion",
    "benchmark criteria",
    "hidden benchmark",
    "external binary gate",
    "binary external validation",
    "make benchmark criterion explicit",
    "rebuild the visual rubric from the original instruction",
}
GENERIC_ELEMENTS = {
    "object",
    "objects",
    "thing",
    "things",
    "item",
    "items",
    "subject",
    "subjects",
    "element",
    "elements",
    "image",
    "picture",
    "scene",
    "criterion",
    "criteria",
    "requirement",
    "requirements",
    "it",
    "this",
    "that",
}


class RelationMemoryValidationError(ValueError):
    pass


def assert_no_private_judge_fields(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if key_text in PRIVATE_JUDGE_KEYS or key_text.startswith("raw_judge"):
                raise RelationMemoryValidationError(
                    f"private judge field is not allowed in evolution review input: {path}.{key_text}"
                )
            assert_no_private_judge_fields(child, path=f"{path}.{key_text}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            assert_no_private_judge_fields(child, path=f"{path}[{idx}]")


def contains_generic_lesson(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False).lower() if not isinstance(value, str) else value.lower()
    return any(phrase in text for phrase in GENERIC_LESSON_PHRASES)


def normalize_review_relation_records(
    review_payload: dict[str, Any],
    *,
    benchmark: str,
    sample_id: str,
    round_index: int,
    source_image_path: str,
    rubric_ref: str,
    episode_id: str,
    judge_label: int,
    created_at: float | None = None,
    min_confidence: float = 0.2,
) -> list[dict[str, Any]]:
    assert_no_private_judge_fields(review_payload)
    if contains_generic_lesson(review_payload):
        raise RelationMemoryValidationError("generic V2-style lesson text is not allowed in relation records")

    outcome = "success" if int(judge_label) == 1 else "failure"
    expected_polarity = "positive" if outcome == "success" else "negative"
    declared_outcome = str(review_payload.get("outcome") or outcome).strip().lower()
    if declared_outcome != outcome:
        raise RelationMemoryValidationError(f"review outcome {declared_outcome!r} does not match judge label {judge_label}")

    raw_records = review_payload.get("relation_records")
    if raw_records is None:
        raw_records = []
    if not isinstance(raw_records, list):
        raise RelationMemoryValidationError("relation_records must be a list")

    now = float(created_at if created_at is not None else time.time())
    records: list[dict[str, Any]] = []
    for raw in raw_records:
        if not isinstance(raw, dict):
            continue
        record = normalize_relation_record(
            raw,
            benchmark=benchmark,
            sample_id=sample_id,
            round_index=round_index,
            outcome=outcome,
            expected_polarity=expected_polarity,
            source_image_path=source_image_path,
            rubric_ref=rubric_ref,
            episode_id=episode_id,
            judge_label=int(judge_label),
            created_at=now,
            min_confidence=min_confidence,
        )
        if record is not None:
            records.append(record)
    return records


def normalize_relation_record(
    raw: dict[str, Any],
    *,
    benchmark: str,
    sample_id: str,
    round_index: int,
    outcome: str,
    expected_polarity: str,
    source_image_path: str,
    rubric_ref: str,
    episode_id: str,
    judge_label: int,
    created_at: float,
    min_confidence: float,
) -> dict[str, Any] | None:
    assert_no_private_judge_fields(raw)
    if contains_generic_lesson(raw):
        raise RelationMemoryValidationError("generic V2-style lesson text is not allowed in relation record")
    if outcome not in ALLOWED_OUTCOMES:
        raise RelationMemoryValidationError(f"invalid relation outcome: {outcome!r}")

    polarity = str(raw.get("polarity") or expected_polarity).strip().lower()
    if polarity not in ALLOWED_POLARITIES:
        raise RelationMemoryValidationError(f"invalid relation polarity: {polarity!r}")
    if polarity != expected_polarity:
        raise RelationMemoryValidationError(f"relation polarity {polarity!r} does not match outcome {outcome!r}")

    confidence = _float(raw.get("confidence"), default=0.0)
    if confidence < min_confidence:
        return None

    elements = _clean_elements(raw.get("elements"))
    attributes = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
    if raw.get("reuse_condition"):
        attributes = {**attributes, "reuse_condition": str(raw.get("reuse_condition"))}
    if len(elements) < 2 and not attributes:
        return None

    relation_type = str(raw.get("relation_type") or "other").strip().lower()
    if relation_type not in ALLOWED_RELATION_TYPES:
        relation_type = "other"

    prompt_span = _clean_text(raw.get("prompt_span"))
    relation_text = _clean_text(raw.get("relation_text"))
    visual_evidence = _clean_text(raw.get("visual_evidence"))
    repair_hint = _clean_text(raw.get("repair_hint"))
    failure_type = _clean_text(raw.get("failure_type")) if polarity == "negative" else ""
    if not relation_text or not visual_evidence:
        return None

    record = {
        "benchmark": str(benchmark),
        "sample_id": str(sample_id),
        "round_index": int(round_index),
        "outcome": outcome,
        "polarity": polarity,
        "prompt_span": prompt_span,
        "elements": elements,
        "relation_type": relation_type,
        "relation_text": relation_text,
        "attributes": attributes,
        "visual_evidence": visual_evidence,
        "failure_type": failure_type,
        "repair_hint": repair_hint,
        "source_image_path": str(source_image_path),
        "rubric_ref": str(rubric_ref),
        "episode_id": str(episode_id),
        "judge_label": int(judge_label),
        "confidence": confidence,
        "created_at": float(created_at),
    }
    record["relation_id"] = _relation_id(record)
    return record


def insert_relation_records(db: V3StateDB, records: Iterable[dict[str, Any]]) -> int:
    count = 0
    for record in records:
        db.insert_evo_relation_record(
            relation_id=str(record["relation_id"]),
            benchmark=str(record.get("benchmark") or ""),
            sample_id=str(record.get("sample_id") or ""),
            round_index=int(record.get("round_index") or 0),
            outcome=str(record.get("outcome") or ""),
            polarity=str(record.get("polarity") or ""),
            prompt_span=str(record.get("prompt_span") or ""),
            elements=[str(item) for item in record.get("elements") or []],
            relation_type=str(record.get("relation_type") or "other"),
            relation_text=str(record.get("relation_text") or ""),
            attributes=record.get("attributes") if isinstance(record.get("attributes"), dict) else {},
            visual_evidence=str(record.get("visual_evidence") or ""),
            failure_type=str(record.get("failure_type") or ""),
            repair_hint=str(record.get("repair_hint") or ""),
            source_image_path=str(record.get("source_image_path") or ""),
            rubric_ref=str(record.get("rubric_ref") or ""),
            episode_id=str(record.get("episode_id") or ""),
            judge_label=int(record.get("judge_label")) if record.get("judge_label") is not None else None,
            confidence=float(record.get("confidence") or 0.0),
            created_at=float(record.get("created_at") or time.time()),
        )
        count += 1
    return count


def public_relation_row(row: dict[str, Any]) -> dict[str, Any]:
    return _public_relation_row(row)


def relation_query_text(row: dict[str, Any]) -> str:
    public = _public_relation_row(row)
    return " ".join(
        str(part)
        for part in (
            public.get("prompt_span"),
            " ".join(str(item) for item in public.get("elements") or []),
            public.get("relation_type"),
            public.get("relation_text"),
            public.get("visual_evidence"),
            public.get("failure_type"),
            public.get("repair_hint"),
            json.dumps(public.get("attributes") or {}, ensure_ascii=False, sort_keys=True),
        )
        if str(part or "").strip()
    )


def fetch_active_relation_candidates(
    dbs: Iterable[tuple[V3StateDB, str]],
    *,
    query: str,
    benchmark: str,
    limit: int,
    exclude_relation_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    exclude = exclude_relation_ids or set()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for db, origin_sandbox_commit_id in dbs:
        for row in db.fetch_relation_context(query, benchmark=benchmark, limit=limit):
            relation_id = str(row.get("relation_id") or "")
            if not relation_id or relation_id in exclude or relation_id in seen:
                continue
            public = _public_relation_row(row)
            public["origin_sandbox_commit_id"] = str(
                row.get("origin_sandbox_commit_id")
                or origin_sandbox_commit_id
                or getattr(db, "sandbox_commit_id", "")
                or ""
            )
            public["_source_db_path"] = str(getattr(db, "path", ""))
            out.append(public)
            seen.add(relation_id)
            if len(out) >= limit:
                return out
    return out


def ensure_relation_copy(
    *,
    current_db: V3StateDB,
    source_db: V3StateDB,
    relation_id: str,
    origin_sandbox_commit_id: str = "",
) -> dict[str, Any]:
    existing = current_db.fetch_evo_relation_record(relation_id)
    if existing is not None:
        return existing
    source = source_db.fetch_evo_relation_record(relation_id)
    if source is None:
        raise KeyError(f"relation candidate not found in source DB: {relation_id}")
    current_db.upsert_evo_relation_record_row(
        source,
        origin_relation_id=relation_id,
        origin_sandbox_commit_id=origin_sandbox_commit_id or str(getattr(source_db, "sandbox_commit_id", "") or ""),
    )
    copied = current_db.fetch_evo_relation_record(relation_id)
    if copied is None:
        raise KeyError(f"relation candidate copy failed: {relation_id}")
    return copied


def apply_relation_lifecycle_updates(
    *,
    current_db: V3StateDB,
    source_dbs_by_relation_id: dict[str, tuple[V3StateDB, str]],
    updates: Iterable[dict[str, Any]],
    allowed_candidate_ids: set[str],
    allowed_new_relation_ids: set[str],
) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for update in updates:
        target_relation_id = str(update.get("target_relation_id") or update.get("relation_id") or "")
        status = str(update.get("record_status") or update.get("status") or "").strip().lower()
        if status not in ALLOWED_RECORD_STATUSES or status == "active":
            continue
        is_duplicate_new = status == "duplicate" and target_relation_id in allowed_new_relation_ids
        if target_relation_id not in allowed_candidate_ids and not is_duplicate_new:
            raise RelationMemoryValidationError(
                f"apply_relation_updates target was not returned by retrieve_related_experiences: {target_relation_id}"
            )
        if target_relation_id in allowed_candidate_ids:
            source_db, origin_commit = source_dbs_by_relation_id.get(target_relation_id, (current_db, ""))
            ensure_relation_copy(
                current_db=current_db,
                source_db=source_db,
                relation_id=target_relation_id,
                origin_sandbox_commit_id=origin_commit,
            )
        reason = _clean_text(update.get("revision_reason") or update.get("reason") or update.get("semantic_reason") or "")
        revised_by = str(update.get("revised_by_relation_id") or update.get("new_relation_id") or "")
        confidence = _float(update.get("revision_confidence") or update.get("confidence"), default=0.0)
        applied.append(
            current_db.update_evo_relation_lifecycle(
                relation_id=target_relation_id,
                record_status=status,
                revision_reason=reason,
                revised_by_relation_id=revised_by,
                revision_confidence=confidence,
            )
            | {"target_relation_id": target_relation_id, "record_status": status}
        )
    return applied


def split_top_relation_rows(rows: Iterable[dict[str, Any]], *, limit: int = 8) -> dict[str, list[dict[str, Any]]]:
    by_polarity: dict[str, list[dict[str, Any]]] = {"positive": [], "negative": []}
    seen: set[str] = set()
    for row in rows:
        relation_id = str(row.get("relation_id") or "")
        if relation_id and relation_id in seen:
            continue
        if relation_id:
            seen.add(relation_id)
        polarity = str(row.get("polarity") or "")
        if polarity in by_polarity:
            by_polarity[polarity].append(row)
    for polarity in by_polarity:
        by_polarity[polarity].sort(
            key=lambda item: (
                float(item.get("retrieval_score") or 0.0),
                float(item.get("confidence") or 0.0),
                float(item.get("created_at") or 0.0),
            ),
            reverse=True,
        )
        by_polarity[polarity] = by_polarity[polarity][:limit]
    return by_polarity


def format_relation_memory_context(rows_by_polarity: dict[str, list[dict[str, Any]]]) -> str:
    positives = rows_by_polarity.get("positive") or []
    negatives = rows_by_polarity.get("negative") or []
    if not positives and not negatives:
        return ""
    parts = [
        "<relation-memory>",
        "Positive relation records are reusable visual constraints.",
        "Negative relation records are checks and repair warnings.",
        "The current instruction remains primary. Do not copy old prompts wholesale.",
        "",
        "When writing the rubric:",
        "- convert retrieved tuples into concrete planned_elements and element_relationships;",
        "- apply positive records only when their elements/relations match the current prompt;",
        "- apply negative records as checklist items to avoid repeated failures;",
        "- ignore records with weak element overlap or low confidence.",
        "<positive-relations>",
    ]
    parts.extend(json.dumps(_public_relation_row(row), ensure_ascii=False, sort_keys=True) for row in positives)
    parts.append("</positive-relations>")
    parts.append("<negative-relations>")
    parts.extend(json.dumps(_public_relation_row(row), ensure_ascii=False, sort_keys=True) for row in negatives)
    parts.append("</negative-relations>")
    parts.append("</relation-memory>")
    return "\n".join(parts)


def _public_relation_row(row: dict[str, Any]) -> dict[str, Any]:
    elements = _decode_json_field(row.get("elements_json"), default=[])
    attributes = _decode_json_field(row.get("attributes_json"), default={})
    return {
        "relation_id": row.get("relation_id"),
        "benchmark": row.get("benchmark"),
        "sample_id": row.get("sample_id"),
        "round_index": row.get("round_index"),
        "polarity": row.get("polarity"),
        "prompt_span": row.get("prompt_span"),
        "elements": elements,
        "relation_type": row.get("relation_type"),
        "relation_text": row.get("relation_text"),
        "attributes": attributes,
        "visual_evidence": row.get("visual_evidence"),
        "failure_type": row.get("failure_type"),
        "repair_hint": row.get("repair_hint"),
        "confidence": row.get("confidence"),
        "retrieval_score": row.get("retrieval_score"),
        "record_status": row.get("record_status") or "active",
        "revision_reason": row.get("revision_reason"),
        "revised_by_relation_id": row.get("revised_by_relation_id"),
        "revision_confidence": row.get("revision_confidence"),
        "origin_relation_id": row.get("origin_relation_id"),
        "origin_sandbox_commit_id": row.get("origin_sandbox_commit_id"),
    }


def _decode_json_field(value: Any, *, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return default
    return data


def _clean_elements(value: Any) -> list[str]:
    raw_items = value if isinstance(value, list) else []
    out: list[str] = []
    for item in raw_items:
        text = _clean_text(item)
        if not text:
            continue
        lowered = text.strip().lower()
        if lowered in GENERIC_ELEMENTS:
            continue
        if text not in out:
            out.append(text)
    return out[:8]


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())[:1000]


def _float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _relation_id(record: dict[str, Any]) -> str:
    seed = json.dumps(
        {
            key: record.get(key)
            for key in (
                "benchmark",
                "sample_id",
                "round_index",
                "outcome",
                "polarity",
                "prompt_span",
                "elements",
                "relation_type",
                "relation_text",
                "visual_evidence",
                "failure_type",
                "repair_hint",
                "episode_id",
                "judge_label",
            )
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return "rel_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_\u4e00-\u9fff]+", text.lower()) if len(token) > 1}

from __future__ import annotations

import json
import hashlib
import re
import sqlite3
from typing import Any, Iterable

from agents.v3.agent_pool import AgentResourcePool

from .relation_memory import PRIVATE_JUDGE_KEYS


MAX_QUERY_CHARS = 96
MAX_QUERY_TOKENS = 10
MAX_FIND_LIMIT = 12
MAX_GREP_QUERIES = 9
MAX_QUERIES_PER_GROUP = 3
MAX_QUERY_GROUPS = 3
MAX_OPEN_RECORDS = 6
MAX_SELECTED_RECORDS = 4
SNIPPET_CHARS = 240
MEMORY_RETRIEVAL_METHOD = (
    "memory_v2 structured LLM-controlled lexical DB find/grep; "
    "surface/relation/failure-risk query expansion; no embedding; no sample_id; no token-overlap fallback"
)
MEMORY_QUERY_GROUP_TYPES = ("surface", "relation", "failure_risk")
MEMORY_QUERY_GROUP_ALIASES = {
    "surface": "surface",
    "surface_query": "surface",
    "surface-query": "surface",
    "entity": "surface",
    "entity_visual": "surface",
    "entity-visual": "surface",
    "relation": "relation",
    "relation_query": "relation",
    "relation-query": "relation",
    "abstract_relation": "relation",
    "abstract-relation": "relation",
    "failure": "failure_risk",
    "failure_risk": "failure_risk",
    "failure-risk": "failure_risk",
    "failure_risk_query": "failure_risk",
    "failure-risk-query": "failure_risk",
    "risk": "failure_risk",
}

SEARCHABLE_FIELDS = [
    "polarity",
    "prompt_span",
    "elements",
    "relation_type",
    "relation_text",
    "attributes",
    "visual_evidence",
    "failure_type",
    "repair_hint",
]
FORBIDDEN_FIELDS = [
    "sample_id",
    "round_id",
    "round_index",
    "episode_id",
    "relation_id query",
    "full prompt",
    "judge_response",
    "raw_judge_response",
    "judge_reason",
    "judge_rationale",
    "judge_prompt",
    "judge_rubric",
    "score_breakdown",
    "scores_raw",
    "weighted_score",
]
QUERY_EXAMPLES = [
    "red cube",
    "contact shadow",
    "satba belt grip",
    "identity preservation",
    "no readable logo",
]


class MemoryQueryRejected(ValueError):
    pass


def memory_schema_payload() -> dict[str, Any]:
    return {
        "record_type": "active public V4 relation memory",
        "allowed_flow": "memory_schema -> memory_find/memory_grep -> memory_open -> memory_select -> write_rubric",
        "searchable_fields": list(SEARCHABLE_FIELDS),
        "forbidden_fields": list(FORBIDDEN_FIELDS),
        "query_rules": [
            "use short lexical words or phrases only",
            "use memory_v2 structured expansion: surface, relation, and failure_risk query groups",
            "surface queries name concrete entities and visual objects",
            "relation queries name abstract physical, spatial, identity, or causal constraints",
            "failure_risk queries name likely failure modes, wrong priors, or impossible states",
            "keep each group to 1-3 short phrases and at most 9 phrases total",
            "compare positive and negative records before selecting",
            "do not use sample ids, round ids, episode ids, relation ids, private judge fields, or the full prompt",
        ],
        "query_groups": {
            "surface": ["Moon surface", "flame"],
            "relation": ["combustion in vacuum", "oxidizer absence", "ignition constraint"],
            "failure_risk": ["physically impossible flame", "wrong environmental state", "default object prior"],
        },
        "examples": list(QUERY_EXAMPLES),
        "retrieval_method": MEMORY_RETRIEVAL_METHOD,
    }


def validate_memory_query(
    query: Any,
    *,
    input_prompt: str,
    sample_id: str,
    episode_id: str,
) -> str:
    text = " ".join(str(query or "").split())
    if not text:
        raise MemoryQueryRejected("memory query must be a non-empty short word or phrase")
    tokens = _tokens(text)
    if len(text) > MAX_QUERY_CHARS or len(tokens) > MAX_QUERY_TOKENS:
        raise MemoryQueryRejected(
            f"memory query is too long; use <= {MAX_QUERY_CHARS} chars and <= {MAX_QUERY_TOKENS} lexical tokens"
        )
    lowered = text.lower()
    forbidden_terms = {
        "sample_id",
        "sample id",
        "episode_id",
        "episode id",
        "round_id",
        "round id",
        "round_index",
        "relation_id",
        "relation id",
        "judge",
        "score",
        "hidden answer",
        "raw response",
    } | {str(key).lower() for key in PRIVATE_JUDGE_KEYS}
    hit = sorted(term for term in forbidden_terms if term and term in lowered)
    if hit:
        raise MemoryQueryRejected(f"memory query contains forbidden field/term: {hit[0]}")
    if re.search(r"\bround[\s_-]*\d+\b", lowered):
        raise MemoryQueryRejected("memory query must not contain a round id")
    if re.search(r"\bep[_-][a-z0-9_/-]+\b", lowered):
        raise MemoryQueryRejected("memory query must not contain an episode id")
    for label, value in (("sample id", sample_id), ("episode id", episode_id)):
        normalized = str(value or "").strip().lower()
        if len(normalized) >= 3 and re.search(rf"(?<![a-z0-9_]){re.escape(normalized)}(?![a-z0-9_])", lowered):
            raise MemoryQueryRejected(f"memory query must not contain the current {label}")
    if _looks_like_full_prompt(text, input_prompt):
        raise MemoryQueryRejected("memory query looks like the full prompt; split it into short visual concepts")
    return text


def normalize_memory_grep_groups(
    payload: dict[str, Any],
    *,
    input_prompt: str,
    sample_id: str,
    episode_id: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Parse legacy flat queries or memory_v2 structured query groups."""
    raw_groups = payload.get("query_groups")
    if raw_groups is None:
        raw_groups = payload.get("structured_queries")
    if raw_groups is None:
        flat_queries = [str(item) for item in payload.get("queries") or [] if str(item).strip()]
        if not flat_queries:
            raise MemoryQueryRejected("queries must contain at least one short query")
        if len(flat_queries) > MAX_GREP_QUERIES:
            raise MemoryQueryRejected(f"memory_grep accepts at most {MAX_GREP_QUERIES} total queries")
        return [
            {
                "type": "legacy",
                "queries": [
                    validate_memory_query(
                        query,
                        input_prompt=input_prompt,
                        sample_id=sample_id,
                        episode_id=episode_id,
                    )
                    for query in flat_queries
                ],
            }
        ], False

    groups: list[dict[str, Any]] = []
    if isinstance(raw_groups, dict):
        iterable = [{"type": key, "queries": value} for key, value in raw_groups.items()]
    elif isinstance(raw_groups, list):
        iterable = raw_groups
    else:
        raise MemoryQueryRejected("query_groups must be a list or object")

    total_queries = 0
    seen_group_types: set[str] = set()
    for raw_group in iterable:
        if not isinstance(raw_group, dict):
            raise MemoryQueryRejected("each query group must be an object")
        group_type = _normalize_query_group_type(raw_group.get("type") or raw_group.get("name") or raw_group.get("category"))
        if group_type in seen_group_types:
            raise MemoryQueryRejected(f"duplicate memory query group: {group_type}")
        raw_queries = [str(item) for item in raw_group.get("queries") or [] if str(item).strip()]
        if len(raw_queries) > MAX_QUERIES_PER_GROUP:
            raise MemoryQueryRejected(
                f"{group_type} query group accepts at most {MAX_QUERIES_PER_GROUP} queries"
            )
        validated = [
            validate_memory_query(
                query,
                input_prompt=input_prompt,
                sample_id=sample_id,
                episode_id=episode_id,
            )
            for query in raw_queries
        ]
        if validated:
            total_queries += len(validated)
            seen_group_types.add(group_type)
            groups.append({"type": group_type, "queries": validated})

    if not groups:
        raise MemoryQueryRejected("query_groups must contain at least one non-empty query group")
    if len(groups) > MAX_QUERY_GROUPS:
        raise MemoryQueryRejected(f"memory_grep accepts at most {MAX_QUERY_GROUPS} query groups")
    if total_queries > MAX_GREP_QUERIES:
        raise MemoryQueryRejected(f"memory_grep accepts at most {MAX_GREP_QUERIES} total queries")
    missing = [group_type for group_type in MEMORY_QUERY_GROUP_TYPES if group_type not in seen_group_types]
    if missing:
        raise MemoryQueryRejected(
            "memory_v2 query_groups must include surface, relation, and failure_risk groups; "
            f"missing: {missing}"
        )
    return groups, True


def find_relation_memory(
    agent_pool: AgentResourcePool,
    *,
    query: str,
    benchmark: str,
    limit: int,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or MAX_FIND_LIMIT), MAX_FIND_LIMIT))
    phrase = query.lower()
    query_tokens = _tokens(query)
    matches: list[tuple[float, float, dict[str, Any]]] = []
    seen: set[str] = set()
    for row in _iter_active_relation_rows(agent_pool, benchmark=benchmark):
        record = runtime_public_relation_row(row)
        memory_id = str(record.get("memory_id") or "")
        if not memory_id or memory_id in seen:
            continue
        haystack = _search_text(record)
        haystack_lower = haystack.lower()
        haystack_tokens = _tokens(haystack)
        token_match = bool(query_tokens) and query_tokens <= haystack_tokens
        if phrase not in haystack_lower and not token_match:
            continue
        seen.add(memory_id)
        record["_snippet"] = _snippet(record, query)
        matches.append((float(row.get("created_at") or 0.0), float(row.get("confidence") or 0.0), record))
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [_candidate_snippet(record) for _, _, record in matches[:limit]]


def merge_memory_candidates(by_group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in by_group:
        for query_result in group.get("by_query") or []:
            for candidate in query_result.get("candidates") or []:
                memory_id = str(candidate.get("memory_id") or "")
                if not memory_id or memory_id in seen:
                    continue
                seen.add(memory_id)
                merged.append(candidate)
    return merged


def open_relation_memory_records(
    cached_records: dict[str, dict[str, Any]],
    memory_ids: Iterable[str],
    *,
    allowed_ids: set[str],
) -> list[dict[str, Any]]:
    requested = [str(item) for item in memory_ids if str(item)]
    if len(requested) > MAX_OPEN_RECORDS:
        raise MemoryQueryRejected(f"memory_open can open at most {MAX_OPEN_RECORDS} records")
    invalid = [memory_id for memory_id in requested if memory_id not in allowed_ids]
    if invalid:
        raise MemoryQueryRejected(f"memory_open can only open ids returned by find/grep: {invalid}")
    out = []
    for memory_id in requested:
        record = cached_records.get(memory_id)
        if record is not None:
            out.append(_strip_internal_fields(record))
    return out


def sample_random_wrong_relation_memory(
    agent_pool: AgentResourcePool,
    *,
    benchmark: str,
    input_prompt: str,
    sample_id: str,
    count: int,
    seed: int,
    excluded_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Deterministically sample unrelated active records while preserving count."""
    target = max(0, min(int(count), MAX_SELECTED_RECORDS))
    if not target:
        return []
    excluded = {str(item) for item in excluded_ids if str(item)}
    prompt_tokens = {token for token in _tokens(input_prompt) if len(token) >= 3}
    strict: list[tuple[str, dict[str, Any]]] = []
    fallback: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for row in _iter_active_relation_rows(agent_pool, benchmark=benchmark):
        record = runtime_public_relation_row(row)
        memory_id = str(record.get("memory_id") or "")
        if not memory_id or memory_id in excluded or memory_id in seen:
            continue
        seen.add(memory_id)
        digest = hashlib.sha256(f"{seed}|{sample_id}|{memory_id}".encode("utf-8")).hexdigest()
        public_record = _strip_internal_fields(record)
        fallback.append((digest, public_record))
        record_tokens = {token for token in _tokens(_search_text(record)) if len(token) >= 3}
        if not (prompt_tokens & record_tokens):
            strict.append((digest, public_record))
    pool = strict if len(strict) >= target else fallback
    pool.sort(key=lambda item: item[0])
    return [record for _, record in pool[:target]]


def runtime_public_relation_row(row: dict[str, Any]) -> dict[str, Any]:
    elements = _decode_json_field(row.get("elements_json"), default=[])
    attributes = _decode_json_field(row.get("attributes_json"), default={})
    return {
        "memory_id": row.get("relation_id"),
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
        "record_status": row.get("record_status") or "active",
        "origin_sandbox_commit_id": row.get("origin_sandbox_commit_id") or "",
        "_created_at": row.get("created_at") or 0.0,
    }


def _iter_active_relation_rows(agent_pool: AgentResourcePool, *, benchmark: str) -> Iterable[dict[str, Any]]:
    dbs = [(agent_pool.db, ""), *[(db, str(getattr(db, "sandbox_commit_id", "") or "")) for db in agent_pool.inherited_dbs]]
    for db, origin_commit in dbs:
        try:
            columns = db._table_columns("evo_relation_records")
        except (sqlite3.Error, AttributeError):
            continue
        if not columns:
            continue
        status_where = "AND COALESCE(record_status, 'active') = 'active'" if "record_status" in columns else ""
        origin_select = "origin_sandbox_commit_id" if "origin_sandbox_commit_id" in columns else "'' AS origin_sandbox_commit_id"
        try:
            rows = db.conn.execute(
                f"""
                SELECT relation_id, benchmark, polarity, prompt_span, elements_json, relation_type,
                       relation_text, attributes_json, visual_evidence, failure_type, repair_hint,
                       confidence, created_at,
                       {'record_status' if 'record_status' in columns else "'active' AS record_status"},
                       {origin_select}
                FROM evo_relation_records
                WHERE lower(COALESCE(benchmark, '')) IN (lower(?), 'agentic_imagegen', 'all', '')
                  {status_where}
                ORDER BY created_at DESC
                LIMIT 5000
                """,
                (benchmark,),
            ).fetchall()
        except sqlite3.Error:
            continue
        for row in rows:
            item = dict(row)
            if not item.get("origin_sandbox_commit_id"):
                item["origin_sandbox_commit_id"] = origin_commit
            yield item


def _candidate_snippet(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "memory_id": record.get("memory_id"),
        "polarity": record.get("polarity"),
        "relation_type": record.get("relation_type"),
        "elements": record.get("elements") or [],
        "snippet": record.get("_snippet") or "",
        "confidence": record.get("confidence"),
        "_record": _strip_internal_fields(record),
    }


def _strip_internal_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("_")}


def _snippet(record: dict[str, Any], query: str) -> str:
    phrase = query.lower()
    query_tokens = _tokens(query)
    for key in ("relation_text", "visual_evidence", "repair_hint", "prompt_span", "failure_type"):
        text = str(record.get(key) or "")
        if not text:
            continue
        lower = text.lower()
        if phrase in lower or (bool(query_tokens) and query_tokens <= _tokens(text)):
            return _clip_snippet(text, lower.find(phrase) if phrase in lower else 0)
    return _clip_snippet(_search_text(record), 0)


def _clip_snippet(text: str, start: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= SNIPPET_CHARS:
        return text
    start = max(0, min(start, len(text) - 1))
    left = max(0, start - SNIPPET_CHARS // 3)
    right = min(len(text), left + SNIPPET_CHARS)
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return prefix + text[left:right].strip() + suffix


def _search_text(record: dict[str, Any]) -> str:
    pieces = [
        record.get("polarity") or "",
        record.get("prompt_span") or "",
        " ".join(str(item) for item in record.get("elements") or []),
        record.get("relation_type") or "",
        record.get("relation_text") or "",
        json.dumps(record.get("attributes") or {}, ensure_ascii=False, sort_keys=True),
        record.get("visual_evidence") or "",
        record.get("failure_type") or "",
        record.get("repair_hint") or "",
    ]
    return " ".join(str(piece) for piece in pieces if str(piece or "").strip())


def _looks_like_full_prompt(query: str, prompt: str) -> bool:
    prompt_text = " ".join(str(prompt or "").split())
    if not prompt_text:
        return False
    query_lower = query.lower()
    prompt_lower = prompt_text.lower()
    if query_lower == prompt_lower:
        return True
    if len(query) >= 80 and query_lower in prompt_lower:
        return True
    query_tokens = _tokens(query)
    prompt_tokens = _tokens(prompt_text)
    if len(query_tokens) < 6 or len(prompt_tokens) < 6:
        return False
    coverage = len(query_tokens & prompt_tokens) / max(len(query_tokens), 1)
    prompt_fraction = len(query_tokens) / max(len(prompt_tokens), 1)
    return coverage >= 0.75 and prompt_fraction >= 0.65


def _decode_json_field(value: Any, *, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return default
    return data


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_\u4e00-\u9fff]+", str(text).lower()) if len(token) > 1}


def _normalize_query_group_type(value: Any) -> str:
    key = str(value or "").strip().lower().replace(" ", "_")
    normalized = MEMORY_QUERY_GROUP_ALIASES.get(key)
    if not normalized:
        raise MemoryQueryRejected(
            f"unknown memory query group {value!r}; expected surface, relation, or failure_risk"
        )
    return normalized

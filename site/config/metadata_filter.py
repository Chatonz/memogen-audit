from __future__ import annotations

from typing import Any


JUDGE_ONLY_METADATA_KEYS = {
    "judge",
    "judge_sample",
    "raw_sample",
    "reference",
    "reference_text",
    "reference_txt",
    "reference_img",
    "reference_image",
    "reference_answer",
    "reasoning_img",
    "reasoning_img_op",
    "reasoning_wo_ins",
    "consistency_free",
}


def sanitize_agent_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_agent_metadata(item)
            for key, item in value.items()
            if str(key).strip().lower() not in JUDGE_ONLY_METADATA_KEYS
        }
    if isinstance(value, list):
        return [sanitize_agent_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_agent_metadata(item) for item in value]
    return value

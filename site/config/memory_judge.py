"""Pluggable multimodal judge prompts and message builders.

The benchmark runners use this module to swap judge behavior without editing a
benchmark's original prompt template in place.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]


EVOLUTION_JUDGE_PROMPT = r"""You are an independent multimodal judge for image generation and image editing self-evolution.

Your task is to decide whether a generated image correctly satisfies the original task.

You are NOT judging according to any specific benchmark’s official scoring rule. Instead, you should perform a strict, benchmark-agnostic evaluation based on the original instruction, provided references, provided evidence, and the generated image.

Your judgment will be used only as an internal self-evolution signal. It must not rely on official benchmark scores or previous benchmark judge results.

==================================================
Inputs
==================================================

You may receive some or all of the following:

- original_instruction:
  The original user task or benchmark prompt.

- enhanced_prompt:
  The prompt used to generate or edit the image.

- intent_analysis:
  A previous analysis of the task intent, if available.

- reference_images:
  Source images, target references, exemplars, or other visual references, if available.

- retrieved_evidence:
  Textual evidence, knowledge, metadata, or external facts retrieved before generation, if available.

- generated_image:
  The image to evaluate.

- task_metadata:
  Optional metadata such as category, domain, task type, or difficulty.

==================================================
Strict anti-leakage rule
==================================================

You must NOT use, infer, or refer to:

- official benchmark scores
- official benchmark pass/fail labels
- previous-round benchmark correctness labels
- official judge explanations
- hidden test annotations
- ground-truth checklist results not explicitly provided as part of the task
- any information saying whether this sample was previously correct or incorrect

If such information appears in the input, ignore it completely.

Evaluate only:
- the original instruction
- the generated image
- reference images, if provided
- retrieved evidence, if provided
- intent analysis, if provided
- enhanced prompt, only to check whether it preserved or distorted the original instruction

==================================================
Evaluation philosophy
==================================================

Be strict but fair.

Do not reward an image merely because it looks plausible or high quality.
Do not reward an image merely because it contains some relevant objects.
Do not assume the image satisfies a requirement unless it is visible, inferable from clear visual evidence, or supported by provided references/evidence.
Do not allow the enhanced prompt to override, simplify, or change the original instruction.

The original instruction is always the primary source of truth.

A generated image should PASS only if it satisfies all core requirements of the original task.

If any core requirement is missing, contradicted, or visually ambiguous, mark FAIL.

When uncertain, be conservative:
- If a strict evaluator could not verify that a core requirement is satisfied, mark it as ambiguous.
- Ambiguous core requirements should generally cause FAIL.
- Do not give credit for likely intention; judge the actual image.

==================================================
Step 1: Understand the task
==================================================

First, determine what the original instruction requires.

Identify:
- the main task goal
- required entities
- required attributes
- required actions or events
- required relations among entities
- required scene, style, or domain constraints
- required knowledge, if any
- required reasoning, if any
- required preservation of reference image content, if any
- forbidden changes or contradictions

If an enhanced prompt is provided, compare it against the original instruction.

Check whether the enhanced prompt:
- preserves the original task
- adds unsupported details
- removes important constraints
- changes the answer
- narrows the task to an easier version
- introduces contradictions or hallucinated assumptions

==================================================
Step 2: Extract atomic criteria
==================================================

Create a concise checklist of atomic criteria required for correctness.

Each criterion should be specific and independently judgeable.

Classify each criterion as one of:

- core:
  Required for the image to be correct.

- supporting:
  Helpful for quality, clarity, or completeness, but not strictly required.

- forbidden:
  Something that must not appear because it contradicts the task, violates the instruction, or corrupts required reference content.

For each criterion, judge its status as:

- satisfied:
  Clearly satisfied by the generated image or provided evidence.

- missing:
  Required element is absent.

- contradicted:
  The image shows the opposite or an incompatible result.

- ambiguous:
  The image may or may not satisfy the requirement, but it is not visually clear enough.

- not_applicable:
  The criterion does not apply after careful inspection.

Important:
- Do not create excessive checklist items.
- Prefer 3 to 8 atomic criteria.
- Focus on requirements that affect correctness.
- Do not penalize harmless extra details unless they conflict with the task.

==================================================
Step 3: Identify active reasoning types
==================================================

Determine which reasoning or knowledge types are actually relevant.

Possible active reasoning types:

- none
- world_knowledge
- cultural_knowledge
- scientific_knowledge
- historical_knowledge
- current_or_dynamic_knowledge
- temporal_reasoning
- spatial_or_geometric_reasoning
- geographic_reasoning
- relational_reasoning
- causal_or_physical_reasoning
- logical_reasoning
- mathematical_reasoning
- counting_or_comparison
- symbolic_or_text_reasoning
- metaphorical_or_abstract_reasoning
- reference_preservation
- image_editing_consistency

Only evaluate reasoning types that are relevant to the original instruction.

Do not penalize the image for irrelevant reasoning types.

==================================================
Step 4: Score four main dimensions
==================================================

Score each dimension from 0.0 to 1.0.

Use null only when the dimension is truly not applicable.

1. task_fidelity

Does the generated image preserve and answer the original task?

Consider:
- whether the image follows the original instruction
- whether the enhanced prompt changed the task
- whether the image answers a different or easier question
- whether important constraints were omitted or distorted

High score:
- The generated image faithfully follows the original instruction.

Low score:
- The image changes the task, ignores key constraints, or follows a hallucinated enhanced prompt rather than the original instruction.

2. core_requirement_satisfaction

Are all core atomic criteria satisfied?

High score:
- All core requirements are clearly satisfied.

Medium score:
- Some requirements are present but incomplete or ambiguous.

Low score:
- One or more core requirements are missing or contradicted.

Important:
If any core criterion is missing, contradicted, or ambiguous, this score should usually be below 0.8.

3. reasoning_knowledge_correctness

Does the image correctly satisfy the active reasoning or knowledge requirement?

Evaluate only the relevant reasoning types identified in Step 3.

Consider:
- temporal order, before/after, sequence, aging, historical era, or state transition
- spatial layout, containment, direction, geometry, map/geographic relation
- causal consequence, physical mechanism, transformation, reaction, damage, or process
- logic, math, counting, comparison, symbolic constraints
- world, cultural, scientific, historical, current, or domain-specific knowledge
- metaphorical or abstract interpretation, if required

High score:
- The required reasoning or knowledge is correct and visually grounded.

Medium score:
- The image partly reflects the required reasoning but lacks clarity or completeness.

Low score:
- The image shows relevant objects but fails the actual reasoning or knowledge requirement.

Use null only if the original task does not require any reasoning or knowledge beyond ordinary visual depiction.

4. visual_reference_quality

Is the image visually coherent, judgeable, and consistent with required references?

For all tasks, consider:
- recognizability
- visual coherence
- physical plausibility
- absence of severe artifacts
- whether the image is clear enough to evaluate

For reference-based or image-editing tasks, also consider:
- preservation of identity
- preservation of unchanged objects
- preservation of layout, style, background, and composition where required
- whether only the intended change was made
- whether the edit is plausible and integrated

High score:
- The image is clear, coherent, and preserves required reference content.

Medium score:
- The image is mostly judgeable but has artifacts or minor preservation issues.

Low score:
- The image is unclear, severely distorted, or corrupts required reference content.

==================================================
Step 5: Make final PASS / FAIL decision
==================================================

Use the following strict decision rule.

Mark PASS only if:
- task_fidelity >= 0.8
- core_requirement_satisfaction >= 0.8
- reasoning_knowledge_correctness >= 0.8, if applicable
- visual_reference_quality >= 0.7
- no core criterion is missing
- no core criterion is contradicted
- no core criterion is ambiguous in a way that affects correctness
- no forbidden criterion is present
- no critical failure exists

Mark FAIL if:
- the image answers a different task
- the enhanced prompt changes the original task in a correctness-relevant way
- any core requirement is missing
- any core requirement is contradicted
- any core requirement is visually ambiguous
- required reasoning or knowledge is wrong
- required reference content is unnecessarily changed
- the image is too unclear to verify correctness
- the image is plausible but does not demonstrate the required answer
- the image relies only on text labels when the visual scene itself should show the answer

Important:
Overall visual beauty or realism cannot compensate for failure on a core requirement.

==================================================
Step 6: Decide whether regeneration is needed
==================================================

Set regenerate = true if:
- final_judgment is FAIL
- any core criterion is missing, contradicted, or ambiguous
- the enhanced prompt likely caused the failure
- the image is not judgeable enough
- a new image would likely improve correctness

Set regenerate = false if:
- final_judgment is PASS
- issues are only minor and do not affect correctness

==================================================
Step 7: Give rewrite guidance
==================================================

If regenerate = true, provide concise and actionable rewrite guidance.

Guidance should:
- target only the failed core criteria
- preserve the original instruction
- avoid adding unsupported details
- avoid overfitting to any benchmark
- avoid mentioning official scores
- avoid revealing hidden labels
- make visual requirements explicit
- specify the reasoning or knowledge that must be visually represented

Do not give generic advice such as “make it better” or “improve quality.”
Do not suggest changing the task.
Do not introduce new facts unless they are supported by the original instruction or retrieved evidence.

==================================================
Output format
==================================================

Return valid JSON only.

Do not include markdown.
Do not include explanations outside the JSON.

Use this schema:

{
  "final_judgment": "PASS or FAIL",
  "pass": true,
  "confidence": 0.0,
  "overall_score": 0.0,

  "task_summary": "Brief summary of what the original instruction requires.",

  "enhanced_prompt_safety": {
    "status": "safe | risky | harmful | not_provided",
    "issues": [
      "Briefly describe any task-changing or hallucinated additions."
    ]
  },

  "active_reasoning_types": [
    "none"
  ],

  "atomic_criteria": [
    {
      "criterion": "A specific atomic requirement.",
      "type": "core | supporting | forbidden",
      "status": "satisfied | missing | contradicted | ambiguous | not_applicable",
      "severity": "critical | major | minor",
      "evidence": "Brief visual or evidence-based justification."
    }
  ],

  "dimension_scores": {
    "task_fidelity": 0.0,
    "core_requirement_satisfaction": 0.0,
    "reasoning_knowledge_correctness": null,
    "visual_reference_quality": 0.0
  },

  "critical_failures": [
    "List only failures that justify FAIL."
  ],

  "non_critical_issues": [
    "List minor issues that do not alone justify FAIL."
  ],

  "regenerate": true,

  "rewrite_guidance": [
    "Concrete guidance for the next prompt rewrite."
  ]
}

==================================================
Output consistency rules
==================================================

The JSON must be internally consistent.

If final_judgment is "PASS":
- pass must be true
- regenerate should usually be false
- critical_failures must be empty
- no core criterion may have status missing, contradicted, or ambiguous
- no forbidden criterion may have status satisfied

If final_judgment is "FAIL":
- pass must be false
- regenerate should usually be true
- critical_failures must explain the failure

overall_score should reflect correctness, not image beauty.

Suggested scoring:
- 0.90 to 1.00: clearly correct
- 0.75 to 0.89: mostly correct but with minor uncertainty or minor non-critical issues
- 0.50 to 0.74: partially correct but fails at least one important requirement
- 0.25 to 0.49: major failure
- 0.00 to 0.24: unrelated, contradictory, or unjudgeable"""


def _load_prompt_file(relative_path: str, fallback: str) -> str:
    path = PROJECT_ROOT / relative_path
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return fallback
    return text or fallback


EVOLUTION_JUDGE_CALIBRATED_V2_PROMPT = _load_prompt_file(
    "prompts/evolution_judge_calibrated_v2.txt",
    EVOLUTION_JUDGE_PROMPT,
)

EVOLUTION_JUDGE_WISE_STRICT_V1_PROMPT = _load_prompt_file(
    "prompts/evolution_judge_wise_strict_v1.txt",
    EVOLUTION_JUDGE_CALIBRATED_V2_PROMPT,
)

EVOLUTION_JUDGE_MIND_STRICT_V1_PROMPT = _load_prompt_file(
    "prompts/evolution_judge_mind_strict_v1.txt",
    EVOLUTION_JUDGE_CALIBRATED_V2_PROMPT,
)


LEGACY_WISE_SYSTEM_PROMPT = "You are a professional text-to-image quality auditor."

WISE_VERIFIED_OFFICIAL_SYSTEM_PROMPT = (
    "You are a professional text-to-image quality auditor. "
    "Evaluate the image strictly according to the protocol."
)


def _wise_verified_official_user_prompt(sample: Dict[str, Any]) -> str:
    """Return the user prompt from the official WISE_Verified vllm_eval.py."""
    return f"""Please evaluate this generated image for the WISE benchmark and return ONLY one binary score.

# WISE Text-to-Image Evaluation Protocol

## What WISE Is Evaluating
WISE is a knowledge-intensive text-to-image benchmark. Many prompts do not directly state the final visual answer. Instead, the model must use commonsense, cultural, scientific, spatial, or temporal knowledge to infer what should appear in the image.

Your job is not to judge whether the image is beautiful. Your job is to judge whether the generated image correctly realizes the knowledge-based meaning of the prompt and is visually usable.

## Input Fields

**PROMPT**
The original text-to-image prompt given to the image generation model. It may contain an implicit clue rather than the explicit final answer.

**EXPLANATION**
The reference interpretation used for judging. It explains the intended answer, the required knowledge reasoning chain, and the visual evidence that should appear in a correct image. Treat EXPLANATION as the ground-truth judging guide.

For example:
- If PROMPT says "the round pastry commonly shared during Mid-Autumn Festival family gatherings", EXPLANATION may specify mooncakes. A correct image should show mooncakes, not just any festival food.
- If PROMPT says "a plant kept for many days beside a bright one-sided window", EXPLANATION may specify phototropism. A correct image should show the plant bending toward the light source.
- If PROMPT says "a street in New York when it is midnight in Beijing", EXPLANATION may specify the corresponding local time and expected lighting/activity. A correct image should reflect that inferred local time, not simply show Beijing or generic night.

## How To Judge

Evaluate the image using these checks:
1. Does the image contain the main objects or scene required by the PROMPT?
2. Does it satisfy the intended knowledge-based answer described in the EXPLANATION?
3. Are important relations correct, such as spatial layout, temporal state, physical effect, biological behavior, cultural object, or scientific phenomenon?
4. Is the image visually usable for judging, without obvious collapse, severe deformation, unreadable main objects, or major artifacts?

## Binary Score

**Score: 1**
Give 1 only when both conditions are met:
- The image is semantically correct according to both PROMPT and EXPLANATION.
- The image has no obvious generation failure that prevents reliable judging.

Minor aesthetic weakness, ordinary composition, non-photorealistic style, or lack of artistic beauty should not by itself cause rejection if the semantic target is correct and the image is clear.

**Score: 0**
Give 0 if any of the following applies:
- The image misses the intended answer in EXPLANATION.
- The image only follows surface words in PROMPT but fails the required knowledge inference.
- Key objects, attributes, states, behaviors, or relations are missing or wrong.
- The image contradicts the prompt or explanation.
- The main visual evidence is ambiguous enough that a human judge could not confidently verify correctness.
- The image has obvious visual collapse, severe deformation, garbled main objects, impossible structure, or artifacts that interfere with evaluation.

If there is serious doubt, return 0.

## Output Format

Return exactly one line and nothing else:

Score: 0

or

Score: 1

---

PROMPT: "{sample['Prompt']}"
EXPLANATION: "{sample['Explanation']}"

Return only `Score: 0` or `Score: 1`."""


def normalize_profile_name(profile: str | None) -> str:
    name = (profile or "wise_legacy_binary").strip().lower().replace("-", "_")
    aliases = {
        "legacy": "wise_legacy_binary",
        "wise": "wise_legacy_binary",
        "wise_legacy": "wise_legacy_binary",
        "binary": "wise_legacy_binary",
        "wise_official": "wise_verified_official",
        "wise_verified": "wise_verified_official",
        "verified": "wise_verified_official",
        "evolution": "evolution_json",
        "self_evolution": "evolution_json",
        "self_evolution_json": "evolution_json",
        "agnostic": "evolution_json",
        "benchmark_agnostic": "evolution_json",
        "json": "evolution_json",
        "calibrated": "evolution_calibrated_v2",
        "calibrated_v2": "evolution_calibrated_v2",
        "evolution_v2": "evolution_calibrated_v2",
        "evolution_json_v2": "evolution_calibrated_v2",
        "evolution_calibrated": "evolution_calibrated_v2",
        "wise_strict": "evolution_wise_strict_v1",
        "wise_strict_v1": "evolution_wise_strict_v1",
        "evolution_wise_strict": "evolution_wise_strict_v1",
        "evolution_wise": "evolution_wise_strict_v1",
        "mind": "evolution_mind_strict_v1",
        "mindbench": "evolution_mind_strict_v1",
        "mind_strict": "evolution_mind_strict_v1",
        "mind_strict_v1": "evolution_mind_strict_v1",
        "evolution_mind": "evolution_mind_strict_v1",
        "evolution_mind_strict": "evolution_mind_strict_v1",
    }
    return aliases.get(name, name)


def is_json_profile(profile: str | None) -> bool:
    return normalize_profile_name(profile) in {
        "evolution_json",
        "evolution_calibrated_v2",
        "evolution_wise_strict_v1",
        "evolution_mind_strict_v1",
    }


def profile_metadata(profile: str | None) -> Dict[str, Any]:
    name = normalize_profile_name(profile)
    return {
        "profile": name,
        "output_format": "json" if is_json_profile(name) else "binary_score",
        "description": (
            "Strict WISE-oriented self-evolution JSON judge"
            if name == "evolution_wise_strict_v1"
            else "Strict MindBench checklist self-evolution JSON judge"
            if name == "evolution_mind_strict_v1"
            else "Official WISE_Verified binary judge prompt"
            if name == "wise_verified_official"
            else
            "Calibrated benchmark-agnostic self-evolution JSON judge"
            if name == "evolution_calibrated_v2"
            else "Benchmark-agnostic self-evolution JSON judge"
            if name == "evolution_json"
            else "Original WISE-style binary judge"
        ),
    }


def encode_image_url(image_path: str | Path, detail: str = "high") -> Dict[str, Any]:
    path = Path(image_path)
    with path.open("rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{mime};base64,{b64}",
            "detail": detail,
        },
    }


def compact_evidence(item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not item:
        return {}
    evidence: Dict[str, Any] = {}
    for key in (
        "search_queries",
        "image_queries",
        "memory_knowledge",
        "retrieval_mode",
        "ood_score",
        "ood_raw",
        "adjusted_ood",
        "p_web",
        "did_search",
    ):
        value = item.get(key)
        if value not in (None, "", [], {}):
            evidence[key] = value
    wit = item.get("wit_results") or []
    if wit:
        evidence["retrieved_captions"] = [
            {
                "caption": row.get("caption"),
                "source": row.get("page_title"),
                "similarity": row.get("match_similarity"),
            }
            for row in wit[:5]
        ]
    return evidence


def _metadata_from_sample(sample: Dict[str, Any], item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    item = item or {}
    return {
        "benchmark_name": "WISE",
        "sample_id": sample.get("prompt_id", item.get("id")),
        "category": sample.get("Category", item.get("category")),
        "subcategory": sample.get("Subcategory", item.get("subcategory")),
        "has_reference_images": bool(item.get("has_refs") or item.get("ref_images")),
        "used_image_editing": bool(item.get("use_edit")),
        "retrieval_mode": item.get("retrieval_mode"),
    }


def _valid_reference_paths(paths: Iterable[str | Path], max_refs: int) -> List[Path]:
    out: List[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.exists() and path.is_file():
            out.append(path)
        if len(out) >= max_refs:
            break
    return out


def build_wise_legacy_messages(
    sample: Dict[str, Any],
    image_path: str | Path,
    *,
    item: Optional[Dict[str, Any]] = None,
    final_line: bool = False,
) -> List[Dict[str, Any]]:
    if final_line:
        system = (
            "You are a strict visual benchmark judge. Reason about the image and target carefully, "
            "then put the final binary decision on the last line as exactly: Final Score: 0 or Final Score: 1."
        )
        prompt = f"""Evaluate whether the image satisfies this WISE target.
Target: {sample['Prompt']}
Criterion: {sample['Explanation']}
Think through the visible evidence first. Use Score 1 only if the image clearly satisfies the criterion; otherwise use Score 0.
End with exactly one final line: Final Score: <0 or 1>."""
    else:
        system = LEGACY_WISE_SYSTEM_PROMPT
        prompt = f"""Evaluate this generated image for the WISE benchmark.

PROMPT: "{sample['Prompt']}"
EXPLANATION: "{sample['Explanation']}"

Score: 1 if the image correctly realizes the prompt and explanation and is visually usable.
Score: 0 if key objects, relations, world knowledge, or realism are wrong or ambiguous.

Return ONLY: Score: 0 or Score: 1"""
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                encode_image_url(image_path),
            ],
        },
    ]


def build_wise_verified_official_messages(
    sample: Dict[str, Any],
    image_path: str | Path,
) -> List[Dict[str, Any]]:
    """Build messages byte-for-byte equivalent to WISE_Verified vllm_eval.py."""
    path = Path(image_path)
    with path.open("rb") as handle:
        image_base64 = base64.b64encode(handle.read()).decode()
    return [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": WISE_VERIFIED_OFFICIAL_SYSTEM_PROMPT,
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": _wise_verified_official_user_prompt(sample),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                },
            ],
        },
    ]


def build_evolution_json_messages(
    sample: Dict[str, Any],
    image_path: str | Path,
    *,
    item: Optional[Dict[str, Any]] = None,
    include_refs: bool = True,
    max_refs: int = 3,
    system_prompt: str = EVOLUTION_JUDGE_PROMPT,
) -> List[Dict[str, Any]]:
    item = item or {}
    payload = {
        "original_instruction": sample.get("Prompt", item.get("prompt", "")),
        "target_explanation": sample.get("Explanation", item.get("explanation", "")),
        "enhanced_prompt": item.get("enhanced_prompt", ""),
        "intent_analysis": item.get("intent_analysis"),
        "retrieved_evidence": compact_evidence(item),
        "task_metadata": _metadata_from_sample(sample, item),
        "reference_images": "attached after this JSON, if provided",
        "generated_image": "attached as the final image",
    }
    content: List[Dict[str, Any]] = [
        {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
    ]
    if include_refs:
        for idx, ref_path in enumerate(_valid_reference_paths(item.get("ref_images") or [], max_refs), start=1):
            content.append({"type": "text", "text": f"reference_image_{idx}: {ref_path}"})
            content.append(encode_image_url(ref_path))
    content.append({"type": "text", "text": f"generated_image: {image_path}"})
    content.append(encode_image_url(image_path))
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]


def build_wise_judge_messages(
    sample: Dict[str, Any],
    image_path: str | Path,
    *,
    item: Optional[Dict[str, Any]] = None,
    profile: str | None = None,
    include_refs: bool = True,
    max_refs: int = 3,
    legacy_final_line: bool = False,
) -> List[Dict[str, Any]]:
    name = normalize_profile_name(profile)
    if name == "wise_verified_official":
        return build_wise_verified_official_messages(sample, image_path)
    if name == "wise_legacy_binary":
        return build_wise_legacy_messages(
            sample,
            image_path,
            item=item,
            final_line=legacy_final_line,
        )
    if name in {"evolution_json", "evolution_calibrated_v2", "evolution_wise_strict_v1"}:
        return build_evolution_json_messages(
            sample,
            image_path,
            item=item,
            include_refs=include_refs,
            max_refs=max_refs,
            system_prompt=(
                EVOLUTION_JUDGE_WISE_STRICT_V1_PROMPT
                if name == "evolution_wise_strict_v1"
                else
                EVOLUTION_JUDGE_CALIBRATED_V2_PROMPT
                if name == "evolution_calibrated_v2"
                else EVOLUTION_JUDGE_PROMPT
            ),
        )
    raise ValueError(f"unknown judge profile: {profile}")


def extract_json(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty judge response")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_json_judgment(judgment: Dict[str, Any]) -> Dict[str, Any]:
    final = str(judgment.get("final_judgment", "")).strip().upper()
    passed = judgment.get("pass")
    if not isinstance(passed, bool) and isinstance(judgment.get("all_pass"), bool):
        passed = bool(judgment["all_pass"])
    if not isinstance(passed, bool):
        passed = final == "PASS"
    if final not in {"PASS", "FAIL"}:
        final = "PASS" if passed else "FAIL"
    judgment["final_judgment"] = final
    judgment["pass"] = bool(passed)
    return judgment


def parse_binary_score(text: str) -> int:
    raw = (text or "").strip()
    match = re.search(r"Final\s+Score\*{0,2}\s*[:：]\s*([01])\b", raw, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"\*{0,2}Score\*{0,2}\s*[::：]?\s*([01])\b", raw, re.IGNORECASE)
    if match:
        return int(match.group(1))
    nums = re.findall(r"(?m)^\s*([01])\s*$", raw)
    if nums:
        return int(nums[-1])
    loose = re.findall(r"\b([01])\b", raw)
    return int(loose[-1]) if loose else 0


def parse_judge_response(text: str, profile: str | None) -> Dict[str, Any]:
    if is_json_profile(profile):
        judgment = normalize_json_judgment(extract_json(text))
        return {
            "score": 1 if judgment["pass"] else 0,
            "pass": judgment["pass"],
            "judgment": judgment,
            "raw": text,
        }
    score = parse_binary_score(text)
    return {
        "score": score,
        "pass": bool(score),
        "judgment": None,
        "raw": text,
    }

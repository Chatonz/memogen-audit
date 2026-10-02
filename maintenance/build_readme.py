#!/usr/bin/env python3
"""Render the Markdown results from the exported experiment records."""
from __future__ import annotations

import argparse
import gzip
import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = [('2', 'Ssireum'), ('146', 'Shamrock'), ('718', 'Venus flytrap')]


def load(path):
    return json.loads(path.read_text())


def cell(value):
    return html.escape(str(value), quote=False).replace('|', '&#124;').replace('\n', '<br>')


def table(headers, rows):
    return '\n'.join([
        '| ' + ' | '.join(headers) + ' |',
        '| ' + ' | '.join('---' for _ in headers) + ' |',
        *['| ' + ' | '.join(str(v) for v in row) + ' |' for row in rows],
    ])


def ratio(n, total):
    return f'{n:,}/{total:,} ({n / total:.1%})'


def verdict(value):
    return {0: 'Fail', 1: 'Pass'}.get(value, '—')


def evaluation_name(round_number):
    return f'WISE · Round {round_number}'


def round_links(prefix=''):
    return ' · '.join(f'[Round {n}]({prefix}round_{n:02d}.md)' for n in (1, 2, 3))


def build(root):
    site = root / 'site'
    rows = load(site / 'data/index.json')
    summary = load(site / 'data/summary.json')
    protocol = load(site / 'data/protocol.json')
    rounds = summary['rounds']
    by_key = {r['key']: r for r in rows}
    files = {}

    results = table(
        ['Round', 'New images', 'Memory judge: pass', 'WISE: pass'],
        [(f'[R{r["round"]}](results/round_{r["round"]:02d}.md)', f'{r["n"]:,}',
          ratio(r['judge_pass'], r['n']), ratio(r['official_pass'], r['n'])) for r in rounds],
    )
    agreement = table(
        ['Round', 'Both pass', 'Both fail', 'Judge pass / WISE fail', 'Judge fail / WISE pass', 'Agreement', "Cohen’s κ"],
        [(f'R{r["round"]}', *[r['official_agreement'][k] for k in
          ['both_pass', 'both_fail', 'judge_only_pass', 'reference_only_pass']],
          f'{r["official_agreement"]["agreement"]:.1%}', f'{r["official_agreement"]["kappa"]:.3f}') for r in rounds],
    )
    examples = []
    for sid, title in EXAMPLES:
        images = []
        for n in (1, 2, 3):
            r = by_key.get(f'r{n}-{sid}')
            if r:
                images.append(f'<a href="results/examples/wise_{int(sid):04d}.md#round-{n}"><img src="site/{r["image"]}" width="220" alt="{title}, round {n}"></a><br>{verdict(r["judge"])} / {verdict(r["official"])}')
            else:
                images.append('Retained from R2')
        examples.append([f'[{title} · #{sid}](results/examples/wise_{int(sid):04d}.md)', *images])
    qualitative = table(['Task', 'Round 1', 'Round 2', 'Round 3'], examples)
    memory = table(
        ['Round', 'Selected records', 'Own task', 'Other task', 'Negative records'],
        [(f'R{r["round"]}', r['memory_own'] + r['memory_other'],
          ratio(r['memory_own'], r['memory_own'] + r['memory_other']),
          ratio(r['memory_other'], r['memory_own'] + r['memory_other']),
          ratio(r['memory_negative'], r['memory_own'] + r['memory_other'])) for r in rounds[1:]],
    )
    transfer = table(
        ['Run', 'Targets', 'Paired-source records', 'Other-source records', 'Targets using paired-source memory'],
        [(f'All-memory v{i}', r['target_n'], r['counts']['paired_source'], r['counts']['other_source'],
          ratio(r['targets_with_paired_source'], r['target_n'])) for i, r in enumerate(summary['paired_source_runs'], 1)],
    )
    search = table(
        ['Round', 'Text-search calls', 'Returned results', 'Episodes with screening matches'],
        [(f'R{n}', f'{sum(r["web_calls"] for r in rows if r["round"] == n):,}',
          f'{sum(r["web_results"] for r in rows if r["round"] == n):,}',
          sum(r['search_candidates'] > 0 for r in rows if r['round'] == n)) for n in (1, 2, 3)],
    )
    files['README.md'] = f'''# MemoGen — Experimental Results

Results for **{summary['unique_tasks']:,} WISE tasks** across three rounds, comprising **{summary['episodes']:,} generated image instances**.

{round_links('results/')} · [Image comparisons](#image-comparisons) · [Experimental setup](results/experimental_setup.md) · [Download results](site/downloads/episodes.csv)

## WISE results

R1 evaluates all 1,000 tasks. R2 and R3 generate new images for the 122 and 65 tasks that failed the preceding memory-judge decision; passing images are retained. Rates below use each round's newly generated images as the denominator.

{results}

The GPT-5.5 memory judge assigns binary decisions for memory admission and round routing. Generated images are scored using the WISE evaluation protocol. [Experimental setup](results/experimental_setup.md).

<details>
<summary>Memory-judge / WISE agreement</summary>

{agreement}

[R1 per-image alignment](site/downloads/wise_round_01_scores.csv)

</details>

## Image comparisons

Labels below each image show **memory judge / WISE**. Each task links to its generation prompts, judge decisions and selected memories.

{qualitative}

## Memory retrieval

Own-task records come from earlier attempts at the same task; other-task records come from a different WISE task. Counts refer to selected-record occurrences across generation instances.

{memory}

[Memory provenance CSV](site/downloads/memory_provenance.csv)

### Analogical transfer

Each run contains 120 target tasks. Paired-source records originate from the source task used to construct a target; other-source records originate from other tasks.

{transfer}

[Target prompts, source mappings and selected records](site/data/transfer.json)

## Search records

The runs contain {sum(r['web_calls'] for r in rows):,} text-search calls and {sum(r['web_results'] for r in rows):,} returned results. Screening checks known benchmark markers and exact 12-word spans from WISE prompts and explanations in returned text.

{search}

[Queries and screening results](site/downloads/search_screening.json)

## Materials

| Material | Contents |
| --- | --- |
| [Instance index](results/README.md) | All 1,187 instances, images and per-instance records |
| [Episode CSV](site/downloads/episodes.csv) | Prompts, categories, decisions and retrieval counts |
| [Experimental setup](results/experimental_setup.md) | Models, evaluation versions, prompts and memory rules |
| [Round manifests](site/config) | Run configurations for R1–R3 |
| [Instance records](site/data/episodes) | Generation prompts, judge outputs, memory selection, search results and tool-call records in JSON.gz |
| [Checksums](site/downloads/checksums.json) | SHA256 hashes of data and configuration files |
| [Build instructions](maintenance/README.md) | Regenerate the Markdown results and validate the export |

## Transfer benchmark

The analogical-transfer runs use 120 held-out WISE-style target tasks, sampled with 20 tasks per category (Cultural knowledge, Time, Space, Biology, Physical Knowledge, Chemistry). Each target keeps the reasoning relation of a WISE source task but changes the concrete instance, so the target prompt does not appear in WISE. The explanation states the intended answer and the visual criteria used for WISE-style scoring.

| File | Contents |
| --- | --- |
| [wise_transfer_120.json](transfer_bench/wise_transfer_120.json) | `prompt_id`, `category`, `subcategory`, `prompt`, `explanation` |
| [wise_transfer_120.csv](transfer_bench/wise_transfer_120.csv) | Same fields in CSV |
'''

    files['results/README.md'] = f'''# Instance index

[Results](../README.md) · [Experimental setup](experimental_setup.md)

{table(['Round', 'Instances', 'Index'], [(f'R{r["round"]}', f'{r["n"]:,}', f'[Browse Round {r["round"]}](round_{r["round"]:02d}.md)') for r in rounds])}

Each row links to its image and complete JSON.gz record. The record contains the generation prompt, judge response, WISE evaluation, selected memories, search results and tool calls.

## Image comparisons

{chr(10).join(f'- [{title} · WISE #{sid}](examples/wise_{int(sid):04d}.md)' for sid, title in EXAMPLES)}

## Data

- [All instances (CSV)](../site/downloads/episodes.csv)
- [Memory provenance (CSV)](../site/downloads/memory_provenance.csv)
- [R1 evaluation alignment (CSV)](../site/downloads/wise_round_01_scores.csv)
- [Machine-readable index (JSON)](../site/data/index.json)
'''

    for rnd in (1, 2, 3):
        rr = sorted((r for r in rows if r['round'] == rnd), key=lambda r: int(r['id']))
        header = f'''# Round {rnd}

[Results](../README.md) · {round_links()}

**{len(rr):,} images** · Memory-judge pass: **{ratio(sum(r['judge'] for r in rr), len(rr))}** · WISE pass: **{ratio(sum(r['official'] for r in rr), len(rr))}**

Evaluation: [{evaluation_name(rnd)}](experimental_setup.md#evaluation). Memory columns count selected records.
'''
        sections = [header]
        for category in sorted({r['category'] for r in rr}):
            sections.append(f'## {category}\n\n' + table(
                ['ID / image', 'Task', 'Judge', 'WISE', 'Own / other memory', 'Record'],
                [(f'[{r["id"]}](../site/{r["image"]})', cell(r['prompt']), verdict(r['judge']),
                  verdict(r['official']), f'{r["own_memory"]} / {r["other_memory"]}' if rnd > 1 else '—',
                  f'[JSON.gz](../site/data/episodes/{r["key"]}.json.gz)') for r in rr if r['category'] == category]))
        files[f'results/round_{rnd:02d}.md'] = '\n\n'.join(sections) + '\n'

    for sid, title in EXAMPLES:
        sections = [f'# {title} · WISE #{sid}\n\n[Results](../../README.md) · [Instance index](../README.md)\n\n> {cell(by_key[f"r1-{sid}"]["prompt"])}']
        for rnd in (1, 2, 3):
            key = f'r{rnd}-{sid}'
            if key not in by_key:
                continue
            d = json.loads(gzip.decompress((site / f'data/episodes/{key}.json.gz').read_bytes()))
            sections.append(f'''## Round {rnd}

<img src="../../site/{d['image']}" width="480" alt="{title}, round {rnd}">

**Memory judge: {verdict(d['judge'])} · WISE: {verdict(d['official'])}**

{d['generation_calls']} generation calls · {d['own_memory']} own-task / {d['other_memory']} other-task selected memories. Evaluation: [{evaluation_name(rnd)}](../experimental_setup.md#evaluation).

### Generation prompt

{cell(d['generated_prompt'])}

### Memory-judge decision

<details>
<summary>Structured judge response</summary>

```json
{json.dumps(d['judge_detail'].get('judge_response', d['judge_detail']), ensure_ascii=False, indent=2)}
```

</details>
''')
            if d['memory']['selected']:
                selected = []
                for m in d['memory']['selected']:
                    record = m['record'] or {}
                    source_key = f'r{record.get("round_index")}-{record.get("sample_id")}'
                    source = f'R{record.get("round_index")} / #{record.get("sample_id")}'
                    if source_key in by_key:
                        source = f'[{source}](../../site/{by_key[source_key]["image"]})'
                    selected.append([source, cell(record.get('polarity', '')), cell(record.get('relation_text', '')), cell(record.get('repair_hint', ''))])
                sections.append('### Selected memories\n\n' + table(['Source', 'Polarity', 'Relation', 'Repair hint'], selected))
            sections.append(f'[Complete instance record](../../site/data/episodes/{key}.json.gz) · [Round {rnd} index](../round_{rnd:02d}.md)')
        files[f'results/examples/wise_{int(sid):04d}.md'] = '\n\n'.join(sections) + '\n'

    j = protocol['judge']
    files['results/experimental_setup.md'] = f'''# Experimental setup

[Results](../README.md) · [Instance index](README.md)

## Evaluation

| Component | Setting |
| --- | --- |
| Dataset | WISE, 1,000 tasks |
| Controller / reference VLM | GPT-5.5 |
| Memory judge | GPT-5.5; binary pass/fail decisions |
| Judge inputs | Task prompt, target explanation and generated image |
| Judge decision | Parsed JSON `pass` / `final_judgment` |
| R1 WISE evaluation | Qwen3.5-35B-A3B; WISE protocol, revision `eb51174` |
| R1 evaluator decoding | Temperature 0; thinking disabled; maximum 500 tokens |
| R2 / R3 WISE evaluation | WISE protocol; scores aligned to the generated images in each round |
| R2 / R3 routing | Generate new images for previous-round memory-judge failures; retain passing images |
| Search | Live web text and image retrieval |

[Evaluation versions and run configuration](../site/data/protocol.json)

### Judge configuration

[Judge prompt](../site/config/memory_judge_prompt.txt) · [Prompt builder and parser](../site/config/memory_judge.py)

Prompt SHA256: `{j['prompt_sha256']}`.

The runner snapshot sets judge temperature to {j['temperature']['value']}; the configuration default is {j['max_completion_tokens']['value']:,} output tokens. Historical request-level overrides are unrecorded. The run manifests and instance records provide the recorded settings.

## Memory

| Operation | Rule |
| --- | --- |
| Admission | Binary judge decision sets positive/negative polarity; relation text, visual evidence and element/attribute validation are required |
| Confidence threshold | 0.2 in the code snapshot |
| Retrieval | Lexical query → open → select; candidates ordered by creation time and confidence |
| Query budget | 96 characters / 10 tokens |
| Retrieval budget | Up to 12 candidates, 6 opened records and 4 selected records |
| Positive memory | Reusable strategies |
| Negative memory | Failure descriptions and repair hints |
| R1 retrieval records | Legacy context; structured query/open/select events begin in R2 |

[Memory admission code](../site/config/memory_admission.py) · [Retrieval code](../site/config/memory_retrieval.py) · [Selected-record provenance](../site/downloads/memory_provenance.csv)

## Analogical transfer

| Run | Targets | Memory |
| --- | --- | --- |
| All-memory v1 | 120 | All-memory retrieval |
| All-memory v2 | 120 | All-memory retrieval |

[Target prompts and source records](../site/data/transfer.json)

## Search screening

Returned search text is matched against benchmark markers and exact 12-word spans from WISE prompts and explanations. Query headers are excluded. The reported measure is the number of instances with matching returned text.

[Screening records](../site/downloads/search_screening.json)

## Files

- [R1 manifest](../site/config/round_01.json)
- [R2 manifest](../site/config/round_02.json)
- [R3 manifest](../site/config/round_03.json)
- [Full protocol metadata](../site/data/protocol.json)
- [Data and configuration checksums](../site/downloads/checksums.json)

Displayed images are WebP previews. Original-image dimensions and SHA256 hashes are included in each instance record.
'''
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check that Markdown matches the exported data')
    args = parser.parse_args()
    files = build(ROOT)
    stale = []
    for name, content in files.items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_text() != content:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if stale:
        parser.exit(1, 'Regenerate Markdown: ' + ', '.join(stale) + '\n')
    print(f'{"Checked" if args.check else "Generated"} {len(files)} Markdown files.')


if __name__ == '__main__':
    main()

# MemoGen — Experimental Results

Results for **1,000 WISE tasks** across three rounds, comprising **1,187 generated image instances**.

[Round 1](results/round-1.md) · [Round 2](results/round-2.md) · [Round 3](results/round-3.md) · [Image comparisons](#image-comparisons) · [Experimental settings](results/settings.md) · [Download results](site/downloads/episodes.csv)

## WISE results

R1 evaluates all 1,000 tasks. R2 and R3 generate new images for the 122 and 65 tasks that failed the preceding memory-judge decision; passing images are retained. Rates below use each round's newly generated images as the denominator.

| Round | New images | Memory judge: pass | WISE: pass |
| --- | --- | --- | --- |
| [R1](results/round-1.md) | 1,000 | 878/1,000 (87.8%) | 925/1,000 (92.5%) |
| [R2](results/round-2.md) | 122 | 57/122 (46.7%) | 74/122 (60.7%) |
| [R3](results/round-3.md) | 65 | 15/65 (23.1%) | 39/65 (60.0%) |

The memory judge uses GPT-5.5 with `evolution_wise_strict_v1`. WISE scores use the September 19 evaluation for R1 and the July evaluations for R2/R3. [Evaluation settings](results/settings.md#evaluation).

<details>
<summary>Memory-judge / WISE agreement</summary>

| Round | Both pass | Both fail | Judge pass / WISE fail | Judge fail / WISE pass | Agreement | Cohen’s κ |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | 857 | 54 | 21 | 68 | 91.1% | 0.502 |
| R2 | 49 | 40 | 8 | 25 | 73.0% | 0.466 |
| R3 | 13 | 24 | 2 | 26 | 56.9% | 0.222 |

[R1 per-image alignment](site/downloads/official_r1_alignment.csv)

</details>

## Image comparisons

Labels below each image show **memory judge / WISE**. Each task links to its generation prompts, judge decisions and selected memories.

| Task | Round 1 | Round 2 | Round 3 |
| --- | --- | --- | --- |
| [Ssireum · #2](results/examples/2.md) | <a href="results/examples/2.md#round-1"><img src="site/images/view/r1-2.webp" width="220" alt="Ssireum, round 1"></a><br>Fail / Pass | <a href="results/examples/2.md#round-2"><img src="site/images/view/r2-2.webp" width="220" alt="Ssireum, round 2"></a><br>Pass / Pass | Retained from R2 |
| [Shamrock · #146](results/examples/146.md) | <a href="results/examples/146.md#round-1"><img src="site/images/view/r1-146.webp" width="220" alt="Shamrock, round 1"></a><br>Fail / Fail | <a href="results/examples/146.md#round-2"><img src="site/images/view/r2-146.webp" width="220" alt="Shamrock, round 2"></a><br>Pass / Fail | Retained from R2 |
| [Venus flytrap · #718](results/examples/718.md) | <a href="results/examples/718.md#round-1"><img src="site/images/view/r1-718.webp" width="220" alt="Venus flytrap, round 1"></a><br>Fail / Fail | <a href="results/examples/718.md#round-2"><img src="site/images/view/r2-718.webp" width="220" alt="Venus flytrap, round 2"></a><br>Fail / Fail | <a href="results/examples/718.md#round-3"><img src="site/images/view/r3-718.webp" width="220" alt="Venus flytrap, round 3"></a><br>Pass / Pass |

## Memory retrieval

Own-task records come from earlier attempts at the same task; other-task records come from a different WISE task. Counts refer to selected-record occurrences across generation instances.

| Round | Selected records | Own task | Other task | Negative records |
| --- | --- | --- | --- | --- |
| R2 | 472 | 414/472 (87.7%) | 58/472 (12.3%) | 357/472 (75.6%) |
| R3 | 214 | 194/214 (90.7%) | 20/214 (9.3%) | 198/214 (92.5%) |

[Memory provenance CSV](site/downloads/memory_provenance.csv)

### Analogical transfer

Each run contains 120 target tasks. Paired-source records originate from the source task used to construct a target; other-source records originate from other tasks.

| Run | Targets | Paired-source records | Other-source records | Targets using paired-source memory |
| --- | --- | --- | --- | --- |
| All-memory v1 | 120 | 112 | 206 | 54/120 (45.0%) |
| All-memory v2 | 120 | 124 | 225 | 62/120 (51.7%) |

[Target prompts, source mappings and selected records](site/data/transfer.json)

## Search records

The runs contain 1,197 text-search calls and 7,107 returned results. Screening checks known benchmark markers and exact 12-word spans from WISE prompts and explanations in returned text.

| Round | Text-search calls | Returned results | Episodes with screening matches |
| --- | --- | --- | --- |
| R1 | 1,010 | 5,970 | 0 |
| R2 | 122 | 744 | 0 |
| R3 | 65 | 393 | 0 |

[Queries and screening results](site/downloads/search_screening.json)

## Materials

| Material | Contents |
| --- | --- |
| [Instance index](results/README.md) | All 1,187 instances, images and per-instance records |
| [Episode CSV](site/downloads/episodes.csv) | Prompts, categories, decisions and retrieval counts |
| [Experimental settings](results/settings.md) | Models, evaluation versions, prompts and memory rules |
| [Round manifests](site/config) | Run configurations for R1–R3 |
| [Instance records](site/data/episodes) | Generation prompts, judge outputs, memory selection, search results and tool-call records in JSON.gz |
| [Checksums](site/downloads/checksums.json) | SHA256 hashes of data and configuration files |
| [Build instructions](maintenance/README.md) | Regenerate the Markdown results and validate the export |

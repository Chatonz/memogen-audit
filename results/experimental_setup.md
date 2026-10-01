# Experimental setup

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

Prompt SHA256: `976ab487f5bef1fdaeea28cb41dbb651ae063b38643eba4dfe2d996fde5c4786`.

The runner snapshot sets judge temperature to 0; the configuration default is 4,096 output tokens. Historical request-level overrides are unrecorded. The run manifests and instance records provide the recorded settings.

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

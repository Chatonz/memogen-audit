# Build the result documents

## Generate Markdown

Run from the repository root:

```bash
python maintenance/build_readme.py
```

The script reads `site/data/` and generates the main README, three round indexes, example pages and experimental settings. It uses the Python standard library. Image and document links are relative to the repository.

## Validate

```bash
python maintenance/validate.py site
python maintenance/build_readme.py --check
```

Validation checks the 1,187 instance records, round routing, image files, evaluation alignment and data checksums. The Markdown check compares the result documents with the exported data.

## Rebuild the data export

```bash
python -m pip install -r maintenance/requirements.txt
python maintenance/build_from_memogen.py \
  --project-root /path/to/MemoGen \
  --output site
python maintenance/build_readme.py
python maintenance/validate.py site
python maintenance/build_readme.py --check
```

The source experiment is identified by `imported_run` in the [experiment configuration](../site/data/protocol.json). The exporter reads that run and its aligned evaluation records.

## File names

Documents and configuration files use descriptive `snake_case` names. Round numbers use two digits (`round_01`); example pages use the WISE task ID (`wise_0002`). Instance keys such as `r2-2` link the image, data record and CSV row.

## Read an instance record

```python
import gzip
import json

with gzip.open("site/data/episodes/r2-2.json.gz", "rt") as f:
    instance = json.load(f)

print(instance["generated_prompt"])
print(instance["judge_detail"])
print(instance["memory"]["selected"])
```

#!/usr/bin/env python3
"""Validate the public export: cohort joins, privacy exclusions, links and checksums."""
import csv
import gzip
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

site=Path(sys.argv[1] if len(sys.argv)>1 else Path(__file__).parent/'site')
rows=json.loads((site/'data/index.json').read_text())
summary=json.loads((site/'data/summary.json').read_text())
protocol=json.loads((site/'data/protocol.json').read_text())
judge_prompt=site/protocol['judge']['prompt_file']
assert judge_prompt.is_file(),judge_prompt
assert hashlib.sha256(judge_prompt.read_bytes()).hexdigest()==protocol['judge']['prompt_sha256']
assert len(rows)==1187
assert Counter(r['round'] for r in rows)=={1:1000,2:122,3:65}
assert len({r['key'] for r in rows})==1187
assert len({r['id'] for r in rows})==1000
assert {r['id'] for r in rows if r['round']==2}=={r['id'] for r in rows if r['round']==1 and r['judge']==0}
assert {r['id'] for r in rows if r['round']==3}=={r['id'] for r in rows if r['round']==2 and r['judge']==0}
for r in rows:
    assert (site/r['image']).is_file(), r['key']
    assert (site/r['thumb']).is_file(), r['key']
    detail=json.loads(gzip.decompress((site/'data/episodes'/f"{r['key']}.json.gz").read_bytes()))
    assert all(detail[k]==r[k] for k in ['key','id','round','judge','official'])
    assert len(detail['image_provenance']['original_sha256'])==64
    assert 'human' not in detail and 'human' not in r
    assert len(detail['memory']['selected'])==r['memory_mentions']
    for image in detail.get('reference_images',[]):
        if not image['missing']:
            assert (site/image['view']).is_file(), image['key']
assert not list((site/'data/episodes').glob('*.json')), 'Superseded uncompressed exports must not remain'
for rnd in [1,2,3]:
    rr=[r for r in rows if r['round']==rnd]
    agreement=sum(r['judge']==r['official'] for r in rr)/len(rr)
    assert abs(summary['rounds'][rnd-1]['official_agreement']['agreement']-agreement)<1e-12
    assert (site/'config'/f'round_{rnd:02d}.json').is_file()
    assert protocol['evaluations'][f'round_{rnd:02d}']['recorded_version']==rr[0]['official_version']
assert summary['rounds'][0]['official_agreement']['agreement']==0.911
assert summary['rounds'][1]['memory_own']==414
assert summary['rounds'][1]['memory_other']==58
forbidden_keys={'human_record','human_pass','human_agreement','human_accuracy','human_score','human_label','machine_only_correct','annotator','annotator_id'}
def inspect(value,path):
    if isinstance(value,dict):
        for k,v in value.items():
            assert k.lower() not in forbidden_keys, (str(path),k)
            assert not re.search(r'api.?key|authorization|access.?token|password|secret',k,re.I), (str(path),k)
            inspect(v,path)
    elif isinstance(value,list):
        for v in value:inspect(v,path)
    elif isinstance(value,str):
        assert not re.search(r'\bsk-[A-Za-z0-9_-]{16,}',value), ('credential-like text',str(path))
        assert 'human_judgements' not in value, ('human artifact pointer',str(path))
for p in site.rglob('*'):
    if p.suffix=='.json':inspect(json.loads(p.read_text()),p)
    elif p.name.endswith('.json.gz'):inspect(json.loads(gzip.decompress(p.read_bytes())),p)
    elif p.suffix=='.csv':
        with p.open() as f:
            reader=csv.DictReader(f)
            assert not (set(reader.fieldnames or [])&forbidden_keys),str(p)
checksums=json.loads((site/'downloads/checksums.json').read_text())
for filename,expected in checksums.items():
    assert hashlib.sha256((site/filename).read_bytes()).hexdigest()==expected,filename
alignment_path=site/'downloads/wise_round_01_scores.csv'
assert alignment_path.is_file(),alignment_path
if alignment_path.exists():
    aligned=list(csv.DictReader(alignment_path.open()));assert len(aligned)==1000
    for r in aligned:
        d=json.loads(gzip.decompress((site/'data/episodes'/f"r1-{r['id']}.json.gz").read_bytes()))
        assert d['image_provenance']['original_sha256']==r['original_sha256']
        assert d['judge']==int(r['judge']) and d['official']==int(r['official'])
print(json.dumps({'valid':True,'instances':len(rows),'rounds':[1000,122,65],'human_scoring_exported':False,'source_images_complete':True,'checksummed_files':len(checksums)},indent=2))

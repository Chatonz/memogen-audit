#!/usr/bin/env python3
"""Build a static, provenance-preserving MemoGen reviewer archive. No API calls."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import shutil
import sqlite3
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN = "eval_outputs/v4_benchmark_pool/v4_wise_gpt55_wise_strict_v1_r1summary_20260717"
OFFICIAL = "eval_outputs/wise_official_eval/qwen35_r1_full_20260919"
OLD_SCORES = "eval_outputs/wise_numerical_audit_20260918/original_adaptive_1000_decisions.csv"
SENSITIVE = re.compile(r"api.?key|authorization|access.?token|password|secret|base_url|endpoint", re.I)
MARKERS = re.compile(r"wise[-_ ]?bench|2503\.07265|data_verified|mind[-_ ]?bench|checklist_results", re.I)


def load(path, default=None):
    p = Path(path)
    return json.loads(p.read_text()) if p.is_file() else default


def jsonl(path):
    p = Path(path)
    return [json.loads(s) for s in p.read_text().splitlines() if s.strip()] if p.exists() else []


def resolve(value):
    text = str(value or "").replace("/mnt/workspace/Wilson/Mind-Brush-hermes", str(ROOT))
    p = Path(text)
    return p if p.is_absolute() else ROOT / p


def public_path(value):
    s = str(value or "")
    for prefix in [str(ROOT), "/mnt/workspace/Wilson/Mind-Brush-hermes"]:
        s = s.replace(prefix + "/", "project://")
    return s


def sanitize(value):
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items() if not SENSITIVE.search(k)}
    if isinstance(value, list):
        return [sanitize(x) for x in value]
    if isinstance(value, str):
        value = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", "[image bytes omitted]", value)
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{16,}\b", "[credential redacted]", value)
        return public_path(value)
    return value


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(sanitize(value), ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    if path.suffix == '.gz':
        path.write_bytes(gzip.compress(content, compresslevel=9, mtime=0))
    else:
        path.write_bytes(content)


def connect(path):
    c = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def tables(c):
    return {x[0] for x in c.execute("select name from sqlite_master where type='table'")}


def agreement(rows, label):
    pairs = [(r['judge'], r[label]) for r in rows if r.get(label) in (0, 1)]
    n = len(pairs)
    if not n:
        return None
    ct = Counter(pairs)
    observed = (ct[1, 1] + ct[0, 0]) / n
    pa, pb = sum(x for x, _ in pairs) / n, sum(y for _, y in pairs) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return {'n': n, 'agreement': observed, 'kappa': (observed-expected)/(1-expected) if expected < 1 else None,
            'both_pass': ct[1, 1], 'both_fail': ct[0, 0], 'judge_only_pass': ct[1, 0], 'reference_only_pass': ct[0, 1]}


def tokens(s):
    return re.findall(r"[a-z0-9]+", str(s).lower())


def fingerprints(benchmark):
    out = defaultdict(set)
    for sid, item in benchmark.items():
        for field in ['Prompt', 'Explanation']:
            words = tokens(item.get(field, ''))
            for i in range(max(0, len(words) - 11)):
                out[tuple(words[i:i+12])].add((sid, field))
    return out


def scan_text(text, index, location):
    words = tokens(text)
    found = set()
    for i in range(max(0, len(words)-11)):
        phrase = tuple(words[i:i+12])
        for sid, kind in index.get(phrase, ()):
            found.add((sid, kind, ' '.join(phrase)))
    return [{'benchmark_id': sid, 'field': kind, 'excerpt': phrase, 'location': location}
            for sid, kind, phrase in sorted(found)]


def search_results(text):
    results = []
    query = ''
    current = None
    for line in text.splitlines():
        if line.startswith('====== Search Query:'):
            query = line.removeprefix('====== Search Query:').strip(' =')
        elif line.startswith('--- Result '):
            if current:
                results.append(current)
            current = {'query': query, 'title': line.split(':', 1)[-1].strip(), 'url': '', 'snippet': ''}
        elif current is not None and line.startswith('Source:'):
            current['url'] = line.removeprefix('Source:').strip()
        elif current is not None and line.startswith('Snippet:'):
            current['snippet'] = line.removeprefix('Snippet:').strip()
    if current:
        results.append(current)
    return results


def relation_rows(run):
    by_round = {}
    for rnd in [1, 2, 3]:
        rels = {}
        for p in sorted((run / 'wise' / f'round_{rnd:02d}' / 'state').rglob('*.db')):
            with connect(p) as c:
                if 'evo_relation_records' not in tables(c):
                    continue
                for r in c.execute('select * from evo_relation_records'):
                    d = dict(r)
                    for k in ['elements_json', 'attributes_json']:
                        d[k.removesuffix('_json')] = json.loads(d.pop(k) or ('[]' if k == 'elements_json' else '{}'))
                    d['source_db'] = public_path(p)
                    rels[d['relation_id']] = d
        by_round[rnd] = rels
        print(f'Relation source R{rnd}: {len(rels):,} records', flush=True)
    return by_round


def export_image(task):
    src, out, key = task
    if not src.is_file():
        return {'key': key, 'missing': True, 'source': public_path(src)}
    original_sha = digest(src)
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert('RGB')
        size = list(im.size)
        for label, maxsize, quality in [('thumb', 320, 78), ('view', 1200, 88)]:
            p = out / 'images' / label / f'{key}.webp'
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists() or p.stat().st_mtime < src.stat().st_mtime:
                copy = im.copy()
                copy.thumbnail((maxsize, maxsize))
                copy.save(p, 'WEBP', quality=quality, method=4)
    return {'key': key, 'missing': False, 'original_sha256': original_sha, 'original_size': size,
            'thumb': f'images/thumb/{key}.webp', 'view': f'images/view/{key}.webp',
            'source': public_path(src), 'display_format': 'Derived WebP preview; SHA256 identifies original image'}


def build(args):
    run, out = resolve(args.experiment_dir), Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out/'.nojekyll').touch()
    benchmark = {str(x['prompt_id']): x for x in load(ROOT/'eval_outputs/wise_official_eval/qwen35_r1_full_20260919/verified.json', [])}
    fp = fingerprints(benchmark)
    scores = {str(r['prompt_id']): int(r['score']) for r in jsonl(ROOT/OFFICIAL/'results/scores.jsonl')}
    score_images = {r['id']: r for r in csv.DictReader((ROOT/OFFICIAL/'comparison_1000.csv').open())}
    old = {r['sample_id']: r for r in csv.DictReader((ROOT/OLD_SCORES).open())}
    relations = relation_rows(run)
    legacy = {str(r['sample_id']): r for r in jsonl(ROOT/'eval_outputs/wise_leakage_audit_20260920/evidence_1000.jsonl')}
    summaries, details, images, manifests = [], {}, [], {}
    reference_jobs = {}
    db_cache = {}
    for rnd in [1, 2, 3]:
        rd = run/'wise'/f'round_{rnd:02d}'
        manifests[str(rnd)] = load(rd/'run_manifest.json', {})
        gate = {str(r['sample_id']): int(r['pass']) for r in jsonl(rd/'judgement_gate.jsonl')}
        private = {str(r['id']): r for r in jsonl(rd/'judge_private/results_private.jsonl')}
        source_rel = {rid: r for prev in range(1, rnd) for rid, r in relations[prev].items()}
        fresh = [load(p) for p in sorted((rd/'intermediate').glob('*.json'), key=lambda p: int(p.stem))]
        fresh = [x for x in fresh if not x.get('carried_forward')]
        assert len(fresh) == {1:1000,2:122,3:65}[rnd], (rnd, len(fresh))
        for num, item in enumerate(fresh):
            sid, ep = str(item['id']), item['episode_id']
            key = f'r{rnd}-{sid}'
            db = resolve(item['state_db'])
            if db not in db_cache:
                db_cache[db] = connect(db)
            c = db_cache[db]
            actions, searches, image_queries, memory_events = [], [], [], []
            for row in c.execute('select * from tool_calls where episode_id=? order by step_index,created_at', (ep,)):
                d = dict(row)
                inputs = json.loads(d.get('args_json') or d.get('input_json') or '{}')
                inputs = inputs.get('input', inputs)
                response = json.loads(d.get('output_json') or '{}')
                output = response.get('output', response)
                actions.append({'step':d['step_index'], 'action':d['tool_name'], 'ok':bool(d['ok']),
                                'input':inputs, 'output':output, 'error':d.get('error'), 'timestamp':d['created_at']})
                if d['tool_name'] == 'web_search':
                    text = output.get('result_text', '')
                    parsed = search_results(text)
                    result_only = '\n'.join(' '.join(r.get(k,'') for k in ['title','url','snippet']) for r in parsed)
                    if not parsed:
                        result_only = re.sub(r'^====== Search Query:.*$', '', text, flags=re.M)
                    searches.append({'step':d['step_index'], 'ok':bool(d['ok']), 'queries':inputs.get('queries', output.get('queries', [])),
                                     'provider': output.get('provider'), 'result_text':text, 'results': parsed,
                                     'truncated': bool(output.get('truncated')), 'original_chars':output.get('result_chars'),
                                     'fingerprint_candidates':scan_text(result_only, fp, 'search_result'),
                                     'benchmark_marker_hits': MARKERS.findall(result_only)})
                elif d['tool_name'] == 'retrieve_reference_web':
                    image_queries.append({'step':d['step_index'], 'queries':inputs.get('queries',[]), 'output': output})
            for row in c.execute("select step_index,payload_json from trajectory_events where episode_id=? and event_kind='memory_retrieval_audit' order by created_at", (ep,)):
                e = json.loads(row['payload_json'])
                memory_events.append({'step':row['step_index'], **e})
            selections = [e for e in memory_events if e.get('action') == 'memory_select']
            selected = selections[-1].get('selected_ids', []) if selections else []
            memories = []
            for rid in selected:
                record = source_rel.get(rid)
                provenance = 'unresolved' if record is None else ('own_task' if str(record['sample_id']) == sid else 'other_task')
                memories.append({'relation_id':rid, 'provenance':provenance, 'record':record})
            resources = []
            for row in c.execute("select resource_id,kind,uri,payload_json from resources where episode_id=? and kind in ('gap_review','reference_candidate','reference_selection','generation_rubric','rubric','attempt_image','working_prompt','selected_reference') order by created_at", (ep,)):
                d = dict(row)
                d['payload'] = json.loads(d.pop('payload_json') or '{}')
                resources.append(d)
            generated = list(c.execute("select call_id,step_index,model_name,ok,latency_sec,raw_input_json,parsed_output_json from model_calls where episode_id=? and model_kind='image_generation' order by created_at", (ep,)))
            generated = [{**dict(x), 'raw_input':json.loads(x['raw_input_json'] or '{}'), 'parsed_output':json.loads(x['parsed_output_json'] or '{}')} for x in generated]
            for x in generated:
                x.pop('raw_input_json'); x.pop('parsed_output_json')
            reference_images = []
            final_call = next((g for g in generated if resolve(g['raw_input'].get('request',{}).get('output_path')) == resolve(item['generated_image'])), None)
            for value in (final_call or {}).get('raw_input',{}).get('request',{}).get('reference_images',[]):
                ref_path = resolve(value)
                ref_sha = digest(ref_path) if ref_path.is_file() else None
                ref_key = 'ref-' + (ref_sha[:24] if ref_sha else hashlib.sha256(str(ref_path).encode()).hexdigest()[:24])
                candidate = next((r for r in resources if r['kind']=='reference_candidate' and resolve(r['payload'].get('path'))==ref_path), None)
                source_meta = (candidate or {}).get('payload',{}).get('library_payload',{}).get('source_metadata',{})
                reference_images.append({'key':ref_key,'source_path':public_path(ref_path),'original_sha256':ref_sha,
                                         'view':f'images/view/{ref_key}.webp','thumb':f'images/thumb/{ref_key}.webp',
                                         'missing':not ref_path.is_file(),'source_metadata':source_meta})
                reference_jobs.setdefault(ref_key,(ref_path,out,ref_key))
            model_calls = [dict(r) for r in c.execute('select call_id,step_index,model_kind,provider,model_name,ok,latency_sec,error,created_at from model_calls where episode_id=? order by created_at', (ep,))]
            controller_first = c.execute("select raw_input_json from model_calls where episode_id=? and model_kind='agent_controller' order by created_at limit 1", (ep,)).fetchone()
            settings = {}
            if controller_first:
                request = json.loads(controller_first[0]).get('chat_completion_kwargs', {})
                settings = {k:v for k,v in request.items() if k not in ['messages','tools','tool_choice']}
            image_path = resolve(item['generated_image'])
            official = scores.get(sid) if rnd == 1 else int(old[sid][f'r{rnd}_historical_score'])
            official_source = f'{OFFICIAL}/results/scores.jsonl' if rnd == 1 else old[sid][f'r{rnd}_historical_score_file']
            if rnd == 1:
                assert resolve(score_images[sid]['image']) == image_path
            else:
                assert resolve(old[sid][f'r{rnd}_image']) == image_path
            own = sum(x['provenance']=='own_task' for x in memories)
            other = sum(x['provenance']=='other_task' for x in memories)
            candidates = sum(len(s['fingerprint_candidates']) + len(s['benchmark_marker_hits']) for s in searches)
            legacy_context = legacy.get(sid,{}).get('controller_initial_memory_context','') if rnd==1 else ''
            summary = {'key':key,'id':sid,'round':rnd,'category':item.get('category',''),'subcategory':item.get('metadata',{}).get('subcategory',''),
                       'prompt':item['prompt'],'judge':gate[sid],'official':official,
                       'official_version':'WISE full R1 · 2026-09-19' if rnd==1 else f'WISE historical R{rnd} · 2026-07-19',
                       'own_memory':own,'other_memory':other,'unresolved_memory':len(memories)-own-other,
                       'negative_memory':sum(x['record'] is not None and x['record'].get('polarity')=='negative' for x in memories),
                       'memory_mentions':len(memories),'memory_logging':'structured' if memory_events else 'legacy / no structured retrieval events',
                       'legacy_context_present':bool(legacy_context),'web_calls':len(searches),'web_results':sum(len(s['results']) for s in searches),
                       'search_candidates':candidates,'search_truncated':any(s['truncated'] for s in searches),
                       'search_status':'candidate_review' if candidates else ('screened_no_match' if searches else 'no_search_record'),
                       'generation_calls':len(generated),'successful_generations':sum(bool(x['ok']) for x in generated),
                       'routed_next':rnd<3 and gate[sid]==0,'image':f'images/view/{key}.webp','thumb':f'images/thumb/{key}.webp'}
            detail = {**summary, 'episode_id':ep, 'generated_prompt':item.get('enhanced_prompt',''), 'rubric':item.get('rubric',{}),
                      'judge_detail':private.get(sid), 'controller_settings':settings,
                      'official_record':{'score':official,'source':official_source,'version':summary['official_version']},
                      'evaluation_only_explanation':benchmark.get(sid,{}).get('Explanation',''),
                      'memory':{'events':memory_events,'selected':memories,'legacy_initial_context':legacy_context},
                      'search':{'calls':searches,'image_search':image_queries,'manual_review':'not_completed',
                                'blocked_rerun':'not_available','interpretation':'Automated candidates are not established leakage. Normal task queries and public facts are legitimate.'},
                      'resources':resources,'actions':actions,'model_calls':model_calls,'generation_calls_detail':generated,'reference_images':reference_images,
                      'source':{'run':public_path(run),'db':public_path(db),'intermediate':public_path(rd/'intermediate'/f'{sid}.json'),
                                'trace':public_path(item.get('trace_md')),'image':public_path(image_path)}}
            summaries.append(summary); details[key]=detail; images.append((image_path,out,key))
            if (num+1)%100==0 or num+1==len(fresh):
                print(f'Extracted R{rnd}: {num+1}/{len(fresh)}',flush=True)
    for c in db_cache.values(): c.close()
    with ThreadPoolExecutor(max_workers=args.image_workers) as pool:
        for num, meta in enumerate(pool.map(export_image,images), 1):
            key = meta.pop('key'); details[key]['image_provenance']=meta
            write(out/'data/episodes'/f'{key}.json.gz',details[key])
            if num%100==0 or num==len(images): print(f'Images and episode JSON: {num}/{len(images)}',flush=True)
    # Remove superseded uncompressed exports, including fields excluded from this public release.
    for old_export in (out/'data/episodes').glob('*.json'):
        old_export.unlink()
    with ThreadPoolExecutor(max_workers=args.image_workers) as pool:
        for num, _ in enumerate(pool.map(export_image,reference_jobs.values()),1):
            if num%200==0 or num==len(reference_jobs): print(f'Selected reference images: {num}/{len(reference_jobs)}',flush=True)
    for r in summaries:
        r['image_missing']=details[r['key']]['image_provenance']['missing']
    rounds=[]
    for rnd in [1,2,3]:
        rows=[r for r in summaries if r['round']==rnd]
        rounds.append({'round':rnd,'n':len(rows),'judge_pass':sum(r['judge'] for r in rows),
                       'official_pass':sum(r['official'] or 0 for r in rows),'official_agreement':agreement(rows,'official'),
                       'memory_own':sum(r['own_memory'] for r in rows),'memory_other':sum(r['other_memory'] for r in rows),
                       'memory_unresolved':sum(r['unresolved_memory'] for r in rows),'memory_negative':sum(r['negative_memory'] for r in rows),
                       'search_calls':sum(r['web_calls'] for r in rows),'search_candidate_episodes':sum(r['search_candidates']>0 for r in rows),
                       'search_truncated_episodes':sum(r['search_truncated'] for r in rows)})
    transfer=[]
    # A separate provenance namespace: target IDs must never be equated with original WISE IDs.
    target_file=ROOT/'eval_outputs/heldout_transfer/wise_transfer_targets_gpt55_round2_source_20260719/wise_transfer_targets_120_seed20260724.json'
    target_map={str(x['prompt_id']):x for x in load(target_file,[])}
    for name in ['wise_transfer_120_all_memory_strict_norepair_20260724','wise_transfer_120_all_memory_v2_strict_norepair_20260724']:
        exp=ROOT/'eval_outputs/v4_benchmark_pool'/name
        source={}
        for db in (exp/'wise/round_01/state').rglob('*.db'):
            with connect(db) as c:
                if 'evo_relation_records' in tables(c):
                    source.update({r['relation_id']:dict(r) for r in c.execute('select relation_id,sample_id,round_index,polarity,relation_text,repair_hint from evo_relation_records')})
        rows=[]
        for db in (exp/'wise/round_02/state/shards').glob('*.db'):
            with connect(db) as c:
                sm={r['episode_id']:str(r['sample_id']) for r in c.execute('select episode_id,sample_id from episodes')}; last={}
                for row in c.execute("select episode_id,payload_json from trajectory_events where event_kind='memory_retrieval_audit' order by created_at"):
                    e=json.loads(row['payload_json'])
                    if e.get('action')=='memory_select':last[row['episode_id']]=e
                for ep,e in last.items():
                    sid=sm[ep];target=target_map[sid];paired=str(target['source_prompt_id'])
                    for rid in e.get('selected_ids',[]):
                        rec=source.get(rid)
                        cls='unresolved' if rec is None else ('paired_source' if str(rec['sample_id'])==paired else 'other_source')
                        rows.append({'target_id':sid,'target_prompt':target['Prompt'],'paired_source_id':paired,'provenance':cls,'record':rec,'relation_id':rid,'selection_reason':e.get('selected_reason','')})
        ct=Counter(r['provenance'] for r in rows)
        transfer.append({'run':name,'mentions':len(rows),'counts':dict(ct),'targets_with_paired_source':len({r['target_id'] for r in rows if r['provenance']=='paired_source'}),'target_n':len(target_map),'rows':rows})
    write(out/'data/transfer.json',transfer)
    protocol={'imported_run':public_path(run),'source_status':'Original archived run selected by the author for this public release',
              'separate_final_protocol_statement':'The author reports that final experiments on another server exclude official labels, explanations and hidden annotations from generation, memory judging and memory. That server has not been imported into this archive.',
              'manifest_by_round':manifests,
              'judge':{'model':'gpt-5.5','profile':'evolution_wise_strict_v1','prompt_file':'config/archived_judge_prompt.txt',
                       'prompt_sha256':digest(ROOT/'prompts/evolution_judge_wise_strict_v1.txt'),
                       'prompt_scope':'Archived configuration uses target_explanation; not the final isolated-server judge configuration.',
                       'temperature':{'value':0,'evidence':'Current runner implementation; historical request value not independently logged'},
                       'max_completion_tokens':{'value':4096,'evidence':'Current config default; historical environment override not recovered'},
                       'decision':'Parsed JSON pass / final_judgment; see released parser source',
                       'exceptions':'Current runner maps judge exceptions to fail; error records remain available per instance'},
              'official':load(ROOT/OFFICIAL/'evaluation_config.json',{}),
              'memory_rules':{'scope':'Current code snapshot; per-episode recorded memory_schema and manifests take precedence for historical runs',
                              'admission':'Binary gate sets positive/negative polarity. Relation text and visual evidence are required; minimum confidence defaults to 0.2, plus element/attribute validation.',
                              'retrieval':'Explicit lexical find/grep → open → select. Matches ordered by creation time and confidence; no embedding ranking.',
                              'limits':{'query_chars':96,'query_tokens':10,'find_candidates':12,'open_records':6,'selected_records':4},
                              'polarity':'Positive strategies may be reused; negative records provide warnings and repair constraints.',
                              'provenance':'Own-task and other-task use original WISE task IDs. Analogical targets use explicit source_prompt_id; IDs are scoped to their dataset.'},
              'routing':{'R1':{'new':1000,'carried':0},'R2':{'new':122,'carried':878},'R3':{'new':65,'carried':935},
                         'rule':'R2 and R3 rerun previous strict-judge failures. Unchanged images are carried forward; gate labels are not substituted for official scores.'},
              'search_audit':{'scope':'Recorded text queries/results and reference-image provenance in imported episodes',
                              'screen':'Known benchmark markers and exact 12-word spans from WISE prompts/explanations; query headers excluded from result matching.',
                              'status':'Automated screening completed; manual adjudication and clean reruns pending',
                              'interpretation':'Leakage through live search is not established. A fingerprint hit is a review candidate, not proof. No hit is not proof of absence.',
                              'qualification':'Imported results use open-web evaluation. No benchmark-isolated retrieval guarantee is claimed.'}}
    write(out/'data/protocol.json',protocol)
    copied={
      'prompts/evolution_judge_wise_strict_v1.txt':'config/archived_judge_prompt.txt',
      'evaluation/judge_profiles.py':'config/judge_profiles.py.txt',
      'agents/v4/relation_memory.py':'config/relation_memory.py.txt',
      'agents/v4/memory_tools.py':'config/memory_tools.py.txt',
      'agents/v4/metadata.py':'config/metadata_sanitization.py.txt',
    }
    for src,dst in copied.items():
        p=out/dst;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(sanitize((ROOT/src).read_text()))
    for rnd, m in manifests.items():write(out/'config'/f'round_{rnd}_manifest.json',m)
    write(out/'data/index.json',summaries)
    write(out/'data/summary.json',{'updated_at':datetime.now(timezone.utc).isoformat(),'episodes':len(summaries),'unique_tasks':len({r['id'] for r in summaries}),
                                 'source':public_path(run),'rounds':rounds,'categories':sorted({r['category'] for r in summaries}),
                                 'missing_images':sum(r['image_missing'] for r in summaries),'paired_source_runs':[{k:v for k,v in x.items() if k!='rows'} for x in transfer]})
    p=out/'downloads/episodes.csv';p.parent.mkdir(exist_ok=True)
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(summaries[0]));w.writeheader();w.writerows(summaries)
    with (out/'downloads/official_r1_alignment.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['id','judge','official','original_sha256']);w.writeheader()
        for r in summaries:
            if r['round']==1:
                assert details[r['key']]['image_provenance']['original_sha256']==score_images[r['id']]['sha256']
                w.writerow({'id':r['id'],'judge':r['judge'],'official':r['official'],'original_sha256':score_images[r['id']]['sha256']})
    with (out/'downloads/memory_provenance.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['episode','target_id','round','relation_id','source_id','source_round','polarity','provenance']);w.writeheader()
        for key,d in details.items():
            for m in d['memory']['selected']:
                r=m['record'] or {};w.writerow({'episode':key,'target_id':d['id'],'round':d['round'],'relation_id':m['relation_id'],'source_id':r.get('sample_id'),'source_round':r.get('round_index'),'polarity':r.get('polarity'),'provenance':m['provenance']})
    write(out/'downloads/search_screening.json',[{'key':k,'status':d['search_status'],'truncated':d['search_truncated'],'calls':[{'queries':s['queries'],'candidates':s['fingerprint_candidates'],'marker_hits':s['benchmark_marker_hits']} for s in d['search']['calls']]} for k,d in details.items()])
    hashes={str(p.relative_to(out)):digest(p) for folder in ['data','config','downloads'] for p in sorted((out/folder).rglob('*')) if p.is_file() and p.name!='checksums.json'}
    write(out/'downloads/checksums.json',hashes)
    print(json.dumps({'episodes':len(summaries),'round_counts':[r['n'] for r in rounds],'missing_images':sum(r['image_missing'] for r in summaries),'output':str(out)},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',default=str(ROOT),help='Path to the original MemoGen source and experiment archive')
    p.add_argument('--experiment-dir',default=DEFAULT_RUN)
    p.add_argument('--output',default=str(Path(__file__).parent/'site'))
    p.add_argument('--image-workers',type=int,default=8)
    args=p.parse_args()
    ROOT=Path(args.project_root).resolve()
    if str(resolve(args.experiment_dir).resolve()) != str((ROOT/DEFAULT_RUN).resolve()):
        p.error('This exporter is version-bound to the archived run. Importing another run requires aligning its own official evaluation labels first.')
    build(args)

"""Compare supplied specialist weights with unchanged generated inputs, offline.

This measures CPU worker helpers, not E57-to-IFC quality or desktop completion.
Weights must already exist in the explicitly supplied directory; no downloads.
"""
import argparse
from collections import OrderedDict
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import tempfile
import time

# ORT owns explicit pools. Set these before importing native numeric libraries.
for _name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ[_name] = '1'

import numpy as np
import onnxruntime as ort

from punctora_core.recognition.specialist_indices import build_index_inputs
from punctora_core.recognition.specialist_pack import resolve_model_pack
from punctora_core.recognition.specialist_runtime import runtime_plan
from punctora_core.recognition.specialist_worker import image_tensor, infer_image, infer_images, infer_point
from punctora_core.recognition.streaming_views import SourceBox
from punctora_core.sampling import available_memory_bytes, resolved_cpu_workers


def compare_models(root, directory, cores, repeats, voxels):
    manifest, status, missing = resolve_model_pack(root)
    if any(branch in missing for branch in 'DEI'):
        raise ValueError('This benchmark requires the reviewed D, E and I graphs and D companion')
    largest = max(v.get('graph_bytes', 0)+v.get('companion_bytes', 0) for v in status.values())
    plan = runtime_plan(cores, int(available_memory_bytes()*.8), largest, 3)
    base = {'model_root': str(root.resolve()), 'manifest': manifest, 'maximum_cached_sessions': 3}
    report = {'scope': 'supplied D/E/I weights, generated fixed inputs; in-process worker helper timing; not real-scan quality or full desktop runtime',
        'onnxruntime': ort.__version__, 'platform': platform.platform(),
        'cpu_budget': cores, 'runtime_plan': plan, 'model_pack_sha256': manifest['manifest_sha256'],
        'weights': {b:status[b] for b in 'DEI'}, 'images': [], 'points': []}
    image = np.zeros((512,512),dtype=np.uint8)
    image[20:490:31,:] = 255; image[:,15:498:33] = 255
    for branch in 'DE': np.save(directory/f'{branch}.npy',image_tensor(branch,image),allow_pickle=False)
    rows = np.arange(voxels)
    grid = np.column_stack((rows%32,(rows//32)%32,rows//1024))
    rng = np.random.default_rng(311)
    normals = rng.normal(size=(len(rows),3))
    normals = (normals/np.linalg.norm(normals,axis=1)[:,None]).astype(np.float32)
    feed,_ = build_index_inputs(grid,normals)
    feed_paths = {}
    for name,value in feed.items():
        path=directory/f'{name}.npy';np.save(path,value,allow_pickle=False);feed_paths[name]=str(path)
    feed_manifest=directory/'feed.json';feed_manifest.write_text(json.dumps(feed_paths))
    parity = {}
    for phase in ('images','points'):
        caches = {name:OrderedDict() for name in ('legacy','bounded')}
        for trial in range(-1,repeats):  # Separate cold startup from warm paired trials.
            order = ('legacy','bounded') if trial%2 else ('bounded','legacy')
            for name in order:
                request = {**base,**({'runtime_plan':plan} if name=='bounded' else {})}
                jobs=[{'branch':b,'tensor':str(directory/f'{b}.npy'),
                       'output':str(directory/f'{b}-{name}.npz')} for b in 'DE']
                started,cpu=time.perf_counter(),time.process_time()
                if phase=='images':
                    if name=='legacy':
                        values=[infer_image(ort,{**request,**job},caches[name]) for job in jobs]
                    else:
                        # Respect a small machine's admission (including one CPU).
                        width=plan['image_workers'];values=[]
                        for begin in range(0,len(jobs),width):
                            values.extend(infer_images(ort,{**request,'jobs':jobs[begin:begin+width]},caches[name])['results'])
                    timings=[v['timings'] for v in values]
                else:
                    value=infer_point(ort,{**request,'feed_manifest':str(feed_manifest),
                        'output':str(directory/f'I-{name}.npy')},caches[name])
                    timings=[value['timings']]
                report[phase].append({'configuration':name,'trial':trial,'cold':trial==-1,
                    'wall_seconds':time.perf_counter()-started,'cpu_seconds':time.process_time()-cpu,
                    'component_timings':timings})
        for branch in ('DE' if phase=='images' else 'I'):
            if branch=='I':
                a,b=(np.load(directory/f'I-{name}.npy',allow_pickle=False) for name in ('legacy','bounded'))
                labels=lambda x:x.argmax(axis=1)
            else:
                arrays=[]
                for name in ('legacy','bounded'):
                    with np.load(directory/f'{branch}-{name}.npz',allow_pickle=False) as archive:
                        arrays.append(archive['logits'].copy())
                a,b=arrays;labels=lambda x:x.argmax(axis=1)
            parity[branch]={'max_absolute_logit_difference':float(np.abs(a-b).max()),
                'label_disagreements':int(np.sum(labels(a)!=labels(b))), 'decisions':int(labels(a).size)}
        caches.clear();gc.collect()
    report['parity']=parity
    report['summary']={}
    for phase in ('images','points'):
        medians={name:statistics.median(v['wall_seconds'] for v in report[phase]
            if v['configuration']==name and not v['cold']) for name in ('legacy','bounded')}
        report['summary'][phase]={'median_warm_wall_seconds':medians,
            'speedup':medians['legacy']/medians['bounded']}
    return report


def compare_cell_reads():
    """A30 per-cell loop versus bounded coalescing, with real RSS checks."""
    from types import SimpleNamespace
    from punctora_core.recognition.job import RecognitionControl
    count=12_000
    cells=np.zeros(count,dtype=[('x','<i8'),('y','<i8'),('z','<i8')]);cells['x']=np.arange(count)
    ids=np.arange(count*8,dtype=np.int64)
    points=np.column_stack((np.repeat(np.arange(count)*.25,8)+.01,np.full(len(ids),.01),np.full(len(ids),.01)))
    index=SimpleNamespace(cell_size_m=.25,runs=[(cells,np.arange(count)*8,ids)])
    results={}
    for name in ('legacy','coalesced'):
        with RecognitionControl() as control:
            source=SourceBox(SimpleNamespace(points=points),index,[0,0,0],[count,1,1],control,65_536)
            if name=='legacy':
                from punctora_core.recognition.specialist_provider import PunctoraSpecialistProvider
                def old_blocks():
                    for candidate in PunctoraSpecialistProvider._iter_box_rows(index,source.minimum,source.maximum):
                        for begin in range(0,len(candidate),source.block_size):
                            control.check()
                            rows=np.asarray(candidate[begin:begin+source.block_size],dtype=np.int64)
                            values=np.asarray(points[rows],dtype=np.float64)
                            keep=np.all((values>=source.minimum)&(values<=source.maximum),axis=1)
                            if keep.any():yield rows[keep],values[keep]
                blocks=old_blocks()
            else:blocks=source.blocks()
            started=time.perf_counter();row_hash,point_hash=hashlib.sha256(),hashlib.sha256();n=0
            for rows,values in blocks:
                n+=1;row_hash.update(rows.tobytes());point_hash.update(values.tobytes())
            results[name]={'seconds':time.perf_counter()-started,'blocks':n,
                'source_row_sha256':row_hash.hexdigest(),'point_sha256':point_hash.hexdigest()}
    results['exact_parity']=all(results['legacy'][k]==results['coalesced'][k]
        for k in ('source_row_sha256','point_sha256'))
    results['scope']='96,000 generated points in 12,000 cells; exact row/value digests; excludes E57 and inference'
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cpu-workers',type=int,default=0)
    parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--point-voxels',type=int,default=8192)
    args=parser.parse_args()
    if args.cpu_workers < -1 or args.repeats<3 or not 128<=args.point_voxels<=65_536:
        parser.error('Use cpu-workers >= -1, at least 3 repeats, and 128 to 65536 point voxels')
    cores=min(resolved_cpu_workers(args.cpu_workers),resolved_cpu_workers(-1))
    with tempfile.TemporaryDirectory(prefix='punctora-runtime-bench-') as temporary:
        report=compare_models(args.model_root,Path(temporary),cores,args.repeats,args.point_voxels)
    report['cell_reads']=compare_cell_reads()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(args.output),'summary':report['summary'],'parity':report['parity'],
                      'cell_read_parity':report['cell_reads']['exact_parity']}))
    if not report['cell_reads']['exact_parity'] or any(v['label_disagreements'] for v in report['parity'].values()):
        raise SystemExit('Parity failed; inspect the report before using the runtime policy')


if __name__=='__main__': main()

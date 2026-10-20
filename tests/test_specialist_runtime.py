from collections import OrderedDict
from pathlib import Path
from threading import Barrier, Lock, get_ident

import numpy as np
import pytest

from punctora_core.recognition import specialist_worker as worker
from punctora_core.recognition.job import RecognitionControl
from punctora_core.recognition.preprocessing import original_normals
from punctora_core.recognition.specialist_runtime import runtime_plan
from punctora_core.recognition.streaming_views import SourceBox


@pytest.mark.parametrize('cores,ram,sessions,expected', [(31, 20_000, 10, 5), (1, 20_000, 10, 1),
    (31, 1000, 10, 1), (31, 20_000, 2, 2)])
def test_cpu_and_activation_admission(cores, ram, sessions, expected):
    plan = runtime_plan(cores, ram, 100, sessions)
    assert plan['image_workers'] == expected
    assert plan['image_workers'] * plan['image_intra_op_threads'] <= cores
    assert plan['point_intra_op_threads'] == cores and plan['normal_workers'] == cores
    assert worker.runtime_options({'runtime_plan': plan}, 'I') == (cores, False)


@pytest.mark.parametrize('field,value', [('image_workers', 6), ('image_intra_op_threads', 9),
    ('point_intra_op_threads', 9), ('cpu_budget', True), ('inter_op_threads', 2),
    ('allow_spinning', True)])
def test_worker_rejects_oversubscribed_or_changed_runtime(field, value):
    plan = runtime_plan(8, 10_000, 100, 3)
    plan[field] = value
    with pytest.raises(ValueError, match='CPU budget'):
        worker.runtime_options({'runtime_plan': plan}, 'D')


def wave_request():
    return {'runtime_plan': runtime_plan(6, 10_000, 100, 3), 'maximum_cached_sessions': 3,
            'jobs': [{'branch': b, 'tensor': str(i)+'.npy', 'output': str(i)+'.npz'} for i, b in enumerate('DED')]}


def test_wave_overlaps_work_but_preserves_order_and_loads_sessions_serially(monkeypatch):
    request = wave_request()
    barrier, guard = Barrier(3), Lock()
    loads, running = [], set()
    session_for = {}
    def load(ort, request, branch, sessions):
        loads.append((branch, get_ident()))
        session_for[branch] = object()
        return session_for[branch]
    def infer(ort, request, sessions=None, session=None):
        assert session is session_for[request['branch']]
        with guard: running.add(request['tensor'])
        barrier.wait(timeout=5)
        assert len(running) == 3  # Fails if work is inadvertently serialized.
        return {'status': 'complete', 'branch': request['branch'], 'output': request['output'],
                'timings': {'session_load_seconds': 0., 'inference_seconds': 1.}}
    monkeypatch.setattr(worker, 'load_session', load)
    monkeypatch.setattr(worker, 'infer_image', infer)
    response = worker.infer_images(None, request, OrderedDict())
    assert [r['output'] for r in response['results']] == ['0.npz', '1.npz', '2.npz']
    assert loads == [('D', get_ident()), ('E', get_ident())]


def test_wave_limit_is_checked_before_loading_any_graph(monkeypatch):
    request = wave_request()
    request['maximum_cached_sessions'] = 2
    def unexpected(*args): pytest.fail('No graph may load before admission validation')
    monkeypatch.setattr(worker, 'load_session', unexpected)
    with pytest.raises(ValueError, match='concurrency/session budget'):
        worker.infer_images(None, request, OrderedDict())


def test_wave_preserves_unavailability_but_never_swallows_contract_errors(monkeypatch):
    monkeypatch.setattr(worker, 'load_session', lambda *args: object())
    def infer(ort, request, **kwargs):
        if request['branch'] == 'E': raise RuntimeError('not implemented generated operator')
        return {'status': 'complete', 'branch': request['branch'], 'timings': {'session_load_seconds': 0.}}
    monkeypatch.setattr(worker, 'infer_image', infer)
    response = worker.infer_images(None, wave_request(), OrderedDict())
    assert [r['status'] for r in response['results']] == ['complete', 'unavailable', 'complete']
    def malformed(*args, **kwargs): raise ValueError('Nonfinite generated output')
    monkeypatch.setattr(worker, 'infer_image', malformed)
    with pytest.raises(ValueError, match='Nonfinite'):
        worker.infer_images(None, wave_request(), OrderedDict())


def test_server_message_uses_inline_request_and_rejects_obsolete_path_contract(tmp_path, monkeypatch):
    request = {'schema_version': 1, 'mode': 'preflight',
               'response': str(tmp_path/'response.json')}
    expected = {'schema_version': 1, 'status': 'complete', 'active_branches': []}
    monkeypatch.setattr(worker, 'execute', lambda value, sessions: expected)

    reply = worker.execute_server_message({'request_id': 7, 'request': request}, OrderedDict())

    assert reply == {'schema_version': 1, 'status': 'complete', 'request_id': 7,
                     'cached_sessions': 0}
    assert worker.read_json(request['response']) == expected
    with pytest.raises(ValueError, match='request identity'):
        worker.execute_server_message({'request_id': 8, 'request': str(Path(request['response']))}, OrderedDict())


def test_parallel_normal_queries_preserve_exact_neighbours_and_features():
    rng = np.random.default_rng(319)
    context = rng.normal(size=(10_000, 3)) * .2
    context[10:15] = context[0]  # Include coincident neighbours and distance ties.
    selected = np.arange(0, 10_000, 2)
    serial = original_normals(context, selected, workers=1)
    parallel = original_normals(context, selected, workers=4)
    assert np.array_equal(serial[0], parallel[0])
    assert np.array_equal(serial[1], parallel[1]) and parallel[1].all()


def test_recognition_cpu_budget_honours_container_and_explicit_limit(monkeypatch):
    monkeypatch.setattr('punctora_core.recognition.job.resolved_cpu_workers', lambda n: 8 if n == -1 else 7 if n == 0 else n)
    assert RecognitionControl(cpu_workers=31).cpu_workers == 8
    assert RecognitionControl(cpu_workers=3).cpu_workers == 3
    with pytest.raises(ValueError, match='CPU workers'):
        RecognitionControl(cpu_workers=True)


def test_cell_reads_coalesce_without_losing_order_identity_or_polygon_filter():
    from types import SimpleNamespace
    from shapely.geometry import box
    cell = np.zeros(64, dtype=[('x','<i8'), ('y','<i8'), ('z','<i8')]); cell['x'] = np.arange(64)
    points = np.column_stack((np.arange(64)*.25+.01, np.full(64,.01), np.full(64,.01)))
    checks = []
    control = SimpleNamespace(chunk_points=11, check=lambda: checks.append(True))
    index = SimpleNamespace(cell_size_m=.25, runs=[(cell,np.arange(64),np.arange(64)[::-1])])
    # Reverse source-row order intentionally; coalescing must not reorder IDs.
    cloud = SimpleNamespace(points=points[::-1])
    source = SourceBox(cloud,index,[0,0,0],[16,1,1],control,7,box(1,-1,15,1))
    blocks = list(source.blocks())
    assert len(checks) == 11 and max(len(r) for r,p in blocks) <= 7
    rows = np.concatenate([r for r,p in blocks]); result = np.concatenate([p for r,p in blocks])
    expected_rows = np.arange(64)[::-1][(points[:,0]>1)&(points[:,0]<15)]
    assert np.array_equal(rows, expected_rows)
    assert np.array_equal(result, cloud.points[expected_rows])


def test_multi_view_rasters_equal_independent_passes_at_survey_coordinates():
    from punctora_core.recognition.specialist_frames import plan_frame, rasterize_plan
    from punctora_core.recognition.streaming_views import plan_images
    rng = np.random.default_rng(403)
    points = rng.uniform([-12,-12,0],[12,12,3],size=(8001,3)) + [7_000_000.,5_000_000.,100.]
    # Independent all-at-once renderer is the oracle, including exact grid planes.
    points[:30,:2] = [7_000_000.,5_000_000.]
    frames = [plan_frame(str(i),[7_000_000.,5_000_000.],side,pixels,angle,mirror,low,high)
        for i,(side,pixels,low,high) in enumerate([(10.24,1024,101.5,101.7),(20.48,2048,101.4,101.6)])
        for angle in (0.,30.,60.) for mirror in (False,True)]
    calls = []
    class Source:
        def blocks(self):
            calls.append(True)
            for start in range(0,len(points),257):
                yield np.arange(start,min(start+257,len(points))), points[start:start+257]
    results = plan_images(Source(),frames)
    assert calls == [True] and len(results) == 12
    for frame,(image,diagnostic) in zip(frames,results):
        expected, expected_counts = rasterize_plan(frame, points)
        assert np.array_equal(image,expected)
        assert diagnostic['rasterized_points'] == expected_counts['rasterized_points']
        assert diagnostic['input_points'] == len(points) and diagnostic['maximum_materialized_points'] == 257


@pytest.mark.parametrize('fraction', [.69,.81,True,float('nan'),'80%'])
def test_recognition_rejects_ram_policy_outside_authorized_band(fraction):
    with pytest.raises(ValueError, match='0.70 and 0.80'):
        RecognitionControl(memory_fraction=fraction)


def image_cloud():
    from punctora_core.cloud_io import CloudData
    x,z = np.meshgrid(np.arange(0,1.001,.05), np.arange(100,103.001,.05))
    points = np.column_stack((x.ravel()+7_000_000.,np.full(x.size,5_000_000.),z.ravel()))
    return CloudData(points,scan_index=np.arange(len(points),dtype='<u8')%3,
        source_record_index=np.arange(2**53,2**53+len(points),dtype='<u8'),
        working_index=np.arange(900,900+len(points),dtype='<u8'))


def wall_query_cloud():
    from punctora_core.cloud_io import CloudData
    x,z = np.meshgrid(np.arange(1.,9.001,.05),np.arange(100.,103.001,.05))
    points = np.column_stack((x.ravel(),np.full(x.size,5.12),z.ravel()))
    return CloudData(points,scan_index=np.arange(len(points),dtype='<u8')%3,
        source_record_index=np.arange(2**53,2**53+len(points),dtype='<u8'),
        working_index=np.arange(900,900+len(points),dtype='<u8'))


@pytest.mark.parametrize('positive_detections', [False,True],ids=['empty-query','positive-wall-query'])
def test_isolated_parallel_views_preserve_proposals_labels_and_source_support(tmp_path, monkeypatch, positive_detections):
    from test_specialist_provider import make_provider, fixture_resolution, identity
    from punctora_core.recognition.job import run_recognition
    from punctora_core.recognition.tiling import TileSettings
    from punctora_core.annotation_io import read_json
    from punctora_core.recognition.contracts import open_proposal_array
    providers = []
    for name in ('serial','parallel'):
        provider = make_provider(tmp_path/name, monkeypatch, 'positive-detections' if positive_detections else None)
        providers.append(provider)
    monkeypatch.setattr('punctora_core.recognition.specialist_provider.resolve_model_pack',
                        lambda *a,**k: fixture_resolution('ABCDEFGHIJ'))
    reports = []
    for provider, cores in zip(providers, (1,4)):
        directory, report, hit = run_recognition(wall_query_cloud() if positive_detections else image_cloud(), identity(), provider, tmp_path/'cache',
            tile_settings=TileSettings(maximum_context_points=10_000),cpu_workers=cores)
        assert not hit
        reports.append((directory,report))
    left, right = reports
    assert left[1]['cache_key'] != right[1]['cache_key']
    assert left[1]['instances'] == right[1]['instances']
    for key in ('labels','scores','scan_ids','record_ids','working_rows'):
        arrays = [open_proposal_array(path, report['arrays'][key]) for path, report in reports]
        try: assert np.array_equal(*arrays)
        finally:
            for a in arrays: a._mmap.close()
    extensions = [report['extensions']['specialist_v1'] for path, report in reports]
    assert all(v['status']=='active' for extension in extensions for v in extension['branches'].values())
    assert extensions[0]['branches'] == extensions[1]['branches']
    for key in ('proposals_path', 'support_index_path'):
        assert read_json(left[0]/extensions[0][key]) == read_json(right[0]/extensions[1][key])
    for filename in ('proposal-source-rows.npy',):
        assert np.array_equal(np.load(left[0]/'specialist'/filename), np.load(right[0]/'specialist'/filename))
    if positive_detections:
        for (directory, report), extension in zip(reports,extensions):
            views = read_json(directory/extension['views_path'])
            assert any(v['branch']=='J' and v['candidates']>0 for v in views['views'])
            assert {'B','C'} <= {v['branch'] for v in views['views'] if v.get('section_scope')=='wall'}
            assert report['instances'] and all(v['class']=='wall' for v in report['instances'])
            items = read_json(directory/extension['proposals_path'])['proposals']
            assert {'A','B','C'} <= {item['branch'] for item in items}
            support = read_json(directory/extension['support_index_path'])['entries']
            counts = {item['id']:item['count'] for item in support}
            assert all(counts[item['id']]>0 for item in report['instances'])
        directory, replay, hit = run_recognition(wall_query_cloud(), identity(), providers[1], tmp_path/'cache',
            tile_settings=TileSettings(maximum_context_points=10_000),cpu_workers=4)
        assert hit and directory == right[0] and replay == right[1]
        expected = wall_query_cloud()
        for key, values in (('scan_ids',expected.scan_index),('record_ids',expected.source_record_index),
                            ('working_rows',expected.working_index)):
            array = open_proposal_array(directory,replay['arrays'][key])
            try: assert np.array_equal(array,values)
            finally: array._mmap.close()
    assert not list((tmp_path/'cache').glob('.proposal-stage-*'))
    assert not list(right[0].rglob('*tensor.npy'))


@pytest.mark.parametrize('angle_degrees',[0.,27.])
def test_positive_wall_sections_follow_offset_wall_plane_at_survey_coordinates(tmp_path,monkeypatch,angle_degrees):
    from types import SimpleNamespace
    from test_specialist_provider import make_provider
    from punctora_core.cloud_io import CloudData
    from punctora_core.spatial_index import SpatialPointIndex
    provider = make_provider(tmp_path,monkeypatch)
    centre = np.array([7_000_003.25,5_000_004.75])
    # Native J pixel centres place this query away from the tile centre.
    wall_centre = centre + [.01,-2.57]
    angle = np.deg2rad(angle_degrees)
    axis = np.array([np.cos(angle),np.sin(angle)])
    along,z = np.meshgrid(np.arange(-2.5,2.501,.05),np.arange(100.,103.001,.05))
    xy = wall_centre + along.ravel()[:,None]*axis
    provider.cloud = CloudData(np.column_stack((xy,z.ravel())))
    provider.active_branches = list('BCDJ')
    def infer(branch,image,identifier,control):
        if branch == 'D':
            logits = np.zeros((1,3,512,512),dtype=np.float32); logits[:,1] = 1
            return {'logits':logits},{}
        outputs = {'dets':np.zeros((1,300,4),dtype=np.float32),
                   'labels':np.full((1,300,3 if branch=='J' else 2 if branch=='B' else 1),-20.,dtype=np.float32)}
        if branch == 'J': outputs['angles'] = np.zeros((1,300,1),dtype=np.float32)
        if branch != 'J' or identifier.endswith('_0_0_J'):
            outputs['dets'][0,0] = [.5,.75,.65,.08] if branch=='J' else [.5,.5,.8,.5]
            outputs['labels'][0,0,0] = 3.
            if branch=='B': outputs['labels'][0,0,1] = -3.
            if branch=='J': outputs['angles'][0,0,0] = -angle
        return outputs,{}
    monkeypatch.setattr(provider,'_try_image',infer)
    monkeypatch.setattr(provider,'_try_images',lambda jobs,control:[infer(*job,control) for job in jobs])
    control = SimpleNamespace(chunk_points=257,check=lambda:None)
    index = SpatialPointIndex.build(provider.cloud,memory_budget_bytes=16*1024**2,chunk_points=509)
    try:
        provider._stream_plan_tile(centre,provider.settings.level_bounds[0],'offset',index,control)
    finally: index.close()
    assert len(provider.instances)==1
    sections = [p for p in provider.proposals if p['branch'] in 'BC']
    assert {p['branch'] for p in sections} == {'B','C'}
    perpendicular = np.array([-axis[1],axis[0]])
    for item in sections:
        ends = np.asarray([item['world']['start'],item['world']['end']])
        assert np.max(np.abs((ends-wall_centre)@perpendicular)) < 1e-6
        rows = provider.proposal_support[item['id']]
        assert len(rows)>0 and np.all(rows<len(provider.cloud.points))
        assert np.max(np.abs((provider.cloud.points[rows,:2]-wall_centre)@perpendicular)) < 1e-8


def test_cancellation_terminates_inflight_parallel_wave_and_publishes_nothing(tmp_path, monkeypatch):
    from test_specialist_provider import make_provider, fixture_resolution, identity
    from punctora_core.recognition.job import run_recognition
    from punctora_core.recognition.tiling import TileSettings
    provider = make_provider(tmp_path, monkeypatch, 'slow-image')
    monkeypatch.setattr('punctora_core.recognition.specialist_provider.resolve_model_pack',
                        lambda *a,**k: fixture_resolution('DEFGH'))
    root = tmp_path/'models'
    with pytest.raises(InterruptedError, match='cancelled'):
        run_recognition(image_cloud(),identity(),provider,tmp_path/'cache',cpu_workers=4,
            tile_settings=TileSettings(maximum_context_points=10_000),
            cancelled=lambda:(root/'wave-started').exists())
    assert (root/'wave-started').exists() and provider.process is None
    assert not list((tmp_path/'cache').rglob('proposals-v1.json'))
    assert not list((tmp_path/'cache').glob('.proposal-stage-*'))

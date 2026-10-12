import pytest
from punctora_core.model import Wall, Opening
from punctora_core.wall_editing import (reconcile_observed_wall_overlaps,
                                       rehost_reconciled_openings)

def wall(identifier,start,end,plane=0):
    return Wall(identifier,'s',(start,plane),(end,plane),0,3,.2,
        'single_face_candidate',evidence_count=100,
        observed_faces=[dict(start=[start,plane],end=[end,plane],z_min=0,z_max=3,
                            original_inlier_fit_points=100,original_plane_fit_rmse_m=.002)])

def test_same_observed_plane_trims_overlap_and_preserves_tails_and_opening():
    host=wall('host',0,6);host.evidence_count=1000
    duplicate=wall('duplicate',2,8,.005)
    final,affected,replaced,report=reconcile_observed_wall_overlaps([duplicate,host])
    assert replaced=={'duplicate'} and len(final)==2
    tail=next(w for w in final if w.id!='host')
    assert tail.start[0]==pytest.approx(6) and tail.end[0]==pytest.approx(8)
    o=Opening('o','duplicate','window',1,.8,1,1.2)
    carried=rehost_reconciled_openings([o],[host,duplicate],final,replaced)
    assert carried[0].host_wall_id=='host' and carried[0].offset==pytest.approx(3)
    assert carried[0].width==o.width and report[0]['source_basis']=='refitted_original_planes'

def test_overlapping_assumed_thickness_does_not_prove_shared_source_planes():
    first,second=wall('a',0,6),wall('b',0,6,.09)
    final,affected,replaced,report=reconcile_observed_wall_overlaps([first,second])
    assert not replaced and not report and len(final)==2

def test_unfitted_or_independent_second_face_is_never_discarded():
    first,second=wall('a',0,6),wall('b',0,6,.005)
    second.observed_faces.append({**second.observed_faces[0],
                                 'start':[0,.15],'end':[6,.15]})
    assert not reconcile_observed_wall_overlaps([first,second])[2]

def test_nested_return_plane_is_retained_as_evidence_without_duplicate_volume():
    host=wall('host',0,6)
    host.classification='paired_faces';host.thickness=.3;host.evidence_count=1000
    host.observed_faces=[{**host.observed_faces[0],'start':[0,p],'end':[6,p]}
                         for p in [-.15,.15]]
    target=wall('return',2,4,.02)
    final,affected,replaced,report=reconcile_observed_wall_overlaps([host,target])
    assert replaced=={'return'} and len(final)==1
    assert len(final[0].observed_faces)==3
    assert report[0]['decision']=='contained_return_plane'

def test_original_full_height_exterior_faces_pair_only_over_common_span():
    first,second=wall('a',0,6),wall('b',4,8)
    for w,p in ((first,-.075),(second,.075)):
        w.classification='exterior_candidate';w.thickness=.3
        w.observed_faces[0]['start'][1]=p;w.observed_faces[0]['end'][1]=p
        w.observed_faces[0]['original_vertical_support_fraction']=1.
    final,affected,replaced,report=reconcile_observed_wall_overlaps([first,second])
    pair=next(w for w in final if w.classification=='paired_faces')
    assert replaced=={'a','b'} and pair.thickness==pytest.approx(.15)
    assert pair.start[0]==pytest.approx(4) and pair.end[0]==pytest.approx(6)
    assert len(final)==3 and report[0]['decision']=='measured_opposite_face_pair'
    second.observed_faces[0].pop('original_inlier_fit_points')
    assert not reconcile_observed_wall_overlaps([first,second])[2]

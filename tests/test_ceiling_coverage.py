import pytest
from shapely.geometry import box
from punctora_core.slab_zones import coverage_evidence
from punctora_core.model import BuildingModel, Slab, Storey
from punctora_core.ifc_export import create_ifc
import ifcopenshell.util.element as ue

def test_coverage_classes_are_disjoint_and_projection_is_not_measured():
    result=coverage_evidence(box(0,0,10,10),box(0,0,6,10),box(0,0,7,10))
    classes=result['coverage_classes']
    assert classes['measured']['percent']==pytest.approx(60)
    assert classes['justified_completion']['percent']==pytest.approx(10)
    assert classes['unsupported']['percent']==pytest.approx(30)
    assert sum(c['percent'] for c in classes.values())==pytest.approx(100)
    assert result['coverage_review_required']

def test_ifc_retains_the_distinction_instead_of_reporting_inference_as_measured():
    ring=[(0,0),(10,0),(10,10),(0,10)]
    evidence=coverage_evidence(box(0,0,10,10),box(0,0,6,10),box(0,0,7,10))
    model=BuildingModel('Coverage',[Storey('s','S',0,3,ring)],
        slabs=[Slab('roof','s',ring,3,.2,review_state='flagged',evidence=evidence)])
    props=ue.get_psets(create_ifc(model).by_type('IfcSlab')[0])['Punctora_Reconstruction']
    assert props['UnsupportedAreaPercent']==pytest.approx(30)
    assert props['JustifiedCompletionAreaPercent']==pytest.approx(10)
    assert props['CoverageReviewRequired'] and props['ReviewState']=='flagged'

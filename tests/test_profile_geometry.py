import pytest
from shapely.geometry import Polygon
from punctora_core.profile_geometry import clean_profile, clean_profiles
from punctora_core.model import BuildingModel, Storey, Slab
from punctora_core.ifc_export import create_ifc, write_ifc, validate_ifc


def test_zero_width_backtrack_is_removed_without_filling_a_concavity():
    vertices=[(0,0),(3,0),(3,3),(2,3),(2,2),(2.05,2),
              (2,2+1e-13),(1,2),(1,3),(0,3)]
    clean, report=clean_profile(vertices)
    assert Polygon(clean).is_valid
    assert Polygon(clean).area == pytest.approx(8,abs=1e-8)
    assert report['area_change_m2'] < 1e-8


@pytest.mark.parametrize('cleaner',[clean_profile,clean_profiles])
def test_meaningful_self_intersection_is_rejected(cleaner):
    with pytest.raises(ValueError):
        cleaner([(0,0),(3,3),(0,3),(3,0)])
    with pytest.raises(ValueError):
        cleaner([(0,0),(4,4),(0,4),(3,0)])


@pytest.mark.parametrize('offset',[0.,7_000_000.])
def test_valid_narrow_connection_preserves_every_body_in_step_safe_profiles(offset):
    from shapely import set_precision
    from shapely.geometry import box
    from shapely.ops import unary_union
    original = unary_union([box(offset,0,offset+1,1),box(offset+2,0,offset+3,1),
                            box(offset+.9,.4,offset+2.1,.4000000002)])
    assert original.is_valid and set_precision(original,1e-9).geom_type=='MultiPolygon'
    vertices = list(original.exterior.coords)[:-1]
    profiles,report = clean_profiles(vertices)
    assert len(profiles)==2
    serialized = [Polygon([(float(format(x,'.15g')),float(format(y,'.15g'))) for x,y in ring]) for ring in profiles]
    assert all(p.is_valid and not p.interiors for p in serialized)
    restored = unary_union(serialized)
    assert restored.symmetric_difference(original).area < 1e-8
    assert restored.covers(box(offset+.1,.1,offset+.9,.9))
    assert restored.covers(box(offset+2.1,.1,offset+2.9,.9))
    assert vertices == list(original.exterior.coords)[:-1]
    assert report['strategy']=='bounded_component_split' and report['output_components']==2
    assert report['area_change_m2'] < 1e-8
    assert report['contour_precision_m']==1e-9
    assert clean_profiles(vertices)==(profiles,report)


def test_single_profile_api_rejects_split_instead_of_discarding_a_component():
    from shapely.geometry import box
    from shapely.ops import unary_union
    original = unary_union([box(0,0,1,1),box(2,0,3,1),box(.9,.4,2.1,.4000000000000002)])
    assert original.is_valid
    with pytest.raises(ValueError,match='change components'):
        clean_profile(list(original.exterior.coords)[:-1])


def test_ifc_profile_round_trip_and_raw_profile_validation(tmp_path):
    ring=[(0,0),(3,0),(3,3),(2,3),(2,2),(2.05,2),
          (2,2+1e-13),(1,2),(1,3),(0,3)]
    ring,_=clean_profile(ring)
    model=BuildingModel('Contour regression',storeys=[Storey('s','S',0,3,ring)],
                        slabs=[Slab('slab','s',ring,-.2,.2)])
    report=write_ifc(model,tmp_path/'contour.ifc')
    assert report['valid'] and report['profile_errors']==[]
    file=create_ifc(model)
    profile=file.by_type('IfcArbitraryClosedProfileDef')[0]
    points=[file.create_entity('IfcCartesianPoint',Coordinates=tuple(map(float,p)))
            for p in [(0,0),(3,3),(0,3),(3,0),(0,0)]]
    profile.OuterCurve.Points=points
    assert validate_ifc(file)['profile_errors']

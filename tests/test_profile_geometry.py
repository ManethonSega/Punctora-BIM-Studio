import pytest
from shapely.geometry import Polygon
from punctora_core.profile_geometry import clean_profile, clean_profiles
from punctora_core.model import BuildingModel, Storey, Slab
from punctora_core.ifc_export import create_ifc, write_ifc, validate_ifc


@pytest.mark.parametrize('vertices,expected_area,expected_bodies',[
    ([(0,0),(1,0),(1,1),(2,1),(2,2),(1,2),(1,1),(0,1)],2.,2),
    ([(0,0),(1,0),(1.2,0),(1,0),(1,1),(2,1),(2,2),(1,2),(1,1),(0,1)],2.,2),
    ([(0,0),(4,0),(4,4),(2.0000000002,4),(2.0000000002,3),(3,3),
      (3,1),(1,1),(1,3),(2,3),(2,4),(0,4)],12.,2),
],ids=['point-touching-bodies','nested-bodies-with-backtrack','bay-closed-by-precision'])
def test_profile_representation_changes_preserve_solid_area_and_voids(vertices,expected_area,expected_bodies):
    from shapely import make_valid
    from shapely.geometry import Point
    from shapely.ops import unary_union
    original = Polygon(vertices)
    profiles,report = clean_profiles(vertices)
    bodies = [Polygon(p) for p in profiles]
    assert len(bodies)==expected_bodies
    assert all(p.is_valid and not p.interiors for p in bodies)
    union = unary_union(bodies)
    assert union.area==pytest.approx(expected_area,abs=1e-8)
    assert union.symmetric_difference(make_valid(original)).area<=report['area_budget_m2']
    assert sum(p.area for p in bodies)-union.area < 1e-12
    if expected_area==12.:
        assert not union.covers(Point(2,2))
    assert clean_profiles(vertices)==(profiles,report)


@pytest.mark.parametrize('offset',[(0.,0.),(7_000_000.,5_000_000.)])
def test_multiple_numerical_voids_partition_without_overlap_or_lost_area(offset):
    from shapely import make_valid
    from shapely.geometry import Point,box
    from shapely.ops import unary_union
    bays = unary_union([box(1,1,3,3),box(2,3,2.0000000002,6),
                        box(6,3.5,8,5.5),box(7,5.5,7.0000000002,6)])
    shape = box(0,0,10,6).difference(bays)
    vertices = [(x+offset[0],y+offset[1]) for x,y in shape.exterior.coords[:-1]]
    profiles,report = clean_profiles(vertices)
    bodies = [Polygon(ring) for ring in profiles]
    union = unary_union(bodies)
    assert len(bodies)==3 and report['partitioned_voids']==2
    assert all(p.is_valid and not p.interiors for p in bodies)
    assert union.symmetric_difference(make_valid(Polygon(vertices))).area<=report['area_budget_m2']
    assert sum(p.area for p in bodies)-union.area < 1e-8
    assert not union.covers(Point(2+offset[0],2+offset[1]))
    assert not union.covers(Point(7+offset[0],4.5+offset[1]))


@pytest.mark.parametrize('count',[3,8193])
def test_profile_error_captures_exact_bounded_geometry_without_large_payload(count):
    import hashlib,json
    from punctora_core.profile_geometry import ProfileGeometryError
    vertices = [(0.,0.)]*count
    with pytest.raises(ProfileGeometryError) as failure:
        clean_profiles(vertices)
    diagnostic = failure.value.diagnostics
    assert diagnostic['input_vertices']==count and diagnostic['reason']=='zero_area'
    assert diagnostic['input_geometry_sha256']==hashlib.sha256(Polygon(vertices).wkb).hexdigest()
    assert ('original_wkb_hex' in diagnostic)==(count<=8192)
    assert diagnostic['capture']==('complete' if count<=8192 else 'omitted_above_8192_vertices')
    json.dumps(diagnostic,allow_nan=False)


@pytest.mark.parametrize('operation',['simplify','union','symmetric_difference'])
def test_native_geometry_failure_retains_original_contour(monkeypatch,operation):
    from shapely.errors import GEOSException
    import punctora_core.profile_geometry as geometry
    vertices = [(0,0),(2,0),(2,2),(0,2)]
    def fail(*args,**kwargs):
        raise GEOSException('native topology failure')
    if operation=='union':
        monkeypatch.setattr(geometry,'unary_union',fail)
    else:
        monkeypatch.setattr(Polygon,operation,fail)
    with pytest.raises(geometry.ProfileGeometryError,match='native topology failure') as failure:
        clean_profiles(vertices)
    assert failure.value.diagnostics['original_wkb_hex']==Polygon(vertices).wkb_hex
    assert failure.value.diagnostics['reason']=='geos_processing'


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

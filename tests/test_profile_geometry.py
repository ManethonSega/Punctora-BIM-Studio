import pytest
from shapely.geometry import Polygon
from punctora_core.profile_geometry import clean_profile
from punctora_core.model import BuildingModel, Storey, Slab
from punctora_core.ifc_export import create_ifc, write_ifc, validate_ifc


def test_zero_width_backtrack_is_removed_without_filling_a_concavity():
    vertices=[(0,0),(3,0),(3,3),(2,3),(2,2),(2.05,2),
              (2,2+1e-13),(1,2),(1,3),(0,3)]
    clean, report=clean_profile(vertices)
    assert Polygon(clean).is_valid
    assert Polygon(clean).area == pytest.approx(8,abs=1e-8)
    assert report['area_change_m2'] < 1e-8


def test_meaningful_self_intersection_is_rejected():
    with pytest.raises(ValueError):
        clean_profile([(0,0),(3,3),(0,3),(3,0)])


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

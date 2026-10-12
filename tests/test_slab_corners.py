from shapely.geometry import box,Point
from punctora_core.model import Wall
from punctora_core.reconstruction import ReconstructionSettings
from punctora_core.slab_corners import complete_wall_corners


def walls(corner=(0,0),ends=((4,0),(0,4)),measured=True):
    return [Wall(str(i),'s',corner,end,0,3,.2,evidence_count=1000,observed_faces=[dict(
        start=corner,end=end,z_min=0,z_max=3,original_inlier_fit_points=1000 if measured else 0,
        original_plane_fit_rmse_m=.003)]) for i,end in enumerate(ends)]


def test_supported_occluded_corner_is_completed_without_filling_real_void():
    shape=box(0,0,4,4).difference(box(0,0,.25,.25)).difference(box(1,1,2,2))
    result,added,reports=complete_wall_corners(shape,walls(),0,ReconstructionSettings(),'s')
    assert result.covers(Point(.05,.05)) and not result.covers(Point(1.5,1.5))
    assert added.area>0 and reports[0]['status']=='inferred_completion'


def test_real_concave_setback_and_unobserved_walls_are_preserved():
    shape=box(0,0,4,4).difference(box(2,2,4,4))
    result,added,reports=complete_wall_corners(shape,walls((2,2),((4,2),(2,4))),0,ReconstructionSettings(),'s')
    assert result.equals(shape) and added.is_empty
    missing=box(0,0,4,4).difference(box(0,0,.25,.25))
    result,added,reports=complete_wall_corners(missing,walls(measured=False),0,ReconstructionSettings(),'s')
    assert result.equals(missing) and not reports


def test_large_missing_corner_remains_a_review_item():
    shape=box(0,0,4,4).difference(box(0,0,1.2,1.2))
    result,added,reports=complete_wall_corners(shape,walls(),0,ReconstructionSettings(),'s')
    assert result.equals(shape) and added.is_empty
    assert reports[0]['reason']=='gap_exceeds_bounded_completion'

import numpy as np
from punctora_core.planar_index import PlanarPointIndex
from punctora_core.reconstruction import _fit_face

def test_index_retains_every_exact_fit_point_in_original_order():
    rng=np.random.default_rng(7)
    points=rng.uniform(-5,5,(30000,3))
    index=PlanarPointIndex(points)
    for a,b in [((-4,-3),(4,3)),((1,1),(1,4)),((-4,0),(4,0))]:
        radius=.05;ids=index.near_segment(a,b,radius)
        d=np.array(b,dtype=float)-a;length=np.linalg.norm(d);d/=length;n=np.array([-d[1],d[0]])
        xy=points[:,:2]-a
        exact=np.flatnonzero((abs(xy@n)<=radius)&(xy@d>=-radius)&(xy@d<=length+radius))
        assert set(exact)<=set(ids) and np.all(np.diff(ids)>0)
        full=_fit_face([a,b],points,radius);local=_fit_face([a,b],points[ids],radius)
        if full is not None:
            assert full[1]==local[1]
            np.testing.assert_allclose(full[0],local[0],atol=1e-12)

def test_huge_extent_falls_back_without_losing_records():
    points=np.array([[0.,0.,0.],[1e6,1e6,0.]])
    np.testing.assert_array_equal(PlanarPointIndex(points).near_segment((0,0),(1,1),.1),[0,1])

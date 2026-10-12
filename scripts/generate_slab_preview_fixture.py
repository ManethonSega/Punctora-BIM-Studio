"""Write a small generated hole-bearing model for native preview CI."""
import json
from pathlib import Path
import sys
from punctora_core.benchmark import benchmark_fixture
from punctora_core.reconstruction import reconstruct
from punctora_core.model import Landing, SlabOpening, Wall, Opening

path = Path(sys.argv[1])
cloud, _, _ = benchmark_fixture("void")
model = reconstruct(cloud)
model._spatial_index.close()
assert model.slab_openings, "Fixture must exercise real slab holes"
# Real clipped contours include sub-float-width spikes and adjacent repeated
# vertices. Native rendering must use the robust derived mesh for these too.
contours = json.loads((Path(__file__).parents[1] / "tests/fixtures/preview_contours.json").read_text())
host = model.slabs[0]
host.footprint = [(-5, -5), (5, -5), (5, 5), (-5, 5)]
for index, polygon in enumerate(contours["slab_openings"]):
    model.slab_openings.append(SlabOpening(f"contour-void-{index}", host.id,
        (0, 0), (1, 0), .1, footprint=polygon, ifc_cut_approved=True))
for index, polygon in enumerate(contours["landings"]):
    model.landings.append(Landing(f"contour-landing-{index}", host.storey_id, polygon, 1.5))
model.walls.append(Wall('profile-wall',host.storey_id,(10,0),(14,0),0,3,.2,
    profile_xz=[[0,0],[4,0],[4,2],[1,2],[1,3],[0,3]]))
model.openings.append(Opening('profile-window','profile-wall','window',2,.5,.8,1))
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(model.to_dict()), encoding="utf-8")

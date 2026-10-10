"""Write a small generated hole-bearing model for native preview CI."""
import json
from pathlib import Path
import sys
from punctora_core.benchmark import benchmark_fixture
from punctora_core.reconstruction import reconstruct
from punctora_core.model import Landing, SlabOpening

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
        (0, 0), (1, 0), .1, footprint=polygon))
for index, polygon in enumerate(contours["landings"]):
    model.landings.append(Landing(f"contour-landing-{index}", host.storey_id, polygon, 1.5))
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(model.to_dict()), encoding="utf-8")

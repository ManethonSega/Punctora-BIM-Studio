"""Write a small generated hole-bearing model for native preview CI."""
import json
from pathlib import Path
import sys
from punctora_core.benchmark import benchmark_fixture
from punctora_core.reconstruction import reconstruct

path = Path(sys.argv[1])
cloud, _, _ = benchmark_fixture("void")
model = reconstruct(cloud)
assert model.slab_openings, "Fixture must exercise real slab holes"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(model.to_dict()), encoding="utf-8")

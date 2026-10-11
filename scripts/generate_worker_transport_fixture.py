"""A valid project larger than the old desktop worker line budget."""
from pathlib import Path
import sys
import uuid
from punctora_core import projects

path = Path(sys.argv[1]).resolve()
project_id = uuid.uuid4().hex
root = projects.ensure_assets(path, project_id)
(root / "preview.bin").write_bytes(bytes(24))
projects.atomic_json(path, {
    "schema_version": 1, "project_id": project_id, "revision": uuid.uuid4().hex,
    "name": "Large worker transfer", "assets_directory": root.name,
    "generations": [], "model": None, "crop": None, "model_crop": None,
    "preview": {"format": "xyzrgb-f32-le", "point_count": 1, "path": "preview.bin"},
    "warnings": ["x" * (20 * 1024 * 1024)],
    "transport_probe": {"record_id": 2**53+17, "coordinate": 125.123456789},
})

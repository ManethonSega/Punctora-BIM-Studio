"""Reproducible local validation against an imported E57 cache.

Customer scans and generated geometry are not committed to the repository.
Use --full-reconstruction to exercise the complete pipeline and IFC export.
"""
import argparse
import json
from pathlib import Path
import time
import numpy as np

from punctora_core.cloud_io import CloudData
from punctora_core.ifc_export import write_ifc
from punctora_core.model import BuildingModel
from punctora_core.reconstruction import ReconstructionSettings, reconstruct, streaming_level_sample
from punctora_core.slab_zones import detect_slab_zones, slab_zone_geometry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--full-reconstruction", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    descriptor = manifest["cache"]["files"]["points"]
    path = args.manifest.parent/"working-cache"/descriptor["path"]
    shape = tuple(descriptor["shape"])
    if path.stat().st_size != int(np.prod(shape))*np.dtype(descriptor["dtype"]).itemsize:
        raise ValueError("Imported point channel is truncated")
    points = np.memmap(path, mode="r", dtype=descriptor["dtype"], shape=shape)
    settings = ReconstructionSettings()
    started = time.perf_counter()
    cloud = CloudData(points, metadata={"coordinate_frame": "E57-derived local metres"})
    if args.full_reconstruction:
        model = reconstruct(cloud, settings, progress=lambda percent, message: print(percent, message, flush=True))
    else:
        sample, stats = streaming_level_sample(points, settings)
        levels, zones, surfaces, report = detect_slab_zones(sample, settings)
        slabs, holes = slab_zone_geometry(zones, surfaces, levels, settings)
        model = BuildingModel("Slab evidence verification", levels, slabs=slabs, slab_openings=holes,
                              metadata={"slab_zones": report, "level_detection": stats})
    model.metadata["source"] = manifest["source"]
    model.metadata["coordinate_mapping"] = manifest["coordinate_mapping"]
    model.validate()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    validation = write_ifc(model, args.output_dir/"model.ifc")
    (args.output_dir/"elements.json").write_text(json.dumps(model.to_dict(), indent=2), encoding="utf-8")
    translation = manifest["coordinate_mapping"]["working_to_source_translation_m"][2]
    zones = [c for c in model.metadata["slab_zones"]["candidates"] if c["selected"]]
    report = {"source_points": len(points), "seconds": time.perf_counter()-started,
              "storeys": len(model.storeys), "zones": len(zones), "slab_components": len(model.slabs),
              "observed_holes": len(model.slab_openings), "full_reconstruction": args.full_reconstruction,
              "source_elevation_zones_m": [[c["bottom_m"]+translation,c["top_m"]+translation] for c in zones],
              "slab_support": [{"id":s.id, **s.evidence} for s in model.slabs],
              "ifc_validation": validation,
              "scope": "algorithm/IFC checks; no independently annotated survey ground truth"}
    if args.full_reconstruction:
        hosts = {w.id:w for w in model.walls}
        report['wall_verification'] = {
            'walls':len(model.walls), 'openings':len(model.openings),
            'multi_slice_walls':sum(w.detection_method == 'multi_slice' for w in model.walls),
            'endpoint_status_counts':{status:sum(t['connectivity']['counts'].get(status,0)
                for t in model.metadata['wall_topology']) for status in
                ('supported_corner','supported_t_junction','unresolved_gap','rejected_correction','intentional_open_end')},
            'opening_hosts':[{'wall_id':w.id,'storey_id':w.storey_id,'start':w.start,'end':w.end,
                'openings':[{'id':o.id,'kind':o.kind,'offset':o.offset,'width':o.width,'sill':o.sill,'height':o.height,
                            'evidence':o.evidence} for o in model.openings if o.host_wall_id == w.id]}
                for w in hosts.values() if any(o.host_wall_id == w.id for o in model.openings)]}
    (args.output_dir/"slab-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in {"slab_support","ifc_validation"}}, indent=2))


if __name__ == "__main__":
    main()

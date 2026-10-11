import numpy as np
import pytest
from shapely.geometry import Polygon, Point

from punctora_core.cloud_io import CloudData
from punctora_core.model import BuildingModel
from punctora_core.reconstruction import ReconstructionSettings, reconstruct
from punctora_core.sampling import DetectionSample
from punctora_core.slab_zones import detect_slab_zones, occupancy_geometry, slab_zone_geometry


def planes(levels, shape=None):
    xy = np.array([(x, y) for x in np.arange(0, 6.01, .04) for y in np.arange(0, 4.01, .04)])
    if shape:
        xy = np.array([p for p in xy if shape.covers(Point(p))])
    points = np.concatenate([np.column_stack([xy, np.full(len(xy), z)]) for z in levels])
    return DetectionSample(points, np.arange(len(points)), .04, len(points))


def test_zone_sequence_rejects_landings_and_pairs_faces():
    sample = planes([0., 2.8, 3., 6., 6.3, 9.4, 9.6, 12.7])
    xy = np.array([(x, y) for x in np.arange(1, 2.2, .04) for y in np.arange(1, 2.2, .04)])
    patches = np.concatenate([np.column_stack([xy, np.full(len(xy), z)]) for z in (4.1, 4.5, 8.0)])
    points = np.concatenate([sample.points, patches])
    sample = DetectionSample(points, np.arange(len(points)), .04, len(points))
    levels, zones, surfaces, report = detect_slab_zones(sample, ReconstructionSettings())
    assert len(zones) == 5 and len(levels) == 4
    assert [(s.elevation, s.ceiling) for s in levels] == pytest.approx([(0, 2.8), (3, 6), (6.3, 9.4), (9.6, 12.7)])
    assert all(z["paired"] for z in zones[1:-1])
    assert all(c["rejection_reasons"] for c in report["candidates"] if not c["selected"])
    assert all(0 <= idx < len(points) for c in report["candidates"] for idx in c["source_point_evidence"]["lower_working_indices"])


def test_occupancy_keeps_concavity_components_and_large_hole():
    shape = Polygon([(0,0),(6,0),(6,2),(4,2),(4,4),(0,4)],
                    holes=[[(1,1),(2,1),(2,2),(1,2)]])
    sample = planes([0, 3], shape)
    geometry, raw = occupancy_geometry(sample.points[:len(sample.points)//2, :2], .08, .16, 1_000_000)
    assert not geometry.covers(Point(5,3))
    assert not geometry.covers(Point(1.5,1.5))
    second = np.array([(x,y) for x in np.arange(8,9,.04) for y in np.arange(0,1,.04)])
    geometry, _ = occupancy_geometry(np.concatenate([sample.points[:len(sample.points)//2,:2],second]), .08,.16,1_000_000)
    assert len(geometry.geoms) == 2


def test_slab_holes_persist_without_stair_enlargement():
    shape = Polygon([(0,0),(6,0),(6,4),(0,4)], holes=[[(2,1),(4,1),(4,3),(2,3)]])
    sample = planes([0,2.8,3,6],shape)
    settings = ReconstructionSettings()
    levels,zones,surfaces,report = detect_slab_zones(sample,settings)
    slabs,holes = slab_zone_geometry(zones,surfaces,levels,settings)
    assert len(slabs) == 3 and len(holes) == 3
    assert all(h.source_stair_id is None for h in holes)
    assert all(h.evidence["stairwell_state"] == "pending_stair_system_validation" for h in holes)
    assert any(h.evidence["classification"] == "observed_hole" for h in holes)
    for slab in slabs:
        assert slab.evidence["supported_percent"]+slab.evidence["inferred_percent"] == pytest.approx(100)
        assert slab.evidence["supported_area_m2"]+slab.evidence["inferred_area_m2"] == pytest.approx(slab.evidence["net_polygon_area_m2"])
    model = BuildingModel("test",levels,slabs=slabs,slab_openings=holes)
    model.validate()
    restored = BuildingModel.from_dict(model.to_dict())
    assert restored.slabs[0].evidence == slabs[0].evidence
    assert restored.slab_openings[0].footprint == holes[0].footprint


def test_no_sequence_is_invented_from_one_patch():
    with pytest.raises(ValueError,match="two supported"):
        detect_slab_zones(planes([1.]),ReconstructionSettings())


def test_slab_settings_validate():
    for kwargs in ({"slab_minimum_face_overlap":1.1},{"slab_minimum_area_fraction":1.1},
                   {"slab_minimum_thickness_m":.7},{"slab_close_gap_m":0}):
        with pytest.raises(ValueError):
            ReconstructionSettings(**kwargs).validate()


def test_crop_zone_evidence_maps_back_to_immutable_source_rows(tmp_path):
    from punctora_core.cropping import materialize_crop
    sample = planes([0, 2.8, 3, 6])
    crop, _ = materialize_crop(CloudData(sample.points),
        {"polygon": [[1,0],[6,0],[6,4],[1,4]]}, tmp_path/"crop", chunk_points=2000)
    settings = ReconstructionSettings(detect_openings_enabled=False, detect_stairs_enabled=False)
    model = reconstruct(crop, settings)
    valid = set(crop.working_index.tolist())
    indices = [i for c in model.metadata["slab_zones"]["candidates"]
               for i in c["source_point_evidence"]["lower_working_indices"]]
    assert indices and set(indices).issubset(valid)


def test_single_face_polygon_holes_remain_review_only(tmp_path):
    import ifcopenshell
    from punctora_core.ifc_export import write_ifc
    shape = Polygon([(0,0),(6,0),(6,4),(0,4)],holes=[[(2,1),(4,1),(4,3),(2,3)]])
    settings = ReconstructionSettings()
    levels,zones,surfaces,_ = detect_slab_zones(planes([0,3],shape),settings)
    slabs,holes = slab_zone_geometry(zones,surfaces,levels,settings)
    model = BuildingModel("test",levels,slabs=slabs,slab_openings=holes)
    write_ifc(model,tmp_path/"model.ifc")
    file = ifcopenshell.open(str(tmp_path/"model.ifc"))
    assert len(holes) == 2
    assert not file.by_type("IfcRelVoidsElement")
    for slab in file.by_type("IfcSlab"):
        assert not slab.HasOpenings


def test_preview_mesh_rebuilds_after_void_edit_and_rejection():
    from punctora_core.model import Slab, SlabOpening, Storey
    storey = Storey("s","s",0,3,[(0,0),(6,0),(6,4),(0,4)])
    slab = Slab("slab","s",storey.footprint,0,.2)
    hole = SlabOpening("hole","slab",(2,2),(4,2),2, ifc_cut_approved=True)
    model = BuildingModel("mesh",[storey],slabs=[slab],slab_openings=[hole])
    def area():
        mesh=model.to_dict()["slabs"][0]["preview_geometry"]
        return sum(Polygon(t).area for t in mesh["surface_triangles_xy"])
    assert area() == pytest.approx(20)
    hole.width=1
    assert area() == pytest.approx(22)
    hole.review_state="rejected"
    assert area() == pytest.approx(24)

"""Evidence-keyed ElementGraph v1 and fail-closed hybrid artifacts."""
import numpy as np

from ..annotation_io import content_digest, file_digest, identifier, read_json, sha256, validate_identity

RELATIONS = {"hosted_by", "bounded_by", "adjacent_to", "above", "below", "connects", "part_of"}
STATES = {"proposed", "geometry_validated", "user_confirmed", "rejected", "unresolved"}


def validate_graph(graph):
    if not isinstance(graph, dict) or graph.get("schema_version") != 1 or graph.get("geometry_authority") != "review_only":
        raise ValueError("ElementGraph requires schema 1 and review-only authority")
    validate_identity(graph["identity"])
    sha256(graph.get("upstream_proposal_sha256"), "graph upstream proposal digest")
    if graph.get("graph_sha256") != content_digest({k: v for k, v in graph.items() if k != "graph_sha256"}):
        raise ValueError("ElementGraph digest changed")
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    evidence = graph.get("evidence", [])
    if any(not isinstance(value, list) for value in (nodes, edges, evidence)):
        raise ValueError("Graph nodes, edges and evidence must be lists")
    ids, proofs, edge_ids = {}, set(), set()
    for item in evidence:
        identifier(item.get("id"), "graph evidence ID")
        identifier(item.get("kind"), "graph evidence kind")
        if item["id"] in proofs:
            raise ValueError("Duplicate graph evidence ID")
        proofs.add(item["id"])
    for node in nodes:
        identifier(node.get("id"), "graph node ID")
        identifier(node.get("class"), "graph node class")
        if node["id"] in ids or node.get("status") not in STATES:
            raise ValueError("Duplicate graph node or unknown state")
        if node["status"] in {"geometry_validated", "user_confirmed"}:
            raise ValueError("Run 3 graph cannot promote proposed geometry or review decisions")
        refs = node.get("evidence_ids")
        if not isinstance(refs, list) or not refs or any(r not in proofs for r in refs):
            raise ValueError("Every graph node requires resolvable evidence")
        if node.get("cut_applied") is not False:
            raise ValueError("Run 3 graph cannot apply an opening/IFC cut")
        ids[node["id"]] = node
    tree = {key: [] for key in ids}
    for edge in edges:
        identifier(edge.get("id"), "graph edge ID")
        if edge["id"] in edge_ids or edge.get("relation") not in RELATIONS or edge.get("status") not in STATES:
            raise ValueError("Duplicate relation ID, unknown relation or state")
        edge_ids.add(edge["id"])
        if edge.get("source") not in ids or edge.get("target") not in ids or edge["source"] == edge["target"]:
            raise ValueError("Relations require two distinct existing nodes")
        if edge["status"] in {"geometry_validated", "user_confirmed"}:
            raise ValueError("Run 3 relations cannot assert accepted topology")
        refs = edge.get("evidence_ids")
        if not isinstance(refs, list) or not refs or any(r not in proofs for r in refs):
            raise ValueError("Every graph relation requires resolvable evidence")
        if edge["relation"] == "hosted_by" and (ids[edge["source"]]["class"] not in {"opening", "door", "window"}
                                                  or ids[edge["target"]]["class"] != "wall"):
            raise ValueError("Opening host proposal must reference a wall")
        if edge["relation"] in {"hosted_by", "part_of"} and edge["status"] != "rejected":
            tree[edge["source"]].append(edge["target"])
    # Iterative cycle check avoids recursion exhaustion on an invalid graph.
    seen, active = set(), set()
    for seed in tree:
        stack = [(seed, False)]
        while stack:
            row, exiting = stack.pop()
            if exiting:
                active.discard(row)
                seen.add(row)
            elif row in active:
                raise ValueError("Cyclic host/part_of relationships are invalid")
            elif row not in seen:
                active.add(row)
                stack.append((row, True))
                stack.extend((child, False) for child in reversed(tree[row]))
    return graph


def build_graph(identity, upstream_digest, instances, evidence, bay_groups=()):
    nodes, edges = [], []
    for item in instances:
        refs = item.get("evidence_ids", ["upstream:instances"])
        nodes.append({"id": item["id"], "class": item["class"], "status": "unresolved" if item.get("classification_state") == "conflicting" else "proposed",
                      "evidence_ids": refs, "cut_applied": False})
        target = item.get("host_id") or item.get("context_wall_id")
        if target:
            relation = "hosted_by" if item.get("host_id") else "adjacent_to"
            edge = {"source": item["id"], "target": target, "relation": relation, "status": "proposed", "evidence_ids": refs}
            edges.append({"id": "edge:" + content_digest(edge)[:24], **edge})
    for group in bay_groups:
        members = group["member_ids"]
        for a, b in zip(members, members[1:]):
            refs = next(i["evidence_ids"] for i in instances if i["id"] == a)
            edge = {"source": a, "target": b, "relation": "adjacent_to", "status": "proposed", "evidence_ids": refs}
            edges.append({"id": "edge:" + content_digest(edge)[:24], **edge})
    graph = {"schema_version": 1, "identity": identity, "geometry_authority": "review_only",
             "upstream_proposal_sha256": upstream_digest, "nodes": sorted(nodes, key=lambda n: n["id"]),
             "edges": sorted(edges, key=lambda e: e["id"]), "evidence": sorted(evidence, key=lambda e: e["id"]),
             "bay_groups": list(bay_groups)}
    graph["graph_sha256"] = content_digest(graph)
    return validate_graph(graph)


def validate_hybrid_artifacts(manifest, directory, verify_arrays=True, cancelled=lambda: False):
    from .contracts import safe_artifact_path
    hybrid = manifest["extensions"]["hybrid_v1"]
    if hybrid.get("schema_version") != 1 or hybrid.get("cut_policy") != "no_cuts_before_run4_host_validation":
        raise ValueError("Unsupported hybrid contract or unsafe cut policy")
    sha256(hybrid.get("upstream_proposal_sha256"), "hybrid upstream digest")
    artifacts = hybrid.get("artifacts", [])
    paths = set()
    for item in artifacts:
        path = safe_artifact_path(directory, item["path"])
        if item["path"] in paths:
            raise ValueError("Duplicate hybrid artifact path")
        paths.add(item["path"])
        sha256(item.get("sha256"), "hybrid artifact digest")
        if verify_arrays and file_digest(path, cancelled=cancelled) != item["sha256"]:
            raise ValueError("Hybrid artifact digest changed")
        if "dtype" in item and verify_arrays:
            value = np.load(path, mmap_mode="r", allow_pickle=False)
            try:
                if value.dtype.str != item["dtype"] or list(value.shape) != item["shape"]:
                    raise ValueError("Hybrid artifact array layout changed")
                for begin in range(0, len(value), 65536):
                    if cancelled(): raise InterruptedError("Hybrid validation cancelled")
                    block = value[begin:begin + 65536]
                    if item.get("role") == "source_rows" and (value.dtype != np.dtype("<u8") or np.any(block >= manifest["source_point_count"])):
                        raise ValueError("Hybrid evidence lost its exact original row identity")
            finally:
                value._mmap.close()
    if hybrid.get("projection_manifest_path") not in paths:
        raise ValueError("Wall projections must be a fingerprinted hybrid artifact")
    projections = read_json(safe_artifact_path(directory, hybrid["projection_manifest_path"]))
    if projections.get("schema_version") != 1 or projections.get("identity") != manifest["identity"]:
        raise ValueError("Projection source/crop/mapping identity changed")
    from .wall_projection import wall_frames
    instance_by_id = {item["id"]: item for item in manifest["instances"]}
    view_by_id = {}
    descriptors = {item["path"]: item for item in artifacts}
    for view in projections.get("views", []):
        frame = view["frame"]
        host = instance_by_id.get(frame.get("host_id"))
        if host is None or host["class"] != "wall":
            raise ValueError("Projection references a missing/nonwall host")
        expected = next((f for f in wall_frames(host, frame["cell_m"]) if f.id == view["id"]), None)
        if expected is None or expected.to_dict() != frame or view["id"] in view_by_id:
            raise ValueError("Projection frame is inconsistent, duplicated or not reversible")
        view_by_id[view["id"]] = view
        layouts = {"face_counts": ("<u4", list(expected.shape)), "return_counts": ("<u4", list(expected.shape)),
                   "signed_depth_m": ("<f8", list(expected.shape)), "rgb": ("<f8", [*expected.shape, 3]),
                   "rgb_valid": ("|b1", list(expected.shape)), "source_rows": ("<u8", None),
                   "pixel_ids": ("<u4", None), "face_distances_m": ("<f8", None)}
        if set(view.get("arrays", {})) != set(layouts):
            raise ValueError("Projection lacks occupancy/depth/RGB or original pixel associations")
        count = None
        for name, (dtype, shape) in layouts.items():
            descriptor = descriptors.get(view["arrays"][name], {})
            if descriptor.get("dtype") != dtype or (shape is not None and descriptor.get("shape") != shape):
                raise ValueError("Projection image layout disagrees with its frame")
            if shape is None:
                layout = descriptor.get("shape", [])
                if len(layout) != 1 or not isinstance(layout[0], int) or not 0 <= layout[0] <= manifest["source_point_count"]:
                    raise ValueError("Projection source map requires one row per original return")
                if count is not None and count != layout[0]:
                    raise ValueError("Projection original rows/pixels/depth lengths differ")
                count = layout[0]
        if verify_arrays:
            maps = {}
            try:
                for name in view["arrays"]:
                    maps[name] = np.load(safe_artifact_path(directory, view["arrays"][name]), mmap_mode="r", allow_pickle=False)
                pixels, distances = maps["pixel_ids"], maps["face_distances_m"]
                if np.any(pixels >= expected.shape[0] * expected.shape[1]) or not np.isfinite(distances).all() or np.any(distances < 0):
                    raise ValueError("Projection pixel map/depth is invalid")
                if not np.array_equal(np.bincount(pixels, minlength=maps["return_counts"].size), maps["return_counts"].ravel()):
                    raise ValueError("Projection occupancy no longer matches original pixel associations")
                occupied = maps["return_counts"] > 0
                if not np.isfinite(maps["signed_depth_m"][occupied]).all() or not np.isnan(maps["signed_depth_m"][~occupied]).all():
                    raise ValueError("Unobserved projection cells require explicit unknown depth")
                if not np.isfinite(maps["rgb"]).all() or np.any(maps["face_counts"] > maps["return_counts"]):
                    raise ValueError("Projection face counts or RGB are invalid")
            finally:
                for value in maps.values(): value._mmap.close()
    if hybrid.get("graph_path") not in paths:
        raise ValueError("Graph must be a fingerprinted hybrid artifact")
    graph = validate_graph(read_json(safe_artifact_path(directory, hybrid["graph_path"])))
    if graph["identity"] != manifest["identity"] or graph["upstream_proposal_sha256"] != hybrid["upstream_proposal_sha256"]:
        raise ValueError("Graph source/crop/mapping identity changed")
    instances = {i["id"]: i for i in manifest["instances"]}
    if {n["id"]: n["class"] for n in graph["nodes"]} != {key: value["class"] for key, value in instances.items()}:
        raise ValueError("Graph instances disagree with ProposalSet")
    for item in graph["evidence"]:
        if item.get("source_rows_path") and item["source_rows_path"] not in paths:
            raise ValueError("Graph evidence references an unfingerprinted source array")
        if item.get("source_rows_path") and (descriptors[item["source_rows_path"]].get("role") != "source_rows"
                or descriptors[item["source_rows_path"]].get("shape") != [item["source_support_count"]]):
            raise ValueError("Evidence support count disagrees with its exact original rows")
        if item.get("frame_id"):
            view = view_by_id.get(item["frame_id"])
            if view is None:
                raise ValueError("Evidence references a missing wall view")
            mask = descriptors.get(item.get("pixel_mask_path"), {})
            if mask.get("dtype") != "|b1" or mask.get("shape") != view["frame"]["shape"]:
                raise ValueError("Evidence mask does not match its wall view")
            if any(descriptors.get(item.get(name), {}).get("role") != "source_rows" for name in ("interior_rows_path", "frame_rows_path")):
                raise ValueError("Evidence lacks exact filling/frame source arrays")
    if verify_arrays:
        selected = np.load(safe_artifact_path(directory, manifest["arrays"]["selected"]["path"]), mmap_mode="r", allow_pickle=False)
        try:
            for descriptor in artifacts:
                if descriptor.get("role") != "source_rows": continue
                rows = np.load(safe_artifact_path(directory, descriptor["path"]), mmap_mode="r", allow_pickle=False)
                try:
                    for begin in range(0, len(rows), 65536):
                        if cancelled(): raise InterruptedError("Hybrid validation cancelled")
                        if not selected[rows[begin:begin + 65536]].all():
                            raise ValueError("Hybrid evidence points escape the declared crop")
                finally: rows._mmap.close()
        finally: selected._mmap.close()
    for item in instances.values():
        if item.get("host_validation_state") and (item["host_validation_state"] != "pending_run4" or item.get("cut_applied") is not False):
            raise ValueError("Hybrid opening bypassed host validation")
    return hybrid

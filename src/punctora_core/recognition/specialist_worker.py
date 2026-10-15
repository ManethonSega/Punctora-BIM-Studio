"""Isolated ONNX Runtime worker for Punctora specialist branches A through J.

Exit 20 means the explicit runtime/provider is unavailable.  Exit 21 means an
asset, tensor or graph contract is malformed.  The worker never downloads,
installs, accepts geometry or writes IFC.
"""
from importlib import metadata
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import gc
import hashlib
import json
from pathlib import Path
import sys
import time


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":")), encoding="utf-8")


def runtime_options(request, branch):
    plan = request.get("runtime_plan")
    if plan is None:  # Readable legacy worker requests retain their old contract.
        return 2, True
    budget = plan.get("cpu_budget")
    lanes = plan.get("image_workers")
    image = plan.get("image_intra_op_threads")
    point = plan.get("point_intra_op_threads")
    if (any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in (budget, lanes, image, point))
            or lanes > 5 or lanes * image > budget or point > budget
            or type(plan.get("inter_op_threads")) is not int or plan.get("inter_op_threads") != 1
            or plan.get("execution_mode") != "sequential"
            or plan.get("allow_spinning") is not False):
        raise ValueError("Specialist runtime CPU budget is malformed or oversubscribed")
    return (point if branch == "I" else image), False


def session_options(ort, request=None, branch="I"):
    options = ort.SessionOptions()
    threads, spinning = runtime_options(request or {}, branch)
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.log_severity_level = 3
    options.add_session_config_entry("session.intra_op.allow_spinning", "1" if spinning else "0")
    options.add_session_config_entry("session.inter_op.allow_spinning", "0")
    return options


def expected_point_names():
    result = {"feat"}
    blocks = (2, 2, 2, 6, 2)
    for stage in range(5):
        result.update({f"s{stage}_gc", f"s{stage}_k3"})
        if stage == 0:
            result.add("s0_k5")
        for order in range(min(4, blocks[stage])):
            result.update({f"s{stage}_o{order}_win", f"s{stage}_o{order}_inv"})
        if stage < 4:
            result.add(f"p{stage}_cluster")
    return result


def _static_shape_matches(actual, expected):
    if len(actual) != len(expected):
        return False
    for observed, wanted in zip(actual, expected):
        if isinstance(wanted, int) and isinstance(observed, int) and observed != wanted:
            return False
    return True


def verify_session(branch, contract, session):
    inputs, outputs = session.get_inputs(), session.get_outputs()
    actual_inputs, actual_outputs = {value.name: value for value in inputs}, {value.name: value for value in outputs}
    if branch == "I":
        if set(actual_inputs) != expected_point_names() or len(actual_inputs) != 40:
            raise ValueError("Branch I graph does not expose the reviewed 40-input contract")
    else:
        expected_inputs = {value["name"] for value in contract["inputs"]}
        if set(actual_inputs) != expected_inputs:
            raise ValueError(f"Branch {branch} graph input names changed")
    expected_outputs = {value["name"] for value in contract["outputs"]}
    if set(actual_outputs) != expected_outputs:
        raise ValueError(f"Branch {branch} graph output names changed")
    for specification in contract["inputs"]:
        if specification["name"] == "39 validated index arrays":
            continue
        value = actual_inputs[specification["name"]]
        expected_type = "tensor(float)" if specification["dtype"] == "float32" else "tensor(int64)"
        if value.type != expected_type or not _static_shape_matches(value.shape, specification["shape"]):
            raise ValueError(f"Branch {branch} input tensor schema changed")
    for specification in contract["outputs"]:
        value = actual_outputs[specification["name"]]
        expected_type = "tensor(float)" if specification["dtype"] == "float32" else "tensor(int64)"
        if value.type != expected_type or not _static_shape_matches(value.shape, specification["shape"]):
            raise ValueError(f"Branch {branch} output tensor schema changed")


def load_session(ort, request, branch, sessions=None):
    contract = request["manifest"]["branches"][branch]
    root = Path(request["model_root"])
    key = (str(root.resolve()), branch, contract["graph_sha256"], contract.get("companion_sha256"),
           runtime_options(request, branch))
    if sessions is not None and key in sessions:
        session = sessions.pop(key)
        sessions[key] = session
        return session
    graph = root / contract["graph"]
    if digest(graph) != contract["graph_sha256"]:
        raise ValueError(f"Branch {branch} graph changed after provider admission")
    if contract.get("companion"):
        companion = root / contract["companion"]
        if digest(companion) != contract["companion_sha256"]:
            raise ValueError(f"Branch {branch} companion changed after provider admission")
    if sessions is not None:
        limit = request.get("maximum_cached_sessions", 1)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
            raise ValueError("Specialist session-cache limit must be an integer from one through ten")
        while len(sessions) >= limit:
            sessions.popitem(last=False)
            gc.collect()
    session = ort.InferenceSession(str(graph), sess_options=session_options(ort, request, branch),
                                   providers=["CPUExecutionProvider"])
    verify_session(branch, contract, session)
    if sessions is not None:
        sessions[key] = session
    return session


def preflight(ort, request, sessions=None):
    active, details = [], {}
    for branch in request["active_branches"]:
        session = load_session(ort, request, branch, sessions)
        details[branch] = {"inputs": [value.name for value in session.get_inputs()],
                           "outputs": [value.name for value in session.get_outputs()],
                           "providers": session.get_providers()}
        active.append(branch)
        del session
        gc.collect()
    return {"schema_version": 1, "status": "complete", "active_branches": active,
            "runtime": {"id": "onnxruntime", "version": metadata.version("onnxruntime"),
                        "requested_provider": "CPUExecutionProvider",
                        "actual_provider": "CPUExecutionProvider",
                        "worker_protocol": "persistent-json-lines-v1",
                        "runtime_plan": request.get("runtime_plan"),
                        "maximum_cached_sessions": request.get("maximum_cached_sessions", 1)},
            "contracts": details}


def image_tensor(branch, image):
    import cv2
    import numpy as np
    image = np.asarray(image)
    if image.dtype != np.uint8 or image.ndim not in (2, 3):
        raise ValueError("Specialist image must be a uint8 grayscale or BGR array")
    if branch in {"A", "B", "C"}:
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (560, 560), interpolation=cv2.INTER_LINEAR)
        return np.repeat((resized.astype(np.float32) / 255.)[None, None], 3, axis=1)
    if branch in {"D", "E", "F", "G", "H"}:
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (512, 512), interpolation=cv2.INTER_LINEAR)
        return ((resized.astype(np.float32) / 255. - .5) / .5)[None, None]
    if branch == "J":
        from PIL import Image
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("Branch J requires the declared BGR overlay")
        # Pillow resizes the supplied byte planes without reordering them, so
        # the graph still receives the audited B/G/R channel positions.
        resized = np.asarray(Image.fromarray(image).resize((576, 576), Image.Resampling.BILINEAR),
                             dtype=np.float32) / 255.
        mean = np.array([.485, .456, .406], dtype=np.float32)[:, None, None]
        std = np.array([.229, .224, .225], dtype=np.float32)[:, None, None]
        return ((resized.transpose(2, 0, 1) - mean) / std)[None]
    raise ValueError("Unknown specialist image branch")


def infer_image(ort, request, sessions=None, session=None):
    import numpy as np
    started = time.monotonic()
    branch = request["branch"]
    if session is None:
        session = load_session(ort, request, branch, sessions)
    loaded = time.monotonic()
    tensor = np.load(request["tensor"], allow_pickle=False)
    expected = ((1, 3, 560, 560) if branch in {"A", "B", "C"} else
                (1, 1, 512, 512) if branch in {"D", "E", "F", "G", "H"} else
                (1, 3, 576, 576) if branch == "J" else None)
    if expected is None or tensor.dtype != np.float32 or tensor.shape != expected or not np.isfinite(tensor).all():
        raise ValueError("Specialist image tensor changed after host preprocessing")
    input_name = session.get_inputs()[0].name
    prepared = time.monotonic()
    arrays = session.run(None, {input_name: tensor})
    inferred = time.monotonic()
    names = [value.name for value in session.get_outputs()]
    if len(arrays) != len(names) or any(not np.isfinite(value).all() for value in arrays):
        raise ValueError("Specialist image model returned malformed or nonfinite outputs")
    output = Path(request["output"])
    np.savez(output, **dict(zip(names, arrays)))
    return {"schema_version": 1, "status": "complete", "branch": branch,
            "output": str(output), "input_shape": list(tensor.shape),
            "timings": {"session_load_seconds": loaded-started, "input_seconds": prepared-loaded,
                        "inference_seconds": inferred-prepared, "output_seconds": time.monotonic()-inferred},
            "output_shapes": {name: list(value.shape) for name, value in zip(names, arrays)}}


def infer_images(ort, request, sessions):
    """One bounded wave. Load/cache serially; execute independent runs concurrently.

    Only the server thread mutates the session LRU. No session can be evicted
    during the wave; results are returned in input order, never finish order.
    """
    jobs = request.get("jobs")
    runtime_options(request, "D")
    lanes = request["runtime_plan"]["image_workers"]
    if (not isinstance(jobs, list) or not 1 <= len(jobs) <= lanes
            or len(jobs) > request["maximum_cached_sessions"]):
        raise ValueError("Image wave exceeds the admitted concurrency/session budget")
    prepared, loads, hits = {}, {}, {}
    for job in jobs:
        if (not isinstance(job, dict) or set(job) != {"branch", "tensor", "output"}
                or job["branch"] not in set("ABCDEFGHJ")):
            raise ValueError("Malformed specialist image wave")
    if len({job['output'] for job in jobs}) != len(jobs):
        raise ValueError("Specialist image wave has duplicate output destinations")
    for job in jobs:
        branch = job["branch"]
        if branch not in prepared:
            before = set(sessions)
            started = time.monotonic()
            prepared[branch] = load_session(ort, request, branch, sessions)
            loads[branch] = time.monotonic()-started
            hits[branch] = set(sessions) == before
    def infer(job):
        try:
            return infer_image(ort, {**request, **job}, session=prepared[job["branch"]])
        except Exception as exc:
            status, error = _failure(exc)
            if status != "unavailable":
                raise
            return {"status": status, "branch": job["branch"], "error": error}
    with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="punctora-image") as executor:
        responses = list(executor.map(infer, jobs))
    for response in responses:
        branch = response["branch"]
        if response["status"] == "complete" and branch in loads:
            response["timings"]["session_load_seconds"] += loads.pop(branch)
            response["session_cache_hit"] = hits[branch]
    return {"schema_version": 1, "status": "complete", "results": responses}


def infer_point(ort, request, sessions=None):
    import numpy as np
    started = time.monotonic()
    session = load_session(ort, request, "I", sessions)
    loaded = time.monotonic()
    feed_manifest = read_json(request["feed_manifest"])
    if set(feed_manifest) != expected_point_names():
        raise ValueError("Branch I feed manifest does not contain exactly 40 tensors")
    feed = {}
    for name, path in feed_manifest.items():
        value = np.load(path, allow_pickle=False)
        expected = np.float32 if name == "feat" else np.int64
        if value.dtype != expected or not value.flags.c_contiguous:
            raise ValueError("Branch I feed tensor dtype/contiguity changed")
        feed[name] = value
    prepared = time.monotonic()
    arrays = session.run(None, feed)
    inferred = time.monotonic()
    outputs = [value.name for value in session.get_outputs()]
    if outputs != ["seg_logits"] or len(arrays) != 1:
        raise ValueError("Branch I output contract changed")
    logits = arrays[0]
    if logits.shape != (len(feed["feat"]), 12) or logits.dtype != np.float32 or not np.isfinite(logits).all():
        raise ValueError("Branch I must return finite float32 N x 12 logits")
    output = Path(request["output"])
    np.save(output, logits, allow_pickle=False)
    return {"schema_version": 1, "status": "complete", "branch": "I", "output": str(output),
            "timings": {"session_load_seconds": loaded-started, "input_seconds": prepared-loaded,
                        "inference_seconds": inferred-prepared, "output_seconds": time.monotonic()-inferred},
            "input_voxels": int(len(feed["feat"])), "output_shape": list(logits.shape)}


def execute(request, sessions=None):
    if request.get("schema_version") != 1 or request.get("mode") not in {"preflight", "image", "point", "image_batch"}:
        raise ValueError("Unsupported specialist worker request")
    if request.get("automatic_download") is not False:
        raise ValueError("Specialist worker forbids automatic downloads")
    if request.get('manifest', {}).get('runtime', {}).get('requires_runtime_plan') and not request.get('runtime_plan'):
        raise ValueError('Specialist model pack requires the explicit job CPU runtime plan')
    limit = request.get("maximum_cached_sessions")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
        raise ValueError("Specialist session-cache limit must be an integer from one through ten")
    import onnxruntime as ort
    if "CPUExecutionProvider" not in ort.get_available_providers():
        raise ImportError("ONNX Runtime CPUExecutionProvider is unavailable")
    started, cpu = time.monotonic(), time.process_time()
    if request["mode"] == "preflight":
        result = preflight(ort, request, sessions)
    elif request["mode"] == "image":
        result = infer_image(ort, request, sessions)
    elif request["mode"] == "image_batch":
        result = infer_images(ort, request, sessions if sessions is not None else OrderedDict())
    else:
        result = infer_point(ort, request, sessions)
    result["process_timing"] = {"cpu_seconds": time.process_time()-cpu,
                                "wall_seconds": time.monotonic()-started}
    return result


def _failure(exc):
    if isinstance(exc, (ImportError, metadata.PackageNotFoundError)):
        return "unavailable", "Unavailable specialist runtime: " + str(exc)
    if isinstance(exc, MemoryError):
        return "unavailable", "Unavailable specialist memory: " + str(exc)
    if isinstance(exc, RuntimeError):
        text = str(exc).lower()
        if any(value in text for value in ("out of memory", "execution provider", "not implemented")):
            return "unavailable", "Unavailable specialist device/operator: " + str(exc)
        return "invalid", "Specialist runtime contract failure: " + str(exc)
    return "invalid", "Invalid specialist worker contract: " + str(exc)


def serve():
    sessions = OrderedDict()
    print(json.dumps({"schema_version": 1, "status": "ready"}, separators=(",", ":")), flush=True)
    for line in sys.stdin:
        request_id = None
        try:
            message = json.loads(line)
            if not isinstance(message, dict) or set(message) != {"request_id", "request"}:
                raise ValueError("Malformed specialist server message")
            request_id, path = message["request_id"], message["request"]
            if not isinstance(request_id, int) or request_id < 1 or not isinstance(path, str):
                raise ValueError("Malformed specialist server request identity")
            request = read_json(path)
            response = execute(request, sessions)
            write_json(request["response"], response)
            reply = {"schema_version": 1, "status": "complete", "request_id": request_id,
                     "cached_sessions": len(sessions)}
        except Exception as exc:
            status, error = _failure(exc)
            reply = {"schema_version": 1, "status": status,
                     "request_id": request_id, "error": error}
        print(json.dumps(reply, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")), flush=True)
    return 0


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--serve":
        return serve()
    response = None
    try:
        request = read_json(sys.argv[1])
        response = execute(request)
        write_json(request["response"], response)
        return 0
    except Exception as exc:
        status, error = _failure(exc)
        print(error)
        return 20 if status == "unavailable" else 21


if __name__ == "__main__":
    raise SystemExit(main())

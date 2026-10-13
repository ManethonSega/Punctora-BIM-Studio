"""Standalone isolated PTv3 inference. Only this process imports model code.

    Exit 20: missing dependency/device/operator. Exit 21: malformed contract or
    runtime defect. No download, pip installation or executable model config.
    Checkpoints are tensor-only and load strictly with weights_only=True.
    """
import hashlib
from importlib import metadata, util
import json
from pathlib import Path
import sys


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def infer(request):
    import numpy as np
    assets = request["assets"]
    for name in ("checkpoint", "model_config", "runtime_manifest"):
        if digest(assets[name]) != assets[name + "_sha256"]:
            raise ValueError("Asset changed after worker admission: " + name)
    runtime = json.loads(Path(assets["runtime_manifest"]).read_text())
    import platform
    if platform.python_version() != runtime["python_version"]:
        raise ValueError("Isolated Python version differs from its runtime fingerprint")
    for package, version in runtime["packages"].items():
        if metadata.version(package) != version:
            raise ValueError("Isolated runtime package version disagrees with its fingerprint: " + package)
    # Load just the owned preprocessing module, not the base converter or its
    # dependency environment. The worker lives at an explicit absolute path.
    spec = util.spec_from_file_location("original_preprocessing", Path(__file__).with_name("preprocessing.py"))
    preprocessing = util.module_from_spec(spec)
    spec.loader.exec_module(preprocessing)
    config = json.loads(Path(assets["model_config"]).read_text())
    if config["preprocessing"] != preprocessing.PREPROCESSING:
        raise ValueError("Preprocessing contract changed")
    import torch
    import pointcept
    source_digest = hashlib.sha256()
    source_root = Path(pointcept.__file__).resolve().parent
    for path in sorted(source_root.rglob("*.py")):
        source_digest.update(path.relative_to(source_root).as_posix().encode())
        source_digest.update(path.read_bytes())
    if source_digest.hexdigest() != runtime["pointcept_python_tree_sha256"]:
        raise ValueError("Installed Pointcept source differs from its explicit runtime fingerprint")
    from pointcept.models import build_model
    if assets["device"].startswith("cuda") and not torch.cuda.is_available():
        raise ImportError("The isolated runtime has no available CUDA device")
    torch.manual_seed(0)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(0)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    model = build_model(config["model"])
    checkpoint = torch.load(assets["checkpoint"], map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict):
        raise ValueError("Checkpoint must be a tensor-only state dictionary")
    state = checkpoint.get("state_dict", checkpoint)
    if not isinstance(state, dict) or any(not isinstance(k, str) or not torch.is_tensor(v) for k, v in state.items()):
        raise ValueError("Checkpoint state_dict contains unsupported objects")
    if state and all(k.startswith("module.") for k in state):
        state = {k[7:]: v for k, v in state.items()}
    model.load_state_dict(state, strict=True)
    model = model.to(assets["device"]).eval()
    points = np.load(request["points"], mmap_mode="r", allow_pickle=False)
    votes = np.load(request["vote_mask"], mmap_mode="r", allow_pickle=False)
    labels = np.full(len(points), -1, dtype="<i2")
    scores = np.zeros(len(points), dtype="<f4")
    try:
        inputs = preprocessing.prepare_model_input(points, votes)
        if inputs is not None:
            device = assets["device"]
            tensors = {name: torch.from_numpy(inputs[name]).to(device) for name in ("coord", "grid_coord", "feat")}
            tensors["offset"] = torch.tensor([len(inputs["coord"])], dtype=torch.int64, device=device)
            tensors["batch"] = torch.zeros(len(inputs["coord"]), dtype=torch.int64, device=device)
            with torch.inference_mode():
                output = model(tensors)
            logits = output.get("seg_logits") if isinstance(output, dict) else None
            if logits is None or tuple(logits.shape) != (len(inputs["coord"]), 12) or not torch.isfinite(logits).all():
                raise ValueError("Pointcept must return finite N x 12 seg_logits")
            values = logits.detach().to("cpu", dtype=torch.float32).numpy()
            classes = values.argmax(axis=1)
            winner_score = values[np.arange(len(classes)), classes]
            native_map = np.asarray(request["native_to_taxonomy"], dtype="<i2")
            labels[inputs["selected"]] = native_map[classes][inputs["inverse"]]
            scores[inputs["selected"]] = winner_score[inputs["inverse"]]
    finally:
        points._mmap.close()
        votes._mmap.close()
    directory = Path(request["output_directory"])
    np.save(directory / "labels.npy", labels, allow_pickle=False)
    np.save(directory / "scores.npy", scores, allow_pickle=False)


def main():
    try:
        request = json.loads(Path(sys.argv[1]).read_text())
        if request.get("schema_version") != 1:
            raise ValueError("Unsupported isolated worker protocol")
        infer(request)
        return 0
    except (ImportError, metadata.PackageNotFoundError) as exc:
        print("Unavailable isolated runtime: " + str(exc))
        return 20
    except RuntimeError as exc:
        # Missing GPU-specific operators and explicit OOM are availability
        # failures, not an excuse to hide arbitrary broken model code.
        text = str(exc).lower()
        if any(word in text for word in ("cuda out of memory", "not compiled with cuda", "no kernel image", "not implemented for 'cpu'")):
            print("Unavailable isolated device/operator: " + str(exc))
            return 20
        print("Internal model runtime failure: " + str(exc))
        return 21
    except Exception as exc:
        print("Invalid isolated worker contract: " + str(exc))
        return 21


if __name__ == "__main__":
    raise SystemExit(main())

"""Scan-free checks using the exact interpreter that will run specialist inference."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .specialist_pack import SPECIALIST_PROVIDER_ID, resolve_model_pack


RUNTIME_VERSION = "1.23.2"
# ONNX IR8/opset13 Identity, float32[2], generated and checked with ONNX 1.19.1.
# This tests the native inference library without shipping ONNX's authoring tools.
IDENTITY_GRAPH_HEX = "08083a4c0a100a017812017922084964656e74697479121670756e63746f72612d72756e74696d652d70726f62655a0f0a0178120a0a08080112040a020802620f0a0179120a0a08080112040a02080242040a00100d"


def runtime_probe_script():
    # CPU-only installation and session API:
    # https://onnxruntime.ai/docs/install/#install-onnx-runtime-cpu
    # https://onnxruntime.ai/docs/api/python/api_summary.html#load-and-run-a-model
    return f"""
import json, sys
import onnxruntime as ort
import numpy as np
if ort.__version__ != {RUNTIME_VERSION!r}:
    raise RuntimeError('Expected onnxruntime {RUNTIME_VERSION}; found '+ort.__version__)
if 'CPUExecutionProvider' not in ort.get_available_providers():
    raise RuntimeError('onnxruntime CPUExecutionProvider is unavailable')
options=ort.SessionOptions()
options.intra_op_num_threads=1
options.inter_op_num_threads=1
session=ort.InferenceSession(bytes.fromhex({IDENTITY_GRAPH_HEX!r}),options,providers=['CPUExecutionProvider'])
x=np.asarray([1.25,-2.5],dtype=np.float32)
y=session.run(None,{{'x':x}})[0]
if not np.array_equal(x,y) or session.get_providers()!=['CPUExecutionProvider']:
    raise RuntimeError('onnxruntime native CPU inference check failed')
print(json.dumps({{'python':sys.executable,'onnxruntime':ort.__version__,'numpy':np.__version__,
                  'actual_provider':'CPUExecutionProvider','native_inference_verified':True}}))
"""


def probe_runtime(interpreter):
    """No scan, working directory imports, user site, or developer PYTHONPATH."""
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME"):
        environment.pop(name, None)
    with tempfile.TemporaryDirectory(prefix="punctora-runtime-check-") as directory:
        process = subprocess.run([interpreter, "-I", "-c", runtime_probe_script()],
                                 cwd=directory, env=environment, capture_output=True,
                                 text=True, timeout=45,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if process.returncode:
        detail = (process.stderr or process.stdout or "Specialist runtime check failed").strip()
        raise RuntimeError(detail.splitlines()[-1][:2000])
    result = json.loads(process.stdout)
    if not result.get("native_inference_verified"):
        raise RuntimeError("Specialist runtime did not verify native CPU inference")
    return result


def preflight_recognition(request):
    """Check runtime before even hashing model files, with no source cloud access."""
    started = time.perf_counter()
    mode = request.get("recognition_mode", "classical")
    if mode not in {"classical", "specialist", "hybrid"}:
        raise ValueError("Recognition mode must be classical, specialist or hybrid")
    if mode == "classical":
        return {"status": "complete", "requested_mode": mode, "requested_provider": "classical",
                "actual_provider": "classical", "active_branches": [], "missing_branches": []}
    # absolute(), not resolve(): resolving a virtualenv symlink selects base Python.
    interpreter = str(Path(request.get("specialist_python") or
                           os.environ.get("PUNCTORA_SPECIALIST_PYTHON") or sys.executable).absolute())
    report = {"status": "unavailable", "requested_mode": mode,
              "requested_provider": SPECIALIST_PROVIDER_ID, "actual_provider": "unavailable",
              "specialist_python": interpreter, "active_branches": [],
              "missing_branches": list("ABCDEFGHIJ"), "scope": "scan_free_runtime_and_asset_preflight"}
    try:
        if not Path(interpreter).is_file():
            raise RuntimeError("Specialist Python interpreter is missing: " + interpreter)
        report["runtime"] = probe_runtime(interpreter)
        root = request.get("specialist_model_directory")
        if not isinstance(root, str) or not root.strip() or not Path(root).is_dir():
            raise RuntimeError("Select the existing A-J specialist model folder; automatic downloads are disabled")
        manifest, assets, missing = resolve_model_pack(Path(root).absolute())
        report.update(asset_status=assets, missing_branches=missing,
                      model_pack_manifest_sha256=manifest["manifest_sha256"],
                      available_branches=[name for name in "ABCDEFGHIJ" if name not in missing])
        if missing:
            raise RuntimeError("Specialist model assets missing for branches: " + ", ".join(missing))
        report.update(status="complete", actual_provider=SPECIALIST_PROVIDER_ID,
                      reason=None, branch_status="assets_verified_inference_pending")
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        report["reason"] = str(exc)
    report["elapsed_seconds"] = time.perf_counter() - started
    return report

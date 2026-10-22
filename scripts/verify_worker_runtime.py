"""Verify detection followed immediately by validated IFC export in a runtime.

Use the selected interpreter from outside the repository, with isolated import
paths. This catches runtime dependencies hidden by the developer/test environment.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


def verify_runtime(interpreter, directory, *, specialist=False):
    # Keep a virtual environment's launcher path; resolving its symlink would
    # silently select the base interpreter and bypass the installed runtime.
    interpreter = Path(interpreter).absolute()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    project = directory / "bundle.punctora"
    target = directory / "bundle.ifc"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment.pop("PUNCTORA_SPECIALIST_PYTHON", None)
    # The portable interpreter and OS DLL directories suffice. A developer PATH
    # must not conceal dependencies on separately installed Python/C++ packages.
    if os.name == "nt":
        environment["PATH"] = os.pathsep.join([str(interpreter.parent),
            str(Path(os.environ["SystemRoot"])/"System32"), os.environ["SystemRoot"]])

    def job(command, **data):
        job_id = uuid.uuid4().hex
        request = {"protocol_version": 1, "job_id": job_id,
                   "command": command, "project": str(project), **data}
        process = subprocess.run(
            [str(interpreter), "-I", "-m", "punctora_core.worker"],
            cwd=directory, env=environment,
            input=json.dumps(request, allow_nan=False)+"\n",
            text=True, capture_output=True, timeout=180,
        )
        messages = [json.loads(line) for line in process.stdout.splitlines()]
        errors = [message for message in messages if message.get("type") == "error"]
        results = [message for message in messages if message.get("type") == "result"]
        if process.returncode or errors or len(results) != 1:
            raise RuntimeError(f"Isolated runtime {command} failed:\n{process.stdout}\n{process.stderr}")
        if any(message.get("job_id") != job_id or message.get("protocol_version") != 1 for message in messages):
            raise RuntimeError("Worker result identity or protocol mismatch")
        return results[0]["result"]

    state = job("demo", two_storeys=True)
    state = job("reconstruct", expected_revision=state["revision"], confirm_z_up=True)
    result = job("export", expected_revision=state["revision"], output=str(target))
    if not result["validation"]["valid"] or result["validation"]["tessellated_products"] == 0 or not target.is_file():
        raise RuntimeError("Isolated runtime did not export a validated, tessellated IFC")

    # Reopen the serialised file and prove EXPRESS rules still reject a known
    # semantic defect. Do not solve missing dependencies by disabling validation.
    probe = """
import json, sys
import ifcopenshell
from punctora_core.ifc_export import validate_ifc
f = ifcopenshell.open(sys.argv[1])
good = validate_ifc(f)
assert good['valid'] and good['tessellated_products'] > 0, good
space = f.by_type('IfcSpace')[0]
storey = f.by_type('IfcBuildingStorey')[0]
f.create_entity('IfcRelContainedInSpatialStructure', GlobalId=ifcopenshell.guid.new(),
                RelatedElements=[space], RelatingStructure=storey)
bad = validate_ifc(f)
assert not bad['valid'] and bad['express_findings'], bad
print(json.dumps({'roundtrip_valid': True, 'invalid_space_containment_rejected': True}))
"""
    process = subprocess.run([str(interpreter), "-I", "-c", probe, str(target)],
                             cwd=directory, env=environment, text=True,
                             capture_output=True, timeout=120)
    if process.returncode:
        raise RuntimeError("Isolated IFC validation probe failed:\n"+process.stdout+"\n"+process.stderr)
    report = {"worker_demo": True, "worker_reconstruct": True,
              "immediate_ifc_export": result["validation"],
              **json.loads(process.stdout)}
    if specialist:
        runtime_probe = """
import ctypes, json, os
from pathlib import Path
from punctora_core.recognition.preflight import probe_runtime
import sys
result=probe_runtime(sys.executable)
if os.name=='nt':
    import onnxruntime
    root=Path(sys.executable).parent.resolve()
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetModuleHandleW.argtypes=[ctypes.c_wchar_p]
    kernel.GetModuleHandleW.restype=ctypes.c_void_p
    kernel.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint]
    loaded={}
    for name in ['msvcp140.dll','msvcp140_1.dll','vcruntime140.dll','vcruntime140_1.dll']:
        handle=kernel.GetModuleHandleW(name)
        assert handle, 'Required native runtime not loaded: '+name
        path=ctypes.create_unicode_buffer(32768)
        assert kernel.GetModuleFileNameW(handle,path,len(path)),name
        assert Path(path.value).parent.resolve()==root,(name,path.value)
        loaded[name]='worker/python/'+name
    result['app_local_native_libraries']=loaded
print(json.dumps(result))
"""
        checked = subprocess.run([str(interpreter), "-I", "-c", runtime_probe],
            cwd=directory, env=environment, text=True, capture_output=True, timeout=60)
        if checked.returncode:
            raise RuntimeError("Standalone specialist runtime check failed:\n"+checked.stdout+checked.stderr)
        report["specialist_cpu_runtime"] = json.loads(checked.stdout)
    (directory / "runtime-verification.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print("Isolated runtime verified: detection, immediate IFC export, roundtrip and invalid EXPRESS rejection.")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    verify_runtime(args.python, args.output)


if __name__ == "__main__":
    main()

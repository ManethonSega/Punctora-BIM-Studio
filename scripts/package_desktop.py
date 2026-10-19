"""Build a portable Windows x64 preview with pinned, replaceable runtimes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PYTHON_URL = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
PYTHON_HASH = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"


def run(*args):
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def copy_cpp_runtime(python):
    """App-local CRT deployment, including ONNX's MSVCP140_1 dependency.

    Build-time Visual Studio is not required on the destination computer.
    https://learn.microsoft.com/en-us/cpp/windows/deployment-in-visual-cpp#local-deployment
    """
    roots = []
    if os.environ.get("VCToolsRedistDir"):
        roots.append(Path(os.environ["VCToolsRedistDir"]))
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(variable):
            roots.extend(Path(os.environ[variable]).glob("Microsoft Visual Studio/*/*/VC/Redist/MSVC/*"))
    candidates = sorted({p for root in roots for p in root.glob("x64/Microsoft.VC*.CRT")})
    required = ("msvcp140.dll", "msvcp140_1.dll", "vcruntime140.dll", "vcruntime140_1.dll")
    candidates = [p for p in candidates if all((p/name).is_file() for name in required)]
    if not candidates:
        raise RuntimeError("Build requires the Visual Studio x64 redistributable CRT files")
    source = candidates[-1]
    result = []
    for name in required:
        shutil.copy2(source/name, python/name)
        result.append({"file": name, "source": source.name,
                       "toolset": source.parent.parent.name, "sha256": digest(python/name)})
    return result


def verify_standalone_desktop(output):
    """Launch the delivered EXE away from the checkout and developer runtimes."""
    with tempfile.TemporaryDirectory(prefix="punctora-standalone-") as temporary:
        directory = Path(temporary)
        app = directory/"app"
        shutil.copytree(output, app)
        environment = os.environ.copy()
        for name in ("PYTHONPATH", "PYTHONHOME", "PUNCTORA_PYTHON", "PUNCTORA_SPECIALIST_PYTHON",
                     "PUNCTORA_SPECIALIST_MODELS"):
            environment.pop(name, None)
        environment["PATH"] = os.pathsep.join([str(Path(os.environ["SystemRoot"])/"System32"),
                                               os.environ["SystemRoot"]])
        environment["DOTNET_ROOT"] = str(directory/"no-system-dotnet")
        environment["DOTNET_ROOT_X64"] = environment["DOTNET_ROOT"]
        environment["DOTNET_MULTILEVEL_LOOKUP"] = "0"
        evidence = directory/"checks"
        process = subprocess.run([str(app/"Punctora.Desktop.exe"), "--software", "--verify-ui", str(evidence)],
            cwd=directory, env=environment, capture_output=True, text=True, timeout=240)
        error = evidence/"ui-error.txt"
        if process.returncode or error.exists() or not (evidence/"ui-verification.json").is_file():
            detail = error.read_text() if error.exists() else process.stdout+process.stderr
            raise RuntimeError("Standalone EXE walkthrough failed:\n"+detail)
        ui = json.loads((evidence/"ui-verification.json").read_text())
        for name in ("edit_survived_reopen", "ifc_exists", "crop_survived_reopen",
                     "feature_add_delete_passed", "small_window_scroll_passed"):
            if ui.get(name) is not True:
                raise RuntimeError("Standalone EXE check failed: "+name)
        provider = json.loads((evidence/"provider-status-verification.json").read_text())
        if not all(provider.values()):
            raise RuntimeError("Standalone EXE provider status check failed")
        return {"packaged_exe_launched": True, "outside_repository": True,
                "os_only_path": True, "external_dotnet_root_disabled": True,
                "bundled_worker_save_reopen_export": True, "provider_status": provider}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/Punctora-BIM-Studio-M3-win-x64")
    parser.add_argument("--dotnet", default="dotnet")
    parser.add_argument("--wheel-cache")
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Choose an empty output directory; existing packages are never overwritten")
    output.mkdir(parents=True, exist_ok=True)
    run(args.dotnet, "restore", "desktop/Punctora.Desktop/Punctora.Desktop.csproj", "-p:RuntimeIdentifier=win-x64", "--locked-mode")
    run(args.dotnet, "publish", "desktop/Punctora.Desktop/Punctora.Desktop.csproj", "-c", "Release", "-r", "win-x64",
        "--self-contained", "true", "--no-restore", "-o", output)
    worker = output / "worker"
    python = worker / "python"
    packages = worker / "packages"
    python.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="punctora-package-") as temporary:
        temporary = Path(temporary)
        archive = temporary / "python.zip"
        urllib.request.urlretrieve(PYTHON_URL, archive)
        if digest(archive) != PYTHON_HASH:
            raise ValueError("Embedded Python archive differs from its reviewed SHA-256")
        with zipfile.ZipFile(archive) as compressed:
            compressed.extractall(python)
        (python / "python312._pth").write_text("python312.zip\n.\n../packages\nimport site\n", encoding="utf-8")
        cache = Path(args.wheel_cache).resolve() if args.wheel_cache else temporary / "wheels"
        cache.mkdir(exist_ok=True)
        tags = ["--only-binary=:all:", "--platform", "win_amd64", "--python-version", "312", "--implementation", "cp", "--abi", "cp312"]
        run(sys.executable, "-m", "pip", "download", *tags, "-r", "requirements-desktop.txt", "--dest", cache)
        hashes = json.loads((ROOT / "desktop/windows-wheel-hashes.json").read_text())
        for entry in hashes["wheels"]:
            if digest(cache / entry["file"]) != entry["sha256"]:
                raise ValueError("Windows wheel differs from reviewed archive: " + entry["file"])
        run(sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", temporary, ".")
        core = next(temporary.glob("punctora_core-*.whl"))
        run(sys.executable, "-m", "pip", "install", *tags, "--no-index", "--find-links", cache,
            "--target", packages, "--no-compile", "-r", "requirements-desktop.txt", core)
    cpp_runtime = copy_cpp_runtime(python)
    for entry in cpp_runtime:
        shutil.copy2(python/entry["file"], output/entry["file"])
        entry["destinations"] = [entry["file"], "worker/python/"+entry["file"]]
    for name in ["LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "ATTRIBUTIONS.md"]:
        shutil.copy2(ROOT / name, output / name)
    shutil.copytree(ROOT / "third_party", output / "third_party")
    shutil.copy2(ROOT / "desktop/windows-wheel-hashes.json", output / "windows-wheel-hashes.json")
    shutil.copy2(ROOT / "docs/DESKTOP.md", output / "README.md")
    shutil.copy2(ROOT / "docs/WINDOWS_RUNTIME_NOTICES.md", output / "WINDOWS_RUNTIME_NOTICES.md")
    license_files = []
    for file in sorted(packages.rglob("*")):
        if file.is_file() and any(word in file.name.lower() for word in ["license", "copying", "notice"]):
            license_files.append({"path": file.relative_to(output).as_posix(), "sha256": digest(file)})
    manifest = {"package": "M3 Windows x64 preview",
                "core_version": tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"],
                "dotnet_runtime": "10.0.0", "python": "3.12.10",
                "python_archive_sha256": PYTHON_HASH, "windows_wheels": hashes["wheels"], "installed_license_files": license_files,
                "reconstruction_backend": "adaptive multicore CPU with optional OpenCL/CUDA voxel indexing",
                "viewport": "automatic OpenGL/ANGLE with software fallback",
                "specialist_runtime": {"onnxruntime": "1.23.2", "provider": "CPUExecutionProvider",
                                       "bundled": True, "model_weights": "external_user_selected"}}
    manifest["app_local_cpp_runtime"] = cpp_runtime
    (output / "package-manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    if os.name == "nt":
        # Exercise reconstruction and IFC export with the actual packaged Python,
        # outside the repository and without the developer Python search path.
        from verify_worker_runtime import verify_runtime
        manifest["runtime_verification"] = verify_runtime(python / "python.exe", output / "verification", specialist=True)
        (output / "package-manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
        shutil.rmtree(output / "verification")
        manifest["standalone_desktop_verification"] = verify_standalone_desktop(output)
        (output / "package-manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    archive = shutil.make_archive(str(output), "zip", root_dir=output.parent, base_dir=output.name)
    print("Preview package:", archive)


if __name__ == "__main__":
    main()


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
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PYTHON_URL = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
PYTHON_HASH = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"


def run(*args):
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
        run(sys.executable, "-m", "pip", "download", *tags, "-r", "requirements-core.txt", "--dest", cache)
        hashes = json.loads((ROOT / "desktop/windows-wheel-hashes.json").read_text())
        for entry in hashes["wheels"]:
            if digest(cache / entry["file"]) != entry["sha256"]:
                raise ValueError("Windows wheel differs from reviewed archive: " + entry["file"])
        run(sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", temporary, ".")
        core = next(temporary.glob("punctora_core-*.whl"))
        run(sys.executable, "-m", "pip", "install", *tags, "--no-index", "--find-links", cache,
            "--target", packages, "--no-compile", "-r", "requirements-core.txt", core)
    # pye57/IfcOpenShell import MSVCP140.dll by its standard name. Reuse the
    # unmodified, licensed runtime already redistributed in the Shapely wheel.
    cpp_runtime = next((packages / "shapely.libs").glob("msvcp140-*.dll"))
    shutil.copy2(cpp_runtime, python / "msvcp140.dll")
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
    manifest = {"package": "M3 Windows x64 preview", "dotnet_runtime": "10.0.0", "python": "3.12.10",
                "python_archive_sha256": PYTHON_HASH, "windows_wheels": hashes["wheels"], "installed_license_files": license_files,
                "reconstruction_backend": "CPU", "viewport": "automatic OpenGL/ANGLE with software fallback"}
    manifest["app_local_cpp_runtime"] = {"source": cpp_runtime.relative_to(output).as_posix(),
                                        "destination": "worker/python/msvcp140.dll", "sha256": digest(cpp_runtime)}
    (output / "package-manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    if os.name == "nt":
        # Run from outside the repository with embedded Python's isolated search path.
        destination = output / "verification"
        process = subprocess.run([str(python / "python.exe"), "-m", "punctora_core.worker"], cwd=output, input=json.dumps({
            "protocol_version": 1, "job_id": "0123456789abcdef0123456789abcdef", "command": "demo",
            "project": str(destination / "bundle.punctora"), "two_storeys": True})+"\n", text=True, capture_output=True, timeout=120)
        if process.returncode or '"type": "result"' not in process.stdout:
            raise RuntimeError("Bundled worker verification failed: " + process.stderr)
        shutil.rmtree(destination)
    archive = shutil.make_archive(str(output), "zip", root_dir=output.parent, base_dir=output.name)
    print("Preview package:", archive)


if __name__ == "__main__":
    main()

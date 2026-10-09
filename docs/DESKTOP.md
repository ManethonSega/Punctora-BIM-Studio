# M3 desktop preview

The desktop opens registered E57 scans, fits the current CPU reconstruction providers, overlays candidate geometry, edits supported elements and exports validated IFC4. It uses local files and has no AI weights or scan uploads.

## Windows preview

Download `Punctora-BIM-Studio-M3-win-x64` from a successful **M3 desktop preview** run on [GitHub Actions](https://github.com/ManethonSega/Punctora-BIM-Studio/actions/workflows/desktop.yml). Extract the artifact, then extract the contained ZIP. Keep all extracted files together and run **Punctora.Desktop.exe**. The portable preview includes .NET 10.0.0, Python 3.12.10 and pinned worker dependencies; it does not need developer tools. This is a preview build. Clean-machine installer acceptance remains M4 work.

1. Choose **Example** for the generated two-storey walkthrough, or **Import E57** for an already registered scan. Choose a new `.punctora` filename.
2. Check the coordinate and pose warnings. Confirm **Z is up** before **Detect elements**. Missing CRS and vertical datum remain unknown; this checkbox does not establish either.
3. Orbit by dragging, pan by right-dragging, zoom with the wheel, and use **Fit view**. Toggle the cloud/model, adjust opacity, select a storey, or lower the section height.
4. Select a candidate in the element list or 3D view. Edit wall endpoints/base/height/thickness/classification, slab base/thickness, or storey name/floor/ceiling. Choose a review state and **Apply correction**. Ctrl-click two or more collinear wall rows and choose **Merge selected wall fragments**, or enter a local distance and choose **Split selected wall**. Hosted openings move to the resulting wall segment; a split through an opening is rejected. **Undo edit** restores the preceding draft; **Revert** reloads the saved model.
5. **Save** retains corrections. **Save copy** copies the project and required assets to a new filename. Keep the `.punctora` file and its sibling `.assets` folder together when moving a project.
6. **Convert to IFC** writes the current model, including corrections in an unsaved draft. If no model exists yet, it first detects elements using the selected method and confirmed Z-up setting. Rejected walls/slabs are excluded. Inferred spaces are omitted after geometry changes until their boundaries can be regenerated. IFC validity and original-fit RMSE do not establish survey accuracy.

**Cancel job** terminates the isolated worker and waits for its exit. Completed atomic writes are authoritative; interrupted work cannot overwrite the last saved project. Existing unsaved corrections remain when the saved revision has not advanced. Unused staging data is removed by cleanup after reconstruction/cancellation; lock files can remain on disk without holding a lock.

## Graphics and current limits

The application automatically attempts an OpenGL cloud/model renderer. On Windows Avalonia supplies ANGLE over Direct3D; the viewport reports the renderer/vendor actually returned by the graphics context. Software drivers are labeled as software OpenGL. If graphics initialization/drawing fails, a 5,000-point software preview is available. **Use software preview** forces that fallback. No NVIDIA/CUDA requirement is introduced.

The OpenGL preview is capped at 100,000 deterministic source samples, held in batched XYZ/RGBA buffers. Camera transformations, section clipping and point depth run in the graphics context. Canonical fitting coordinates remain double precision; preview floats never overwrite scan data. Transparent candidate meshes and observed points form an inspection overlay. The preview is not an exact hidden-surface rendering or a deviation report.

This preview uses a fixed sample rather than view-dependent streaming/LOD. It provides a vertical section and storey filtering; arbitrary box crops and large-scene picking indexes are follow-up work. Version 0.3.0a5 adds full-cloud streaming level statistics, adaptive memory limits, larger geometry budgets and multicore sampling/nearest-neighbour queries. Version 0.3.0a4 added conservative automatic wall-fragment consolidation and draft merge/split controls. Version 0.3.0a3 added geometric opening-gap and straight-stair candidates, parameter editing, review states and IFC export. Opening candidates cut the host wall in the preview; stair candidates display tread envelopes. See [feature detection and limits](FEATURE_DETECTION.md).

**Point-cloud-to-IFC conversion still uses the CPU.** GPU rendering does not accelerate E57 decoding, reconstruction or IFC writing. Coordinated multicore reconstruction and a GPU compute backend need separate profiling and numerical verification. Existing native NumPy/OpenCV routines may use threads internally.

The M3 OpenGL/fallback walkthroughs have been checked under Linux/Xvfb/Mesa, and software review/export has passed Windows CI. The 0.3.0a2 package check also performs immediate IFC export using only the bundled interpreter, including EXPRESS-rule validation. AMD RX 7800 XT and clean Windows acceptance remain hardware checks; no hardware frame-rate claim is made. See [M3 verification](https://github.com/ManethonSega/Punctora-BIM-Studio/blob/main/docs/M3_VERIFICATION.md) for current evidence.

## Developer launch

Install Python 3.12 and .NET SDK 10.0.100, then run from the repository:

```sh
python -m venv .venv
# Activate .venv, then:
python -m pip install -e ".[test]" -c requirements-core.txt
dotnet restore desktop/Punctora.Desktop/Punctora.Desktop.csproj --locked-mode
dotnet run --project desktop/Punctora.Desktop -c Release
```

`PUNCTORA_PYTHON` can point to a compatible worker Python executable. The bundled worker takes precedence over a developer virtual environment. `--software` forces the bounded software view. A `.punctora` path passed on the command line opens that project.

Build a Windows package with Python 3.11/3.12 and the pinned .NET SDK:

```sh
python scripts/package_desktop.py
```

The script checks the embedded Python archive and Windows wheel hashes, retains licences and records a package manifest. On Windows it also runs the embedded worker from the package directory. Build output is in `artifacts/` and is excluded from source control. Runtime replacements and source locations are documented in `WINDOWS_RUNTIME_NOTICES.md`.

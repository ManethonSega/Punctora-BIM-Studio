# Cloud2BIM viewer audit and Punctora visual-quality plan

Audit version **1.1**, consolidated reference **1.3**, 2026-10-13. Findings **CB-044 through CB-060** extend the [maintained reference](CLOUD2BIM_REFERENCE.md). The [viewer evidence](cloud2bim-viewer-audit-v1.json) records native anchors, source fingerprints, visual observations and six generated probes.

**Conclusion:** Cloud2BIM uses a mature Qt/PyVista/VTK viewer with custom CAD navigation, actual IFC tessellation, explicit face lighting and architectural outlines. We can reproduce those useful behaviours in Punctora and improve review through detailed local point loading, accurate occlusion, linked views and preserved element/evidence identities. Visual comfort is an explicit implementation outcome alongside geometric fidelity.

This audit changes documentation and derived evidence only. The supplied executable was inspected as data and was never launched or imported. The user screenshot was inspected once it became available. It shows a Cloud2BIM point-cloud view, without a matched Punctora view or IFC view. Conclusions about the native IFC route come from static inspection and separately identified generated probes. The existing Punctora documentation screenshot is an older software-preview example with different geometry, not a fair rendering benchmark.

## 1. How the viewer is made

| Layer | Recovered implementation | Evidence |
| --- | --- | --- |
| Desktop shell | PySide6 Qt widgets; embedded `pyvistaqt.QtInteractor` | CB-044, N |
| Rendering/data model | PyVista `PolyData`, VTK actors, geometry filters and camera | CB-044, N/P |
| Navigation | First-party `cad_camera_style`, derived from VTK trackball camera style | CB-045/046, N/P |
| Cloud display | Prefer diluted XYZ when available; apply crop; subtract shared display offset; assign elevation or RGB scalars | CB-047/051, N |
| IFC display | IfcOpenShell geometry iterator, per-shape transformation, concatenation by IFC type and PyVista meshes | CB-048, N |
| IFC appearance | Triangulate, clean, compute normals; lit face actor plus separate feature-edge actor | CB-049/050, N |
| Sections | VTK box clipping/plane widgets and IFC-floor section choices | CB-056, N |

Decoded module literals report **PySide6 6.7.3, PyVista 0.47.1, PyVistaQt 0.11.3, vtkmodules 9.6.2 and IfcOpenShell 0.8.4.post1**. These are package version literals, not measured Windows runtime versions. Current public documentation may describe later APIs. Pin and test actual dependencies when implementing.

The important new discovery is `cad_camera_style`: the previous first-party inventory selected `src.cloud2BIM_*` modules and omitted this top-level module. This pass decoded all **178 primitive constants** and traced its registered camera functions. It is a viewer improvement source independent of the ONNX detection models.

## 2. Confirmed findings

### CB-044: embedded VTK viewing stack [N/P]

`Cloud2BIMApp._setup_ui` creates `QtInteractor`, sets a white background and installs CAD navigation while keeping a reference to the style. Point cloud, 3D model, combined view and cross-section controls share this viewport. Anchor: `0x1405b0f00`; CAD installation is visible around `0x1405b1778`.

PyVista provides the high-level mesh/actor interface; VTK supplies the underlying geometry and rendering machinery. [PyVistaQt documents QtInteractor embedding](https://qt.pyvista.org/usage.html). This architecture explains a substantial part of the viewer maturity without implying that VTK itself recognizes building elements.

### CB-045: geometry-aware CAD navigation [N/P]

Recovered behaviour: left drag orbits around a picked point with world Z up; middle drag or Shift plus left drag pans; right drag uses inherited dolly navigation; wheel zoom moves toward the cursor; double click recentres on the picked point. A prop picker supplies an orbit pivot, with focal-depth unprojection as fallback. A cell picker also participates in the perspective zoom guard. Rotation preserves Z up and clamps polar motion to prevent pole flips. Wheel logic supports perspective and parallel cameras, although this does not establish a production UI projection toggle.

Anchors: orbit `0x14075df30`, cursor zoom `0x140760d10`, pivot `0x14076aff0`, recenter `0x140763ce0`. The wheel step literal is 1.15. The generated focal-plane zoom probe retained the cursor anchor to numerical precision; centre-only zoom moved it. This is an independent geometry contract, not execution of the native camera code.

Punctora currently orbits its stored target, right-drags to pan and changes `Span` on wheel events. It ray-picks model triangles for selection, but does not use a cloud/geometry hit as the orbit pivot or wheel anchor. Preserve the familiar Punctora shortcuts while adding a CAD preset and explaining the active controls.

### CB-046: clipping repair inside buildings [N/P]

The camera style resets the clipping range, checks its validity and repairs a collapsed/degenerate interval. The embedded explanation explicitly addresses a camera inside a closed building: invalid clipping can hide all geometry and break focal-plane unprojection. `_safe_clip` is called during navigation. Anchor: `0x140767e30`.

Implement finite, positive, ordered near/far planes with a close-geometry floor and an inside-building fallback. Recalculate from visible bounds and camera position. Avoid repeatedly fitting the whole scene to repair an interior view.

### CB-047: one display origin for cloud, IFC and crop [N/V]

Cloud2BIM has an explicit render-only offset for large XY coordinates. The branch uses a 20,000 m threshold and a 100 m grid offset recipe; `_disp` and `_disp_bounds` apply it to geometry and bounds. Data coordinates remain unchanged. Anchors: offset `0x1405bd9b0`, points `0x1405bec70`, bounds `0x1405bf1d0`.

Punctora already imports E57 into an f64 local metre frame with a reversible source mapping. Retain that stronger evidence contract and extend it consistently to imported IFC and added scans. Subtract the shared origin **before** casting to GPU float32. In the generated million-metre example, direct float32 lost distinct XY positions and reached 13 mm error; local-origin casting preserved the fixture within 4.7e-10 m. This is a precision demonstration, not a measured scan accuracy.

### CB-048: display actual IFC geometry, retain identity [N/V]

`_ifc_to_mesh` opens an IFC path or accepts an in-memory IFC, initializes the IfcOpenShell geometry iterator, reads vertex/face arrays, retrieves `get_shape_matrix`, applies the homogeneous transformation in float64 and concatenates geometry by IFC type with adjusted face offsets. It creates display-shifted PyVista meshes. Anchor: `0x1405460c0`; transform retrieval `0x140546f22`.

This provides the tessellated authored solid, including opening booleans and placements. Punctora's editor currently builds preview triangles from its element model, not from an arbitrary loaded IFC file. Keep that immediate edit preview, and add a separate IFC geometry route for exported and imported models. The generated wall probe produced 28 triangles, the expected 2 m3 net volume after a 0.4 m3 door cut, and correct rotated/georeferenced bounds.

The traced Cloud2BIM mesh assembly batches by type and returns geometry without a per-triangle product-ID channel. Do better: preserve IFC GUID, project element ID, representation ID, triangle range, material and evidence/review state through batching. A type-wide actor must not erase element selection or evidence association. [IfcOpenShell's geometry-processing documentation](https://docs.ifcopenshell.org/ifcopenshell-python/geometry_processing.html) explains iterator reuse, shapes and transformation handling.

### CB-049: explicit lit faces [N/V]

Cloud2BIM prepares meshes using triangulation, cleaning and point normals with vertex splitting, consistent normals and automatic orientation. The face actor uses **lighting on**, **show_edges off**, **smooth_shading off**, ambient **0.18**, diffuse **0.88**, specular **0.08**, power **12** and scalar interpolation enabled. Anchors: prepare `0x140545250`, face actor `0x1405456e0`. Boolean values were resolved against the executable's Python true/false import entries, not guessed from nearby literals.

Punctora's GPU vertex layout is XYZ plus RGBA; its fragment shader has no normal or light calculation. Same-colour perpendicular faces therefore receive the same brightness. This is a concrete visual gap. Add normals, restrained diffuse lighting and a weak fill light. Preserve sharp architectural edges; offer smooth shading for curved surfaces rather than rounding every wall corner. Lighting changes the display, not the authored mesh. [PyVista documents these material controls](https://docs.pyvista.org/api/plotting/_autosummary/pyvista.Plotter.add_mesh.html).

### CB-050: architectural outlines, not triangulation wireframe [N/V]

Cloud2BIM extracts feature edges at **28 degrees**, with boundaries and feature edges included, ordinary manifold edges and non-manifold edges excluded. It renders them separately in `#303030`, width **1.5**, lighting off. Anchor: `0x14054595c`.

A generated triangulated cube contained 18 unique mesh edges but only 12 architectural feature edges. Punctora should use boundary/crease edges and a restrained selection outline. Do not show every diagonal. Compute topology edges before normal-driven vertex splitting, retain component/product identity, and deduplicate coincident edge segments. Normal splitting created 24 display vertices from eight geometric cube corners while preserving bounds; this is a display operation, not additional geometry evidence.

### CB-051: distinct point-cloud and combined recipes [N]

The traced cloud-only slot assigns world Z to `Elevation`, uses **turbo**, point size **1.5** and a visible black-labelled scalar bar. Combined view uses **3.0** points at **50% opacity**, RGB if available and elevation/turbo otherwise. Cloud-only prefers diluted points when present and falls back to imported points. Anchors: cloud `0x140526d70`, cloud material `0x140528301`, combined `0x1405c3bd0`.

Do not describe cloud-only RGB as established by this route. Punctora already offers Original, Height and Monochrome. Preserve those choices, add valid intensity where available and give each mode a clear legend. Keep the complete-cloud height range stable while zooming/cropping, with an explicitly chosen local-range option. Do not normalize geometry accuracy from the displayed colour range.

### CB-052: crop and zoom need local detail loading [V/A]

Punctora has a deterministic 500,000-point overview, adaptive movement limits and a 5,000-point software fallback. Those are useful bounded previews. However, crop filtering operates on that overview. Zoom cannot load points discarded when the overview was written. The generated scaled-cap probe used the actual `spatial_preview_indices` function: a region with **10,000** source points retained only **207** in a 5,000-point global overview; a region-specific request could display **5,000**.

Add an immutable spatial tile/LOD cache queried by viewport, crop and section. Retain the overview for immediate feedback and stream region detail progressively. Do not remove all memory bounds or label displayed points as the entire source. This probe diagnoses a design limitation; it does not claim the supplied Cloud2BIM screenshot has a particular point count or an octree backend.

### CB-053: separate solid occlusion from evidence overlay [V/A]

Punctora's GPU path intentionally clears model depth before drawing point evidence. That makes points visible through model faces, including opaque faces. Its nearest-skin transparency pass also intentionally avoids stacking every coincident/rear face. Keep this useful evidence review mode, but make it explicit.

Provide **solid depth-correct comparison**, **translucent model comparison** and **evidence X-ray**. In the solid mode, cloud and model share depth; points behind an opaque wall disappear. In X-ray, hidden evidence remains visible with a clear mode indicator. Verify transparency independently; an opacity slider alone does not select the intended depth semantics. The existing stencil/coincident-face safeguards should remain regression fixtures.

### CB-054: depth precision and clip-space mismatch [V/A]

For `Span=20 m`, Punctora sets near **0.0002 m**, far **300 m** and allocates `DEPTH24_STENCIL8`. The ratio is 1,500,000. `System.Numerics.Matrix4x4.CreatePerspectiveFieldOfView` uses the DirectX-style depth interval 0..1. The shader submits that matrix to OpenGL without an identified clip-space conversion or `glClipControl` call. OpenGL's default interval is -1..1, so this projection uses approximately half the window-depth range and changes effective near clipping.

The generated analytical probe mapped eye depths **32 m** and **32.001 m** to the same 24-bit value under this current path. An illustrative full-range projection with near 0.1 m and far 80 m separated them. The local depth-step estimate improved from about **0.61 m** to **0.00061 m**. These values describe that fixture and default depth mapping; they are not a captured framebuffer or proof of the user's particular artifact.

Correct the projection convention and CPU unprojection/picking together. Choose adaptive near/far planes from visible geometry and allow closer ranges inside buildings. Do not impose a fixed 0.1 m near plane everywhere. Add known-plane depth and selection fixtures before tuning shading. Source: [.NET 10 implementation](https://github.com/dotnet/runtime/blob/v10.0.0/src/libraries/System.Private.CoreLib/src/System/Numerics/Matrix4x4.Impl.cs), [OpenGL depth precision](https://wikis.khronos.org/opengl/Depth_Buffer_Precision).

### CB-055: consistent point appearance across backends and DPI [V/A]

Punctora submits raw point size to `gl_PointSize`, while the software view draws ellipses in logical coordinates. GPU points use the primitive's square coverage without an explicit rounded sprite mask. At higher display scaling the two paths therefore use different physical sizing conventions. Define size in device-independent pixels, scale once for the framebuffer and report the convention accurately.

Offer crisp small dots and an optional rounded/splat mode with a capped screen-space footprint. Keep facade edges and stair gaps readable; large overlapping splats can visually bridge unsupported areas. Never use a visually filled point surface as reconstruction evidence. Check 100%, 150% and 200% scaling.

### CB-056: section controls should work before reconstruction [N/A]

Cloud2BIM's cross-section entry has an IFC-floor dependency and emits a conversion-first message without floor choices. Its cloud renderer also warns and shows the full cloud when crop bounds exclude every point. Anchors: floor dependency around `0x140529247`, empty-crop fallback `0x140527f0c`.

Punctora already supports a non-destructive project polygon/height crop before reconstruction. Extend viewing with arbitrary section planes/boxes and manual heights, independent of successful floor detection. An empty view should say that the crop/section contains no points and offer reset; silently restoring unrelated points would confuse an audit. Keep view clipping distinct from saved reconstruction crop and model edits. If section caps are drawn, label them as display caps, never inferred floors or exported solids.

### CB-057: visual comfort and screenshot observations [V/A]

The supplied **963 x 1335** image shows a white canvas, fine dense points and a continuous height palette. Multiple stair flights, landings and gaps are visually legible. These are useful presentation targets. The lower scalar bar crowds the geometry and its right title is partly cut in the supplied image; the attachment alone does not establish whether application layout or capture cropping caused that truncation.

Use a calm canvas, restrained materials, controlled point footprint and a spacious scene area. Add light and dark canvas presets within Punctora's palette; use a light canvas as the initial Cloud2BIM-like review preset, with user choice retained. Collapse configuration/inspector panels for visual inspection. Keep legends in reserved margins, preserve units, avoid covering stairs and show the active mode clearly. This is a visual requirement, not a claim of measured preference superiority across users.

### CB-058: useful library capabilities are not confirmed app settings [P/Q/A]

PyVista/VTK support eye-dome lighting (EDL), anti-aliasing and Gaussian point rendering. No explicit enabling call for EDL, SSAO, PBR, Gaussian splats or anti-aliasing was established in the inspected first-party viewer paths. Library strings do not prove Cloud2BIM uses these features; default context/theme behaviour remains unqualified.

Use [EDL](https://docs.pyvista.org/examples/02-plot/edl.html) as an optional point-depth cue, [anti-aliasing](https://docs.pyvista.org/examples/02-plot/anti_aliasing.html) for stable edges and [VTK's Gaussian point mapper](https://vtk.org/doc/nightly/release/9.3/html/classvtkPointGaussianMapper.html) as a controlled visual candidate. Qualify the appearance, picking footprint and depth semantics on our fixtures. Prefer clean geometry and lighting first; effects must not conceal missing walls, floor corners or openings.

## 3. Visual design specification

The traced native type palette is a useful starting reference, rather than a requirement to replace the user's Punctora palette:

| IFC class | Native colour |
| --- | --- |
| Walls | `#A9CCE3` |
| Slabs | `#D5D8DC` |
| Doors | `#E59866` |
| Windows | `#AED6F1` |
| Roofs | `#CD6155` |
| Beams | `#99A3A4` |
| Columns | `#7F8C8D` |
| Other displayed types | `#E8DAEF` |


| Aspect | Intended appearance and behaviour | Implementation contract |
| --- | --- | --- |
| Canvas | Calm light review preset plus retained dark option | Theme-controlled solid background; no automatic palette changes during jobs |
| IFC faces | Soft class materials, readable wall thickness and corners | Opaque default; sharp normals on planar faces; restrained lighting; stable class/material map |
| Outlines | Fine architectural edges | Boundary/crease lines only; DPI-scaled width; depth bias limited to display |
| Points | Dense fine structure without a blocky veil | Source RGB/height/intensity choices; small capped footprint; progressive local detail |
| Depth cues | Clear front/back and stair separation | Correct projection and clipping first; optional EDL thereafter |
| Comparison | Cloud/model comparison without camera jumps | Retain camera, origin, projection, colour range and section while switching layers; linked split views and overlay |
| Selection | Unambiguous selected element | Per-element outline plus inspector/evidence focus; type batches retain GUID/element map |
| Sections | Crisp, understandable cuts | Plane/box manipulation; units and reset control; display caps visibly separate |
| Legend | Readable and unobtrusive | Reserved viewport margin; label/tick layout tested at narrow sizes and high DPI |
| Status | Noticeable top status/progress area | Current phase and Save/Revert/Failed state; icon and text plus existing palette severity colour; brief transition emphasis, persistent failure; respect reduced motion |
| Workspace | More room to see the building | Collapsible side panels, compact viewport toolbar, optional orientation/scale helpers |

The model and evidence palettes must remain distinct: class colour describes element type; review/inferred state belongs in an outline, pattern or separate evidence layer. Avoid using the same whole-face colour to mean both a wall class and confirmed source support. Geometry cleanup, recognition confidence and screen prettiness remain separate measurements.

## 4. Technical architecture and implementation order

**Revised direction, version 1.3:** retain the Avalonia shell and evaluate direct VTK integration through ActiViz 9.7 first. Kitware now explicitly documents an Avalonia 12 rendering control. This supersedes the version 1.2 repair-custom-OpenGL-first ordering, although projection, clipping, identity and comparison requirements still apply to either backend. Keep the existing renderer as fallback and behind a replaceable interface. QtInteractor remains a Qt integration route; it is not necessary to migrate the application to Qt to obtain VTK rendering. Exact compatibility with our Avalonia 12.1.3/.NET 10 build and resource lifecycle is an internal Run 8 check.

| Work package | Concrete changes | Owner / dependencies |
| --- | --- | --- |
| A. Coordinate/camera foundation | f64 camera pose and pivot; shared display origin; explicit projection convention; adaptive finite clipping; picked orbit, cursor zoom, recenter; orthographic and named views | Run 8; consumes Run 7 alignment contract |
| B. IFC mesh authority | Worker IfcOpenShell iterator route; apply shape matrix once; stable units/origin; preserve GUID and triangle IDs; geometry failures reported per product; cancellable generation-keyed cache | Runs 4-6 provide schema/geometry; Run 8 displays; Run 7 identity |
| C. Pleasant IFC presentation | Normal buffers, sharp-edge policy, restrained lighting, crease/boundary line buffers, anti-aliasing; retain existing degenerate/coincident-face safeguards | Run 8, after A/B |
| D. Detailed cloud presentation | Spatial tile/LOD requests for view/crop/section; bounded RAM/GPU residency; valid colour/intensity channels; original uint64 source IDs retained in CPU tables | Run 8, optional native acceleration in Run 9 |
| E. Review composition | Solid shared depth, translucent comparison and explicit X-ray; linked cloud/IFC cameras; saved view bookmarks; per-element picking and evidence focus | Run 8, after A-D |
| F. Visual workspace | Light/dark canvas, focused view, compact controls, readable legends, top status/progress and state emphasis | Run 8; prior user palette/status requirements retained |
| G. Backend qualification, performed first | ActiViz 9.7 Avalonia 12 integration spike using our actual locked build; then same generated mesh/point fixtures and camera/material recipe on VTK and existing OpenGL; compare fidelity, overlays, context recovery, DPI and selection | Run 8; hardware/user qualification after Run 9 |

Recommended interface inputs are: immutable generation/source identity; f64 working coordinates and source mapping; explicit display origin; double-precision camera pose; indexed position/normal/material buffers; per-triangle GUID/project-ID ranges; point tile IDs and source-key tables; clip state; presentation mode. A render result includes loaded/displayed point counts, pending-detail state and failures. None of these display buffers becomes geometry authority.

Worker mesh/tile generation happens off the UI thread. GPU resource creation and rendering stay on the appropriate graphics/UI lifecycle. New scene generations cancel obsolete requests; results from stale revisions are discarded. Make cache keys include source/model revision, meshing settings, coordinate frame and tile/LOD version. Closing/reopening the viewport releases resources safely; a failed renderer leaves saved project/evidence intact and permits fallback.

ActiViz 9.7 supplies a documented Avalonia 12 control using an offscreen VTK scene integrated into Avalonia's Skia canvas, including before/after rendering hooks. Qualify this supported route first. Our build still must verify focus/input, overlays, scaling, resize, screenshot, cancellation and teardown. A custom bridge or generic NativeControlHost is a fallback engineering route, with separate lifecycle and composition constraints. Rust is useful for spatial indexing, tile decoding, immutable buffer construction or a picking BVH if measured need justifies it. Rust does not supply face lighting, IFC boolean fidelity or a pleasant colour/legend design automatically. Keep that selective work in Run 9.

## 5. Internal acceptance and nine-run decisions

The six audit probes passed on trusted **Python 3.12.14, NumPy 2.3.5, VTK 9.3.1 and IfcOpenShell 0.8.3**. They establish contracts and design limitations, not a native Cloud2BIM render capture. Future implementation must exercise the actual app:

- A known rotated/georeferenced IFC wall with a door opening preserves bounds, net volume, GUID selection and cloud alignment across display modes.
- Planar perpendicular faces have distinct lighting; a cube has 12 architectural outlines with no six triangulation diagonals; curved meshes retain a deliberate smooth-shading path.
- Known near/far planes map to the specified clip interval. Millimetre-separated reference planes at the chosen review scale remain distinguishable; picking agrees with rendered position. An interior camera remains finite and can zoom out.
- Solid comparison hides points behind opaque IFC faces; X-ray deliberately reveals them. Coincident/rear triangles do not accumulate stripes or excessive colour. These checks include section clipping and transparent surfaces.
- Zoom/crop requests source-backed local tiles rather than repeatedly filtering the overview. Display IDs resolve to original scan/record keys; cancelling or switching revisions cannot attach stale points.
- Cloud and IFC share a camera when modes change. Legends, controls and top status remain readable at narrow sizes, high DPI and collapsed-panel layouts; reduced-motion settings suppress flash animation.
- Cached/uncached loads, context loss and reopen leave source hashes, f64 mappings and exported IFC unchanged. Memory stays within the project's 70% RAM ceiling; fallback is visibly identified.

**Current decision: Proceed with revised future scope.** Runs 1-3 are not reopened for this audit. Run 4 remains the next recognition implementation. Runs 4-6 must expose mesh/evidence identities; Run 7 must supply aligned scene frames; Run 8 owns the expanded viewer/visual work; Run 9 qualifies selective acceleration and subsequent real-scan/hardware review. There is no new external-check loop or required tenth run.

For the implementation owner, apply all five existing decisions: **Proceed** after internal criteria pass; **Proceed with revised future scope** when findings alter later design; **Repeat current run** for repairable internal implementation defects; **Redesign current run** when a renderer/geometry assumption fails; **Redesign/update future run** for dependent scope changes. Missing user visual review or designated-hardware qualification never triggers Repeat. Actual comparative user/real-scan assessment follows all nine runs.

## 6. Remaining focused questions

1. Which renderer/context and defaults does the supplied Windows app actually select on the user's machine? Static package literals cannot establish adapter, MSAA or GPU behaviour.
2. Does a VTK candidate improve our generated visual/fidelity fixtures enough to justify the Avalonia integration cost? Decide from a bounded Run 8 comparison, not another broad discovery pass.
3. What point density and image quality does the user prefer on the same scan, camera and section? Capture paired cloud and IFC views after implementation; the supplied image anchors appearance, not objective reconstruction completeness.
4. What default dot size, light balance and canvas best match the existing requested colour scheme? Retain user-selectable presets and current palette tokens until reviewed together.

Another unrestricted package pass is not a prerequisite. The newly recovered camera module, explicit render recipes and identified Punctora gaps provide enough evidence to implement the viewer scope. Return to source inspection when a concrete runtime mismatch appears.


## 7. Integration and E57-to-XYZ follow-up

### CB-059: direct VTK integration is a stronger first option [P/A]

The follow-up primary-source check found Kitware's [ActiViz 9.7 release](https://www.kitware.com/activiz-9-7-release/), published 2026-09-04, explicitly describing a redesigned **Avalonia 12** rendering control. It integrates the VTK scene with Avalonia's Skia canvas and exposes hooks for 2D drawing around the VTK pass. [ActiViz 9.6](https://www.kitware.com/activiz-9-6-release/) also documents Avalonia context management and hardware picking. This is a concrete .NET integration resource omitted from the initial viewer audit.

**Revised Run 8 ordering:** evaluate the supplied ActiViz Avalonia control first, rather than commit first to rebuilding VTK capabilities in custom OpenGL. Retain our UI, Python reconstruction worker and source/evidence contracts. Use VTK for scene rendering, materials, outlines, clipping and picking. Implement our CAD navigation behaviour using VTK camera/picker primitives in C#; it is custom interaction code, not an automatic consequence of adding VTK. Continue using IfcOpenShell in the worker to tessellate actual IFC solids, then send vertices, normals, materials, placements and element IDs to the viewer. The tessellator and renderer are different responsibilities.

Qt/PyVista/VTK as a complete Python viewer can also be used for a reference or a separate viewer process. A full Qt shell is possible, but it expands migration to menus, editing, jobs, packaging and window lifecycle. Native PyVista objects are not C# Avalonia controls. For an integrated Punctora viewer, direct .NET VTK is now the preferred first evaluation. A supported offscreen Avalonia control is distinct from generic native child-window embedding, which has overlay/z-order limitations documented by [Avalonia](https://docs.avaloniaui.net/docs/app-development/native-interop).

The vendor's capability statement is not a local build result. Validate our exact Avalonia 12.1.3, .NET 10, Windows/Linux packages and the earlier generated fixtures during Run 8. No trial was downloaded, production dependency added or vendor contacted in this documentation pass. External hardware/user review stays after all nine runs. The replacement decision remains evidence-based, and camera/depth correctness is required under either backend.

### CB-060: E57-to-XYZ participates in reconstruction, but format is not the recognition mechanism [N/V/A]

The supplied import route explicitly branches on `.e57`, calls `read_e57`, calls `e57_data_to_xyz`, obtains the `.xyz` path and feeds it to the XYZ loader. It concatenates resulting arrays, rounds coordinates and can apply line/spatial thinning. The GUI load thread calls that importer and assigns its returned coordinates to the working point cloud. The normal reconstruction entry obtains `_get_points_for_inference`, whose path prefers/builds diluted points, and proceeds into surface and storey processing. This supports **E57 -> XYZ -> working arrays -> preprocessing/detection -> IFC**, rather than an XYZ file used only for display.

Anchors at the pinned executable:

| Operation | Anchor |
| --- | --- |
| E57 read wrapper | `0x14ac4f9c0`, dispatch to `e57.read_points` near `0x14ac4fd35` |
| XYZ writer body | `0x14ac51760` |
| XYZ coordinate formats / rounding | `0x14ac51f40` / `0x14ac52892` |
| E57 branch invokes writer | `0x14ac5562b` |
| XYZ loader invocation | `0x14ac56b08` |
| Post-concatenation rounding / spatial dilution | `0x14ac5801a` / `0x14ac5878a` |
| GUI invokes structured importer | `0x1405204a7` |
| Main reconstruction selects inference points | `0x140559e64` |
| Diluted/source inference-point choice | around `0x1405bd763` through `0x1405bd818` |

The native XYZ header contains **X, Y, Z, R, G, B, Intensity**. Coordinates use three decimal places; other channels use seven significant digits. The writer stages a `.part` file before replacement. The inspected seven-column text does not carry scan IDs, source record IDs, scan poses, validity masks or coordinate metadata. Those require source retention and a sidecar. This is a statement about that representation, not a claim that Cloud2BIM deletes the original E57 or cannot have other metadata paths. The reader's explanatory text refers to pye57, while the traced wrapper dispatches to `e57.read_points`; source-reader registration/pose parity must be verified at the reader boundary, not assumed from that text.

**Value for IFC reconstruction:** a common working dataset lets all specialist stages share coordinate conventions, channels and preprocessing. Persisting it can support inspection and repeatable processing when it is keyed to source identity and preprocessing settings. It can change the IFC if scan pose application, invalid-point filtering, line sampling, spatial dilution, coordinate rounding or channel handling change. The same exact coordinates and preprocessing produce the same model inputs irrespective of whether they came from E57, XYZ or a binary cache; ONNX detectors consume tensors, not a magical filename extension.

At metre units, rounding to 0.001 m contributes at most about **0.0005 m per axis**, or **0.000866 m in 3D** for an individual rounded position. A generated 1,000-row, seven-channel text roundtrip stayed within this coordinate bound and preserved its uint8 RGB values. This format probe did not run native recognition or show equivalent real-building results. Near-threshold decisions can still be sensitive to small perturbations, but coordinate rounding alone does not explain a wall missing or extending substantially past its evidence. Much larger point thinning and pose/frame errors deserve separate examination.

**Punctora adaptation:** retain E57 as the source, decode/apply scan poses once and keep f64 working coordinates with scan IDs, original record IDs, validity masks and a reversible frame transform. Our disk-backed binary source cache already serves as an intermediate working dataset. Add versioned specialist analysis views derived from that cache, with declared thinning/normalisation and reverse mappings; the viewer uses its own tiles/LOD. Optional XYZ export/import is useful for interchange, debugging or a controlled Cloud2BIM-input comparison. It should not replace the evidence-bearing source cache by default.

Before attributing an IFC improvement to conversion, compare the **decoded inputs**: counts, bounds, pose transforms, finite-point masks, XYZ residuals, RGB/intensity/missing-channel handling, retained IDs and applied thinning. Then compare the same preprocessing and detector stages. If the paths differ, fix the identified ingestion or analysis-view contract. Do not conclude that writing XYZ improves recognition merely because the complete Cloud2BIM pipeline succeeds. This is a bounded integration check within the existing runs; external real-scan quality review remains after Run 9.

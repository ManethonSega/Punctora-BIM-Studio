# Run 2: interactive preview candidate, v0.3.0a19

The desktop continues to read only the bounded 500,000-point preview, never the
complete E57 cloud. The original f64 coordinates and source records remain in
the worker. No new NVIDIA, CUDA or Rust dependency is introduced.

## Rendering changes

| Quality | While moving | After stopping |
| --- | ---: | ---: |
| Adaptive (default) | 75,000 to 100,000 | 500,000 |
| Low | 75,000 | 100,000 |
| Medium | 100,000 | 250,000 |
| High | 100,000 | 500,000 |

Counts are capped by the available cropped preview. CPU software fallback uses
2,500 points while moving and 5,000 at rest; Intel hardware OpenGL follows the
table, without requiring NVIDIA.

Points are reordered into deterministic, spatially distributed prefixes once
when the scene or crop changes. One complete preview buffer stays on the GPU.
Orbiting and changing density change only the draw count, with no cloud scans,
resampling, coordinate changes or buffer uploads.

Mouse events replace the pending absolute pointer position. One animation-frame
request applies the latest camera state; intermediate states are discarded.
The last position is also applied on release or capture loss. A 20 ms timer
requests resting density once input has been quiet for 150 ms. Diagnostics
separately record this scheduling delay and the actual full-density render
callback delay, so a slow driver cannot be hidden behind the timer target.

Model triangles are grouped by material and storey, with exact duplicate and
degenerate triangles removed from the render buffer. A depth prepass resolves
the nearest model skin, followed by transparent colour only at that depth.
The scan remains overlaid for evidence review. Selection uses its own buffer
and separate highlight draw pass; changing selection does not rebuild batches.

Slab, landing and slab-void render contours have a 2 mm simplification tolerance,
preserving topology. Simplification is rejected if the symmetric area change
exceeds 0.1%. Original footprints and exact cap meshes remain unchanged. IFC
export reads the original geometry and never the render contours.

## Verification

Native checks exercise all quality budgets, timer boundaries, a 500k progressive
buffer without lost/duplicated points, crop filtering, material batches, overlap
removal and slab/void geometry. The UI walkthrough supplies bursts of pointer
positions to the same coalescing path, using a generated 500k-point scene with
a simulated 210M source count. It checks the final camera position, a maximum
of one pending frame, zero orbit-time point uploads and full density restoration.
This fixture does not establish performance on the user's project.

The Python regression verifies that contour simplification reduces detail,
retains the slab void and produces exactly the same IFC tessellation vertices
before and after preview serialization/reopening.

The footer shows the active adapter, frame cadence/FPS, active point count and
quality. Diagnostics include frame mean/p95, CPU submission time, batches,
draw calls, mouse coalescing and restore delay. FPS measures render callback
cadence during movement, not GPU completion or physical screen presentation.

## Intel UHD acceptance gate (pending)

Use the same real project and computer, with Windows selecting Intel graphics.
Keep Adaptive quality and confirm that the footer names the Intel adapter.
Orbit, pan and zoom for at least 10 seconds with model and cloud visible:

1. At least 30 FPS during sustained movement.
2. No visible input delay or continued movement after releasing the pointer.
3. A 500,000-point resting view restored in roughly 200 ms after input stops.
4. Walls, slab holes, stairs and selection remain visually usable.

For a repeatable diagnostic run from the portable package directory:

```powershell
.\Punctora.Desktop.exe --verify-preview "C:\path\project.punctora" "C:\path\run2-check"
```

This records the active adapter and orbit/restore timing in
`preview-verification.json`, plus captures. Also inspect real mouse behaviour;
the automated orbit alone cannot establish absence of perceived input delay.
Run 2 is not accepted until these Intel UHD checks pass. CI machines and
software OpenGL do not substitute for the target hardware.

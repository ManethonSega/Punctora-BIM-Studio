# Dependency and research inventory

Reviewed on 2026-10-08. This register distinguishes selected M1 dependencies from future candidates. Cloud2BIM geometry helpers are included as source; NumPy, Shapely, OpenCV headless and IfcOpenShell are external Python dependencies. Exact direct versions are pinned in pyproject.toml; requirements-core.txt records the tested runtime dependencies. No native binaries or model weights are bundled. Installed Linux licence texts are retained as references, not a Windows binary audit. The machine-readable source is [dependency-inventory.json](../dependency-inventory.json).

Top-level review identifies published licence evidence, not all-file/transitive clearance. `pending` means the component's terms still need inspection; it is not approved for inclusion. Source links with a commit identify the inspected upstream revision. All chosen package versions must be pinned during implementation.

| Component | Type / intended role | Licence evidence | Status | Selected version |
| --- | --- | --- | --- | --- |
| [Cloud2BIM](https://github.com/VaclavNezerka/Cloud2BIM/blob/cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e/LICENSE) | code: Selected reconstruction algorithms | MIT | source_port_reviewed | cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e |
| [Avalonia](https://github.com/AvaloniaUI/Avalonia/blob/main/licence.md) | code: Desktop UI | MIT | top_level_reviewed | Future candidate |
| [.NET runtime](https://github.com/dotnet/runtime) | runtime: Desktop runtime | unverified | pending | Future candidate |
| [CPython](https://github.com/python/cpython) | runtime: Bundled geometry worker | unverified | pending | Future candidate |
| [pye57](https://github.com/davidcaron/pye57/blob/master/LICENSE) | code: E57 reader candidate | MIT | top_level_reviewed | Future candidate |
| [libE57Format and native E57 dependencies](https://github.com/asmaloney/libE57Format) | code: Native E57 reader dependencies | unverified | pending | Future candidate |
| [Open3D](https://github.com/isl-org/Open3D/blob/main/LICENSE) | code: Surface fitting and cloud processing | MIT | top_level_reviewed | Future candidate |
| [IfcOpenShell library](https://github.com/IfcOpenShell/IfcOpenShell/blob/v0.8.0/src/ifcopenshell-python/ifcopenshell/__init__.py) | code: IFC4 authoring and validation | LGPL-3.0-or-later | installed_source_header_reviewed | 0.8.3 |
| [PDAL](https://github.com/PDAL/PDAL/blob/master/LICENSE.txt) | code: Optional additional formats and chunk processing | BSD-3-Clause (overall); bundled terms vary | top_level_reviewed | Future candidate |
| [numpy](https://github.com/numpy/numpy) | code: Numerical arrays | BSD-3-Clause; wheel contains additional terms | installed_license_reviewed | 2.3.5 |
| [scipy](https://github.com/scipy/scipy) | code: Numerical fitting | unverified | pending | Future candidate |
| [shapely](https://github.com/shapely/shapely) | code: Planar geometry | BSD-3-Clause; GEOS LGPL-2.1-or-later | installed_license_reviewed | 2.1.2 |
| [scikit-image](https://github.com/scikit-image/scikit-image) | code: Image-based reconstruction where retained | unverified | pending | Future candidate |
| [opencv](https://github.com/opencv/opencv) | code: Image processing where retained | Apache-2.0 (OpenCV), MIT (Python packaging); native wheel terms vary | installed_license_reviewed | 4.11.0.86 (opencv-python-headless) |
| [SpatialLM repository code](https://github.com/manycore-research/SpatialLM/blob/8913c44d84a450c53e9340b13317f8cf7144a738/LICENSE.txt) | code: Future structured layout proposal adapter | Llama-3.2 community terms in repository LICENSE.txt; scope requires clarification | clarification_required | Future candidate |
| [SpatialLM1.1-Qwen-0.5B weights](https://huggingface.co/manycore-research/SpatialLM1.1-Qwen-0.5B) | model: Optional layout proposals | CC-BY-NC-4.0 | restricted | Future candidate |
| [Sonata encoder weights](https://github.com/manycore-research/SpatialLM/blob/8913c44d84a450c53e9340b13317f8cf7144a738/README.md) | model: SpatialLM1.1 point encoder | CC-BY-NC-4.0 as stated in SpatialLM README | restricted | Future candidate |
| [SpatialLM Dataset](https://huggingface.co/datasets/manycore-research/SpatialLM-Dataset) | dataset: Possible additional evaluation and training | CC-BY-NC-4.0 | restricted | Future candidate |
| [Pointcept repository code](https://github.com/Pointcept/Pointcept/blob/1342eda30e96cbb5fadf5374ff8eb18f6de15c71/LICENSE) | code: Future point-label proposal provider | MIT (reviewed root file) | top_level_reviewed | Future candidate |
| [GPT4Point](https://github.com/Pointcept/GPT4Point/blob/main/LICENSE) | research: Object-language research reference | MIT root file versus CC-BY-NC-SA-4.0 README | clarification_required | Future candidate |
| [MiniGPT-3D](https://huggingface.co/papers/2405.01413) | research: Object recognition research reference | unverified | pending | Future candidate |
| [ENEL](https://arxiv.org/html/2502.09620v1) | research: Encoder-free 3D-language architecture reference | unverified | pending | Future candidate |
| [PointLLM-R](https://dl.acm.org/doi/10.1145/3799902.3811081) | research: Object reasoning research reference | unverified; separate base-model/data terms require review | pending | Future candidate |
| [Pts3D-LLM](https://machinelearning.apple.com/research/pts3d-llm) | research: Scene understanding reference | unverified | pending | Future candidate |
| [LLM-Supervised Point Cloud Processing paper](https://doi.org/10.5194/isprs-archives-XLIX-B2-2026-1311-2026) | research: Region-growing and scene-relationship design reference | CC-BY-4.0 (paper only) | publication_reviewed | Future candidate |

## Incorporation decisions

Cloud2BIM, NumPy, Shapely, OpenCV headless and the IfcOpenShell library are selected for M1. E57, Open3D and Avalonia remain candidates for later milestones. PDAL is optional, not a mandatory extra runtime for the E57 milestone. Exact native and numerical dependencies will follow from the selected port and packaging trials.

SpatialLM can inform an independently written element/proposal contract now, but its source-code terms are not assumed permissive. Pointcept's reviewed MIT root licence does not cover every associated pretrained asset. Model weights and datasets remain separate inventory entries.

The ACM and May 2026 arXiv references are recorded together as PointLLM-R, not counted as separate engines. The general local-LLM blog is background reading, not an implementation dependency.

## Evidence limits and required actions

- **Cloud2BIM:** MIT notice retained; selected geometry helpers adapted. No upstream AI assets or full application copied.
- **Avalonia:** Pin and review the exact component and its dependencies before incorporation.
- **.NET runtime:** Pin and review the exact component and its dependencies before incorporation.
- **CPython:** Pin and review the exact component and its dependencies before incorporation.
- **pye57:** Pin and review the exact component and its dependencies before incorporation.
- **libE57Format and native E57 dependencies:** Pin and review the exact component and its dependencies before incorporation.
- **Open3D:** Pin and review the exact component and its dependencies before incorporation.
- **IfcOpenShell library:** Installed as an external dependency for M1. No native binary bundled. Audit exact platform wheels, complete native/transitive notices and source/replacement information before standalone packaging.
- **PDAL:** Pin and review the exact component and its dependencies before incorporation.
- **numpy:** Installed as an external dependency for M1. No native binary bundled. Audit exact platform wheels, complete native/transitive notices and source/replacement information before standalone packaging.
- **scipy:** Pin and review the exact component and its dependencies before incorporation.
- **shapely:** Installed as an external dependency for M1. No native binary bundled. Audit exact platform wheels, complete native/transitive notices and source/replacement information before standalone packaging.
- **scikit-image:** Pin and review the exact component and its dependencies before incorporation.
- **opencv:** Installed as an external dependency for M1. No native binary bundled. Audit exact platform wheels, complete native/transitive notices and source/replacement information before standalone packaging.
- **SpatialLM repository code:** Independently author Punctora's contract now. Clarify file-specific code terms before importing upstream implementation.
- **SpatialLM1.1-Qwen-0.5B weights:** No bundling in initial app. Resolve intended-use and redistribution permission, encoder/base-model terms and hardware feasibility.
- **Sonata encoder weights:** Pin and review the exact component and its dependencies before incorporation.
- **SpatialLM Dataset:** Resolve permitted evaluation/training/distribution uses before acquisition or inclusion; real survey evaluation still required.
- **Pointcept repository code:** Review chosen files and checkpoint terms separately; not a licence clearance for Sonata or other weights.
- **GPT4Point:** Pin and review the exact component and its dependencies before incorporation.
- **MiniGPT-3D:** Pin and review the exact component and its dependencies before incorporation.
- **ENEL:** Pin and review the exact component and its dependencies before incorporation.
- **PointLLM-R:** Pin and review the exact component and its dependencies before incorporation.
- **Pts3D-LLM:** Pin and review the exact component and its dependencies before incorporation.
- **LLM-Supervised Point Cloud Processing paper:** Cite research. Benchmark an independently implemented method; review separately any external code, models or data. No paper performance guarantee adopted.

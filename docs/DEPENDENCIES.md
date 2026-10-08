# Dependency and research inventory

Reviewed on 2026-10-08. This register contains **candidates only**. No listed implementation, model, dataset or runtime is installed or redistributed by Punctora at M0. Versions are not selected yet. The machine-readable source is [dependency-inventory.json](../dependency-inventory.json).

Top-level review identifies published licence evidence, not all-file/transitive clearance. `pending` means the component's terms still need inspection; it is not approved for inclusion. Source links with a commit identify the inspected upstream revision. All chosen package versions must be pinned during implementation.

| Component | Type / intended role | Licence evidence | Status |
| --- | --- | --- | --- |
| [Cloud2BIM](https://github.com/VaclavNezerka/Cloud2BIM/blob/cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e/LICENSE) | code: Selected reconstruction algorithms | MIT | top_level_reviewed |
| [Avalonia](https://github.com/AvaloniaUI/Avalonia/blob/main/licence.md) | code: Desktop UI | MIT | top_level_reviewed |
| [.NET runtime](https://github.com/dotnet/runtime) | runtime: Desktop runtime | unverified | pending |
| [CPython](https://github.com/python/cpython) | runtime: Bundled geometry worker | unverified | pending |
| [pye57](https://github.com/davidcaron/pye57/blob/master/LICENSE) | code: E57 reader candidate | MIT | top_level_reviewed |
| [libE57Format and native E57 dependencies](https://github.com/asmaloney/libE57Format) | code: Native E57 reader dependencies | unverified | pending |
| [Open3D](https://github.com/isl-org/Open3D/blob/main/LICENSE) | code: Surface fitting and cloud processing | MIT | top_level_reviewed |
| [IfcOpenShell library](https://github.com/IfcOpenShell/IfcOpenShell/blob/v0.8.0/src/ifcopenshell-python/ifcopenshell/__init__.py) | code: IFC4 authoring and validation | LGPL-3.0-or-later | component_reviewed |
| [PDAL](https://github.com/PDAL/PDAL/blob/master/LICENSE.txt) | code: Optional additional formats and chunk processing | BSD-3-Clause (overall); bundled terms vary | top_level_reviewed |
| [numpy](https://github.com/numpy/numpy) | code: Numerical arrays | unverified | pending |
| [scipy](https://github.com/scipy/scipy) | code: Numerical fitting | unverified | pending |
| [shapely](https://github.com/shapely/shapely) | code: Planar geometry | unverified | pending |
| [scikit-image](https://github.com/scikit-image/scikit-image) | code: Image-based reconstruction where retained | unverified | pending |
| [opencv](https://github.com/opencv/opencv) | code: Image processing where retained | unverified | pending |
| [SpatialLM repository code](https://github.com/manycore-research/SpatialLM/blob/8913c44d84a450c53e9340b13317f8cf7144a738/LICENSE.txt) | code: Future structured layout proposal adapter | Llama-3.2 community terms in repository LICENSE.txt; scope requires clarification | clarification_required |
| [SpatialLM1.1-Qwen-0.5B weights](https://huggingface.co/manycore-research/SpatialLM1.1-Qwen-0.5B) | model: Optional layout proposals | CC-BY-NC-4.0 | restricted |
| [Sonata encoder weights](https://github.com/manycore-research/SpatialLM/blob/8913c44d84a450c53e9340b13317f8cf7144a738/README.md) | model: SpatialLM1.1 point encoder | CC-BY-NC-4.0 as stated in SpatialLM README | restricted |
| [SpatialLM Dataset](https://huggingface.co/datasets/manycore-research/SpatialLM-Dataset) | dataset: Possible additional evaluation and training | CC-BY-NC-4.0 | restricted |
| [Pointcept repository code](https://github.com/Pointcept/Pointcept/blob/1342eda30e96cbb5fadf5374ff8eb18f6de15c71/LICENSE) | code: Future point-label proposal provider | MIT (reviewed root file) | top_level_reviewed |
| [GPT4Point](https://github.com/Pointcept/GPT4Point/blob/main/LICENSE) | research: Object-language research reference | MIT root file versus CC-BY-NC-SA-4.0 README | clarification_required |
| [MiniGPT-3D](https://huggingface.co/papers/2405.01413) | research: Object recognition research reference | unverified | pending |
| [ENEL](https://arxiv.org/html/2502.09620v1) | research: Encoder-free 3D-language architecture reference | unverified | pending |
| [PointLLM-R](https://dl.acm.org/doi/10.1145/3799902.3811081) | research: Object reasoning research reference | unverified; separate base-model/data terms require review | pending |
| [Pts3D-LLM](https://machinelearning.apple.com/research/pts3d-llm) | research: Scene understanding reference | unverified | pending |
| [LLM-Supervised Point Cloud Processing paper](https://doi.org/10.5194/isprs-archives-XLIX-B2-2026-1311-2026) | research: Region-growing and scene-relationship design reference | CC-BY-4.0 (paper only) | publication_reviewed |

## Incorporation decisions

Cloud2BIM, the E57 reader, Open3D, Avalonia and the IfcOpenShell library are the initial implementation candidates. PDAL is optional, not a mandatory extra runtime for the E57 milestone. Exact native and numerical dependencies will follow from the selected port and packaging trials.

SpatialLM can inform an independently written element/proposal contract now, but its source-code terms are not assumed permissive. Pointcept's reviewed MIT root licence does not cover every associated pretrained asset. Model weights and datasets remain separate inventory entries.

The ACM and May 2026 arXiv references are recorded together as PointLLM-R, not counted as separate engines. The general local-LLM blog is background reading, not an implementation dependency.

## Evidence limits and required actions

- **Cloud2BIM:** Retain MIT copyright/permission notice; record adapted files and changes; check each ported file and transitive dependency. Supplied release README has a conflicting GPL label.
- **Avalonia:** Pin and review the exact component and its dependencies before incorporation.
- **.NET runtime:** Pin and review the exact component and its dependencies before incorporation.
- **CPython:** Pin and review the exact component and its dependencies before incorporation.
- **pye57:** Pin and review the exact component and its dependencies before incorporation.
- **libE57Format and native E57 dependencies:** Pin and review the exact component and its dependencies before incorporation.
- **Open3D:** Pin and review the exact component and its dependencies before incorporation.
- **IfcOpenShell library:** Pin library build; retain LGPL/GPL texts and applicable source/replacement information; audit native dependencies. Do not copy GPL Bonsai application code as if it were LGPL.
- **PDAL:** Pin and review the exact component and its dependencies before incorporation.
- **numpy:** Pin and review the exact component and its dependencies before incorporation.
- **scipy:** Pin and review the exact component and its dependencies before incorporation.
- **shapely:** Pin and review the exact component and its dependencies before incorporation.
- **scikit-image:** Pin and review the exact component and its dependencies before incorporation.
- **opencv:** Pin and review the exact component and its dependencies before incorporation.
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

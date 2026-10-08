# Dependency and research inventory

Reviewed on 2026-10-08. This register distinguishes selected M2 dependencies from future candidates. Cloud2BIM geometry helpers are included as source; NumPy, SciPy, Shapely, OpenCV headless, IfcOpenShell, pye57 and pyquaternion are external Python dependencies. pye57 compiles libE57Format and links or bundles Xerces-C++; libE57Format vendors CRC++. Exact direct versions are pinned in pyproject.toml; requirements-core.txt records the tested runtime dependencies. No model weights are bundled. Installed Linux licence texts are retained as references, not a complete Windows installer audit. The machine-readable source is [dependency-inventory.json](../dependency-inventory.json). Component credits and notices are in [ATTRIBUTIONS.md](../ATTRIBUTIONS.md).

Top-level review identifies published licence evidence, not all-file/transitive clearance. `pending` means the component's terms still need inspection; it is not approved for inclusion. Source links with a commit identify the inspected upstream revision. All chosen package versions must be pinned during implementation.

| Component | Type / intended role | Licence evidence | Status | Selected version |
| --- | --- | --- | --- | --- |
| [Cloud2BIM](https://github.com/VaclavNezerka/Cloud2BIM/blob/cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e/LICENSE) | code: Selected reconstruction algorithms | MIT | source_port_reviewed | cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e |
| [Avalonia](https://github.com/AvaloniaUI/Avalonia/blob/main/licence.md) | code: Desktop UI | MIT | top_level_reviewed | Future candidate |
| [.NET runtime](https://github.com/dotnet/runtime/blob/main/LICENSE.TXT) | runtime: Desktop runtime | MIT | top_level_reviewed | Future candidate |
| [CPython](https://github.com/python/cpython/blob/main/LICENSE) | runtime: Bundled geometry worker | PSF-2.0; incorporated components have additional terms | top_level_reviewed | Future candidate |
| [pye57](https://github.com/davidcaron/pye57/tree/v0.4.19) | code: Direct E57 import and bounded-memory decoding | MIT | selected_runtime_reviewed | 0.4.19 |
| [libE57Format](https://github.com/asmaloney/libE57Format/tree/1914b8ea972251d3bb49a33828497dde683205d9) | native code: E57 decoding compiled into pye57 | BSL-1.0 | selected_runtime_reviewed | 3.1.1 at `1914b8e` |
| [pyquaternion](https://github.com/KieranWynn/pyquaternion/tree/v0.9.9) | code: Quaternion handling used by pye57 | MIT | selected_runtime_reviewed | 0.9.9 |
| [Apache Xerces-C++](https://github.com/apache/xerces-c/tree/v3.2.3) | native library: E57 XML parsing | Apache-2.0 | selected_runtime_reviewed | 3.2.3 |
| [CRC++](https://github.com/asmaloney/libE57Format/tree/1914b8ea972251d3bb49a33828497dde683205d9/extern/CRCpp) | native header code: E57 checksums | BSD-3-Clause | selected_runtime_reviewed | vendored with libE57Format 3.1.1 |
| [Open3D](https://github.com/isl-org/Open3D/blob/main/LICENSE) | code: Surface fitting and cloud processing | MIT | top_level_reviewed | Future candidate |
| [IfcOpenShell library](https://github.com/IfcOpenShell/IfcOpenShell/blob/v0.8.0/src/ifcopenshell-python/ifcopenshell/__init__.py) | code: IFC4 authoring and validation | LGPL-3.0-or-later | installed_source_header_reviewed | 0.8.3 |
| [PDAL](https://github.com/PDAL/PDAL/blob/master/LICENSE.txt) | code: Optional additional formats and chunk processing | BSD-3-Clause; bundled components have additional terms | top_level_reviewed | Future candidate |
| [numpy](https://github.com/numpy/numpy/blob/main/LICENSE.txt) | code: Numerical arrays | BSD-3-Clause; wheel contains additional terms | installed_license_reviewed | 2.3.5 |
| [scipy](https://github.com/scipy/scipy/blob/main/LICENSE.txt) | code: CPU surface neighbourhoods | BSD-3-Clause; bundled components have additional terms | runtime_distribution_notices_retained | 1.17.0 |
| [shapely](https://github.com/shapely/shapely) | code: Planar geometry | BSD-3-Clause; GEOS LGPL-2.1-or-later | installed_license_reviewed | 2.1.2 |
| [scikit-image](https://github.com/scikit-image/scikit-image/blob/main/LICENSE.txt) | code: Image-based reconstruction where retained | BSD-3-Clause overall; file-specific terms vary | top_level_reviewed | Future candidate |
| [opencv](https://github.com/opencv/opencv) | code: Image processing where retained | Apache-2.0 (OpenCV), MIT (Python packaging); native wheel terms vary | installed_license_reviewed | 4.11.0.86 (opencv-python-headless) |
| [SpatialLM repository code](https://github.com/manycore-research/SpatialLM/blob/8913c44d84a450c53e9340b13317f8cf7144a738/LICENSE.txt) | code: Future structured layout proposal adapter | Component-specific: Llama-3.2, Apache-2.0, MIT and CC-BY-NC-4.0 | component_declarations_reviewed | Future candidate |
| [SpatialLM paper, arXiv v2](https://arxiv.org/abs/2506.07491v2) | research: Structured wall/opening proposals; [detailed assessment](research/SPATIALLM.md) | CC-BY-4.0 (publication only) | publication_reviewed | 5 November 2025 revision |
| [SpatialLM1.1-Qwen-0.5B weights](https://huggingface.co/manycore-research/SpatialLM1.1-Qwen-0.5B) | model: Optional layout proposals | CC-BY-NC-4.0 | restricted | Future candidate |
| [Sonata encoder weights](https://github.com/manycore-research/SpatialLM/blob/8913c44d84a450c53e9340b13317f8cf7144a738/README.md) | model: SpatialLM1.1 point encoder | CC-BY-NC-4.0 as stated in SpatialLM README | restricted | Future candidate |
| [SpatialLM Dataset](https://huggingface.co/datasets/manycore-research/SpatialLM-Dataset) | dataset: Possible additional evaluation and training | CC-BY-NC-4.0 | restricted | Future candidate |
| [Pointcept repository code](https://github.com/Pointcept/Pointcept/blob/1342eda30e96cbb5fadf5374ff8eb18f6de15c71/LICENSE) | code: Future point-label proposal provider | MIT | top_level_reviewed | Future candidate |
| [GPT4Point](https://github.com/Pointcept/GPT4Point/blob/main/LICENSE) | research: Object-language research reference | MIT (repository LICENSE) | license_file_reviewed_with_conflicting_readme | Future candidate |
| [MiniGPT-3D](https://github.com/TangYuan96/MiniGPT-3D/blob/main/README.md) | research: Object recognition research reference | CC-BY-NC-SA-4.0 | restricted | Future candidate |
| [ENEL](https://arxiv.org/abs/2502.09620) | research: Encoder-free 3D-language architecture reference | CC-BY-NC-SA-4.0 (paper); code/weights unverified | publication_reviewed | Future candidate |
| [PointLLM-R](https://dl.acm.org/doi/10.1145/3799902.3811081) | research: Object reasoning research reference | Apache-2.0 (repository code); MIT (model card, upstream terms retained); CC-BY (ACM paper, user supplied) | mixed_publication_and_model_evidence | Future candidate |
| [Pts3D-LLM](https://machinelearning.apple.com/research/pts3d-llm) | research: Scene understanding reference | CC-BY (paper, user supplied); code/weights unverified | publication_user_reported | Future candidate |
| [LLM-Supervised Point Cloud Processing paper](https://doi.org/10.5194/isprs-archives-XLIX-B2-2026-1311-2026) | research: Region-growing and scene-relationship design reference | CC-BY-4.0 (paper only) | publication_reviewed | Future candidate |

### SpatialLM component licences

The [research assessment register](research/index.json) records the supplied paper version, fingerprint, practical findings and future experiment. Publication review is distinct from implementing an adapter or bundling assets.

| Component | Licence | Scope |
| --- | --- | --- |
| SpatialLM-Llama-1B backbone (Llama3.2-1B-Instruct) | Llama-3.2 Community License | base model |
| SpatialLM-Qwen-0.5B backbone (Qwen-2.5) | Apache-2.0 | original base model, not blanket clearance for SpatialLM weights |
| SpatialLM1.0 SceneScript point-cloud encoder | CC-BY-NC-4.0 | encoder declaration in SpatialLM README |
| TorchSparse | MIT | code declaration in SpatialLM README |
| SpatialLM1.1 Sonata encoder weights | CC-BY-NC-4.0 | model weights |
| SpatialLM1.1 code built on Pointcept | Apache-2.0 | SpatialLM README declaration; upstream Pointcept repository is separately MIT |

The released SpatialLM1.1-Qwen-0.5B checkpoint remains CC-BY-NC-4.0 according to its model card. Apache-2.0 for the original Qwen backbone does not change that checkpoint declaration.

### Licence scope notes

- **.NET runtime:** Root runtime code licence; bundled third-party components retain their terms.
- **CPython:** Open source is a category, not a licence name. Python documentation examples also have BSD-0-Clause terms from Python 3.8.6 onward.
- **libE57Format:** Applies to libE57Format. Xerces-C++ and CRC++ retain the separate notices listed above.
- **PDAL:** Redistribution is permitted subject to the full licence conditions; retain bundled component notices.
- **scikit-image:** The project licence lists additional file-specific terms; the supplied SciPy link is replaced by the scikit-image licence.
- **SpatialLM repository code:** README identifies component terms; root LICENSE.txt contains Llama-3.2 terms. No blanket licence is inferred for all repository files. The Qwen backbone licence is distinct from the released SpatialLM checkpoint licence.
- **GPT4Point:** The MIT LICENSE file is recorded as requested. README still declares CC-BY-NC-SA-4.0; scope of that declaration remains unresolved, particularly for models and data.
- **MiniGPT-3D:** Project README declaration; base model and incorporated assets require separate checks.
- **ENEL:** Verified publication licence. A paper licence does not by itself establish implementation or model licence.
- **PointLLM-R:** The user-supplied CC-BY label concerns the ACM paper; exact CC-BY version not established here. The repository code licence is Apache-2.0. The released model card states MIT while retaining base-model and Objaverse-derived data licences. The arXiv copy uses its own non-exclusive distribution licence.
- **Pts3D-LLM:** The CC-BY label and unspecified version are recorded from the supplied list for the publication, not as permission for implementation code or model weights.

## Incorporation decisions

Cloud2BIM, NumPy, SciPy, Shapely, OpenCV headless, IfcOpenShell, pye57, pyquaternion, libE57Format, Xerces-C++ and CRC++ are selected for the current core. Open3D and Avalonia remain candidates for later milestones. PDAL is optional and is not part of direct E57 import.

SpatialLM can inform an independently written element/proposal contract now, but its source-code terms are not assumed permissive. Pointcept's reviewed MIT root licence does not cover every associated pretrained asset. Model weights and datasets remain separate inventory entries.

The ACM and May 2026 arXiv references are recorded together as PointLLM-R, not counted as separate engines. The general local-LLM blog is background reading, not an implementation dependency.

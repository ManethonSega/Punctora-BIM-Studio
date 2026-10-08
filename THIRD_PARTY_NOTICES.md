# Third-party notices

## M1 status

See [ATTRIBUTIONS.md](ATTRIBUTIONS.md) for per-component credits and licence notices, and [NOTICE_REGISTER.json](third_party/NOTICE_REGISTER.json) for their machine-readable code/runtime/model/publication scopes. Exact supplied licence texts and disclaimers are retained in `third_party/licenses`; future-candidate references are retained separately in `third_party/references`.

Selected Cloud2BIM geometry routines are incorporated as MIT source. Apache 2.0 applies to original Punctora material. External runtime libraries are installed through pip and are not embedded in this repository or Punctora's wheel. No datasets or model weights are included.

The Python package declares Apache-2.0 AND MIT to reflect its original modules and adapted routines.

## Cloud2BIM licence reference

- Author: Václav Nežerka.
- Repository: <https://github.com/VaclavNezerka/Cloud2BIM>.
- Reviewed revision: `cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e`.
- Licence file: [Cloud2BIM MIT licence](third_party/licenses/Cloud2BIM-MIT.txt).
- Upstream source: <https://github.com/VaclavNezerka/Cloud2BIM/blob/cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e/LICENSE>.
- Import status: selected geometry helpers adapted in `src/punctora_core/cloud2bim_geometry.py` from `aux_functions.py`, and in `src/punctora_core/ifc_geometry.py` from `generate_ifc.py`.

The adapted routines cover distances, collinearity, merging, parallel overlap, intersections, placements, extrusions and representations. Plotting/global configuration imports and unrelated routines are omitted. Headers identify source and changes. Original Punctora orchestration, scan fitting, provenance, per-storey handling and IFC relationship code replace the upstream pipeline. No full upstream application or AI module is copied. The retained MIT licence file is authoritative over the conflicting release README label.

## Selected external dependencies

| Dependency | Version | Retained licence reference |
| --- | --- | --- |
| NumPy | 2.3.5 | [Wheel licence and bundled notices](third_party/licenses/NumPy-2.3.5-wheel.txt), NumPy BSD-3-Clause and additional native terms |
| Shapely | 2.1.2 | [BSD-3-Clause](third_party/licenses/Shapely-2.1.2.txt), [GEOS notice](third_party/licenses/GEOS-Shapely-wheel.txt) |
| opencv-python-headless | 4.11.0.86 | [Python packaging MIT](third_party/licenses/OpenCV-python-4.11.0.86.txt), [native notices including OpenCV Apache-2.0](third_party/licenses/OpenCV-wheel-third-party.txt) |
| IfcOpenShell library | 0.8.3 | Installed source headers specify LGPL-3.0-or-later; [source](https://github.com/IfcOpenShell/IfcOpenShell/blob/v0.8.0/src/ifcopenshell-python/ifcopenshell/__init__.py), [LGPL text](third_party/licenses/IfcOpenShell-LGPL-3.0.txt), [GPL text referenced by LGPL](third_party/licenses/IfcOpenShell-GPL-3.0.txt) |

These are references from the tested Linux dependencies, not a completed Windows binary audit. `requirements-core.txt` records runtime versions including transitive Python dependencies. pytest is a test dependency. Platform-specific bundled/native terms and source/replacement information must be checked before distributing the standalone application.

## Future distributions

Add an entry for every incorporated component with its exact version or commit, source location, copyright, complete applicable licence text and local modifications. A future Windows package must include notices for its actual transitive and native dependencies, not just this candidate list.

For the IfcOpenShell library, include the applicable LGPL/GPL licence texts and required source and replacement information for the packaged build. Do not treat the licences of Bonsai or other applications in its repository as identical to the library's licence.

Optional research components are credited with their own licence notices without including their code, weights or datasets. The intended use is noncommercial. Additional creator permission will be requested only for an actual use that the applicable licence does not cover. No special permission grant is recorded yet.

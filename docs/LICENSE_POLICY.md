# Licence policy

## Original work

Original Punctora code and documentation use Apache-2.0. Preserve the existing root LICENSE. Upstream licences, copyright notices and applicable obligations continue to govern third-party material.

The owner intends noncommercial application use. Component-specific terms still apply; this intent does not relicense original Apache-2.0 source or third-party material. [Attributions](../ATTRIBUTIONS.md) and [the notice register](../third_party/NOTICE_REGISTER.json) map each component's creators, source, licence notices, use and modifications. The package includes the retained notice files.

## Candidate inventory

`dependency-inventory.json` records selected dependencies and candidate code, runtime, model, dataset and research components separately. It is not a lockfile or a release SBOM. The core includes selected MIT Cloud2BIM source and uses pinned external Python dependencies. M2 selects pye57, whose platform wheel contains or links native libE57Format and Xerces-C++ code; their notices and CRC++'s notice are retained separately. Punctora's own wheel does not embed dependency binaries, and no model weights are bundled. A reviewed top-level licence is not approval of every file or transitive dependency.

Before incorporation, record the exact version/commit, files used, applicable licence evidence, native/transitive dependencies and required notices. Before packaging, create an inventory of the actual installed distribution, retain its applicable licence texts and verify its source/replacement requirements. Unpinned candidates remain design choices.

## Specific decisions

- Cloud2BIM: selectively port reviewed MIT-covered code, retain attribution and identify modifications. The GPL label in the supplied release README conflicts with its MIT licence file; resolve source/file provenance rather than relying on the release name.
- IfcOpenShell: use the LGPL-3.0-or-later library through its published API. Plan a replaceable package and fulfil applicable source, notice and modification obligations. Its repository also contains differently licensed applications; do not import Bonsai code under the assumption that it is LGPL.
- E57 runtime: use pye57 0.4.19 with its MIT notice, pyquaternion 0.9.9 under MIT, libE57Format 3.1.1 under BSL-1.0, Xerces-C++ 3.2.3 under Apache-2.0 with NOTICE, and vendored CRC++ under BSD-3-Clause. Recheck the actual platform wheels when creating the Windows installer.
- SpatialLM: keep the Llama-3.2 or Apache-2.0 backbone terms, SceneScript/Sonata noncommercial encoder terms, TorchSparse MIT terms, Sonata Apache-2.0 code terms and the released checkpoint/dataset terms separate. The repository root contains Llama-3.2 terms, while its README describes component-specific licences. Use the notice register to select the applicable attribution for each actual backend.
- Pointcept: the reviewed root LICENSE is MIT. Separate model checkpoints and components such as Sonata have their own terms. A licence statement elsewhere is not sufficient to clear all model assets.
- GPT4Point: the MIT root file and README's CC-BY-NC-SA-4.0 declaration conflict. Keep code and weights out of the initial distribution pending clarification.
- Papers: use cited methods as research references. A paper's licence is not a licence for every external implementation, dataset or model it mentions.
- PointLLM-R: preserve Apache-2.0 for repository code. Its model card declares MIT with base-model and data terms retained; publication terms remain separate.

## Model permissions

No model weights or datasets are bundled in the current core. Use existing component licences when they cover the intended noncommercial use. If a specific planned use needs extra rights, identify the exact component and requested rights for the owner to obtain from its creator. Record any written grant alongside the applicable notice; an attribution is not itself a permission grant.

This is a project implementation policy based on inspected upstream evidence, not a claim that a future distribution is already cleared.

# Licence policy

## Original work

Original Punctora code and documentation use Apache-2.0. Preserve the existing root LICENSE. Upstream licences, copyright notices and applicable obligations continue to govern third-party material.

## Candidate inventory

`dependency-inventory.json` records selected dependencies and candidate code, runtime, model, dataset and research components separately. It is not a lockfile or a release SBOM. M1 includes selected MIT Cloud2BIM source and uses pinned external Python dependencies. No native binaries or model weights are bundled. A reviewed top-level licence is not approval of every file or transitive dependency.

Before incorporation, record the exact version/commit, files used, applicable licence evidence, native/transitive dependencies and required notices. Before packaging, create an inventory of the actual installed distribution, retain its applicable licence texts and verify its source/replacement requirements. Unpinned candidates remain design choices.

## Specific decisions

- Cloud2BIM: selectively port reviewed MIT-covered code, retain attribution and identify modifications. The GPL label in the supplied release README conflicts with its MIT licence file; resolve source/file provenance rather than relying on the release name.
- IfcOpenShell: use the LGPL-3.0-or-later library through its published API. Plan a replaceable package and fulfil applicable source, notice and modification obligations. Its repository also contains differently licensed applications; do not import Bonsai code under the assumption that it is LGPL.
- SpatialLM: its reviewed repository LICENSE.txt is the Llama 3.2 Community License. Code-wide applicability and file-specific terms need clarification before copying code. Its Qwen model card separately lists CC-BY-NC-4.0; the encoder and datasets also need individual review. Independently designed interfaces may be informed by published representations without vendoring their implementation.
- Pointcept: the reviewed root LICENSE is MIT. Separate model checkpoints and components such as Sonata have their own terms. A licence statement elsewhere is not sufficient to clear all model assets.
- GPT4Point: the MIT root file and README's CC-BY-NC-SA-4.0 declaration conflict. Keep code and weights out of the initial distribution pending clarification.
- Papers: use cited methods as research references. A paper's licence is not a licence for every external implementation, dataset or model it mentions.

## Model permissions

No model weights or datasets are bundled at M0. For components with restrictive or unclear terms, obtain a written grant covering the intended use, modification/fine-tuning and redistribution of the relevant assets, or choose a suitable replacement. Record which rights the owner actually controls, including encoder, base-model and data dependencies. Do not assume the application licence, separate worker or separate download overrides those terms.

This is a project implementation policy based on inspected upstream evidence, not a claim that a future distribution is already cleared.

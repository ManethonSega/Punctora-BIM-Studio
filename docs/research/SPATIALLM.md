# SpatialLM: research assessment for Punctora

Reviewed 2026-10-08. Status: research understood and recorded; optional provider candidate, not integrated. This assessment does not change the implemented M2 core or the M3-first development order.

## Source and version

**SpatialLM: Training Large Language Models for Structured Indoor Modeling**, Yongsen Mao, Junhao Zhong, Chuan Fang, Jia Zheng, Rui Tang, Hao Zhu, Ping Tan and Zihan Zhou. Manycore Tech and Hong Kong University of Science and Technology, NeurIPS 2025.

- Supplied paper: arXiv **2506.07491v2**, revised **5 November 2025**, 24 pages. [Versioned paper](https://arxiv.org/abs/2506.07491v2), [DOI](https://doi.org/10.48550/arXiv.2506.07491).
- Supplied PDF SHA-256: `3d6f8ebb92f96c62442275afbd71fb204e253796d0085378f5ec8f36bc8be4e9`.
- [Author project page](https://manycore-research.github.io/SpatialLM/).
- [Implementation README at reviewed revision](https://github.com/manycore-research/SpatialLM/blob/8913c44d84a450c53e9340b13317f8cf7144a738/README.md).
- [Existing component and asset licence assessment](../DEPENDENCIES.md#spatiallm-component-licences).

The arXiv publication declares [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This note is an independently written assessment; the PDF, figures, source implementation, weights and dataset are not copied into Punctora. Publication terms do not replace the separate implementation and model terms.

## What the method actually does

The model consumes a point cloud with XYZ and RGB attributes. A learned point encoder compresses the cloud into features, an MLP projects those features into the language model, and the language model generates structured scene descriptions. The paper's principal configuration combines Sonata/Point Transformer V3 with Qwen2.5-0.5B (Sections 3 and 4).

The generated representation describes wall endpoints and heights, doors/windows with a host-wall reference and dimensions, and oriented bounding boxes with object categories (Figure 2, p. 3; Figure 12, p. 22). Explicit host references are valuable for BIM relationships. Bounding boxes, however, are not detailed editable building geometry. The wall definition in the paper does not establish hidden thickness, construction layers, material or structural function. Slab reconstruction and complete BIM authoring are not supplied by this representation.

Although the output resembles Python, a future adapter should parse a restricted data grammar into Punctora's own element proposals. It should not execute generated scripts. Proposed validation includes permitted record types, numeric bounds, valid IDs, valid host references and job-local output paths.

## Evidence and its limits

These are **reported research results**, not tests performed by Punctora.

| Evidence | Reported result | Meaning for this project |
| --- | --- | --- |
| Synthetic training corpus, Section 3.1 | 12,328 scenes, 54,778 rooms, 59 object categories | Useful scale and structured supervision; not a representative test of our real building surveys |
| Structured3D layouts, Table 5 | F1 at IoU 0.5: 93.5 after synthetic training and Structured3D fine-tuning; 44.7 with synthetic training only | The strongest result depends on adaptation to the target benchmark |
| ScanNet objects, Table 6 | F1 at IoU 0.5: 52.6 for adapted SpatialLM; 56.8 for V-DETR | Competitive object detection, not superiority on every task or detailed IFC geometry |
| Reconstructed-video experiment, Appendix C.3 | Layout F1 at IoU 0.25: 55.7; object F1: 36.9 | Considerable difficulty remains with noisy/incomplete reconstructions; these videos are rendered virtual tours |
| Semantic label completion, Appendix D.2 | 96.8% classification accuracy on the authors' test dataset | An easier task with supplied boxes; not 96.8% end-to-end reconstruction accuracy |

The evaluation uses matched-element overlap and F1, not millimetre surface deviations, survey accuracy or contractual acceptance. The authors also acknowledge domain differences among RGBD, video-derived and LiDAR clouds and the need for target-specific fine-tuning (Section 5).

Section 4.3 explicitly describes completing occluded object extents and plausible missing room regions. That capability can help produce suggestions, but completed geometry must remain `inferred`. It must not be promoted to `measured` merely because it looks convincing or connects neatly to other elements.

The paper notes that autoregressive methods do not produce detection confidence scores (Section 4.2). Punctora must not display an invented probability of correctness. Scan support, residuals, coverage and user review are separate evidence, not interchangeable with calibrated model confidence.

## Coordinate and input implications

Appendix B shifts coordinates into a nonnegative frame and quantizes them into 1,280 bins at **2.5 cm** resolution, then reverses the transformations. This is a proposal-coordinate grid, not a promise of measurement accuracy. Sub-centimetre accepted dimensions require further fitting against source records; even that fitting cannot certify absolute survey accuracy.

The grid describes a nominal span of approximately 32 m. That arithmetic does not prove how every released checkpoint handles larger inputs. A future adapter must verify its exact normalization, coordinate range and clipping behaviour. Large floors should be evaluated through bounded room/storey crops, with recorded transforms and explicit merging tests, rather than assumed to fit in one model call.

The reviewed implementation expects axis-aligned clouds with Z up. Preserve the implemented E57 scan poses and local/project mapping. Any model-specific alignment, crop origin and quantization are additional recorded transforms, applied and inverted once. Cross-crop deduplication and wall/host identity reconciliation must retain stable Punctora IDs and evidence selectors.

XYZRGB is the research input. E57 records may lack RGB; intensity is not RGB. Colourless/intensity-only surveys require explicit evaluation of the exact model and preprocessing. No success claim follows from simply inserting default colours.

## Decisions for Punctora

| Topic | Decision recorded from this review |
| --- | --- |
| Role | Candidate provider for wall/opening/class proposals, using the common downstream fitting/review/IFC pipeline |
| Precision | AI coordinates seed fitting; accepted geometry is checked against original observed surfaces |
| Missing geometry | Keep inferred completions visibly distinct; unsupported hidden properties stay unknown |
| Relations | Preserve explicit opening-to-wall references, then validate them geometrically and in IFC |
| M3 review | Design the overlay to distinguish proposals, supported geometry, user edits and unresolved elements; show evidence and allow rejection/correction |
| M6 experiment | Benchmark a replaceable optional adapter against the existing contour and region-growing providers on the same scans |
| Core availability | Keep the first usable app local and operational without AI weights, CUDA or an NVIDIA GPU |

These are design decisions and future acceptance requirements, not implemented features. They reinforce [R02, R04, R05, R07, R08, R09 and R10](../PROJECT_REQUIREMENTS.md).

## Integration experiment to perform later

1. Pin the checkpoint, point encoder, preprocessing and component licences. Record exact inference hardware and dependency versions. The reviewed upstream installation targets Python 3.11, PyTorch 2.4.1 and CUDA 12.4; that is not evidence of AMD, CPU-only or packaged Windows inference support.
2. Use a small consented real E57 floor, split into bounded crops with reversible coordinates. Include rotated rooms, colourless data, partial observations, thin partitions and genuinely missing areas.
3. Parse proposals as data. Preserve the original model output for reproducibility, then validate classes, hosts and coordinates before entering the common pipeline.
4. Compare classical-only, AI-only proposals and AI plus source-based fitting. Assess missed/false elements, wall-face deviation, opening geometry, unsupported completions, IFC relationships, runtime, peak memory and human correction time.
5. Test room boundaries and crop stitching explicitly. Repeated runs must not duplicate elements or lose host references. Cancellation/failure must leave the saved project intact.
6. Adopt the provider only if it improves practical accuracy or correction effort within the project's tolerances. A higher benchmark F1 or more attractive preview alone is insufficient.

The paper's training run used 32 NVIDIA H20 GPUs for approximately one day (Appendix B). That is a **training** resource report, not an inference requirement or estimate. Training from scratch is not the next project step; a separately evaluated released model is the relevant optional experiment.

## Conclusion for the development plan

SpatialLM is a directly relevant architectural-proposal reference. Its strongest contribution to Punctora is an explicit, editable structure with host relationships, coupled to a learned semantic proposal provider. The current geometric core, reversible E57 handling, original-record fitting and user review remain necessary. Continue M3 desktop review and the real-scan trial; prepare the adapter boundary now and evaluate actual AI integration in M6.

## Follow-up: supplied E57 examples and practical priorities

The PDF supplied again on 2026-10-08 has the same SHA-256 as the indexed version above. Its representation and encoder figures were visually checked against the extracted text. The two supplied E57 examples have now passed full-record import-integrity checks; see [sample verification](../M2_SUPPLIED_E57_VERIFICATION.md). They have not been run through SpatialLM or accepted as reconstructed BIM.

| Finding | Practical consequence | Status |
| --- | --- | --- |
| Station018 has a source-aligned X extent of about 711 m, substantially beyond the paper's nominal 32 m quantized span | Record crop bounds, alignment and inverse transforms; test overlaps, deduplication and opening hosts before any whole-floor AI claim | Future adapter requirement; cropping/stitching is not implemented |
| Both examples include RGB and intensity, but their coordinateMetadata strings are empty | They exercise coloured input import, not colourless-model performance or verified georeferencing | Import checked; AI suitability and CRS remain unverified |
| One of the pump's five scans has no pose | Keep the missing-pose warning visible. Identity is the import fallback, not evidence that scan registration is correct | Existing importer behaviour verified |
| The paper uses a learned hierarchical point encoder; naive feature pooling performs poorly in its Table 2 | Preserve local geometry for semantic proposals; do not assume a cheap RGB/feature average reproduces the model. This result does not invalidate voxel sampling for classical plane fitting | Research finding, no new encoder integrated |
| More visual tokens do not improve every score in Table 3 | Measure crop resolution versus accuracy, runtime and memory instead of blindly increasing density | Future controlled experiment |
| Appendix B includes edge noise, floating points, colour loss and partial crops | Extend future real-scan comparisons with reflections, incomplete walls and colourless inputs, keeping the same reference geometry and correction-time measures | Benchmark backlog; generated M2 results remain unchanged |

The immediate M3 benefit is review design: show evidence and unsupported extents, distinguish observed surfaces from inferred completions, preserve identity through edits, and allow rejection. The later M6 benefit is an optional structured proposal provider for walls and openings. No weights, training corpus, model source or figures have been added to the repository, and no new runtime dependency is introduced by this research note.

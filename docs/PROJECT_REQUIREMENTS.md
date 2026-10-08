# Project requirements

These design requirements are informed by the user's three point-cloud documents, version V0.03: the creation guidelines, preliminary-meeting checklist and completion-report attachment. The original documents are not redistributed in this public repository. This summary covers conversion-software requirements, not scanning-contractor deliverables or a claim of compliance.

The guidelines explicitly separate point-cloud creation from BIM model creation. Their stated point-cloud accuracy requirements are not automatically model tolerances.

| ID | Requirement | Source topic | Planned evidence |
| --- | --- | --- | --- |
| R01 | Preserve source files and identify repeatable processing runs | Guidelines: processing and metadata | Fingerprint, job parameters, engine version and separate derived output |
| R02 | Preserve scan poses, units, project origin and coordinate transformations | Guidelines section 4.2; checklist: georeferencing | Transform records and round-trip coordinate fixtures |
| R03 | Capture missing CRS and vertical reference information explicitly | Guidelines: coordinate system selection | User confirmation; no silent CRS guessing |
| R04 | Support storey/building-part organisation and isolated reconstruction | Guidelines section 5.2; checklist: segmentation | Two-storey isolation test and stable segment IDs |
| R05 | Store configurable project and element tolerances | Checklist: technical requirements and acceptance | Separate scan-quality and model-deviation fields; no universal millimetre guarantee |
| R06 | Preserve supplied scan metadata and distinguish missing fields | Guidelines section 4.2.5; report section 4.3 | Scanner/date/software/source-quality fields with origin and unknown states |
| R07 | Record inaccessible, unscanned and excluded areas | Guidelines: inaccessible areas; report section 2.3 | Coverage/exclusion records and visibly unresolved reconstruction |
| R08 | Measure model deviation against original observed surfaces | Guidelines: relationship between cloud/model quality and validation | Defined statistics, samples, coverage and exclusions |
| R09 | Separate measurements, inferences and user inputs | Report: alternative information; guidelines: geometric/semantic quality | Parameter-level provenance, assumptions report and review status |
| R10 | Produce editable IFC elements with validated relationships | Application goal, extending beyond source documents | IFC rules, geometric checks and independent viewer inspection |
| R11 | Keep model validity separate from survey and contractual acceptance | Guidelines: separate modelling scope; checklist: acceptance | Distinct schema/geometry/deviation/survey-quality findings |
| R12 | Process scans locally by default | Application design decision | No scan upload or network dependency in the initial conversion workflow |
| R13 | Accelerate point-cloud-to-IFC conversion using multiple CPU cores and an available compatible GPU where measured beneficial, retaining CPU fallback | User clarification, 2026-10-08 | Stage timings and complete-job CPU/multicore/GPU comparisons; bounded RAM/VRAM; agreed numerical equivalence, stable evidence/identity and valid IFC; target AMD hardware verified separately |

## Unknowns requiring project input

Model tolerances, wall thickness evidence, material/structural information, CRS/vertical datum and reference dimensions cannot be invented by the application. When absent, record them as unknown or explicitly inferred. Source scanning documents may contain category-specific point-cloud thresholds, but the software must not hard-code them as a general reconstruction guarantee.

Document sensor/registration accuracy as supplied information. Point-to-model residuals alone cannot verify scanner calibration, absolute survey accuracy or concealed building construction.

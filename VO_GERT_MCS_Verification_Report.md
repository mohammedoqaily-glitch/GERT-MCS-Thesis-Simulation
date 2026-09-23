# VO PERT-GERT Final Appendix Verification Report

**Acceptance classification: READY FOR THESIS APPENDIX**

## 1. Audit scope and provenance

The audit indexed 1,027 relevant project artifacts: 69 Python files, 706 CSV files, 80 workbooks, 6 Word inputs, 146 JSON files, 17 Markdown files, 2 text manifests, and 1 YAML configuration. No notebooks were present. Duplicate packaged/exported artifacts were reconciled by hash and content rather than treated as independent implementations.

Principal files inspected were:

- `release/VO_PERT_GERT_Full_Simulation_Package/11_SOURCE_AND_REPRODUCIBILITY/Source/simulation_core/simulate_final.py`
- `work/final_preliminary/simulate_final.py`
- `work/final_preliminary/validate_final.py`
- `work/final_preliminary/build_final_outputs.py`
- `release/VO_PERT_GERT_Full_Simulation_Package/01_AUTHORITATIVE_INPUTS/PERT Input.docx`
- `release/VO_PERT_GERT_Full_Simulation_Package/01_AUTHORITATIVE_INPUTS/GERT nput.docx`
- release-package PERT/GERT iteration, summary, route, traversal, loop, and exact-verification CSV files
- `release/VO_PERT_GERT_Full_Simulation_Package/12_SUPPORTING_REPORTS/prepackaging_validation.json`
- `release/VO_PERT_GERT_Full_Simulation_Package/12_SUPPORTING_REPORTS/raw_export_integrity.json`
- `release/VO_PERT_GERT_Full_Simulation_Package/11_SOURCE_AND_REPRODUCIBILITY/simulation_configuration.json`
- `release/VO_PERT_GERT_Full_Simulation_Package/11_SOURCE_AND_REPRODUCIBILITY/random_stream_metadata.json`
- `release/VO_PERT_GERT_Full_Simulation_Package/11_SOURCE_AND_REPRODUCIBILITY/Dependency_Manifest.json`
- `release/VO_PERT_GERT_Full_Simulation_Package/11_SOURCE_AND_REPRODUCIBILITY/requirements-lock.txt`
- `sensitivity/{model.py,analysis.py,statistics.py,bimodality.py,config.py}`
- `sensitivity_config.yaml`, `run_sensitivity.py`, all nine `tests/test_*.py` modules, and the completed sensitivity reports/outputs
- the older portable GUI implementation under `work/vo_pert_gert/` and its packaged copies

The authoritative result-generating implementation is `simulate_final.py` in the release package. It is byte-identical to `work/final_preliminary/simulate_final.py`:

```text
SHA-256  8bc526bb1052089aaa75f2bd97713f8adb2b29077e5f06cab2a6f167bc7a8940
```

The authoritative input identities are:

| Input | SHA-256 |
|---|---|
| `PERT Input.docx` | `7984b5b2e29928345772f0110ea1fa1c9ceb4121dc2e3aed4737112a98bc1f58` |
| `GERT nput.docx` | `dc34b00fcd3988146da0760ac18499eeca9d8596601c09445ca5d956c4ae6387` |

This attribution is supported by the release dependency/configuration manifests, matching source hashes, matching accepted output counts, and exact row-level reconciliation. The portable GUI engine was not used as the appendix source because it uses Python `random.Random`, supports a demonstration fallback model, and does not reproduce the final stream behavior.

## 2. Final implementation

`VO_GERT_MCS_Final_Appendix.py` preserves the released numerical method while removing machine-specific paths and runtime Word parsing. The validated authoritative activities, arcs, probabilities, duration triplets, ordering, and caps are embedded as typed immutable records so the appendix is self-contained and inspectable.

Preserved numerical behavior:

- 50,000 PERT and 50,000 GERT replications; root seed 42.
- `SeedSequence(42).spawn(3)` with PCG64 child streams in fixed order: PERT duration, GERT routing, GERT duration.
- conventional Beta-PERT with lambda 4 and explicit deterministic-duration handling.
- ceiling immediately after every activity/realized-arc draw.
- fixed six-activity PERT route and the released 29-arc GERT XOR network.
- independently tracked cap 2 for `e22,e21,e33,e32,e43,e42,e55,e54,e52,e66`.
- cap-based exclusion followed by proportional renormalization of the eligible XOR alternatives.
- nearest-rank percentiles and sample variance/standard deviation (`ddof=1`).
- `S7` successful closure and `ST` withdrawn/rejected as absorbing outcomes; `SD` remains transient.

Refactoring was limited to dataclasses, small validation/simulation/export functions, explicit CLI configuration, relative output paths, stronger route replay checks, and deterministic CSV/JSON output. The CSV writer uses the ordered union of row fields so heterogeneous sensitivity records retain their intervention parameters. No probabilities, duration estimates, arc ordering, caps, random streams, rounding operations, or statistical definitions were changed.

## 3. Specification discrepancies

The repository evidence takes precedence over the prose specification, as requested. The following differences were preserved and disclosed rather than silently changed:

| Prompt description | Authoritative released implementation |
|---|---|
| Separate `S_End` after `S7` | `S7` itself is the absorbing successful terminal state. |
| Dispute entries listed from `S4`, `S5`, and `S6` | The released model also contains `e3D: S3 -> SD`. |
| Feedback list does not mention `S2 -> S1` | The released model includes capped return arc `e21: S2 -> S1`. |
| PERT nominal sequence starts at `S0 -> S1` | `e01` is a zero-duration structural arc; PERT duration sampling begins with `e12`. |
| State notation `S_T` and `S_D` | Implemented identifiers are `ST` and `SD`. |
| Verification figures near PERT mean 113.52 and success rate 58.40% | Final release data reproduce PERT mean 115.17844 and success rate 57.742%. |

These are provenance discrepancies, not defects in the appendix script. No output was tuned to the supplied approximate figures.

## 4. Verification tests

The final script was executed twice from separate fresh processes with CPython 3.12.14 and NumPy 2.3.5. Each process also performs an internal independent same-seed rerun. All 64 script checks passed in both external runs. All seven exported files were byte-identical between runs. The existing project test suite also passed 27/27 tests.

| Test | Result | Evidence |
|---|---|---|
| 1. Syntax/execution | PASS | `py_compile` succeeded; both complete processes exited 0. |
| 2. Reproducibility | PASS | All output SHA-256 hashes identical; result signature identical. |
| 3. Probability validation | PASS | Seven XOR groups finite, non-negative, and sum to 1; perturbation tests pass. |
| 4. Duration validation | PASS | All O/M/P triples finite and ordered; invalid values raise explicit errors. |
| 5. Network integrity | PASS | Exact state/arc sets, terminal behavior, connectivity, and success reachability checked. |
| 6. Loop-cap integrity | PASS | Every realized loop count is <= cap; original loop-cap tests pass. |
| 7. Termination integrity | PASS | Every route replays legally and no route continues after `ST`. |
| 8. Successful-closeout integrity | PASS | Every successful route replays legally to `S7`. |
| 9. Replication accounting | PASS | 28,871 + 21,129 = 50,000; no computational outcome. |
| 10. Numerical verification | PASS against authoritative release | Exact released statistics and all 50,000 rows reproduced; supplied preliminary targets differ as documented. |
| 11. Path accounting | PASS | 50,000 paths reconcile to 380 exact routes; route counts sum to 50,000. |
| 12. Statistical sanity | PASS | No NaN, Inf, negative duration, invalid outcome, empty subset, or invalid probability. |

Additional checks cover deterministic Beta-PERT inputs, per-activity ceiling, PERT summation, dynamic XOR renormalization, dispute non-terminality, valid state identifiers, the maximum-step watchdog, and matching PERT/GERT nominal duration assumptions.

## 5. Reproduced principal results

| Population | N | Mean | Variance | SD | Min | P50 | P80 | P90 | P95 | Max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| PERT-MCS | 50,000 | 115.17844 | 38.04916 | 6.16840 | 97 | 115 | 121 | 124 | 126 | 138 |
| GERT combined | 50,000 | 66.80548 | 3173.08778 | 56.33017 | 3 | 100 | 112 | 118 | 129 | 397 |
| GERT successful | 28,871 | 112.49160 | 530.08811 | 23.02364 | 37 | 109 | 117 | 125 | 149 | 397 |
| GERT withdrawn/rejected | 21,129 | 4.37924 | 35.35309 | 5.94585 | 3 | 4 | 4 | 4 | 4 | 186 |

Other reproduced diagnostics:

| Diagnostic | Reproduced value |
|---|---:|
| Successful closeout probability | 57.742% |
| Withdrawn/rejected probability | 42.258% |
| Dispute diversion probability | 2.268% |
| At least one capped-loop traversal, all runs | 10.812% |
| At least two loop traversals, conditional on success | 1.9293% |
| Exact routes observed | 380 |

Successful-duration means by total loop traversal count were 107.85650 days (0), 131.80531 (1), 161.91093 (2), 189.44068 (3), 187.5 (4; two runs), and 193.0 (5; two runs).

## 6. Comparison with supplied verification targets

The combined GERT P50/P80/P90/P95 and several conditional percentiles agree with the prompt. Material differences are concentrated in the PERT baseline, outcome mix, and upper-tail/extreme values:

| Metric | Supplied approximate target | Reproduced final release | Difference |
|---|---:|---:|---:|
| PERT mean | 113.52 | 115.17844 | +1.65844 |
| PERT SD | 5.47 | 6.16840 | +0.69840 |
| PERT P95 | 122 | 126 | +4 |
| GERT combined mean | 67.54 | 66.80548 | -0.73452 |
| Successful rate | 58.40% | 57.742% | -0.658 percentage points |
| Successful SD | 23.66 | 23.02364 | -0.63636 |
| Successful P95 | 152 | 149 | -3 |
| Successful maximum | 379 | 397 | +18 |
| Termination rate | 41.60% | 42.258% | +0.658 percentage points |
| Any-loop rate | 10.52% | 10.812% | +0.292 percentage points |

Investigation found that the supplied targets are not the values in the final release package. The appendix output matches the final authoritative source and released iteration datasets exactly: zero mismatches across 50,000 PERT rows and zero mismatches across 50,000 GERT rows for the reconciled fields. The supplied values therefore appear to be preliminary/stale results. Changing the model to force agreement would violate the documented provenance.

## 7. Sensitivity and robustness

The completed thesis sensitivity package was audited. Its design comprises 111 distinct full GERT runs: baseline; low/high perturbations of 29 routing probabilities; low/high duration scaling for the screened arcs `e45,e24,e56,e67,e12`; low/high cap tests for ten capped arcs; one triangular-duration run; ten fixed-seed runs; and eleven `e1T` probability-grid runs. It also derives convergence subsets and bootstrap/KDE/GMM diagnostics without treating them as additional independent model runs.

The appendix preserves the 111 model-running scenarios behind `--run-sensitivity`. The existing detailed reporting modules and generated workbooks remain authoritative for bootstrap intervals, bimodality diagnostics, figures, and formatted thesis tables; those presentation layers were not duplicated into the appendix script.

The optional appendix mode was executed at 50,000 replications per scenario. It exported 111 unique scenario rows, all with zero computational errors. Nine directly comparable metrics were reconciled for every scenario against the existing routing, duration, loop-cap, distribution, seed, and threshold tables (999 comparisons in total); no mismatch was found. The verified sensitivity CSV SHA-256 is `48554c45215adc5ab6eb4528e1baba8eb249a595c0be896ff8b08ac2febba5c9`.

## 8. Dependency and identity record

- Release environment: CPython 3.12.13, NumPy 2.3.5.
- Final verification environment: CPython 3.12.14, NumPy 2.3.5.
- Appendix runtime dependency: `numpy==2.3.5` only.
- Result-array signature: `2245cfe7452c068ec418d09e9b84c3a6ca48c9f67278bb0dce2ffdb4f1bddcad`.
- Final appendix script SHA-256: `735673fb10be77130270aa9303047e7bce9c92b3e623bb9aa8cf56b27b849bd4`.

No unresolved syntax, execution, accounting, reproducibility, dependency, or numerical-provenance issue remains.

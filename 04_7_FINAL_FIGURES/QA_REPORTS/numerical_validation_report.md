# Section 4.7 Numerical Validation Report

**Overall status: PASS**

## Authoritative Source

- ZIP: `C:\Users\moham\Documents\Codex\2026-07-28\build\release\VO_PERT_GERT_Full_Simulation_Package.zip`
- SHA-256: `e5b6e1a9ccec1f83bf91317e3e432e9beb044ef949d5fd80c9e505f7fa95978f`
- Expected SHA-256: `e5b6e1a9ccec1f83bf91317e3e432e9beb044ef949d5fd80c9e505f7fa95978f`
- ZIP hash status: `PASS`

The generator extracted the following CSV members into an isolated temporary directory and recomputed all values from them:

- `pert_iterations`: `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/02_PERT_Raw_Data__PERT_Iterations_Wide.csv`
- `pert_convergence`: `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/09_Convergence_Data__PERT_Checkpoints.csv`
- `gert_iterations`: `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/04_GERT_Iteration_Data__Iteration_Summary.csv`
- `gert_features`: `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/07_GERT_Analysis_Ready__Iteration_Feature_Matrix.csv`
- `gert_paths`: `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/04_GERT_Iteration_Data__Path_Register.csv`
- `gert_duration_convergence`: `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/09_Convergence_Data__GERT_Duration_Checkpoints.csv`
- `gert_outcome_convergence`: `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/09_Convergence_Data__GERT_Outcome_Checkpoints.csv`
- `loop_register`: `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/01_Input_and_Metadata__Loop_Register.csv`

## Statistical Rules

- Durations: integer working days.
- Standard deviations: sample SD (`ddof=1`).
- Percentiles: nearest-rank, rank `ceil(p * N)`.
- Bin definition: one-day bins centred on integer durations.
- Outcome intervals: two-sided Wilson 95% confidence intervals.
- Variance decomposition: sums-of-squares identity; between-group sum of squares divided by total sum of squares.
- Route hierarchy: successful dispute-bearing routes take precedence, followed by feedback-loop-bearing routes, self-loop-bearing routes, the exact fixed PERT route, the dominant direct route, and other successful loop-free routes. This mutually exclusive hierarchy reproduces every supplied variance and tail checkpoint.

## Mandatory Checks

| Metric | Target | Observed | Difference | Status |
|---|---:|---:|---:|:---:|
| PERT N | 50000 | 50000 | 0 | PASS |
| PERT Mean | 115.17844 | 115.17844 | 0 | PASS |
| PERT SD | 6.1684 | 6.16840013 | 1.29e-07 | PASS |
| PERT P50 | 115 | 115 | 0 | PASS |
| PERT P80 | 121 | 121 | 0 | PASS |
| PERT P90 | 124 | 124 | 0 | PASS |
| PERT P95 | 126 | 126 | 0 | PASS |
| PERT P99 | 130 | 130 | 0 | PASS |
| Successful N | 28871 | 28871 | 0 | PASS |
| Successful Mean | 112.491601 | 112.491601 | -4.32e-07 | PASS |
| Successful SD | 23.023642 | 23.0236424 | 3.97e-07 | PASS |
| Successful P50 | 109 | 109 | 0 | PASS |
| Successful P80 | 117 | 117 | 0 | PASS |
| Successful P90 | 125 | 125 | 0 | PASS |
| Successful P95 | 149 | 149 | 0 | PASS |
| Successful P99 | 213 | 213 | 0 | PASS |
| Withdrawn/Rejected N | 21129 | 21129 | 0 | PASS |
| Withdrawn/Rejected Mean | 4.379242 | 4.3792418 | -2e-07 | PASS |
| Withdrawn/Rejected P50 | 4 | 4 | 0 | PASS |
| Withdrawn/Rejected P80 | 4 | 4 | 0 | PASS |
| Withdrawn/Rejected P90 | 4 | 4 | 0 | PASS |
| Withdrawn/Rejected P95 | 4 | 4 | 0 | PASS |
| Withdrawn/Rejected P99 | 19 | 19 | 0 | PASS |
| Successful probability (%) | 57.742 | 57.742 | 7.11e-15 | PASS |
| Withdrawn/Rejected probability (%) | 42.258 | 42.258 | 0 | PASS |
| Between outcomes variance share (%) | 89.883 | 89.8831007 | 0.000101 | PASS |
| Between exact routes variance share (%) | 93.547 | 93.5474268 | 0.000427 | PASS |
| Between broad categories variance share (%) | 59.487 | 59.4871612 | 0.000161 | PASS |
| P90 feedback-loop-bearing share (%) | 55.759 | 55.7588076 | -0.000192 | PASS |
| P90 dispute-bearing share (%) | 33.503 | 33.50271 | -0.00029 | PASS |
| P95 feedback-loop-bearing share (%) | 55.533 | 55.5327869 | -0.000213 | PASS |
| P95 dispute-bearing share (%) | 44.467 | 44.4672131 | 0.000213 | PASS |
| P99 dispute-bearing share (%) | 81.107 | 81.1074919 | 0.000492 | PASS |

## Typography and Export

- Selected font: `Times New Roman`
- Resolved font file: `C:\Windows\Fonts\times.ttf`
- Matplotlib: `3.11.1`
- Python: `3.12.13`
- PNG resolution requested: `1200 dpi`
- PDF font mode: TrueType (`pdf.fonttype = 42`)

## Findings

All mandatory numerical targets passed. Source-table reconciliation passed for GERT iteration IDs, durations, outcomes, and row counts. No data substitutions or fitted distributions were used.

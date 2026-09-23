# VO PERT-GERT Appendix Reproduction

## Requirements

- CPython 3.12
- The single package pinned in `requirements.txt`

The appendix script is self-contained. Its PERT activities and GERT network are an exact, inspectable transcription of the authoritative thesis inputs; the original Word files are not required at runtime.

## Fresh environment

From this directory on Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe .\VO_GERT_MCS_Final_Appendix.py
```

The final command runs 50,000 PERT replications and 50,000 GERT replications with root seed 42. It executes the simulation twice internally, checks that the result signatures agree, runs the model and realization integrity checks, and writes deterministic files to `appendix_outputs/`.

Successful execution prints JSON with `"status": "PASS"`. The principal machine-readable outputs are:

- `appendix_outputs/simulation_summary.json`
- `appendix_outputs/verification_tests.json`
- `appendix_outputs/pert_iterations.csv`
- `appendix_outputs/gert_iterations.csv`
- `appendix_outputs/path_frequencies.csv`
- `appendix_outputs/loop_arc_diagnostics.csv`
- `appendix_outputs/successful_loop_depth_diagnostics.csv`

## Optional sensitivity mode

The documented 111-scenario one-way and robustness design can be run at the thesis replication count with:

```powershell
.\.venv\Scripts\python.exe .\VO_GERT_MCS_Final_Appendix.py --run-sensitivity --sensitivity-replications 50000
```

This additionally writes `appendix_outputs/sensitivity_scenarios.csv`. It is computationally much more expensive than the baseline reproduction.

## Verification identity

The accepted appendix script has SHA-256:

```text
735673fb10be77130270aa9303047e7bce9c92b3e623bb9aa8cf56b27b849bd4
```

See `VO_GERT_MCS_Verification_Report.md` for provenance, model discrepancies, test results, and the comparison with the thesis figures supplied for verification.

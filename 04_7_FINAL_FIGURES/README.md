# Section 4.7 Final Figures

This package contains the complete reproducible figure set for thesis Section 4.7.

## Contents

- `PNG_1200DPI/`: 16 high-resolution PNG figures at 1200 dpi.
- `PDF_VECTOR/`: 16 vector PDF figures.
- `FIGURE_DATA/`: plot-ready CSV data for every figure.
- `QA_REPORTS/`: numerical checks, figure inventory, file hashes, and visual-QA artifacts.
- `SOURCE_CODE/generate_all_section_4_7_figures.py`: the complete generator.

## Authoritative Input

- ZIP: `C:\Users\moham\Documents\Codex\2026-07-28\build\release\VO_PERT_GERT_Full_Simulation_Package.zip`
- SHA-256: `e5b6e1a9ccec1f83bf91317e3e432e9beb044ef949d5fd80c9e505f7fa95978f`

Source CSV members:

- `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/02_PERT_Raw_Data__PERT_Iterations_Wide.csv`
- `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/09_Convergence_Data__PERT_Checkpoints.csv`
- `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/04_GERT_Iteration_Data__Iteration_Summary.csv`
- `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/07_GERT_Analysis_Ready__Iteration_Feature_Matrix.csv`
- `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/04_GERT_Iteration_Data__Path_Register.csv`
- `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/09_Convergence_Data__GERT_Duration_Checkpoints.csv`
- `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/09_Convergence_Data__GERT_Outcome_Checkpoints.csv`
- `VO_PERT_GERT_Full_Simulation_Package/09_ALL_CSV/01_Input_and_Metadata__Loop_Register.csv`

## Reproduce

Use Python with NumPy, pandas, and Matplotlib installed:

```powershell
python SOURCE_CODE/generate_all_section_4_7_figures.py --zip "C:\Users\moham\Documents\Codex\2026-07-28\build\release\VO_PERT_GERT_Full_Simulation_Package.zip" --output "C:\Users\moham\Documents\Codex\2026-07-28\build\04_7_FINAL_FIGURES"
```

The script verifies the ZIP hash, extracts the required CSVs to a temporary directory, recomputes all statistics, stops if a mandatory checkpoint fails, then regenerates every artifact. The selected typeface was **Times New Roman**.

Figure titles are recorded in `QA_REPORTS/figure_inventory.csv`; titles and captions are intentionally not embedded inside plotting areas.

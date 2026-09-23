VO PERT-GERT FULL SIMULATION PACKAGE
====================================

This package contains the complete preliminary PERT-MCS and GERT-MCS simulation dataset.

Simulation configuration
------------------------
- 50,000 iterations per model.
- Root seed 42.
- Beta-PERT lambda 4.
- Activity- and traversal-level ceiling.

Recommended starting files
--------------------------
- 02_MASTER_AND_METADATA/00_Master_Index.xlsx
- 00_START_HERE/RAW_DATA_EXPORT_REPORT.md
- 02_MASTER_AND_METADATA/Data_Dictionary.xlsx
- 03_PERT_RESULTS/03_PERT_Analysis_Ready.xlsx
- 04_GERT_RESULTS/07_GERT_Analysis_Ready.xlsx
- 07_SENSITIVITY_READY/10_Sensitivity_Ready_Data.xlsx
- 08_VALIDATION_AND_RECONCILIATION/11_Validation_and_Reconciliation.xlsx

Format guidance
---------------
Excel files are provided for review and analysis. Parquet files are the preferred format for large programmatic analyses. CSV files provide universal fallback access.

Analytical scope
----------------
The baseline matrices support descriptive, correlation, regression, path, structural, and tail-driver analyses. Sensitivity to fixed probabilities, O/ML/P parameters, and Loop Caps requires additional approved parameter-variation runs. Baseline associations must not be interpreted as causal effects.

Integrity
---------
See checksums.sha256, PACKAGE_CONTENTS.xlsx, and PACKAGE_VALIDATION_REPORT.md before analysis. Package-relative paths are used throughout.

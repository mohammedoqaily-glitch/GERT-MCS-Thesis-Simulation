# Legacy Error Audit

| Location | Issue | Corrective action | Test |
|---|---|---|---|
| vo_pert_gert.engine.default_case | Demonstration P01-P04 and START/ASSESS/DISPUTE network existed in previous package. | Normal release gate now parses the authoritative Word input and blocks when incomplete. Demo data is not used for prepared outputs. | test_no_demo_fallback (blocked by authoritative input gate). |
| generate_package_outputs.py | Previous package generated a 1,000-iteration sample from fallback data. | Corrected package does not run simulation when authoritative Word cells are incomplete. | Input audit status is AUTHORITATIVE INPUT INCOMPLETE - SIMULATION BLOCKED. |
| outputs.py | Previous chart workbooks could contain metadata without native chart assertions. | Release remains blocked before output generation. | Workbook generation tests are not executed because input gate failed. |
| engine.py | Previous calculations were demonstration-only and not tied to Word Arc Tags. | Authoritative parser requires explicit Arc and Tag before simulation. | Input audit enumerates missing Arc/Tag cells. |
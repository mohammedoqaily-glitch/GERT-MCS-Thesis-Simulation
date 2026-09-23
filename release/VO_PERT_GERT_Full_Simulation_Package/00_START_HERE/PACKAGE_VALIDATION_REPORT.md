# Package Validation Report

Status: PASS
Validation timestamp (UTC): 2026-07-30T00:54:47+00:00

The completed full extraction and integrity validation below was performed on the pre-report archive. This report was then inserted, the master archive was recreated, and the recreated archive was independently revalidated before delivery.

## Package Counts

- Total packaged files: 544
- Total package folders: 30
- Total Excel workbooks: 16
- Unique CSV datasets: 127
- Unique Parquet datasets: 127
- Physical CSV dataset copies: 254
- Physical Parquet dataset copies: 254
- Total raw-data file copies: 508
- Total source files: 3
- Total uncompressed size: 661587194 bytes
- Validated pre-report ZIP size: 368886606 bytes
- Validated pre-report ZIP SHA-256: 3e76d947beb5eb3a397851605cfc308a3f9e9caf95c3b6e3d340cab63a07c3eb

The organized result folders contain one copy of each of the 127 CSV and 127 Parquet datasets. The complete verified CSV and Parquet directories are also copied unchanged into 09_ALL_CSV and 10_ALL_PARQUET, producing 254 physical files per format without changing dataset counts.

The recreated master ZIP size and SHA-256 are reported with release delivery. A ZIP cannot contain its own stable final SHA-256 because inserting that digest would change the archive bytes.

## Integrity Results

- Corrupt ZIP members: 0
- Missing required files: 0
- Hash mismatches after extraction: 0
- Excel open failures after extraction: 0
- CSV read failures: 0
- Parquet read failures: 0

## Validation Checks

| Category | Check | Observed | Expected | Status |
|---|---|---:|---:|---|
| ZIP | ZIP exists, nonzero, and is valid format | 368886606 | >0 and zipfile=True | PASS |
| ZIP | ZipFile.testzip | 0 | 0 | PASS |
| ZIP | Staged/ZIP member path parity | missing=0 unexpected=0 | 0/0 | PASS |
| ZIP | Uncompressed size parity | 0 | 0 | PASS |
| ZIP | CRC parity | 0 | 0 | PASS |
| Extraction | Extracted hashes match checksums manifest | 0 | 0 | PASS |
| Extraction | Required file names present | 0 | 0 | PASS |
| Extraction | All extracted Excel workbooks open | 0 | 0 | PASS |
| Extraction | Extracted CSV sample read | 0 | 0 | PASS |
| Extraction | Extracted Parquet sample read | 0 | 0 | PASS |
| Extraction | Physical CSV dataset copies | 254 | 254 | PASS |
| Extraction | Physical Parquet dataset copies | 254 | 254 | PASS |
| Extraction | Unique CSV datasets | 127 | 127 | PASS |
| Extraction | Unique Parquet datasets | 127 | 127 | PASS |

## Manifest Note

checksums.sha256 is the detached machine-verification manifest for every packaged file except itself. PACKAGE_CONTENTS.xlsx and PACKAGE_CONTENTS.csv record every packaged path; their own SHA-256 cells are marked self-referential because embedding a file's final cryptographic digest inside that same file is not mathematically stable.

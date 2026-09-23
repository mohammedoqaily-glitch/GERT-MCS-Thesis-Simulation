# Section 4.7 Artifact Validation Report

**Overall status: PASS**

- Figure pairs expected/found: 16/16
- PNG target resolution: 1200 dpi
- PNG metadata tolerance: +/- 1 dpi (Matplotlib records 1200 dpi as approximately 1199.9976 dpi in the PNG pHYs chunk)
- PDF pages: one per figure
- PDF vector check: no image XObjects in any figure PDF
- Embedded PDF typeface check: Times New Roman present in every PDF
- Selected Matplotlib typeface: Times New Roman

The complete per-figure results are recorded in `artifact_validation.csv`.

## Visual Inspection

A contact-sheet review and targeted full-size review were performed after the 150 dpi smoke render and before the definitive 1200 dpi render. The review covered label collisions, clipped text, legend placement, inset readability, axis coverage, annotation placement, and consistency across panels. Five revisions were made before final export: Figure 4.7-1 reference labels, Figure 4.7-4 mode annotation, Figure 4.7-7 tail coverage, Figure 4.7-12 labels/note, and Figure 4.7-17 tiny-segment callouts. The definitive render uses those reviewed layouts.

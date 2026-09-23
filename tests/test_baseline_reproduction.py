import csv
import unittest
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]


class BaselineReproductionTests(unittest.TestCase):
    def test_generated_baseline_validation_all_passes(self):
        path = BASE / "outputs" / "Sensitivity_Analysis" / "Tables" / "Baseline_Validation.csv"
        self.assertTrue(path.exists())
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertGreaterEqual(len(rows), 10)
        self.assertTrue(all(row["Status"] == "PASS" for row in rows))

    def test_authoritative_input_hashes_match_verified_values(self):
        from sensitivity.model import load_authoritative_model
        model = load_authoritative_model()
        self.assertEqual(model.pert_hash, "7984b5b2e29928345772f0110ea1fa1c9ceb4121dc2e3aed4737112a98bc1f58")
        self.assertEqual(model.gert_hash, "dc34b00fcd3988146da0760ac18499eeca9d8596601c09445ca5d956c4ae6387")

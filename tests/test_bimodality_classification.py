import unittest

import numpy as np

from sensitivity.bimodality import classify_distribution


CONFIG = {
    "kde_grid_points": 512,
    "kde_min_bandwidth_days": 1.0,
    "mode_prominence_fraction": 0.05,
    "gmm_bic_clear_threshold": 10.0,
}


class BimodalityClassificationTests(unittest.TestCase):
    def test_separated_mixture_is_classified_bimodal(self):
        rng = np.random.default_rng(7)
        values = np.concatenate([rng.normal(10, 1, 4000), rng.normal(40, 2, 6000)])
        row, _ = classify_distribution(values, CONFIG)
        self.assertEqual(row["Classification"], "clearly bimodal")
        self.assertGreaterEqual(row["Meaningful_Mode_Count"], 2)

    def test_single_normal_is_not_clear_bimodal(self):
        rng = np.random.default_rng(8)
        values = rng.normal(20, 3, 10000)
        row, _ = classify_distribution(values, CONFIG)
        self.assertNotEqual(row["Classification"], "clearly bimodal")

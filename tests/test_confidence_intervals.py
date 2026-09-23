import unittest

import numpy as np

from sensitivity.statistics import bootstrap_quantile_intervals, mean_ci, wilson_interval


class ConfidenceIntervalTests(unittest.TestCase):
    def test_wilson_contains_observed_probability(self):
        low, high = wilson_interval(577, 1000)
        self.assertLessEqual(low, 0.577)
        self.assertGreaterEqual(high, 0.577)

    def test_mean_interval_is_ordered(self):
        values = np.arange(1, 101)
        se, low, high = mean_ci(values)
        self.assertGreater(se, 0)
        self.assertLess(low, values.mean())
        self.assertGreater(high, values.mean())

    def test_bootstrap_quantile_intervals_are_reproducible(self):
        values = np.repeat(np.arange(10), 50)
        first = bootstrap_quantile_intervals(values, resamples=1000, seed=123)
        second = bootstrap_quantile_intervals(values, resamples=1000, seed=123)
        self.assertEqual(first, second)
        self.assertLessEqual(first["p90"][0], first["p90"][1])

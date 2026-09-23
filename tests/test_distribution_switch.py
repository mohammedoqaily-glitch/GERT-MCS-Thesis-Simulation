import unittest

import numpy as np

from sensitivity.model import load_authoritative_model, result_signature, simulate_gert


class DistributionSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_authoritative_model()

    def test_distribution_switch_preserves_routes_for_same_draw_structure(self):
        beta = simulate_gert(self.model, 2000, 42, "beta_pert")
        triangular = simulate_gert(self.model, 2000, 42, "triangular")
        self.assertTrue(np.array_equal(beta.outcomes, triangular.outcomes))
        self.assertEqual(beta.route_counts, triangular.route_counts)
        self.assertFalse(np.array_equal(beta.totals, triangular.totals))

    def test_unsupported_distribution_fails(self):
        with self.assertRaises(ValueError):
            simulate_gert(self.model, 10, 42, "unsupported")

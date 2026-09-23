import unittest

from sensitivity.model import load_authoritative_model, result_signature, simulate_gert


class SeedReproducibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_authoritative_model()

    def test_same_seed_reproduces_exactly(self):
        first = simulate_gert(self.model, 2000, 303)
        second = simulate_gert(self.model, 2000, 303)
        self.assertEqual(result_signature(first), result_signature(second))

    def test_different_seed_changes_result(self):
        first = simulate_gert(self.model, 2000, 303)
        second = simulate_gert(self.model, 2000, 404)
        self.assertNotEqual(result_signature(first), result_signature(second))

    def test_every_run_has_terminal_or_separate_safety_outcome(self):
        result = simulate_gert(self.model, 5000, 42)
        self.assertTrue(set(result.outcomes.tolist()).issubset({-1, 0, 1}))
        self.assertEqual(int((result.outcomes < 0).sum()), 0)
